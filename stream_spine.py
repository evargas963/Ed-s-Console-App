"""CR-01 streaming spine: topic bus + last-value cache + capture writer + feed health.

Consensus plan v1.2 (docs/CONSOLE_REBUILD_PLAN_CR_V1.md §4). Laws encoded here:
  - cache-then-publish: the cache is written BEFORE subscribers are notified, so any
    consumer can snapshot-then-ride-deltas without a poll-to-hydrate step.
  - every queue is BOUNDED with an explicit policy: quotes coalesce-to-latest,
    prints are NEVER coalesced (drops are counted and surface in health).
  - raw streams write ONLY to stream_capture.db — ed_console.db grows zero bytes.
  - health is first-class: a stale feed must look different from a quiet market.

Pure asyncio; no Schwab/Alpaca imports here. The capture daemon (tools/) plugs feed
clients into `MessageBus.publish` and runs `CaptureWriter.run` + `HealthRegistry`.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from db_authority import canonical_stream_db_path

STREAM_DB_DEFAULT = canonical_stream_db_path()


def resolve_stream_db_path(default: "Path | str | None" = None) -> Path:
    """THE ONE canonical stream-capture DB path authority every producer and
    consumer (tools/run_stream_capture.py's CaptureWriter,
    app/options/order_flow/streaming.py's feed-loop reader) resolves through.

    RC-534 removed the ambient STREAM_CAPTURE_DB_PATH authority. Linked worktrees
    already converge through runtime_layout; recovery/tests pass an explicit path
    to the owning API instead of changing the production default process-wide.
    ``default`` remains solely for test-monkeypatched reader modules."""
    if default is not None:
        return Path(default).resolve()
    return canonical_stream_db_path()

def default_active_ticker_signal_path(db_path: Path | str | None = None) -> Path:
    """Ticker signal beside the resolved stream DB — the ONE cross-process channel by which
    the server tells the daemon which symbol's book to add/drop. The server never opens its
    own StreamClient (single-stream-authority law).

    Resolved fresh each call through the canonical `resolve_stream_db_path`, so a worktree
    daemon and a production server converge on the same file (RC-523/RC-534 runtime_layout)
    and the live StreamClient sees exactly the contract the UI requested — never bound as a
    function default, which would freeze at import.
    """
    return resolve_stream_db_path(db_path).with_name("stream_active_ticker.json")


def default_active_option_contract_signal_path(db_path: Path | str | None = None) -> Path:
    """Option-contract signal beside the resolved stream DB. Same one channel, for the one
    option CONTRACT (OSI symbol, e.g. "SPY   260820C00767000") the daemon streams
    LEVELONE_OPTIONS/OPTIONS_BOOK for. The symbol MUST come from a chain response's own
    "symbol" field (schwab_client.safe_get_chain), never constructed here."""
    return resolve_stream_db_path(db_path).with_name("stream_active_option_contract.json")


#: Import-time snapshots of the canonical resolver above, kept for tests that monkeypatch
#: the module attribute and for callers that read a constant. Production writers/readers call
#: default_active_*_signal_path() at call time; these are that same path resolved once here,
#: so constant and function agree. ONE owner: the functions. (RC-534: the runtime_layout path
#: subsumes the older _runtime_data_dir() constant and the removed STREAM_CAPTURE_DB_PATH env.)
ACTIVE_TICKER_SIGNAL_DEFAULT = default_active_ticker_signal_path()
ACTIVE_OPTION_CONTRACT_SIGNAL_DEFAULT = default_active_option_contract_signal_path()

#: Queue policies. COALESCE keeps only the newest pending message per topic (quotes).
#: COUNT_DROPS rejects new messages when full and counts them loudly (prints).
COALESCE = "coalesce"
COUNT_DROPS = "count_drops"

STREAM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stream_quotes_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    bid REAL, ask REAL, last REAL,
    bid_size INTEGER, ask_size INTEGER, last_size INTEGER,
    total_volume INTEGER,
    quote_time_ms INTEGER, trade_time_ms INTEGER,
    src TEXT NOT NULL,
    native_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_sqr_sym_ts ON stream_quotes_raw(symbol, ts_recv);
CREATE TABLE IF NOT EXISTS stream_book_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    service TEXT NOT NULL,
    native_json TEXT NOT NULL,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sbkr_sym_ts ON stream_book_raw(symbol, ts_recv);
CREATE TABLE IF NOT EXISTS stream_options_quotes_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    native_json TEXT NOT NULL,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_soqr_sym_ts ON stream_options_quotes_raw(symbol, ts_recv);
-- One row per (symbol, service) SUBSCRIPTION INTERVAL. ended_ts NULL means still open.
-- WHY THIS EXISTS: a gap in stream_options_quotes_raw/stream_book_raw is ambiguous
-- between "we were not subscribed" (a hole in coverage) and "we were subscribed and
-- nothing changed" (the vendor's silence IS the observation) — without this record both
-- read identically as "no rows", and a reader would mistake our subscription window for
-- a market fact. Multiple option contracts may be concurrently open now (RC-UI-3,
-- 2026-09-12): this remains one open-interval ledger per (symbol, service) — each
-- concurrently-streamed contract gets its OWN row per service, closed and reopened
-- independently of every other contract's row, via _apply_active_option_contract_subs'
-- one-reconciler-instance-per-desired-symbol design (capture.py).
CREATE TABLE IF NOT EXISTS stream_coverage_epochs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    service TEXT NOT NULL,
    started_ts REAL NOT NULL,
    ended_ts REAL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_sce_sym_svc ON stream_coverage_epochs(symbol, service);
CREATE TABLE IF NOT EXISTS stream_prints_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    price REAL, size INTEGER,
    exchange TEXT, conditions TEXT,
    trade_ts_ms INTEGER,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spr_sym_ts ON stream_prints_raw(symbol, ts_recv);
CREATE TABLE IF NOT EXISTS stream_bars_raw (
    ts_recv REAL NOT NULL,
    symbol TEXT NOT NULL,
    bar_start_ms INTEGER,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    src TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sbr_sym_ts ON stream_bars_raw(symbol, bar_start_ms);
-- PR214_RTH_DEFECT_REMEDIATION_FINAL_GAPS (Gap 2): the daemon's own producer identity
-- and liveness, written INTO this same file rather than a separate checkout-relative
-- status file. A consumer that opens its OWN resolved db_path and finds a fresh row
-- here has, by construction, proven it is reading the SAME physical file the daemon is
-- writing to -- no second, independently-resolved path string to keep in sync (the
-- prior _DAEMON_STATUS_PATH-based identity check inherited the exact checkout-relative
-- defect class it was built to catch). Singleton row (id=1, upserted).
-- `claimed_coverage_json` (PR214 durable producer truth): the epoch id the LIVE producer
-- currently asserts per option service, as {service: epoch_id|null}. An OPEN coverage row
-- is NOT by itself a subscription claim: a durable CLOSE that failed leaves ended_ts NULL
-- on an epoch the daemon has already KNOWINGLY surrendered, and reading that row as
-- producer identity produced a false "subscribed" that the UI rendered. The claim rides
-- this existing liveness row so there is still exactly ONE producer-truth channel, and it
-- fails closed in both directions: the daemon republishes the claim the instant a close
-- fails, and if the daemon cannot write at all the heartbeat goes stale and nothing is
-- confirmed. The coverage rows remain the coverage HISTORY; this is the live assertion.
-- `rejected_contracts_json` (bounded-vendor-call reconciliation, 2026-09-16): symbols the
-- vendor explicitly refused on the most recent subscribe attempt, as {symbol: reason}. A
-- symbol that is simply not-yet-attempted is absent from this map entirely, never a false
-- "rejected" -- only a call that actually returned a non-zero response code for that exact
-- symbol (isolated by bisection when it was rejected as part of a larger batch) is
-- recorded here. Rides the same heartbeat row as claimed_coverage_json for the same
-- reason: one producer-truth channel, one clock, fails closed the same way (a stale
-- heartbeat means UNKNOWN, not "not rejected").
CREATE TABLE IF NOT EXISTS stream_producer_heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    daemon_pid INTEGER,
    heartbeat_ts REAL NOT NULL,
    resolved_db_path TEXT NOT NULL,
    claimed_coverage_json TEXT,
    rejected_contracts_json TEXT
);
"""


#: How long a PUBLISHED producer coverage claim can still confirm a subscription. It is
#: the consumer's staleness bound AND, read from the other side, the producer's own lease:
#: a claim written at T can be used as positive evidence until T + this. The daemon needs
#: the same number the reader uses — it is what tells a controlled surrender how long a
#: claim it failed to retract remains capable of confirming — so the value lives here, in
#: the module both sides already share, rather than being duplicated on either side.
PRODUCER_CLAIM_TTL_SEC = 30.0


def read_producer_heartbeat(conn: sqlite3.Connection) -> "dict | None":
    """Read the producer identity/liveness row from THIS connection's own
    stream_capture.db (Gap 2) -- the SAME data plane the caller already reads
    quote/book rows from, never a second independent channel. Returns None when the
    table does not exist yet (a pre-heartbeat daemon, or a DB nothing has ever written
    a heartbeat into) or holds no row. The caller judges freshness/identity from the
    returned `heartbeat_ts`, not this function."""
    try:
        row = conn.execute(
            "SELECT daemon_pid, heartbeat_ts, resolved_db_path, claimed_coverage_json, "
            "rejected_contracts_json FROM stream_producer_heartbeat WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    try:
        claimed = json.loads(row[3]) if row[3] else None
    except (TypeError, ValueError):
        claimed = None      # unparseable claim is UNKNOWN, never confirmation
    try:
        rejected = json.loads(row[4]) if row[4] else None
    except (TypeError, ValueError):
        rejected = None      # unparseable rejection map is UNKNOWN, never confirmation
    return {"daemon_pid": row[0], "heartbeat_ts": row[1], "resolved_db_path": row[2],
            "claimed_coverage": claimed, "rejected_contracts": rejected}


def read_rejected_option_contracts(conn: sqlite3.Connection, *, stale_sec: float,
                                   now: "float | None" = None) -> "dict[str, str]":
    """PRODUCER-SIDE rejection identity: {symbol: reason} for every additional option
    contract the vendor explicitly refused on its most recent subscribe attempt, per
    `read_producer_heartbeat`'s own claim (never a second channel). A stale or absent
    heartbeat yields {} -- unknown is never "not rejected", the same fail-closed rule
    `read_open_coverage_symbols` applies to confirmed coverage. `stale_sec` is required
    for the same reason it is required there: there is no correct ungated read."""
    beat = read_producer_heartbeat(conn)
    if beat is None:
        return {}
    hb_ts = beat.get("heartbeat_ts")
    t = time.time() if now is None else now
    if not isinstance(hb_ts, (int, float)) or (t - float(hb_ts)) > float(stale_sec):
        return {}
    rejected = beat.get("rejected_contracts")
    if not isinstance(rejected, dict):
        return {}
    return {str(k): str(v) for k, v in rejected.items()}


def read_open_coverage_symbols(conn: sqlite3.Connection,
                               services: "tuple[str, ...]", *,
                               stale_sec: float,
                               now: "float | None" = None) -> "dict[str, list[str]]":
    """PRODUCER-SIDE subscription identity, read from THIS connection's own
    stream_capture.db (PR214 premerge gap 1A).

    The active-contract SIGNAL FILE(s) are DESIRED state -- what the server asked for. The
    OPEN COVERAGE EPOCH is PRODUCER state -- what the daemon actually holds a vendor
    subscription for, written only after a confirmed subscribe. Between an operator's
    request and the daemon's next poll, those disagree, and a health verdict built on
    desired state alone would claim a contract is live while the producer still physically
    holds a different (or no) set.

    Returns {service: [confirmed_symbol, ...]} -- MULTIPLE concurrently-open, independently
    confirmed symbols per service are the NORMAL case as of RC-UI-3 (2026-09-12,
    multi-contract coverage; previously this returned {service: symbol|None} because the
    daemon's reconciler could only ever hold one symbol per service at all). Each OPEN row
    is confirmed or refused entirely on ITS OWN claimed epoch id -- one row's confirmation
    or refusal never depends on how many OTHER rows are also open for the same service.

    A missing table, unreadable DB, or stale/absent producer heartbeat likewise yields []
    for every service: unknown is never confirmation.

    AN OPEN ROW IS NOT BY ITSELF A CLAIM (PR214 durable producer truth). `ended_ts IS
    NULL` used to be sufficient, and it lied: when a durable CLOSE fails, the row stays
    open for an epoch the daemon has ALREADY KNOWINGLY SURRENDERED, so this reader
    answered with a contract the vendor was no longer subscribed to and the UI rendered it
    as "subscribed". Measured at that shape, the state was re-entrant -- every tick the
    daemon subscribed, was refused a durable epoch, and unsubscribed again, capturing
    nothing, while this function kept naming the contract.

    A row therefore confirms only when the LIVE producer currently asserts that exact
    epoch id, via `claimed_coverage` on its heartbeat (now {service: [epoch_id, ...]} --
    the SET of epoch ids this producer currently claims for that service, not one bare
    id). That closes both directions of the failure:
      * daemon alive, close failed -> it republishes the claim immediately (the surrendered
        id is gone from the list), so that ROW returns unconfirmed even though it is still
        open in the table;
      * daemon cannot write at all -> the heartbeat itself goes stale past `stale_sec`,
        and a stale producer confirms nothing.
    A durable-write failure can therefore make producer identity UNKNOWN. It can no longer
    manufacture a false positive.

    A DUPLICATE symbol -- the SAME symbol open on the SAME service via two different rows
    -- remains refused for that symbol even though the underlying CaptureWriter guard
    (open_coverage_epoch's per-(symbol,service) uniqueness check) should make it
    unreachable through the normal path; a corrupted or hand-edited ledger must not be
    laundered into a confident double-confirmation here.

    `stale_sec` is required, not defaulted: there is no correct "ungated" read of this
    table, and an optional gate is one a caller can forget."""
    out: "dict[str, list[str]]" = {s: [] for s in services}
    beat = read_producer_heartbeat(conn)
    if beat is None:
        return out              # no producer has ever asserted anything here
    hb_ts = beat.get("heartbeat_ts")
    t = time.time() if now is None else now
    if not isinstance(hb_ts, (int, float)) or (t - float(hb_ts)) > float(stale_sec):
        return out              # the producer is not currently able to assert anything
    claimed = beat.get("claimed_coverage")
    if not isinstance(claimed, dict):
        return out              # a producer that publishes no claim confirms nothing
    for service in services:
        try:
            rows = conn.execute(
                "SELECT id, symbol FROM stream_coverage_epochs "
                "WHERE service = ? AND ended_ts IS NULL", (service,)).fetchall()
        except sqlite3.OperationalError:
            return {s: [] for s in services}
        if not rows:
            continue             # not subscribed to anything, as far as the ledger knows
        claimed_ids = claimed.get(service)
        if not isinstance(claimed_ids, list):
            continue             # no live claim for this service at all (surrendered/unknown)
        claimed_id_set = {v for v in claimed_ids if isinstance(v, int) and not isinstance(v, bool)}
        symbol_row_counts: dict[str, int] = {}
        for _row_id, sym in rows:
            symbol_row_counts[sym] = symbol_row_counts.get(sym, 0) + 1
        confirmed: list[str] = []
        for row_id, sym in rows:
            if symbol_row_counts[sym] != 1:
                continue          # the SAME symbol open twice on one service: refuse it
            if row_id in claimed_id_set:
                confirmed.append(sym)
        out[service] = sorted(confirmed)
    return out


def quote_msg(*, symbol: str, bid=None, ask=None, last=None, bid_size=None, ask_size=None,
              last_size=None, total_volume=None, quote_time_ms=None, trade_time_ms=None,
              src: str, ts_recv: float | None = None, native: dict | None = None) -> dict:
    """The ONE producer shape for quote.* topics — daemon and tests both build through
    here so the writer's reads and the producers' writes can never drift (RC-15 class).

    ``native``: the Schwab content-item dict verbatim, when the caller has it (e.g. a
    LEVEL_ONE_EQUITY handler). Stored alongside the flattened columns so a downstream
    consumer that needs FIELD FIDELITY (e.g. live-plane hydration, which reads
    BID_TIME_MILLIS / REGULAR_MARKET_CHANGE_PERCENT — fields the flattened columns do
    not carry) is not forced to re-derive a lossy approximation from them. Optional:
    existing quote producers that lack the native dict are unaffected."""
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "bid": bid, "ask": ask, "last": last, "bid_size": bid_size,
            "ask_size": ask_size, "last_size": last_size, "total_volume": total_volume,
            "quote_time_ms": quote_time_ms, "trade_time_ms": trade_time_ms, "src": src,
            "native": native}


def book_msg(*, symbol: str, service: str, content: dict, src: str,
             ts_recv: float | None = None) -> dict:
    """The ONE producer shape for book.* topics (NASDAQ_BOOK / NYSE_BOOK).

    ``content`` is the Schwab content-item dict verbatim (BIDS/ASKS/BOOK_TIME) — stored
    as-is, never flattened, since book depth has no meaningful scalar projection."""
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "service": service, "content": content, "src": src}


def options_quote_msg(*, symbol: str, content: dict, src: str,
                      ts_recv: float | None = None) -> dict:
    """The ONE producer shape for optquote.* topics (LEVELONE_OPTIONS).

    ``content`` is the Schwab content-item dict verbatim (57 native fields: greeks, OI,
    IV, DTE, ...) — stored as native JSON, never flattened; nothing in this repo reads a
    flattened options-quote column, so inventing one would be speculative schema, not a
    compatibility need."""
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "content": content, "src": src}


def _write_json_signal(value_key: str, value: str, *, path: Path) -> None:
    """Shared atomic write for the server->daemon signal files: write-temp-then-replace,
    so the daemon (polling on its own schedule) never observes a half-written body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({value_key: (value or "").upper().strip(),
                               "requested_at": time.time()}), encoding="utf-8")
    tmp.replace(path)


def _read_json_signal_body(path: Path) -> dict:
    """Shared malformed-content guard for every signal reader below (singular and
    plural): any read/parse failure, OR valid JSON whose root is not an object (a bare
    list, string, number, `true`/`false`, or `null` -- all legal JSON, none of them a
    signal body), returns {} uniformly. Independent-review finding (2026-09-12): both
    _read_json_signal and _read_json_list_signal called `.get(value_key)` directly on
    the parsed root, raising AttributeError on `[]` or `null` content instead of the
    fail-closed 'nothing requested' every caller here documents and depends on -- a
    malformed signal must never raise into the daemon's poll loop."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_json_signal(value_key: str, *, path: Path) -> str | None:
    """Shared read: None on any absence/corruption/malformed-root content — a missing or
    unusable signal means 'no subscription', never a guessed value."""
    v = str(_read_json_signal_body(path).get(value_key) or "").upper().strip()
    return v or None


def write_active_ticker_signal(ticker: str, *, path: Path | None = None) -> None:
    """The server's ONE write into the daemon's book-subscription decision."""
    dest = path if path is not None else default_active_ticker_signal_path()
    _write_json_signal("ticker", ticker, path=dest)


def read_active_ticker_signal(*, path: Path | None = None) -> str | None:
    """The daemon's read of the server's requested active ticker."""
    dest = path if path is not None else default_active_ticker_signal_path()
    return _read_json_signal("ticker", path=dest)


def write_active_option_contract_signal(
    contract_symbol: str, *, path: Path | None = None,
) -> None:
    """The server's ONE write into the daemon's options-subscription decision.
    `contract_symbol` MUST be a chain response's own "symbol" field — never constructed
    here."""
    dest = path if path is not None else default_active_option_contract_signal_path()
    _write_json_signal("contract_symbol", contract_symbol, path=dest)


def read_active_option_contract_signal(
    *, path: Path | None = None,
) -> str | None:
    """The daemon's read of the server's requested active option contract."""
    dest = path if path is not None else default_active_option_contract_signal_path()
    return _read_json_signal("contract_symbol", path=dest)


def default_active_option_contracts_signal_path(db_path: Path | str | None = None) -> Path:
    """PLURAL companion to default_active_option_contract_signal_path (RC-UI-3, 2026-09-12:
    "historical coverage failures establish properties to preserve; they do not establish
    that single-contract operation must survive" — operator authorization to move past the
    single-contract ceiling). A SEPARATE file/key from the singular signal, not a shape
    change to it: every existing reader of the singular signal is completely unaffected,
    and the daemon's reconciler (capture.py) treats the union of "the one pinned contract"
    (singular signal, unchanged) and "additionally desired contracts" (this, plural) as the
    full requested set — see _apply_active_option_contract_subs."""
    return resolve_stream_db_path(db_path).with_name("stream_active_option_contracts.json")


def _write_json_list_signal(value_key: str, values: "list[str]", *, path: Path) -> None:
    """PLURAL counterpart to _write_json_signal: a de-duplicated, normalized (upper/strip,
    empties dropped) JSON list under `value_key`, same atomic write-temp-then-replace
    discipline so the daemon (polling on its own schedule) never observes a half-written
    body."""
    path.parent.mkdir(parents=True, exist_ok=True)
    norm = sorted({str(v or "").upper().strip() for v in (values or [])} - {""})
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({value_key: norm, "requested_at": time.time()}), encoding="utf-8")
    tmp.replace(path)


def _read_json_list_signal(value_key: str, *, path: Path) -> "list[str]":
    """PLURAL counterpart to _read_json_signal: [] on any absence/corruption, malformed
    root, or malformed (non-list) value — a missing/broken signal means 'no additional
    contracts', never a guessed set, exactly the same fail-closed discipline the singular
    signal uses (see _read_json_signal_body)."""
    raw = _read_json_signal_body(path).get(value_key)
    if not isinstance(raw, list):
        return []
    return sorted({str(v or "").upper().strip() for v in raw} - {""})


def write_active_option_contracts_signal(
    symbols: "list[str]", *, path: Path | None = None,
) -> None:
    """The server's write of the ADDITIONAL (beyond the one singular/pinned contract)
    option contracts it wants concurrently streamed. Each symbol MUST be a chain
    response's own "symbol" field, exactly like the singular signal — never constructed
    here. Passing an empty list clears the additional set (the singular contract, if any,
    is unaffected — it has its own signal)."""
    dest = path if path is not None else default_active_option_contracts_signal_path()
    _write_json_list_signal("contract_symbols", symbols, path=dest)


#: How many ADDITIONAL option contracts the ONE shared Schwab streaming socket may hold.
#:
#: MEASURED 2026-09-23 (stream_capture.db, 08:30-15:00 CT each day): LEVELONE_OPTIONS load
#: on the socket that also carries LEVELONE_EQUITIES / books / chart kills the WHOLE socket,
#: and every Schwab service (SPY's live price included) goes dark until a recycle:
#:   9/15    10 option subscriptions opened  ->  0 recycles, 0 SPY gaps >60s (max 24s)
#:   9/16  4,442                              ->  4 recycles, 5 gaps (max 131s)
#:   9/22 48,333 (~850-2,500 held at once)    -> 39 recycles, 41 gaps (max 824s)
#:   9/23 53,754 (~850-5,200 held at once)    -> 42 recycles, 49 gaps (max 1,341s)
#: Deaths arrive every 3-4 min with ~2,500 held and every 4-20 min with ~850 held, and every
#: one of them lands as `ConnectionClosedError: no close frame` (3,223 of 3,224 rejections
#: recorded on 9/23). Alpaca write volume is NOT the driver (5.0M rows on the clean 9/15).
#: Schwab allows ONE streamer connection per account, so options cannot move to a second
#: socket. The budget below is the starting bound, set well under the smallest held count
#: that still died (~850); tools/stream_socket_budget_probe.py re-measures recycles/hour
#: against the held count at the next RTH, and this number moves only on that evidence.
OPTION_CONTRACTS_MAX_HELD = 200


def rank_option_contracts(requested, contract_inputs: "dict[str, dict]",
                          budget: int = OPTION_CONTRACTS_MAX_HELD,
                          ) -> "tuple[list[str], dict[str, str]]":
    """(admitted, {not_admitted_symbol: reason}) -- the ONE ranking of which contracts the
    shared socket carries, done by the console.

    Inputs are canonical Schwab fields only, supplied per requested symbol in
    `contract_inputs[symbol]`:
      expirationDate -- the chain contract's own field, compared as sent   (0 hops)
      strikePrice    -- the chain contract's own field                     (0 hops)
      spot           -- the underlying's streamed LEVELONE_EQUITIES LAST_PRICE (0 hops)
    Rank = expirationDate, then |strikePrice - spot| (1 hop: one subtraction of two
    canonical fields), then symbol. A symbol with ANY input missing is not admitted and
    says which -- nothing is parsed out of the symbol text and nothing is guessed."""
    from numeric_contract import float_finite_or_none

    not_admitted: "dict[str, str]" = {}
    rankable = []
    for sym in sorted({str(s).upper().strip() for s in requested or ()} - {""}):
        inp = contract_inputs.get(sym)
        if inp is None:
            not_admitted[sym] = "not admitted: contract not in the console's current Schwab chain"
            continue
        strike = float_finite_or_none(inp.get("strikePrice"))
        spot = float_finite_or_none(inp.get("spot"))
        missing = [k for k, v in (("expirationDate", inp.get("expirationDate")),
                                  ("strikePrice", strike), ("spot", spot)) if v is None]
        if missing:
            not_admitted[sym] = f"not admitted: no {', '.join(missing)}"
            continue
        rankable.append((str(inp["expirationDate"]), abs(strike - spot), sym))
    rankable.sort()
    admitted = [sym for _e, _d, sym in rankable[:max(budget, 0)]]
    for _e, _d, sym in rankable[max(budget, 0):]:
        not_admitted[sym] = f"not admitted: outside the live-stream budget ({budget})"
    return admitted, not_admitted


def enforce_option_contracts_budget(symbols, budget: int = OPTION_CONTRACTS_MAX_HELD
                                    ) -> "tuple[list[str], dict[str, str]]":
    """The DAEMON's guard. It holds no spot, so it never ranks: a request within the budget
    is held as sent; a request over it is refused whole (every symbol not admitted, with the
    reason), because only the console can choose by spot. The console always sends a set
    already ranked to the budget, so a refusal here means the console broke its contract."""
    uniq = sorted({str(s).upper().strip() for s in symbols or ()} - {""})
    if len(uniq) <= budget:
        return uniq, {}
    reason = (f"not admitted: request of {len(uniq)} contracts exceeds the shared-socket "
              f"budget ({budget}); the console must rank by spot before sending")
    return [], {s: reason for s in uniq}


def read_active_option_contracts_signal(
    *, path: Path | None = None,
) -> "list[str]":
    """The daemon's read of the server's ADDITIONALLY-requested option contracts (beyond
    the one singular/pinned contract, which keeps reading from its own unchanged signal)."""
    dest = path if path is not None else default_active_option_contracts_signal_path()
    return _read_json_list_signal("contract_symbols", path=dest)


def print_msg(*, symbol: str, price=None, size=None, exchange=None, conditions=None,
              trade_ts_ms=None, src: str, ts_recv: float | None = None) -> dict:
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "price": price, "size": size, "exchange": exchange, "conditions": conditions,
            "trade_ts_ms": trade_ts_ms, "src": src}


def bar_msg(*, symbol: str, bar_start_ms=None, open=None, high=None, low=None, close=None,  # noqa: A002
            volume=None, src: str, ts_recv: float | None = None) -> dict:
    return {"ts_recv": ts_recv if ts_recv is not None else time.time(), "symbol": symbol,
            "bar_start_ms": bar_start_ms, "open": open, "high": high, "low": low,
            "close": close, "volume": volume, "src": src}


@dataclass
class Subscription:
    prefix: str
    policy: str
    queue: asyncio.Queue
    #: COALESCE keeps the newest pending message per exact topic here instead of the queue.
    pending: dict[str, Any] = field(default_factory=dict)
    dropped: int = 0

    def deliver(self, topic: str, msg: Any) -> None:
        if self.policy == COALESCE:
            # Newest wins per topic; the queue carries topic keys, payload rides pending.
            fresh = topic not in self.pending
            self.pending[topic] = msg
            if fresh:
                try:
                    self.queue.put_nowait(topic)
                except asyncio.QueueFull:
                    self.pending.pop(topic, None)
                    self.dropped += 1
            return
        try:
            self.queue.put_nowait((topic, msg))
        except asyncio.QueueFull:
            self.dropped += 1

    async def get(self) -> tuple[str, Any]:
        item = await self.queue.get()
        if self.policy == COALESCE:
            topic = item
            return topic, self.pending.pop(topic)
        return item


class MessageBus:
    """Topic pub/sub with a last-value cache written BEFORE publish (cache-then-publish)."""

    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        self.cache: dict[str, Any] = {}
        self.published = 0

    def subscribe(self, prefix: str, *, policy: str = COUNT_DROPS, maxsize: int = 2048) -> Subscription:
        sub = Subscription(prefix=prefix, policy=policy, queue=asyncio.Queue(maxsize=maxsize))
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """Stop delivering to `sub` (a disconnected push client must not accumulate)."""
        if sub in self._subs:
            self._subs.remove(sub)

    def publish(self, topic: str, msg: Any) -> None:
        self.cache[topic] = msg
        self.published += 1
        for sub in self._subs:
            if topic.startswith(sub.prefix):
                sub.deliver(topic, msg)

    def snapshot(self, prefix: str = "") -> dict[str, Any]:
        return {t: v for t, v in self.cache.items() if t.startswith(prefix)}

    def drop_counts(self) -> dict[str, int]:
        return {s.prefix: s.dropped for s in self._subs if s.dropped}


#: Health thresholds (seconds since last message). DEGRADED warns; STALE is the
#: fail-closed state that CR-07's law hooks (STALE -> directional prompts suppressed).
HEALTH_DEGRADED_SEC = 5.0
HEALTH_STALE_SEC = 30.0


class HealthRegistry:
    """Per-feed liveness: RUNNING / DEGRADED / STALE / DOWN, judged by message age."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def beat(self, feed: str, ts: float | None = None) -> None:
        self._last[feed] = ts if ts is not None else time.time()

    def state(self, feed: str, now: float | None = None) -> str:
        last = self._last.get(feed)
        if last is None:
            return "DOWN"
        age = (now if now is not None else time.time()) - last
        if age <= HEALTH_DEGRADED_SEC:
            return "RUNNING"
        if age <= HEALTH_STALE_SEC:
            return "DEGRADED"
        return "STALE"

    def report(self, now: float | None = None) -> dict[str, dict]:
        t = now if now is not None else time.time()
        return {
            f: {"state": self.state(f, t), "age_sec": round(t - ts, 3)}
            for f, ts in self._last.items()
        }

    def any_stale(self, now: float | None = None) -> bool:
        return any(v["state"] in ("STALE", "DOWN") for v in self.report(now).values())


class CoverageWriteError(Exception):
    """A durable coverage-epoch write did not land.

    Raised, not swallowed, so a caller advancing IN-MEMORY subscription state (e.g. the
    daemon's option_state["contract"]) can gate that advance on the durable record
    actually being written — memory must never claim coverage the epoch table never
    recorded, or a reader trusting the epoch table would see a coverage window that was
    never actually live.
    """


class CaptureWriter:
    """Single writer draining bus subscriptions into stream_capture.db in batches.

    NEVER points at ed_console.db — guarded at construction, not by convention.
    Commit every `batch_rows` rows or `batch_sec`, whichever first.
    """

    def __init__(self, db_path: "Path | str | None" = None, *,
                 batch_rows: int = 500, batch_sec: float = 0.25) -> None:
        # None always means the canonical permanent stream DB. An explicit path is
        # retained for isolated tests/recovery APIs; the production daemon exposes no
        # path option.
        p = resolve_stream_db_path() if db_path is None else Path(db_path).resolve()
        # RESOLVED path, not basename: `data/x/../ed_console.db`, symlinks and junctions
        # all collapse under resolve() (Cursor review 2026-07-21: basename-only guard
        # was bypassable — an RC-6 law hole).
        if p.name == "ed_console.db":
            raise ValueError("CaptureWriter must never write the operational DB (RC-6 law)")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = p
        self.batch_rows = int(batch_rows)
        self.batch_sec = float(batch_sec)
        self.rows_written = 0
        self.commits = 0
        self.insert_errors = 0
        #: When a POSITIVE coverage claim was last successfully published, or None if the
        #: most recent successful publication claimed nothing. This is the producer's own
        #: view of its outstanding lease: a controlled surrender that cannot retract the
        #: claim must not proceed until this + PRODUCER_CLAIM_TTL_SEC has passed, because
        #: until then a consumer can still confirm coverage from it.
        self._positive_claim_ts: "float | None" = None
        #: Sticky last-published rejection map. `write_heartbeat` is called far more often
        #: (every coverage-epoch open/close/retry) than the caller that actually knows the
        #: current rejection set (the reconciler, on its own slower cadence) — if every one
        #: of those more-frequent calls wrote `rejected_contracts=None` literally, each
        #: would NULL OUT a standing rejection until the reconciler's next tick republished
        #: it, a real gap a consumer could read as "no longer rejected" mid-window. Passing
        #: None therefore means "unchanged", not "clear"; pass {} explicitly to clear it.
        self._last_rejected_contracts: "dict[str, str] | None" = None
        self._closed = False
        self._conn = sqlite3.connect(str(p))
        try:
            self._conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
            self._conn.executescript(STREAM_SCHEMA_SQL)
            # CREATE TABLE IF NOT EXISTS does not add columns to a table that already
            # exists from a prior daemon run. Migrate forward, idempotently.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(stream_quotes_raw)")}
            if "native_json" not in cols:
                self._conn.execute("ALTER TABLE stream_quotes_raw ADD COLUMN native_json TEXT")
            hb_cols = {r[1] for r in
                       self._conn.execute("PRAGMA table_info(stream_producer_heartbeat)")}
            if "claimed_coverage_json" not in hb_cols:
                self._conn.execute("ALTER TABLE stream_producer_heartbeat "
                                   "ADD COLUMN claimed_coverage_json TEXT")
            if "rejected_contracts_json" not in hb_cols:
                self._conn.execute("ALTER TABLE stream_producer_heartbeat "
                                   "ADD COLUMN rejected_contracts_json TEXT")
            self._conn.commit()
        except Exception:
            # Init failed after connect — close before the object is discarded so the
            # SQLite handle cannot leak until GC (Bugbot 2026-07-21 HIGH).
            self._conn.close()
            self._closed = True
            raise

    def insert(self, topic: str, msg: dict, *, conn: "sqlite3.Connection | None" = None) -> None:
        """Write one bus message. `conn` is the writer thread's own connection in `run`;
        direct callers (tests, recovery tools) write on the control connection."""
        db = self._conn if conn is None else conn
        kind = topic.split(".", 1)[0]
        if kind == "quote":
            native = msg.get("native")
            db.execute(
                "INSERT INTO stream_quotes_raw(ts_recv,symbol,bid,ask,last,bid_size,ask_size,"
                "last_size,total_volume,quote_time_ms,trade_time_ms,src,native_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("bid"), msg.get("ask"),
                 msg.get("last"), msg.get("bid_size"), msg.get("ask_size"), msg.get("last_size"),
                 msg.get("total_volume"), msg.get("quote_time_ms"), msg.get("trade_time_ms"),
                 msg.get("src", "?"),  # caps-ok: src is a required kwarg on quote_msg (no default); "?" only guards a dict built outside that constructor, never a legitimately-absent value
                 json.dumps(native) if native is not None else None))
        elif kind == "book":
            content = msg.get("content")
            if content is None:
                return
            db.execute(
                "INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,src) "
                "VALUES(?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("service"),
                 json.dumps(content),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on book_msg (no default); same guard as the quote branch above
        elif kind == "optquote":
            content = msg.get("content")
            if content is None:
                return
            db.execute(
                "INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,src) "
                "VALUES(?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), json.dumps(content),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on options_quote_msg (no default); same guard as the quote branch above
        elif kind == "print":
            db.execute(
                "INSERT INTO stream_prints_raw(ts_recv,symbol,price,size,exchange,conditions,"
                "trade_ts_ms,src) VALUES(?,?,?,?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("price"), msg.get("size"),
                 msg.get("exchange"), msg.get("conditions"), msg.get("trade_ts_ms"),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on print_msg (no default); same guard as the quote branch above
        elif kind == "bar1m":
            db.execute(
                "INSERT INTO stream_bars_raw(ts_recv,symbol,bar_start_ms,open,high,low,close,"
                "volume,src) VALUES(?,?,?,?,?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("bar_start_ms"), msg.get("open"),
                 msg.get("high"), msg.get("low"), msg.get("close"), msg.get("volume"),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on bar_msg (no default); same guard as the quote branch above
        else:
            return
        self.rows_written += 1

    def commit(self) -> None:
        self._conn.commit()
        self.commits += 1

    #: Canonical reason stamped on epochs left open by a prior daemon lifetime.
    COVERAGE_ORPHAN_REASON = "daemon_restart_orphan"

    #: RETIRED (2026-09-12, RC-UI-3 multi-contract coverage — operator-authorized:
    #: "historical coverage failures establish properties to preserve; they do not
    #: establish that single-contract operation must survive"). Previously named
    #: LEVELONE_OPTIONS/OPTIONS_BOOK here to scope their open-epoch uniqueness check to
    #: the WHOLE SERVICE regardless of symbol, because the two-key ("l1"/"book")
    #: reconciler in capture.py could only ever hold ONE symbol per service, and a
    #: switch whose close failed could otherwise open a SECOND symbol's epoch while the
    #: first was still open. That reconciler now runs one independent instance PER
    #: desired symbol (still using this exact per-(symbol,service) uniqueness check
    #: below, in the `else` branch, which already existed for every OTHER service) — so
    #: the constraint this set existed to add is now redundant with, and strictly
    #: weaker than, the ordinary per-(symbol,service) rule every service gets: two
    #: DIFFERENT symbols legitimately open at once is the whole point of multi-contract
    #: coverage; the SAME symbol open twice remains refused, exactly as for any other
    #: service. `claimed_coverage`'s shape changed accordingly (server.py's
    #: _publish_coverage_claim publishes a LIST of currently-claimed epoch ids per
    #: service, not one bare id) — see read_open_coverage_symbols below, which now
    #: confirms EACH open row against its OWN claimed epoch id instead of refusing
    #: whenever more than one row is open.
    SINGLE_CONTRACT_SERVICES: frozenset[str] = frozenset()

    def reconcile_orphan_coverage_epochs(self, *, reason: str | None = None,
                                         ts: float | None = None) -> int:
        """Close every epoch still open from a PRIOR daemon lifetime. Returns the count.

        PR214 merge blocker 2A. stream_coverage_epochs exists to separate "we were NOT
        subscribed" from "we were subscribed and the vendor was silent". A clean
        shutdown closes its epochs; a hard process death (SIGKILL, power loss, OOM)
        skips that cleanup entirely, leaving `ended_ts IS NULL` rows behind. On restart
        the in-memory epoch state is new, so those rows would persist as
        INDEFINITELY-SUBSCRIBED forever -- a historically false claim of coverage over
        a window in which the daemon was not even running.

        This runs at startup, BEFORE any new live epoch is opened, and closes those
        rows durably. History is never deleted and the crash time is never fabricated:
        `ended_ts` here is the RECONCILIATION timestamp, and its documented meaning is
        "coverage is KNOWN CLOSED NO LATER THAN this new daemon's startup" -- an upper
        bound on the true end, not a claim to know when the previous process died. The
        `reason` column records that provenance so a reader can tell a reconciled
        boundary from an observed one and never mistake it for a measured close.
        """
        t = ts if ts is not None else time.time()
        r = reason if reason is not None else self.COVERAGE_ORPHAN_REASON
        try:
            # MEASURE the orphan count, never infer it from cursor.rowcount: sqlite3
            # reports -1 when it cannot determine the affected-row count, and coercing
            # that to 0 would silently report "no orphans found" for a reconciliation
            # that may have closed many -- the exact silent-zero shape this repo bans.
            # The count is read on the same connection immediately before the UPDATE
            # that consumes it, so it is the number of rows actually reconciled.
            n = int(self._conn.execute(
                "SELECT COUNT(*) FROM stream_coverage_epochs "
                "WHERE ended_ts IS NULL").fetchone()[0])
            self._conn.execute(
                "UPDATE stream_coverage_epochs SET ended_ts=?, reason=? "
                "WHERE ended_ts IS NULL", (t, r))
            self._conn.commit()
            return n
        except Exception as e:
            raise CoverageWriteError(f"reconcile_orphan_coverage_epochs: {e}") from e

    def open_coverage_epoch(self, symbol: str, service: str, *, reason: str,
                            ts: float | None = None) -> int:
        """Immediately committed, not batched: this is a low-frequency state transition
        where correctness (durably recording WHEN a subscription started) matters more
        than throughput. Returns the new epoch's row id.

        PR214 merge blocker 2B: refuses to create a SECOND open epoch for the same
        (symbol, service). Two concurrently-open rows for one pair is contradictory
        history -- it makes the coverage ledger unreadable, since a gap can no longer be
        attributed to a single subscription window. The invariant is mechanical:
        OPEN_EPOCH_COUNT <= 1 per (symbol, service). Normal re-subscription is
        unaffected because it closes the prior epoch first; reaching here with a row
        still open means reconciliation was skipped or a close was lost, so this fails
        LOUDLY rather than silently writing a record that cannot be true."""
        t = ts if ts is not None else time.time()
        try:
            # For a single-contract service the scope is the SERVICE, regardless of
            # symbol (see SINGLE_CONTRACT_SERVICES); otherwise it is (symbol, service).
            if service in self.SINGLE_CONTRACT_SERVICES:
                existing = self._conn.execute(
                    "SELECT id, symbol FROM stream_coverage_epochs "
                    "WHERE service=? AND ended_ts IS NULL", (service,)).fetchall()
                scope = f"service {service}"
            else:
                existing = self._conn.execute(
                    "SELECT id, symbol FROM stream_coverage_epochs "
                    "WHERE symbol=? AND service=? AND ended_ts IS NULL",
                    (symbol, service)).fetchall()
                scope = f"({symbol}, {service})"
            if existing:
                raise CoverageWriteError(
                    f"open_coverage_epoch({symbol},{service}): refusing to open a second "
                    f"epoch while {len(existing)} is/are still open for {scope} (row id(s) "
                    f"{[r[0] for r in existing]}, symbol(s) {[r[1] for r in existing]}). "
                    f"Close the prior epoch, or run reconcile_orphan_coverage_epochs() at "
                    f"startup — two open epochs on one option service is contradictory "
                    f"coverage history and makes producer identity unanswerable.")
            cur = self._conn.execute(
                "INSERT INTO stream_coverage_epochs(symbol,service,started_ts,reason) "
                "VALUES(?,?,?,?)", (symbol, service, t, reason))
            self._conn.commit()
            return cur.lastrowid
        except CoverageWriteError:
            raise
        except Exception as e:
            raise CoverageWriteError(f"open_coverage_epoch({symbol},{service}): {e}") from e

    def write_heartbeat(self, *, pid: int | None = None, ts: float | None = None,
                        claimed_coverage: "dict[str, list[int]] | None" = None,
                        rejected_contracts: "dict[str, str] | None" = None) -> None:
        """Producer identity/liveness signal written INTO the canonical stream_capture.db
        itself (PR214_RTH_DEFECT_REMEDIATION_FINAL_GAPS, Gap 2) -- not a separate
        checkout-relative status file. A consumer opening its OWN resolved db_path and
        finding a fresh row here has, by construction, proven it is reading the SAME
        physical file this writer is writing to. `resolved_db_path` is carried for human
        diagnostics only (what the daemon believes its own path is) -- it is NOT the
        trust mechanism; the trust mechanism is "this connection can see this row at
        all". Immediately committed (like open/close_coverage_epoch): a low-frequency
        liveness signal where durability matters more than batching throughput."""
        t = ts if ts is not None else time.time()
        p = pid if pid is not None else os.getpid()
        claim = None if claimed_coverage is None else json.dumps(
            {str(k): v for k, v in claimed_coverage.items()}, sort_keys=True)
        if rejected_contracts is not None:
            self._last_rejected_contracts = {str(k): str(v) for k, v in rejected_contracts.items()}
        rejected = None if self._last_rejected_contracts is None else json.dumps(
            self._last_rejected_contracts, sort_keys=True)
        try:
            self._conn.execute(
                "INSERT INTO stream_producer_heartbeat(id, daemon_pid, heartbeat_ts, "
                "resolved_db_path, claimed_coverage_json, rejected_contracts_json) "
                "VALUES (1, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET daemon_pid=excluded.daemon_pid, "
                "heartbeat_ts=excluded.heartbeat_ts, resolved_db_path=excluded.resolved_db_path, "
                "claimed_coverage_json=excluded.claimed_coverage_json, "
                "rejected_contracts_json=excluded.rejected_contracts_json",
                (p, t, str(self.db_path), claim, rejected))
            self._conn.commit()
        except Exception as e:
            raise CoverageWriteError(f"write_heartbeat: {e}") from e
        # Only a LANDED write changes the outstanding lease. A publication that claims
        # nothing clears it; one that names any epoch starts a fresh one at `t`.
        # RC-UI-3 (2026-09-12): claimed_coverage's per-service values are now LISTS of
        # epoch ids (multi-contract), not a bare id-or-None -- an EMPTY list must count
        # as "nothing claimed for this service", the same as the old None did, so this is
        # a plain truthiness check (an empty list, like None, is falsy) rather than the
        # old `is not None` (which would have misread {} as a positive claim).
        self._positive_claim_ts = t if (
            claimed_coverage and any(v for v in claimed_coverage.values())
        ) else None

    @property
    def positive_claim_published_ts(self) -> "float | None":
        """When this producer last successfully published a POSITIVE coverage claim.

        None means nothing it published is capable of confirming coverage. Otherwise the
        claim can still confirm until this + PRODUCER_CLAIM_TTL_SEC — which is exactly the
        barrier a controlled surrender must clear when it cannot retract the claim."""
        return self._positive_claim_ts

    def close_coverage_epoch(self, epoch_id: int, *, reason: str,
                             ts: float | None = None) -> None:
        """Idempotent: only an OPEN epoch (ended_ts IS NULL) is closed, so a duplicate
        close call cannot overwrite an already-recorded end time."""
        t = ts if ts is not None else time.time()
        try:
            self._conn.execute(
                "UPDATE stream_coverage_epochs SET ended_ts=?, reason=? "
                "WHERE id=? AND ended_ts IS NULL", (t, reason, epoch_id))
            self._conn.commit()
        except Exception as e:
            raise CoverageWriteError(f"close_coverage_epoch({epoch_id}): {e}") from e

    def _insert_guarded(self, topic: str, msg: Any, *,
                        conn: "sqlite3.Connection | None" = None) -> int:
        """1 if a row landed; insert failures are COUNTED, never kill the writer
        (Cursor review MEDIUM: an uncaught insert() death silently stopped capture)."""
        try:
            before = self.rows_written
            self.insert(topic, msg, conn=conn)
            return self.rows_written - before
        except Exception:  # noqa: BLE001 — counted + surfaced in status; capture continues
            self.insert_errors += 1
            return 0

    #: Sentinel that tells the writer thread to commit what it holds and exit.
    _WRITER_STOP = object()

    async def run(self, sub: Subscription, *, stop: asyncio.Event) -> None:
        """Persist every bus message -- WITHOUT ever blocking the event loop.

        MEASURED 2026-09-23: this used to execute every SQLite insert and commit on the SAME
        asyncio loop that reads the Schwab and Alpaca websockets. A slow commit (a busy
        disk, a reader holding the WAL) stalled the socket reads; the writer queue reached
        6,565 and 9,784 messages were dropped. Now the loop only hands each message to a
        thread-safe queue (put, never blocks) and a dedicated thread, which owns its own
        SQLite connection, does all tick inserts and batch commits. The rare control writes
        (coverage epochs, heartbeat) keep the control connection on the loop thread -- two
        connections on one WAL database is SQLite's supported pattern.

        Stop semantics are unchanged: everything already delivered to the subscription is
        handed to the thread, which writes and commits it all before `run` returns."""
        q: "queue.SimpleQueue" = queue.SimpleQueue()
        self._writer_queue = q
        thread = threading.Thread(target=self._writer_thread, args=(q,),
                                  name="stream-capture-writer", daemon=True)
        thread.start()
        try:
            while not stop.is_set():
                try:
                    item = await asyncio.wait_for(sub.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                q.put(item)
            while not sub.queue.empty():
                q.put(await sub.get())
        finally:
            q.put(self._WRITER_STOP)
            await asyncio.to_thread(thread.join)
            self._writer_queue = None

    def writer_backlog(self) -> "int | None":
        """Messages handed to the writer thread and not yet written (None when not running)."""
        q = getattr(self, "_writer_queue", None)  # caps-ok: None before run() starts or after it returns -- the documented "not running" answer
        return q.qsize() if q is not None else None

    def _writer_thread(self, q: "queue.SimpleQueue") -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        pending = 0
        last_commit = time.monotonic()
        try:
            conn.execute("PRAGMA synchronous=NORMAL")
            while True:
                timeout = max(self.batch_sec - (time.monotonic() - last_commit), 0.01)
                try:
                    item = q.get(timeout=timeout)
                except queue.Empty:
                    item = None
                if item is self._WRITER_STOP:
                    break
                if item is not None:
                    topic, msg = item
                    pending += self._insert_guarded(topic, msg, conn=conn)
                if pending and (pending >= self.batch_rows
                                or time.monotonic() - last_commit >= self.batch_sec):
                    conn.commit()
                    self.commits += 1
                    pending = 0
                    last_commit = time.monotonic()
            if pending:
                conn.commit()
                self.commits += 1
        finally:
            conn.close()

    def close(self) -> None:
        """Idempotent — the daemon closes in a finally that may run after an inner
        close (Cursor round-3 MEDIUM: login-failure paths leaked the connection).

        Commit-then-close: `_closed` is set only after both attempts so a failed
        commit cannot skip a later close and leak the handle (Bugbot 2026-07-21)."""
        if self._closed:
            return
        try:
            self._conn.commit()
        finally:
            try:
                self._conn.close()
            finally:
                self._closed = True
