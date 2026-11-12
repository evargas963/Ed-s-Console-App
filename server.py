"""Ed Console web server: the levels loop, the bar writer, and the routes the screens read."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import threading
import time
from collections.abc import Collection, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Annotated

import psutil
from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import live_market_plane as lmp
import live_price_rows as _lpr  # with_change: the bar-change computation
import runtime_layout
import time_et
from app.market_data.schwab.streaming import live_ui
from app.market_data.schwab.streaming.live_push import MARKET_CONTEXT
from app.options.order_flow.engine import (
    BOOK_VENUES,
    COMPOSITE,
    book_age_sec,
    book_readout,
    compute_book_microstructure,
    readout_card,
)
from app.options.order_flow.history import (
    BOOKS_KEPT_SEC,
    LEAN,
    book_heatmap_for_ticker,
    recent_prints,
    tape_row,
)
from app.options.order_flow.live_payload import options_live_payload
from app.options.order_flow.state import (
    get_content_for_symbol,
    get_stream_greeks,
    option_top,
    rest_quotes,
)
from app.options.order_flow.streaming import (
    get_option_contract_streaming_diagnostics,
    price_row,
    price_state,
    select_flow_contract,
    start_order_flow_stream,
    stop_order_flow_stream,
    streamed_bars,
    watchlist_request,
)
from calibration.complete_chain_capture import (
    CAPTURE_BASIS,
    last_capture_per_day,
    newest_capture_ts,
)
from confluence_composite import at_price, build_matrix, window_rows
from db import LevelCrossEvent, get_db
from db_authority import canonical_stream_db_path
from instrument_identity import display_symbol, ticker_storage_key, vendor_option_root
from liquidity_models import ZONE_DISPLAY, PlaybookConfig
from liquidity_value_engine import (
    _MATERIALIZED_SNAPSHOTS,
    OPTION_LEVEL_TAGS,
    bars_from_candles,
    build_live_snapshot,
    materialize_price_level_snapshot,
)
from math_exposure_core import (
    bucket_metric,
    compute_exposures_by_strike,
    merge_exposure_books,
    overlay_streamed_contract_fields,
    strike_oi_legs,
    strike_total_oi,
    strike_volume_legs,
)
from math_levels import compute_charm_by_strike
from micro_structure import Candle
from numeric_contract import float_finite_or_none, price_text, schwab_count, schwab_number
from option_contract import OptionContract, chain_row
from terrain_atr import Atr, compute_atrs
from terrain_engine import (
    OPTION_LEVELS,
    PRICE_RELATIONS,
    SAME_DAY_LEVELS,
    SCOPES,
    TerrainSnapshot,
    chain_ladder,
    compute_terrain,
    level_moves,
    nearest_strike,
    per_strike_view,
    positioning_migration,
    price_relations,
    side_total,
    strike_window,
)
from terrain_read import LEVEL_ABOVE, LEVEL_BELOW, crossed, from_spot_text, level_side, within
from time_et import (
    CLOSE_AUCTION,
    ET,
    OPEN_AUCTION,
    age_text,
    auction,
    ct_label,
    et_date_str_from_ts_utc,
    last_open,
    market_session_date,
    now_et,
    option_close_product,
    option_market_open,
    options_closed_at,
    options_open,
    options_opened,
    record_markets,
    session,
    session_label,
    valuation_instant,
)

# ── App directory = same folder as this file ─────────────────────────────────
APP_DIR = str(Path(__file__).parent.resolve())


# Its lines go to the program's one log (capture._start_log: the day's file and the window).
log = logging.getLogger("ed_server")

#: Precedence for the ONE spot authority. Highest wins; every entry records where the
#: number came from so a caller can never silently accept a lower-confidence source.
SPOT_SOURCE_PLANE = (
    "streaming_plane"  # live_market_plane.get_quote — the freshest real trade this process has seen
)
SPOT_SOURCE_NONE = "none"  # Schwab has sent no price


def price_mark(ticker: str, spot_ts: float | None, now: float) -> dict:
    """The live price's trade time and, while it is not live at `now` (price_state), its mark.

    Served beside every value computed from that price, so a value from a price that has stopped
    stands marked not live (AGENTS rule 5): `spot_not_live_text` is the mark the page prints
    beside each such value, with the trade's time and age, None while the price is live.
    """
    mark = ["not live"]
    if spot_ts is not None:
        mark.append(f"last trade {ct_label(spot_ts)}, {age_text(now - spot_ts)} old")
    return {
        "spot_time_ct": None if spot_ts is None else ct_label(spot_ts),
        "spot_not_live_text": (
            None if price_state(ticker, now)[0] == lmp.LIVE else " · ".join(mark)
        ),
    }


def resolve_spot(ticker: str, *, now: float) -> tuple[float | None, str, float | None]:
    """(spot, source, as_of_ts_utc): the daemon's price row's Schwab LAST_PRICE as sent.

    With its trade time. Why it is not live (price_state) does not remove it; the number stays.
    (None, the outage reason or SPOT_SOURCE_NONE, None) until Schwab has sent one.
    """
    row = price_row(ticker, now)
    if row["spot"] is not None:
        return row["spot"], SPOT_SOURCE_PLANE, row["trade_ts"]
    outage = price_state(ticker, now)[1]
    if outage is None:
        return None, SPOT_SOURCE_NONE, None
    return None, outage, None


#: one RTH day of 1-minute bars
CANDLE_1M_MAX_BARS: int = 390


#: every ticker's completed 1-minute bars, oldest first, the newest BARS_KEPT: Schwab's own
#: 1-minute price history (its last 10 days, extended hours, from the capture daemon's
#: /pricehistory request each ET date) with Schwab's streamed CHART_EQUITY bars on top, a streamed
#: minute replacing Schwab's history of it. Owned by the bar writer (_bar_writer). Every live
#: reader reads this, never a database (docs/DATA_FLOW.md §2 D6).
BARS_KEPT = 24_000
_bars: dict[str, list[Candle]] = {}
#: every ticker's other series of Schwab's /pricehistory, each its newest answer as sent
#: ((ticker, series) -> candles, oldest first; every series of the daemon's PRICE_HISTORY but
#: "1m"). Owned by the bar writer; the bars panel and the ATR (_atr) read them.
_series: dict[tuple[str, str], list[Candle]] = {}
_bars_lock = threading.Lock()
#: where the bars come from, named in every level's provenance
BAR_SOURCE = "Schwab /pricehistory 1-minute bars and CHART_EQUITY"


def _schwab_bar(start_ms, o, h, lo, c, volume) -> Candle | None:
    """One Schwab CHART_EQUITY bar as a Candle, each field as Schwab sent it.

    None when its start or a price is not a number (AGENTS.md rule 2: absent, -999, text, NaN or
    infinity). A volume that is not a number, or negative, is absent.
    """
    start, o, h, lo, c = (
        schwab_number(start_ms),
        schwab_number(o),
        schwab_number(h),
        schwab_number(lo),
        schwab_number(c),
    )
    if start is None or o is None or h is None or lo is None or c is None:
        return None
    return Candle(start / 1000.0, o, h, lo, c, schwab_count(volume))


def _write_price_history(msg: dict) -> str | None:
    """One series of a ticker's price history as Schwab's /pricehistory answered it.

    Pushed by the capture daemon: its 1-minute bars into the ticker's bars, only the minutes not
    held taken (a held minute, a streamed bar or an earlier history's, stands over Schwab's
    history of it); any other series replacing the one held. A candle without a valid field is
    not kept. The ticker when the bars or candles it holds changed, else None. Runs on the bar
    writer, the one writer of _bars and _series.
    """
    tk = ticker_storage_key(msg["symbol"])
    sent = msg["answer"]["candles"]
    if msg["series"] != "1m":
        key = (tk, msg["series"])
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
        if key in _series and _series[key] == candles:
            return None
        with _bars_lock:
            _series[key] = candles
        return tk
    held = _bars[tk] if tk in _bars else []
    held_minutes = {b.ts for b in held}
    taken = {}
    for c in sent:
        start = schwab_number(c.get("datetime"))
        if start is None or start / 1000.0 in held_minutes:
            continue
        b = _schwab_bar(
            start, c.get("open"), c.get("high"), c.get("low"), c.get("close"), c.get("volume")
        )
        if b is not None:
            taken[b.ts] = b
    if not taken:
        return None
    bars = sorted([*held, *taken.values()], key=lambda b: b.ts)[-BARS_KEPT:]
    with _bars_lock:
        _bars[tk] = bars
    return tk if any(t >= bars[0].ts for t in taken) else None


def _keep_bar(tk: str, bar: Candle) -> None:
    """Put a streamed bar into `tk`'s bars.

    A minute already held is replaced (Schwab's newest bar for it), a new one takes its place in
    time; the oldest beyond BARS_KEPT leave.
    """
    with _bars_lock:
        held = _bars.setdefault(tk, [])
        i = len(held)  # bars arrive in time order: found at once
        while i and held[i - 1].ts > bar.ts:
            i -= 1
        if i and held[i - 1].ts == bar.ts:
            held[i - 1] = bar
        else:
            held.insert(i, bar)
        del held[:-BARS_KEPT]


def _bars_1m(tk: str, limit: int = CANDLE_1M_MAX_BARS) -> list[Candle]:
    """`tk`'s completed 1-minute bars, oldest first.

    Schwab's streamed CHART_EQUITY bars as the bar writer keeps them. A minute the stream did not
    deliver is absent, never filled in.
    """
    key = ticker_storage_key(tk)
    with _bars_lock:
        return list(_bars[key][-int(limit) :]) if key in _bars else []


def _bar_dict(c: Candle) -> dict:
    return {"t": float(c.ts), "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}


def _write_streamed_bar(msg: dict) -> bool:
    """Keep one streamed 1-minute bar with the ticker's bars.

    The bar is Schwab CHART_EQUITY, pushed by the capture daemon, which records it. False when it
    lacks a valid field (then it is not kept).
    """
    bar = _schwab_bar(
        msg.get("bar_start_ms"),
        msg.get("open"),
        msg.get("high"),
        msg.get("low"),
        msg.get("close"),
        msg.get("volume"),
    )
    if bar is None:
        log.warning("streamed bar for %s lacks a valid field, not kept: %s", msg.get("symbol"), msg)
        return False
    tk = ticker_storage_key(msg["symbol"])
    _keep_bar(tk, bar)  # what every live reader reads
    live_ui.changed(app.state, tk, *BARS_PANELS)
    return True


def _write_streamed_bars(msgs: list, now: datetime) -> None:
    """Write streamed bars and price histories, then build the price levels of each ticker.

    A price history is a message with a `series`. The levels are built for each ticker whose
    1-minute bars were written, for the market's session at `now`: everything that arrived
    together is written before any level is built (a minute's bars for the whole watchlist arrive
    together).
    """
    written = []
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
                msg.get("symbol"),
                e,
                exc_info=True,
            )
    for tk in dict.fromkeys(written):
        _publish_price_levels(tk, now)


def _bar_writer() -> None:
    """Run the bar writer, the one owner of the bars and candles in memory (_bars, _series).

    It writes every streamed bar and price history the capture daemon pushes, as it arrives, with
    those already waiting behind it. Ends at stop_bar_writer's None, once everything queued before
    it is written.
    """
    while True:
        msgs = [streamed_bars.get()]
        while not streamed_bars.empty():
            msgs.append(streamed_bars.get_nowait())
        _write_streamed_bars([m for m in msgs if m is not None], now_et())
        if None in msgs:
            return


_bar_writer_thread: threading.Thread | None = None


def start_bar_writer() -> None:
    global _bar_writer_thread
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _bar_writer_thread = threading.Thread(target=_bar_writer, name="bar-writer", daemon=True)
    _bar_writer_thread.start()


def stop_bar_writer(thread: threading.Thread | None = None) -> None:
    """Write every bar already queued, then end the bar writer (`thread`: the one started)."""
    thread = thread or _bar_writer_thread
    if thread is None:
        return
    streamed_bars.put(None)
    thread.join(timeout=10.0)


def _watchlist() -> list[str] | None:
    """Return the watchlist: the tickers the capture daemon asks Schwab for.

    A current heartbeat that carries a list is that list; one that carries none is unknown. A late
    or missing heartbeat keeps the list of the last beat.
    """
    st = lmp.last_beat()
    return None if st is None else list(st["watchlist"])


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _app_lifespan(_app):
    """Startup and shutdown.

    The live-binding check, the signal handlers, the recorded market sessions, the levels loop,
    the bar writer, the daemon's feed and the page push.
    """
    # ── Startup ─────────────────────────────────────────────────────────────
    # FIRST, before any worker, client or database is touched: a checkout whose runtime is
    # ANOTHER checkout (a worktree converging on production) does not start a live console
    # (runtime_layout.live_binding_error). Refusing here stops uvicorn before it serves anything.
    _binding = runtime_layout.live_binding_error()
    if _binding is not None:
        log.critical("LIVE CONSOLE REFUSED: %s", _binding)
        raise RuntimeError(f"live console refused: {_binding}")
    # Before the loops and the feed: everything priced from here on has the recorded sessions, and
    # the daemon's answers then replace them.
    _load_stored_sessions(canonical_stream_db_path())

    # The levels loop: the stored levels at startup, then the status line and the price levels
    # (the chains arrive from the daemon, _on_chain).
    start_terrain_loop()
    # bar collection is its own always-on service, never a side-effect of rendering
    start_bar_writer()

    # The live feed from the capture daemon (the only Schwab client): every streamed equity
    # quote and option greeks/OI/volume quote -> _on_stream_tick, which reprices a viewed
    # ticker; every chain the daemon fetched -> _on_chain, which prices it.
    start_order_flow_stream(**FEED_CALLBACKS)

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    # The program's one stop (capture.run) ends the pages with everything else; stop_bar_writer
    # waits up to 10 s for the bar writer.
    try:
        stop_order_flow_stream()
    except Exception as e:  # the other loops still stop
        log.warning("Order flow streaming shutdown: %s", e, exc_info=True)

    stop_terrain_loop()
    stop_bar_writer()


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

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


static_dir = Path(APP_DIR) / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", _RevalidateStaticFiles(directory=str(static_dir)), name="static")


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

_MARKET_CONTEXT_META = '<meta name="ed-market-context" content="">'
_SCOPES_META = '<meta name="ed-scopes" content="">'
_STREAM_WORDS_META = '<meta name="ed-stream-words" content="">'
#: the scope control's words, one per terrain_engine.SCOPES
SCOPE_LABELS = {"auto": "Auto", "wider": "Wider", "all": "All available"}


#: the page's price socket, on the program's own port (live_ui.page_socket)
app.add_api_websocket_route("/ws", live_ui.page_socket)


def _with_page_settings(html: str) -> str:
    """Tell the page its market-context symbols, strike-window scopes and streaming-state words.

    The market-context symbols it always shows are live_push.MARKET_CONTEXT, each with its
    display name; the scopes its strike windows take are terrain_engine.SCOPES, each with its
    word; and the words for each streaming state are STREAM_WORDS.
    """
    context = json.dumps([{"key": k, "display": display_symbol(k)} for k in MARKET_CONTEXT])
    scopes = json.dumps([{"key": s, "label": SCOPE_LABELS[s]} for s in SCOPES])
    return (
        html.replace(
            _MARKET_CONTEXT_META,
            f'<meta name="ed-market-context" content="{html_escape(context)}">',
            1,
        )
        .replace(_SCOPES_META, f'<meta name="ed-scopes" content="{html_escape(scopes)}">', 1)
        .replace(
            _STREAM_WORDS_META,
            f'<meta name="ed-stream-words" content="{html_escape(json.dumps(STREAM_WORDS))}">',
            1,
        )
    )


@app.get("/", response_class=HTMLResponse)
def root():
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
def favicon():
    """Browsers request this automatically; without a route they log 404 (harmless but noisy)."""
    return Response(status_code=204)


#: the stored cross direction in words; a direction not stored reads "through", never a side
_CROSS_WORD = {"up": "above", "down": "below"}


#: every ticker's newest CROSSES_KEPT level crosses, newest last, as stored rows: loaded from
#: level_crosses once the watchlist is known (_load_crosses), then each cross as it is recorded
#: (_log_level_crosses). Every live reader reads this, never the database (DATA_FLOW §2 D6).
CROSSES_KEPT = 1600
_crosses: dict[str, list[dict]] = {}
_crosses_lock = threading.Lock()


def _held_crosses(tk: str) -> list[dict]:
    """Return the ticker's held level crosses, oldest first.

    The one database read of them, the first time they are needed (the console's start, or a
    cross found before it), then fed live. Called holding _crosses_lock.
    """
    if tk not in _crosses:
        _crosses[tk] = get_db().get_recent_crosses(ticker=tk, n=CROSSES_KEPT)[::-1]
    return _crosses[tk]


def _load_crosses(watchlist: list[str]) -> None:
    """Load the watchlist's held level crosses, at the console's start."""
    with _crosses_lock:
        for tk in watchlist:
            _held_crosses(tk)


def _merged_recent_crosses(ticker: str, n: int) -> list[dict]:
    """Return the newest `n` level crosses, each (time, value, direction) one event.

    Each event carries every level named there in `level_names`. The one reader of level crosses
    for every route. Price crossing one strike writes one stored row per named level sitting
    there; they are merged here, at the read, so the stored history keeps its per-level rows.
    """
    with _crosses_lock:
        raw = _crosses[ticker][::-1][: max(int(n) * 8, 64)] if ticker in _crosses else []
    merged: list[dict] = []
    seen: dict[tuple, dict] = {}
    for r in raw:
        key = (r.get("ts_utc"), r.get("level_value"), r.get("direction"))
        hit = seen.get(key)
        if hit is None:
            row = dict(r)
            row["level_names"] = [r.get("level_name")]
            seen[key] = row
            merged.append(row)
            continue
        nm = r.get("level_name")
        if nm and nm not in hit["level_names"]:
            hit["level_names"].append(nm)
    return merged[:n]


def unavailable(ticker: str, reason: str, **fields) -> dict:
    """Return a route's answer when the value it serves is not held for `ticker`.

    It says why, with the route's own `fields`.
    """
    return {"ticker": ticker, "available": False, **fields, "reason": reason}


# ── THE LEVELS (from the chains the capture daemon fetches) ──────────────────
@dataclass(frozen=True)
class PublishedLevels:
    """A ticker's levels as _publish_levels published them, with what they were priced from."""

    snap: TerrainSnapshot
    #: when the chain was fetched: a reprice on a kept chain does not make the chain newer
    computed_ts_utc: float
    #: the newest Schwab option value in them: the chain, or a value pushed since
    levels_ts_utc: float
    #: Schwab's label of the chain's completeness (CAPTURE_BASIS, or a capture's own)
    chain_basis: str
    #: the price the levels were computed at, its source and its time
    spot_source: str
    spot_as_of_ts_utc: float | None
    #: the price as resolved for this publication: (price, source, time)
    priced_at: tuple
    #: the heatmap grid (project_gamma_surface); None without a price or a book
    gamma_surface: dict | None
    vanna_rows: list
    charm_rows: list
    #: the chain as Schwab sent it, and as priced with the values pushed since
    chain: list[OptionContract]
    priced_chain: list[OptionContract]
    #: the contracts Schwab listed in the newest chain, each record by its symbol
    contracts: Mapping[str, OptionContract]
    #: read from the stored captures, recomputed only when `captures_key` changes
    forces: dict
    prior_day: TerrainSnapshot | None
    captures_key: tuple

    def served(self) -> dict:
        """Return the levels as the terrain panel sends them, before the live price's relations."""
        return self.snap.to_dict() | {
            "computed_ts_utc": self.computed_ts_utc,
            "levels_ts_utc": self.levels_ts_utc,
            "chain_basis": self.chain_basis,
            "spot_source": self.spot_source,
            "spot_as_of_ts_utc": self.spot_as_of_ts_utc,
        }


_terrain_cache: dict[str, PublishedLevels] = {}
_terrain_cache_lock = threading.Lock()
#: Why the ticker's newest chain is not priced: the daemon's chain fetch failed with Schwab's
#: answer, or a chain arrived incomplete. Cleared by the next chain priced.
_terrain_refresh_last_error: dict[str, str] = {}

_terrain_loop_running: bool = False
_terrain_loop_thread: threading.Thread | None = None


def published_levels(ticker: str) -> PublishedLevels | None:
    """Return the ticker's levels as last published, or None before the first."""
    with _terrain_cache_lock:
        return _terrain_cache.get(ticker_storage_key(ticker))


def terrain_cache_get(ticker: str, now: float) -> tuple[PublishedLevels | None, dict]:
    """Return the ticker's published levels (None before the first) and their verdict at `now`.

    The verdict is terrain_staleness's: the cache holds the chain's time, never a verdict.
    """
    levels = published_levels(ticker)
    if levels is None:
        return None, terrain_staleness(None, ticker, now=now)
    return levels, terrain_staleness(
        levels.computed_ts_utc, ticker, now=now, levels_ts_utc=levels.levels_ts_utc
    )


#: The least age at which a terrain snapshot stops calling itself current (terrain_staleness also
#: allows two of the loop's delivered cycles).
TERRAIN_STALE_AFTER_SEC: float = 180.0


def terrain_staleness(
    computed_ts_utc: float | None,
    ticker: str,
    *,
    now: float,
    levels_ts_utc: float | None = None,
) -> dict:
    """Return the levels' state at `now`, THE levels verdict every screen shows (`levels_state`).

    LIVE from the market day's start (time_et.options_open) until the ticker's own option market
    closes (time_et.option_close_product: stock options at 16:00 ET, index-close options at 16:15)
    with its chain current; CLOSE once that market has closed, and through the day's first round,
    with a chain fetched after its close, however old (docs/DATA_FLOW.md §2 D5); STALE, with WHY,
    when the chain is overdue or the close values were never fetched; NOT LIVE when Schwab's
    /markets answer for today is not held. The daemon's last answer for the ticker's chain (a
    failed fetch, an incomplete delivery) outranks the age, and its refused sign-in
    (`chains_waiting`) outranks both, on every verdict but LIVE and CLOSE. While its option market
    is open the daemon fetches every watchlist ticker's chain without end, so age past two of its
    delivered rounds is a gap, never a schedule. Served beside it: the time of the newest Schwab
    option value the levels hold (`levels_ts_utc`: the chain, or a value pushed since) and its
    age.
    """
    failure = _terrain_refresh_last_error.get(ticker_storage_key(ticker))
    state, reason = _levels_state(computed_ts_utc, ticker, now, failure)
    age = None if levels_ts_utc is None else now - float(levels_ts_utc)
    return {
        "levels_state": state,
        "levels_stale_reason": reason,
        "levels_age_text": None if age is None else age_text(age),
        "levels_time_ct": None if levels_ts_utc is None else ct_label(levels_ts_utc),
    }


def _levels_state(
    computed_ts_utc: float | None, ticker: str, now: float, failure: str | None
) -> tuple[str, str]:
    """(levels_state, why it is not LIVE or CLOSE) for terrain_staleness.

    While the daemon asks Schwab for nothing (its status's `chains_waiting`: a refused sign-in),
    that is the why.
    """
    status = lmp.daemon_status(now)
    waiting = None if status is None else status["chains_waiting"]
    if waiting:
        failure = f"no chain is fetched: {waiting}"
    sep = f" — {failure}" if failure else ""
    if computed_ts_utc is None:
        return LEVELS_STALE, "no terrain snapshot has been computed yet" + sep
    at = datetime.fromtimestamp(now, ET)
    product = option_close_product(ticker)
    market_open = options_open(at)
    if market_open is None:
        return lmp.NOT_LIVE, "the market session is unknown" + sep
    age = now - float(computed_ts_utc)
    # judged against the round the daemon's chain sweep last reported (every watchlist ticker
    # once): a chain's age is its own, and a late heartbeat does not shorten the round
    last = lmp.last_beat()
    round_sec = None if last is None else last["chain_round_sec"]
    # Stale only past the floor *and* past two delivered rounds — one missed round is normal
    # jitter, two is a real gap. The floor is retained so a fast sweep cannot hide staleness;
    # with no round delivered (or no current status) the floor alone.
    stale_after = (
        float(TERRAIN_STALE_AFTER_SEC)
        if round_sec is None
        else max(float(TERRAIN_STALE_AFTER_SEC), 2.0 * float(round_sec))
    )
    closed = options_closed_at(at, product)
    opened = options_opened(at)
    if (
        not market_open
        or (closed is not None and closed.date() == at.date())  # its own market has closed today
        or (
            float(computed_ts_utc) < opened.timestamp() and now - opened.timestamp() <= stale_after
        )  # the day's first round
    ):
        if closed is None or float(computed_ts_utc) < closed.timestamp():
            return (
                LEVELS_STALE,
                "this ticker's options are closed and its close values have not been fetched" + sep,
            )
        return LEVELS_CLOSE, ""
    if age <= stale_after:
        return lmp.LIVE, ""
    if waiting:
        return LEVELS_STALE, f"levels are {age:.0f}s old{sep}"
    if failure:
        return (
            LEVELS_STALE,
            f"levels are {age:.0f}s old and every chain since has failed — {failure}",
        )
    return LEVELS_STALE, (
        f"levels are {age:.0f}s old; the daemon's chain sweep has not delivered this "
        + (
            f"ticker in two of its rounds ({float(round_sec):.0f}s each)"
            if round_sec is not None
            else f"ticker in {float(TERRAIN_STALE_AFTER_SEC):.0f}s (the daemon reports no round "
            "of its sweep)"
        )
    )


#: the levels' words beside the price's (live_market_plane LIVE / NOT_LIVE): the close values of the
#: ticker's own option market stand; the chain is overdue or the close values were never fetched
LEVELS_CLOSE, LEVELS_STALE = "CLOSE", "STALE"


def levels_mark(levels: dict, ticker: str, now: float) -> dict:
    """Return the one word the Key Levels line shows, from the levels' verdict and their price's.

    From terrain_staleness and price_state: the levels' state while it is not LIVE, else the
    price's state (the walls stand and are LIVE only while the price they are measured from is
    live), with why.
    """
    if levels["levels_state"] != lmp.LIVE:
        return {
            "levels_mark": levels["levels_state"],
            "levels_mark_reason": levels["levels_stale_reason"],
        }
    label, outage = price_state(ticker, now)
    return {"levels_mark": label, "levels_mark_reason": outage}


def levels_verdict(staleness: dict) -> dict:
    """Return the levels verdict a screen shows, from terrain_staleness's answer.

    The word, the chain's time, the age and why not live.
    """
    return {
        k: staleness[k]
        for k in (
            "levels_state",
            "levels_time_ct",
            "levels_age_text",
            "levels_stale_reason",
        )
    }


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


def _streamed_greeks_for_ticker(
    listed: Collection[str], now: float, feed: lmp.FeedNow | None = None
) -> dict:
    """Return the newest streamed Greeks, volume, bid and ask of the ticker's held contracts.

    The contracts are every one the daemon's latest beat holds of the ticker's chain (`listed`,
    the symbols Schwab listed in it). A missing beat keeps that set. `feed` is one read of that
    heartbeat; omitted, this call reads it.
    """
    out: dict = {}
    for sym in _held_option_symbols_for_ticker(listed, now, feed):
        held = [r for r in (get_stream_greeks(sym), option_top(sym)) if r is not None]
        if held:
            out[sym] = {k: v for r in held for k, v in r.items()}
    return out


def _held_option_symbols_for_ticker(
    listed: Collection[str], now: float, feed: lmp.FeedNow | None = None
) -> list[str]:
    """Every contract of the ticker's chain (`listed`) on the daemon's latest LEVELONE_OPTIONS beat.

    A missing or too-old beat keeps that set; it does not say the feed is live.
    `feed` is one read of that heartbeat; omitted, this call reads it.
    """
    if feed is None:
        feed = lmp.feed_now(now)
    opts = feed.held.get("LEVELONE_OPTIONS")
    if not opts:
        return []
    return [sym for sym in opts if sym in listed]


def _overlaid_symbols(pre: list, post: list) -> list[str]:
    """Return the contracts `post` holds as new records of `pre`'s.

    overlay_streamed_contract_fields passes an unchanged contract through as the same record.
    """
    return [new.symbol for orig, new in zip(pre, post) if new is not orig and new.symbol]


def _leg_stream_ts_recv(greeks: dict | None) -> float | None:
    """Return the freshest of a streamed contract's own per-field `_ts_recv` stamps.

    The shape is get_stream_greeks', app.options.order_flow.state; None if `greeks` is
    absent/empty. Any one of these
    fields ticking is evidence the contract is actively producing observations right now, so the
    MAX (not a single hardcoded field) is the contract's own last-observed instant.
    """
    if not greeks:
        return None
    candidates = [greeks.get(k) for k in ("gamma_ts_recv", "delta_ts_recv", "total_volume_ts_recv")]
    candidates = [c for c in candidates if isinstance(c, (int, float))]
    return max(candidates) if candidates else None


_STREAM_STATE_ORDER = ("stale", "pending")


def _stream_state_of(states: list) -> str:
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
    surface: dict, streamed: dict, overlay_symbols: set, held_symbols: set[str]
) -> dict:
    """`surface` with per-leg (call/put) and per-cell STREAM state on its cells and columns.

    It never touches a cell's computed value (project_gamma_surface is the one exposure
    computation); it says whether a streamed Schwab value backs it now.

    `streamed`: the streamed values of the contracts the daemon's latest beat holds of this
    ticker (_streamed_greeks_for_ticker); `overlay_symbols`: those the feed is delivering now
    (live_market_plane.live_on, the one live rule); `held_symbols`: every contract on that
    beat, ticked or not (_held_option_symbols_for_ticker). A missing beat is not live: those
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
    cells = []
    for cell in surface["cells"]:
        state_row = []
        for pair in cell["contracts"]:  # {call, put} for every column (_gamma_surface_cell_fields)
            legs: dict = {}
            leg_states: list[str] = []
            for side in ("call", "put"):
                sym = pair.get(side)
                if not sym:
                    continue
                greeks = streamed.get(sym)
                if sym in overlay_symbols:
                    leg_state = "live"
                elif sym in streamed:
                    leg_state = "stale"
                elif sym in held_symbols:
                    leg_state = "pending"
                else:
                    leg_state = "unavailable"
                leg_states.append(leg_state)
                legs[side] = {
                    "symbol": sym,
                    "state": leg_state,
                    "ts_recv": _leg_stream_ts_recv(greeks),
                }
            if not leg_states:  # the expiry lists no contract at this strike: nothing streams
                state_row.append(None)
                continue
            received = [leg["ts_recv"] for leg in legs.values() if leg["ts_recv"] is not None]
            legs["state"] = _stream_state_of(leg_states)
            legs["title"] = _stream_cell_title(legs["state"], min(received) if received else None)
            state_row.append(legs)
        cells.append({**cell, "stream": state_row})
    return {
        **surface,
        "cells": cells,
        # each expiry column's state, from its cells' states -- the column header's status
        "stream_by_expiry": {
            e["expiry"]: _stream_state_of(
                [row["stream"][j]["state"] for row in cells if row["stream"][j]]
            )
            for j, e in enumerate(surface["expirations"])
        },
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

#: per ticker, the beat its open surface was last stamped from (_feed_stamp_key: the socket open,
#: the surface's contracts the daemon holds, the option market open), by its pricing
#: (_publish_levels) or a restamp, so a beat that changes none of them for a surface does not
#: restamp or republish it
_last_feed_stamp: dict[str, tuple] = {}


def restamp_off_the_loop() -> None:
    """Take the daemon's beat (the feed's callback, on the event loop) to the pricing thread.

    The surfaces are stamped where they are priced (_chain_pricing), never on the event loop,
    whose one reader takes Schwab's stream (docs/DATA_FLOW.md §4.1). The restamp is at the
    instant it runs, as a pricing is (_price_waiting_chain): one that waited behind a pricing
    is judged by the beat of then, not by the time it was queued.
    """
    _chain_pricing.submit(lambda: restamp_open_surfaces(time_et.now())).add_done_callback(
        _restamp_ended
    )


def _restamp_ended(done: Future) -> None:
    """Log a restamp that ended on an error, with its traceback; the next beat restamps."""
    if done.exception() is not None:
        e = done.exception()
        log.warning("restamping the surfaces failed: %s", e, exc_info=e)


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
    "forces",
    "desk",
    "liquidity",
)


def _levels_changed(tk: str) -> None:
    """Tell the pages on `tk` (its key) that its levels changed: the socket sends them again."""
    live_ui.changed(app.state, tk, *LEVELS_PANELS)


def flow_changed(sym: str) -> None:
    """Tell the pages on Schwab's symbol `sym` that its quote or book changed (FLOW_PANELS)."""
    live_ui.changed(app.state, ticker_storage_key(sym), *FLOW_PANELS)


def _surface_symbols(surface: dict) -> list[str]:
    """Return every contract a heatmap's cells name."""
    return [
        s
        for cell in surface["cells"]
        for pair in cell["contracts"]
        for s in (pair["call"], pair["put"])
        if s
    ]


def _feed_stamp_key(feed: lmp.FeedNow, symbols: list[str], now: float) -> tuple:
    """Return what a heatmap's stamp takes from one beat (`feed`) at `now`.

    That is whether Schwab's socket is open, which of the heatmap's `symbols` the daemon holds on
    LEVELONE_OPTIONS, and whether the option market is open.
    """
    socket_open = lmp.feed_up(feed)
    held = feed.held.get("LEVELONE_OPTIONS", frozenset()) if socket_open else frozenset()
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
    thread, the one writer of the levels, so the cache's lock is held only to read and to store.
    """
    feed = lmp.feed_now(now)
    with _terrain_cache_lock:
        cached = list(_terrain_cache.items())
    for tk, levels in cached:
        surface = levels.gamma_surface
        if surface is None:  # this ticker's levels hold no surface (no price or no book)
            continue
        symbols = _surface_symbols(surface)
        key = _feed_stamp_key(feed, symbols, now)
        if _last_feed_stamp.get(tk) == key:
            continue
        _last_feed_stamp[tk] = key
        held = key[1]
        streamed = {}
        for sym in symbols:
            greeks = get_stream_greeks(sym)
            if greeks:
                streamed[sym] = greeks
        live = lmp.live_symbols(feed, streamed, "LEVELONE_OPTIONS", now)
        stamped = _stamp_gamma_surface_cell_stream_state(surface, streamed, live, held)
        stamped["surface_seq"] = _next_gamma_surface_seq(tk, now)
        with _terrain_cache_lock:
            _terrain_cache[tk] = replace(levels, gamma_surface=stamped)
        _levels_changed(tk)


#: The heatmap header's chip, per coverage state: ALL STREAMING only when every cell on screen is
#: live (every visible heatmap cell is an exact option contract receiving streamed Schwab
#: updates). Never the bare word LIVE: that is the
#: price feed's word in the header.
COVERAGE_LIVE, COVERAGE_PARTIAL, COVERAGE_WARMING, COVERAGE_EXPIRED = (
    "live",
    "partial",
    "warming",
    "expired",
)


def _stream_coverage(cells: list, cols: list[int], expired_only: bool) -> dict:
    """How many of the heatmap's `cells` (the window on screen, _surface_view) are live.

    Over the columns `cols` that can stream (an expired column's contracts never will;
    `expired_only`: every column drawn has expired). Only cells with a contract count (a strike an
    expiry does not list was never a data point). Returns the counts by cell state, the share live
    rounded down (100 only when every cell is live), and the header's words: `state`, `label`,
    `title`.
    """
    counts = {"live": 0, "partial": 0, "stale": 0, "pending": 0, "unavailable": 0}
    for cell in cells:
        for j in cols:
            pair = cell["contracts"][j]
            if pair["call"] or pair["put"]:
                counts[cell["stream"][j]["state"]] += 1
    cells_n = sum(counts.values())
    live_pct = 100 * counts["live"] // cells_n if cells_n else None
    if not cells_n and expired_only:
        state, label, title = (
            COVERAGE_EXPIRED,
            "EXPIRED",
            "every column on screen has expired: none streams",
        )
    elif not cells_n:
        state, label, title = COVERAGE_WARMING, "WARMING", "no cell on screen has a contract yet"
    elif counts["live"] == cells_n:
        state, label, title = COVERAGE_LIVE, "ALL STREAMING", f"all {cells_n} cells streaming"
    else:
        rest = ", ".join(
            f"{n} {k.replace('_', ' ')}" for k, n in counts.items() if n and k != "live"
        )
        # the share rounded down, so it never claims more than streams; under 1% is "<1%", not 0
        state = COVERAGE_PARTIAL
        label = f"{live_pct}% STREAMING" if live_pct or not counts["live"] else "<1% STREAMING"
        title = f"{counts['live']} of {cells_n} cells streaming · {rest}"
    return {
        "cells": cells_n,
        **counts,
        "live_pct": live_pct,
        "state": state,
        "label": label,
        "title": title,
    }


#: the heatmap's measures: GEX and DEX are a value per cell, OI and volume {call, put, total};
#: each None where not known
HEAT_MEASURES = ("gex", "dex", "oi", "volume")


def _measure_values(cell: dict, measure: str) -> list:
    """One heatmap row's values of `measure`, a value or None per column."""
    if measure in ("oi", "volume"):  # {call, put, total}, or None where not known (_legs)
        return [cp if cp is None else cp["total"] for cp in cell[measure]]
    return list(cell[measure])


#: why a strike window is not around the price
WINDOW_NO_PRICE = "no live price: the middle strikes of the chain"


def _window(strikes, spot_strike, scope: str, centre, shift: int) -> tuple[int, int, dict]:
    """Every per-strike panel's rows.

    strike_window around the operator's panned `centre`, else the strike nearest the live price
    (`spot_strike`), moved `shift` rows. Returns (first index,
    last index, the view's {centre, note}): `note` says why the rows are not around the price
    (no price and no pan), else None.
    """
    lo, hi, c = strike_window(strikes, spot_strike if centre is None else centre, scope, shift)
    note = WINDOW_NO_PRICE if centre is None and spot_strike is None and strikes else None
    return lo, hi, {"centre": c, "note": note}


def _surface_view(
    surf: dict,
    spot_strike,
    scope: str,
    centre,
    shift: int,
    cols: int | None,
    expiry: str | None,
) -> tuple[dict, dict]:
    """Return the heatmap the page draws: (the surface cut to its window, the view).

    Rows: _window.
    Columns: the selected `expiry` alone; else for Auto the nearest `cols` (as many as the page
    fits) that have not expired, for Wider twice that, expired ones after, for All every one;
    with none unexpired, the expired ones (drawn labelled EXPIRED, a past observation). Each cell:
    `spot` (the row at the price). The view: the window's centre and note, the coverage,
    each measure's largest |value| drawn (the colour scale), and `missing_expiry` when the
    selected expiry is not in the surface.
    """
    exps = surf["expirations"]
    every = list(range(len(exps)))
    unexpired = [j for j in every if not exps[j]["expired"]]
    if expiry:
        picked = [j for j in every if exps[j]["expiry"] == expiry]
    elif scope == "all" or cols is None:
        picked = every
    elif scope == "wider":
        picked = sorted((unexpired + [j for j in every if j not in unexpired])[: 2 * cols])
    else:
        picked = (unexpired or every)[:cols]
    lo, hi, view = _window(surf["strikes"], spot_strike, scope, centre, shift)

    def pick(v):
        return [v[j] for j in picked] if isinstance(v, list) else v

    cells = [
        {**{k: pick(v) for k, v in cell.items()}, "spot": cell["strike"] == spot_strike}
        for cell in surf["cells"][lo : hi + 1]
    ]
    streams = [i for i, j in enumerate(picked) if not exps[j]["expired"]]
    max_abs = {}
    for m in HEAT_MEASURES:
        known = [abs(v) for cell in cells for v in _measure_values(cell, m) if v is not None]
        max_abs[m] = max(known) if known else None
    window = {
        **surf,
        "strikes": surf["strikes"][lo : hi + 1],
        "expirations": [exps[j] for j in picked],
        "cells": cells,
    }
    return window, {
        **view,
        "scope": scope,
        "coverage": _stream_coverage(cells, streams, bool(picked) and not streams),
        "max_abs": max_abs,
        "missing_expiry": expiry if expiry and not picked else None,
    }


def _contract_ticker(sym: str) -> str | None:
    """Return the ticker whose chain Schwab listed `sym` in, or None.

    The same rule for every instrument, whatever the contract's root (SPXW and SPX are both
    $SPX's).
    """
    with _terrain_cache_lock:
        return next(
            (tk for tk, levels in _terrain_cache.items() if sym in levels.contracts),
            None,
        )


def _closed_since(now: datetime, product: str) -> datetime | None:
    """Return the ticker's last option close while its option market is closed at `now`.

    None while it is open, or while Schwab's /markets answer for today is not held.
    """
    return options_closed_at(now, product) if option_market_open(now, product) is False else None


def _close_capture(tk: str, closed: datetime) -> list | None:
    """Return the ticker's stored close values, or None when none is stored.

    Its two newest market days' captures, when the newest was taken at or after `closed`.
    """
    stored = last_capture_per_day(get_db().db_path, tk, 2)
    return stored if stored and stored[0]["ts_utc"] >= closed.timestamp() else None


def _priced_at(tk, new_chain, chain_spot, previous, now):
    """Return the price a publication of `tk`'s levels is computed at: (price, source, time).

    A chain's spot, a stored capture's or a delivered chain's: Schwab's LAST_PRICE when the
    chain was complete, with its trade time (SPOT_SOURCE_NONE when the daemon held no price,
    as a capture stored without one reads); for a streamed tick, the live price, newer than any
    the levels hold, or the last one published while Schwab has sent this program none.
    """
    if new_chain:
        source = SPOT_SOURCE_NONE if chain_spot[0] is None else SPOT_SOURCE_PLANE
        return chain_spot[0], source, chain_spot[1]
    live = resolve_spot(tk, now=now.timestamp())
    return previous.priced_at if live[0] is None else live


def _publish_levels(
    tk: str,
    chain: list | None = None,
    fetched_ts: float | None = None,
    *,
    chain_spot: tuple = (None, None),
    captures: list | None = None,
    now: datetime,
) -> TerrainSnapshot | None:
    """Produce a ticker's levels, per-strike rows and gamma-surface grid: THE producer of them.

    Prices the ticker's chain once -- each contract with its newest values, the stream's or its
    /quotes answer's (overlay_streamed_contract_fields) -- and publishes all three together, so the
    heatmap, Strike Detail and Key Levels always show one computation. A delivered chain is passed
    in with its spot (`chain_spot`: Schwab's LAST_PRICE when the chain was complete and its trade
    time; (None, None) when the daemon held none); a tick (a streamed value, or a /quotes answer)
    passes none and the kept chain is repriced at the live price (resolve_spot) with every value
    received since. Once that ticker's option window has
    ended, a
    later publication keeps the spot already published, so a later equity print does not move
    the close book. Called only on the one pricing thread
    (_price_chain), so each publication is computed from inputs read after the one it replaces.
    `captures` (startup
    and a closed market, DATA_FLOW decision 7) are the two newest market days' stored captures,
    read once: the newest is priced at that capture's chain spot (one stored without it has no
    price), valued at its own time, or at that ticker's option close when the capture is past
    it, and both feed the forces and prior-day rows. `now`: the instant of this publication.
    A chain that is not a capture is valued then, or at that ticker's option close once it has
    passed. Inside that window each contract's newest values price over the chain (the stream's,
    or its /quotes answer's when that was received since the chain began), and each leg's age
    is taken. Outside it the close values are the balance until the next open: the first chain
    begun at or after the close, the one published or the ticker's stored capture taken then,
    priced as Schwab sent it, a reported 0 included; nothing Schwab sends later (a chain, a
    pushed value) replaces it. Until the close values are held, a chain is priced as sent.
    Returns the snapshot, or None when there is no chain to price.
    """
    previous = published_levels(tk)
    product = option_close_product(tk)
    closed = _closed_since(now, product)
    if closed is not None:
        # the close values stand, and a value pushed after the close (no chain) changes nothing
        if previous is not None and (
            previous.computed_ts_utc >= closed.timestamp() or (chain is None and not captures)
        ):
            return previous.snap
        captures = captures or _close_capture(tk, closed)
    capture = captures[0] if captures else None
    if capture is not None:
        chain, fetched_ts = capture["contracts"], capture["ts_utc"]
        chain_spot = capture["spot"], capture["spot_ts"]
    new_chain = chain is not None
    if chain is None:
        if previous is None or not previous.chain:
            return None
        chain, fetched_ts = previous.chain, previous.computed_ts_utc
    begun = datetime.fromtimestamp(fetched_ts, ET)
    valued_at = valuation_instant(begun if capture is not None else now, product)
    priced_at = _priced_at(tk, new_chain, chain_spot, previous, now)
    if (
        capture is None
        and valued_at < now
        and previous is not None
        and previous.snap.spot is not None
    ):
        # the window has ended: the spot already published is the close, and a later print is not
        spot, spot_source, spot_ts = (
            previous.snap.spot,
            previous.spot_source,
            previous.spot_as_of_ts_utc,
        )
    else:
        spot, spot_source, spot_ts = priced_at
    # the ticker's contracts are the ones Schwab listed in its newest chain
    listed = {c.symbol: c for c in chain if c.symbol} if new_chain else previous.contracts
    # one read of the heartbeat: pricing and the cell stamp share it
    feed = lmp.feed_now(now.timestamp())
    streamed = _streamed_greeks_for_ticker(listed, now.timestamp(), feed)
    feed_live = lmp.live_symbols(feed, streamed, "LEVELONE_OPTIONS", now.timestamp())
    held = set(_held_option_symbols_for_ticker(listed, now.timestamp(), feed))
    # inside the window each contract's newest values (the stream's, or its /quotes answer's
    # when that was received since this chain began); the close values are the chain as sent.
    # The cell stamp says whether that stream is live.
    quoted = rest_quotes(listed, fetched_ts)
    priced, n_live = (
        overlay_streamed_contract_fields(chain, streamed, held, quoted)
        if closed is None
        else (chain, 0)
    )
    live_syms = _overlaid_symbols(chain, priced)
    pushed_ts = [
        ts
        for s in live_syms
        if s in streamed and (ts := _leg_stream_ts_recv(streamed[s])) is not None
    ]
    # a contract the stream does not hold was given its /quotes answer: that answer's receive time
    quoted_ts = [quoted[s][0] for s in live_syms if s not in held]
    snap = compute_terrain(tk, priced, spot, now=valued_at)
    # the values read from the stored chain captures (forces, the prior day's per-strike rows)
    # change only with a new capture or a new chain day: computed then, once, for all readers
    captures_key = (
        (newest_capture_ts(get_db().db_path, tk), et_date_str_from_ts_utc(float(fetched_ts)))
        if new_chain
        else previous.captures_key
    )
    if previous is not None and previous.captures_key == captures_key:
        forces, prior = previous.forces, previous.prior_day
    else:
        stored = captures if captures is not None else last_capture_per_day(get_db().db_path, tk, 2)
        # This publication priced a stored capture, so its charm map is that newer capture.
        # A live chain is not that capture: the same function then runs once on the banked one.
        held_charm = snap.charm_by_strike if captures and captures[0]["spot"] is not None else None
        forces = _forces_from_captures(tk, stored, held_charm)
        prior = _prior_day(tk, stored, fetched_ts)
    surface = None
    if spot is not None and snap.books:
        projected = project_gamma_surface(priced, snap.books)
        projected.update(
            spot=float(spot),
            spot_source=spot_source,
            spot_as_of_ts_utc=spot_ts,
            stream_overlay_contracts=n_live,
            stream_overlay_symbols=live_syms,
            stream_overlay_computed_ts_utc=now.timestamp(),
        )
        surface = _stamp_gamma_surface_cell_stream_state(projected, streamed, feed_live, held)
        surface["surface_seq"] = _next_gamma_surface_seq(tk, now.timestamp())
        # a later beat that differs from this one restamps it (restamp_open_surfaces)
        _last_feed_stamp[tk] = _feed_stamp_key(feed, _surface_symbols(surface), now.timestamp())
    levels = PublishedLevels(
        snap=snap,
        computed_ts_utc=fetched_ts,
        levels_ts_utc=max([fetched_ts, *pushed_ts, *quoted_ts]),
        chain_basis=capture["basis"] if capture is not None else CAPTURE_BASIS,
        spot_source=spot_source,
        spot_as_of_ts_utc=spot_ts,
        priced_at=priced_at,
        gamma_surface=surface,
        vanna_rows=_vanna_rows(snap),
        charm_rows=_charm_rows(snap),
        # every ticker keeps its chain and its heatmap, so a ticker put on screen shows at once
        chain=chain,
        priced_chain=priced,
        contracts=listed,
        forces=forces,
        prior_day=prior,
        captures_key=captures_key,
    )
    with _terrain_cache_lock:
        _terrain_cache[tk] = levels
    _levels_changed(tk)
    if new_chain:
        live_ui.changed(app.state, tk, *CHAIN_PANELS)
    return snap


#: the levels whose crossing by spot is recorded, with their display names
CROSS_LEVELS = (
    ("call_wall", "Call g-Wall"),
    ("put_wall", "Put g-Wall"),
    ("gamma_flip", "Gamma Flip"),
    ("lvp", "Net call Γ peak"),
    ("hvp", "Net put Γ peak"),
    ("max_pain", "Max Pain"),
    ("call_delta_wall", "Call d-Wall"),
    ("put_delta_wall", "Put d-Wall"),
)


#: ticker -> the live price at its last streamed equity quote: the price before the next one (a
#: cross needs both, and the price row holds only the newest); read and written on the event loop
_last_tick_spot: dict[str, float | None] = {}


def _level_crosses_at(
    published: TerrainSnapshot, before: float | None, spot: float | None
) -> list[tuple]:
    """(level value, level name, direction) for each `published` level the price crossed.

    Going from `before` to `spot` (terrain_read.crossed).
    """
    return [
        (getattr(published, k), name, side)
        for k, name in CROSS_LEVELS
        if (side := crossed(getattr(published, k), before, spot)) is not None
    ]


#: seconds a level's cross in one direction holds back the next in that direction (a price
#: wavering on a level); a reversal is stored at once
LEVEL_CROSS_HOLD_S = 60.0


def _log_level_crosses(
    tk: str, spot: float, crosses: list[tuple], now: float, now_text: str
) -> None:
    """Store the crosses _level_crosses_at found, hold them for live readers, tell the open pages.

    Each is stored unless the ticker's held crosses have the same level's cross in the same
    direction from the last LEVEL_CROSS_HOLD_S. Runs on the pricing thread; a failed store is
    logged.
    """
    try:
        with _crosses_lock:
            recent = {
                (c["level_name"], c["direction"])
                for c in _held_crosses(tk)
                if c["ts_utc"] >= now - LEVEL_CROSS_HOLD_S
            }
        logged = get_db().record_level_crosses(
            [
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
                if (name, side) not in recent
            ]
        )
    except Exception:
        log.exception("level crosses of %s at %s not stored: %s", tk, spot, crosses)
        return
    if logged:
        with _crosses_lock:
            held = _held_crosses(tk)
            held.extend(logged)
            del held[:-CROSSES_KEPT]
        _levels_changed(tk)


def _vanna_rows(snap: TerrainSnapshot) -> list:
    """[strike, net dealer vanna] for every strike whose vanna is known, from the published book.

    Each strike's net_vanna exactly as compute_exposures_by_strike computed it (+call/-put).
    """
    exposures, _diag = merge_exposure_books(snap.books.values())
    rows = []
    for k, b in exposures.items():
        net = bucket_metric(b, "net_vanna")
        if net is None:
            continue
        rows.append([float(k), net])
    rows.sort(key=lambda r: r[0])
    return rows


def _charm_rows(snap: TerrainSnapshot) -> list:
    """[strike, net dealer charm] from the published charm map (the charm walls' own), exact."""
    return sorted(
        [float(k), float(b["net_charm"])]
        for k, b in snap.charm_by_strike.items()
        if b.get("net_charm") is not None
    )


def _tick_ticker(sym: str) -> str | None:
    """Return the cached ticker a streamed symbol moves.

    The equity itself, or an option contract's underlying.
    """
    if not vendor_option_root(sym):
        return ticker_storage_key(sym)
    return _contract_ticker(sym)


def _on_stream_tick(sym: str) -> None:
    """Take one tick of `sym`.

    Called by the live feed, on the event loop, for every streamed equity quote, every option
    quote carrying Greeks or volume, and every contract of a /quotes answer. An equity quote
    checks the ticker's levels for a cross at the live price (stored off the event loop); a
    ticker a page shows (_gamma_surface_wanted) is queued for a reprice with every value Schwab
    has sent (one waits per ticker, so the reprice that runs takes the newest). A ticker no page
    shows is priced by each chain the daemon delivers, and repriced when a page selects it
    (ticker_selected). Returns at once.
    """
    tk = _tick_ticker(sym)
    if tk and not vendor_option_root(sym):
        now = time_et.now()
        spot, _source, _ts = resolve_spot(tk, now=now)
        before, _last_tick_spot[tk] = _last_tick_spot.get(tk), spot
        published = published_levels(tk)
        crosses = _level_crosses_at(published.snap, before, spot) if published is not None else None
        if crosses:
            _chain_pricing.submit(
                _log_level_crosses,
                tk,
                spot,
                crosses,
                now,
                datetime.fromtimestamp(now, ET).strftime("%Y-%m-%d %H:%M:%S ET"),
            )
    if tk and _gamma_surface_wanted(tk):
        _wait_to_price(tk, REPRICE)


def ticker_selected(tk: str) -> None:
    """Queue a reprice of `tk` (its key), which a page has just selected (live_ui)."""
    _wait_to_price(tk, REPRICE)


#: prices every ticker's levels, off the event loop, one at a time
_chain_pricing = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chain-pricing")
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
_chains_waiting: dict[str, tuple[str, list | None, float | None, tuple | None]] = {}
_chains_waiting_lock = threading.Lock()
#: the tickers the daemon has delivered a chain for since the console started: their stored
#: capture is older and is not priced as the book, unless it holds the close values
#: (_publish_levels)
_chains_delivered: set[str] = set()


def _on_chain(
    ticker: str, contracts: list | None, ts: float, reason: str | None, spot: tuple | None
) -> None:
    """Take one chain: the feed's chain callback (streaming.assemble_chain_part), on the event loop.

    A whole chain the daemon fetched is priced on a pricing thread at its one spot (spot, trade
    time); a chain it could not deliver keeps the ticker's last levels, which then say why no
    newer chain came.
    """
    tk = ticker_storage_key(ticker)
    if contracts is None:
        _terrain_refresh_last_error[tk] = f"chain fetch failed ({reason})"
        return
    _wait_to_price(tk, DELIVERED, contracts, ts, spot)


def _wait_to_price(
    tk: str,
    what: str,
    contracts: list | None = None,
    ts: float | None = None,
    spot: tuple | None = None,
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
        _chain_pricing.submit(_price_waiting_chain)
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
    _price_chain(tk, what, contracts, ts, spot, now_et())


def _price_chain(
    tk: str,
    what: str,
    contracts: list | None,
    fetched_ts: float | None,
    spot: tuple | None,
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
            captures = last_capture_per_day(get_db().db_path, tk, 2)
            if captures:
                _publish_levels(tk, captures=captures, now=now)
            return
        # the chain as the sweep read it, once (complete_chain_capture.chain_messages)
        _publish_levels(tk, contracts, fetched_ts, chain_spot=spot, now=now)
        _terrain_refresh_last_error.pop(tk, None)
    except Exception as e:  # kept as the ticker's reason, and logged
        _terrain_refresh_last_error[tk] = f"pricing the chain failed: {type(e).__name__}: {e}"
        log.warning("pricing the chain of %s failed: %s", tk, e, exc_info=True)


#: what the console takes from the daemon's bus (start_order_flow_stream, at startup): each
#: streamed tick, each chain the daemon fetched, and each beat of the daemon's status, the last
#: restamped on the pricing thread
FEED_CALLBACKS = {
    "on_tick_callback": _on_stream_tick,
    "on_chain_callback": _on_chain,
    "on_feed_callback": restamp_off_the_loop,
    "on_flow_callback": flow_changed,
}


STATUS_EVERY_SEC = 60.0
#: the daemon writes a feed-status row every 60 s; older than this, the record has stopped
FEED_RECORD_STALE_SEC = 150.0


def _feed_record_state(path: Path, now: float) -> str:
    """How old the newest stream_feed_status row in the stream database at `path` is at `now`.

    It proves the whole path (the daemon's loop, the bus, the writer, the database) wrote this
    minute.
    """
    if not path.is_file():
        return "feed record: NO DATABASE"
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='stream_feed_status'"
        ).fetchone():
            return "feed record: none yet"
        newest = conn.execute("SELECT MAX(ts) FROM stream_feed_status").fetchone()[0]
    finally:
        conn.close()
    if newest is None:
        return "feed record: none yet"
    age = now - float(newest)
    return (
        f"feed record: written {age:.0f}s ago"
        if age <= FEED_RECORD_STALE_SEC
        else f"FEED RECORD STALE: last written {age / 60:.0f} min ago"
    )


def _status_line(now: float) -> str:
    """One line for the console window: is each part working at `now`, from its own check."""
    st = lmp.daemon_status(now)
    watchlist = _watchlist()
    if st is None and watchlist is not None:
        prices = f"last watchlist: {len(watchlist)} tickers (daemon not reporting)"
    elif watchlist is not None:
        priced = sum(1 for tk in watchlist if resolve_spot(tk, now=now)[0] is not None)
        prices = f"live prices: {priced} of {len(watchlist)} watchlist tickers"
    else:  # no list has arrived: the list is unknown
        prices = "live prices: WATCHLIST UNKNOWN (no current daemon heartbeat)"
    with _terrain_cache_lock:
        as_of = [levels.levels_ts_utc for levels in _terrain_cache.values()]
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
            _feed_record_state(canonical_stream_db_path(), now),
            (
                f"chains: the daemon's last round of the watchlist took {round_sec:.0f} s"
                if round_sec
                else "chains: the daemon's first round is running"
            ),
        ]
    )


#: while the console waits at its start, what it waits for is logged this often, with how long
WAITING_LOG_EVERY_SEC = 5.0


def _wait_for(what: str, ready) -> None:
    """Wait until `ready()` (or the loop stops), logging what for and for how long.

    Then log how long it took once ready.
    """
    started = time_et.elapsed()
    next_log = started
    while _terrain_loop_running and not ready():
        if time_et.elapsed() >= next_log:
            log.info("waiting for %s (%.0f s so far)", what, time_et.elapsed() - started)
            next_log += WAITING_LOG_EVERY_SEC
        time.sleep(0.5)
    if ready():
        log.info("done waiting for %s after %.1f s", what, time_et.elapsed() - started)


def refresh_not_live_pages(now: float) -> None:
    """Tell each open page whose ticker's price or levels are not live at `now` to read again.

    The price is price_state's, the published levels levels_state's; the page reads its levels
    again, so each not-live age (price_mark, terrain_staleness) keeps counting while nothing new
    arrives: a stopped price, or the close values after the ticker's own option close. The levels
    loop calls it every STATUS_EVERY_SEC; a page whose price and levels are both live is told by
    each new price and chain instead.
    """
    for tk in live_ui.selected(app.state):
        levels, verdict = terrain_cache_get(tk, now)
        if price_state(tk, now)[0] != lmp.LIVE or (
            levels is not None and verdict["levels_state"] != lmp.LIVE
        ):
            _levels_changed(tk)


def _terrain_loop() -> None:
    """Run the levels loop: the watchlist's stored levels, then the status every STATUS_EVERY_SEC.

    The stored levels come once the daemon has said what the watchlist is (queued behind the
    delivered chains: _load_stored_levels); then every STATUS_EVERY_SEC the status line is logged,
    each open page whose price or levels are not live is told to read its levels again
    (refresh_not_live_pages) and the price levels of a new session or a new ticker are published.
    The chains, and the bars each ticker's price levels are built from, arrive from the daemon
    (_on_chain, _bar_writer).
    """
    _wait_for(
        "the capture daemon's heartbeat (it says what the watchlist is)",
        lambda: _watchlist() is not None,
    )
    watchlist = _watchlist()
    _load_crosses(watchlist)
    _publish_missing_price_levels(watchlist, now_et())
    queued = _load_stored_levels(watchlist)
    log.info(
        "Ready: the stored levels of %d of %d watchlist tickers are queued to price (session: %s); "
        "the daemon's chains price them from here.",
        queued,
        len(watchlist),
        session_label(now_et()),
    )
    next_status = time_et.elapsed() + STATUS_EVERY_SEC
    while _terrain_loop_running:
        time.sleep(1.0)
        try:
            if time_et.elapsed() >= next_status:
                next_status = time_et.elapsed() + STATUS_EVERY_SEC
                now = time_et.now()
                log.info(_status_line(now))
                refresh_not_live_pages(now)
                watchlist = _watchlist()
                if watchlist is not None:
                    _publish_missing_price_levels(watchlist, now_et())
        except Exception as e:  # the status line says it failed, never silence
            log.warning("levels loop: %s: %s", type(e).__name__, e, exc_info=True)
    log.info("Terrain loop stopped")


def _load_stored_sessions(path: Path) -> None:
    """Schwab's /markets answers as the daemon recorded them in the stream database at `path`.

    Oldest first, so a stored chain is priced on the sessions of its expiries. No database or
    table yet, as at the first start before the daemon's, is no answer held. A database that
    cannot be read, or a row that cannot be taken, stops the console's start with its error.
    """
    if not path.is_file():
        return
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='stream_markets_raw'"
        ).fetchone():
            return
        rows = conn.execute(
            "SELECT native_json FROM stream_markets_raw WHERE status = 200 ORDER BY ts_recv"
        ).fetchall()
    finally:
        conn.close()
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
    """Start the levels thread.

    Refuses to start under pytest: tests call _terrain_loop's parts directly.
    """
    global _terrain_loop_running, _terrain_loop_thread
    if os.environ.get("PYTEST_CURRENT_TEST"):
        log.debug("terrain loop not started: running under pytest")
        return
    if _terrain_loop_running:
        return
    _terrain_loop_running = True
    _terrain_loop_thread = threading.Thread(target=_terrain_loop, name="terrain-loop", daemon=True)
    _terrain_loop_thread.start()


def stop_terrain_loop() -> None:
    """Stop the levels thread, and drop every pricing that waits (_chains_waiting).

    The program is stopping: what waits would be priced for pages that are closing, and the
    program's exit waits for the pricing thread, so only the pricing already running finishes.
    The chains stay stored and are priced at the next start (_load_stored_levels).
    """
    global _terrain_loop_running
    _terrain_loop_running = False
    with _chains_waiting_lock:
        _chains_waiting.clear()


def _todays_candles(tk: str, now: datetime) -> list[Candle]:
    """Today's daily candle as Schwab pushes it: one candle, or none yet.

    LEVELONE_EQUITIES OPEN_PRICE, HIGH_PRICE, LOW_PRICE, REGULAR_MARKET_LAST_PRICE and
    TOTAL_VOLUME, as the price row holds them (live_market_plane.get_quote). Only regular session
    trades set the first three, and each is 0 until one does (Schwab Streamer API §3.1, fields
    17, 10 and 11); the last stands from the session's close while the extended hours trade on.
    None before today's regular session Schwab sent (/markets) opens, on a day without one, and
    until the ticker's first regular trade. Its time is the session's open.
    """
    s = session(now.astimezone(ET).date().isoformat())
    row = lmp.get_quote(tk)
    if s is None or not s.regular or now < s.regular[0][0] or row is None:
        return []
    day = [row["open_price"], row["high_price"], row["low_price"], row["regular_last"]]
    if None in day or row["open_price"] == 0:
        return []
    return [Candle(s.regular[0][0].timestamp(), *day, row["total_volume"])]


def _daily_candles(tk: str, now: datetime) -> list[Candle]:
    """`tk`'s daily candles through today, every one Schwab's: the ATR's and the daily chart's.

    Schwab's /pricehistory series as the bar writer holds it (_series; none from Schwab yet: none
    held), today's candle of it once Schwab's regular window for today has ended and Schwab has
    sent it. Until then today's is the one Schwab pushes (_todays_candles).
    """
    today = now.astimezone(ET).date()
    s = session(today.isoformat())
    ended = s is not None and bool(s.regular) and now >= s.regular[-1][1]
    with _bars_lock:
        sent = list(_series[(tk, "1d")]) if (tk, "1d") in _series else []
    daily = [
        c
        for day, c in ((datetime.fromtimestamp(c.ts, ET).date(), c) for c in sent)
        if day < today or (ended and day == today)
    ]
    if daily and datetime.fromtimestamp(daily[-1].ts, ET).date() == today:
        return daily
    return daily + _todays_candles(tk, now)


def _atr(ticker: str, now: datetime) -> Atr:
    """Return the ticker's daily, weekly and monthly ATR at `now`, each from Schwab's candles.

    The daily from _daily_candles; the weekly and monthly from Schwab's own weekly and monthly
    /pricehistory series as the bar writer holds them (_series). Too few reads as None.
    """
    tk = ticker_storage_key(ticker)
    with _bars_lock:
        weekly, monthly = (
            list(_series[(tk, s)]) if (tk, s) in _series else [] for s in ("1w", "1mo")
        )
    return compute_atrs(_daily_candles(tk, now), weekly, monthly)


def _atr_fields(tk: str, now: datetime) -> dict:
    """atr_daily / atr_weekly / atr_monthly at `now`. A horizon that cannot be computed is None."""
    a = _atr(tk, now)
    return {"atr_daily": a.daily, "atr_weekly": a.weekly, "atr_monthly": a.monthly}


# ── Per-strike gamma and volume bars for the histogram panel ─────────────────
# Today's per-strike dealer gamma and traded volume, plus the previous market day's last chain
# capture (the day-over-day migration), each in three expiry scopes (all / near<=7DTE / far).
# Read-only, no Schwab call. Bar heights use the same exposure math as the levels.
def _prior_day(tk: str, captures: list, chain_ts: float) -> TerrainSnapshot | None:
    """Return the levels of the previous market day's close before the day of the chain's.

    The one producer (compute_terrain) on that day's stored capture, at its own spot and time:
    its per-strike rows and its walls and flip. None with no prior day captured, or none stored
    with its spot. On a closed market today's rows ARE the newest capture, so the day before is
    the chain's day's, not the wall clock's (which picks that same capture and compares it with
    itself). Run by _publish_levels when the ticker's newest capture or its chain's day changes,
    on the same two newest market days' captures the forces read: the chain's day is today or
    the newest capture's, so the day before it is one of those two.
    """
    chain_day = et_date_str_from_ts_utc(float(chain_ts))
    prior = next((c for c in captures if c["et_date"] < chain_day), None)
    if prior is None or prior["spot"] is None:
        return None
    return compute_terrain(
        tk,
        prior["contracts"],
        float(prior["spot"]),
        now=datetime.fromtimestamp(prior["ts_utc"], ET),
    )


def _max_abs_row(rows) -> list | None:
    """Return the row ([strike, value, ...]) with the largest |value| of every strike.

    None with no known value.
    """
    known = [r for r in rows if r[1] is not None]
    return max(known, key=lambda r: abs(r[1])) if known else None


def _windowed(rows: list, spot_strike, scope: str, centre, shift: int) -> tuple[list, dict]:
    """`rows` ([strike, value, ...], ascending) as a panel draws them.

    _window's rows, with its view {centre, note, max_abs}: the centre strike (send it back to pan
    from it), why the rows are not around the price, and the largest |value| in the window (the
    bar and colour scale), None when no value is known.
    """
    lo, hi, view = _window([r[0] for r in rows], spot_strike, scope, centre, shift)
    win = rows[lo : hi + 1]
    known = [abs(r[1]) for r in win if r[1] is not None]
    return win, {**view, "max_abs": max(known) if known else None}


def strikes(ticker: str, now: float, params: dict) -> dict:
    """Return the per-strike rows at `now` in the window `params` ask for (the `strikes` panel).

    `ticker` is the levels' own key; `params` the reader's window (_window_asked). The page's
    socket sends it to GEX by Strike, the Gamma chart's profile, Right Now's migration and the
    Desk map, each its own panel with its own window (terrain_strikes_payload).
    """
    window = _window_asked(params)
    if isinstance(window, str):
        return unavailable(ticker, window)
    return terrain_strikes_payload(ticker, *window, now)


def terrain_strikes_payload(tk: str, scope: str, centre, shift: int, now: float) -> dict:
    """Return the per-strike rows of the published levels at `now`, each windowed for its panel.

    Windowed by _windowed: today's GEX and volume (all, near, far expiries), the Chart view's DEX
    and OI, with each list's view; the side sums, the largest-GEX strike and the day-over-day
    migration are of every strike.
    """
    # today's per-strike rows: the published levels' own (_publish_levels' `_per_strike`,
    # terrain_engine.per_strike_view: {all, near, far} of [strike, net_gex_1pct$, volume], and
    # the dex and oi rows), served as-is; with no levels published, that view of no book: no rows
    levels, verdict = terrain_cache_get(tk, now)
    # no levels published for tk: no rows, no walls; no prior day captured: no prior rows. The
    # prior day's levels are set with every chain the levels are published from.
    snap = None if levels is None else levels.snap
    prior_day = None if levels is None else levels.prior_day
    rows = per_strike_view({}, {}) if snap is None else snap.per_strike
    prior = per_strike_view({}, {}) if prior_day is None else prior_day.per_strike
    walls = (None, None) if snap is None else (snap.call_wall, snap.put_wall)
    today = {k: rows[k] for k in ("all", "near", "far")}
    measures = {m: rows[m] for m in ("dex", "oi")}

    # the per-side GEX sums, against the spot this payload serves (the one aggregator)
    def _side_sums(rows, s):
        if not rows or s is None:
            return None
        cells = [[float_finite_or_none(x) for x in r[:2]] for r in rows]
        return {
            "gex_below": side_total([c[1] for c in cells if c[0] is not None and c[0] < s]),
            "gex_above": side_total([c[1] for c in cells if c[0] is not None and c[0] > s]),
        }

    live_spot, _live_src, _live_ts = resolve_spot(tk, now=now)  # the one spot on every screen
    migration = {
        sc: positioning_migration(today[sc], prior[sc], *walls) for sc in ("all", "near", "far")
    }
    lists = {**today, **measures}
    windows = {
        name: _windowed(rows, nearest_strike([r[0] for r in rows], live_spot), scope, centre, shift)
        for name, rows in lists.items()
    }
    for sc in ("all", "near", "far"):  # the migration panel scales today's and the prior day's bars
        drawn = {r[0] for r in windows[sc][0]}
        both = [
            abs(v)
            for r in migration[sc]["rows"]
            if r[0] in drawn
            for v in (r[1], r[2])
            if v is not None
        ]
        both += [windows[sc][1]["max_abs"]] if windows[sc][1]["max_abs"] is not None else []
        windows[sc][1]["max_abs_with_prior"] = max(both) if both else None
    return {
        "ticker": tk,
        "today": {sc: windows[sc][0] for sc in ("all", "near", "far")},
        # the Chart view's DEX and OI profiles: each measure's window (terrain_engine
        # _per_strike_measure_rows) and its largest-magnitude row, on screen or not (the label)
        "measures": {
            m: {"rows": windows[m][0], "view": windows[m][1], "max_abs_row": _max_abs_row(rows)}
            for m, rows in measures.items()
        },
        # each scope's window: its centre strike and the largest |value| drawn
        "views": {sc: windows[sc][1] for sc in ("all", "near", "far")},
        "today_side_sums": _side_sums(today["all"], live_spot),
        "spot_strike": nearest_strike([r[0] for r in today["all"]], live_spot),
        # the row with the largest net GEX magnitude, on screen or not (the chart labels it)
        "max_abs_row": _max_abs_row(today["all"]),
        "migration": migration,
        # the call wall, put wall and gamma flip today against the prior day's own
        "level_moves": level_moves(snap, prior_day),
        # the levels verdict these rows carry (LIVE, CLOSE, STALE, NOT LIVE), their time and age
        **verdict,
    }


#: the most 1-minute bars one `bars` panel spans
BARS_LIMIT_MAX = 12000


def bars(ticker: str, now: float, params: dict) -> dict:
    """Return the `bars` panel at `now`: the ticker's bars at chart timeframe `tf`, newest-last.

    The page's socket sends it (live_ui, PAGE_PANELS) to every chart, at once and with each new
    bar (BARS_PANELS). [{t,o,h,l,c,v}] epoch-seconds bar starts (chart_bars), over the span of its
    newest `limit` 1-minute bars, from the bars the console holds (_bars_1m): no database, no
    Schwab call. `last_bar`: the newest completed minute and its label. A `tf` not in
    LEVEL_TIMEFRAMES or a `limit` not a count up to BARS_LIMIT_MAX raises: the socket sends that
    panel's words. `ticker` is the levels' own key.
    """
    tf, limit = _tf_asked(params), params.get("limit")
    if type(limit) is not int or not 1 <= limit <= BARS_LIMIT_MAX:
        raise ValueError(f"limit {limit!r} is not a count from 1 to {BARS_LIMIT_MAX}")
    held = [_bar_dict(c) for c in _bars_1m(ticker, limit)]
    shown = chart_bars(ticker, tf, held, datetime.fromtimestamp(now, ET))
    return {
        "bars": [_lpr.with_change(b) for b in shown],
        "tf": tf,
        "last_bar": {"t": held[-1]["t"], "label": ct_label(held[-1]["t"])} if held else None,
    }


def _tf_bucket_key(t: float, tf: str):
    """Return the chart bar a timestamp belongs to.

    Its ET trading date ("D") or its tf-minute bucket.
    """
    return datetime.fromtimestamp(t, ET).date() if tf == "D" else int(t // (int(tf) * 60))


def aggregate_vwap(rows: list, tf: str) -> list:
    """VWAP rows [t, vwap, +1s, -1s, +2s, -2s] rolled up to the chart timeframe.

    Exactly as aggregate_bars rolls the bars: each bar takes the value as of its last minute,
    stamped with the bar's first minute (the bar's own `t`).
    """
    if tf == "1":
        return [list(r) for r in rows]
    out, cur_key = [], None
    for r in rows:
        k = _tf_bucket_key(float(r[0]), tf)
        if k != cur_key:
            out.append([r[0]] + list(r[1:]))
            cur_key = k
        else:
            out[-1] = [out[-1][0]] + list(r[1:])
    return out


#: the chart timeframes Schwab sends as a /pricehistory series of their own (the daemon's
#: PRICE_HISTORY): chart timeframe -> series
SCHWAB_SERIES = {"5": "5m", "15": "15m", "30": "30m", "D": "1d"}


def chart_bars(tk: str, tf: str, minutes: list[dict], now: datetime) -> list[dict]:
    """`tk`'s bars at chart timeframe `tf` over the span of `minutes` (its 1-minute bars).

    A timeframe Schwab sends (SCHWAB_SERIES) is Schwab's series as the bar writer holds it, but
    for the bar Schwab has not sent whole yet: a minute series' newest bar (forming, or not asked
    again yet; the daemon asks as each completes), which is rolled up (aggregate_bars) from
    Schwab's 1-minute bars; and today's daily candle (_daily_candles). Every other timeframe (3
    and 60 minutes, which Schwab does not send), or one whose series is not held yet, is rolled
    up from the 1-minute bars.
    """
    key = (tk, SCHWAB_SERIES[tf]) if tf in SCHWAB_SERIES else None
    with _bars_lock:
        sent = list(_series[key]) if key in _series else []
    if not sent:
        return aggregate_bars(minutes, tf)
    if tf != "D":
        newest = sent[-1].ts
        first = minutes[0]["t"] if minutes else sent[0].ts
        schwab = [_bar_dict(c) for c in sent if first <= c.ts < newest]
        return schwab + aggregate_bars([m for m in minutes if m["t"] >= newest], tf)
    first_day = datetime.fromtimestamp(minutes[0]["t"], ET).date() if minutes else None
    return [
        _bar_dict(c)
        for c in _daily_candles(tk, now)
        if first_day is None or first_day <= datetime.fromtimestamp(c.ts, ET).date()
    ]


def aggregate_bars(bars: list[dict], tf: str) -> list[dict]:
    """Roll up 1m bars to a chart timeframe: THE chart-timeframe roll-up.

    The timeframe is "1", "3", "5", "15", "30", "60" minutes, or "D" = the ET trading date: first
    open, max high, min low, last close. Volume is the sum only when every minute in the bucket
    reported one -- otherwise None (unknown), never a partial sum or a 0.
    """
    if tf == "1":
        return list(bars)

    def key(t: float):
        return _tf_bucket_key(t, tf)

    out: list[dict] = []
    cur: dict | None = None
    cur_key = None
    for b in bars:
        k = key(float(b["t"]))
        if cur is None or k != cur_key:
            if cur is not None:
                out.append(cur)
            cur = {"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b.get("v")}
            cur_key = k
            continue
        cur["h"] = max(cur["h"], b["h"])
        cur["l"] = min(cur["l"], b["l"])
        cur["c"] = b["c"]
        cur["v"] = None if (cur["v"] is None or b.get("v") is None) else cur["v"] + b["v"]
    if cur is not None:
        out.append(cur)
    return out


#: each per-strike bar panel's published rows and how they are made
STRIKE_BAR_METHODS = {
    "vanna_rows": "the published levels' exposure book -> call_vanna - put_vanna",
    "charm_rows": "the published levels' charm map -> call_charm - put_charm",
}


def strike_bar_payload(tk: str, key: str, scope: str, centre, shift: int, now: float) -> dict:
    """Return a per-strike bar panel's answer at `now` (vanna, charm).

    The published rows `key`, windowed for the panel (_windowed), with the live price and the
    strike nearest it.
    """
    method = STRIKE_BAR_METHODS[key]
    levels = published_levels(tk)
    if levels is None:
        return unavailable(tk, "no levels published for this ticker yet")
    rows = getattr(levels, key)
    spot = resolve_spot(tk, now=now)[0]
    spot_strike = nearest_strike([r[0] for r in rows], spot)
    win, view = _windowed(rows, spot_strike, scope, centre, shift)
    return {
        "ticker": tk,
        "available": bool(rows),
        "spot": spot,
        "spot_strike": spot_strike,
        "rows": win,
        "view": view,
        "scope": scope,
        "reason": None if rows else "no usable strikes for this chain",
        "method": method,
    }


def _window_asked(params: dict) -> tuple[str, float | None, int] | str:
    """Return the window a page's panel parameters ask for: (scope, centre, shift).

    The page sends all three: the scope, one of SCOPES; the centre, a strike or None (follow the
    price); the shift, a whole number of rows. Parameters that ask for none of these: the words
    saying which.
    """
    scope, centre, shift = params.get("scope"), params.get("centre"), params.get("shift")
    if scope not in SCOPES:
        return f"scope {scope!r} is not one of {', '.join(SCOPES)}"
    if centre is not None and (isinstance(centre, bool) or not isinstance(centre, int | float)):
        return f"centre {centre!r} is not a strike"
    if isinstance(shift, bool) or not isinstance(shift, int):
        return f"shift {shift!r} is not a whole number of rows"
    return scope, centre, shift


def strike_bars(key: str, tk: str, now: float, params: dict) -> dict:
    """Return the per-strike bar panel `key` of `tk` at `now` in the window `params` ask for.

    "vanna_rows": net_vanna = call_vanna - put_vanna per strike, across every expiry (the Vanna
    panel). "charm_rows": the charm walls' own map, net_charm = call_charm - put_charm per strike,
    delta-shares/day (the Charm panel).
    """
    window = _window_asked(params)
    if isinstance(window, str):
        return unavailable(tk, window)
    return strike_bar_payload(tk, key, *window, now)


#: the most prints the `tape` panel shows
TAPE_ROWS = 100


def tape(ticker: str, now: float) -> dict:
    """Return the `tape` panel at `now`: the newest option trade prints of the ticker.

    The prints the console builds from Schwab's LEVELONE_OPTIONS as the daemon pushes them
    (the live state's prints, history.recent_prints), of every contract of `ticker` the daemon
    streams
    (_held_option_symbols_for_ticker), merged newest first and capped at TAPE_ROWS across the
    merge, each with its contract's terms and open interest from the chain record and its
    premium (history.tape_row). No aggressor side. `ticker` is the levels' own key.
    """
    held = published_levels(ticker)
    if held is None:
        return unavailable(ticker, "the console holds no chain of this ticker yet", rows=[])
    symbols = _held_option_symbols_for_ticker(held.contracts, now)
    if not symbols:
        return unavailable(ticker, "the daemon streams no option contract of this ticker", rows=[])
    prints = [
        (p, held.contracts[sym])
        for sym in symbols
        for p in recent_prints(sym, get_content_for_symbol(sym), TAPE_ROWS)
    ]
    prints.sort(key=lambda kept: kept[0]["ts_recv"], reverse=True)
    rows = [tape_row(p, contract) for p, contract in prints[:TAPE_ROWS]]
    return {
        "available": bool(rows),
        "rows": rows,
        "reason": None if rows else "no trade prints for these contracts since the console started",
    }


def _venue_asked(params: dict) -> str:
    """Return the Schwab book a panel's `params` name; another raises (the socket sends why)."""
    venue = params.get("venue")
    if venue not in BOOK_VENUES:
        raise ValueError(f"venue {venue!r} is not one of {', '.join(BOOK_VENUES)}")
    return venue


def _tf_asked(params: dict) -> str:
    """Return the chart timeframe a panel's `params` name; another raises."""
    tf = params.get("tf")
    if tf not in LEVEL_TIMEFRAMES:
        raise ValueError(f"tf {tf!r} is not one of {', '.join(LEVEL_TIMEFRAMES)}")
    return tf


def bookmap(ticker: str, params: dict) -> dict:
    """Return the `bookmap` panel: the depth heatmap of the ticker's Schwab book `venue`.

    history.book_heatmap_for_ticker bins the venue's recent books in the console's memory into a
    time x price grid over the newest `minutes`. The window ends at the newest book, never at
    the time of asking. A window not above 0, or longer than the books the console keeps
    (history.BOOKS_KEPT_SEC), raises.
    """
    minutes = params.get("minutes")
    if type(minutes) not in (int, float) or not 0 < minutes <= BOOKS_KEPT_SEC / 60:
        raise ValueError(f"minutes {minutes!r} is not above 0 and at most {BOOKS_KEPT_SEC / 60:g}")
    return book_heatmap_for_ticker(ticker, _venue_asked(params), minutes=minutes)


def forces(ticker: str) -> dict:
    """Return the `forces` panel: the ticker's forces, as the levels producer computed them."""
    held = published_levels(ticker)
    return _forces_absent(ticker) if held is None else held.forces


def _forces_absent(tk: str) -> dict:
    """Return the forces numbers before two market days of captures exist, or when the read fails.

    Each number is None. Nothing stands in for it.
    """
    return {
        "ticker": tk,
        "available": False,
        "doi_below": None,
        "doi_above": None,
        "dex_below_dollars": None,
        "dex_above_dollars": None,
        "charm_below": None,
        "charm_above": None,
    }


def _forces_from_captures(tk: str, captures: list, charm_by_strike: dict | None = None) -> dict:
    """Build the forces rows from banked chains.

    Each day's OI totalled by side of the NEWER capture's spot — bucketing each day by its own
    spot lets the moving boundary masquerade as OI change. DEX is the newer capture's
    net_dex_dollars side sums; CHARM the dealer-signed net_charm below and above spot on the newer
    banked chain. `charm_by_strike` is that capture's map when this publication just priced it.
    Otherwise the same function runs once, at that capture's valuation instant.
    Run by _publish_levels when the ticker's newest capture changes, on `captures`: the two
    newest market days' captures (last_capture_per_day, newest first), read once for it.
    """
    payload: dict = _forces_absent(tk)
    try:
        rows = [
            (c["et_date"], c["spot"], c["contracts"], c["ts_utc"])
            for c in captures
            if c["spot"] is not None
        ]
        if len(rows) >= 2:
            (_, s1, c1, t1), (d0, s0, c0, t0) = rows[0], rows[1]
            # each capture at its own time, or at that day's option close once the capture is past
            # it
            product = option_close_product(tk)
            clock1 = valuation_instant(datetime.fromtimestamp(t1, ET), product)
            clock0 = valuation_instant(datetime.fromtimestamp(t0, ET), product)
            per1 = compute_exposures_by_strike(c1, spot=float(s1), now=clock1, product=product)[0]
            per0 = compute_exposures_by_strike(c0, spot=float(s0), now=clock0, product=product)[0]

            dex1 = {k: bucket_metric(v, "net_dex_dollars") for k, v in per1.items()}
            spot1 = float(s1)

            def _oi_change(in_side) -> float | None:
                """Return the side's open interest on the newer day less the older day's.

                It assumes each capture is the whole chain, where a strike not listed holds no
                contracts.
                """
                totals = [
                    side_total([strike_total_oi(b) for k, b in per.items() if in_side(k)])
                    for per in (per1, per0)
                ]
                return None if None in totals else totals[0] - totals[1]

            # CHARM below/above from the NEWER banked wide chain (full book).
            # Dealer-signed net_charm = call_charm - put_charm per strike.
            charm_below = charm_above = None
            try:
                if isinstance(charm_by_strike, dict):
                    per_ch = charm_by_strike
                else:
                    per_ch = compute_charm_by_strike(c1, spot1, now=clock1, product=product)

                charm_below = side_total([v["net_charm"] for k, v in per_ch.items() if k < spot1])
                charm_above = side_total([v["net_charm"] for k, v in per_ch.items() if k > spot1])
            except Exception as e:
                log.warning("forces charm for %s failed (%s)", tk, e, exc_info=True)
            payload = {
                "ticker": tk,
                "available": True,
                "doi_below": _oi_change(lambda k: k < spot1),
                "doi_above": _oi_change(lambda k: k > spot1),
                "dex_below_dollars": side_total([d for k, d in dex1.items() if k < spot1]),
                "dex_above_dollars": side_total([d for k, d in dex1.items() if k > spot1]),
                "charm_below": charm_below,
                "charm_above": charm_above,
                "older_et_date": d0,
                "method": (
                    "OI side totals of the two captures, each side by the newer capture's spot; "
                    "DEX = net_dex_dollars side sums on the newer capture; "
                    "CHARM = dealer-signed net_charm side sums on the newer capture"
                ),
            }
    except Exception as e:
        log.warning("forces for %s failed (%s)", tk, e, exc_info=True)
        payload = _forces_absent(tk)
    return payload


def _legs(legs: tuple | None) -> dict | None:
    """Return a cell's call/put pair and their total; None when not known."""
    if legs is None:
        return None
    return {"call": legs[0], "put": legs[1], "total": legs[0] + legs[1]}


def _gamma_surface_cell_fields(bucket: dict | None, contracts: dict):
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


def project_gamma_surface(chain: list[OptionContract], books: dict) -> dict:
    """Shape the strike × expiry grid the gamma heatmap draws from `books`.

    `books` are the exposure_books compute_terrain priced `chain` into, so every cell is the
    number the levels and per-strike rows were computed from. No exposure math here. A contract
    with a missing or malformed expiry is counted, never given a column.
    """
    by_expiry: dict[str, list] = {}
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
    excluded_malformed = total_contracts - contracts_used
    strike_set = {float(k) for ex in per_expiry.values() for k in ex}
    expiries = sorted(per_expiry)
    strikes = sorted(strike_set)
    expirations = [{"expiry": e, "dte": exp_dte.get(e)} for e in expiries]
    # Each cell carries every measure its bucket already holds -- GEX, DEX, vanna (call - put,
    # the dealer convention of math_exposure_core._finish_bucket), OI and volume -- so one grid
    # serves every heatmap measure; a measure with no value is None (_gamma_surface_cell_fields).
    cells = []
    for k in strikes:
        row, dex_row, vanna_row, oi_row, vol_row, contracts_row = [], [], [], [], [], []
        for col in expirations:
            e = col["expiry"]
            bucket = per_expiry[e].get(k)  # every column is one of per_expiry's
            legs = {"call": leg_symbol.get((e, k, "call")), "put": leg_symbol.get((e, k, "put"))}
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
        "contracts_excluded_malformed_expiry": excluded_malformed,
    }


def _stamp_columns(surface: dict, now: datetime) -> dict:
    """Stamp the surface's expiration columns at `now` (ET; a browser never decides what day it is).

    `expired` (its expiry is before now's date) and `front` (the nearest expiry that has not
    expired, by Schwab's daysToExpiration). No cell value is touched.
    """
    today = now.strftime("%Y-%m-%d")
    exps = [dict(e, expired=e["expiry"] < today) for e in surface["expirations"]]
    live_cols = [e for e in exps if not e["expired"] and e["dte"] is not None]
    front = min(live_cols, key=lambda e: e["dte"])["expiry"] if live_cols else None
    return {**surface, "expirations": [dict(e, front=e["expiry"] == front) for e in exps]}


def gamma_surface(ticker: str, now: float, params: dict) -> dict:
    """Return the heatmap: the strike x expiration surface the levels producer projected.

    The `surface` panel. Cell = net_gex_1pct, compute_exposures_by_strike; cut to the window the
    page draws (_surface_view: the scope, the panned centre and a drag's shift, _window_asked;
    `cols`, the columns the page fits, a whole number from 1, or None for every column; `expiry`,
    the selected expiry, or None for all), with its `view`: the centre, the coverage words, the
    contracts to stream and the colour scale. Parameters that ask for none of these: the words
    saying which. `ticker` is the levels' own key.
    """
    window = _window_asked(params)
    cols, expiry = params.get("cols"), params.get("expiry")
    if isinstance(window, str):
        return unavailable(ticker, window)
    if "cols" not in params or "expiry" not in params:
        return unavailable(ticker, "the heatmap's window names no cols or no expiry")
    if cols is not None and (isinstance(cols, bool) or not isinstance(cols, int) or cols < 1):
        return unavailable(ticker, f"cols {cols!r} is not a whole number of columns")
    if expiry is not None and not isinstance(expiry, str):
        return unavailable(ticker, f"expiry {expiry!r} is not an expiry date")
    return gamma_surface_payload(ticker, *window, cols, expiry, datetime.fromtimestamp(now, ET))


def gamma_surface_payload(
    tk: str, scope: str, centre, shift: int, cols: int | None, expiry: str | None, now: datetime
) -> dict:
    """Return the heatmap's answer for ticker `tk` at `now` (the `surface` panel).

    With no live surface the answer is "unavailable" with the reason; there is no second source.
    Served with the levels' verdict (levels_verdict) and the chain's and price's times.
    """
    # ---- LIVE: surface projected this cycle from the canonical live terrain wide chain ----
    live, verdict = terrain_cache_get(tk, now.timestamp())
    surf = None if live is None else live.gamma_surface
    _surface_live_spot = resolve_spot(tk, now=now.timestamp())
    if surf is not None:
        spot_strike = nearest_strike(surf["strikes"], _surface_live_spot[0])
        # the surface's state is the levels' (terrain_staleness: LIVE, CLOSE, STALE, NOT LIVE);
        # whether the cells on screen are streaming is the view's coverage
        window, view = _surface_view(
            _stamp_columns(surf, now), spot_strike, scope, centre, shift, cols, expiry
        )
        return {
            # every cell Schwab listed is drawn: a cell without a value is None, drawn "-"
            "ticker": tk,
            "symbol": tk,
            "available": True,
            "reason": None,
            "source": "terrain_live_cache",
            **levels_verdict(verdict),
            "chain_basis": live.chain_basis,
            **window,
            "view": view,
            # one spot on every screen: the live price, the header's own rule, after the surface's
            # own keys so its stamp cannot overwrite it.
            "spot": _surface_live_spot[0],
            "spot_source": _surface_live_spot[1],
            "spot_as_of_ts_utc": _surface_live_spot[2],
            "spot_strike": spot_strike,
        }

    # ---- no live surface: unavailable, with the reason. Nothing stands in for it. ----
    # REQUESTED: a page shows this ticker. WARMING: its chain is coming -- it is on the
    # watchlist (fetched in turn; while Closed, once, its close values). The reason is that
    # state's own.
    _requested = _gamma_surface_wanted(tk)
    _watched = _watchlist()  # the last list stands when the heartbeat is missing
    _warming = _watched is not None and tk in _watched
    _levels_why = verdict["levels_stale_reason"]
    if lmp.daemon_status(now.timestamp()) is None:
        _why = ["the capture daemon is not reporting (no current heartbeat)"]
        if _watched is None:
            _why.append("its watchlist is unknown")
        elif tk not in _watched:
            _why.append("it is not on the watchlist")
        if _levels_why:
            _why.append(_levels_why)
    elif _levels_why:
        _why = [_levels_why]
    elif _warming:
        _why = ["the surface is projected when the daemon delivers this ticker's chain"]
    else:
        _why = ["no chain is fetched for this ticker: it is not on the watchlist"]
    return unavailable(
        tk,
        " — ".join(r for r in _why if r),
        symbol=tk,
        source="unavailable",
        warming=_requested and _warming,
        requested=_requested,
    )


def terrain(tk: str, now: float) -> dict:
    """Return `tk`'s published levels at `now`, at the live price (the `terrain` panel).

    `tk` is the levels' own key ($SPX). The page's socket sends
    them to Key Levels, the Gamma chart, the Trade Desk's Right Now and its map (live_ui,
    PAGE_PANELS), at once and each time the levels change (_levels_changed).
    """
    at = datetime.fromtimestamp(now, ET)
    cached, staleness = terrain_cache_get(tk, now)
    if cached is not None:
        # the levels as the producer published them; `spot` is the live price, and every relation
        # of the price to the levels is at it (price_relations); internal fields (the kept chain,
        # the heatmap grid, per-strike rows) are their own panels
        out = cached.served() | staleness
        out["spot"], out["spot_source"], out["spot_as_of_ts_utc"] = resolve_spot(tk, now=now)
        out.update(price_relations(out, out["spot"]).to_dict())
        out.update(_atr_fields(tk, at))  # live: today's candle from the bars held now
        # the chain's verdict is levels_state, above. The live price the relations are computed from
        # is a separate fact: the numbers stay, marked with whether that price is live
        out.update(price_mark(tk, out["spot_as_of_ts_utc"], now))
        return out | levels_mark(out, tk, now)
    spot, spot_source, spot_ts = resolve_spot(tk, now=now)
    _why = _terrain_refresh_last_error.get(tk)
    empty = compute_terrain(tk, None, spot, now=at).to_dict()
    mark = price_mark(tk, spot_ts, now)
    return (
        empty
        | price_relations(empty, spot).to_dict()
        | mark
        | levels_mark(staleness, tk, now)
        | {
            "spot_source": spot_source,
            "spot_as_of_ts_utc": spot_ts,
            **_atr_fields(tk, at),  # from the candles and bars, which do not wait for a chain
            # not ready, with the producer's reason when it has one, and the levels' verdict
            "error": (
                "terrain_not_ready: no chain from the daemon yet for this ticker"
                + (f" (last chain error: {_why})" if _why else "")
            ),
            **staleness,
        }
    )


#: The Trade Desk's lookback per chart timeframe: seconds, or "session" (the latest regular
#: session), with the words the page shows for it.
DESK_LOOKBACK = {
    "1": (900, "last 15 min"),
    "3": (1800, "last 30 min"),
    "5": ("session", "this session"),
    "15": (14400, "last 4 h"),
    "30": ("session", "this session"),
    "60": (172800, "last 2 days"),
    "D": (1728000, "last 20 days"),
}


def _desk_window_start(tf: str, now: datetime) -> float:
    """Start of the Trade Desk's event window for chart timeframe `tf`.

    `now` minus its lookback, or the open of the latest regular session that has begun (Schwab's
    /markets, time_et.last_open).
    """
    lb = DESK_LOOKBACK[tf][0]
    if lb != "session":
        return now.timestamp() - lb
    start = last_open(now)
    if start is None:
        raise ValueError(
            f"Schwab's /markets has sent no regular session that began by {now.isoformat()}"
        )
    return start.timestamp()


def desk_events_payload(tk: str, venue: str, tf: str, now: datetime) -> dict:
    """Return the Trade Desk's attention queue at `now`.

    Level crosses in the timeframe's window as recorded (level, direction, price, spot, time),
    numbered oldest first, the newest cross at each level for the newest DESK_MARKERS levels
    flagged for the chart; wall breaches and stale levels from the terrain; the book's size walls
    at the book's own time -- newest first, an item with no time last -- plus the window's up/down
    cross counts. One item is one event: the chart's marker and the queue's entry are the same
    item. The page draws it; it selects, numbers and orders nothing.
    """
    start = _desk_window_start(tf, now)
    crosses = _merged_recent_crosses(tk, 200)
    in_window = sorted(
        (c for c in crosses if c.get("ts_utc") is not None and c["ts_utc"] >= start),
        key=lambda c: c["ts_utc"],
    )
    items = []
    for i, c in enumerate(in_window):
        names = " + ".join(c["level_names"])
        cid = c.get("cross_id")  # external-key-ok: ed_console.db level_crosses column
        items.append(
            {
                "key": f"x{cid}",
                "n": i + 1,
                "ts": c["ts_utc"],
                "dom": "LEVELS",
                "price": c.get("level_value"),
                "dir": c.get("direction"),
                "marker": False,
                "title": f"Crossed {_CROSS_WORD[c['direction']]} {names}",
                "detail": f"{price_text(c['level_value'])} · spot "
                f"{price_text(c['spot_at_cross'])} at the cross",
                "src": "level_crosses",
            }
        )
    # the chart's few: the newest cross at each level, for the newest DESK_MARKERS levels
    newest_at = {it["price"]: it for it in items}
    for it in sorted(newest_at.values(), key=lambda it: it["ts"])[-DESK_MARKERS:]:
        it["marker"] = True
    t = terrain(tk, now.timestamp())  # the levels the page's terrain panel is sent
    tts = t.get("levels_ts_utc")
    for side, word, key in (("call", "call", "cw"), ("put", "put", "pw")):
        if t.get(f"{side}_wall_state") == "breached":  # at the live price (price_relations)
            items.append(
                {
                    "key": key,
                    "ts": t.get("spot_as_of_ts_utc"),
                    "dom": "OPTIONS",
                    "dir": "up" if side == "call" else "down",
                    "title": f"Spot through the {word} wall",
                    "detail": f"{word} wall {price_text(t[f'{side}_wall'])} · spot "
                    f"{price_text(t['spot'])}",
                    "src": "gamma levels",
                }
            )
    if t.get("levels_state") == LEVELS_STALE:
        items.append(
            {
                "key": "ls",
                "ts": tts,
                "dom": "DATA",
                "dir": None,
                "warn": True,
                "title": "Gamma levels are stale",
                "detail": t["levels_stale_reason"],
                "src": "gamma levels",
            }
        )
    # the book's size walls, stamped with the book's own time (BOOK_TIME); a book that is not live
    # is a past observation and says so
    micro = order_flow_microstructure(tk, venue, now.timestamp())
    book_ms = micro["provenance"]["book_time_ms"]
    live_book = micro["ages"]["book_stale"] is False
    for i, w in enumerate(micro["wall_candidates"][:3]):
        items.append(
            {
                "key": f"wall{i}",
                "ts": None if book_ms is None else book_ms / 1000.0,
                "dom": "LIQUIDITY",
                "dir": "up" if w.get("side") == "bid" else "down",
                "warn": not live_book,
                "title": f"{venue} size wall · {w['side']} {price_text(w['price'])}"
                + ("" if live_book else " (not live)"),
                "detail": f"{w['volume']} shown · {w['median_mult']:.1f}× the median level"
                + ("" if live_book else " · a past book, not the current one"),
                "src": "equity book",
            }
        )
    # newest first; an event with no time of its own after every timed one
    items = sorted((it for it in items if it["ts"] is not None), key=lambda it: -it["ts"]) + [
        it for it in items if it["ts"] is None
    ]
    return {
        "ticker": tk,
        "tf": tf,
        "window_start_ts_utc": start,
        "window_label": DESK_LOOKBACK[tf][1],
        "items": items,
        "cross_counts": {
            d: sum(1 for c in in_window if c.get("direction") == d) for d in ("up", "down")
        },
    }


#: the chart draws the newest cross at each level, for the newest this-many levels (the queue
#: lists every cross)
DESK_MARKERS = 6


def book(ticker: str, now: float, params: dict) -> dict:
    """Return the `book` panel at `now`: the ticker's quote and Schwab book `venue`."""
    return order_flow_microstructure(ticker, _venue_asked(params), now)


def _when_age(when: str | None, sec: float | None) -> str | None:
    """Return a clock's time and its age as the screen shows them ("Fri 09/25 06:59 PM CT · 4s").

    Either alone when the other is missing; None when both are.
    """
    shown = [x for x in (when, None if sec is None else age_text(sec)) if x is not None]
    return " · ".join(shown) or None


def _stamp_book_times(payload: dict) -> None:
    """Schwab's quote clock and book clock, as the screen shows them, each with its age.

    The age is the engine's `ages`. Absent stays absent.
    """
    prov = payload.get("provenance")
    quote_ts = prov.get("exchange_quote_ts") if isinstance(prov, dict) else None
    book_ms = prov.get("book_time_ms") if isinstance(prov, dict) else None
    payload["quote_time_ct"] = ct_label(quote_ts) if quote_ts is not None else None
    payload["book_time_ct"] = ct_label(book_ms / 1000.0) if book_ms is not None else None
    ages = payload["ages"]
    payload["book_age_text"] = (
        None if ages["book_age_sec"] is None else age_text(ages["book_age_sec"])
    )
    payload["book_when_age_text"] = _when_age(payload["book_time_ct"], ages["book_age_sec"])
    payload["quote_when_age_text"] = _when_age(payload["quote_time_ct"], ages["quote_age_sec"])


def order_flow_microstructure(ticker: str, venue: str, now: float) -> dict:
    """Canonical L2 book microstructure at `now` (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1).

    Top-of-book, spread, microprice, Top 1/3/5 depth totals + imbalance, depth-pressure curve,
    book slope, liquidity concentration, wall_candidates, and ages — every field classified
    NATIVE/DERIVED/PROXY. SERIALIZER, not a second producer: it delegates to the ONE canonical
    app.options.order_flow.engine.compute_book_microstructure keyed by this ticker, which carries
    the engine's already-computed structural state for the current book (memoized per ticker +
    BOOK_TIME) rather than re-walking the raw book. No Schwab REST quote call; the client
    renders, never recomputes. `venue` is the one Schwab book the payload's book fields show:
    NYSE_BOOK (exchanges) or NASDAQ_BOOK (market makers); those fields never combine the two.
    `readout` is the Desk Liquidity card's, whatever the venue: both books and their deduped
    composite (liquidity_readout).
    """
    t = ticker_storage_key(ticker)
    # the venue's newest book and the ticker's prints, as the order-flow state holds them
    data: dict = {"content": get_content_for_symbol(t, venue)}
    # top of book: the daemon's price row. The last bid and ask stand when it is not live;
    # top_outage says why and top_feed_label is the page's word for it (docs/DATA_FLOW.md §2 D5)
    top_label, top_outage = price_state(t, now)
    _row = price_row(t, now)
    if _row["quote_ts"] is not None:
        data["exchange_quote_ts"] = _row["quote_ts"]
    data["top"] = (
        {k: _row[k] for k in ("bid", "ask", "bid_size", "ask_size", "mark")}
        if _row["bid"] is not None or _row["ask"] is not None
        else None
    )
    # the venue's book: the same verdict on its own service (price_state), its word served
    book_label = price_state(t, now, venue)[0]
    data["book_live"] = book_label == lmp.LIVE
    # ticker=t → serialize the canonical state carried per (ticker, BOOK_TIME); no independent
    # recompute.
    payload = compute_book_microstructure(data, now_ts=now, ticker=t)
    payload["top_outage"], payload["top_feed_label"], payload["book_feed_label"] = (
        top_outage,
        top_label,
        book_label,
    )
    payload["ticker"] = t
    payload["venue"] = venue
    _stamp_book_times(payload)
    payload["readout"] = liquidity_readout(t, now)
    return payload


#: the amber line inside an exchange auction window, by window (time_et.auction): the continuous
#: book's number stays
_AUCTION_TEXT = {
    OPEN_AUCTION: "Opening auction window — auction imbalance is a different number, not shown"
    " here.",
    CLOSE_AUCTION: "Closing auction window — auction imbalance is a different number, not shown"
    " here.",
}


#: the readout before any book has arrived: every venue no_book
_NO_BOOKS = book_readout(dict.fromkeys(BOOK_VENUES))
_LIVE_BOOK = "live book"


def _source(venue: str, r: dict) -> str:
    """Whose book: Schwab's book of `venue`, or for the composite the books it is built from."""
    if venue != COMPOSITE:
        return f"Schwab {venue}"
    return f"Schwab {' + '.join(r['books'])} · composite, newest quote of each exchange"


def _no_number(r: dict) -> tuple[str, str, str] | None:
    """Why a venue has no number, as the source line, the card's line and the card's heading say it.

    None when it has one.
    """
    status = r["status"]
    if status == "no_book":
        return "no book for this symbol right now", "No book for this symbol right now", "NO BOOK"
    if status == "empty":
        return (
            "the book Schwab sent has no levels",
            "The book Schwab sent has no levels",
            "NO LEVELS",
        )
    return None


def _source_text(venue: str, r: dict, window: str | None) -> str:
    """Return the card's source line for `venue`.

    Schwab's book, then why it has no number, or live, or its time and not live; and, when today's
    auction windows are not known, that.
    """
    parts = [_source(venue, r)]
    why = _no_number(r)
    if why is not None:
        parts.append(why[0])
    elif r["live"]:
        if venue != COMPOSITE:
            parts.append(_LIVE_BOOK)
    elif r["book_time_ct"] is not None:
        parts.append(f"book {r['book_time_ct']} · {r['book_age_text']} old · not live")
    else:
        parts.append("not live, no book time sent")
    if window is None:
        parts.append("auction windows unknown: no Schwab market hours held for today")
    return " · ".join(parts)


def _stood_from(points: list[tuple[float, dict]], venue: str) -> float:
    """Return the receive time of the first reading from which `venue`'s readout has stood as now.

    That is where a venue that is not live is read to (a book that stopped stands from its last
    arrival; the composite of a stopped book and a running one still changes with the running
    one).
    """
    newest, k = points[-1][1][venue], len(points) - 1
    while k > 0 and points[k - 1][1][venue] == newest:
        k -= 1
    return points[k][0]


def liquidity_readout(t: str, now: float) -> dict:
    """Return the Desk Liquidity card's order-imbalance readout for ticker `t` at `now`.

    The newest readout of both Schwab books and their deduped composite the console's intake
    computed (engine.book_readout, kept in history.LEAN), read over the readouts kept
    (engine.readout_card). Each book is judged by the one live rule on its own service, the
    composite live only while both are; a venue that is not live keeps its last values, read to
    the reading its readout has stood from (`_stood_from`), with its book's time and age. With the
    exchange auction window of today's session as Schwab sent it (time_et.auction; None while
    Schwab's answer for today is not held), and every word the card shows.
    """
    points = LEAN.points(t)
    readout = points[-1][1] if points else _NO_BOOKS
    labels = {v: price_state(t, now, v)[0] for v in BOOK_VENUES}
    labels[COMPOSITE] = next((labels[v] for v in BOOK_VENUES if labels[v] != lmp.LIVE), lmp.LIVE)
    ends = {v: now if labels[v] == lmp.LIVE else _stood_from(points, v) for v in readout if points}
    card = readout_card(readout, points, ends)
    window = auction(datetime.fromtimestamp(now, ET))
    for v, r in card["venues"].items():
        book_ms = r["book_time_ms"]
        r["feed_label"] = labels[v]
        r["live"] = labels[v] == lmp.LIVE
        r["book_time_ct"] = None if book_ms is None else ct_label(book_ms / 1000.0)
        age = book_age_sec(book_ms, now)
        r["book_age_text"] = None if age is None else age_text(age)
        r["source_text"] = _source_text(v, r, window)
        why = _no_number(r)
        r["no_number_text"] = None if why is None else why[1]
        r["no_number_head"] = None if why is None else why[2]
        r["dedup_partial_text"] = (
            "Dedup partial: a level came without per-exchange sizes (its total taken whole), or"
            " a quote in both books without its quote time (a timed copy counts over it)"
            if r["dedup_partial"]
            else None
        )
    card["auction"] = window
    card["auction_text"] = _AUCTION_TEXT.get(window)
    return card


def _contract_asked(params: dict) -> str:
    """Return the option contract a panel's `params` name; none named raises.

    `contract` is a chain answer's own "symbol" (OSI, e.g. "SPY   260820C00767000"), served as the
    console holds it for that literal string (options_microstructure).
    """
    symbol = params.get("contract")
    if type(symbol) is not str or not symbol.strip():
        raise ValueError("contract is required")
    return symbol.strip()


def options_microstructure(c: str, now: float) -> dict:
    """Return the Flow panel's payload for contract `c` at `now`, judged by the one live rule."""
    payload = options_live_payload(ticker_storage_key(c), now)
    payload["contract"] = c
    # the side of the contract's chain record; None while no chain the console holds lists it
    tk = _contract_ticker(c)
    payload["put_call"] = None if tk is None else published_levels(tk).contracts[c].side
    # whether the daemon streams this contract (the option rule) and is receiving it
    payload["streaming_plane"] = get_option_contract_streaming_diagnostics(c, now)
    _stamp_book_times(payload)
    return payload


async def _watchlist_change(action: str, ticker: str) -> JSONResponse:
    """Ask the daemon for an add or a removal (streaming.watchlist_request).

    Its record is the answer, stamped with the record's time (`ts`, the program's clock, as each
    beat's status is): `ok` when it happened, else what happened (an invalid ticker with
    Schwab's /quotes answer, one already on the list, ...).
    """
    try:
        rec = await watchlist_request(action, ticker)
    except ConnectionError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)
    except TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "the capture daemon did not answer"}, status_code=504
        )
    return JSONResponse(
        {
            "ok": rec["op"] in ("added", "removed"),
            "op": rec["op"],
            "ticker": rec["ticker"],
            "tickers": rec["tickers"],
            "ts": rec["ts_recv"],
            "status": rec["status"],
            "answer": rec["answer"],
        }
    )


@app.post("/api/watchlist")
async def post_watchlist(ticker: Annotated[str, Body(embed=True)]):
    """Add a ticker.

    The daemon checks it with one /quotes request and adds it unless Schwab does not quote it
    (names it in errors.invalidSymbols).
    """
    return await _watchlist_change("add", ticker)


@app.delete("/api/watchlist/{ticker}")
async def delete_watchlist(ticker: str):
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
    if contract is not None and _contract_ticker(contract) is None:
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


def expiries(ticker: str, now: float) -> dict:
    """Return the ticker's listed expiries at `now`, each with its dropdown texts.

    `ticker` is the levels' own key ($SPX). Each expiry's label is its date, MM/DD/YYYY, and its
    `dte_text` Schwab's daysToExpiration as sent (18DTE), None when Schwab sent none. Before the
    ticker's first chain is priced the list is unknown (None), with the levels' own reason; a
    chain listing none is an empty list with its reason. The page's socket sends it (live_ui,
    PAGE_PANELS) when the page subscribes on the ticker and on each new chain.
    """
    levels, verdict = terrain_cache_get(ticker, now)
    exps = dte = labels = dte_text = None
    reason = verdict["levels_stale_reason"]
    if levels is not None:
        exps, dte = levels.snap.expiries, levels.snap.expiry_dte
        labels = {e: f"{e[5:7]}/{e[8:10]}/{e[:4]}" for e in exps}
        dte_text = {e: None if dte[e] is None else f"{dte[e]:g}DTE" for e in exps}
        reason = None if exps else "no expiry listed in the published chain"
    return {
        "expiries": exps,
        "dte": dte,
        "labels": labels,
        "dte_text": dte_text,
        "reason": reason,
    }


#: the chain panel's reason while no chain of the ticker is held and no chain error is recorded
NO_CHAIN_YET = "the daemon has not delivered this ticker's chain yet"


def chain(ticker: str, now: float, params: dict) -> dict:
    """Return one expiry of the ticker's full chain at `now`, from the chain the daemon delivered.

    The `chain` panel: the Chain ladder, Strike Detail and Structures, each its own reader with
    its own `expiry` (the selected expiry, or None for the chain's front one, the levels' first
    listed). Every contract Schwab listed, as the chain screens show it (option_contract.chain_row:
    a value Schwab did not send is null) -- from the chain the daemon delivered
    (strike_range=ALL), with each live streamed contract's streamed fields as its values (the
    stream owns them), by the levels' own rule on the same inputs (the chain's listed contracts,
    its fetch time). Every watchlist ticker's chain is kept. Answers `status: unavailable` with a
    reason when no chain is held. `ticker` is the levels' own key.
    """
    t = ticker
    expiry = params.get("expiry")
    held, staleness = terrain_cache_get(t, now)
    listed = held.snap.expiries if held is not None else None
    requested = expiry.strip()[:10] if isinstance(expiry, str) and expiry.strip() else None
    resolved_expiry = requested or (listed[0] if listed else None)
    # the chain's state is its levels' (terrain_staleness), the one verdict the screen shows
    verdict = levels_verdict(staleness)

    def _unavailable(reason: str) -> dict:
        return {
            "ticker": t,
            "spot": None,
            "expiry": resolved_expiry,
            "contracts": [],
            "status": "unavailable",
            **verdict,
            "scope": {"kind": "unavailable", "reason": reason},
        }

    if "expiry" not in params or not (expiry is None or isinstance(expiry, str)):
        return _unavailable(f"expiry {expiry!r} is not an expiry date or null")
    if held is None:
        return _unavailable(_terrain_refresh_last_error.get(t) or NO_CHAIN_YET)
    if not held.priced_chain:
        return _unavailable(held.snap.error or _terrain_refresh_last_error.get(t) or NO_CHAIN_YET)
    if resolved_expiry is None:
        return _unavailable("no listed expiry for this ticker")
    # the contracts as the levels priced them (_publish_levels, each with its newest values):
    # one computation, the screen's
    response_contracts = [c for c in held.priced_chain if c.expiry == resolved_expiry]
    if not response_contracts:
        return _unavailable(f"the chain lists no contracts for {resolved_expiry}")
    shown = [chain_row(c) for c in response_contracts]
    live_spot, _src, live_ts = resolve_spot(t, now=now)  # the one spot, with Schwab's trade time
    ladder, not_on_ladder = chain_ladder(response_contracts, live_spot, shown)
    if not_on_ladder:
        log.warning(
            "%s %s: %d contract(s) Schwab sent have no strike or no CALL/PUT side and are not "
            "on the chain ladder",
            t,
            resolved_expiry,
            not_on_ladder,
        )
    # this expiry's net GEX per strike, as the heatmap publishes it (its column of the surface):
    # Strike Detail shows it beside this expiry's contracts -- one value, one producer
    surf = held.gamma_surface
    col = (
        None
        if surf is None
        else next(
            (i for i, e in enumerate(surf["expirations"]) if e["expiry"] == resolved_expiry), None
        )
    )
    # no surface, or no column for this expiry: unknown (None), each strike drawn "-"
    net_gex_by_strike = (
        None
        if col is None
        else [[c["strike"], c["gex"][col]] for c in surf["cells"] if c["gex"][col] is not None]
    )
    return {
        "ticker": t,
        "spot": live_spot,
        "spot_time_ct": ct_label(live_ts) if live_ts is not None else None,
        "expiry": resolved_expiry,
        "net_gex_by_strike": net_gex_by_strike,
        "spot_strike": nearest_strike(
            {c.strike for c in response_contracts if c.strike is not None}, live_spot
        ),
        # Schwab's own flag for a non-standard (adjusted) deliverable, as sent
        "adjusted_deliverable_symbols": [c.symbol for c in response_contracts if c.non_standard],
        # Schwab's lastTradingDay, an instant in epoch milliseconds, as its date on the market's
        # clock (ET); a contract Schwab sent none for has no entry
        "last_trading_day_et": {
            c.symbol: et_date_str_from_ts_utc(ms / 1000.0)
            for c in response_contracts
            if isinstance(ms := c.listing.get("lastTradingDay"), float)
        },
        # two contracts listed at one (strike, side): the chain is not strike-unique
        "has_duplicate_contracts": len({(c.strike, c.side) for c in response_contracts})
        < len(response_contracts),
        **verdict,
        "contracts": shown,
        "status": "ok",
        "ladder": ladder,
        "n_strikes": len({r["strike"] for r in ladder}),
        "scope": {"kind": "complete_single_expiry"},
    }


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
    watchlist = _watchlist()
    capability: dict[str, object] = {
        "schwab": "AVAILABLE" if st is not None and st["schwab_socket_open"] else "UNAVAILABLE"
    }
    if capability["schwab"] == "UNAVAILABLE":
        capability["schwab_reason"] = NO_DAEMON_HEARTBEAT if st is None else st["schwab_down"]
    return {
        "status": "ok",
        "time": datetime.fromtimestamp(now).isoformat(),
        "watchlist_tickers": len(watchlist) if watchlist is not None else None,
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


@dataclass(frozen=True)
class ProcessIdentityV1:
    """Immutable process-start identity (schema v1).

    Captured once; never recomputed per request. identity_capture_error carries a sanitized fixed
    classification only — never raw subprocess output or stack traces.
    """

    schema_version: str
    startup_git_sha: str | None
    startup_git_sha_short: str | None
    startup_git_dirty: bool | None
    startup_git_available: bool
    startup_identity_captured_at_utc: float
    process_started_at_utc: float | None
    process_id: int
    identity_source: str
    identity_capture_error: str | None


def capture_process_identity(checkout: str | Path) -> ProcessIdentityV1:
    """Capture the process's identity at its start.

    `checkout`'s HEAD (checkout_head), whether its tree was dirty (`git status --porcelain` with
    any output, tracked changes or untracked files; None, unknown and never clean, when git cannot
    say), and the process's id and start time.
    """
    sha = checkout_head(checkout)
    short, dirty, source, error = None, None, "unavailable", "head_unreadable"
    if sha is not None:
        short, source, error = sha[:12], "git_startup_capture", None
        try:
            dirty = bool(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=checkout,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10.0,
                ).stdout.strip()
            )
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("the checkout's dirty state is unknown: %r", e)
            error = "git_dirty_state_unavailable"
    return ProcessIdentityV1(
        schema_version="1",
        startup_git_sha=sha,
        startup_git_sha_short=short,
        startup_git_dirty=dirty,
        startup_git_available=sha is not None,
        startup_identity_captured_at_utc=time_et.now(),
        process_started_at_utc=float(psutil.Process(os.getpid()).create_time()),
        process_id=os.getpid(),
        identity_source=source,
        identity_capture_error=error,
    )


#: captured once, at import, before uvicorn serves any request (one process, no --reload:
#: launch.CONSOLE)
PROCESS_IDENTITY_V1: ProcessIdentityV1 = capture_process_identity(APP_DIR)


def build_identity_answer(identity: ProcessIdentityV1, repo_head_now: str | None) -> dict:
    """/api/build's answer: `git_sha` is the code the running process loaded.

    That is its identity, stable for its life; the checkout's HEAD now is reported apart
    (repository_state_now), and whether the checkout has moved past the process (None while
    either is unknown).
    """
    startup_sha = identity.startup_git_sha
    return {
        "git_sha": startup_sha,
        "contract": "meet_or_exceed_v1",
        "process_identity": asdict(identity),
        "repository_state_now": {"repo_head_now": repo_head_now},
        "code_drift": {
            "repo_moved_past_process": None
            if startup_sha is None or repo_head_now is None
            else startup_sha != repo_head_now,
            "running_code": startup_sha,
            "checked_out_code": repo_head_now,
        },
        "git_sha_semantics": "startup_process_identity",
    }


@app.get("/api/build")
def api_build():
    """Serve the running process's identity and the checkout's HEAD now (build_identity_answer)."""
    return build_identity_answer(PROCESS_IDENTITY_V1, checkout_head(APP_DIR))


def _publish_price_levels(ticker: str, now: datetime) -> None:
    """Publish a ticker's price-level snapshot: THE producer of it.

    Materialized for the market's session at `now` (market_session_date: today's while a session
    is open, the newest one's while Closed) from its completed Schwab 1m bars, by the bar writer
    after each of the ticker's bars, and by the levels loop for a ticker with none yet for the
    session (a restart, a new session). The routes read what it published
    (canonical_price_level_snapshot). A failed build is logged; the routes serve the last
    published snapshot with its as-of time, or say the levels are absent.
    """
    tk = ticker_storage_key(ticker)
    before = canonical_price_level_snapshot(tk, now)
    try:
        with _bars_lock:
            daily = list(_series[(tk, "1d")]) if (tk, "1d") in _series else []
        snap = materialize_price_level_snapshot(
            tk,
            market_session_date(now),
            bars_from_candles(_bars_1m(tk, 2500)),
            daily=daily,
            bar_source=BAR_SOURCE,
            config=PlaybookConfig(),
        )
    except Exception as e:  # logged; the ticker's next bar builds them
        log.warning("price levels for %s not built: %s", tk, e, exc_info=True)
        return
    if snap is not before:  # the same object when its bars did not change
        _levels_changed(tk)


def _publish_missing_price_levels(tickers, now: datetime) -> None:
    """Build the price levels of each ticker with none published for the market's session at `now`.

    As at the console's start, or a new session.
    """
    for tk in tickers:
        if canonical_price_level_snapshot(tk, now) is None:
            _publish_price_levels(tk, now)


def canonical_price_level_snapshot(ticker: str, now: datetime):
    """Return the ticker's price-level snapshot for the market's session at `now`.

    The session is market_session_date's; the snapshot as its producer published it
    (_publish_price_levels), or None when none is published yet. Every server surface reads this;
    none computes a level.
    """
    return _MATERIALIZED_SNAPSHOTS.get(
        (ticker_storage_key(ticker), market_session_date(now).isoformat())
    )


#: why a route serves no price levels for a ticker
NO_PRICE_LEVELS_REASON = (
    "no price levels published for this ticker for the market's session yet (they are "
    "built from its 1-minute bars on each new bar and at the console's start)"
)


def _expiry_order(item: tuple) -> tuple:
    """Known days-to-expiration first, then the date. A missing count sorts last."""
    dte = item[1]
    if isinstance(dte, (int, float)):
        return (0, float(dte), item[0])
    return (1, 0.0, item[0])


def _confluence_expiries(books: dict, expiry_dte: dict) -> list[dict]:
    found: dict[str, float | None] = {}
    for key in books:
        if not isinstance(key, tuple) or not key[0]:
            continue
        exp = str(key[0])[:10]
        dte = expiry_dte.get(exp)
        if dte is None:
            dte = key[1]
        if exp not in found or (found[exp] is None and dte is not None):
            found[exp] = dte
    listed = []
    for exp, dte in sorted(found.items(), key=_expiry_order):
        label = exp
        if isinstance(dte, (int, float)) and float(dte) == 0:
            label = "0DTE · " + exp
        elif isinstance(dte, (int, float)) and float(dte) == int(dte):
            label = exp + " · " + str(int(dte))
        elif isinstance(dte, (int, float)):
            label = exp + " · " + str(dte)
        listed.append({"expiry": exp, "dte": dte, "label": label})
    return listed


#: Pill text for the chain's option levels. Same-day copies take "0D " in front.
#: The same-day absolute-gamma strike is the 0DTE pin.
_OPTION_SHORT = {
    "Call wall": "CW",
    "Put wall": "PW",
    "Gamma flip": "Flip",
    "Max pain": "Pain",
    "Abs Γ": "Abs Γ",
    "Pin candidate": "Pin",
    "GSF": "GSF",
    "GRC": "GRC",
    "Net put Γ peak": "Net PΓ",
    "Net call Γ peak": "Net CΓ",
    "Key Δ strike": "Key Δ",
    "Call charm wall": "CCh",
    "Put charm wall": "PCh",
}


def _option_abbrev(label: str, same_day: bool) -> str:
    if same_day and label == "Abs Γ":
        return "0D Pin"
    base = _OPTION_SHORT[label] if label in _OPTION_SHORT else label
    if same_day:
        return "0D " + base
    return base


def _confluence_markers(live: TerrainSnapshot, tk: str, now: datetime, spot) -> list[dict]:
    """Levels carried from this same priced snapshot, plus the session levels already published.

    And the one-day move around the live price `spot`.
    """
    markers = []
    snap = canonical_price_level_snapshot(tk, now)
    if snap is not None:
        for value in snap.levels.values():
            row = value.to_contract_dict()
            price = row.get("price")
            if price is not None:
                short = row.get("short")
                markers.append(
                    {
                        "label": row["label"],
                        "short": short if isinstance(short, str) and short else row["label"],
                        "title": row["label"],
                        "lane": "session",
                        "price": price,
                    }
                )
    served = live.to_dict()
    at_spot = served | price_relations(served, spot).to_dict()  # the pin candidate: live price
    for gid, label in OPTION_LEVELS:
        price = at_spot[gid]
        if price is not None:
            markers.append(
                {
                    "label": label,
                    "short": _option_abbrev(label, False),
                    "title": label,
                    "lane": "options",
                    "price": price,
                }
            )
    for gid, label in SAME_DAY_LEVELS:
        price = live.same_day.get(gid)  # an unavailable snapshot holds no same-day level
        if price is not None:
            markers.append(
                {
                    "label": "0DTE " + label,
                    "short": _option_abbrev(label, True),
                    "title": "0DTE " + label,
                    "lane": "options",
                    "price": price,
                }
            )
    move = expected_move(live.implied_1d_move, spot)
    if move is not None:
        markers.append(
            {
                "label": "+1σ move",
                "short": "EM+",
                "title": "Expected move, one day, upper",
                "lane": "session",
                "price": move[0],
            }
        )
        markers.append(
            {
                "label": "−1σ move",
                "short": "EM−",
                "title": "Expected move, one day, lower",
                "lane": "session",
                "price": move[1],
            }
        )
    return markers


def expected_move(move: dict | None, spot) -> tuple[float, float] | None:
    """Return the one-day move's upper and lower price.

    The live price plus and minus the terrain's implied one-day move
    (TerrainSnapshot.implied_1d_move). None without either.
    """
    if move is None or spot is None:
        return None
    points = move["points"]
    return float(spot) + float(points), float(spot) - float(points)


def _screen_levels(markers: list[dict]) -> list[dict]:
    """Each level at its own price, for the rail. The page does not move it onto a strike."""
    levels = []
    for marker in markers:
        price = marker.get("price")
        if not isinstance(price, (int, float)):
            continue
        levels.append(
            {
                "lane": marker["lane"],
                "abbrev": marker["short"],
                "price": float(price),
                "price_text": price_text(price),
                "title": marker["title"],
            }
        )
    return levels


def _level_named(levels: list[dict], abbrev: str) -> dict | None:
    for level in levels:
        if level["abbrev"] == abbrev:
            return level
    return None


def _move_text(low: dict | None, high: dict | None) -> str | None:
    if low is None or high is None:
        return None
    return low["price_text"] + "–" + high["price_text"]


def _inside_move(strike, low, high) -> bool:
    """Whether this strike sits between the book's one-day move. Display only."""
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return False
    return float(low) <= float(strike) <= float(high)


def _ranked_matrix(snap: TerrainSnapshot, chosen: str, dte: float) -> dict:
    """The ranking of one expiry of a priced chain: the one the matrix request shows.

    `chosen` is an expiry of `snap`'s books with its days to expiration, `dte`
    (_confluence_expiries).
    """
    selected = [book for key, book in snap.books.items() if str(key[0])[:10] == chosen]
    exposures = selected[0][0] if len(selected) == 1 else merge_exposure_books(selected)[0]
    return build_matrix(
        exposures,
        snap.charm_by_expiry[chosen],
        snap.iv_by_expiry[chosen],
        float(snap.spot),
        float(dte),
    )


def confluence_payload(tk: str, expiry: str | None, now: datetime) -> dict:
    """Return the ranking of the priced chain, for the expiry the operator picks."""
    published = published_levels(tk)
    if published is None or not published.snap.books:  # a snapshot with a book has its price
        return unavailable(tk, "no priced chain is held for this ticker")
    live = published.snap
    today = now.strftime("%Y-%m-%d")
    listed = [e for e in _confluence_expiries(live.books, live.expiry_dte) if e["expiry"] >= today]
    if not listed:
        return unavailable(tk, "no expiry on this chain is still open")
    chosen = expiry
    if not isinstance(chosen, str) or chosen < today:
        live_listed = [e for e in listed if e["dte"] is not None and e["dte"] >= 0]
        chosen = (live_listed or listed)[0]["expiry"]
    match = next((e for e in listed if e["expiry"] == chosen), None)
    if match is None or match["dte"] is None:
        absent = match is None
        reason = (
            "that expiry is not on the priced chain"
            if absent
            else "that expiry did not carry days to expiration"
        )
        return unavailable(tk, reason, expiries=listed)
    stored = _ranked_matrix(live, chosen, match["dte"])
    fetched = published.computed_ts_utc
    live_spot, _src, live_ts = resolve_spot(tk, now=now.timestamp())
    markers = _confluence_markers(live, tk, now, live_spot)
    levels = _screen_levels(markers)
    flip = _level_named(levels, "Flip")
    pin = _level_named(levels, "0D Pin")
    em_up = _level_named(levels, "EM+")
    em_dn = _level_named(levels, "EM−")
    body = {key: value for key, value in stored.items() if key not in ("ranked", "strikes")}
    ranked = sorted(stored["ranked"])
    lo, hi, view = _window(ranked, nearest_strike(ranked, live_spot), "auto", None, 0)
    body["rows"] = window_rows(stored, ranked[lo : hi + 1])
    if view["note"] is not None:
        body["notes"] = [*body["notes"], view["note"]]
    body.update(at_price(body["rows"], stored["strikes"], live_spot))
    low = None
    high = None
    if em_dn is not None:
        low = em_dn["price"]
    if em_up is not None:
        high = em_up["price"]
    for row in body["rows"]:
        row["inside"] = _inside_move(row["strike"], low, high)
    body.update(
        {
            "ticker": tk,
            "available": True,
            "reason": None,
            "expiry": chosen,
            "expiries": listed,
            "spot_as_of_ts_utc": live_ts,
            # the distances, the spot line and the pin candidate are from the live price: its mark
            **price_mark(tk, live_ts, now.timestamp()),
            "status_text": "Chain as of " + ct_label(fetched),
            "levels": levels,
            "regime": live.regime,
            "flip_text": None if flip is None else flip["price_text"],
            "pin_text": None if pin is None else pin["price_text"],
            "move_text": _move_text(em_dn, em_up),
        }
    )
    return body


#: the chart timeframes the levels' VWAP curve is served in (aggregate_vwap)
LEVEL_TIMEFRAMES = ("1", "3", "5", "15", "30", "60", "D")

#: every panel the page shows, sent by its socket for the page's selected ticker
#: (live_ui.LiveUiServer): each kind's producer, given what it reads of what the page asked.
#: Each is sent at once and again when its inputs change: CHAIN_PANELS on a new chain
#: (_publish_levels), LEVELS_PANELS on each publication of the levels (_levels_changed),
#: BARS_PANELS on a new bar and FLOW_PANELS on a streamed equity quote or book (flow_changed)
PAGE_PANELS = {
    "expiries": lambda a: expiries(a.ticker, a.now),
    "vanna": lambda a: strike_bars("vanna_rows", a.ticker, a.now, a.params),
    "charm": lambda a: strike_bars("charm_rows", a.ticker, a.now, a.params),
    "terrain": lambda a: terrain(a.ticker, a.now),
    "strikes": lambda a: strikes(a.ticker, a.now, a.params),
    "surface": lambda a: gamma_surface(a.ticker, a.now, a.params),
    "chain": lambda a: chain(a.ticker, a.now, a.params),
    "levels": lambda a: levels_payload(a.ticker, _tf_asked(a.params), a.at),
    "bars": lambda a: bars(a.ticker, a.now, a.params),
    "tape": lambda a: tape(a.ticker, a.now),
    "book": lambda a: book(a.ticker, a.now, a.params),
    "bookmap": lambda a: bookmap(a.ticker, a.params),
    "contract": lambda a: options_microstructure(_contract_asked(a.params), a.now),
    "forces": lambda a: forces(a.ticker),
    "desk": lambda a: desk_events_payload(
        a.ticker, _venue_asked(a.params), _tf_asked(a.params), a.at
    ),
    "confluence": lambda a: confluence_payload(a.ticker, a.params.get("expiry"), a.at),
    "liquidity": lambda a: liquidity_snapshot(a.ticker, a.at),
}
CHAIN_PANELS = ("expiries",)
BARS_PANELS = ("bars", "liquidity", "desk")
FLOW_PANELS = ("book", "bookmap", "tape", "contract")
#: the panels computed from the ticker's live price (each level's distance and side, the spot
#: they are measured from): the socket sends them again with each of its price rows
PRICED_PANELS = ("levels",)


def levels_payload(tk: str, tf: str, now: datetime) -> dict:
    """The levels panel at `now`: the published price-level snapshot for the market's session.

    The terrain's levels carried beside it, each with its distance from the live price.
    """
    served_ts = now.timestamp()
    spot, spot_source, spot_ts = resolve_spot(tk, now=now.timestamp())
    mark = price_mark(tk, spot_ts, served_ts)  # each value computed from that price carries it
    snap = canonical_price_level_snapshot(tk, now)

    levels: list[dict] = []
    for lid, value in snap.levels.items() if snap is not None else ():
        row = value.to_contract_dict()
        as_of = value.as_of_ts_utc
        row["staleness"] = {
            "as_of_ts_utc": as_of,
            "as_of_time_ct": ct_label(as_of) if as_of is not None else None,
            "age_sec": None if as_of is None else served_ts - as_of,
            "reason": f"carried from canonical snapshot generation {snap.generation}; a session "
            "price level has no staleness rule, its age is shown",
        }
        levels.append(row)
    # the gamma family, carried from the terrain (terrain_engine.compute_terrain's own values),
    # and the pin candidate at the live price (terrain_engine.price_relations)
    published, verdict = terrain_cache_get(tk, now.timestamp())
    t = None if published is None else published.served()
    if t is not None:
        t |= price_relations(t, spot).to_dict()
    em = None if published is None else expected_move(published.snap.implied_1d_move, spot)
    carried = [
        (gid, label, "gamma", t[gid] if t is not None else None) for gid, label in OPTION_LEVELS
    ]
    carried += [
        ("em_up", "+1σ move", "expected_move", None if em is None else em[0]),
        ("em_dn", "−1σ move", "expected_move", None if em is None else em[1]),
    ]
    for gid, label, fam, price in carried:
        if price is not None:
            as_of = published.levels_ts_utc
            producer = (
                {"producer": "terrain_engine.price_relations", "carried": False}
                if gid in PRICE_RELATIONS
                else {"producer": "terrain_engine.compute_terrain", "carried": True}
            )
            levels.append(
                {
                    "id": gid,
                    "price": price,
                    "family": fam,
                    "label": label,
                    "short": label,
                    "evidence_tier": "DERIVED",
                    "provenance": producer
                    if fam == "gamma"
                    else {"producer": "server.expected_move", "carried": False},
                    "staleness": {
                        "as_of_ts_utc": as_of,
                        "as_of_time_ct": ct_label(as_of),
                        "age_sec": served_ts - as_of,
                        "reason": "carried from the terrain",
                    },
                    # a level placed at the live price (the pin candidate) is marked with it
                    "not_live_text": mark["spot_not_live_text"] if gid in PRICE_RELATIONS else None,
                }
            )
    for row in levels:
        price = row.get("price")
        row["distance"] = (price - spot) if price is not None and spot is not None else None
        row["side"] = level_side(price, spot)
        row["from_spot_text"] = from_spot_text(row["distance"], row["side"])
    # the ladder in price order (highest first, unpriced last), and the order by distance to spot
    levels = sorted(
        (r for r in levels if r.get("price") is not None), key=lambda r: r["price"], reverse=True
    ) + [r for r in levels if r.get("price") is None]
    # the order the chart draws them in: nearest Schwab's last price (spot, with its trade time)
    by_distance = (
        []
        if spot is None
        else [
            r["id"]
            for r in sorted(
                (r for r in levels if r.get("price") is not None),
                key=lambda r: abs(r["price"] - spot),
            )
        ]
    )

    families_absent = (
        list(snap.families_absent)
        if snap is not None
        else [{"family": "price_levels", "reason": NO_PRICE_LEVELS_REASON}]
    )
    vp = snap.volume_profile if snap is not None else None
    if em is None:
        families_absent.append(
            {
                "family": "expected_move",
                "reason": "no live price"
                if spot is None
                else "the terrain has no implied 1-day move",
            }
        )

    return {
        "ticker": tk,
        "schema_version": 1,
        "served_ts_utc": served_ts,
        "spot": spot,
        "spot_source": spot_source,
        "spot_as_of_ts_utc": spot_ts,
        **mark,  # each level's distance and side are from that price
        "generation": snap.generation if snap is not None else None,
        "snapshot_as_of_ts_utc": snap.as_of_ts_utc if snap is not None else None,
        "snapshot_time_ct": ct_label(snap.as_of_ts_utc)
        if snap is not None and snap.as_of_ts_utc is not None
        else None,
        "snapshot_age_text": (
            age_text(served_ts - snap.as_of_ts_utc)
            if snap is not None and snap.as_of_ts_utc is not None
            else None
        ),
        # the gamma levels' verdict (terrain_staleness: LIVE, CLOSE, STALE, NOT LIVE)
        **levels_verdict(verdict),
        "bar_source": snap.bar_source if snap is not None else None,
        "levels": levels,
        "by_distance": by_distance,
        # the nearest listed expiry's own levels, beside the whole book's level of the same name.
        # The time is the terrain's own compute time, the same instant the gamma rows carry.
        "zero_dte": [
            {
                "id": gid,
                "label": label,
                # an unavailable snapshot holds no same-day level
                "price": None if published is None else published.snap.same_day.get(gid),
                "carried": None if t is None else t[gid],
                "staleness": {
                    "as_of_ts_utc": None if published is None else published.levels_ts_utc,
                    "as_of_time_ct": None
                    if published is None
                    else ct_label(published.levels_ts_utc),
                    "age_sec": None if published is None else served_ts - published.levels_ts_utc,
                    "reason": "carried from the terrain",
                },
            }
            for gid, label in SAME_DAY_LEVELS
        ],
        # The VWAP curve and its σ bands, CARRIED: the one VWAP of the session, which no page
        # accumulates for itself. [epoch_sec, vwap, +1σ, -1σ, +2σ, -2σ]
        "vwap_series": aggregate_vwap(snap.vwap_series, tf)
        if snap is not None
        else [],  # one point per chart bar of `tf`
        # the session's volume profile the value area is read from (absent: families_absent
        # names the value_area reason)
        "volume_profile": None
        if vp is None
        else {
            "basis": "Estimated volume by price: each RTH 1-minute bar's volume spread evenly "
            "over its range (not trades observed at a price)",
            "bars": vp.bars,
            "bars_without_volume": vp.bars_without_volume,
            "tick_size": vp.tick_size,
            # [price, volume, inside the value area]
            "bins": [[p, v, vp.val <= p <= vp.vah] for p, v in vp.bins],
            # the largest bin's volume: the profile's scale
            "max_volume": max((v for _p, v in vp.bins), default=None),
            "poc": vp.poc,
            "vah": vp.vah,
            "val": vp.val,
        },
        "tf": tf,
        "families_absent": families_absent,
        "degraded": list(snap.degraded) if snap is not None else [],
    }


def _liquidity_option_levels(tk: str) -> list[tuple[float, str]]:
    """Return the ticker's option levels from its published terrain, tagged for liquidity zones."""
    published = published_levels(tk)
    return [
        (float(getattr(published.snap, k)), tag)
        for k, tag in OPTION_LEVEL_TAGS
        if published is not None and getattr(published.snap, k) is not None
    ]


def _zone_against_spot(lo: float, hi: float, spot: float | None) -> dict:
    """Return the zone's distance_to_spot and spot_inside_zone, each None without a spot."""
    known = spot is not None
    inside = within(lo, hi, spot) if known else None
    outside_by = min(abs(spot - lo), abs(spot - hi)) if known else None
    return {"distance_to_spot": 0.0 if inside else outside_by, "spot_inside_zone": inside}


def _spot_location(zones: list, spot) -> dict | None:
    """Where spot sits among the zones, by index into `zones`.

    The zone it is inside, else the nearest zone above and below. None without a spot or a zone.
    """
    if spot is None or not zones:
        return None
    for i, z in enumerate(zones):
        if within(z.get("zone_low"), z.get("zone_high"), spot):
            return {"inside": i, "above": None, "below": None}
    above = [i for i, z in enumerate(zones) if level_side(z.get("zone_low"), spot) == LEVEL_ABOVE]
    below = [i for i, z in enumerate(zones) if level_side(z.get("zone_high"), spot) == LEVEL_BELOW]
    return {
        "inside": None,
        "above": min(above, key=lambda i: zones[i]["zone_low"]) if above else None,
        "below": max(below, key=lambda i: zones[i]["zone_high"]) if below else None,
    }


def liquidity_snapshot(ticker: str, now: datetime) -> dict:
    """Return the market session's liquidity & value zones for the ticker at `now`.

    Built from the one price-level snapshot (canonical_price_level_snapshot, the same values the
    `levels` panel sends) with the terrain's option levels and the live price fused in. It
    computes no level of its own.
    """
    ticker_upper = ticker_storage_key(ticker)
    config = PlaybookConfig(max_zone_width=2.0)
    extra = _liquidity_option_levels(ticker_upper)
    # the one spot (resolve_spot), the header's own
    spot_for_zones, _, _ = resolve_spot(ticker_upper, now=now.timestamp())
    if spot_for_zones is not None:
        extra = list(extra) + [(spot_for_zones, "SPOT_LIVE")]
    _canon = canonical_price_level_snapshot(ticker_upper, now)
    if _canon is None:
        return unavailable(ticker_upper, NO_PRICE_LEVELS_REASON, zones=[])
    out = build_live_snapshot(ticker_upper, config, canonical=_canon, now=now, extra_levels=extra)
    zones_payload = [
        {
            "zone_type": z.zone_type.value,
            "zone_label": ZONE_DISPLAY[z.zone_type][0],
            "zone_side": ZONE_DISPLAY[z.zone_type][1],
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "anchor": z.zone_mid,
            "source_levels": z.source_levels,
            "source_tags": z.source_tags,
            "confluence_score": z.confluence_score,
            "interpretation_notes": z.interpretation_notes,
            **_zone_against_spot(z.zone_low, z.zone_high, spot_for_zones),
        }
        for z in out.zones
    ]
    zones_payload.sort(key=lambda x: x["zone_low"])
    if spot_for_zones is not None:
        zones_payload.sort(key=lambda x: x["distance_to_spot"])
    return {
        "ticker": out.ticker,
        "snapshot_type": out.snapshot_type.value,
        "zones": zones_payload,
        "summary": out.summary
        and {
            "value_state": out.summary.value_state,
            "vwap_relation": out.summary.vwap_relation,
        },
        "spot_used_for_scoring": spot_for_zones,
        "spot_location": _spot_location(zones_payload, spot_for_zones),
    }
