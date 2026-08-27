"""OPTIONS FLOW — what was OBSERVABLE, and when. The record that makes absence interpretable.

THE PROBLEM THIS SOLVES. A gap in options history has at least three different causes and they
mean opposite things:

  1. NOT_SUBSCRIBED   — we never asked for this contract in this window. Silence says nothing
                        about the market; it is a hole in our coverage.
  2. SUBSCRIBED_NO_UPDATE — we were subscribed and the vendor sent nothing. Silence IS the
                        observation: nothing changed on that contract.
  3. SUBSCRIBED_BUT_DROPPED — we were subscribed, the vendor sent frames, and our own ingest
                        shed them under load (options_stream_ingest_health records this).

Without a coverage record, all three look identical in the frame table: no rows. A researcher
reading that history would treat our subscription ceiling as a market fact, which is the kind of
silent, months-long error the REST chain envelope loss already cost this repo once.

Contract selection is a CAPACITY POLICY, not the universe of interesting contracts. Because the
policy cannot subscribe everything at once, coverage is deliberately partial AND ROTATING, so
"which contracts were observable at time T" is a genuine question with a time-varying answer.
This module stores that answer.

WHAT IT IS NOT. It is not a market claim. Knowing a contract was subscribed says nothing about
dealer ownership, inventory sign, aggressor side, or opening/closing intent. Nothing here enters
Decide.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


class CoverageWriteError(Exception):
    """A durable coverage write did not land.

    Raised (not swallowed) by open_epochs/close_epochs so a caller advancing IN-MEMORY
    subscription state can gate that advance on the DURABLE record actually being written.
    A write that fails silently and returns 0 would let memory claim coverage the epoch table
    never recorded — the exact "memory advances while the coverage write fails" divergence this
    subsystem must not have. Callers that are legitimately best-effort (shutdown, startup
    reconcile) catch it explicitly; the reconciler does not, so it can decline to advance.
    """


COVERAGE_SQL = """
-- One row per (symbol, service) SUBSCRIPTION INTERVAL. ended_ms NULL means still open.
CREATE TABLE IF NOT EXISTS options_stream_coverage_epochs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT NOT NULL,        -- vendor option contract symbol, as subscribed
    underlying   TEXT,                 -- parsed root, for per-underlying coverage questions
    service      TEXT NOT NULL,        -- LEVELONE_OPTIONS | OPTIONS_BOOK
    started_ms   INTEGER NOT NULL,     -- epoch ms; same clock as options_stream_frames
    ended_ms     INTEGER,              -- epoch ms; NULL while the subscription is live
    policy_json  TEXT,                 -- the selection policy that chose it, for interpretability
    reason       TEXT                  -- why it started/ended (rotation, reconnect, shutdown)
);
CREATE INDEX IF NOT EXISTS idx_osce_symbol_time
    ON options_stream_coverage_epochs(symbol, started_ms);
CREATE INDEX IF NOT EXISTS idx_osce_underlying_time
    ON options_stream_coverage_epochs(underlying, started_ms);
CREATE INDEX IF NOT EXISTS idx_osce_open
    ON options_stream_coverage_epochs(ended_ms) WHERE ended_ms IS NULL;
"""


def ensure_coverage_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(COVERAGE_SQL)
    conn.commit()


def coverage_db_path(db_path: Path | str | None = None) -> Path:
    """Resolve the capture database, refusing the operational one (RC-6 law).

    Coverage epochs describe raw stream capture and live alongside the frames they explain, so
    they obey the same law: raw streams never touch ed_console.db
    (governance/CONSOLE_REBUILD_PLAN_CR_V1.md S4, BLOCKING). Keeping the epochs in the SAME
    database as the frames also matters for correctness — explain_absence joins coverage
    against frames and ingest health, and a cross-database join would silently return nothing.
    """
    if db_path is None:
        from stream_spine import STREAM_DB_DEFAULT
        db_path = STREAM_DB_DEFAULT
    p = Path(db_path).resolve()
    if p.name == "ed_console.db":
        raise ValueError(
            "options coverage must never write the operational DB (RC-6 law): "
            f"stream capture belongs in stream_capture.db, got {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def underlying_of(option_symbol: str) -> str | None:
    """Root from a vendor option symbol, e.g. 'SPY   260820C00767000' -> 'SPY'.

    Schwab pads the root to six characters. Parsing is deliberately conservative: an unexpected
    shape returns None rather than a guess, because a wrong root would silently mis-attribute a
    contract's coverage to another underlying.
    """
    if not isinstance(option_symbol, str) or len(option_symbol) < 7:
        return None
    root = option_symbol[:6].strip()
    return root or None


def open_epochs(db_path: Path | str, symbols: Iterable[str], *, service: str,
                policy: str | None = None, reason: str = "subscribe",
                at_ms: int | None = None) -> int:
    """Record that these symbols became observable on `service`. Returns rows written.

    Idempotent in the sense that matters: a symbol already carrying an OPEN epoch for the same
    service is not given a second one, so a reconnect that re-subscribes the same set does not
    manufacture duplicate coverage.
    """
    syms = [s for s in dict.fromkeys(symbols) if s]
    if not syms:
        return 0
    now = int(at_ms if at_ms is not None else time.time() * 1000.0)
    conn = sqlite3.connect(str(coverage_db_path(db_path)), timeout=30.0)
    try:
        ensure_coverage_schema(conn)
        existing = {r[0] for r in conn.execute(
            "SELECT symbol FROM options_stream_coverage_epochs "
            "WHERE service = ? AND ended_ms IS NULL", (service,))}
        rows = [(s, underlying_of(s), service, now, policy, reason)
                for s in syms if s not in existing]
        if rows:
            conn.executemany(
                "INSERT INTO options_stream_coverage_epochs "
                "(symbol, underlying, service, started_ms, policy_json, reason) "
                "VALUES (?,?,?,?,?,?)", rows)
            conn.commit()
        return len(rows)
    except sqlite3.Error as e:
        # DO NOT swallow-and-return-0. A caller that reads 0 as "nothing new to open" would then
        # mark the contract subscribed in memory with no durable epoch behind it. Signal the
        # failure so the caller can decline to advance.
        log.warning("coverage open_epochs failed: %s", e)
        raise CoverageWriteError(f"open_epochs({service}) failed: {e}") from e
    finally:
        conn.close()


def close_epochs(db_path: Path | str, symbols: Iterable[str] | None, *, service: str,
                 reason: str = "unsubscribe", at_ms: int | None = None) -> int:
    """Record that these symbols stopped being observable. `symbols=None` closes ALL open ones.

    Closing on shutdown matters: an epoch left open forever would claim we were watching a
    contract during a window when the process was not even running.
    """
    now = int(at_ms if at_ms is not None else time.time() * 1000.0)
    conn = sqlite3.connect(str(coverage_db_path(db_path)), timeout=30.0)
    try:
        ensure_coverage_schema(conn)
        if symbols is None:
            cur = conn.execute(
                "UPDATE options_stream_coverage_epochs SET ended_ms = ?, reason = ? "
                "WHERE service = ? AND ended_ms IS NULL", (now, reason, service))
        else:
            syms = [s for s in dict.fromkeys(symbols) if s]
            if not syms:
                return 0
            q = ",".join("?" * len(syms))
            cur = conn.execute(
                f"UPDATE options_stream_coverage_epochs SET ended_ms = ?, reason = ? "
                f"WHERE service = ? AND ended_ms IS NULL AND symbol IN ({q})",
                [now, reason, service, *syms])
        conn.commit()
        return cur.rowcount or 0
    except sqlite3.Error as e:
        # Same reasoning as open_epochs: a swallowed failure would let a caller drop the contract
        # from memory while its epoch is still open in the record — memory claiming LESS coverage
        # than the durable truth. Signal it; best-effort callers catch.
        log.warning("coverage close_epochs failed: %s", e)
        raise CoverageWriteError(f"close_epochs({service}) failed: {e}") from e
    finally:
        conn.close()


def _last_observed_ms(conn: sqlite3.Connection, symbol: str, service: str,
                      not_before_ms: int) -> int | None:
    """The receive-clock time of the LAST frame stored for this symbol on this service at or after
    the epoch's start. None when the epoch never produced a stored frame.

    This is the honest right-edge of an interrupted epoch: the last instant we can PROVE the
    contract was observable. Uses received_ts_ms (our clock, the same clock started_ms is stamped
    on), never frame_ts_ms (the vendor clock), so the closed interval is measured on one ruler.
    """
    try:
        row = conn.execute(
            "SELECT MAX(f.received_ts_ms) FROM options_stream_frames f "
            "JOIN options_stream_frame_symbols s ON s.frame_id = f.id "
            "WHERE s.symbol_key = ? AND f.service = ? AND f.received_ts_ms >= ?",
            (symbol, service, int(not_before_ms))).fetchone()
    except sqlite3.Error:
        # The frames/index tables may not exist yet (reconcile can run before any capture). A
        # missing observation trail is not an error here — it just means "no proof of observation".
        return None
    return int(row[0]) if row and row[0] is not None else None


def reconcile_open_epochs_on_start(db_path: Path | str, *, services: Iterable[str],
                                   at_ms: int | None = None,
                                   reason: str = "startup_reconcile_unclean_exit") -> dict[str, int]:
    """Close every epoch left OPEN by a prior process, at its LAST OBSERVED instant — NOT now.

    RESTART COVERAGE TRUTH, corrected. close_epochs runs on a CLEAN shutdown, but a crash or a
    kill (the daemon's own last result was a control-C exit code) leaves epochs open with no
    ended_ms. On the next start those stale epochs still answer was_subscribed()=True across the
    whole downtime gap.

    The FIRST fix closed them at the reconcile instant (`now`), which was itself a lie: an epoch
    that opened at 09:30, crashed at 15:00, and reconciled at 08:25 the next morning would be
    recorded as observed continuously for ~17 hours — the entire overnight downtime folded into
    coverage. That is the same "silence read as observation" error the whole module exists to
    prevent, just relocated to the restart boundary.

    So each orphaned epoch is closed at the receive-time of the LAST FRAME actually stored for
    that contract (the last instant observation is provable), or — if the epoch produced no stored
    frame at all — at its own started_ms, a zero-width interval that claims nothing. Never at a
    time past the last real observation. `at_ms`, when given, is only an upper CAP (a frame clock
    that somehow ran ahead of the reconcile instant cannot push coverage into the future). It is
    idempotent: a clean prior shutdown left nothing open, so this closes zero.
    """
    cap = int(at_ms if at_ms is not None else time.time() * 1000.0)
    out: dict[str, int] = {s: 0 for s in services}
    conn = sqlite3.connect(str(coverage_db_path(db_path)), timeout=30.0)
    try:
        ensure_coverage_schema(conn)
        for service in services:
            try:
                open_rows = conn.execute(
                    "SELECT id, symbol, started_ms FROM options_stream_coverage_epochs "
                    "WHERE service = ? AND ended_ms IS NULL", (service,)).fetchall()
            except sqlite3.Error as e:
                log.warning("reconcile: could not read open epochs for %s: %s", service, e)
                continue
            for eid, symbol, started_ms in open_rows:
                last = _last_observed_ms(conn, symbol, service, started_ms)
                ended = last if last is not None else int(started_ms)
                if ended < int(started_ms):
                    ended = int(started_ms)
                if ended > cap:
                    ended = cap
                try:
                    conn.execute(
                        "UPDATE options_stream_coverage_epochs SET ended_ms = ?, reason = ? "
                        "WHERE id = ?", (ended, reason, eid))
                    out[service] += 1
                except sqlite3.Error as e:
                    log.warning("reconcile: could not close epoch %s (%s): %s", eid, symbol, e)
            conn.commit()
    finally:
        conn.close()
    return out


def was_subscribed(db_path: Path | str, symbol: str, at_ms: int, *,
                   service: str = "LEVELONE_OPTIONS") -> bool:
    """Was `symbol` observable on `service` at `at_ms`? The question replay must ask first."""
    conn = sqlite3.connect(f"file:{coverage_db_path(db_path)}?mode=ro", uri=True, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT 1 FROM options_stream_coverage_epochs WHERE symbol = ? AND service = ? "
            "AND started_ms <= ? AND (ended_ms IS NULL OR ended_ms >= ?) LIMIT 1",
            (symbol, service, int(at_ms), int(at_ms))).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def coverage_at(db_path: Path | str, at_ms: int, *,
                service: str = "LEVELONE_OPTIONS") -> dict[str, Any]:
    """Everything observable at an instant, grouped by underlying.

    This is what makes 'no underlying silently starved' checkable rather than asserted: a
    reader can ask what each underlying's depth actually was at any past moment.
    """
    conn = sqlite3.connect(f"file:{coverage_db_path(db_path)}?mode=ro", uri=True, timeout=30.0)
    try:
        rows = conn.execute(
            "SELECT symbol, underlying FROM options_stream_coverage_epochs "
            "WHERE service = ? AND started_ms <= ? AND (ended_ms IS NULL OR ended_ms >= ?)",
            (service, int(at_ms), int(at_ms))).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    by_und: dict[str, list[str]] = {}
    for sym, und in rows:
        by_und.setdefault(und or "?", []).append(sym)
    return {
        "at_ms": int(at_ms), "service": service,
        "contracts": len(rows),
        "underlyings": len(by_und),
        "per_underlying": {k: len(v) for k, v in sorted(by_und.items())},
        "symbols_by_underlying": {k: sorted(v) for k, v in sorted(by_und.items())},
    }


def explain_absence(db_path: Path | str, symbol: str, at_ms: int, *,
                    service: str = "LEVELONE_OPTIONS",
                    window_ms: int = 60_000) -> dict[str, Any]:
    """Why is there no observation for `symbol` at `at_ms`? Give the REASON, not just the gap.

    Returns one of:
      NOT_SUBSCRIBED        — outside every coverage epoch; our hole, not the market's.
      OBSERVED              — a frame exists in the window.
      SUBSCRIBED_NO_UPDATE  — covered, no frame, and ingest reported no drops in the window:
                              the vendor genuinely sent nothing.
      SUBSCRIBED_MAYBE_DROPPED — covered, no frame, but ingest DID drop frames in the window,
                              so silence cannot be attributed to the vendor. Stated as MAYBE
                              on purpose: drop counters are per-process totals, not per-symbol,
                              so this window cannot prove THIS symbol was the one shed.
    """
    if not was_subscribed(db_path, symbol, at_ms, service=service):
        return {"verdict": "NOT_SUBSCRIBED", "symbol": symbol, "at_ms": at_ms,
                "meaning": "no coverage epoch contains this instant; silence is our gap, "
                           "not a market observation"}
    lo, hi = int(at_ms) - int(window_ms), int(at_ms) + int(window_ms)
    conn = sqlite3.connect(f"file:{coverage_db_path(db_path)}?mode=ro", uri=True, timeout=30.0)
    try:
        seen = conn.execute(
            "SELECT COUNT(*) FROM options_stream_frame_symbols s "
            "JOIN options_stream_frames f ON f.id = s.frame_id "
            "WHERE s.symbol_key = ? AND f.service = ? AND f.frame_ts_ms BETWEEN ? AND ?",
            (symbol, service, lo, hi)).fetchone()[0]
        dropped = conn.execute(
            "SELECT COALESCE(SUM(dropped),0) FROM options_stream_ingest_health "
            "WHERE window_end_ms >= ? AND window_start_ms <= ?", (lo, hi)).fetchone()[0]
    except sqlite3.Error:
        seen, dropped = 0, 0
    finally:
        conn.close()
    if seen:
        return {"verdict": "OBSERVED", "symbol": symbol, "at_ms": at_ms, "frames": int(seen)}
    if dropped:
        return {"verdict": "SUBSCRIBED_MAYBE_DROPPED", "symbol": symbol, "at_ms": at_ms,
                "dropped_in_window": int(dropped),
                "meaning": "covered and no frame stored, but ingest shed frames in this window; "
                           "drop counters are per-process, so this symbol cannot be singled out"}
    return {"verdict": "SUBSCRIBED_NO_UPDATE", "symbol": symbol, "at_ms": at_ms,
            "meaning": "covered, ingest lost nothing: the vendor sent no update — silence IS "
                       "the observation"}
