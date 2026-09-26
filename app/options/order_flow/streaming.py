"""
Live-plane feed for the single active UI ticker — READ-ONLY consumer of the canonical
capture daemon (app.market_data.schwab.streaming.capture), never a second Schwab session.

SINGLE-STREAM-AUTHORITY LAW (root-fixed here): this module used to own its own
`schwab.streaming.StreamClient`, logging into Schwab independently of the canonical
capture daemon — two authenticated sockets on one account, racing each other for the
same market truth. It now opens ZERO Schwab connections. The daemon is the one producer.

LIVE PUSH (2026-09-23): the daemon forwards every Schwab stream message to this module over
a local WebSocket (app.market_data.schwab.streaming.live_push, ws://127.0.0.1:8799) the
moment it arrives, and this module applies it to the in-process planes
(`app.options.order_flow.state`, `live_market_plane`). The database is NOT in the live
path: it used to be -- this module polled `stream_capture.db` every 0.5s -- which put a
disk write, a commit and a poll between Schwab and the screen. stream_capture.db stays the
permanent record (options history reads it); nothing live reads it. If the push connection
drops, the live values go stale and the screen says so; nothing falls back to the database
(operator rule 2026-09-23: no fallbacks).

Dynamic ticker switching survives the process boundary via a small signal file
(`stream_spine.write_active_ticker_signal` / `read_active_ticker_signal`): this module
WRITES the desired active ticker, the daemon POLLS it and adds/drops NASDAQ_BOOK /
NYSE_BOOK subscription for that one symbol. Equity L1 needs no signal — the daemon
already captures LEVELONE_EQUITIES for its whole configured roster; whichever symbol
this module is asked to serve, its rows are already there.

Public API is unchanged from the pre-repair module (same names, same call sites in
server.py): `start_order_flow_stream` / `stop_order_flow_stream` /
`set_streaming_active_ticker` / `get_plane_authority_for_ticker` /
`streaming_l1_cache_usable` / `get_streaming_diagnostics` / `is_order_flow_stream_running`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

from instrument_identity import (
    BROKER_INDEX_BARE_ROOTS,
    option_underlying_root,
    ticker_storage_key,
    vendor_option_root,
)
from stream_spine import (
    EQUITY_SYMBOLS_MAX_HELD,
    OPTION_CONTRACTS_MAX_HELD,
    PRODUCER_CLAIM_TTL_SEC,
    STREAM_DB_DEFAULT,
    read_open_coverage_symbols,
    rank_option_contracts,
    read_producer_heartbeat,
    read_rejected_option_contracts,
    resolve_stream_db_path,
    read_active_option_contract_signal,
    write_active_option_contract_signal,
    write_active_option_contracts_signal,
    write_active_ticker_signal,
    write_equity_symbols_signal,
)

from app.options.order_flow.state import (
    clear_all_live_state,
    clear_symbol,
    forget_unsubscribed_symbols,
    push_book,
    push_level_one,
)

import live_market_plane as _lmp

log = logging.getLogger(__name__)

#: The daemon's live push endpoint (app.market_data.schwab.streaming.live_push). Module
#: attribute, read at connect time, so a test can point the feed at its own server.
from app.market_data.schwab.streaming.live_push import LIVE_PUSH_HOST, LIVE_PUSH_PORT

LIVE_PUSH_URL = f"ws://{LIVE_PUSH_HOST}:{LIVE_PUSH_PORT}"
#: Wait between reconnect attempts when the daemon's push server is down. While it is down
#: no live value is refreshed -- the freshness checks turn them stale; nothing substitutes.
PUSH_RECONNECT_SEC = 1.0

# ── Runtime state (single asyncio task inside the SAME event loop as the server —
#    no dedicated thread/loop needed once nothing here opens a socket) ──
_feed_task: Optional[asyncio.Task] = None
_feed_running = False
#: A FIFTH independent review (2026-09-13), REPRODUCED: `_feed_running` alone cannot tell
#: "this dispatched work belongs to the CURRENT feed lifecycle" from "some earlier
#: lifecycle also happened to leave `_feed_running` True" -- a stop() then a start() BEFORE
#: an old queued task drains flips `_feed_running` False then back to True, and a check of
#: the boolean alone cannot distinguish the two lifecycles. Concretely reproduced: hold an
#: AMD hook call, queue a PLTR dispatch behind it, stop the feed (PLTR still queued,
#: unstarted), RESTART the feed (`_feed_running` -> True again, a NEW lifecycle), THEN
#: release AMD -- PLTR's task, dispatched under the OLD lifecycle, incorrectly ran under
#: the NEW one because `_run_streamed_greeks_hook_if_live`'s own re-check only ever asked
#: "is SOME feed running right now," never "is the SAME feed running that queued me."
#: Bumped once per `start_order_flow_stream` call; each dispatched hook task captures the
#: generation active when `_feed_loop` itself started and must match it again at actual
#: execution time, not just find `_feed_running` true.
_feed_generation = 0
_active_ticker: Optional[str] = None
_streaming_last_update_ts: Optional[float] = None
_last_subscribe_completed_ts: Optional[float] = None
#: Push connection state for diagnostics: when the current connection opened (None while
#: disconnected) and how many messages it has applied.
_push_connected_ts: Optional[float] = None
_push_messages_applied = 0

#: The one option CONTRACT (OSI symbol) whose LEVELONE_OPTIONS/OPTIONS_BOOK rows this feed
#: replays — a SEPARATE slot from _active_ticker (an equity ticker and an option contract
#: on that same underlying can be watched at once; they are different symbol identities in
#: every table and signal file).
_active_option_contract: Optional[str] = None
#: Own staleness clock, separate from the equity ticker's — an option contract watched
#: alongside a ticker must be able to go stale (or come up fresh) independently.
_option_streaming_last_update_ts: Optional[float] = None
_option_last_subscribe_completed_ts: Optional[float] = None
#: PER-CONTRACT staleness clock (RC-UI-3 finding #4, 2026-09-12, REPRODUCED): the single
#: scalar above is updated by ANY contract's message -- primary OR any additional one (see
#: _ingest_pushed) -- so a fresh additional contract can mask a genuinely
#: stale primary, and vice versa: querying one contract's health answered with another
#: contract's heartbeat. Keyed by the SAME ticker_storage_key identity
#: set_active_option_contract/set_active_option_contracts already normalize to.
_option_contract_last_update_ts: dict[str, float] = {}

_on_tick_callback: Optional[Callable[[str], None]] = None

#: Called with (contract_symbol, ts_recv) at most ONCE per underlying per burst of pushed
#: messages carrying GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME (ts_recv is the FRESHEST such
#: message's own receive time -- see HookBurst) -- lets a consumer
#: (server.py's gamma-surface cache) freshen itself the instant new Greeks/OI/volume are known,
#: instead of waiting for the next wide-chain REST cycle. TOTAL_VOLUME is included (not just
#: the Greeks) so a volume-only tick -- no Greeks/OI change -- still reaches the per-strike
#: volume column and compute_exposures_by_strike's own call/put volume aggregation, not just
#: the ticker-level header display; independent-review finding (2026-09-12): "the current hook
#: is triggered by GAMMA/DELTA/OPEN_INTEREST; that does not complete volume-only update
#: delivery." Once-per-burst (not once-per-message) is itself a fix for a separate independent-
#: review finding (2026-09-12), REPRODUCED: calling this per row meant a burst of N rows
#: triggered N sequential expensive recomputes on the consumer side. Same
#: shape/precedent as `_on_tick_callback` above; kept separate because ITS payload (an option
#: contract symbol + the field's own receive time) is different from a bare ticker, and a
#: caller wanting only one of the two must not be forced to filter the other's calls.
_streamed_greeks_hook: Optional[Callable[[str, float], None]] = None


def set_streamed_greeks_hook(fn: Optional[Callable[[str, float], None]]) -> None:
    """Register (or clear, with None) the callback `_feed_loop` dispatches at most once per
    underlying per burst of pushed messages carrying GAMMA/DELTA/OPEN_INTEREST/TOTAL_VOLUME.
    One slot, like `_on_tick_callback` -- the daemon has exactly one composition
    root (server.py's startup) that wires this, not a list of subscribers to fan out to."""
    global _streamed_greeks_hook
    _streamed_greeks_hook = fn


def _run_streamed_greeks_hook_if_live(rep_sym: str, rep_ts: float, generation: int) -> str:
    """The actual executor-thread entry point `_start_hook_task` submits, in place of calling
    `_streamed_greeks_hook` directly.

    A FOURTH independent review (2026-09-13), REPRODUCED: `_dispatch_hook_background`'s fresh-
    dispatch path (a root not already in `_hook_inflight_roots`) submits straight to
    `hook_executor` with NO `_feed_running` check at all -- only `_done`'s trailing-rerun path
    checks it. `hook_executor` is single-worker (RC-556): two different underlyings' tasks
    (e.g. a long-running AMD hook and a freshly-dispatched PLTR hook) can both be legitimately
    SUBMITTED while only one runs at a time, so PLTR's task can still be sitting queued, not
    yet started, at the instant shutdown sets `_feed_running = False` -- and `executor.shutdown
    (wait=False)` does not cancel queued-but-unstarted work, so PLTR's task WILL eventually run
    once AMD's finishes, regardless of shutdown, because nothing upstream of the task's own
    entry point ever re-checks liveness.

    Fixed here, at the one point every hook invocation funnels through regardless of which root
    or dispatch path submitted it: re-check `_feed_running` the instant this actually starts
    executing on the worker thread (not when it was submitted) and skip the real hook body
    entirely if the feed has already stopped -- closing the gap `_done`'s existing shutdown
    check (RC-556) only ever covered for a same-root trailing rerun, never a different root's
    independently-submitted fresh dispatch.

    A FIFTH independent review (2026-09-13), REPRODUCED: `_feed_running` alone is not enough --
    a stop() followed by a restart() before this task drains flips it back to True for a NEW
    lifecycle, and this check alone would then wrongly treat OLD, pre-restart work as
    belonging to the current one. `generation` is the lifecycle identifier `_feed_loop`
    captured for itself when IT started; this only runs the real hook body when that captured
    generation still matches the CURRENT `_feed_generation` -- not merely when some feed
    happens to be running right now."""
    if not _feed_running or generation != _feed_generation:
        return "feed_stopped"
    if _streamed_greeks_hook is None:
        return "no_hook_registered"
    return _streamed_greeks_hook(rep_sym, rep_ts)


STREAMING_STALE_MS = 25_000.0
GRACE_AFTER_SUBSCRIBE_SEC = 8.0

#: FRESHNESS/HEALTH SEMANTIC AUDIT (OPTIONS_ORDER_FLOW_V1, 2026-08-30): this module's own
#: streaming_connected/streaming_healthy answer ONE question — "is my live-push feed
#: running, and did a message for the active symbol arrive recently (by its own receive
#: time)" — which is a PROXY for daemon health, not the daemon's Schwab-socket truth itself:
#: a quiet symbol and a dead socket look alike to it. The daemon
#: itself already computes the REAL truth per Schwab service (stream_spine.HealthRegistry,
#: fed by health.beat() calls inside the actual message handlers in tools/
#: run_stream_capture.py) and writes it to STATUS_PATH every ~10s — but nothing ever read
#: it back into the UI-facing diagnostics until now. "local feed task exists" must never
#: masquerade as "Schwab stream connected" — _read_daemon_upstream_health is the ground
#: truth for that distinct question, surfaced as its own field, never blended into
#: streaming_healthy.
from runtime_layout import reports_dir as _artifact_reports_dir  # RC-523: artifacts root

_DAEMON_STATUS_PATH = _artifact_reports_dir() / "stream_capture_status.json"
#: The daemon's write_status() loop runs on a 10s cadence — 3x that as a liveness bound on
#: the STATUS FILE ITSELF (not the per-service health it carries): if the file hasn't been
#: touched this recently, the daemon PROCESS may be dead, and every entry inside a dead
#: process's last-written snapshot would be lying about "recent" if trusted at face value.
_DAEMON_STATUS_STALE_SEC = 30.0


def _read_daemon_upstream_health(services: tuple[str, ...]) -> dict[str, dict]:
    """Ground truth for "is the Schwab websocket itself actually connected and receiving
    frames for these services" — read from the CANONICAL DAEMON's own status file, never
    derived from this module's local replay state. Fails closed to state='UNKNOWN' (never
    fabricates 'RUNNING') on any read/parse failure, or when the status file's own
    last-write timestamp is stale enough that the daemon PROCESS itself may not be
    running — a per-service health entry from a dead process's last snapshot is not
    'current' just because the JSON happens to still say RUNNING."""
    try:
        status = json.loads(_DAEMON_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {s: {"state": "UNKNOWN", "age_sec": None} for s in services}
    status_ts = status.get("ts")
    status_age = (time.time() - status_ts) if isinstance(status_ts, (int, float)) else None
    if status_age is None or status_age > _DAEMON_STATUS_STALE_SEC:
        return {s: {"state": "UNKNOWN", "age_sec": None,
                    "daemon_status_stale_sec": status_age} for s in services}
    health = status.get("health")
    health = health if isinstance(health, dict) else {}
    out: dict[str, dict] = {}
    for s in services:
        entry = health.get(s)
        out[s] = ({"state": entry.get("state"), "age_sec": entry.get("age_sec")}
                  if isinstance(entry, dict) else {"state": "UNKNOWN", "age_sec": None})
    return out


def _log_stream(phase: str, **kwargs: Any) -> None:
    if kwargs:
        extra = " ".join(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
        log.info("STREAM_DIAG %s %s", phase, extra)
    else:
        log.info("STREAM_DIAG %s", phase)


def _streaming_healthy() -> bool:
    if not (_feed_running and _active_ticker):
        return False
    now = time.time()
    if _streaming_last_update_ts is not None:
        return (now - _streaming_last_update_ts) * 1000.0 <= STREAMING_STALE_MS
    if _last_subscribe_completed_ts is not None and (now - _last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC:
        return True
    return False


def is_order_flow_stream_running() -> bool:
    return bool(_feed_running)


def get_plane_authority_for_ticker(ticker: str) -> str:
    """The state of this ticker's STREAMED quote: streaming | stream_not_running |
    not_active_ticker | stream_unhealthy. (It named REST modes -- rest_only /
    rest_fallback_explicit / rest_mismatch -- until 2026-09-24; nothing writes REST quotes
    into the plane any more, so those labels described a path that does not exist.)"""
    t = ticker_storage_key(ticker)
    if not _feed_running:
        return "stream_not_running"
    if not _active_ticker or _active_ticker.upper() != t:
        return "not_active_ticker"
    if _streaming_healthy():
        return "streaming"
    return "stream_unhealthy"


FAST_QUOTE_STREAM_CACHE_MAX_AGE_MS = 5_000.0


def streaming_l1_cache_usable(ticker: str) -> bool:
    t = ticker_storage_key(ticker)
    if get_plane_authority_for_ticker(t) != "streaming":
        return False
    last = _streaming_last_update_ts
    if last is None:
        return False
    return (time.time() - last) * 1000.0 <= FAST_QUOTE_STREAM_CACHE_MAX_AGE_MS


#: How stale a producer heartbeat row may be before it stops counting as "current" —
#: matches the daemon's own status-write cadence bound (_DAEMON_STATUS_STALE_SEC, 3x
#: its ~10s write loop), the SAME grounding that already governs the file-based
#: upstream-health check. write_status() writes the DB heartbeat and the status file
#: on the SAME call, so one bound serves both.
#: Defined in stream_spine so the DAEMON reads the identical bound: a controlled surrender
#: has to know exactly how long a claim it could not retract can still confirm. Same value
#: as _DAEMON_STATUS_STALE_SEC (30s, 3x the ~10s write loop); one definition, two readers.
STREAM_PRODUCER_HEARTBEAT_STALE_SEC = PRODUCER_CLAIM_TTL_SEC


def _stream_db_identity_status() -> dict[str, Any]:
    """PRODUCER IDENTITY VIA THE SHARED DATA PLANE (PR214_RTH_DEFECT_REMEDIATION_FINAL_GAPS,
    Gap 2): opens THIS process's own resolved db_path — the SAME connection the replay
    loop already reads quote/book rows through — and looks for a fresh
    stream_producer_heartbeat row the daemon wrote through that identical file. Identity
    is proven STRUCTURALLY (same file => same connection sees the same row), not by
    string-comparing two independently-resolved path values.

    PR214_RTH_DEFECT_REMEDIATION_V1's prior mechanism compared this process's resolved
    path against a path the daemon self-reported into a SEPARATE, ALSO checkout-relative
    status file (_DAEMON_STATUS_PATH) — the identical defect class Defect 2 fixed, one
    level up: in the real two-checkout failure geometry, the server read its OWN
    checkout's copy of that status file and got identity_match=None (unknown), never the
    confirmed-False the fail-closed guard requires. Reading the heartbeat OUT OF the
    exact file already being consumed removes that second path-identity channel
    entirely — there is nothing left to independently mis-resolve.

    `identity_match`:
      True  — a heartbeat row is visible on THIS connection and is fresh (within
              STREAM_PRODUCER_HEARTBEAT_STALE_SEC). Confirmed live producer, same file.
      False — a heartbeat row is visible but STALE. CONFIRMED, not unknown: something
              wrote here, but not recently enough to trust as a live producer.
      None  — no heartbeat row at all (the DB cannot be opened yet, is empty, or a
              pre-heartbeat daemon has never written one here). Unknown — covers cold
              start AND "this resolved path is not the file a producer is writing to"
              (e.g. a genuine two-checkout mismatch) identically; callers must not treat
              an indefinite None as healthy (see get_streaming_diagnostics)."""
    resolved = str(resolve_stream_db_path(STREAM_DB_DEFAULT))
    con = _open_capture_db_readonly()
    if con is None:
        return {"server_resolved_path": resolved, "producer_heartbeat": None, "identity_match": None}
    try:
        beat = read_producer_heartbeat(con)
    finally:
        con.close()
    if beat is None:
        return {"server_resolved_path": resolved, "producer_heartbeat": None, "identity_match": None}
    age = time.time() - beat["heartbeat_ts"]
    return {
        "server_resolved_path": resolved,
        "producer_heartbeat": {**beat, "age_sec": age},
        "identity_match": age <= STREAM_PRODUCER_HEARTBEAT_STALE_SEC,
    }


def _identity_forces_unhealthy(db_identity: dict, last_subscribe_completed_ts: Optional[float],
                               now: float) -> bool:
    """Gap 2: streaming_healthy=True must never coexist indefinitely with an unproven
    producer identity. A CONFIRMED stale/absent-then-found-stale heartbeat
    (identity_match is False) fails closed unconditionally, regardless of local replay
    freshness. identity_match is None (no heartbeat visible on this resolved path at
    all — cold start, or a genuine cross-checkout mismatch, indistinguishable from each
    other by design; see _stream_db_identity_status) is tolerated ONLY within the SAME
    startup grace window _streaming_healthy/_option_streaming_healthy already grant
    local replay staleness (GRACE_AFTER_SUBSCRIBE_SEC) — brief cold-start unknown is
    fine, an indefinite unknown is not (operator requirement, verbatim: 'Unknown may
    exist briefly during cold startup, but it cannot coexist indefinitely with a
    positive healthy connected stream plane claim')."""
    m = db_identity["identity_match"]
    if m is False:
        return True
    if m is None:
        within_grace = (last_subscribe_completed_ts is not None
                        and (now - last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC)
        return not within_grace
    return False


def get_streaming_diagnostics() -> dict[str, Any]:
    now = time.time()
    last = _streaming_last_update_ts
    stale_ms: Optional[float]
    if last is not None:
        stale_ms = max(0.0, (now - last) * 1000.0)
    elif _last_subscribe_completed_ts is not None and (now - _last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC:
        stale_ms = 0.0
    else:
        stale_ms = None

    db_identity = _stream_db_identity_status()
    healthy = _streaming_healthy()
    if _identity_forces_unhealthy(db_identity, _last_subscribe_completed_ts, now):
        # Fail closed: producer identity is confirmed mismatched/stale, or has never
        # been established beyond the startup grace window -- never report a connected
        # stream plane on that basis, no matter what the local replay staleness says.
        healthy = False
    return {
        "streaming_connected": bool(_feed_running),
        "streaming_ticker": _active_ticker,
        "streaming_last_update_ts": last,
        "streaming_staleness_ms": stale_ms,
        "streaming_healthy": healthy,
        # Ground truth for the Schwab socket itself (see _read_daemon_upstream_health's
        # docstring) — distinct from streaming_healthy above, which only proves this
        # module's own live-push feed is alive and recently updated.
        "daemon_upstream_health": _read_daemon_upstream_health(("LEVELONE_EQUITIES",)),
        "stream_db_identity": db_identity,
    }


def _open_capture_db_readonly(db_path=None) -> Optional[sqlite3.Connection]:
    """Read-only by construction (uri mode=ro), never a write handle onto the daemon's
    database — this module carries observations, it does not produce them.

    `db_path` defaults to the MODULE ATTRIBUTE at call time, not a parameter default bound
    once at function-definition time — a default of `STREAM_DB_DEFAULT` directly would
    freeze whatever that name pointed to when this module was imported, so a caller (or a
    test) that reassigns the module attribute afterward would silently be ignored.

    PR214_RTH_DEFECT_REMEDIATION_V1: goes through `resolve_stream_db_path`, the ONE
    canonical resolver `app.market_data.schwab.streaming.capture`'s CaptureWriter also uses, with
    THIS module's own `STREAM_DB_DEFAULT` (still test-monkeypatchable, unchanged) as the
    explicit reader default; production resolves to the one runtime_layout path (RC-534)."""
    if db_path is None:
        db_path = resolve_stream_db_path(STREAM_DB_DEFAULT)
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        # Autocommit: a caller that reuses this handle must see later CaptureWriter
        # commits. Default isolation_level="" opens a deferred snapshot on the first
        # SELECT and holds it until commit, hiding them. One statement = one snapshot.
        con.isolation_level = None
        return con
    except sqlite3.OperationalError:
        return None   # daemon has not created the DB yet (cold start) — retry next tick


_tick_callback_failures = 0


def _ingest_pushed(topic: str, msg: Any) -> "tuple[str, float] | None":
    """Apply ONE daemon-pushed Schwab stream message to the live planes.

    The same plane-ingest calls the DB replay made, now fed straight from the daemon's
    bus. Every timestamp written is the message's own `ts_recv` -- the daemon's receive
    time for it -- never the time this console processed it (a delayed message must not
    read as fresh; 2026-09-23 audit P0).

      quote.SYM    LEVELONE_EQUITIES -> order-flow state + live_market_plane (every roster
                   symbol; the plane serves each one's streamed LAST_PRICE)
      book.SYM     NASDAQ_BOOK / NYSE_BOOK -> order-flow book; OPTIONS_BOOK -> the option
                   contract's book
      optquote.SYM LEVELONE_OPTIONS -> order-flow state for the contract

    Returns (contract, ts_recv) when an option L1 message carried GAMMA/DELTA/
    OPEN_INTEREST/TOTAL_VOLUME/VOLUME -- the caller dispatches the streamed-greeks hook,
    coalesced per underlying -- else None. A message missing its symbol, its receive time
    or its Schwab payload is dropped whole: nothing is applied with a guessed part."""
    global _streaming_last_update_ts, _option_streaming_last_update_ts, _push_messages_applied
    if not isinstance(msg, dict):
        return None
    sym = msg.get("symbol")
    ts = msg.get("ts_recv")
    if not sym or not isinstance(ts, (int, float)):
        return None
    ts = float(ts)
    kind = topic.split(".", 1)[0]
    if kind == "quote":
        item = msg.get("native")
        if not isinstance(item, dict):
            return None
        push_level_one(sym, item, ts_recv=ts)
        try:
            _lmp.record_from_level_one_equity(sym, item, received_ts=ts)
        except Exception as e:  # noqa: BLE001 -- one malformed row must not end the feed
            log.debug("live_market_plane ingest %s: %s", sym, e)
        _push_messages_applied += 1
        if sym == _active_ticker:
            _streaming_last_update_ts = ts
        if _on_tick_callback:
            # every equity tick; the callback (server._dispatch_spot_gamma_refresh) decides by
            # the heatmap's OWN demand registry whether this ticker's surface is being viewed --
            # one "viewed" signal, not a second one built here from the raw watchlist
            try:
                _on_tick_callback(sym)
            except Exception as e:  # noqa: BLE001 -- counted + WARNING; ingest must go on
                global _tick_callback_failures
                _tick_callback_failures += 1
                if _tick_callback_failures & (_tick_callback_failures - 1) == 0:
                    log.warning("spot tick callback failed for %s (%s failures): %s",
                                sym, _tick_callback_failures, e)
        return None
    if kind == "book":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_book(sym, content)
        _push_messages_applied += 1
        if msg.get("service") == "OPTIONS_BOOK":
            _option_streaming_last_update_ts = ts
            _option_contract_last_update_ts[sym] = ts
        elif sym == _active_ticker:
            _streaming_last_update_ts = ts
        return None
    if kind == "optquote":
        content = msg.get("content")
        if not isinstance(content, dict):
            return None
        push_level_one(sym, content, ts_recv=ts)
        _push_messages_applied += 1
        _option_streaming_last_update_ts = ts
        _option_contract_last_update_ts[sym] = ts
        if ("GAMMA" in content or "DELTA" in content or "OPEN_INTEREST" in content
                or "TOTAL_VOLUME" in content or "VOLUME" in content):
            return sym, ts
        return None
    return None


def _hook_grouping_key(symbol: str) -> str:
    """The cheap, symbol-only proxy _feed_loop's hook-coalescing groups by: "which
    contracts likely share one underlying / one terrain-cache entry."

    Independent-review finding (2026-09-12), REPRODUCED: grouping by the RAW
    `vendor_option_root` alone treats a bare-rooted contract (root "SPX") and a
    weekly-rooted contract (root "SPXW") as two DIFFERENT groups, even when both
    genuinely belong to the SAME underlying ($SPX) -- refresh_gamma_surface_from_stream
    itself resolves this correctly via contract_matches_underlying's chain-aware
    fallback, but that fallback needs a candidate TICKER and a live chain-DB read;
    _feed_loop has neither readily available (it operates on bare option-contract
    symbols, with no reverse symbol->ticker mapping and no visibility into server.py's
    enrolled-ticker roster) and must not add a per-tick chain-DB dependency just to
    group cheaply. Root-caused with a NARROW, non-invented canonicalization: Schwab/OCC
    weekly-root suffixes for the specific handful of BROKER-INDEX products this repo
    already names as `$`-prefixed bare roots (BROKER_INDEX_BARE_ROOTS: SPX, NDX, RUT,
    DJX, XSP, OEX, ...) are that SAME bare root plus a trailing "W" (SPXW, NDXW, RUTW,
    ...) -- a real, documented vendor/exchange convention for these specific products,
    not a guess. Stripping a trailing "W" is applied ONLY when the resulting bare root
    is in that SAME small, curated set, so an unrelated real equity root that happens
    to end in "W" is never affected (it would have to coincidentally equal one of the
    ~11 named index roots after stripping, which real stock tickers do not). This does
    NOT replace contract_matches_underlying's full chain-aware equivalence check
    anywhere it is used for correctness (subscription reconciliation, coverage epochs,
    the hook's own terrain-cache resolution) -- it exists ONLY to avoid an
    over-eager, redundant-but-still-individually-correct extra hook call for this one
    well-known aliasing case; a contract this heuristic fails to group correctly still
    gets its own (still individually correct, merely less coalesced) hook call."""
    root = vendor_option_root(symbol) or symbol
    if root.endswith("W") and len(root) > 1:
        bare = root[:-1]
        if bare in BROKER_INDEX_BARE_ROOTS:
            return bare
    return root


class HookBurst:
    """Qualifying option ticks that arrived together, one entry per underlying.

    The streamed-greeks hook re-gathers EVERY desired contract of an underlying on each call,
    so ticks that arrive together need ONE call per underlying (grouped by
    `_hook_grouping_key`), carrying the freshest tick's receive time. Across bursts,
    `_dispatch_hook_background` keeps at most one call in flight per underlying plus one
    trailing re-run."""

    def __init__(self) -> None:
        self._by_root: "dict[str, tuple[str, float]]" = {}

    def note(self, sym: str, ts: float) -> bool:
        """Record one qualifying tick. True when it opens a new burst (schedule a flush)."""
        opens = not self._by_root
        root = _hook_grouping_key(sym)
        cur = self._by_root.get(root)
        if cur is None or ts >= cur[1]:
            self._by_root[root] = (sym, ts)
        return opens

    def take(self) -> "list[tuple[str, float]]":
        out = list(self._by_root.values())
        self._by_root.clear()
        return out


async def _feed_loop() -> None:
    """Consume the daemon's live push (LIVE_PUSH_URL) until the feed stops.

    Each frame is one Schwab stream message; it is applied the moment it arrives
    (_ingest_pushed) -- no poll interval, no database read. A dropped connection is retried
    every PUSH_RECONNECT_SEC; while it is down, the live values age out through their own
    freshness checks and the screen shows them stale. There is no second source."""
    global _feed_running
    # This lifecycle's own identity (see `_feed_generation`'s module-level docstring) --
    # captured ONCE here, not re-read per dispatch, so every hook task this ONE loop
    # invocation ever submits carries the SAME generation number regardless of how many
    # times `_feed_generation` itself is bumped by a LATER, unrelated restart.
    my_generation = _feed_generation
    # Independent-review finding (2026-09-12, state-authority review), REPRODUCED: the
    # streamed-greeks hook call (below) used to be AWAITED on the feed's single-worker DB
    # executor before the loop could proceed to its next poll tick -- a real, structurally
    # guaranteed cost, not a hypothetical: the hook's own committed benchmark
    # (tests/test_streamed_greeks_hook_v1.py::test_hook_coalescing_avoids_the_real_per_
    # call_cost_at_spxw_scale) MEASURED ~1.95s for one real call at full SPXW scale (42,001
    # contracts). Because state capture for the CURRENT tick's own newer rows (and every
    # OTHER contract/ticker this loop replays) only resumes once the awaited hook call
    # returns, a single slow surface recompute for one ticker delayed CAPTURE -- not just
    # publication -- for every ticker, by however long that one ticker's hook took.
    # Fixed by decoupling the two: the hook is dispatched as a background task on its own
    # dedicated executor and the loop's own progression to the next message no longer
    # waits for it (with the live push, the loop never waits on the hook at all).
    # Safe to run detached: refresh_gamma_surface_from_stream already compare-and-swaps
    # against the cache's own generation marker (_contracts_rest_computed_ts) before
    # publishing, so an overlapping or out-of-order background hook call for the same
    # ticker can only ever be silently superseded, never corrupt a newer result -- the
    # exact protection this file's own history (RC-UI-2/finding#2, the CAS fix) already
    # established for a REST cycle landing mid-eager-computation.
    hook_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="daemon-plane-feed-hook")
    hook_tasks: "set[asyncio.Task]" = set()
    loop = asyncio.get_event_loop()
    # Independent-review finding (2026-09-13), REPRODUCED: this dispatched one hook task
    # PER QUALIFYING TICK, per root, unconditionally -- with no check for "is a call for
    # this root already queued or running." Holding the hook callback while four
    # qualifying poll batches arrived queued FOUR separate tasks on the single-worker
    # executor; stopping the feed loop after only the first had started still let the
    # other THREE start running afterward, because each was already an independently
    # submitted `run_in_executor` future the executor's own non-blocking shutdown lets
    # finish. Coalescing within one burst already existed (HookBurst); nothing bounded it
    # ACROSS bursts. Fixed the same way the client-side coalescing
    # loader does it: at most one call in flight per root, and a call requested while one
    # is already in flight is coalesced into exactly one trailing re-run -- never piled up.
    # The hook itself (_desired_stream_greeks_for_ticker, called fresh every run) always
    # re-gathers the CURRENT state of every desired contract regardless of which symbol's
    # tick triggered the call, so a coalesced trailing run loses nothing a discarded
    # duplicate call would have captured.
    _hook_inflight_roots: "set[str]" = set()
    _hook_pending_by_root: "dict[str, tuple[str, float]]" = {}

    def _start_hook_task(root: str, rep_sym: str, rep_ts: float) -> None:
        fut = loop.run_in_executor(
            hook_executor, _run_streamed_greeks_hook_if_live, rep_sym, rep_ts, my_generation)
        task = asyncio.ensure_future(fut)
        hook_tasks.add(task)

        def _done(t: "asyncio.Task", _root: str = root, _sym: str = rep_sym) -> None:
            hook_tasks.discard(t)
            _hook_inflight_roots.discard(_root)
            exc = t.exception() if not t.cancelled() else None
            if exc is not None:
                log.debug("streamed-greeks hook failed for %s: %s", _sym, exc)
            nxt = _hook_pending_by_root.pop(_root, None)
            # Independent-review finding (2026-09-13), REPRODUCED, connected: the trailing
            # coalesced run must NOT start once this loop has stopped -- `_feed_running`
            # going False is this loop's own shutdown signal, checked here (not just at the
            # top of the while-loop below) precisely because this callback can fire AFTER
            # the loop has already exited. A task already in flight at shutdown still runs
            # to completion (existing CAS-protected, harmless-if-late publish); this only
            # stops a NEW one from ever being scheduled into a lifecycle that has ended.
            #
            # A FIFTH independent review (2026-09-13), REPRODUCED: `_feed_running` alone
            # let a trailing rerun queued under THIS generation start under a LATER one --
            # a stop() then a restart() between this callback firing and its own check
            # flips `_feed_running` back to True for a NEW lifecycle. `my_generation ==
            # _feed_generation` closes that gap the same way `_run_streamed_greeks_hook_
            # if_live` now does for a fresh dispatch.
            if nxt is not None and _feed_running and my_generation == _feed_generation:
                _hook_inflight_roots.add(_root)
                _start_hook_task(_root, nxt[0], nxt[1])
        task.add_done_callback(_done)

    def _dispatch_hook_background(rep_sym: str, rep_ts: float) -> None:
        root = _hook_grouping_key(rep_sym)
        if root in _hook_inflight_roots:
            _hook_pending_by_root[root] = (rep_sym, rep_ts)
            return
        _hook_inflight_roots.add(root)
        _start_hook_task(root, rep_sym, rep_ts)
    global _push_connected_ts
    from websockets.asyncio.client import connect

    # Frames already received are applied back to back without the loop yielding, so a
    # flush scheduled with call_soon runs once the whole burst has been applied -- one hook
    # dispatch per underlying for exactly what arrived together, no timer, no added delay.
    burst = HookBurst()

    def _flush_burst() -> None:
        for rep_sym, rep_ts in burst.take():
            _dispatch_hook_background(rep_sym, rep_ts)

    def _note_qualifying(sym: str, ts: float) -> None:
        if burst.note(sym, ts):
            loop.call_soon(_flush_burst)
    try:
        while _feed_running:
            try:
                async with connect(LIVE_PUSH_URL, max_size=None, open_timeout=5,
                                   ping_interval=20, ping_timeout=20) as ws:
                    _push_connected_ts = time.time()
                    _log_stream("PUSH_CONNECTED", url=LIVE_PUSH_URL)
                    async for frame in ws:
                        if not _feed_running:
                            break
                        try:
                            env = json.loads(frame)
                        except (TypeError, ValueError):
                            continue
                        if not isinstance(env, dict):
                            continue
                        if env.get("topic") == "daemon.heartbeat":
                            _lmp.record_feed_heartbeat(env.get("msg") or {}, time.time())
                            continue
                        hit = _ingest_pushed(str(env.get("topic") or ""), env.get("msg"))
                        if hit is not None and _streamed_greeks_hook is not None:
                            _note_qualifying(hit[0], hit[1])
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 -- daemon down/restarting: retry, never substitute
                log.info("live push unavailable (%s: %s); retrying in %.1fs",
                         type(e).__name__, e, PUSH_RECONNECT_SEC)
            _push_connected_ts = None
            _lmp.record_feed_down()        # no daemon, no live price -- visible at once
            if _feed_running:
                await asyncio.sleep(PUSH_RECONNECT_SEC)
    finally:
        _push_connected_ts = None
        _lmp.record_feed_down()
        # A background hook dispatch already submitted to hook_executor keeps running on
        # its worker thread to completion even after this loop stops -- its CAS in
        # refresh_gamma_surface_from_stream makes a late publish after a restart harmless
        # (superseded by whatever the next real cycle computes), never corrupting.
        hook_executor.shutdown(wait=False)
        _log_stream("FEED_LOOP_STOP_DONE")



def _contract_matches_underlying(
    contract: str | None, ticker: str, *, chain_db_path: Path | str | None = None,
) -> bool:
    """True when the vendor OSI symbol is for this exact underlying.

    Identity is the OCC/Schwab option root already in the vendor ``symbol``
    versus ``option_underlying_root`` (ticker_storage_key + BROKER_INDEX_BARE_ROOTS).
    Prefix match is not identity: ``CDE   260904C00005000`` is not ticker ``C``.

    Weekly index roots are not invented (``SPXW`` is not aliased to ``SPX``).
    When ``chain_db_path`` is given, a vendor root that actually appears on the
    ticker's nearest banked complete chain also matches — that is Schwab's
    ``$SPX`` → ``SPXW`` weekly root, read from the chain, not a hardcoded map.
    """
    if not contract or not ticker:
        return False
    osi_root = vendor_option_root(contract)
    und_root = option_underlying_root(ticker)
    if osi_root and und_root and osi_root == und_root:
        return True
    if not osi_root or chain_db_path is None:
        return False
    try:
        from app.options.contracts.default import _expiry_cutoff_et
        from calibration.complete_chain_capture import nearest_complete_chain_capture
        cap = nearest_complete_chain_capture(
            chain_db_path, ticker, on_or_after_expiry=_expiry_cutoff_et(),
        )
    except Exception:
        return False
    if not cap:
        return False
    for raw in cap.get("contracts") or []:
        if not isinstance(raw, dict):
            continue
        if vendor_option_root(str(raw.get("symbol") or "")) == osi_root:
            return True
    return False


def contract_matches_underlying(contract: str | None, ticker: str) -> bool:
    """Public wrapper for `_contract_matches_underlying` that resolves the chain DB path
    itself, for callers outside this module (server.py's streaming-overlay wiring) that
    should not need to know about DB_PATH plumbing to ask "does this option contract
    belong to this ticker".

    Independent-review finding (2026-09-12): server.py's own bare
    `vendor_option_root(contract) == option_underlying_root(ticker)` equality check silently
    excludes a valid contract whose vendor root genuinely differs from the underlying's
    (Schwab's $SPX -> SPXW weekly root is the canonical example) -- the exact case
    `_contract_matches_underlying`'s chain-aware fallback already exists to handle, and which
    this repo's own default-contract selection already relies on
    (`_ensure_default_option_contract_for_ticker`). Reusing it here means a legitimate weekly
    or adjusted-root contract's streamed Greeks are not silently dropped from the overlay."""
    chain_db: Path | str | None = None
    try:
        from db import DB_PATH
        chain_db = DB_PATH
    except Exception:
        chain_db = None
    return _contract_matches_underlying(contract, ticker, chain_db_path=chain_db)


def get_active_option_contract() -> Optional[str]:
    """The DESIRED option contract symbol (this daemon's own signal), or None.

    This is REQUESTED/desired state, same caveat as `_active_option_contract`'s other
    readers (see the PR214 premerge gap 1A note below at the diagnostics endpoint): it can
    be ahead of what the vendor has actually confirmed for one tick. Callers using this to
    freshen a computation with streamed data already tolerate that (the data simply is not
    there yet if the vendor hasn't caught up), so no additional confirmation is required
    here — unlike stopping a process, freshening a projection has no destructive downside
    to occasionally reading one tick early."""
    return _active_option_contract


def clear_active_option_contract(*, reason: str) -> None:
    """Drop desired option-contract state and tell the daemon to unsubscribe.

    Used when the active underlying changes and no replacement vendor symbol
    exists — keeping the previous underlying's contract would stream the wrong
    identity. Empty signal reads as None (fail-closed: no subscription).
    """
    global _active_option_contract, _option_streaming_last_update_ts
    old = _active_option_contract
    # Same guard as set_active_option_contract: do not wipe a symbol's shared live store
    # while the ADDITIONAL set still desires it.
    if old and old not in _active_option_contracts:
        clear_symbol(old)
        _option_contract_last_update_ts.pop(old, None)
        _log_stream("OPTION_CONTRACT_CLEARED", old=old, reason=reason)
    write_active_option_contract_signal("")
    _active_option_contract = None
    _option_streaming_last_update_ts = None


def _ensure_default_option_contract_for_ticker(ticker: str) -> None:
    """Server-owned collectable contract so OPTIONS_BOOK is not browser-gated.

    Operator POST /api/streaming/active-option-contract still wins. This only
    fills an empty slot or replaces a leftover contract from a different underlying.
    A foreign contract with no replacement is CLEARED, not retained.
    """
    global _active_option_contract
    chain_db: Path | str | None = None
    try:
        from db import DB_PATH
        chain_db = DB_PATH
    except Exception:
        chain_db = None
    if _contract_matches_underlying(
        _active_option_contract, ticker, chain_db_path=chain_db,
    ):
        return
    signaled = read_active_option_contract_signal()
    if _contract_matches_underlying(signaled, ticker, chain_db_path=chain_db):
        # Same signal file the daemon already polls. Bind the plane to it on
        # process start instead of leaving OPTIONS_BOOK browser-gated when the
        # default-contract lookup is not ready.
        set_active_option_contract(signaled)
        return
    try:
        from app.options.contracts.default import default_option_contract
        if chain_db is None:
            from db import DB_PATH
            chain_db = DB_PATH
        sym = default_option_contract(ticker, chain_db_path=chain_db)
    except Exception as e:
        log.debug("default option contract lookup failed: %s", e)
        if _active_option_contract:
            clear_active_option_contract(reason="lookup_failed_foreign_cleared")
        return
    if not sym:
        if _active_option_contract:
            clear_active_option_contract(reason="no_replacement_foreign_cleared")
        return
    set_active_option_contract(sym)

#: Which stocks/indexes a screen shows a live price for, by source. The daemon streams its
#: fixed --symbols roster only; everything else is requested here (the no-fallback rule
#: means an unstreamed symbol reads UNAVAILABLE, so every shown symbol must be requested).
#: The market context every page's header shows beside the selected ticker (Trade Desk,
#: operator 2026-09-25). Standing demand: measured 2026-09-25, a page whose watchlist did not
#: happen to hold them showed SPX/NDX/VIX as "—" all session because nobody requested them.
MARKET_CONTEXT_SYMBOLS = ("$SPX", "$NDX", "$VIX")
_EQUITY_DEMAND_ORDER = ("context", "watchlist", "board")
_equity_demand: "dict[str, list[str]]" = {k: [] for k in _EQUITY_DEMAND_ORDER}
_equity_demand["context"] = list(MARKET_CONTEXT_SYMBOLS)
_equity_not_admitted: "dict[str, str]" = {}
_equity_last_written: "list[str] | None" = None
_equity_lock = threading.Lock()


def rank_equity_symbols(active: "str | None", demand: "dict[str, list[str]]",
                        budget: int = EQUITY_SYMBOLS_MAX_HELD,
                        ) -> "tuple[list[str], dict[str, str]]":
    """(admitted, {not_admitted: reason}). Order of importance: the active ticker, then the
    market context (MARKET_CONTEXT_SYMBOLS), then the watchlist in its own order, then the
    gamma board. Duplicates count once, at their
    most important place; everything past the budget is named, never silently cut."""
    ordered: list[str] = []
    for sym in [active, *[s for k in _EQUITY_DEMAND_ORDER for s in demand.get(k, [])]]:
        t = ticker_storage_key(sym or "")
        if t and t not in ordered:
            ordered.append(t)
    admitted = ordered[:max(budget, 0)]
    not_admitted = {t: f"not streamed: outside the live equity budget ({budget})"
                    for t in ordered[max(budget, 0):]}
    return admitted, not_admitted


def _publish_equity_symbols() -> None:
    """Re-rank and hand the daemon the list (written only when it changed)."""
    global _equity_last_written, _equity_not_admitted
    with _equity_lock:
        admitted, not_admitted = rank_equity_symbols(_active_ticker, _equity_demand)
        _equity_not_admitted = not_admitted
        if sorted(admitted) == _equity_last_written:
            return
        _equity_last_written = sorted(admitted)
    write_equity_symbols_signal(admitted)


def declare_equity_symbols(kind: str, symbols: "list[str]") -> "dict[str, str]":
    """A screen's set of symbols whose live price it shows (`kind` = watchlist | board).
    Returns the symbols left unstreamed, with the reason."""
    if kind not in _equity_demand:
        raise ValueError(f"unknown equity demand kind {kind!r}")
    with _equity_lock:
        _equity_demand[kind] = [t for t in (ticker_storage_key(s or "") for s in symbols or []) if t]
    _publish_equity_symbols()
    return get_equity_symbols_not_admitted()


def viewed_equity_symbols() -> "list[str]":
    """What the operator is looking at right now: the active ticker, then the watchlist in
    its own order (no gamma board) -- the one roster for "warm what is being viewed"."""
    with _equity_lock:
        admitted, _ = rank_equity_symbols(_active_ticker, {"watchlist": list(_equity_demand["watchlist"])})
    return admitted


def get_equity_symbols_not_admitted() -> "dict[str, str]":
    with _equity_lock:
        return dict(_equity_not_admitted)


def set_streaming_active_ticker(ticker: str) -> bool:
    """Make `ticker` the active symbol: the daemon adds its NASDAQ_BOOK/NYSE_BOOK depth
    (stream_active_ticker.json) and, when it is outside the daemon's roster, its
    LEVELONE_EQUITIES stream (stream_equity_symbols.json, ranked first)."""
    global _active_ticker, _last_subscribe_completed_ts, _streaming_last_update_ts
    t = ticker_storage_key(ticker)
    if not t:
        return False
    old = [_active_ticker] if _active_ticker else []
    if _active_ticker == t:
        _ensure_default_option_contract_for_ticker(t)
        return True
    _log_stream("STREAM_RESUBSCRIBE_START", old=old, new=[t])
    forget_unsubscribed_symbols(old, [t])
    write_active_ticker_signal(t)
    _active_ticker = t
    _publish_equity_symbols()
    _last_subscribe_completed_ts = time.time()
    _streaming_last_update_ts = None
    log.info("Live-plane feed active ticker -> %s", t)
    _log_stream("STREAM_RESUBSCRIBE_DONE", ticker=t)
    _ensure_default_option_contract_for_ticker(t)
    return True


#: Monotonic generation for option-contract subscription COMMANDS (PR214 premerge
#: gap 2). Every command takes a number the moment it is admitted; only a command whose
#: number is still the highest may WRITE desired state. This is the one authority that
#: orders the two things a command mutates together -- the signal file the daemon reads
#: and `_active_option_contract` -- so ordering never depends on HTTP arrival or
#: completion order, and never on the browser choosing to ignore a stale response.
#: Guarded by a lock because the endpoint runs its body on a thread-pool executor, so
#: two commands really can interleave inside this module.
_option_command_seq: int = 0
_option_command_lock = threading.Lock()


class StaleOptionCommandError(RuntimeError):
    """A superseded subscription command tried to write desired state after a newer one
    already did. Raised instead of silently returning, so the caller reports the command
    as superseded rather than as the successful current authority."""


def begin_option_contract_command() -> int:
    """Admit a subscription command and return its generation. Callers pass this back to
    set_active_option_contract so a delayed command cannot overwrite a newer one."""
    global _option_command_seq
    with _option_command_lock:
        _option_command_seq += 1
        return _option_command_seq


def set_active_option_contract(contract_symbol: str,
                               command_generation: Optional[int] = None) -> bool:
    """Request LEVELONE_OPTIONS+OPTIONS_BOOK for this ONE option contract and begin
    replaying its rows. `contract_symbol` MUST already be a chain response's own "symbol"
    field (see stream_spine.ACTIVE_OPTION_CONTRACT_SIGNAL_DEFAULT) — never constructed
    here. A separate slot from the equity active ticker: the daemon adds its own
    subscription on its own poll cadence (stream_active_option_contract.json).

    PR214 premerge gap 2: `command_generation` (from begin_option_contract_command)
    mechanically orders competing commands. A request for A that was admitted BEFORE a
    request for B, but reaches this writer AFTER it, is superseded and refused --
    otherwise the delayed A would write the signal file and `_active_option_contract`
    back to A, leaving the daemon subscribed to the contract the operator already moved
    off. The browser-side token cannot prevent that: it only stops a stale RESPONSE from
    repainting, never a stale WRITE from landing. Omitting the generation preserves the
    historical single-caller behavior for internal/test callers."""
    global _active_option_contract, _option_last_subscribe_completed_ts, _option_streaming_last_update_ts
    t = ticker_storage_key(contract_symbol)
    if not t:
        return False
    # The staleness check and the two writes it guards happen under ONE lock: checking
    # outside it would leave the same race one layer down.
    with _option_command_lock:
        if command_generation is not None and command_generation < _option_command_seq:
            _log_stream("OPTION_CONTRACT_COMMAND_SUPERSEDED",
                        contract=t, generation=command_generation,
                        newest=_option_command_seq)
            raise StaleOptionCommandError(
                f"subscription command for {t} (generation {command_generation}) was "
                f"superseded by a newer command (generation {_option_command_seq}); "
                f"refusing to overwrite newer desired state")
        if _active_option_contract == t:
            return True
        old = _active_option_contract
        _log_stream("OPTION_CONTRACT_RESUBSCRIBE_START", old=old, new=t)
        # Independent-review finding (2026-09-12), mirror case: a symbol the primary slot
        # is switching AWAY from must not be cleared if it is STILL desired in the
        # ADDITIONAL set (_active_option_contracts) -- clear_symbol wipes the one shared
        # per-symbol live store regardless of which slot(s) name it, so clearing it here
        # would erase state the additional-contracts subscription still depends on.
        if old and old not in _active_option_contracts:
            clear_symbol(old)
        write_active_option_contract_signal(t)
        _active_option_contract = t
        _option_last_subscribe_completed_ts = time.time()
        _option_streaming_last_update_ts = None
        log.info("Live-plane feed active option contract -> %s", t)
        _log_stream("OPTION_CONTRACT_RESUBSCRIBE_DONE", contract=t)
        return True


#: The ADDITIONAL option contracts to stream beside the one primary/pinned
#: `_active_option_contract` (RC-UI-3, 2026-09-12 multi-contract coverage --
#: operator-authorized: "historical coverage failures establish properties to preserve;
#: they do not establish that single-contract operation must survive"). A separate slot,
#: mirroring `_active_option_contract` exactly, so the daemon's plural desired-state
#: signal (stream_spine.write_active_option_contracts_signal) has a server-side writer
#: symmetric to the existing singular one.
_active_option_contracts: "list[str]" = []
#: {symbol: reason} for every contract the last plural request asked for that was not
#: admitted to the stream (outside the budget, or no spot to rank it by).
_option_contracts_not_admitted: "dict[str, str]" = {}


def _contract_ranking_inputs(symbols: "list[str]") -> "dict[str, dict]":
    """{symbol: {expirationDate, strikePrice, spot}} for every requested symbol found in a
    Schwab chain the console currently holds (the terrain cache's raw REST contracts).
    expirationDate and strikePrice are that contract's own fields; spot is resolve_spot of
    the ticker whose chain holds the contract (streamed LAST_PRICE, or None). A symbol in
    no held chain is absent, and rank_option_contracts reports it as not admitted."""
    import server as _srv

    wanted = set(symbols)
    out: "dict[str, dict]" = {}
    with _srv._terrain_cache_lock:
        chains = [(tk, list(payload.get("_contracts_rest") or []))
                  for tk, payload in _srv._terrain_cache.items()]
    spot_by_ticker: "dict[str, float | None]" = {}
    for tk, contracts in chains:
        for ct in contracts:
            sym = ticker_storage_key(ct.get("symbol")) if isinstance(ct, dict) else None
            if not sym or sym not in wanted or sym in out:
                continue
            if tk not in spot_by_ticker:
                spot_by_ticker[tk] = _srv.resolve_spot(tk)[0]
            out[sym] = {"expirationDate": ct.get("expirationDate"),
                        "strikePrice": ct.get("strikePrice"),
                        "spot": spot_by_ticker[tk]}
    return out


def get_option_contracts_over_budget() -> "list[str]":
    """Contracts the last plural request asked for that were not admitted to the stream."""
    return sorted(_option_contracts_not_admitted)


def get_option_contracts_not_admitted() -> "dict[str, str]":
    """{symbol: reason} for the last plural request's contracts that were not admitted."""
    return dict(_option_contracts_not_admitted)


def get_option_contracts_budget_state() -> dict:
    """What the last plural request was admitted to, against the shared-socket budget."""
    return {"admitted_count": len(_active_option_contracts),
            "over_budget_count": len(_option_contracts_not_admitted),
            "budget": OPTION_CONTRACTS_MAX_HELD}

#: Serializes the swap of the additional-contracts set (the plural signal write).
_option_contracts_command_lock = threading.Lock()
#: The last request that was ranked in full, and the set that rank admitted (see
#: set_active_option_contracts: identical demand keeps the held set, no re-rank).
_option_contracts_last_request: "list[str] | None" = None
_option_contracts_last_admitted: "list[str]" = []
_OVER_BUDGET_REASON_PREFIX = "not admitted: outside the live-stream budget"

#: Per-view demand (2026-09-24). Every page that shows option contracts (the heatmap, Strike
#: Detail, in any number of tabs) declares ITS OWN set under its own client id; the stream
#: carries the union of every live declaration, ranked to the budget. MEASURED 2026-09-24:
#: this used to be one last-writer-wins slot, so two views (a 0DTE ladder and the
#: all-expiry grid) replaced each other's set on every render and the daemon swapped ~200
#: contracts on the shared Schwab socket every few seconds until the socket died.
#: A declaration is a lease: a live view re-declares every 30 s (DEMAND_REFRESH_MS in
#: static/js/ed-stream.js), and one not refreshed within OPTION_DEMAND_LEASE_SEC -- a closed
#: or crashed tab -- stops counting at the next declaration from any view.
OPTION_DEMAND_LEASE_SEC = 90.0
_option_demand_by_client: "dict[str, dict]" = {}
_option_demand_lock = threading.Lock()


def declare_option_contract_demand(client_id: str, contract_symbols: "list[str]", *,
                                   seq: int, now: "float | None" = None) -> dict:
    """Record one view's demand and stream the union of every live view's demand.

    `seq` orders ONE client's declarations (a late, older request from the same view never
    overwrites a newer one: StaleOptionCommandError). Different clients never supersede each
    other -- that was the defect. Returns this client's accepted demand (`requested`, the
    set the view can confirm against) and how many views are counted."""
    cid = str(client_id or "").strip()
    if not cid:
        raise ValueError("client_id is required: demand is declared per view")
    t = time.time() if now is None else float(now)
    requested = sorted({ticker_storage_key(s) for s in (contract_symbols or [])  # caps-ok: a view declaring no contracts is an empty declaration, which releases its demand
                        if ticker_storage_key(s)})
    with _option_demand_lock:
        prior = _option_demand_by_client.get(cid)
        if prior is not None and seq <= prior["seq"]:
            raise StaleOptionCommandError(
                f"demand {requested} from view {cid} (seq {seq}) was superseded by that "
                f"view's newer declaration (seq {prior['seq']})")
        _option_demand_by_client[cid] = {"symbols": requested, "seq": seq, "ts": t}
        for other in [k for k, v in _option_demand_by_client.items()
                      if t - v["ts"] > OPTION_DEMAND_LEASE_SEC]:
            del _option_demand_by_client[other]
        live = [v["symbols"] for v in _option_demand_by_client.values() if v["symbols"]]
        union = sorted(set().union(*live)) if live else []
        set_active_option_contracts(union)
    return {"requested": requested, "demand_views": len(live)}


def get_active_option_contracts() -> "list[str]":
    """The DESIRED additional option-contract symbols (this daemon's own plural signal),
    beside the one primary contract get_active_option_contract reports. Same
    requested/desired-state caveat as get_active_option_contract."""
    return list(_active_option_contracts)


def set_active_option_contracts(contract_symbols: "list[str]") -> bool:
    """Request LEVELONE_OPTIONS+OPTIONS_BOOK for these ADDITIONAL option contracts,
    beside the one primary contract set_active_option_contract manages. Symbols MUST
    already be chain-response "symbol" fields, same requirement as
    set_active_option_contract -- never constructed here.

    The ONE caller in production is declare_option_contract_demand, which passes the union
    of every live view's demand under its own lock; ordering is per view there (`seq`)."""
    global _active_option_contracts, _option_contracts_not_admitted
    global _option_contracts_last_request, _option_contracts_last_admitted
    requested = sorted({ticker_storage_key(s) for s in (contract_symbols or [])  # caps-ok: no symbols requested is an empty request, which clears the set
                        if ticker_storage_key(s)})
    # The same demand as last time keeps the set already held. MEASURED 2026-09-24: every
    # re-post of an unchanged heatmap re-ranked against the newest streamed spot, the
    # 200-contract cutoff slid by a strike, and the daemon unsubscribed/resubscribed on the
    # shared Schwab socket for nothing (3,676 SPY option subscriptions in 5 minutes, median
    # life 5 s; the socket died 8 times that session). A new rank happens only when the
    # demand changes, or when the last rank could not place every contract (an input such as
    # spot was missing then and may be present now).
    if (requested == _option_contracts_last_request
            and list(_active_option_contracts) == _option_contracts_last_admitted):
        return True
    # The shared Schwab socket's budget (stream_spine.OPTION_CONTRACTS_MAX_HELD, measured):
    # publish only what the daemon may hold, ranked on canonical Schwab fields (the chain
    # contract's expirationDate, then |strikePrice - streamed LAST_PRICE|), and remember
    # what was left out and why. Any input missing: not admitted, never a guess.
    admitted, not_admitted = rank_option_contracts(requested, _contract_ranking_inputs(requested))
    symbols = sorted(admitted)
    _option_contracts_not_admitted = not_admitted
    with _option_contracts_command_lock:
        # Remember this rank as final only when every contract was placed (admitted, or
        # left out by the budget alone); a contract missing an input is re-ranked next time.
        placed = all(r.startswith(_OVER_BUDGET_REASON_PREFIX) for r in not_admitted.values())
        _option_contracts_last_request = requested if placed else None
        _option_contracts_last_admitted = symbols
        old = _active_option_contracts
        if set(old) == set(symbols):
            return True
        _log_stream("OPTION_CONTRACTS_RESUBSCRIBE_START", old=old, new=symbols)
        # Only a symbol actually being DROPPED needs its replay cursors forgotten -- one
        # still (or newly) requested keeps replaying without a spurious reset. Independent-
        # review finding (2026-09-12): a symbol dropped from the ADDITIONAL set that is
        # STILL the primary/pinned contract (_active_option_contract) must not be cleared
        # either -- clear_symbol wipes the one shared per-symbol live store (cursors,
        # streamed greeks, book state) regardless of which slot(s) named it, so clearing it
        # here would erase state the primary subscription is still actively depending on.
        for s in old:
            if s not in symbols and s != _active_option_contract:
                clear_symbol(s)
                _option_contract_last_update_ts.pop(s, None)
        write_active_option_contracts_signal(symbols)
        _active_option_contracts = symbols
        log.info("Live-plane feed additional option contracts -> %s", symbols)
        _log_stream("OPTION_CONTRACTS_RESUBSCRIBE_DONE", contracts=symbols)
        return True


def get_option_contract_book_microstructure(contract_symbol: str) -> dict:
    """The order-flow SEMANTIC PRODUCT for one option contract: book + PROXY flow.

    Assembled by ``app.options.order_flow.live_payload.options_live_payload``, which calls
    ``OrderFlowEngine.compute`` once (that function already produces
    ``book_microstructure``). No second book walk.
    """
    from app.options.order_flow.live_payload import options_live_payload

    t = ticker_storage_key(contract_symbol)
    return options_live_payload(t)


def _option_streaming_healthy(*, for_contract: Optional[str] = None) -> bool:
    """RC-UI-3 finding #4 (2026-09-12), REPRODUCED: the top-line guard below used to
    unconditionally require `_active_option_contract` (the PRIMARY slot) to be set,
    even when the caller was asking about an ADDITIONAL-only contract with genuinely
    fresh, confirmed coverage -- with no primary requested, this returned False no
    matter how healthy the additional contract's own feed was, and
    get_option_contract_streaming_diagnostics never overrode that False back to True
    (it only ever forced healthy -> False on a mismatch, never healthy -> True on a
    match). Passing `for_contract` answers health for THAT contract alone, from its
    own PER-CONTRACT last-update timestamp -- not the single global clock every
    contract's rows all update together (see _option_contract_last_update_ts), so one
    contract's freshness can never mask or borrow another's. `for_contract=None`
    keeps the historical whole-plane (primary-gated) answer for back-compat callers
    that do not name a specific contract."""
    if not _feed_running:
        return False
    now = time.time()
    if for_contract is not None:
        key = ticker_storage_key(for_contract)
        if not key:
            return False
        last = _option_contract_last_update_ts.get(key)
        if last is not None:
            return (now - last) * 1000.0 <= STREAMING_STALE_MS
        is_requested = key == _active_option_contract or key in _active_option_contracts
        return bool(
            is_requested and _option_last_subscribe_completed_ts is not None
            and (now - _option_last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC)
    if not _active_option_contract:
        return False
    if _option_streaming_last_update_ts is not None:
        return (now - _option_streaming_last_update_ts) * 1000.0 <= STREAMING_STALE_MS
    if (_option_last_subscribe_completed_ts is not None
            and (now - _option_last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC):
        return True
    return False


#: The two Schwab option services whose durable open coverage epochs constitute
#: PRODUCER-side subscription identity (as opposed to the server's desired state).
OPTION_PRODUCER_SERVICES: tuple[str, ...] = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")


def _read_producer_option_contracts() -> dict[str, list[str]]:
    """Currently open coverage SYMBOLS per option service, from the canonical stream DB
    (RC-UI-3, 2026-09-12: a service can now durably hold more than one concurrently-open
    contract, so this is a list, not a single symbol-or-None). Fails closed to an empty
    list per service on any read problem: an unreadable ledger is 'unknown', and unknown
    must never be treated as producer confirmation."""
    con = _open_capture_db_readonly()
    if con is None:
        return {s: [] for s in OPTION_PRODUCER_SERVICES}
    try:
        # An open coverage row confirms only while the LIVE producer still claims that
        # epoch: a failed durable close leaves the row open on a subscription the daemon
        # has already surrendered. Same TTL the DB-identity check already uses — the
        # producer's liveness and its claim are one signal, not a second knob.
        return read_open_coverage_symbols(
            con, OPTION_PRODUCER_SERVICES,
            stale_sec=STREAM_PRODUCER_HEARTBEAT_STALE_SEC)
    except Exception:   # noqa: BLE001 — diagnostics must never raise into a route
        return {s: [] for s in OPTION_PRODUCER_SERVICES}
    finally:
        con.close()


def read_producer_admitted_option_contracts() -> "dict[str, list[str]]":
    """Public wrapper for `_read_producer_option_contracts` (2026-09-16, independent-review
    follow-up: server.py needs the PRODUCER-confirmed admitted set by name, not the
    underscore-private one, to distinguish 'admitted' from merely 'desired' when disclosing
    per-contract subscription state). See that function's own docstring — this is the exact
    same read, exposed under a name a consumer outside this module is meant to call."""
    return _read_producer_option_contracts()


def is_option_producer_daemon_available() -> bool:
    """True only when a FRESH producer heartbeat is confirmed on THIS process's own
    resolved stream-db connection (2026-09-16, independent-review follow-up: 'daemon-
    unavailable' must be its own disclosed state, distinct from 'requested but not yet
    processed' -- a contract that will never admit because the daemon itself is down reads
    very differently from one that is merely queued behind a live daemon's own poll cycle).

    Delegates to `_stream_db_identity_status`'s own `identity_match` — True only for a
    heartbeat visible AND fresh on this exact connection; both False (stale) and None
    (absent/unknown, including a cold-start or cross-checkout mismatch) report unavailable
    here, fail-closed: an indefinite unknown must never be disclosed as 'the daemon is
    fine, just busy'."""
    return _stream_db_identity_status().get("identity_match") is True


def read_producer_rejected_option_contracts() -> "dict[str, str]":
    """{symbol: vendor_error} for every additional option contract the capture daemon's
    most recent batched subscribe attempt had the vendor explicitly REFUSE (2026-09-16,
    bounded-vendor-call reconciliation — see capture.py's
    _batch_subscribe_with_bisection). Fails closed to {} on any read problem or a stale/
    absent producer heartbeat, same TTL and same DB-identity discipline as
    _read_producer_option_contracts: unknown is never 'not rejected'."""
    con = _open_capture_db_readonly()
    if con is None:
        return {}
    try:
        return read_rejected_option_contracts(con, stale_sec=STREAM_PRODUCER_HEARTBEAT_STALE_SEC)
    except Exception:   # noqa: BLE001 — diagnostics must never raise into a route
        return {}
    finally:
        con.close()


def _pick_producer_contract(symbols: "list[str]", queried: Optional[str]) -> Optional[str]:
    """Reduce a service's list of currently-confirmed producer symbols to the single
    value the back-compat `producer_l1_contract`/`producer_book_contract` diagnostic
    fields report (RC-UI-3: those fields predate multi-contract coverage and every
    existing caller — the JS binding-status renderers, the order-flow subscription
    panel — still expects a single symbol or None). Prefers the QUERIED contract when it
    is among the confirmed symbols, since that is the subject the caller actually asked
    about; otherwise falls back to the first (the list is already sorted, so this is
    deterministic) so a caller not asking about a specific contract still sees SOME live
    evidence instead of a fabricated absence. Single-contract operation is unaffected:
    with at most one symbol ever confirmed, this always returns exactly that symbol or
    None, identical to the pre-RC-UI-3 scalar behavior."""
    if not symbols:
        return None
    if queried is not None and queried in symbols:
        return queried
    return symbols[0]


def get_option_contract_streaming_diagnostics(
    for_contract: Optional[str] = None,
) -> dict[str, Any]:
    """FRESHNESS/HEALTH for the option-contract feed — the SAME shape as
    get_streaming_diagnostics(), mirrored for the separate option-contract slot. Answers
    "is the daemon actually subscribed and receiving data for this contract", distinct
    from get_option_contract_book_microstructure's book-CONTENT-level ages/status (which
    answer "how stale is the replayed book itself"). Both distinctions matter: a feed can
    be streaming_healthy=True with status='no_book' (subscribed, market simply has not
    sent a book frame yet) as legitimately as it can be streaming_healthy=False with a
    perfectly fresh cached book (the feed died after its last good frame).

    CONTRACT BINDING (PR214 merge blocker 1A): `option_contract` is, and always was,
    the GLOBALLY ACTIVE contract — but this health was being attached verbatim to a
    payload computed for a DIFFERENT, caller-queried contract, so a response could
    read `contract: A` beside `streaming_healthy: true` that belonged entirely to B.
    Pass `for_contract` to bind the answer to the contract actually being asked
    about: the plane still truthfully reports which contract it is streaming, and
    `contract_match` states whether that is the one queried. On a mismatch the
    health FAILS CLOSED — there is no live evidence about A while the feed is bound
    to B, and absence of evidence must never render as healthy. `for_contract=None`
    (no caller-specified subject) keeps the historical whole-plane answer, with
    `contract_match` left None rather than fabricated."""
    now = time.time()
    queried = ticker_storage_key(for_contract) if for_contract else None
    # RC-UI-3 finding #4 (2026-09-12), REPRODUCED: `last`/`stale_ms` used to read ONLY the
    # single global `_option_streaming_last_update_ts`, which every contract's rows (primary
    # OR any additional one) all bump together -- so a query about a genuinely stale
    # contract could report a fresh `streaming_staleness_ms` borrowed entirely from a
    # DIFFERENT contract's own recent traffic. When a specific contract is queried, answer
    # from THAT contract's own per-contract clock instead.
    last = _option_contract_last_update_ts.get(queried) if queried else _option_streaming_last_update_ts
    stale_ms: Optional[float]
    if last is not None:
        stale_ms = max(0.0, (now - last) * 1000.0)
    elif (_option_last_subscribe_completed_ts is not None
          and (now - _option_last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC):
        stale_ms = 0.0
    else:
        stale_ms = None

    db_identity = _stream_db_identity_status()
    healthy = _option_streaming_healthy(for_contract=queried) if queried else _option_streaming_healthy()
    if _identity_forces_unhealthy(db_identity, _option_last_subscribe_completed_ts, now):
        healthy = False   # fail closed — see get_streaming_diagnostics' identical guard

    # Contract binding: compare on the SAME canonical key set_active_option_contract
    # stores (ticker_storage_key), so a caller passing the raw chain "symbol" string
    # reconciles correctly rather than mismatching on whitespace/case alone.
    #
    # PR214 premerge gap 1A: `_active_option_contract` is only DESIRED/REQUESTED state
    # (the server wrote the signal file). It is NOT proof the daemon has completed the
    # LEVELONE_OPTIONS / OPTIONS_BOOK subscriptions -- between the request for B and the
    # daemon's next poll, the producer still physically holds A. Binding health to
    # requested state alone would green B during exactly that window. Producer truth is
    # read from the CANONICAL open coverage epochs in the same stream DB, and a full
    # contract match now requires requested AND both producer services to agree.
    producer = _read_producer_option_contracts()
    contract_match: Optional[bool] = None
    if queried:
        # Independent-review finding (2026-09-12): this used to recognize ONLY the
        # primary/pinned contract as a legitimate requested subject -- a queried contract
        # that was genuinely requested and confirmed as an ADDITIONAL contract (RC-UI-3)
        # was always rejected, because `requested_ok` never checked
        # `_active_option_contracts` at all. Fixed by recognizing either role.
        is_primary_request = (_active_option_contract == queried)
        is_extra_request = queried in _active_option_contracts
        requested_ok = is_primary_request or is_extra_request
        if is_primary_request:
            # The primary slot always requests BOTH services (the Flow view needs book
            # depth too), so a full match still requires both to confirm.
            producer_ok = (queried in producer["LEVELONE_OPTIONS"]
                           and queried in producer["OPTIONS_BOOK"])
        else:
            # An ADDITIONAL-only contract requests LEVELONE_OPTIONS alone (survivor-
            # challenge finding: the heatmap/GEX/volume consumers it serves never read
            # book depth -- see EXTRA_OPTION_CONTRACT_SVC_KEY in capture.py). Requiring
            # OPTIONS_BOOK confirmation here would fail this contract closed FOREVER,
            # since book is never subscribed for it in the first place.
            producer_ok = queried in producer["LEVELONE_OPTIONS"]
        contract_match = bool(requested_ok and producer_ok)
        if not contract_match:
            # Either the plane is bound elsewhere, or the producer has not yet confirmed
            # this contract on its required service(s). No live evidence about the queried
            # contract exists in either case -- fail closed rather than lending another
            # contract's health, or a not-yet-established subscription's, to this one.
            healthy = False
    return {
        "streaming_connected": bool(_feed_running),
        # Back-compatible name; it has always been the SERVER-REQUESTED contract.
        "option_contract": _active_option_contract,
        "server_requested_contract": _active_option_contract,
        "producer_l1_contract": _pick_producer_contract(producer["LEVELONE_OPTIONS"], queried),
        "producer_book_contract": _pick_producer_contract(producer["OPTIONS_BOOK"], queried),
        "queried_contract": queried,
        "contract_match": contract_match,
        "streaming_last_update_ts": last,
        "streaming_staleness_ms": stale_ms,
        "streaming_healthy": healthy,
        # Ground truth for the Schwab socket itself, per service — distinct from
        # streaming_healthy above (this module's local replay proxy). A fresh LEVELONE_
        # OPTIONS quote does not imply a fresh OPTIONS_BOOK if the book service has
        # stopped: the two are reported SEPARATELY, never collapsed into one flag, so a
        # consumer cannot mistake one service's freshness for the other's.
        "daemon_upstream_health": _read_daemon_upstream_health(
            ("LEVELONE_OPTIONS", "OPTIONS_BOOK")),
        "stream_db_identity": db_identity,
    }


def start_order_flow_stream(
    client: Any,
    account_id: Any,
    initial_ticker: "str | None",
    on_tick_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """`client`/`account_id` are accepted, not used: this feed opens no Schwab session
    of its own, so it has no account dependency — kept for call-site compatibility.
    `initial_ticker` may be None: the feed then runs with no active ticker until the browser
    chooses one (no built-in ticker -- universality, operator 2026-09-23)."""
    global _feed_task, _feed_running, _feed_generation, _on_tick_callback
    it = (initial_ticker or "").upper().strip()
    if _feed_task is not None and not _feed_task.done():
        log.info("Live-plane feed already running")
        return True
    _on_tick_callback = on_tick_callback
    _feed_running = True
    # A new lifecycle -- see `_feed_generation`'s module-level docstring. Bumped here
    # (never in stop_order_flow_stream) so a restart is what invalidates in-flight work
    # from before it, matching exactly the reproduced stop-then-restart-before-drain gap.
    _feed_generation += 1
    if it:
        set_streaming_active_ticker(it)
    _feed_task = asyncio.get_event_loop().create_task(_feed_loop(), name="daemon-plane-feed")
    log.info("Live-plane feed started (initial ticker %s, source=capture daemon live push)",
             it or "none -- awaiting the browser's choice")
    return True


STREAM_THREAD_JOIN_TIMEOUT_SEC = 35.0


def stop_order_flow_stream(*, join_timeout: float = STREAM_THREAD_JOIN_TIMEOUT_SEC) -> None:
    global _feed_running, _feed_task, _streaming_last_update_ts, _active_ticker
    global _active_option_contract, _option_streaming_last_update_ts
    _log_stream("STREAM_THREAD_JOIN_START", join_timeout_sec=join_timeout)
    _feed_running = False
    _streaming_last_update_ts = None
    _active_ticker = None
    _active_option_contract = None
    _option_streaming_last_update_ts = None
    _option_contract_last_update_ts.clear()
    clear_all_live_state()
    task = _feed_task
    if task is not None and not task.done():
        task.cancel()
    _feed_task = None
    _log_stream("STREAM_THREAD_JOIN_DONE")


def get_stream_thread() -> None:
    """No dedicated OS thread exists — the feed is one asyncio task on the server's own
    event loop. Kept for import compatibility; nothing external reads a live value."""
    return None
