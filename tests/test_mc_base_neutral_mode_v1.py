"""Monte Carlo runs in a valid BASE/NEUTRAL mode when the ML team is unavailable.

The unified-stack team gate selects Monte Carlo's CONDITIONING MODE, not its availability.
`monte_carlo.simulate` requires only spot / iv / horizon_bars; the model_prob_* arguments are
optional directional conditioning. Every test below drives the REAL `signals._run_model_stack`
and the REAL `monte_carlo.simulate` (never a stub standing in for the producer), so the proof is
behavioral: frames in, simulated paths out.

NOTE ON SEMANTICS: base MC is NOT "the same numbers minus the drift". The drift term enters every
simulated path step, so every PATH-DERIVED output (bands, excursions, touch probabilities,
containment/expansion, dispersion, expected move, tail risk, directional bias) is drift-SENSITIVE.
Base MC is internally valid for a neutral-drift assumption; it is a different simulation from a
conditioned one, which is exactly why the provenance stamp must never be silently dropped.
Only `sigma_annualized` (computed before path generation) and the run metadata are drift-invariant.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _regime():
    return SimpleNamespace(primary="unknown", confidence="low", confidence_label="low")


def _layer(available: bool, up: float = 0.34, dn: float = 0.33, flat: float | None = -1.0):
    """One ML layer's fusion-dict view. available=False => the layer abstained this tick.

    flat=None models a layer that reports available but whose directional TRIPLET is incomplete —
    the team gate keys on triplet completeness, the persisted column stores only `available`.
    """
    if not available:
        return {"available": False, "prob_up": None, "prob_down": None, "prob_flat": None}
    pf = round(1 - up - dn, 6) if flat == -1.0 else flat
    # confidence_label: bayesian_fusion reads it when building the evidence line for a live layer
    return {"available": True, "prob_up": up, "prob_down": dn, "prob_flat": pf,
            "confidence_label": "medium", "dominant": "up" if up >= dn else "down"}


ALL_LIVE = {"xgb": _layer(True, 0.55, 0.25), "lstm": _layer(True, 0.52, 0.28),
            "transformer": _layer(True, 0.50, 0.30)}
PARTIAL = {"xgb": _layer(True, 0.60, 0.20), "lstm": _layer(False), "transformer": _layer(False)}
#: The row that makes durable provenance NECESSARY: all three layers report `available` (the value
#: the snapshot column stores) but one triplet is incomplete, so the team gate refuses and MC runs
#: base-neutral. Indistinguishable from ALL_LIVE on the persisted availability columns alone.


# ── PROOF 1b (RC-REHAB-1, 2026-09-22): LIVE_MODEL_STACK_ENABLED=False (the real default)
# skips BOTH run_unified_stack_ml_once and monte_carlo.simulate entirely -- neither the ML
# models nor Monte Carlo run at all, distinct from PROOF 1 above (a genuine ML failure,
# where MC still runs in base_neutral mode). Operator directive: the live model stack is
# legacy and consumed by nothing today; Monte Carlo is reserved for a future portfolio-
# analysis wiring, not needed live right now either. ──────────────────────────────────────


# ── PROOF 6: watchdog still separates a DEAD MC producer from a healthy BASE MC ────────────────
def _liveness_db(tmp_path: Path, *, mc_paths_value) -> str:
    db = tmp_path / "ed_console.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE snapshots (ts_utc REAL, ticker TEXT, mc_paths INTEGER)")
    con.execute("CREATE TABLE logging_universe (ticker TEXT, category TEXT, "
                "last_background_log_ts_utc REAL)")
    now = time.time()
    for i in range(5):
        con.execute("INSERT INTO snapshots VALUES (?,?,?)", (now - i, "SPY", mc_paths_value))
    con.execute("INSERT INTO logging_universe VALUES (?,?,?)", ("SPY", "core", now))
    con.commit()
    con.close()
    return str(db)


def _run_liveness(db_path: str) -> tuple[int, list]:
    import tools.console_liveness_check as clc

    emitted: list = []
    with patch.object(clc, "_required_window_now", return_value=(True, "forced inside window")), \
        patch.object(clc, "_emit", side_effect=lambda s, m: emitted.append((s, m))):
        rc = clc.check(db_path)
    return rc, emitted


def test_watchdog_reports_ok_for_healthy_base_mc(tmp_path):
    """Base MC writes mc_paths => the producer is alive; DEAD PRODUCER must NOT fire."""
    rc, emitted = _run_liveness(_liveness_db(tmp_path, mc_paths_value=10000))
    assert rc == 0, f"healthy base MC must not alert: {emitted}"
    assert emitted and emitted[0][0] == "OK"
    assert not any("DEAD PRODUCER" in m for _, m in emitted)


def test_watchdog_still_detects_a_genuinely_dead_mc_producer(tmp_path):
    """A truly dead MC producer still writes NULL mc_paths => the alert must still fire."""
    rc, emitted = _run_liveness(_liveness_db(tmp_path, mc_paths_value=None))
    assert rc == 1, "a dead MC producer must still alert"
    assert any("DEAD PRODUCER" in m for _, m in emitted), emitted
