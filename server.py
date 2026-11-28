"""Ed Console web server: the levels loop, the bar writer, and the routes the screens read."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import AsyncGenerator, Callable, Collection, Iterable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Annotated, Any, Literal, NamedTuple, TypedDict

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

import live_market_plane as lmp
import time_et
from app.market_data.schwab.streaming import live_ui
from app.market_data.schwab.streaming.live_push import MARKET_CONTEXT, VOLATILITY_INDEX
from app.options.order_flow.state import rest_quotes, streamed_values
from app.options.order_flow.streaming import (
    FEED,
    select_flow_contract,
    start_order_flow_stream,
    stop_order_flow_stream,
    streamed_bars,
    watchlist_request,
)
from calc.liquidity_value_engine import (
    bars_from_candles,
    levels_start,
)
from calc.math_exposure_core import (
    Bucket,
    bucket_metric,
    merge_exposure_books,
    overlay_streamed_contract_fields,
    strike_oi_legs,
    strike_volume_legs,
)
from calc.micro_structure import Candle
from calc.terrain_engine import (
    OPTION_LEVELS,
    SCOPES,
    Book,
    ExpiryKey,
    TerrainSnapshot,
    compute_terrain,
    total_gamma_record,
)
from calc.terrain_read import crossed
from calibration.complete_chain_capture import CAPTURE_BASIS, StoredCapture
from db import LevelCrossEvent, StoredCross, get_db, stored_rows
from db_authority import canonical_db_path
from instrument_identity import display_symbol, ticker_storage_key, vendor_option_root
from numeric_contract import (
    fixed_text,
    schwab_count,
    schwab_number,
    schwab_time_ms,
)
from open_gap import (
    open_gap_record,
)
from option_contract import NO_GREEKS, OptionContract, Streamed
from push import bars as push_bars
from push import book as push_book
from push import book_heatmap as push_book_heatmap
from push import chain as push_chain
from push import confluence as push_confluence
from push import contract as push_contract
from push import desk as push_desk
from push import experimental as push_experimental
from push import expiries as push_expiries
from push import levels as push_levels
from push import liquidity as push_liquidity
from push import option_book as push_option_book
from push import strike_bars as push_strike_bars
from push import strikes as push_strikes
from push import surface as push_surface
from push import tape as push_tape
from push import terrain as push_terrain
from push.asked import tf_asked
from push.spot import SPOT_SOURCE_NONE, SPOT_SOURCE_PLANE, resolve_spot
from push.verdict import (
    terrain_cache_get,
)
from state import bar_store, capture_store, cross_store, level_store
from state.level_store import (
    CallPutTotal,
    CellContracts,
    CellStream,
    GammaSurface,
    GridCell,
    ProjectedCell,
    ProjectedSurface,
    PublishedLevels,
    StreamLegs,
    SurfaceColumn,
    published_levels,
)
from state.price_level_store import (
    canonical_price_level_snapshot,
    materialize_price_level_snapshot,
)
from stream_spine import CAPTURE_HELD, CAPTURE_STORED, StoredFirst, cross_ids
from time_et import (
    ET,
    ct_label,
    et_date_str_from_ts_utc,
    et_stamp,
    market_session_date,
    option_close_product,
    option_market_open,
    options_closed_at,
    options_open,
    record_markets,
    session_label,
    sessions,
    valuation_instant,
)

# ── App directory = same folder as this file ─────────────────────────────────
APP_DIR = str(Path(__file__).parent.resolve())


# Its lines go to the program's one log (capture._start_log: the day's file and the window).
log = logging.getLogger("ed_server")


#: where the bars come from, named in every level's provenance
BAR_SOURCE = "Schwab /pricehistory 1-minute bars and CHART_EQUITY"


def _schwab_bar(
    start_ms: object, o: object, h: object, lo: object, c: object, volume: object
) -> Candle | None:
    """One Schwab CHART_EQUITY bar as a Candle, each field as Schwab sent it.

    None when its start or a price is not a number (AGENTS.md rule 2: absent, -999, text, NaN or
    infinity), or its start is no time (schwab_time_ms). A volume that is not a number, or
    negative, is absent.
    """
    start, o, h, lo, c = (
        schwab_time_ms(start_ms),
        schwab_number(o),
        schwab_number(h),
        schwab_number(lo),
        schwab_number(c),
    )
    if start is None or o is None or h is None or lo is None or c is None:
        return None
    return Candle(start / 1000.0, o, h, lo, c, schwab_count(volume))


def _take_open_gap(tk: str, series: str, sent: list[dict[str, Any]]) -> None:
    """Take one of the open-gap record's two answers.

    Each answer is held (state.bar_store) until both are in, then the record is computed from the
    newest of each. A record that changed is pushed to the pages showing that ticker (no bars or
    candles changed, so no levels are built).
    """
    if bar_store.take_open_gap_answer(tk, series, sent) and bar_store.hold_open_gap(
        tk, open_gap_record(*bar_store.open_gap_answers(tk))
    ):
        live_ui.changed(app.state, tk, "experimental")


def _write_price_history(msg: dict[str, Any]) -> str | None:
    """One series of a ticker's price history as Schwab's /pricehistory answered it.

    Pushed by the capture daemon: its 1-minute bars into the ticker's bars, only the minutes not
    held taken (a held minute, a streamed bar or an earlier history's, stands over Schwab's
    history of it); any other series replacing the one held. A candle without a valid field is
    not kept. The ticker when the bars or candles it holds changed, else None. Runs on the bar
    writer, the one writer of state.bar_store.
    """
    tk = ticker_storage_key(msg["symbol"])
    sent = msg["answer"]["candles"]
    if msg["series"] in bar_store.OPEN_GAP_SERIES:  # no bars or candles: the open-gap record's
        _take_open_gap(tk, msg["series"], sent)
        return None
    if msg["series"] not in {
        *bar_store.MINUTE_SERIES,
        *push_bars.SCHWAB_SERIES.values(),
        "1w",
        "1mo",
    }:
        return None  # a series no screen reads: the daemon records it, the console holds none
    if msg["series"] not in bar_store.MINUTE_SERIES:
        candles = [
            b
            for b in (
                _schwab_bar(
                    c.get("datetime"),
                    c.get("open"),
                    c.get("high"),
                    c.get("low"),
                    c.get("close"),
                    c.get("volume"),
                )
                for c in sent
            )
            if b is not None
        ]
        return tk if bar_store.put_series(tk, msg["series"], candles) else None
    held_minutes = bar_store.held_minutes(tk)
    taken: dict[float, Candle] = {}
    for c in sent:
        start = schwab_time_ms(c.get("datetime"))
        if start is None or start / 1000.0 in held_minutes:
            continue
        b = _schwab_bar(
            start, c.get("open"), c.get("high"), c.get("low"), c.get("close"), c.get("volume")
        )
        if b is not None:
            taken[b.ts] = b
    return tk if bar_store.take_history(tk, list(taken.values())) else None


def _write_streamed_bar(msg: dict[str, Any]) -> bool:
    """Keep one streamed 1-minute bar with the ticker's bars.

    The bar is Schwab CHART_EQUITY, pushed by the capture daemon, which records it. False when it
    lacks a valid field (then it is not kept).
    """
    bar = _schwab_bar(
        msg["bar_start_ms"],
        msg["open"],
        msg["high"],
        msg["low"],
        msg["close"],
        msg["volume"],
    )
    if bar is None:
        log.warning("streamed bar for %s lacks a valid field, not kept: %s", msg["symbol"], msg)
        return False
    tk = ticker_storage_key(msg["symbol"])
    bar_store.keep_bar(tk, bar)  # what every live reader reads
    live_ui.changed(app.state, tk, *BARS_PANELS)
    return True


def _write_streamed_bars(msgs: list[dict[str, Any]], now: datetime) -> None:
    """Write streamed bars and price histories, then build the price levels of each ticker.

    A price history is a message with a `series`. The levels are built for each ticker whose
    1-minute bars were written, for the market's session at `now`: everything that arrived
    together is written before any level is built (a minute's bars for the whole watchlist arrive
    together).
    """
    written: list[str] = []
    for msg in msgs:
        try:
            if "series" in msg:
                tk = _write_price_history(msg)
                if tk is not None:  # 1-minute bars or daily candles: both are the levels' inputs
                    live_ui.changed(app.state, ticker_storage_key(tk), *BARS_PANELS)
                    written.append(tk)
            elif _write_streamed_bar(msg):
                written.append(msg["symbol"])
        except Exception as e:  # logged; the next bar is still written
            log.warning(
                "streamed bar or price history for %s not written: %s",
                msg["symbol"],
                e,
                exc_info=True,
            )
    for tk in dict.fromkeys(written):
        _publish_price_levels(tk, now)


def _bar_writer() -> None:
    """Run the bar writer, the one writer of the bars and candles in memory (state.bar_store).

    It writes every streamed bar and price history the capture daemon pushes, as it arrives, with
    those already waiting behind it. Ends at stop_bar_writer's None, once everything queued before
    it is written.
    """
    while True:
        msgs = [streamed_bars.get()]
        while not streamed_bars.empty():
            msgs.append(streamed_bars.get_nowait())
        _write_streamed_bars(
            [m for m in msgs if m is not None], datetime.fromtimestamp(time_et.now(), ET)
        )
        if None in msgs:
            return


@dataclass
class Services:
    """The program's services beside its pages (start_services and stop_services own them).

    The bar writer's thread, and the running levels loop's stop: its own for each start, so a
    stopped loop never takes a later start for its own; None while no loop runs.
    """

    bar_writer: threading.Thread | None = None
    levels_stop: threading.Event | None = None


#: the program's one Services
SERVICES = Services()


def start_bar_writer() -> None:
    SERVICES.bar_writer = threading.Thread(target=_bar_writer, name="bar-writer", daemon=True)
    SERVICES.bar_writer.start()


def stop_bar_writer(thread: threading.Thread | None = None) -> None:
    """Write every bar already queued, then end the bar writer (`thread`: the one started)."""
    thread = thread or SERVICES.bar_writer
    if thread is None:
        return
    streamed_bars.put(None)
    thread.join(timeout=10.0)


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────


def start_services() -> None:
    """Start the program's services beside its pages (capture.serve_console, the one start).

    The recorded market sessions first, so everything priced from here on has them (the daemon's
    answers then replace them); then the levels loop (the stored levels at startup, then the
    status line and the price levels; the chains arrive from the daemon, _on_chain) and the bar
    writer, its own always-on service, never a side effect of rendering.
    """
    _load_stored_sessions(canonical_db_path())
    start_terrain_loop()
    start_bar_writer()


def stop_services() -> None:
    """Stop the levels loop and the bar writer (it waits up to 10 s for the bars queued)."""
    stop_terrain_loop()
    stop_bar_writer()


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Run the daemon's feed while the pages are served.

    The live feed from the capture daemon (the only Schwab client): every streamed equity quote
    and option greeks/OI/volume quote -> _on_stream_tick, which reprices a viewed ticker; every
    chain the daemon fetched -> _on_chain, which prices it.
    """
    start_order_flow_stream(**FEED_CALLBACKS)
    yield
    # the program's one stop (capture.run) ends the pages with everything else
    stop_order_flow_stream()


app = FastAPI(title="Ed Console API", version="1.0", lifespan=_app_lifespan)
#: the price server the page's socket serves while the program serves prices
#: (live_ui.serve_live_ui), None before and after
app.state.prices = None


class _RevalidateStaticFiles(StaticFiles):
    """StaticFiles sends no Cache-Control at all, leaving freshness to each browser's own heuristic.

    The heuristic is commonly ~10% of Last-Modified age, RFC 7234. MEASURED: after a code change
    and a server restart, a browser served a stale ed-gamma.js across THREE separate full
    navigations with zero requests reaching this server for that file -- staleness a `curl` or a
    direct no-store fetch never reveals. `no-cache` forces revalidation on every load (the
    existing ETag/Last-Modified still make an unchanged file a cheap 304, so this costs nothing
    beyond a round trip) instead of trusting a heuristic a shipped fix cannot control.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


static_dir = Path(APP_DIR) / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", _RevalidateStaticFiles(directory=str(static_dir)), name="static")


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

#: the scope control's words, one per calc.terrain_engine.SCOPES
SCOPE_LABELS = {"auto": "Auto", "wider": "Wider", "all": "All available"}


#: the page's price socket, on the program's own port (live_ui.page_socket)
app.add_api_websocket_route("/ws", live_ui.page_socket)


def _with_page_settings(html: str) -> str:
    """Tell the page its market-context symbols, strike-window scopes and streaming-state words.

    The market-context symbols it always asks for are live_push.MARKET_CONTEXT, each with its
    display name and whether it is the volatility index (live_push.VOLATILITY_INDEX), which the
    header draws first of them on every page and the Desk's Volatility card shows; the
    scopes its strike windows take are calc.terrain_engine.SCOPES, each with its word; the
    words for each streaming state are STREAM_WORDS; and the words for the states only the page
    can see, its own connection to the program and the viewer's expiry choice, are PAGE_WORDS. A
    page without a setting's empty meta is refused, never served without it.
    """
    for name, value in (
        (
            "ed-market-context",
            [
                {"key": k, "display": display_symbol(k), "volatility": k == VOLATILITY_INDEX}
                for k in MARKET_CONTEXT
            ],
        ),
        ("ed-scopes", [{"key": s, "label": SCOPE_LABELS[s]} for s in SCOPES]),
        ("ed-stream-words", STREAM_WORDS),
        ("ed-page-words", PAGE_WORDS),
    ):
        empty = f'<meta name="{name}" content="" />'
        if empty not in html:
            raise ValueError(f"the page has no {empty}")
        html = html.replace(
            empty, f'<meta name="{name}" content="{html_escape(json.dumps(value))}" />', 1
        )
    return html


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    html_path = static_dir / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>static/index.html not found</h1>", status_code=404)
    # "/" is never cached: a cached page would run stale page code after an edit
    return HTMLResponse(
        content=_with_page_settings(html_path.read_text(encoding="utf-8")),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """Browsers request this automatically; without a route they log 404 (harmless but noisy)."""
    return Response(status_code=204)


# ── THE LEVELS (from the chains the capture daemon fetches) ──────────────────


def _gamma_surface_wanted(tk: str) -> bool:
    """Tell whether the ticker is viewed: the heatmap's REQUESTED state.

    Viewed: a page has the ticker selected on its socket (live_ui.selected), on any workspace,
    for as long as it stays open. Every watchlist ticker's chain is fetched and priced alike; a
    viewed one is repriced on its streamed ticks as well (_on_stream_tick).
    """
    return tk in live_ui.selected(app.state)


#: Per-ticker revision of PublishedLevels.gamma_surface, bumped on every publication and restamp
#: (the page redraws its table for a new one).
#: A ticker's first counts on from its time in milliseconds (`now`), so a page that drew a
#: publication of the console before a restart sees every publication of the new one as new.
_gamma_surface_seq: dict[str, int] = {}


def _next_gamma_surface_seq(tk: str, now: float) -> int:
    n = _gamma_surface_seq.get(tk, int(now * 1000)) + 1
    _gamma_surface_seq[tk] = n
    return n


def _overlaid_symbols(pre: list[OptionContract], post: list[OptionContract]) -> list[str]:
    """Return the contracts `post` holds as new records of `pre`'s.

    overlay_streamed_contract_fields passes an unchanged contract through as the same record.
    """
    return [new.symbol for orig, new in zip(pre, post) if new is not orig and new.symbol]


_STREAM_STATE_ORDER = ("stale", "pending")
#: a cell's two legs, by their key in its contracts and in its stream state
_SIDES: tuple[Literal["call"], Literal["put"]] = ("call", "put")


def _stream_state_of(states: list[str]) -> str:
    """One stream state for a set of leg (or cell) states.

    Live when all are live, partial when some are, else the first of _STREAM_STATE_ORDER present,
    else unavailable.
    """
    if not states:
        return "unavailable"
    if all(s == "live" for s in states):
        return "live"
    if any(s in ("live", "partial") for s in states):
        return "partial"
    return next((o for o in _STREAM_STATE_ORDER if o in states), "unavailable")


def _stream_cell_title(state: str, ts_recv: float | None) -> str | None:
    """Return the tooltip for a cell that is not live.

    The served word and the time its oldest leg was last received, in Central Time. A live cell
    has no tooltip. No age: the stamp stands until the feed next changes (hours, after the
    close), and an age written at the stamp would be read long after it stopped being true.
    """
    if state == "live":
        return None
    word = STREAM_WORDS["cell"].get(state)
    if word is None:
        return None
    return word if ts_recv is None else f"{word} · {ct_label(ts_recv)}"


def _stamp_gamma_surface_cell_stream_state(
    grid: Sequence[ProjectedCell],
    expirations: list[SurfaceColumn],
    streamed: dict[str, Streamed],
    overlay_symbols: Collection[str],
    held_symbols: Collection[str],
) -> tuple[list[GridCell], dict[str, str]]:
    """Return a grid's cells with their per-leg (call/put) and per-cell STREAM state.

    With them, each expiry column's state from its cells' (the column header's status). It never
    touches a cell's computed value (project_gamma_surface is the one exposure computation); it
    says whether a streamed Schwab value backs it now.

    `streamed`: the streamed values of the contracts the daemon's latest beat holds of this
    ticker (order_flow.state.streamed_values); `overlay_symbols`: those the feed is delivering now
    (live_market_plane.live_on, the one live rule); `held_symbols`: every contract on that
    beat, ticked or not (live_market_plane.held_option_symbols). A missing beat is not live: those
    cells keep the last streamed value and are not live. Each leg carries the time it was last
    received (`ts_recv`), never an age: the stamp stands until the feed next changes.
      'live'         — the feed is delivering this symbol now.
      'stale'        — the symbol has streamed but the feed is not delivering it now.
      'pending'      — the daemon holds the symbol and no tick has landed yet.
      'unavailable'  — a symbol the daemon does not stream.

    Cell aggregate, over the legs that exist for this strike/expiry: live when all are live,
    partial when some are, else the first of stale > pending present, else unavailable. A strike
    the expiry does not list has no contract and so no state: its place in `stream` is None.
    """
    cells: list[GridCell] = []
    by_column: list[list[str]] = [[] for _ in expirations]  # each column's cell states
    for cell in grid:
        state_row: list[CellStream | None] = []
        # {call, put} for every column (_gamma_surface_cell_fields)
        for j, pair in enumerate(cell["contracts"]):
            legs: StreamLegs = {}
            leg_states: list[str] = []
            received: list[float] = []
            for side in _SIDES:
                sym = pair[side]
                if not sym:
                    continue
                greeks = streamed[sym].greeks if sym in streamed else NO_GREEKS
                if sym in overlay_symbols:
                    leg_state = "live"
                elif sym in streamed:
                    leg_state = "stale"
                elif sym in held_symbols:
                    leg_state = "pending"
                else:
                    leg_state = "unavailable"
                leg_states.append(leg_state)
                ts_recv = greeks.newest_ts()
                if ts_recv is not None:
                    received.append(ts_recv)
                legs[side] = {"symbol": sym, "state": leg_state, "ts_recv": ts_recv}
            if not leg_states:  # the expiry lists no contract at this strike: nothing streams
                state_row.append(None)
                continue
            state = _stream_state_of(leg_states)
            title = _stream_cell_title(state, min(received) if received else None)
            state_row.append({**legs, "state": state, "title": title})
            by_column[j].append(state)
        cells.append({**cell, "stream": state_row})
    return cells, {
        e["expiry"]: _stream_state_of(states)
        for e, states in zip(expirations, by_column, strict=True)
    }


#: The words for each streaming state (_stream_state_of): a heatmap cell's tooltip, and an expiry
#: column's; served in the page (meta ed-stream-words)
STREAM_WORDS = {
    "cell": {
        "partial": "one side of this cell is streaming",
        "stale": "this cell has stopped streaming",
        "pending": "streaming requested, no update yet",
        "unavailable": "not streaming",
    },
    "column": {
        "live": "streaming",
        "partial": "partly streaming",
        "stale": "stopped streaming",
        "pending": "streaming requested",
        "unavailable": "not streaming",
    },
}

#: The words for the states only the page can see, its own connection to the program, served in
#: the page (meta ed-page-words): the page says them in this one wording and holds none of its
#: own (AGENTS.md rule 4). A ticker just asked for, its row on its way; the push silent; no row
#: yet for a symbol the page shows; "{name}" is the symbol's served display name. No symbol
#: chosen; the daemon's beat carrying no status; what the operator typed not a symbol's form
#: ("{typed}"); a watchlist change on its way, or its request failing before any answer
#: ("{ticker}", "{why}": the failure as the browser reports it). No expiry chosen: all of them,
#: in the selector and, short, in the context line; on the Chain view, the expiry the program
#: sends by default. The expiry chosen not in the surface, and what the viewer can do; no strike
#: chosen on the matrix; the strikes panned away from the price ("{strike}": the served centre
#: strike). A panel the page has asked for and not yet received (the chart's bars,
#: "{name}" at "{tf}", its timeframe's label; the event queue's), one whose answer has nothing to
#: draw, one the program could not produce
#: ("{what}": the panel's name; "{why}": the program's reason, as served), and one the page
#: could not draw.
PAGE_WORDS = {
    "waiting": "WAITING",
    "no_push_yet": "no push yet",
    "offline": "OFFLINE",
    "push_down": "live push down",
    "no_row_yet": "no price row yet",
    "no_row_yet_symbol": "no price row yet for this symbol",
    "waiting_stream": "waiting for the {name} stream",
    "choose_symbol": "CHOOSE A SYMBOL",
    "no_symbol": "NO SYMBOL",
    "no_contract": "NONE",
    "choose_contract": "Select a Call or Put contract in Chain.",
    "all_expiries": "All Expirations",
    "all_expiries_short": "All",
    "default_expiry": "Default Expiry",
    "missing_expiry_hint": "not in this surface — choose another expiry, or All Expirations",
    "choose_strike": "Click a strike for its readings.",
    "panned_to": "Panned to {strike} · double-click the strikes to follow the price",
    "daemon_silent": "the capture daemon is not reporting",
    "session_no_status": "session unknown: the daemon sent no status",
    "session_push_down": "session unknown: the console push is down",
    "watchlist_empty": "Watchlist is empty — use + Add symbol below",
    "not_a_symbol": 'Not a valid symbol: "{typed}"',
    "checking": "Checking {ticker} with Schwab…",
    "not_added": "{ticker} is not added: {why}",
    "not_removed": "{ticker} is not removed: {why}",
    "loading": "LOADING",
    "loading_text": "loading…",
    "loading_chart": "Loading {name} · {tf}…",
    "loading_events": "Loading {name} events…",
    "unavailable": "UNAVAILABLE",
    "failed": "FAILED",
    "not_produced": "the program could not produce the {what}",
    "not_produced_why": "the program could not produce the {what}: {why}",
    "not_drawn": "the page could not draw the answer of {what}",
}

#: per ticker, the beat its open surface was last stamped from (_feed_stamp_key: the socket open,
#: the surface's contracts the daemon holds, the option market open), by its pricing
#: (_publish_levels) or a restamp, so a beat that changes none of them for a surface does not
#: restamp or republish it
_last_feed_stamp: dict[str, tuple[bool, frozenset[str], bool | None]] = {}


def restamp_off_the_loop() -> None:
    """Take the daemon's beat (the feed's callback, on the event loop) to the pricing thread.

    There each beat takes the Recorder's answers for the level crosses it did not commit in
    their wait (_hold_answered_crosses), then restamps the surfaces. The surfaces are stamped
    where they are priced (chain_pricing), never on the event loop, whose one reader takes
    Schwab's stream (docs/DATA_FLOW.md §4). The restamp is at the instant it runs, as a pricing
    is (_price_waiting_chain): one that waited behind a pricing is judged by the beat of then,
    not by the time it was queued.
    """
    chain_pricing.submit(_on_beat).add_done_callback(_pricing_job_ended)


def _on_beat() -> None:
    """Run the daemon's beat on the pricing thread (restamp_off_the_loop)."""
    _hold_answered_crosses()
    restamp_open_surfaces(time_et.now())


def _pricing_job_ended(done: Future[None]) -> None:
    """Log a pricing-thread job (a beat's, a price's crosses) that ended on an error.

    With its traceback, which names the job; the next beat or price runs its own.
    """
    if done.exception() is not None:
        e = done.exception()
        log.warning("a job of the pricing thread failed: %s", e, exc_info=e)


#: the page's socket panels (PAGE_PANELS) read from the published levels and the live price
LEVELS_PANELS = (
    "vanna",
    "charm",
    "terrain",
    "strikes",
    "surface",
    "chain",
    "levels",
    "confluence",
    "contract",
    "option_book",
    "desk",
    "liquidity",
)


def _levels_changed(tk: str) -> None:
    """Tell the pages on `tk` (its key) that its levels changed: the socket sends them again."""
    live_ui.changed(app.state, tk, *LEVELS_PANELS)


def flow_changed(sym: str) -> None:
    """Tell the pages on `sym`'s ticker that its quote or book changed.

    `sym` is Schwab's symbol: the equity (FLOW_PANELS), or an option contract of a chain the
    console holds (OPTION_PANELS: an option's quote or book moves no equity panel).
    """
    tk = _tick_ticker(sym)
    if tk:
        live_ui.changed(app.state, tk, *(OPTION_PANELS if vendor_option_root(sym) else FLOW_PANELS))


def _surface_symbols(surface: GammaSurface) -> list[str]:
    """Return every contract a heatmap's cells name."""
    return [
        s
        for cell in surface["cells"]
        for pair in cell["contracts"]
        for s in (pair["call"], pair["put"])
        if s
    ]


def _feed_stamp_key(
    feed: lmp.FeedNow, symbols: frozenset[str], now: float
) -> tuple[bool, frozenset[str], bool | None]:
    """Return what a heatmap's stamp takes from one beat (`feed`) at `now`.

    That is whether Schwab's socket is open, which of the heatmap's `symbols` the daemon holds on
    LEVELONE_OPTIONS, and whether the option market is open.
    """
    socket_open = lmp.feed_up(feed)
    held: frozenset[str] = (
        feed.held.get("LEVELONE_OPTIONS", frozenset()) if socket_open else frozenset()
    )
    return (
        socket_open,
        held.intersection(symbols),
        options_open(datetime.fromtimestamp(now, ET)),
    )


def restamp_open_surfaces(now: float) -> None:
    """Mark every cached heatmap from the daemon's heartbeat at `now`, without repricing.

    The last streamed gamma stays. A contract is live by the one live rule on its ticker's own
    option market (live_market_plane.live_symbols): a socket that has closed, a contract the daemon
    no longer holds and an option market that has closed are not live. A surface is restamped,
    and the page told, only when that changes for its own contracts. It runs on the pricing
    thread, the one writer of the levels.
    """
    feed = lmp.feed_now(now)
    for tk, levels in level_store.every_published():
        surface = levels.gamma_surface
        if surface is None:  # this ticker's levels hold no surface (no price or no book)
            continue
        symbols = levels.surface_symbols
        key = _feed_stamp_key(feed, symbols, now)
        if _last_feed_stamp.get(tk) == key:
            continue
        _last_feed_stamp[tk] = key
        held = key[1]
        streamed = streamed_values(symbols)
        live = lmp.live_symbols(feed, streamed, "LEVELONE_OPTIONS", now)
        cells, by_expiry = _stamp_gamma_surface_cell_stream_state(
            surface["cells"], surface["expirations"], streamed, live, held
        )
        stamped: GammaSurface = {
            **surface,
            "cells": cells,
            "stream_by_expiry": by_expiry,
            "surface_seq": _next_gamma_surface_seq(tk, now),
        }
        level_store.publish(tk, replace(levels, gamma_surface=stamped))
        _levels_changed(tk)


def _closed_since(now: datetime, product: str) -> datetime | None:
    """Return the ticker's last option close while its option market is closed at `now`.

    None while it is open: in its regular window, or in an option window Schwab sent before its
    market has closed that day (the pre-market, whose values are live). None
    too while Schwab's /markets answer for today is not held.
    """
    if option_market_open(now, product) is not False:
        return None
    closed = options_closed_at(now, product)
    if options_open(now) and (closed is None or closed.date() < now.astimezone(ET).date()):
        return None
    return closed


def _close_capture(tk: str, closed: datetime) -> list[StoredCapture] | None:
    """Return the ticker's stored close values, or None when none is stored.

    Its two newest market days' captures, when the newest was taken at or after `closed`.
    """
    stored = capture_store.captures(get_db().db_path, tk)
    return stored if stored and stored[0].ts_utc >= closed.timestamp() else None


def _priced_at(
    tk: str,
    chain_spot: tuple[float | None, float | None],
    kept: PublishedLevels | None,
    now: datetime,
) -> tuple[float | None, str, float | None]:
    """Return the price a publication of `tk`'s levels is computed at: (price, source, time).

    A chain's spot, a stored capture's or a delivered chain's: Schwab's LAST_PRICE when the
    chain was complete, with its trade time (SPOT_SOURCE_NONE when the daemon held no price,
    as a capture stored without one reads); for a streamed tick (`kept`: the levels it
    reprices), the live price, newer than any the levels hold, or the last one published while
    Schwab has sent this program none.
    """
    if kept is None:
        source = SPOT_SOURCE_NONE if chain_spot[0] is None else SPOT_SOURCE_PLANE
        return chain_spot[0], source, chain_spot[1]
    live = resolve_spot(tk, now=now.timestamp())
    return kept.priced_at if live[0] is None else live


def _publication_spot(
    previous: PublishedLevels | None,
    capture: StoredCapture | None,
    valued_at: datetime,
    priced_at: tuple[float | None, str, float | None],
    now: datetime,
) -> tuple[float | None, str, float | None]:
    """Return the price a publication is computed at: (price, source, time).

    Once the window of a chain that is not a capture has ended, the spot already published is
    the close, and a later print is not; otherwise `priced_at`.
    """
    if (
        capture is None
        and valued_at < now
        and previous is not None
        and previous.snap.spot is not None
    ):
        return previous.snap.spot, previous.spot_source, previous.spot_as_of_ts_utc
    return priced_at


class _Priced(NamedTuple):
    """A chain priced with each contract's newest values, and what the pricing read."""

    priced: list[OptionContract]
    #: when each value newer than the chain's was received
    received: list[float]
    #: one read of the heartbeat, the streamed values, which of them are live, which are held
    feed: lmp.FeedNow
    streamed: dict[str, Streamed]
    feed_live: set[str]
    held: set[str]


def _price_chain_values(
    chain: list[OptionContract],
    listed: Collection[str],
    fetched_ts: float,
    window_open: bool,
    now: datetime,
) -> _Priced:
    """Return `chain` priced: inside the window each contract's newest values; else as sent.

    The newest values are the stream's, or its /quotes answer's when that was received since this
    chain began; the close values are the chain as sent. The cell stamp says whether that stream
    is live.
    """
    # one read of the heartbeat: pricing and the cell stamp share it
    feed = lmp.feed_now(now.timestamp())
    held = set(lmp.held_option_symbols(listed, now.timestamp(), feed))
    streamed = streamed_values(held)
    feed_live = lmp.live_symbols(feed, streamed, "LEVELONE_OPTIONS", now.timestamp())
    quoted = rest_quotes(listed, fetched_ts)
    priced = (
        overlay_streamed_contract_fields(chain, streamed, held, quoted) if window_open else chain
    )
    # the contracts given newer values than the chain's
    live_syms = _overlaid_symbols(chain, priced)
    pushed_ts = [
        ts
        for s in live_syms
        if s in streamed and (ts := streamed[s].greeks.newest_ts()) is not None
    ]
    # a contract the stream does not hold was given its /quotes answer: that answer's receive time
    quoted_ts = [quoted[s][0] for s in live_syms if s not in held]
    return _Priced(priced, pushed_ts + quoted_ts, feed, streamed, feed_live, held)


def _prior(
    tk: str,
    previous: PublishedLevels | None,
    kept: PublishedLevels | None,
    captures: list[StoredCapture] | None,
    fetched_ts: float,
) -> tuple[tuple[float | None, str], TerrainSnapshot | None]:
    """Return the key of the stored captures read and the prior market day's levels.

    The prior market day's close capture (_prior_day) changes only with a new capture or a new
    chain day: its levels are computed then, once, for all readers.
    """
    captures_key = (
        (capture_store.newest_ts(get_db().db_path, tk), et_date_str_from_ts_utc(fetched_ts))
        if kept is None
        else kept.captures_key
    )
    stored = captures if captures is not None else capture_store.captures(get_db().db_path, tk)
    prior_capture = _prior_capture(stored, fetched_ts)
    if previous is not None and previous.captures_key == captures_key:
        return captures_key, previous.prior_day
    return captures_key, None if prior_capture is None else _prior_day(tk, prior_capture)


def _published_surface(
    tk: str,
    p: _Priced,
    snap: TerrainSnapshot,
    now: datetime,
) -> tuple[GammaSurface, frozenset[str]]:
    """Return the gamma surface of the priced chain (`snap`'s books), its cells stamped.

    With it, every contract its cells name (_surface_symbols), read once here.
    """
    projected = project_gamma_surface(p.priced, snap.books)
    cells, by_expiry = _stamp_gamma_surface_cell_stream_state(
        projected["cells"], projected["expirations"], p.streamed, p.feed_live, p.held
    )
    surface: GammaSurface = {
        "expirations": projected["expirations"],
        "strikes": projected["strikes"],
        "cells": cells,
        "contracts_total": projected["contracts_total"],
        "contracts_used": projected["contracts_used"],
        "stream_by_expiry": by_expiry,
        "surface_seq": _next_gamma_surface_seq(tk, now.timestamp()),
    }
    symbols = frozenset(_surface_symbols(surface))
    # a later beat that differs from this one restamps it (restamp_open_surfaces)
    _last_feed_stamp[tk] = _feed_stamp_key(p.feed, symbols, now.timestamp())
    return surface, symbols


def _publish_levels(
    tk: str,
    chain: list[OptionContract] | None = None,
    fetched_ts: float | None = None,
    *,
    chain_spot: tuple[float | None, float | None] = (None, None),
    captures: list[StoredCapture] | None = None,
    now: datetime,
) -> TerrainSnapshot | None:
    """Produce a ticker's levels, per-strike rows and gamma-surface grid: THE producer of them.

    Prices the chain once (_price_chain_values) and publishes all three together, so every screen
    shows one computation; called only on the one pricing thread (_price_chain). A delivered chain
    comes with its spot (`chain_spot`: Schwab's LAST_PRICE when it was complete, and its trade
    time; (None, None) with none); a tick passes no chain, and the kept one is repriced at the
    live price with every value received since. `captures` (startup and a closed market, DATA_FLOW
    decision 7): the two newest market days' stored captures; the newest is priced at its own
    chain spot and time (or its option close, once past), and the prior market day's is the
    prior day's levels (_prior). `now`: this publication's instant; a chain that is not a capture
    is valued then, or at the option close once passed, after which the spot already published
    stands (_publication_spot). Outside the window the close values (the first chain begun at or
    after the close, as Schwab sent it, a 0 included) stand until the next open. None: no chain.
    """
    previous = published_levels(tk)
    product = option_close_product(tk)
    closed = _closed_since(now, product)
    if closed is not None:
        # its market has closed: the last values computed while it was open stand, with their
        # time, until its next session; nothing is priced after the close
        if previous is not None:
            return previous.snap
        # nothing held from the session (a start after the close): Schwab's close values, a
        # contract settled at the close valued with no time left
        captures = captures or _close_capture(tk, closed)
    capture = captures[0] if captures else None
    if capture is not None:
        chain, fetched_ts = capture.contracts, capture.ts_utc
        chain_spot = capture.spot, capture.spot_ts
    # the levels a tick reprices (no chain passed in); None when a chain is priced
    kept = None
    if chain is None or fetched_ts is None:
        if previous is None or not previous.chain:
            return None
        kept, chain, fetched_ts = previous, previous.chain, previous.computed_ts_utc
    begun = datetime.fromtimestamp(fetched_ts, ET)
    valued_at = valuation_instant(begun if capture is not None else now, product)
    priced_at = _priced_at(tk, chain_spot, kept, now)
    spot, spot_source, spot_ts = _publication_spot(previous, capture, valued_at, priced_at, now)
    # the ticker's contracts are the ones Schwab listed in its newest chain
    listed = {c.symbol: c for c in chain if c.symbol} if kept is None else kept.contracts
    p = _price_chain_values(chain, listed, fetched_ts, closed is None, now)
    snap = compute_terrain(tk, p.priced, spot, now=valued_at, sessions=sessions())
    captures_key, prior = _prior(tk, previous, kept, captures, fetched_ts)
    surface, surface_symbols = None, frozenset[str]()
    if spot is not None and snap.books:
        surface, surface_symbols = _published_surface(tk, p, snap, now)
    levels_ts = max([fetched_ts, *p.received])
    levels = PublishedLevels(
        snap=snap,
        computed_ts_utc=fetched_ts,
        levels_ts_utc=levels_ts,
        chain_basis=capture.basis if capture is not None else CAPTURE_BASIS,
        spot_source=spot_source,
        spot_as_of_ts_utc=spot_ts,
        priced_at=priced_at,
        gamma_surface=surface,
        surface_symbols=surface_symbols,
        # every ticker keeps its chain and its heatmap, so a ticker put on screen shows at once
        chain=chain,
        priced_chain=p.priced,
        contracts=listed,
        prior_day=prior,
        captures_key=captures_key,
        total_gamma=total_gamma_record(previous and previous.total_gamma, snap, levels_ts),
    )
    level_store.publish(tk, levels)
    _levels_changed(tk)
    if kept is None:
        live_ui.changed(app.state, tk, *CHAIN_PANELS)
    return snap


#: the levels whose crossing by the price is recorded, each under its name in the one list
#: (OPTION_LEVELS): Gamma Flip, where the regime changes; Gamma Call and Gamma Put, the range the
#: industry reads; and Gamma Total (docs/DATA_FLOW.md, level crosses)
CROSS_LEVELS = tuple(
    level
    for level in OPTION_LEVELS
    if level[0] in ("gamma_flip", "call_wall", "put_wall", "absolute_gamma_strike")
)


#: ticker -> the live price at its last streamed equity quote: the price before the next one (a
#: cross needs both, and the price row holds only the newest); read and written on the event loop
_last_tick_spot: dict[str, float | None] = {}


def _level_crosses_at(
    published: TerrainSnapshot, before: float | None, spot: float | None
) -> list[tuple[float, str, str]]:
    """(level value, level name, direction) for each `published` level the price crossed.

    Going from `before` to `spot` (terrain_read.crossed).
    """
    return [
        (getattr(published, k), name, side)
        for k, name in CROSS_LEVELS
        if (side := crossed(getattr(published, k), before, spot)) is not None
    ]


#: how long the pricing thread waits for the Recorder to commit a price's crosses (store first),
#: as the chain sweep waits for a capture's (chain_sweep.CAPTURE_WAIT_SEC)
CROSS_WAIT_SEC = 10.0


@dataclass(frozen=True, eq=False)
class _Crosses:
    """A price's level crosses handed to the Recorder (_log_level_crosses), with its answer."""

    tk: str
    spot: float
    crosses: list[tuple[float, str, str]]  # as _level_crosses_at found them, for the log
    events: list[LevelCrossEvent]
    stored: StoredFirst  # told once the Recorder commits them (CaptureWriter.store_crosses)


#: the prices' level crosses the Recorder did not commit in CROSS_WAIT_SEC, oldest first, kept
#: until it answers (_hold_answered_crosses); read and written on the pricing thread alone
_crosses_unanswered: list[_Crosses] = []


def _log_level_crosses(
    tk: str, spot: float, crosses: list[tuple[float, str, str]], now: float, now_text: str
) -> None:
    """Store the crosses _level_crosses_at found, hold them for live readers, tell the open pages.

    Every cross is stored as it happened, by the Recorder, the database's one writer, before it
    is held (store first: CaptureWriter.store_crosses). Runs on the pricing thread. Crosses the
    Recorder did not commit in CROSS_WAIT_SEC (held while the database refuses writes, and
    written once it takes them) are logged and kept until it answers (_hold_answered_crosses);
    refused, they are logged and not held.
    """
    events = [
        LevelCrossEvent(
            ticker=tk,
            ts_utc=now,
            ts_et=now_text,
            level_name=name,
            level_value=value,
            direction=side,
            spot_at_cross=spot,
            zone_before=None,
            zone_after=None,
            timeframe="1m",
        )
        for value, name, side in crosses
    ]
    daemon = FEED.daemon
    if daemon is None or daemon.writer is None:
        log.warning("level crosses of %s at %s not stored: no Recorder runs", tk, spot)
        return
    msg = {"ticker": tk, "ts_utc": now, "crosses": [asdict(e) for e in events]}
    handed = _Crosses(tk, spot, crosses, events, daemon.writer.store_crosses(msg))
    outcome = handed.stored.outcome(CROSS_WAIT_SEC)
    if outcome == CAPTURE_HELD:
        log.warning(
            "level crosses of %s at %s not committed by the Recorder in %g s: kept until it "
            "answers, shown once it commits them: %s",
            tk,
            spot,
            CROSS_WAIT_SEC,
            crosses,
        )
        _crosses_unanswered.append(handed)
    elif outcome == CAPTURE_STORED:
        _hold_crosses(handed)
    else:
        log.warning("level crosses of %s at %s not stored (%s): %s", tk, spot, outcome, crosses)


def _hold_crosses(handed: _Crosses) -> None:
    """Hold a price's crosses the Recorder committed for the live readers; tell the open pages."""
    ids = cross_ids(handed.stored)
    cross_store.add(
        handed.tk, [StoredCross(**asdict(e), cross_id=i) for e, i in zip(handed.events, ids)]
    )
    _levels_changed(handed.tk)


def _hold_answered_crosses() -> None:
    """Take the Recorder's answer for each price's crosses not committed in their wait.

    On the pricing thread, at each of the daemon's beats (restamp_off_the_loop). Committed, they
    are held as crosses committed in their wait are (_hold_crosses); refused, none is held. Each
    answer is logged. Those still unanswered stay kept: a Recorder that died answers none of
    them, and the console's next start reads what was written.
    """
    for handed in list(_crosses_unanswered):
        outcome = handed.stored.outcome()
        if outcome == CAPTURE_HELD:
            continue
        _crosses_unanswered.remove(handed)
        log.warning(
            "level crosses of %s at %s %s by the Recorder after their wait: %s",
            handed.tk,
            handed.spot,
            outcome,
            handed.crosses,
        )
        if outcome == CAPTURE_STORED:
            _hold_crosses(handed)


def _tick_ticker(sym: str) -> str | None:
    """Return the cached ticker a streamed symbol moves.

    The equity itself, or an option contract's underlying.
    """
    if not vendor_option_root(sym):
        return ticker_storage_key(sym)
    return level_store.listing_ticker(sym)


def _on_stream_tick(sym: str) -> None:
    """Take one tick of `sym`.

    Called by the live feed, on the event loop, for every streamed equity quote, every option
    quote carrying Greeks or volume, and every contract of a /quotes answer. An equity quote
    checks the ticker's levels for a cross at the live price (stored off the event loop); a
    ticker a page shows (_gamma_surface_wanted) is queued for a reprice with every value Schwab
    has sent, at most once a second (_reprice_from_tick; one waits per ticker, so the reprice
    that runs takes the newest). A ticker no page
    shows is priced by each chain the daemon delivers, and repriced when a page selects it
    (ticker_selected). Returns at once.
    """
    tk = _tick_ticker(sym)
    if tk and not vendor_option_root(sym):
        now = time_et.now()
        spot, _source, _ts = resolve_spot(tk, now=now)
        before, _last_tick_spot[tk] = _last_tick_spot.get(tk), spot
        published = published_levels(tk)
        # a cross needs the price before and now (terrain_read.crossed)
        if (
            published is not None
            and spot is not None
            and (crosses := _level_crosses_at(published.snap, before, spot))
        ):
            chain_pricing.submit(
                _log_level_crosses,
                tk,
                spot,
                crosses,
                now,
                et_stamp(now),
            ).add_done_callback(_pricing_job_ended)
    if tk and _gamma_surface_wanted(tk):
        _reprice_from_tick(tk)


#: the least time between two reprices a ticker's ticks queue (the operator's setting)
REPRICE_EVERY_SEC = 1.0
#: ticker -> when its ticks last queued a reprice (time_et.elapsed), and the one timer that
#: queues the next for a tick that came sooner
_repriced_at: dict[str, float] = {}
_reprice_timers: dict[str, threading.Timer] = {}
_reprice_lock = threading.Lock()


def _reprice_from_tick(tk: str) -> None:
    """Queue a reprice of `tk` for a tick of it, at most one each REPRICE_EVERY_SEC.

    A tick that comes that long after the last one queued does so at once. One that comes
    sooner starts the ticker's one timer for the rest of that time, so the newest values Schwab
    sent are priced when it ends and no tick is left unpriced.
    """
    with _reprice_lock:
        now = time_et.elapsed()
        wait = _repriced_at[tk] + REPRICE_EVERY_SEC - now if tk in _repriced_at else 0.0
        if wait > 0:
            if tk not in _reprice_timers:
                _arm_reprice(tk, wait)
            return
        _repriced_at[tk] = now
    _wait_to_price(tk, REPRICE)


def _arm_reprice(tk: str, wait: float) -> None:
    """Start `tk`'s one timer for `wait` seconds (the caller holds _reprice_lock)."""
    timer = threading.Timer(wait, _reprice_due, (tk,))
    timer.daemon = True
    _reprice_timers[tk] = timer
    timer.start()


def _reprice_due(tk: str) -> None:
    """Queue the reprice a tick of `tk` waited for (its timer), while a page still shows it.

    Windows counts a timed wait in clock ticks, so the timer can wake a fraction of a millisecond
    before its second by time_et.elapsed (Microsoft, Sleep: "the wait can be anywhere between one
    and two ticks"); woken before it, the timer waits out the rest.
    """
    with _reprice_lock:
        if tk not in _reprice_timers:  # dropped by the stop
            return
        now = time_et.elapsed()
        left = _repriced_at[tk] + REPRICE_EVERY_SEC - now
        if left > 0:
            _arm_reprice(tk, left)
            return
        del _reprice_timers[tk]
        _repriced_at[tk] = now
    if _gamma_surface_wanted(tk):
        _wait_to_price(tk, REPRICE)


def ticker_selected(tk: str) -> None:
    """Queue a reprice of `tk` (its key), which a page has just selected (live_ui)."""
    _wait_to_price(tk, REPRICE)


#: prices every ticker's levels, off the event loop, one at a time
chain_pricing = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chain-pricing")
#: what waits to be priced for a ticker: a chain the daemon DELIVERED, the ticker's STORED
#: captures (startup, for a ticker the daemon has not delivered yet), or a REPRICE of its held
#: chain (a page selecting the ticker, or a streamed tick of it or of one of its contracts while
#: a page shows it)
DELIVERED, STORED, REPRICE = "delivered", "stored", "reprice"
#: ticker -> (what, contracts, a chain's fetched time, the chain's spot): at most
#: one per ticker however far
#: pricing falls behind; a delivered chain replaces what waits, and whatever waits already prices
#: the newest ticks. Every pricing runs on the one pricing thread, so each ticker's chains are
#: priced in the order they were fetched.
_chains_waiting: dict[
    str,
    tuple[str, list[OptionContract] | None, float | None, tuple[float | None, float | None]],
] = {}
_chains_waiting_lock = threading.Lock()
#: the tickers the daemon has delivered a chain for since the console started: their stored
#: capture is older and is not priced as the book, unless it holds the close values
#: (_publish_levels)
_chains_delivered: set[str] = set()


def _on_chain(
    ticker: str,
    contracts: list[OptionContract] | None,
    ts: float,
    reason: str | None,
    spot: tuple[float | None, float | None] | None,
    capture: bool,
) -> None:
    """Take one chain: the feed's chain callback (streaming.assemble_chain_part), on the event loop.

    A whole chain the daemon fetched is priced on a pricing thread at its one spot (spot, trade
    time); a chain it could not deliver keeps the ticker's last levels, which then say why no
    newer chain came. A chain the sweep stored as its window's capture is kept as one
    (state.capture_store), in the shape the stored rows read back (its contracts are in expiry
    order already: the sweep asks the expiries ascending, option_contract.listed_expiries).
    """
    tk = ticker_storage_key(ticker)
    # a whole chain carries its spot (assemble_chain_part); one not delivered carries neither
    if contracts is None or spot is None:
        level_store.chain_failed(tk, f"chain fetch failed ({reason})")
        return
    if capture:
        capture_store.keep(tk, StoredCapture.taken(ts, spot, contracts))
    _wait_to_price(tk, DELIVERED, contracts, ts, spot)


def _wait_to_price(
    tk: str,
    what: str,
    contracts: list[OptionContract] | None = None,
    ts: float | None = None,
    spot: tuple[float | None, float | None] = (None, None),
) -> bool:
    """Queue a ticker's pricing (DELIVERED, STORED or REPRICE) for the pricing thread.

    A delivered chain replaces whatever waits for the ticker; anything else waits only for a
    ticker with nothing waiting, and stored captures only for one with nothing delivered.
    Returns whether it was queued.
    """
    with _chains_waiting_lock:
        held = _chains_waiting.get(tk)
        if what != DELIVERED and (held is not None or (what == STORED and tk in _chains_delivered)):
            return False
        if what == DELIVERED:
            _chains_delivered.add(tk)
        _chains_waiting[tk] = (what, contracts, ts, spot)
    if held is None:
        chain_pricing.submit(_price_waiting_chain)
    return True


def _price_waiting_chain() -> None:
    """Price one waiting ticker, every ticker the same.

    The longest waiting, a stored capture after every delivered chain. A reprice takes its turn
    behind the stored captures queued before it: a viewed ticker's ticks queue one again during
    each of its pricings. Nothing, once the stop dropped what waited (stop_terrain_loop).
    """
    with _chains_waiting_lock:
        if not _chains_waiting:
            return
        waiting = list(_chains_waiting)
        delivered = any(what == DELIVERED for what, *_ in _chains_waiting.values())
        tk = next(t for t in waiting if not (delivered and _chains_waiting[t][0] == STORED))
        what, contracts, ts, spot = _chains_waiting.pop(tk)
    _price_chain(tk, what, contracts, ts, spot, datetime.fromtimestamp(time_et.now(), ET))


def _price_chain(
    tk: str,
    what: str,
    contracts: list[OptionContract] | None,
    fetched_ts: float | None,
    spot: tuple[float | None, float | None],
    now: datetime,
) -> None:
    """Price a ticker's levels through THE producer of them (_publish_levels), at `now`.

    From a newly fetched chain, with the chain's own fetch time as its as-of (an older streamed
    value never overrides it); from the held chain with the newest values Schwab sent, the
    stream's and a /quotes answer's (REPRICE; the levels' time is the newest of them,
    levels_ts_utc); or from the ticker's newest stored captures (STORED, DATA_FLOW decision 7).
    Every pricing is at the job's own instant, so the daemon's newest beat is a beat of that
    instant and its contracts are judged by it.
    """
    if what == REPRICE:  # the held chain: the ticker's reason stays the chain's own
        try:
            _publish_levels(tk, now=now)
        except Exception as e:  # logged; the next tick or chain reprices
            log.warning("levels reprice failed for %s: %s", tk, e, exc_info=True)
        return
    try:
        if what == STORED:
            captures = capture_store.captures(get_db().db_path, tk)
            if captures:
                _publish_levels(tk, captures=captures, now=now)
            return
        # the chain as the sweep read it, once (chain_sweep.chain_messages)
        _publish_levels(tk, contracts, fetched_ts, chain_spot=spot, now=now)
        level_store.chain_priced(tk)
    except Exception as e:  # kept as the ticker's reason, and logged
        level_store.chain_failed(tk, f"pricing the chain failed: {type(e).__name__}: {e}")
        log.warning("pricing the chain of %s failed: %s", tk, e, exc_info=True)


#: what the console takes from the daemon's bus (start_order_flow_stream, at startup): each
#: streamed tick, each chain the daemon fetched, and each beat of the daemon's status, the last
#: restamped on the pricing thread
FEED_CALLBACKS: dict[str, Callable[..., None]] = {
    "on_tick_callback": _on_stream_tick,
    "on_chain_callback": _on_chain,
    "on_feed_callback": restamp_off_the_loop,
    "on_flow_callback": flow_changed,
}


STATUS_EVERY_SEC = 60.0


def _record_state(st: lmp.Beat | None) -> str:
    """Return the Recorder's own line, as the daemon's heartbeat carries it (WriterStatus.line).

    Its rows are counted once committed, and what it holds unwritten is its backlog; no live
    read of the database (AGENTS.md rule 6).
    """
    if st is None or st["writer"] is None:
        return "record: NOT REPORTED"
    return f"record: {st['writer']['line']}"


def _status_line(now: float) -> str:
    """One line for the console window: is each part working at `now`, from its own check."""
    st = lmp.daemon_status(now)
    watchlist = lmp.watchlist()
    if st is None and watchlist is not None:
        prices = f"last watchlist: {len(watchlist)} tickers (daemon not reporting)"
    elif watchlist is not None:
        priced = sum(1 for tk in watchlist if resolve_spot(tk, now=now)[0] is not None)
        prices = f"live prices: {priced} of {len(watchlist)} watchlist tickers"
    else:  # no list has arrived: the list is unknown
        prices = "live prices: WATCHLIST UNKNOWN (no current daemon heartbeat)"
    as_of = [levels.levels_ts_utc for _, levels in level_store.every_published()]
    newest = ct_label(max(as_of)) if as_of else "none"
    round_sec = None if st is None else st["chain_round_sec"]
    return " | ".join(
        [
            "alive",
            f"session {session_label(datetime.fromtimestamp(now, ET))}",
            "daemon link: " + ("connected" if st is not None else "NOT CONNECTED"),
            "Schwab socket: "
            + ("open" if st is not None and st["schwab_socket_open"] else "NOT OPEN"),
            prices,
            f"levels: {len(as_of)} tickers, newest as of {newest}",
            _record_state(st),
            (
                "chains: the daemon's last round of the watchlist took "
                f"{fixed_text(round_sec, 0)} s"
                if round_sec
                else "chains: the daemon's first round is running"
            ),
        ]
    )


#: while the console waits at its start, what it waits for is logged this often, with how long
WAITING_LOG_EVERY_SEC = 5.0


def _wait_for(what: str, ready: Callable[[], bool], stop: threading.Event) -> None:
    """Wait until `ready()` or `stop`, logging what for and for how long.

    `ready()` is read every half second (no event announces it); the stop ends the wait at once.
    Then log how long it took once ready.
    """
    started = time_et.elapsed()
    next_log = started
    while not stop.is_set() and not ready():
        if time_et.elapsed() >= next_log:
            log.info("waiting for %s (%.0f s so far)", what, time_et.elapsed() - started)
            next_log += WAITING_LOG_EVERY_SEC
        stop.wait(0.5)
    if ready():
        log.info("done waiting for %s after %.1f s", what, time_et.elapsed() - started)


def refresh_not_live_pages(now: float) -> None:
    """Tell each open page whose ticker's levels are not live at `now` to read them again.

    The published levels' verdict is levels_state's; the page reads its levels again, so their
    not-live age (terrain_staleness) keeps counting while nothing new arrives: the close values
    after the ticker's own option close. The levels loop calls it every STATUS_EVERY_SEC; a page
    whose levels are live is told by each new chain instead. The price's own age needs no read:
    the price row carries it on every beat.
    """
    for tk in live_ui.selected(app.state):
        levels, verdict = terrain_cache_get(tk, now)
        if levels is not None and verdict["levels_state"] != lmp.LIVE:
            _levels_changed(tk)


def _terrain_loop(stop: threading.Event, status_every: float = STATUS_EVERY_SEC) -> None:
    """Run the levels loop until `stop`: the stored levels, then the status every `status_every`.

    The stored levels come once the daemon has said what the watchlist is (queued behind the
    delivered chains: _load_stored_levels); then every `status_every` seconds the status line is
    logged, each open page whose price or levels are not live is told to read its levels again
    (refresh_not_live_pages) and the price levels of a new session or a new ticker are published.
    The loop waits for each status itself, and the stop ends that wait at once. The chains, and the
    bars each ticker's price levels are built from, arrive from the daemon (_on_chain,
    _bar_writer).
    """
    _wait_for(
        "the capture daemon's heartbeat (it says what the watchlist is)",
        lambda: lmp.watchlist() is not None,
        stop,
    )
    watchlist = lmp.watchlist()
    if watchlist is None:  # the stop came first: the daemon never said what the watchlist is
        return
    cross_store.load(watchlist)
    started = datetime.fromtimestamp(time_et.now(), ET)
    _publish_missing_price_levels(watchlist, started)
    queued = _load_stored_levels(watchlist)
    log.info(
        "Ready: the stored levels of %d of %d watchlist tickers are queued to price (session: %s); "
        "the daemon's chains price them from here.",
        queued,
        len(watchlist),
        session_label(started),
    )
    while not stop.wait(status_every):
        try:
            now = time_et.now()
            log.info(_status_line(now))
            refresh_not_live_pages(now)
            watchlist = lmp.watchlist()
            if watchlist is not None:
                _publish_missing_price_levels(watchlist, datetime.fromtimestamp(now, ET))
        except Exception as e:  # the status line says it failed, never silence
            log.warning("levels loop: %s: %s", type(e).__name__, e, exc_info=True)
    log.info("Terrain loop stopped")


def _load_stored_sessions(path: Path) -> None:
    """Schwab's /markets answers as the daemon recorded them in the stream database at `path`.

    Oldest first, so a stored chain is priced on the sessions of its expiries. No database or
    table yet, as at the first start before the daemon's, is no answer held. A database that
    cannot be read, or a row that cannot be taken, stops the console's start with its error.
    """
    rows = stored_rows(
        path,
        "stream_markets_raw",
        "SELECT native_json FROM stream_markets_raw WHERE status = 200 ORDER BY ts_recv",
    )
    for (answer,) in rows:
        record_markets(json.loads(answer))
    log.info("Recorded market answers held: %d", len(rows))


def _load_stored_levels(watchlist: list[str]) -> int:
    """At startup, each watchlist ticker's newest full chain capture is priced once.

    DATA_FLOW decision 7, so a restart, a weekend or the close shows the last reading with its
    time: queued for the pricing thread behind every delivered chain (_wait_to_price), never for a
    ticker the daemon already delivered a chain for. Returns how many tickers were queued.
    """
    return sum(_wait_to_price(tk, STORED) for tk in watchlist)


def start_terrain_loop() -> None:
    """Start the levels thread (start_services), with its own stop."""
    if SERVICES.levels_stop is not None:
        return
    SERVICES.levels_stop = stop = threading.Event()
    threading.Thread(target=_terrain_loop, args=(stop,), name="terrain-loop", daemon=True).start()


def stop_terrain_loop() -> None:
    """Stop the levels thread, and drop every pricing that waits (_chains_waiting).

    The program is stopping: what waits would be priced for pages that are closing, and the
    program's exit waits for the pricing thread, so only the pricing already running finishes.
    The chains stay stored and are priced at the next start (_load_stored_levels). The loop ends
    at once, in whatever wait it is.
    """
    stop, SERVICES.levels_stop = SERVICES.levels_stop, None
    if stop is not None:  # None: no loop was started
        stop.set()
    with _reprice_lock:  # a timer that fires after this queues nothing (_reprice_due)
        for timer in _reprice_timers.values():
            timer.cancel()
        _reprice_timers.clear()
    with _chains_waiting_lock:
        _chains_waiting.clear()


# ── Per-strike gamma and volume bars for the histogram panel ─────────────────
# Today's per-strike dealer gamma and traded volume, plus the previous market day's last chain
# capture (the day-over-day migration), of every expiry and of each listed expiry.
# Read-only, no Schwab call. Bar heights use the same exposure math as the levels.
def _prior_capture(captures: list[StoredCapture], chain_ts: float) -> StoredCapture | None:
    """Return the previous market day's close capture before the day of the chain's.

    Of the ticker's two newest market days' captures (newest first): on a closed market today's
    rows ARE the newest capture, so the day before is the chain's day's, not the wall clock's
    (which picks that same capture and compares it with itself). None with none captured.
    """
    chain_day = et_date_str_from_ts_utc(float(chain_ts))
    return next((c for c in captures if c.et_date < chain_day), None)


def _prior_day(tk: str, prior: StoredCapture) -> TerrainSnapshot | None:
    """Return the levels of the prior day's close capture (_prior_capture).

    The one producer (compute_terrain) on that capture, at its own spot and time: its per-strike
    rows, its walls and flip. None for a capture stored without its spot: it has no levels.
    """
    if prior.spot is None:
        return None
    return compute_terrain(
        tk,
        prior.contracts,
        prior.spot,
        now=datetime.fromtimestamp(prior.ts_utc, ET),
        sessions=sessions(),
    )


def _legs(legs: tuple[float, float] | None) -> CallPutTotal | None:
    """Return a cell's call/put pair and their total; None when not known."""
    if legs is None:
        return None
    return {"call": legs[0], "put": legs[1], "total": legs[0] + legs[1]}


def _gamma_surface_cell_fields(
    bucket: Bucket | None, contracts: CellContracts
) -> tuple[
    float | None,
    float | None,
    float | None,
    CallPutTotal | None,
    CallPutTotal | None,
    CellContracts,
]:
    """ONE (strike, expiry) cell's gex/dex/vanna/oi/volume/contracts fields from its bucket.

    The bucket is its exposure bucket, Schwab's values and the book's computed values exact; a
    value not known is None (no
    contract listed there, or Schwab sent nothing for it). Returns (gex, dex, vanna, oi, volume,
    contracts).
    """
    if bucket is None:
        return None, None, None, None, None, contracts
    return (
        bucket_metric(bucket, "net_gex_1pct"),
        bucket_metric(bucket, "net_dex_dollars"),
        bucket_metric(bucket, "net_vanna"),
        _legs(strike_oi_legs(bucket)),
        _legs(strike_volume_legs(bucket)),
        contracts,
    )


def project_gamma_surface(
    chain: list[OptionContract], books: dict[ExpiryKey, Book]
) -> ProjectedSurface:
    """Shape the strike × expiry grid the gamma heatmap draws from `books`.

    `books` are the exposure_books compute_terrain priced `chain` into, so every cell is the
    number the levels and per-strike rows were computed from. No exposure math here. A contract
    with a missing or malformed expiry is counted, never given a column.
    """
    by_expiry: dict[str, list[Book]] = {}
    for (exp, _dte), book in books.items():
        if exp is not None:
            by_expiry.setdefault(exp, []).append(book)
    per_expiry = {
        e: (bs[0][0] if len(bs) == 1 else merge_exposure_books(bs)[0])
        for e, bs in by_expiry.items()
    }
    exp_dte: dict[str, int | None] = {}
    # the vendor OSI symbol behind each (expiry, strike, side) leg, so the browser can ask the
    # stream for exactly the contracts it is showing
    leg_symbol: dict[tuple[str, float, str], str] = {}
    contracts_used = 0
    for c in chain:
        e = c.expiry
        if e not in per_expiry:
            continue
        contracts_used += 1
        if exp_dte.get(e) is None:  # native DTE for the column header, never inferred
            d = c.days_to_expiry
            exp_dte[e] = int(d) if d is not None else None
        if c.symbol and c.side is not None and c.strike is not None:
            leg_symbol[(e, c.strike, c.side.lower())] = str(c.symbol)
    total_contracts = len(chain)
    strike_set = {float(k) for ex in per_expiry.values() for k in ex}
    expiries = sorted(per_expiry)
    strikes = sorted(strike_set)
    expirations: list[SurfaceColumn] = [{"expiry": e, "dte": exp_dte.get(e)} for e in expiries]
    # Each cell carries every measure its bucket already holds -- GEX, DEX, vanna (call - put,
    # the dealer convention of calc.math_exposure_core._finish_bucket), OI and volume -- so one grid
    # serves every heatmap measure; a measure with no value is None (_gamma_surface_cell_fields).
    cells: list[ProjectedCell] = []
    for k in strikes:
        row: list[float | None]
        dex_row: list[float | None]
        vanna_row: list[float | None]
        oi_row: list[CallPutTotal | None]
        vol_row: list[CallPutTotal | None]
        contracts_row: list[CellContracts]
        row, dex_row, vanna_row, oi_row, vol_row, contracts_row = [], [], [], [], [], []
        for e in expiries:
            bucket = per_expiry[e].get(k)  # every column is one of per_expiry's
            legs: CellContracts = {
                "call": leg_symbol.get((e, k, "call")),
                "put": leg_symbol.get((e, k, "put")),
            }
            gex, dex, vanna, oi, volume, contracts = _gamma_surface_cell_fields(bucket, legs)
            row.append(gex)
            dex_row.append(dex)
            vanna_row.append(vanna)
            oi_row.append(oi)
            vol_row.append(volume)
            contracts_row.append(contracts)
        cells.append(
            {
                "strike": k,
                "gex": row,
                "dex": dex_row,
                "vanna": vanna_row,
                "oi": oi_row,
                "volume": vol_row,
                "contracts": contracts_row,
            }
        )
    return {
        "expirations": expirations,
        "strikes": strikes,
        "cells": cells,
        "contracts_total": total_contracts,
        "contracts_used": contracts_used,
    }


async def _watchlist_change(action: str, ticker: str) -> JSONResponse:
    """Ask the daemon for an add or a removal (streaming.watchlist_request).

    Its record is the answer: `ok` when it happened, else what happened (an invalid ticker with
    Schwab's /quotes answer, one already on the list, ...), and the record's sentence for it
    (`text`). With no answer, `text` says why. The list itself reaches the page in its beat, its
    one source, which a change sends at once (live_ui.watchlist_changed).
    """
    not_done = f"{ticker} is not {'added' if action == 'add' else 'removed'}"
    try:
        rec = await watchlist_request(action, ticker)
    except ConnectionError as e:
        return JSONResponse({"ok": False, "text": f"{not_done}: {e}"}, status_code=503)
    except TimeoutError:
        return JSONResponse(
            {"ok": False, "text": f"{not_done}: the capture daemon did not answer"},
            status_code=504,
        )
    return JSONResponse(
        {
            "ok": rec.op in ("added", "removed"),
            "op": rec.op,
            "ticker": rec.ticker,
            "status": rec.status,
            "answer": rec.answer,
            "text": rec.text,
        }
    )


@app.post("/api/watchlist")
async def post_watchlist(ticker: Annotated[str, Body(embed=True)]) -> JSONResponse:
    """Add a ticker.

    The daemon checks it with one /quotes request and adds it unless Schwab does not quote it
    (names it in errors.invalidSymbols).
    """
    return await _watchlist_change("add", ticker)


@app.delete("/api/watchlist/{ticker}")
async def delete_watchlist(ticker: str) -> JSONResponse:
    """Remove a ticker: Schwab is no longer asked for it; what was recorded for it stays."""
    return await _watchlist_change("remove", ticker)


@dataclass(frozen=True)
class FlowContract:
    """The body of /api/flow-contract: the field is required, null meaning none selected.

    A required body parameter of its own would read null as missing.
    """

    contract: str | None


@app.post("/api/flow-contract")
async def post_flow_contract(selected: FlowContract):
    """Select the contract on the Flow panel ({"contract": symbol}, or null for none).

    The daemon streams it on LEVELONE_OPTIONS and OPTIONS_BOOK on top of its option rule. Only a
    contract Schwab listed in a chain the console holds is taken.
    """
    contract = selected.contract
    if contract is not None and level_store.listing_ticker(contract) is None:
        return JSONResponse(
            {
                "ok": False,
                "contract": contract,
                "error": "not a contract in a chain the console holds",
            },
            status_code=409,
        )
    await select_flow_contract(contract)
    return {"ok": True, "contract": contract}


#: /api/health's Schwab reason when the console has no current heartbeat from the daemon
NO_DAEMON_HEARTBEAT = "the capture daemon's heartbeat is not current"


@app.get("/api/health")
def health():
    # docs/ARCHITECTURE.md "Failure domains": application availability and capability
    # availability are separate, so `status` answers "is the app alive" and never folds a
    # vendor outage into it. Schwab is the capture daemon's: its heartbeat says whether its
    # Schwab socket is open and, when not, why (as its log says it); no current heartbeat is
    # UNAVAILABLE (unmeasurable is not ok).
    now = time_et.now()
    st = lmp.daemon_status(now)
    capability: dict[str, object] = {
        "schwab": "AVAILABLE" if st is not None and st["schwab_socket_open"] else "UNAVAILABLE"
    }
    if capability["schwab"] == "UNAVAILABLE":
        capability["schwab_reason"] = NO_DAEMON_HEARTBEAT if st is None else st["schwab_down"]
    return {
        "status": "ok",
        "time": datetime.fromtimestamp(now).isoformat(),
        "capabilities": capability,
    }


def checkout_head(checkout: str | Path) -> str | None:
    """`checkout`'s HEAD now, read from its git files as git lays them out (gitrepository-layout).

    A worktree's `.git` file names its git directory, whose `commondir`
    holds the shared refs; HEAD holds a commit, or names a branch whose commit is in its ref file
    or in `packed-refs`. No process is started, so no request waits on one. None, logged with
    why, when it cannot be read.
    """
    try:
        git = Path(checkout) / ".git"
        if git.is_file():  # a worktree: "gitdir: <its git directory>"
            git = Path(checkout) / git.read_text(encoding="utf-8").split(":", 1)[1].strip()
        common = (
            git / (git / "commondir").read_text(encoding="utf-8").strip()
            if (git / "commondir").is_file()
            else git
        )
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[len("ref: ") :]
            loose = common / ref
            if loose.is_file():
                head = loose.read_text(encoding="utf-8").strip()
            else:
                packed = (common / "packed-refs").read_text(encoding="utf-8").splitlines()
                head = next(line.split(" ", 1)[0] for line in packed if line.endswith(" " + ref))
        if not _is_full_git_sha(head.lower()):
            log.warning("the checkout's HEAD is not a commit: %r", head)
            return None
        return head.lower()
    except (
        OSError,
        ValueError,
        IndexError,
        StopIteration,
    ) as e:  # ValueError: a file that is not text
        log.warning("the checkout's HEAD could not be read from its git files: %r", e)
        return None


# ── The running process's identity: the code it loaded, captured once at import; the checkout's
# HEAD read per request is reported beside it, never as it.
_IDENTITY_SHA_HEX_CHARS = frozenset("0123456789abcdef")


def _is_full_git_sha(value: str) -> bool:
    """Tell whether `value` is a 40-char lowercase-hex string; only that is true.

    A HEAD or ref file that holds anything else is no commit (checkout_head).
    """
    return len(value) == 40 and set(value) <= _IDENTITY_SHA_HEX_CHARS


#: captured once, at import, before uvicorn serves any request (one process, no --reload:
#: launch.CONSOLE)
RUNNING_COMMIT: str | None = checkout_head(APP_DIR)


class BuildAnswer(TypedDict):
    """/api/build: the commit the program runs, the checkout's, and whether they differ."""

    running_commit: str | None
    checkout_commit: str | None
    differ: bool | None


def build_answer(running: str | None, checkout: str | None) -> BuildAnswer:
    """/api/build's answer: the commit the running process loaded, stable for its life.

    The checkout's HEAD now is reported beside it, and whether the two differ (None while
    either is unknown).
    """
    return {
        "running_commit": running,
        "checkout_commit": checkout,
        "differ": None if running is None or checkout is None else running != checkout,
    }


@app.get("/api/build")
def api_build():
    """Serve the commit the process loaded and the checkout's HEAD now (build_answer)."""
    return build_answer(RUNNING_COMMIT, checkout_head(APP_DIR))


def _publish_price_levels(ticker: str, now: datetime) -> None:
    """Publish a ticker's price-level snapshot: THE producer of it.

    Materialized for the market's session at `now` (market_session_date: today's while a session
    is open, the newest one's while Closed) from its completed Schwab 1m bars, by the bar writer
    after each of the ticker's bars, and by the levels loop for a ticker with none yet for the
    session (a restart, a new session). It reads the bars from the prior session's regular open
    on (levels_start), the oldest a level reads. The routes read what it published
    (canonical_price_level_snapshot). A failed build is logged; the routes serve the last
    published snapshot with its as-of time, or say the levels are absent.
    """
    tk = ticker_storage_key(ticker)
    before = canonical_price_level_snapshot(tk, now)
    day, daily = market_session_date(now), bar_store.series(tk, "1d")
    try:
        start = levels_start(daily, day, sessions()).timestamp()
        snap = materialize_price_level_snapshot(
            tk,
            day,
            bars_from_candles(bar_store.bars_from(tk, start)),
            daily=daily,
            bar_source=BAR_SOURCE,
        )
    except Exception as e:  # logged; the ticker's next bar builds them
        log.warning("price levels for %s not built: %s", tk, e, exc_info=True)
        return
    if snap is not before:  # the same object when its bars did not change
        _levels_changed(tk)


def _publish_missing_price_levels(tickers: Iterable[str], now: datetime) -> None:
    """Build the price levels of each ticker with none published for the market's session at `now`.

    As at the console's start, or a new session.
    """
    for tk in tickers:
        if canonical_price_level_snapshot(tk, now) is None:
            _publish_price_levels(tk, now)


#: every panel the page shows, sent by its socket for the page's selected ticker
#: (live_ui.LiveUiServer): each kind's producer, given what it reads of what the page asked.
#: Each is sent at once and again when its inputs change: CHAIN_PANELS on a new chain
#: (_publish_levels), LEVELS_PANELS on each publication of the levels (_levels_changed),
#: BARS_PANELS on a new bar, FLOW_PANELS on each streamed equity quote and book and
#: OPTION_PANELS on each option contract's (flow_changed)
PAGE_PANELS: dict[str, Callable[[live_ui.Asked], Mapping[str, Any]]] = {
    "experimental": lambda a: push_experimental.experimental(a.ticker, a.now),
    "expiries": lambda a: push_expiries.expiries(a.ticker, a.now),
    "vanna": lambda a: push_strike_bars.strike_bars("vanna", a.ticker, a.now, a.params),
    "charm": lambda a: push_strike_bars.strike_bars("charm", a.ticker, a.now, a.params),
    "terrain": lambda a: push_terrain.terrain(a.ticker, a.now),
    "strikes": lambda a: push_strikes.strikes(a.ticker, a.now, a.params),
    "surface": lambda a: push_surface.gamma_surface(
        a.ticker, a.now, a.params, requested=_gamma_surface_wanted(a.ticker)
    ),
    "chain": lambda a: push_chain.chain(a.ticker, a.now, a.params),
    "levels": lambda a: push_levels.levels_payload(a.ticker, tf_asked(a.params), a.at),
    "bars": lambda a: push_bars.bars(a.ticker, a.now, a.params),
    "forming": lambda a: push_bars.forming(a.ticker, a.now, a.params),
    "tape": lambda a: push_tape.tape(a.ticker, a.now),
    "book": lambda a: push_book.book(a.ticker, a.now, a.params),
    "book_heatmap": lambda a: push_book_heatmap.book_heatmap(a.ticker, a.params),
    "contract": lambda a: push_contract.options_microstructure(
        push_contract.contract_asked(a.params), a.now
    ),
    "option_book": lambda a: push_option_book.option_book(a.ticker, a.now, a.params),
    "desk": lambda a: push_desk.desk_events_payload(
        a.ticker, tf_asked(a.params), a.at, a.params.get("limit")
    ),
    "confluence": lambda a: push_confluence.confluence(a.ticker, a.at, a.params),
    "liquidity": lambda a: push_liquidity.liquidity_snapshot(a.ticker, a.at),
}
CHAIN_PANELS = ("expiries",)
#: the panels a new bar moves; `forming` after `bars` (the socket sends them in name order), so the
#: page draws the bars Schwab has not sent whole over the newest bars it has
BARS_PANELS = ("bars", "liquidity", "desk", "forming")
#: the chain screens and the Options Book show each contract's newest streamed values (push.chain,
#: push.option_book), and the live price
FLOW_PANELS = ("book", "book_heatmap", "tape", "contract", "chain", "option_book")
#: the panels an option contract's own quote or book moves: its Flow panel, the chain screens and
#: the Options Book
OPTION_PANELS = ("contract", "chain", "option_book")
#: the panels computed from the ticker's live price (each level's distance and side, the spot
#: they are measured from; today's gap and open; each zone's side of the price and the zones
#: nearest it; the bar forming from its trades): the socket sends them again with each of its
#: price rows
PRICED_PANELS = ("levels", "experimental", "liquidity", "forming")
