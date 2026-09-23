"""Last-valid GEX cells: the per-cell memory of the most recent VALID gamma-exposure value, so a
cell whose live input goes briefly missing is back-filled with its last real value (labelled
as such) instead of blanking, plus its DB persistence (hydrate at first use, floor-limited
flush) and the per-ticker error channel. Extracted from server.py (RC-REHAB-1, 2026-09-23,
forty-eighth slice).
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)


#: Operator directive (2026-09-15, canonical input-validity rules): "If current inputs are
#: invalid, display the latest valid timestamped snapshot for that cell. Show — only if no
#: valid current or historical snapshot exists... current vendor failure must not erase
#: previously valid data." Per (ticker, strike, expiry) last-known-VALID gex/dex/vanna.
#:
#: MUST survive a process restart (operator directive, 2026-09-15, second pass): this
#: in-memory dict is a WRITE-THROUGH CACHE of the gamma_surface_last_valid table below, in
#: the SAME database file (get_db().db_path) option_chain_accrual (RC-159) already uses for
#: exactly this class of problem (durable, always-latest, per-ticker banked observations) --
#: not a second, disconnected persistence authority.
#:
#: Schema + read/write owned by db.EdDB (operator directive, 2026-09-15, DB ownership review,
#: FOURTH pass): first placed in calibration/option_chain_morning_full.py (wrong module -- that
#: file's docstring scopes it to once-per-day morning full-chain persistence, a calibration/
#: forward-collection concern), then moved to server.py directly (also wrong: server.py owning
#: its own raw sqlite3 connections and CREATE TABLE duplicates db.py's actual job -- EdDB is
#: "the main database interface for Ed Console" and every other table's schema/migration lives
#: there, in ONE place, using ONE connection-configuration convention). The table and its
#: load_gamma_surface_last_valid/persist_gamma_surface_last_valid methods now live in db.py
#: beside every other table; server.py only calls get_db().load_gamma_surface_last_valid(...)/
#: get_db().persist_gamma_surface_last_valid(...), the same way it calls every other DB read/
#: write. This module still owns the RUNTIME (in-memory, per-process) side of the checkpoint --
#: the write-through cache below, the lock discipline guarding it, and when to hydrate/flush --
#: because that IS a server.py concern (what the live heatmap shows this cycle); only the
#: durable storage itself moved.
#:
#: LOCK DISCIPLINE (operator directive, 2026-09-15): the first draft of this held
#: _LAST_VALID_GEX_CELLS_LOCK across the actual blocking SQLite I/O on the write side -- a
#: real anti-pattern regardless of any specific incident: that lock is shared across EVERY
#: ticker's terrain cycle and EVERY eager stream refresh, so one slow/contended write could
#: stall all of them simultaneously. Independent git review (2026-09-15) correctly rejected an
#: earlier claim that this defect explained a SPECIFIC previously-observed console hang: the
#: process that hung was running a commit that predates this table's existence entirely, so
#: this code cannot have caused that incident -- that causal claim is withdrawn, and the
#: incident's real cause remains unknown. This lock restructuring stands on its own merits as
#: a correct fix to a genuine bug (a shared lock must never be held across blocking disk I/O),
#: not as an explanation for any specific past symptom. The lock now only ever guards the
#: in-memory dict; the DB read (hydrate) and DB write (flush) both happen with the lock
#: released, and their own connect timeouts are short (db.EdDB.GAMMA_LAST_VALID_DB_TIMEOUT_SEC)
#: so a genuinely stuck DB fails this best-effort checkpoint fast rather than blocking anything.
#:
#: OBSERVABILITY (operator directive, 2026-09-15, THIRD pass): "Database hydrate/flush
#: failures must be observable and fail honestly; they may not be swallowed at debug level
#: while the product implies restart durability." Every failure is logged at WARNING and
#: recorded in _LAST_VALID_GEX_CELLS_ERRORS (surfaced by /api/build) -- restart durability
#: degrading to in-memory-only-this-session is now a visible, queryable fact, never a silent
#: one, while still never blocking or failing the live gamma-surface response itself (a
#: display-durability checkpoint is not allowed to become a new way to break serving data).
_LAST_VALID_GEX_CELLS: dict[str, dict[tuple[float, str], dict]] = {}
_LAST_VALID_GEX_CELLS_LOCK = threading.Lock()
_LAST_VALID_GEX_CELLS_HYDRATED: set[str] = set()
_LAST_VALID_GEX_CELLS_DB_WRITE_TS: dict[str, float] = {}
_LAST_VALID_GEX_CELLS_ERRORS: dict[str, dict] = {}
GAMMA_LAST_VALID_DB_WRITE_FLOOR_SEC = 20.0


def _record_last_valid_gex_error(tk: str, op: str, exc: Exception) -> None:
    log.warning("gamma-surface last-valid DB %s failed for %s: %s", op, tk, exc)
    _LAST_VALID_GEX_CELLS_ERRORS[tk] = {
        "op": op, "error": f"{type(exc).__name__}: {exc}", "ts_utc": time.time(),
    }


def _clear_last_valid_gex_error(tk: str, op: str) -> None:
    """Independent review, 2026-09-16: a ticker's /api/build persistence-error entry is meant
    to disclose an UNRESOLVED problem, not a permanent scar -- a later successful hydrate/flush
    for the SAME ticker must clear it, or the endpoint keeps reporting a since-recovered
    failure as if it were still current (MEASURED live: a TSLA flush failed on
    'database is locked', a later flush succeeded and persisted newer rows, and the error
    entry never cleared). Historical observability is retained by the WARNING log line
    _record_last_valid_gex_error already wrote at failure time (permanent in the log, unlike
    this in-memory active-state dict) plus the INFO line logged here on recovery -- this
    function only ever REMOVES a matching active entry, never fabricates or backdates one."""
    if _LAST_VALID_GEX_CELLS_ERRORS.pop(tk, None) is not None:
        log.info("gamma-surface last-valid DB %s recovered for %s -- clearing active error", op, tk)


def _hydrate_last_valid_gex_cells(tk: str) -> dict[tuple[float, str], dict]:
    """Lazily rehydrates `tk`'s durable snapshot from the DB exactly once per process
    lifetime. Acquires _LAST_VALID_GEX_CELLS_LOCK only for the cheap in-memory bookkeeping;
    the DB read itself runs with NO lock held (see LOCK DISCIPLINE above) -- a slow/stuck read
    degrades to "this ticker starts cold this process" (logged, recorded, never silent),
    never to blocking every other ticker's gamma-surface path."""
    import server as _srv

    with _LAST_VALID_GEX_CELLS_LOCK:
        if tk in _LAST_VALID_GEX_CELLS_HYDRATED:
            return _LAST_VALID_GEX_CELLS.setdefault(tk, {})
    try:
        loaded = _srv.get_db().load_gamma_surface_last_valid(tk)
        _clear_last_valid_gex_error(tk, "hydrate")
    except Exception as e:
        _record_last_valid_gex_error(tk, "hydrate", e)
        loaded = {}
    with _LAST_VALID_GEX_CELLS_LOCK:
        store = _LAST_VALID_GEX_CELLS.setdefault(tk, {})
        for key, val in loaded.items():
            store.setdefault(key, val)   # a same-process value (should not exist yet) always wins
        _LAST_VALID_GEX_CELLS_HYDRATED.add(tk)
        return store


def _flush_last_valid_gex_cells_to_db(tk: str) -> None:
    """Throttled durability checkpoint -- the in-memory store is already the live source of
    truth for this process; this only makes sure a LATER restart does not lose it. Snapshots
    the store and updates the throttle timestamp under the lock (cheap), then performs the
    actual DB write with NO lock held (see LOCK DISCIPLINE above)."""
    import server as _srv

    now = time.time()
    with _LAST_VALID_GEX_CELLS_LOCK:
        last = _LAST_VALID_GEX_CELLS_DB_WRITE_TS.get(tk, 0.0)
        if now - last < GAMMA_LAST_VALID_DB_WRITE_FLOOR_SEC:
            return
        _LAST_VALID_GEX_CELLS_DB_WRITE_TS[tk] = now
        store_snapshot = dict(_LAST_VALID_GEX_CELLS.get(tk) or {})
    cells = [
        {"strike": k[0], "expiry": k[1], "gex": v["gex"], "dex": v["dex"], "vanna": v["vanna"],
         "captured_ts_utc": v["captured_ts_utc"]}
        for k, v in store_snapshot.items()
    ]
    try:
        _srv.get_db().persist_gamma_surface_last_valid(ticker=tk, cells=cells)
        _clear_last_valid_gex_error(tk, "flush")
    except Exception as e:
        _record_last_valid_gex_error(tk, "flush", e)


def _backfill_gex_cells_from_last_valid(tk: str, surface: dict) -> None:
    """Canonical input-validity/data-authority fix (operator directive, 2026-09-15) -- the
    ONE place a cell's gex/dex/vanna falls back to its last known valid snapshot instead of
    a bare None, so the endpoint/heatmap never has to special-case this per-ticker (SPX
    included) or in the presentation layer. Mutates `surface["cells"]` in place, then
    recomputes `surface`'s own gamma_available/cells_with_data/gamma_unavailable_reason so a
    ticker whose CURRENT cycle has zero valid cells (SPX, 2026-09-14/15: real OI outage or
    all-invalid-greeks) but a real history still reports available=True from the snapshot.

    Never invents a value: a cell with no prior valid snapshot AND no current one stays None
    (the endpoint's existing '—' path). Never mutates a CURRENTLY valid cell -- backfill is
    strictly additive to what would otherwise be absent, and a valid cell's own fresh value
    always updates the store for the NEXT cycle that needs it, so a snapshot itself is never
    re-stamped as a fresher snapshot (store writes only happen from real, current data)."""
    expirations = surface.get("expirations") or []
    exp_keys = [e.get("expiry") for e in expirations]
    now = time.time()
    # Rehydrates with NO lock held across the DB read (see _hydrate_last_valid_gex_cells'
    # own LOCK DISCIPLINE note) -- a no-op, pure in-memory lookup after this ticker's first
    # call in this process.
    _hydrate_last_valid_gex_cells(tk)
    cells_with_data = 0
    cells_with_oi_but_invalid_greeks = 0
    wrote_new = False
    with _LAST_VALID_GEX_CELLS_LOCK:
        store = _LAST_VALID_GEX_CELLS.setdefault(tk, {})
        for cell in (surface.get("cells") or []):
            strike = cell.get("strike")
            gex_row, dex_row, vanna_row = cell.get("gex") or [], cell.get("dex") or [], cell.get("vanna") or []
            snapshot_row = cell.setdefault("value_snapshot_ts_utc", [None] * len(exp_keys))  # caps-ok: per-cell timestamp row initialised to None per expiry (unknown until stamped below), not a fabricated time
            for j, exp in enumerate(exp_keys):
                if j >= len(gex_row):
                    continue
                key = (strike, exp)
                if gex_row[j] is not None:
                    # Current, real data this cycle -- the ONE write path for this key. Vanna
                    # can legitimately be None (no IV/TTE) even when gex/dex are real; stored
                    # as-is, never fabricated on the way in.
                    store[key] = {
                        "gex": gex_row[j],
                        "dex": dex_row[j] if j < len(dex_row) else None,
                        "vanna": vanna_row[j] if j < len(vanna_row) else None,
                        "captured_ts_utc": now,
                    }
                    cells_with_data += 1
                    wrote_new = True
                    continue
                snap = store.get(key)
                if snap is None:
                    continue   # never valid, current or historical -- stays None ('—')
                gex_row[j] = snap["gex"]
                if j < len(dex_row):
                    dex_row[j] = snap["dex"]
                if j < len(vanna_row):
                    vanna_row[j] = snap["vanna"]
                snapshot_row[j] = snap["captured_ts_utc"]
                cells_with_data += 1
                cells_with_oi_but_invalid_greeks += 1
    # Flush runs with NO lock held across the DB write (see _flush_last_valid_gex_cells_to_db's
    # own LOCK DISCIPLINE note): a shared lock must never be held across blocking disk I/O.
    # NOT_PROVEN (independent review, 2026-09-16): this is a correct fix to that anti-pattern on
    # its own merits, not a proven explanation for any specific historical hang -- the process
    # that hung ran code predating this table entirely, so this cannot have caused it. The
    # actual cause of that hang is unresolved.
    if wrote_new:
        _flush_last_valid_gex_cells_to_db(tk)
    surface["gamma_available"] = cells_with_data > 0
    surface["cells_with_data"] = cells_with_data
    surface["cells_with_oi_but_invalid_greeks"] = cells_with_oi_but_invalid_greeks
    if cells_with_data > 0:
        surface["gamma_unavailable_reason"] = None
