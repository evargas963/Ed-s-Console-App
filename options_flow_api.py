"""OPTIONS FLOW — the read API. Native observations, with their provenance and their age.

WHAT THIS SERVES, and what it refuses to serve. Every value returned here is a NATIVE field the
vendor sent, read back out of retained raw frames. Nothing is derived, modelled, smoothed or
inferred: no greeks are recomputed, no dealer ownership or inventory sign is attributed, no
aggressor side or opening/closing intent is guessed, and nothing produced here is eligible to
enter Decide.

WHY EVERY VALUE CARRIES A TIMESTAMP AND AN AGE. LEVELONE_OPTIONS is a DELTA service (measured:
content entries of 55, 23, 17, 17, 17 and 11 fields, with only ten names common to all). State at
an instant is therefore FOLDED from earlier frames, which means a field's value and the moment it
was last observed are genuinely different facts. Returning the value alone would let a consumer
read a forty-minute-old GAMMA as current. Age is not decoration here; it is the difference
between an honest reading and a misleading one.

WHY EMPTINESS IS EXPLAINED RATHER THAN RETURNED BARE. Options collection is OFF unless the
operator enables it, contract coverage is bounded by Schwab's key budget, and a covered contract
can simply have no updates. Those are three different reasons for "no data" and they mean opposite
things, so this API always says WHICH. A UI that cannot tell "we were not watching" from "the
market was quiet" will eventually present our own coverage limit as a market fact.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Fields that identify the frame rather than describing the instrument. Surfaced separately so a
#: consumer never counts them as market observations.
_METADATA = frozenset({"key", "delayed", "assetMainType", "cusip"})


def _capture_db() -> Path:
    from stream_spine import STREAM_DB_DEFAULT
    return Path(STREAM_DB_DEFAULT)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    except sqlite3.Error:
        return False


def collection_status() -> dict[str, Any]:
    """Is options collection running, what is covered, and is retention keeping up?

    Deliberately answers "is this surface trustworthy right now" rather than only "here is some
    data". A UI needs the first question answered before it renders the second.
    """
    out: dict[str, Any] = {
        "enabled": False, "reason": None, "capture_db": str(_capture_db()),
        "coverage": None, "ingest": None, "frames": None,
        "semantics": {
            "LEVELONE_OPTIONS": "DELTA — later frames carry only changed fields; state is folded",
            "OPTIONS_BOOK": "FULL_REPLACEMENT — the latest frame is the state; never merged",
        },
    }
    try:
        from options_stream_collect import options_stream_status
        st = options_stream_status()
        out["enabled"] = bool(st.get("enabled"))
        out["ingest"] = st.get("ingest")
        out["subscribed_contracts"] = st.get("subscribed_contracts")
        if not out["enabled"]:
            out["reason"] = ("options collection is DISABLED (ED_OPTIONS_STREAM unset). No frames "
                             "are being retained; any empty result below is OUR gap, not a "
                             "market observation.")
    except Exception as e:                              # noqa: BLE001
        out["reason"] = f"stream module unavailable: {e}"

    db = _capture_db()
    if not db.is_file():
        out["reason"] = out["reason"] or "no capture database yet — nothing has been collected"
        return out
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15.0)
    except sqlite3.Error as e:
        out["reason"] = f"capture db unreadable: {e}"
        return out
    try:
        if _table_exists(conn, "options_stream_frames"):
            row = conn.execute(
                "SELECT service, COUNT(*), MIN(frame_ts_ms), MAX(frame_ts_ms), "
                "       MAX(ingest_lag_ms), SUM(n_contracts) "
                "FROM options_stream_frames GROUP BY service").fetchall()
            out["frames"] = [
                {"service": r[0], "frames": r[1], "first_ts_ms": r[2], "last_ts_ms": r[3],
                 "max_ingest_lag_ms": r[4], "contract_rows": r[5]} for r in row]
        if _table_exists(conn, "options_stream_coverage_epochs"):
            now = int(time.time() * 1000.0)
            cov = conn.execute(
                "SELECT service, COUNT(DISTINCT symbol), COUNT(DISTINCT underlying) "
                "FROM options_stream_coverage_epochs "
                "WHERE started_ms <= ? AND (ended_ms IS NULL OR ended_ms >= ?) GROUP BY service",
                (now, now)).fetchall()
            out["coverage"] = [{"service": r[0], "contracts": r[1], "underlyings": r[2]}
                               for r in cov]
    finally:
        conn.close()
    return out


def observable_contracts(at_ms: int | None = None, underlying: str | None = None,
                         service: str = "LEVELONE_OPTIONS") -> dict[str, Any]:
    """What was observable at an instant, by underlying — the answer to 'did anything starve?'"""
    from calibration.options_stream_coverage import coverage_at
    at = int(at_ms if at_ms is not None else time.time() * 1000.0)  # caps-ok: as-of QUERY PARAMETER, not a Schwab leaf; unspecified means "the current instant", this endpoint's documented semantic, so no measurement is being replaced
    db = _capture_db()
    if not db.is_file():
        return {"at_ms": at, "contracts": 0, "underlyings": 0, "per_underlying": {},
                "note": "no capture database — nothing has been collected yet"}
    out = coverage_at(db, at, service=service)
    if underlying:
        u = str(underlying).upper()
        syms = out.get("symbols_by_underlying", {}).get(u, [])  # caps-ok: indexes a dict this call just built; an underlying with no symbols HAS none, and the empty list is reported as NOT SUBSCRIBED four lines down rather than passed off as data
        out = {"at_ms": at, "service": service, "underlying": u,
               "contracts": len(syms), "symbols": syms}
        if not syms:
            out["note"] = (f"{u} was NOT SUBSCRIBED at this instant — this is a coverage gap, "
                           f"not a statement that {u} options were quiet")
    return out


def contract_state(symbol: str, as_of_ms: int | None = None,
                   include_metadata: bool = False) -> dict[str, Any]:
    """Native LEVELONE_OPTIONS state for one contract at an instant, folded causally.

    Values are separated from their observation times so a stale field cannot be mistaken for a
    fresh one, and service metadata is split out of the market fields entirely.
    """
    from calibration.options_stream_replay import level_one_state_as_of
    at = int(as_of_ms if as_of_ms is not None else time.time() * 1000.0)  # caps-ok: as-of QUERY PARAMETER, not a Schwab leaf; unspecified means "the current instant", this endpoint's documented semantic, so no measurement is being replaced
    db = _capture_db()
    if not db.is_file():
        return {"symbol": symbol, "as_of_ms": at, "coverage": "NO_CAPTURE_DB",
                "fields": {}, "note": "nothing has been collected yet"}

    st = level_one_state_as_of(db, symbol, at)
    fields, meta = {}, {}
    for name, rec in (st.get("fields") or {}).items():
        target = meta if rec.get("is_service_metadata") else fields
        target[name] = {"value": rec.get("value"),
                        "observed_ts_ms": rec.get("observed_ts_ms"),
                        "age_ms": rec.get("age_ms")}
    out: dict[str, Any] = {
        "symbol": symbol, "as_of_ms": at, "coverage": st.get("coverage"),
        "service": "LEVELONE_OPTIONS",
        "semantics": "DELTA — state is folded from earlier frames; each field carries the "
                     "instant it was last observed and is NOT necessarily fresh",
        "fields": fields, "field_count": len(fields),
        # A counter that was never reported is not a measured zero: every neighbouring
        # age field already passes absence through, and "0 frames folded" is a claim
        # about the stream that nothing measured.
        "frames_folded": st.get("frames_folded"),
        "max_field_age_ms": st.get("max_field_age_ms"),
        "min_field_age_ms": st.get("min_field_age_ms"),
        "notes": st.get("notes") or [],
    }
    if include_metadata:
        out["service_metadata"] = meta
    if st.get("coverage") == "NOT_SUBSCRIBED":
        out["note"] = ("this contract was not subscribed at that instant — the empty result is "
                       "our coverage gap, not an observation about the market")
    return out


def contract_book(symbol: str, as_of_ms: int | None = None) -> dict[str, Any]:
    """Native OPTIONS_BOOK state at an instant. The latest frame, never a merge."""
    from calibration.options_stream_replay import book_state_as_of
    at = int(as_of_ms if as_of_ms is not None else time.time() * 1000.0)  # caps-ok: as-of QUERY PARAMETER, not a Schwab leaf; unspecified means "the current instant", this endpoint's documented semantic, so no measurement is being replaced
    db = _capture_db()
    if not db.is_file():
        return {"symbol": symbol, "as_of_ms": at, "coverage": "NO_CAPTURE_DB", "book": None,
                "note": "nothing has been collected yet"}
    return book_state_as_of(db, symbol, at)


def explain_gap(symbol: str, at_ms: int | None = None,
                service: str = "LEVELONE_OPTIONS", window_ms: int = 60_000) -> dict[str, Any]:
    """Why is there no observation here? NOT_SUBSCRIBED / NO_UPDATE / MAYBE_DROPPED / OBSERVED."""
    from calibration.options_stream_coverage import explain_absence
    at = int(at_ms if at_ms is not None else time.time() * 1000.0)  # caps-ok: as-of QUERY PARAMETER, not a Schwab leaf; unspecified means "the current instant", this endpoint's documented semantic, so no measurement is being replaced
    db = _capture_db()
    if not db.is_file():
        return {"verdict": "NO_CAPTURE_DB", "symbol": symbol, "at_ms": at,
                "meaning": "nothing has been collected yet"}
    return explain_absence(db, symbol, at, service=service, window_ms=window_ms)
