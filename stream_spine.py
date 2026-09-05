"""CR-01 streaming spine: topic bus + last-value cache + capture writer + feed health.

Consensus plan v1.2 (governance/CONSOLE_REBUILD_PLAN_CR_V1.md §4). Laws encoded here:
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
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STREAM_DB_DEFAULT = Path(__file__).resolve().parent / "data" / "stream_capture.db"

#: env var name for resolve_stream_db_path's cross-checkout override.
STREAM_CAPTURE_DB_PATH_ENV = "STREAM_CAPTURE_DB_PATH"


def resolve_stream_db_path(default: "Path | str | None" = None) -> Path:
    """THE ONE canonical stream-capture DB path authority every producer and
    consumer (tools/run_stream_capture.py's CaptureWriter,
    app/options/order_flow/streaming.py's feed-loop reader) resolves through.

    PR214_RTH_DEFECT_REMEDIATION_V1 (2026-08-31 RTH proof): STREAM_DB_DEFAULT alone
    is checkout-relative with no cross-process override -- a daemon launched with
    `--db` against one checkout's file and a server defaulting to a DIFFERENT
    checkout's own STREAM_DB_DEFAULT both reported healthy (real data flowing,
    real subscriptions RUNNING) while structurally disconnected: the API served a
    truthful `no_book` because the two processes were never reading the same file.
    Same override shape config.py already uses for SCHWAB_TOKEN_PATH.

    `STREAM_CAPTURE_DB_PATH`, when set, is checked FIRST and resolved to an
    ABSOLUTE path — never used relative, since a relative override could mean two
    different absolute files under two different processes' working directories,
    silently reproducing the exact defect this closes. Only when unset does this
    fall back to `default` (a caller's own, possibly test-monkeypatched, module
    constant) or STREAM_DB_DEFAULT. Called fresh on every use, never bound as a
    function/class default-argument value (which freezes at import/definition
    time and can never see a later env var or monkeypatch)."""
    override = os.environ.get(STREAM_CAPTURE_DB_PATH_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if default is not None:
        return Path(default).resolve()
    return STREAM_DB_DEFAULT.resolve()

def default_active_ticker_signal_path(db_path: Path | str | None = None) -> Path:
    """Ticker signal beside the resolved stream DB, not the checkout.

    Same split-brain class as the owner lock: a worktree daemon and a production
    server otherwise write two files and the live StreamClient never sees the
    contract the UI requested. Called fresh each time — never bound as a
    function default (that freezes at import and misses STREAM_CAPTURE_DB_PATH).
    """
    return resolve_stream_db_path(db_path).with_name("stream_active_ticker.json")


def default_active_option_contract_signal_path(db_path: Path | str | None = None) -> Path:
    """Option-contract signal beside the resolved stream DB, not the checkout."""
    return resolve_stream_db_path(db_path).with_name("stream_active_option_contract.json")


#: Checkout-relative names kept for tests that monkeypatch the constant. Production
#: readers/writers resolve through default_active_*_signal_path() at call time.
ACTIVE_TICKER_SIGNAL_DEFAULT = Path(__file__).resolve().parent / "data" / "stream_active_ticker.json"
ACTIVE_OPTION_CONTRACT_SIGNAL_DEFAULT = Path(__file__).resolve().parent / "data" / "stream_active_option_contract.json"

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
-- a market fact. Options streaming watches at most ONE contract at a time (bounded by
-- construction, see _apply_active_option_contract_subs), so this is a single open-interval
-- ledger per (symbol, service), not the historical branch's multi-contract rotation
-- policy — that complexity does not apply to this design.
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
CREATE TABLE IF NOT EXISTS stream_producer_heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    daemon_pid INTEGER,
    heartbeat_ts REAL NOT NULL,
    resolved_db_path TEXT NOT NULL,
    claimed_coverage_json TEXT
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
            "SELECT daemon_pid, heartbeat_ts, resolved_db_path, claimed_coverage_json "
            "FROM stream_producer_heartbeat WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    try:
        claimed = json.loads(row[3]) if row[3] else None
    except (TypeError, ValueError):
        claimed = None      # unparseable claim is UNKNOWN, never confirmation
    return {"daemon_pid": row[0], "heartbeat_ts": row[1], "resolved_db_path": row[2],
            "claimed_coverage": claimed}


def read_open_coverage_symbols(conn: sqlite3.Connection,
                               services: "tuple[str, ...]", *,
                               stale_sec: float,
                               now: "float | None" = None) -> "dict[str, str | None]":
    """PRODUCER-SIDE subscription identity, read from THIS connection's own
    stream_capture.db (PR214 premerge gap 1A).

    The active-contract SIGNAL FILE is DESIRED state -- what the server asked for. The
    OPEN COVERAGE EPOCH is PRODUCER state -- what the daemon actually holds a vendor
    subscription for, written only after a confirmed subscribe. Between an operator's
    request for B and the daemon's next poll, those disagree, and a health verdict built
    on desired state alone would claim B is live while the producer still physically
    holds A.

    Returns {service: symbol or None}:
      0 open rows -> None (not subscribed, as far as the durable ledger knows)
      1 open row  -> that symbol (the only confirming case)
      2+ open rows -> None, AMBIGUOUS -- explicitly NOT confirmed

    A missing table or unreadable DB likewise yields None for every service: unknown is
    never confirmation.

    The ambiguous case must never be resolved by picking a row. An earlier version used
    `ORDER BY id DESC LIMIT 1`, which silently answered "B" whenever a contradictory
    A-open/B-open pair existed -- newest-row-wins, i.e. inventing a confident producer
    identity out of a ledger that cannot support one, and greening health on it. The
    CaptureWriter service-wide uniqueness guard makes that state unreachable through the
    normal path; this reader still fails closed so a corrupted or hand-edited ledger
    cannot be laundered into a confident answer here.

    AN OPEN ROW IS NOT BY ITSELF A CLAIM (PR214 durable producer truth). `ended_ts IS
    NULL` used to be sufficient, and it lied: when a durable CLOSE fails, the row stays
    open for an epoch the daemon has ALREADY KNOWINGLY SURRENDERED, so this reader
    answered with a contract the vendor was no longer subscribed to and the UI rendered it
    as "subscribed". Measured at that shape, the state was re-entrant -- every tick the
    daemon subscribed, was refused a durable epoch, and unsubscribed again, capturing
    nothing, while this function kept naming the contract.

    A row therefore confirms only when the LIVE producer currently asserts that exact
    epoch id, via `claimed_coverage` on its heartbeat. That closes both directions of the
    failure:
      * daemon alive, close failed -> it republishes the claim immediately (the surrendered
        id is gone from it), so this returns None even though the row is still open;
      * daemon cannot write at all -> the heartbeat itself goes stale past `stale_sec`,
        and a stale producer confirms nothing.
    A durable-write failure can therefore make producer identity UNKNOWN. It can no longer
    manufacture a false positive.

    `stale_sec` is required, not defaulted: there is no correct "ungated" read of this
    table, and an optional gate is one a caller can forget."""
    out: "dict[str, str | None]" = {s: None for s in services}
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
            return {s: None for s in services}
        if len(rows) != 1:
            continue            # 0 -> not subscribed; 2+ -> ambiguous, never confirmed
        claimed_id = claimed.get(service)
        if isinstance(claimed_id, bool) or not isinstance(claimed_id, int):
            continue            # no live claim for this service (surrendered, or unknown)
        if claimed_id == rows[0][0]:
            out[service] = rows[0][1]
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


def _read_json_signal(value_key: str, *, path: Path) -> str | None:
    """Shared read: None on any absence/corruption — a missing signal means 'no
    subscription', never a guessed value."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = str(data.get(value_key) or "").upper().strip()
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
        # PR214_RTH_DEFECT_REMEDIATION_V1: `db_path: Path | str = STREAM_DB_DEFAULT`
        # was a default-argument value, evaluated ONCE at class-definition time
        # (import time) -- it could never see a later STREAM_CAPTURE_DB_PATH env
        # var. `None` is the sentinel; an explicit `db_path` (e.g. a test's
        # tmp_path, or the daemon's --db flag) still bypasses the resolver
        # entirely, exactly as before -- only the "no explicit path given" case
        # now goes through the one canonical, env-var-aware resolver.
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
            self._conn.commit()
        except Exception:
            # Init failed after connect — close before the object is discarded so the
            # SQLite handle cannot leak until GC (Bugbot 2026-07-21 HIGH).
            self._conn.close()
            self._closed = True
            raise

    def insert(self, topic: str, msg: dict) -> None:
        kind = topic.split(".", 1)[0]
        if kind == "quote":
            native = msg.get("native")
            self._conn.execute(
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
            self._conn.execute(
                "INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,src) "
                "VALUES(?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("service"),
                 json.dumps(content),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on book_msg (no default); same guard as the quote branch above
        elif kind == "optquote":
            content = msg.get("content")
            if content is None:
                return
            self._conn.execute(
                "INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,src) "
                "VALUES(?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), json.dumps(content),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on options_quote_msg (no default); same guard as the quote branch above
        elif kind == "print":
            self._conn.execute(
                "INSERT INTO stream_prints_raw(ts_recv,symbol,price,size,exchange,conditions,"
                "trade_ts_ms,src) VALUES(?,?,?,?,?,?,?,?)",
                (msg.get("ts_recv"), msg.get("symbol"), msg.get("price"), msg.get("size"),
                 msg.get("exchange"), msg.get("conditions"), msg.get("trade_ts_ms"),
                 msg.get("src", "?")))  # caps-ok: src is a required kwarg on print_msg (no default); same guard as the quote branch above
        elif kind == "bar1m":
            self._conn.execute(
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

    #: Services this architecture subscribes for AT MOST ONE contract at a time (see
    #: tools/run_stream_capture.py::_apply_active_option_contract_subs and
    #: stream_spine.ACTIVE_OPTION_CONTRACT_SIGNAL_DEFAULT — one active option contract,
    #: by design, not by accident). For these, "one open epoch per (symbol, service)" is
    #: too weak: A and B are different symbols, so a switch whose close failed could open
    #: B while A was still open, leaving TWO open epochs on one service. Since these
    #: epochs are also read as PRODUCER SUBSCRIPTION IDENTITY, that state is not merely
    #: untidy — it makes "what is this service subscribed to" unanswerable. Scoped
    #: deliberately to the two canonical option services; equity/book services subscribe
    #: many symbols concurrently and are NOT covered by this stricter rule.
    SINGLE_CONTRACT_SERVICES: frozenset[str] = frozenset({"LEVELONE_OPTIONS", "OPTIONS_BOOK"})

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
                        claimed_coverage: "dict[str, int | None] | None" = None) -> None:
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
        try:
            self._conn.execute(
                "INSERT INTO stream_producer_heartbeat(id, daemon_pid, heartbeat_ts, "
                "resolved_db_path, claimed_coverage_json) "
                "VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET daemon_pid=excluded.daemon_pid, "
                "heartbeat_ts=excluded.heartbeat_ts, resolved_db_path=excluded.resolved_db_path, "
                "claimed_coverage_json=excluded.claimed_coverage_json",
                (p, t, str(self.db_path), claim))
            self._conn.commit()
        except Exception as e:
            raise CoverageWriteError(f"write_heartbeat: {e}") from e
        # Only a LANDED write changes the outstanding lease. A publication that claims
        # nothing clears it; one that names any epoch starts a fresh one at `t`.
        self._positive_claim_ts = t if (
            claimed_coverage and any(v is not None for v in claimed_coverage.values())
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

    def _insert_guarded(self, topic: str, msg: Any) -> int:
        """1 if a row landed; insert failures are COUNTED, never kill the writer
        (Cursor review MEDIUM: an uncaught insert() death silently stopped capture)."""
        try:
            before = self.rows_written
            self.insert(topic, msg)
            return self.rows_written - before
        except Exception:  # noqa: BLE001 — counted + surfaced in status; capture continues
            self.insert_errors += 1
            return 0

    async def run(self, sub: Subscription, *, stop: asyncio.Event) -> None:
        pending = 0
        last_commit = time.monotonic()
        while not stop.is_set():
            timeout = max(self.batch_sec - (time.monotonic() - last_commit), 0.01)
            try:
                topic, msg = await asyncio.wait_for(sub.get(), timeout=timeout)
                pending += self._insert_guarded(topic, msg)
            except asyncio.TimeoutError:
                pass
            if pending and (pending >= self.batch_rows
                            or time.monotonic() - last_commit >= self.batch_sec):
                self.commit()
                pending = 0
                last_commit = time.monotonic()
        # DRAIN on stop — Cursor review HIGH: stopping must not vaporize up to a full
        # queue of buffered rows. Everything already delivered to the subscription is
        # written and committed before the writer exits.
        while not sub.queue.empty():
            topic, msg = await sub.get()
            pending += self._insert_guarded(topic, msg)
        if pending:
            self.commit()

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
