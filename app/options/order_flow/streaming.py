"""
The console's live-plane feed for every watchlist ticker — READ-ONLY consumer of the capture
daemon (app.market_data.schwab.streaming.capture). It opens no Schwab connection: the daemon
holds the one Schwab socket and is the one producer.

The daemon's message bus gives this module every Schwab record the moment it changes (follow), in
the one program, and this module applies it to the in-process planes
(`app.options.order_flow.state`, `live_market_plane`). The database is not in the live path:
stream_capture.db is the daemon's record, and no screen value is read from it. If the daemon
stops, the live values go stale and the screen says so; nothing falls back to the database.

The daemon streams every ticker on its watchlist (capture.Daemon.watchlist, the one list), and
picks the option contracts it streams itself (capture.Daemon.pick_options, the option rule).
This module hands it the operator's adds and removals of watchlist tickers (watchlist_request),
each answered by the daemon's watchlist record, and the contract selected on the Flow panel
(select_flow_contract), which the daemon streams on top of the rule. The daemon's one-second
status (live_ui's beat, recorded in live_market_plane) is the one source for "is the daemon /
Schwab alive", the watchlist and "what does Schwab hold".

Public API: `start_order_flow_stream` / `stop_order_flow_stream`
/ `get_option_contract_streaming_diagnostics`.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import time
from collections.abc import Callable
from typing import Any

import live_market_plane as _lmp
import live_price_rows
import push_changes
from app.options.order_flow import history as recent
from app.options.order_flow.state import (
    clear_all_live_state,
    push_book,
    push_level_one,
    push_option_top,
)
from instrument_identity import ticker_storage_key
from stream_spine import LATEST
from time_et import record_markets

log = logging.getLogger(__name__)

#: topic prefix -> the only `src` taken from the bus for it: Schwab's alone
_FROM_SCHWAB = {
    "quote.": "schwab_l1",
    "book.": "schwab_book",
    "optquote.": "schwab_options_l1",
    "news.": "schwab_news",
    "bar1m.": "schwab_chart",
    "chain.": "schwab_chain",
    "pricehistory.": "schwab_pricehistory",
    "markets.": "schwab_markets",
    "watchlist": "daemon_watchlist",
}
#: The finished price row per ticker (live_price_rows.price_row), the one the browser gets. The
#: console keeps no other copy of a live price; the last row stays until a newer one arrives.
_price_rows: dict[str, dict] = {}
#: how often each row is finished again and what is live restamped: the daemon's beat
BEAT_SEC = 1.0


def price_row(ticker: str) -> dict | None:
    return _price_rows.get(ticker_storage_key(ticker) or "")


def price_state(
    ticker: str, now: float, service: str = "LEVELONE_EQUITIES"
) -> tuple[str, str | None]:
    """`ticker`'s state on Schwab `service` (its quote, or a venue's book) at `now`, as the console
    serves it: the rule on the beat the console holds (live_market_plane.live_state) while that is
    not LIVE (the feed down, the symbol not held, its market not trading); while it is LIVE, the
    daemon's own verdict on its price row (`feed_label`, `outage`: live_price_rows.price_row), which
    alone holds Schwab's SECURITY_STATUS; NOT LIVE while no row from the daemon has arrived."""
    label, why = _lmp.live_state(ticker, service, now)
    if label != _lmp.LIVE:
        return label, why
    row = price_row(ticker)
    if row is None:
        return _lmp.NOT_LIVE, f"no price row from the daemon for {ticker_storage_key(ticker)} yet"
    return row["feed_label"], row["outage"]


#: the daemon while it runs (follow): watchlist requests go to it
_daemon = None
#: request id -> the future the daemon's watchlist record for it resolves (_ingest_pushed)
_watchlist_answers: dict[int, asyncio.Future] = {}
#: how long a watchlist request waits for the daemon's record (an add waits on Schwab's /quotes
#: answer)
WATCHLIST_ANSWER_SEC = 30.0


async def watchlist_request(action: str, ticker: str) -> dict:
    """An add or a removal ("add" | "remove") of `ticker`, sent to the daemon, which keeps the
    watchlist; its record once the daemon has answered (capture.watchlist_message: the list, what
    happened, Schwab's /quotes answer to an add's check). Raises ConnectionError while the daemon
    is not running, TimeoutError when no record comes in WATCHLIST_ANSWER_SEC."""
    if _daemon is None:
        raise ConnectionError("the capture daemon is not running")
    rid = time.time_ns()
    answer = asyncio.get_running_loop().create_future()
    _watchlist_answers[rid] = answer
    try:
        _daemon.console_request({"op": "watchlist", "action": action, "ticker": ticker, "id": rid})
        return await asyncio.wait_for(answer, WATCHLIST_ANSWER_SEC)
    finally:
        del _watchlist_answers[rid]


#: the contract Ed selected on the Flow panel, or None: the daemon streams it on both option
#: services on top of its option rule; told to the daemon at each start of it and on each change
_flow_contract: str | None = None


async def select_flow_contract(contract: str | None) -> None:
    """The Flow panel's selection (None: none), told to the daemon now when it runs, and at each
    start of it (follow), so a daemon restart keeps it."""
    global _flow_contract
    _flow_contract = contract
    if _daemon is not None:
        _daemon.console_request({"op": "flow_contract", "contract": contract})


# ── Runtime state (the daemon's task on the program's one event loop) ──
_feed_running = False

#: Each option contract's last streamed message time (LEVELONE_OPTIONS or OPTIONS_BOOK), keyed
#: by ticker_storage_key.
_option_contract_last_update_ts: dict[str, float] = {}

#: Called with the symbol of every streamed equity quote and every option quote carrying
#: GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME/VOLUME (server._on_stream_tick: reprices a viewed
#: ticker). Runs on the event loop, so it must return at once.
_on_tick_callback: Callable[[str], None] | None = None
_on_feed_callback: Callable[[float], None] | None = None
_tick_callback_failures = 0
#: Every streamed 1-minute bar (bar1m.SYM, Schwab CHART_EQUITY), for server._bar_writer to write.
streamed_bars: queue.SimpleQueue[dict] = queue.SimpleQueue()
#: Called on the event loop with (ticker, contracts, fetched_ts, None) for each whole chain the
#: daemon fetched, and with (ticker, None, ts, reason) for one it could not deliver
#: (server._on_chain).
_on_chain_callback: Callable[..., None] | None = None
#: ticker -> the chain being received: {"ts", "parts", "got": {part: contracts}}
_chain_parts: dict[str, dict] = {}


def assemble_chain_part(
    msg: dict,
) -> list[tuple[str, list | None, float, str | None, tuple | None]]:
    """One chain message from the daemon (complete_chain_capture.chain_messages) -> what it
    settles, in order: a chain whose parts did not all arrive before the next one began
    (ticker, None, ts, reason, None); a fetch that failed (ticker, None, ts, Schwab's answer, None);
    the whole chain once its last part is in (ticker, contracts, fetched_ts, None, (spot, spot_ts)),
    with the chain's one spot and its trade time. A chain missing a part is never returned."""
    tk, ts = msg.get("ticker"), msg.get("ts_recv")
    if not tk or not isinstance(ts, (int, float)):
        return []
    out = []
    cur = _chain_parts.get(tk)
    if cur is not None and cur["ts"] != ts:
        out.append(
            (
                tk,
                None,
                float(ts),
                f"the daemon's chain of {tk} arrived with "
                f"{len(cur['got'])} of its {cur['parts']} parts",
                None,
            )
        )
        del _chain_parts[tk]
        cur = None
    if "failed" in msg:
        _chain_parts.pop(tk, None)
        return [*out, (tk, None, float(ts), str(msg["failed"]), None)]
    if cur is None:
        if int(msg["part"]) != 0:
            return out  # a chain begun before this console connected: not its chain
        cur = _chain_parts[tk] = {"ts": ts, "parts": int(msg["parts"]), "got": {}}
    cur["got"][int(msg["part"])] = msg.get("contracts") or []
    if len(cur["got"]) == cur["parts"]:
        del _chain_parts[tk]
        out.append(
            (
                tk,
                [c for i in range(cur["parts"]) for c in cur["got"][i]],
                float(ts),
                None,
                (msg["spot"], msg["spot_ts"]),
            )
        )
    return out


def _tick(sym: str) -> None:
    global _tick_callback_failures
    if _on_tick_callback is None:
        return
    try:
        _on_tick_callback(sym)
    except Exception as e:  # noqa: BLE001 -- counted + WARNING; ingest must go on
        _tick_callback_failures += 1
        if _tick_callback_failures & (_tick_callback_failures - 1) == 0:
            log.warning(
                "tick callback failed for %s (%s failures): %s", sym, _tick_callback_failures, e
            )


def _service_feed(symbol: str | None, service: str, now: float, product: str | None) -> dict:
    """One Schwab option service's feed for contract `symbol` at `now`, as the page shows it: its
    state by the one live rule on its own option market `product` (live_market_plane.live_state:
    LIVE, OFFLINE or NOT LIVE), and how long ago the daemon last received anything on that service
    (its own report)."""
    status = _lmp.daemon_status(now)
    reports = status.get("health") if status is not None else None
    health = reports.get(service) if reports is not None else None
    return {
        "state": _lmp.live_state(symbol, service, now, product)[0],
        "age_sec": health.get("age_sec") if health is not None else None,
    }


#: the option quote fields the levels are priced from: a message carrying one reprices
_REPRICE_FIELDS = ("GAMMA", "DELTA", "OPEN_INTEREST", "TOTAL_VOLUME", "VOLUME")


def _ingest_pushed(topic: str, msg: Any) -> None:
    """Apply ONE daemon-pushed Schwab stream message to the live planes.

    Every timestamp written is the message's own `ts_recv` -- the daemon's receive time for
    it -- never the time this console processed it (a delayed message must not read as
    fresh).

      quote.SYM    LEVELONE_EQUITIES -> order-flow state (the tape); the live price is the
                   daemon's price row (_took_row), never rebuilt here
      book.SYM     NASDAQ_BOOK / NYSE_BOOK -> order-flow book; OPTIONS_BOOK -> the option
                   contract's book
      optquote.SYM LEVELONE_OPTIONS -> order-flow state for the contract
      markets.DATE Schwab's /markets answer -> that date's sessions (time_et), when it is a 200

    Every option quote carrying GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME/VOLUME is passed to the
    tick callback (an equity's tick is its price row's arrival). A message missing its symbol, its
    receive time or its Schwab payload is dropped whole: nothing is applied with a guessed
    part."""
    if not isinstance(msg, dict):
        return None
    if topic.startswith("chain."):
        for done in assemble_chain_part(msg):
            if _on_chain_callback is not None:
                _on_chain_callback(*done)
        return None
    if topic.startswith("markets."):
        if msg["status"] == 200:
            record_markets(msg["answer"])
        return None
    if topic == "watchlist":  # the daemon's answer to a watchlist request
        if (
            msg["request_id"] in _watchlist_answers
            and not _watchlist_answers[msg["request_id"]].done()
        ):
            _watchlist_answers[msg["request_id"]].set_result(msg)
        return None
    sym = msg.get("symbol")
    ts = msg.get("ts_recv")
    if not sym or not isinstance(ts, (int, float)):
        return None
    ts = float(ts)
    kind = topic.split(".", 1)[0]
    if kind in ("bar1m", "pricehistory"):  # the bar writer's: a streamed bar, a price history
        streamed_bars.put(msg)
        return None
    received = {f: stamp[1] for f, stamp in msg["field_ts"].items()} if "field_ts" in msg else None
    if kind == "quote":
        item = msg.get("native")
        if not isinstance(item, dict):
            return None
        push_level_one(sym, item, ts_recv=ts, field_received=received)
        push_changes.changed(sym, push_changes.FLOW)
        return None
    if kind == "book":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_book(sym, content, msg["service"])
        if msg.get("service") == "OPTIONS_BOOK":
            _option_contract_last_update_ts[sym] = ts
        else:
            recent.BOOKS.record(sym, msg["service"], content, ts)
            push_changes.changed(sym, push_changes.FLOW)
        return None
    if kind == "optquote":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_level_one(sym, content, ts_recv=ts, field_received=received)
        push_option_top(sym, content)
        recent.TAPE.record(sym, content, ts)
        _option_contract_last_update_ts[sym] = ts
        # a tick when the newest message carried a value the levels use (a merged record holds
        # the last of each field; only one this message brought is new)
        if any(f in content and (received is None or received[f] == ts) for f in _REPRICE_FIELDS):
            _tick(sym)
    return None


def _rows_wanted(now: float) -> list[str]:
    """The price rows this console holds at `now`: every equity the daemon streams (its
    heartbeat's held LEVELONE_EQUITIES -- the watchlist and the market context, as Schwab
    accepted them)."""
    return sorted(_lmp.held_by_daemon("LEVELONE_EQUITIES", now))


def _took_row(ticker: str) -> None:
    """The plane's new values for `ticker` (live_market_plane.add_row_listener): its row, and the
    equity's tick."""
    _price_rows[ticker] = live_price_rows.price_row(ticker, time.time())
    _tick(ticker)


async def _beats() -> None:
    """Every BEAT_SEC, a fresh row for each equity the daemon streams, so a dead feed reads dead,
    and what is live restamped. A beat that fails is logged, and the next one runs."""
    while True:
        now = time.time()
        try:
            for ticker in _rows_wanted(now):
                _price_rows[ticker] = live_price_rows.price_row(ticker, now)
            _feed_changed(now)
        except Exception as e:  # noqa: BLE001 -- logged; the next beat runs
            log.warning("console beat: %s: %s", type(e).__name__, e)
        await asyncio.sleep(BEAT_SEC)


def from_schwab(topic: str, record: Any) -> bool:
    """A bus record that came from Schwab (a chain: its parts)."""
    first = record[0] if isinstance(record, list) and record else record
    if not isinstance(first, dict):
        return False
    return any(
        topic.startswith(prefix) and first.get("src") == src for prefix, src in _FROM_SCHWAB.items()
    )


async def follow(bus, daemon) -> None:
    """The daemon's bus, for the daemon's life: the Flow panel's contract told first
    (select_flow_contract), the watchlist requests sent to it (watchlist_request), each new price
    row (_took_row), and every Schwab record applied the moment it changes (_ingest_pushed) -- no
    poll interval, no database read. A record that fails is logged, and the next one is applied.
    When the daemon ends, the feed is down and the last values stand, marked."""
    global _daemon
    sub = bus.subscribe("", policy=LATEST)
    daemon.console_request({"op": "flow_contract", "contract": _flow_contract})
    _daemon = daemon
    _lmp.add_row_listener(_took_row)
    beats = asyncio.create_task(_beats(), name="console beats")
    try:
        while True:
            topic, record = await sub.get()
            if not from_schwab(topic, record):
                continue
            for msg in record if isinstance(record, list) else [record]:
                try:
                    _ingest_pushed(topic, msg)
                except Exception as e:  # noqa: BLE001 -- logged; the next record is applied
                    log.warning("%s not applied: %s: %s", topic, type(e).__name__, e)
                # a backlog of chain parts would hold the loop: the daemon's status beat and every
                # route take a turn
                await asyncio.sleep(0)
    finally:
        beats.cancel()
        _lmp.remove_row_listener(_took_row)
        _daemon = None
        bus.unsubscribe(sub)
        _lmp.record_feed_down()
        _feed_changed(time.time())


#: a contract's subscription, as the Flow panel shows it: the daemon's option rule holds it on
#: LEVELONE_OPTIONS, or it does not (capture.Daemon.pick_options streams each ticker's contracts
#: with the highest gamma)
SUBSCRIBED, NOT_STREAMED = "SUBSCRIBED", "NOT STREAMED"


def get_option_contract_streaming_diagnostics(
    for_contract: str, now: float, product: str | None
) -> dict[str, Any]:
    """Whether the daemon streams `for_contract` and is receiving it at `now`, distinct from the
    book's own content ages (options_live_payload): its subscription (SUBSCRIBED / NOT STREAMED,
    from the symbols on the latest beat), and each feed by the one live rule on its own option
    market `product` (live_market_plane.live_state). A missing beat keeps that last subscription.
    The feed health says whether it is live. The page paints ACTIVE only while that feed is live."""
    c = ticker_storage_key(for_contract)
    levelone = _lmp.feed_now(now).held.get("LEVELONE_OPTIONS")
    l1 = _service_feed(c, "LEVELONE_OPTIONS", now, product)
    healthy = bool(_feed_running and l1["state"] == _lmp.LIVE)
    return {
        "queried_contract": c,
        "subscription_state": SUBSCRIBED
        if levelone is not None and c in levelone
        else NOT_STREAMED,
        "streaming_last_update_ts": _option_contract_last_update_ts.get(c),
        "feed_health": {
            "replay": "healthy" if healthy else "stale" if _feed_running else "not connected",
            "l1": l1,
            "book": _service_feed(c, "OPTIONS_BOOK", now, product),
        },
    }


def _feed_changed(now: float) -> None:
    """The daemon's heartbeat changed: the console restamps what is live."""
    if _on_feed_callback is not None:
        _on_feed_callback(now)


def start_order_flow_stream(
    on_tick_callback: Callable[[str], None] | None = None,
    on_chain_callback: Callable[..., None] | None = None,
    on_feed_callback: Callable[[float], None] | None = None,
) -> bool:
    """Set what the feed from the capture daemon calls (follow reads it)."""
    global _feed_running, _on_tick_callback, _on_chain_callback, _on_feed_callback
    _on_tick_callback = on_tick_callback
    _on_chain_callback = on_chain_callback
    _on_feed_callback = on_feed_callback
    _feed_running = True
    log.info("Live-plane feed started")
    return True


def stop_order_flow_stream() -> None:
    """Clear the live state the feed fed."""
    global _feed_running
    _feed_running = False
    _option_contract_last_update_ts.clear()
    clear_all_live_state()
