"""
Live-plane feed for the single active UI ticker — READ-ONLY consumer of the canonical
capture daemon (tools/run_stream_capture.py), never a second Schwab session.

SINGLE-STREAM-AUTHORITY LAW (root-fixed here): this module used to own its own
`schwab.streaming.StreamClient`, logging into Schwab independently of the canonical
capture daemon — two authenticated sockets on one account, racing each other for the
same market truth. It now opens ZERO Schwab connections. The daemon is the one producer;
this module polls `stream_capture.db` (read-only) for the rows the daemon already wrote,
and replays them into the same in-process planes (`order_flow_live_state`,
`live_market_plane`) the old socket handlers fed — so every downstream consumer
(`/api/fast-quote`, streaming diagnostics, the active-ticker switch endpoint) needs no
changes and cannot tell the difference except by dropped/added latency.

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

from instrument_identity import ticker_storage_key
from stream_spine import (
    PRODUCER_CLAIM_TTL_SEC,
    STREAM_DB_DEFAULT,
    read_open_coverage_symbols,
    read_producer_heartbeat,
    resolve_stream_db_path,
    write_active_option_contract_signal,
    write_active_ticker_signal,
)

from order_flow_live_state import (
    clear_all_live_state,
    clear_symbol,
    forget_unsubscribed_symbols,
    get_content_for_symbol,
    push_book,
    push_level_one,
)
from order_flow_engine import compute_book_microstructure

import live_market_plane as _lmp

log = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 0.5   # daemon commits every batch_sec=0.25s; sub-second feed latency

# ── Runtime state (single asyncio task inside the SAME event loop as the server —
#    no dedicated thread/loop needed once nothing here opens a socket) ──
_feed_task: Optional[asyncio.Task] = None
_feed_running = False
_active_ticker: Optional[str] = None
_streaming_last_update_ts: Optional[float] = None
_last_subscribe_completed_ts: Optional[float] = None
#: Per-symbol read cursor (ts_recv of the newest row already replayed) so a poll tick
#: reads only NEW rows — never replays history, never misses a row between polls.
_l1_cursor: dict[str, float] = {}
_book_cursor: dict[str, float] = {}

#: The one option CONTRACT (OSI symbol) whose LEVELONE_OPTIONS/OPTIONS_BOOK rows this feed
#: replays — a SEPARATE slot from _active_ticker (an equity ticker and an option contract
#: on that same underlying can be watched at once; they are different symbol identities in
#: every table and signal file).
_active_option_contract: Optional[str] = None
_option_l1_cursor: dict[str, float] = {}
_option_book_cursor: dict[str, float] = {}
#: Own staleness clock, separate from the equity ticker's — an option contract watched
#: alongside a ticker must be able to go stale (or come up fresh) independently.
_option_streaming_last_update_ts: Optional[float] = None
_option_last_subscribe_completed_ts: Optional[float] = None

_on_tick_callback: Optional[Callable[[str], None]] = None

STREAMING_STALE_MS = 25_000.0
GRACE_AFTER_SUBSCRIBE_SEC = 8.0

#: FRESHNESS/HEALTH SEMANTIC AUDIT (OPTIONS_ORDER_FLOW_V1, 2026-08-30): this module's own
#: streaming_connected/streaming_healthy answer ONE question — "is my local read-only DB-
#: poll task alive, and did a row land in stream_capture.db recently" — which is a PROXY
#: for daemon health, not the daemon's Schwab-socket truth itself. A stale row sitting in
#: the DB could let this proxy read "healthy" while the daemon's actual upstream Schwab
#: connection for that exact service has gone dark; the reverse is also possible right
#: after a fresh daemon (re)connect, before this module's poll has caught up. The daemon
#: itself already computes the REAL truth per Schwab service (stream_spine.HealthRegistry,
#: fed by health.beat() calls inside the actual message handlers in tools/
#: run_stream_capture.py) and writes it to STATUS_PATH every ~10s — but nothing ever read
#: it back into the UI-facing diagnostics until now. "local DB poll task exists" must never
#: masquerade as "Schwab stream connected" — _read_daemon_upstream_health is the ground
#: truth for that distinct question, surfaced as its own field, never blended into
#: streaming_healthy.
_DAEMON_STATUS_PATH = Path(__file__).resolve().parent / "reports" / "stream_capture_status.json"
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
    """
    rest_only | streaming | rest_fallback_explicit | rest_mismatch
    """
    t = ticker_storage_key(ticker)
    if not _feed_running:
        return "rest_only"
    if not _active_ticker or _active_ticker.upper() != t:
        return "rest_mismatch"
    if _streaming_healthy():
        return "streaming"
    return "rest_fallback_explicit"


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
        # module's own local DB-poll replay is alive and recently updated.
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
    canonical resolver `tools/run_stream_capture.py`'s CaptureWriter also uses, with
    THIS module's own `STREAM_DB_DEFAULT` (still test-monkeypatchable, unchanged) as
    the fallback when no STREAM_CAPTURE_DB_PATH override is set."""
    if db_path is None:
        db_path = resolve_stream_db_path(STREAM_DB_DEFAULT)
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None   # daemon has not created the DB yet (cold start) — retry next tick


def _replay_new_rows(con: sqlite3.Connection, ticker: str) -> None:
    """One poll tick: read rows newer than the cursor for `ticker`, replay them through
    the SAME plane-ingest functions the old direct-socket handlers called."""
    global _streaming_last_update_ts

    l1_since = _l1_cursor.get(ticker, 0.0)
    rows = con.execute(
        "SELECT ts_recv, native_json FROM stream_quotes_raw "
        "WHERE symbol = ? AND ts_recv > ? AND native_json IS NOT NULL "
        "ORDER BY ts_recv", (ticker, l1_since)).fetchall()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        push_level_one(ticker, item, ts_recv=ts_recv)
        try:
            _lmp.record_from_level_one_equity(ticker, item)
        except Exception as e:
            log.debug("live_market_plane ingest: %s", e)
        _streaming_last_update_ts = time.time()
        if _on_tick_callback:
            try:
                _on_tick_callback(ticker)
            except Exception as e:
                log.debug("Tick callback: %s", e)
        _l1_cursor[ticker] = ts_recv

    book_since = _book_cursor.get(ticker, 0.0)
    rows = con.execute(
        "SELECT ts_recv, native_json FROM stream_book_raw "
        "WHERE symbol = ? AND ts_recv > ? ORDER BY ts_recv", (ticker, book_since)).fetchall()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        push_book(ticker, item)
        _book_cursor[ticker] = ts_recv


def _replay_option_contract_rows(con: sqlite3.Connection, contract_symbol: str) -> None:
    """Same replay shape as _replay_new_rows, for the one option CONTRACT this feed is
    tracking. LEVELONE_OPTIONS rows read via push_level_one and OPTIONS_BOOK rows via
    push_book — order_flow_live_state's functions are symbol-generic (they read Schwab's
    native field names, not an equity-specific schema) and the captured field shapes
    (reports/of_capability_probe/options_20260820T1354Z/) carry every field either reads:
    BID_PRICE/ASK_PRICE/LAST_PRICE/LAST_SIZE/TOTAL_VOLUME/TRADE_TIME_MILLIS for L1;
    BIDS/ASKS/BOOK_TIME for book. No new plane, no new ingest function — the SAME producer
    order_flow_live_state already is, called with a different symbol."""
    global _option_streaming_last_update_ts
    l1_since = _option_l1_cursor.get(contract_symbol, 0.0)
    rows = con.execute(
        "SELECT ts_recv, native_json FROM stream_options_quotes_raw "
        "WHERE symbol = ? AND ts_recv > ? ORDER BY ts_recv",
        (contract_symbol, l1_since)).fetchall()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        push_level_one(contract_symbol, item, ts_recv=ts_recv)
        _option_streaming_last_update_ts = time.time()
        _option_l1_cursor[contract_symbol] = ts_recv

    book_since = _option_book_cursor.get(contract_symbol, 0.0)
    rows = con.execute(
        "SELECT ts_recv, native_json FROM stream_book_raw "
        "WHERE symbol = ? AND service = 'OPTIONS_BOOK' AND ts_recv > ? ORDER BY ts_recv",
        (contract_symbol, book_since)).fetchall()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        push_book(contract_symbol, item)
        _option_book_cursor[contract_symbol] = ts_recv


async def _feed_loop() -> None:
    """A sqlite3.Connection is THREAD-AFFINE (check_same_thread=True by default) — it may
    only be touched from the OS thread that created it. This loop opens ONE read-only
    connection and reuses it across every poll tick's two replay calls, but the default
    executor `asyncio.to_thread` schedules onto (min(32, cpu_count+4) worker threads with
    no affinity guarantee between calls — a real defect, not a test artifact: measured via
    a genuinely flaky integration test ("SQLite objects created in a thread can only be
    used in that same thread") that reproduced under real cross-call thread reuse, not a
    synthetic shortcut. Fixed at the root: every DB touch in this loop's lifetime — open
    AND both replay calls — runs on a DEDICATED single-worker executor, so `con` never
    crosses threads. The executor is scoped to this loop's own lifetime, not module-level,
    so a start/stop/restart cycle never risks a stale worker thread from a prior run."""
    global _feed_running
    con: Optional[sqlite3.Connection] = None
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="daemon-plane-feed-db")
    loop = asyncio.get_event_loop()
    try:
        while _feed_running:
            if con is None:
                con = await loop.run_in_executor(executor, _open_capture_db_readonly)
            tkr = _active_ticker
            contract = _active_option_contract
            if con is not None and (tkr or contract):
                try:
                    if tkr:
                        await loop.run_in_executor(executor, _replay_new_rows, con, tkr)
                    if contract:
                        await loop.run_in_executor(
                            executor, _replay_option_contract_rows, con, contract)
                except sqlite3.Error as e:
                    log.warning("daemon plane feed: db read failed, reopening: %s", e)
                    try:
                        await loop.run_in_executor(executor, con.close)
                    except sqlite3.Error:
                        pass
                    con = None
            await asyncio.sleep(POLL_INTERVAL_SEC)
    finally:
        if con is not None:
            try:
                await loop.run_in_executor(executor, con.close)
            except sqlite3.Error:
                pass
        executor.shutdown(wait=False)
        _log_stream("FEED_LOOP_STOP_DONE")


def set_streaming_active_ticker(ticker: str) -> bool:
    """Request book depth + begin replaying L1 for this symbol. The daemon adds/drops
    its own NASDAQ_BOOK/NYSE_BOOK subscription for `ticker` on its own poll cadence
    (stream_active_ticker.json) — L1 replay here starts immediately since the daemon
    already captures LEVELONE_EQUITIES for its whole roster."""
    global _active_ticker, _last_subscribe_completed_ts, _streaming_last_update_ts
    t = ticker_storage_key(ticker)
    if not t:
        return False
    old = [_active_ticker] if _active_ticker else []
    if _active_ticker == t:
        return True
    _log_stream("STREAM_RESUBSCRIBE_START", old=old, new=[t])
    forget_unsubscribed_symbols(old, [t])
    write_active_ticker_signal(t)
    _active_ticker = t
    _last_subscribe_completed_ts = time.time()
    _streaming_last_update_ts = None
    log.info("Live-plane feed active ticker -> %s", t)
    _log_stream("STREAM_RESUBSCRIBE_DONE", ticker=t)
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
        if old:
            clear_symbol(old)
        write_active_option_contract_signal(t)
        _active_option_contract = t
        _option_last_subscribe_completed_ts = time.time()
        _option_streaming_last_update_ts = None
        log.info("Live-plane feed active option contract -> %s", t)
        _log_stream("OPTION_CONTRACT_RESUBSCRIBE_DONE", contract=t)
        return True


def get_option_contract_book_microstructure(contract_symbol: str) -> dict:
    """The order-flow SEMANTIC PRODUCT for one option contract's live book: reuses
    order_flow_engine.compute_book_microstructure — the SAME one producer the equity
    `/api/order-flow/microstructure` route reads — called with this contract's own
    replayed content, never a second book-imbalance computation. Fail-closed by that
    producer's own contract: no book snapshot yet -> status 'no_book', no fabricated
    metric. This function does not gate on _active_option_contract being set to
    `contract_symbol` — a caller may query content already replayed even if the daemon
    has since moved on, exactly as the equity route does not gate on the ticker being
    'the' active one."""
    t = ticker_storage_key(contract_symbol)
    content = get_content_for_symbol(t) if t else []
    return compute_book_microstructure({"content": content}, ticker=t)


def _option_streaming_healthy() -> bool:
    if not (_feed_running and _active_option_contract):
        return False
    now = time.time()
    if _option_streaming_last_update_ts is not None:
        return (now - _option_streaming_last_update_ts) * 1000.0 <= STREAMING_STALE_MS
    if (_option_last_subscribe_completed_ts is not None
            and (now - _option_last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC):
        return True
    return False


#: The two Schwab option services whose durable open coverage epochs constitute
#: PRODUCER-side subscription identity (as opposed to the server's desired state).
OPTION_PRODUCER_SERVICES: tuple[str, ...] = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")


def _read_producer_option_contracts() -> dict[str, Optional[str]]:
    """Current open coverage symbol per option service, from the canonical stream DB.
    Fails closed to None per service on any read problem: an unreadable ledger is
    'unknown', and unknown must never be treated as producer confirmation."""
    con = _open_capture_db_readonly()
    if con is None:
        return {s: None for s in OPTION_PRODUCER_SERVICES}
    try:
        # An open coverage row confirms only while the LIVE producer still claims that
        # epoch: a failed durable close leaves the row open on a subscription the daemon
        # has already surrendered. Same TTL the DB-identity check already uses — the
        # producer's liveness and its claim are one signal, not a second knob.
        return read_open_coverage_symbols(
            con, OPTION_PRODUCER_SERVICES,
            stale_sec=STREAM_PRODUCER_HEARTBEAT_STALE_SEC)
    except Exception:   # noqa: BLE001 — diagnostics must never raise into a route
        return {s: None for s in OPTION_PRODUCER_SERVICES}
    finally:
        con.close()


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
    last = _option_streaming_last_update_ts
    stale_ms: Optional[float]
    if last is not None:
        stale_ms = max(0.0, (now - last) * 1000.0)
    elif (_option_last_subscribe_completed_ts is not None
          and (now - _option_last_subscribe_completed_ts) < GRACE_AFTER_SUBSCRIBE_SEC):
        stale_ms = 0.0
    else:
        stale_ms = None

    db_identity = _stream_db_identity_status()
    healthy = _option_streaming_healthy()
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
    queried = ticker_storage_key(for_contract) if for_contract else None
    contract_match: Optional[bool] = None
    if queried:
        requested_ok = (_active_option_contract == queried)
        producer_ok = (producer["LEVELONE_OPTIONS"] == queried
                       and producer["OPTIONS_BOOK"] == queried)
        contract_match = bool(requested_ok and producer_ok)
        if not contract_match:
            # Either the plane is bound elsewhere, or the producer has not yet confirmed
            # this contract on both services. No live evidence about the queried contract
            # exists in either case -- fail closed rather than lending another contract's
            # health, or a not-yet-established subscription's, to this one.
            healthy = False
    return {
        "streaming_connected": bool(_feed_running),
        # Back-compatible name; it has always been the SERVER-REQUESTED contract.
        "option_contract": _active_option_contract,
        "server_requested_contract": _active_option_contract,
        "producer_l1_contract": producer["LEVELONE_OPTIONS"],
        "producer_book_contract": producer["OPTIONS_BOOK"],
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
    initial_ticker: str,
    on_tick_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """`client`/`account_id` are accepted, not used: this feed opens no Schwab session
    of its own, so it has no account dependency — kept for call-site compatibility."""
    global _feed_task, _feed_running, _on_tick_callback
    it = (initial_ticker or "").upper().strip()
    if not it:
        log.warning("Live-plane feed: no initial ticker")
        return False
    if _feed_task is not None and not _feed_task.done():
        log.info("Live-plane feed already running")
        return True
    _on_tick_callback = on_tick_callback
    _feed_running = True
    set_streaming_active_ticker(it)
    _feed_task = asyncio.get_event_loop().create_task(_feed_loop(), name="daemon-plane-feed")
    log.info("Live-plane feed started (initial ticker %s, source=canonical capture daemon)", it)
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
