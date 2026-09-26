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
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TRI = ("prob_up", "prob_down", "prob_flat")


def _minimal_inf_v1(spot: float | None = 450.0):
    from features.canonical_contract import get_mvp_feature_names
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = spot          # None => canonical spot ABSENT (MC must fail closed)
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_neutral"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = -1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.1
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY", expiry=None, as_of_ts=1_700_000_000.0, features=feats)


def _inp(spot: float = 450.0, iv: float = 0.2):
    return SimpleNamespace(
        ticker="SPY", timeframe="1m", spot=spot, iv_level=iv,
        call_gamma_wall=455.0, put_gamma_wall=445.0,
        em_upper=456.0, em_lower=444.0,
        realized_vol=0.15, atr=1.0, garch_sigma_bars=None)


def _rules():
    return SimpleNamespace(signal="wait", conviction="low", confidence_label="low")


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


def _run_stack(*, layers: dict, spot: float = 450.0, iv: float = 0.2):
    """Drive the real _run_model_stack, spying on (but really executing) monte_carlo.simulate."""
    import monte_carlo
    import signals

    real_simulate = monte_carlo.simulate
    captured: dict = {}

    def spy(**kwargs):
        # DETERMINISM: production runs monte_carlo with SEED = None (monte_carlo.py:57), so
        # np.random.default_rng(None) reseeds from OS entropy on EVERY call and two simulations are
        # INDEPENDENT draws. Any test comparing two runs must therefore pin the seed itself, or it
        # is really measuring Monte Carlo sampling noise. Injected here, at the test's own seam;
        # the producer's default is untouched.
        kwargs.setdefault("seed", 20260828)
        captured.update(kwargs)
        return real_simulate(**kwargs)

    inf_v1 = _minimal_inf_v1(spot)
    # RC-REHAB-1 (2026-09-22): LIVE_MODEL_STACK_ENABLED now defaults to False (operator
    # directive -- the live ML/MC stack is legacy, off by default). This whole file proves
    # the STACK'S OWN behavior when genuinely running (real inference wiring, real
    # monte_carlo.simulate), so every test here explicitly re-enables it for its own call --
    # that behavior is still correct code, just no longer the default.
    with patch.object(signals, "LIVE_MODEL_STACK_ENABLED", True), \
        patch("features.inference_snapshot.build_inference_snapshot_v1_from_signal_input",
               return_value=inf_v1), \
        patch("prediction_engine.build_fusion_model_overlay_for_stack",
              return_value={"ticker": "SPY"}), \
        patch("ml_predict.run_unified_stack_ml_once") as rbm, \
        patch("monte_carlo.simulate", side_effect=spy):
        # Directional authorization now requires PROVENANCE, not just complete-looking layers:
        # the approved composition (per active_bundle_contract) must have produced the triplet.
        # These fixtures therefore supply a composition record and the combined triplet whenever
        # every layer is live. A partial roster supplies an INCOMPLETE record, which is exactly the
        # unauthorized case these tests exercise.
        _live = [k for k, v in layers.items() if v.get("prob_flat") is not None and v.get("available")]
        _all_live = sorted(_live) == ["lstm", "transformer", "xgb"]
        from ml_predict import stack_probs_bundle_key
        rbm.return_value = {
            "fusion": layers,
            "model_outputs": {},
            # the combined triplet must live under the LIVE horizon's key, not a hard-coded one
            stack_probs_bundle_key(): (
                {"up": 0.55, "down": 0.25, "flat": 0.20} if _all_live else None),
            "stack_probs_composition": {
                "authorization_schema_version": 1,
                "horizon": "15c", "required": ["xgb", "lstm", "transformer"],
                "produced": [
                    k for k in ("xgb", "lstm", "transformer") if k in _live
                ],
                "missing": [k for k in ("xgb", "lstm", "transformer") if k not in _live],
                "collapsed": [],
                "approved_computation": "meta_stack",
                "executed_computation": "meta_stack" if _all_live else None,
                "computation_compliant": _all_live,
                "contract_compliant": _all_live, "contract_issues": [],
                "complete": _all_live,
            },
        }
        xgb_out, lstm_out, transformer_out, mc_out, ml_bundle = signals._run_model_stack(
            _inp(spot, iv), _rules(),
            SimpleNamespace(primary="unknown", confidence="low"),
            db=MagicMock(), inference_snapshot_v1=inf_v1)
    return SimpleNamespace(xgb=xgb_out, lstm=lstm_out, transformer=transformer_out,
                           mc=mc_out, bundle=ml_bundle, sim_kwargs=captured)


ALL_DARK = {k: _layer(False) for k in ("xgb", "lstm", "transformer")}
ALL_LIVE = {"xgb": _layer(True, 0.55, 0.25), "lstm": _layer(True, 0.52, 0.28),
            "transformer": _layer(True, 0.50, 0.30)}
PARTIAL = {"xgb": _layer(True, 0.60, 0.20), "lstm": _layer(False), "transformer": _layer(False)}
#: The row that makes durable provenance NECESSARY: all three layers report `available` (the value
#: the snapshot column stores) but one triplet is incomplete, so the team gate refuses and MC runs
#: base-neutral. Indistinguishable from ALL_LIVE on the persisted availability columns alone.
AVAIL_BUT_INCOMPLETE = {"xgb": _layer(True, 0.40, 0.30, flat=None),
                        "lstm": _layer(True, 0.35, 0.35), "transformer": _layer(True, 0.33, 0.33)}


# ── PROOF 1: ML unavailable + valid inputs -> MC RUNS and is explicitly base/neutral ──────────


# ── PROOF 1b (RC-REHAB-1, 2026-09-22): LIVE_MODEL_STACK_ENABLED=False (the real default)
# skips BOTH run_unified_stack_ml_once and monte_carlo.simulate entirely -- neither the ML
# models nor Monte Carlo run at all, distinct from PROOF 1 above (a genuine ML failure,
# where MC still runs in base_neutral mode). Operator directive: the live model stack is
# legacy and consumed by nothing today; Monte Carlo is reserved for a future portfolio-
# analysis wiring, not needed live right now either. ──────────────────────────────────────


# ── PROOF 2: ML available/authorized -> MC runs CONDITIONED as intended ───────────────────────




# ── PROOF 3: invalid spot or IV -> MC STILL FAILS CLOSED ──────────────────────────────────────




# ── PROOF 4: ML abstention stays HONEST — never fabricated or revived by base MC ───────────────




# ── PROOF 5: persisted mc_* recover WITHOUT falsely claiming ML participation ──────────────────


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


# ── PROOF 7: the persisted ML columns are PROVABLY insufficient on their own ───────────────────


# ── PROOF 8: a DURABLE consumer cannot read a base-neutral row as ML-conditioned ───────────────
def _persist_and_read_back(tmp_path, run, name: str) -> dict:
    """Round-trip through the REAL EdDB snapshot writer and read the stored row back."""
    import bayesian_fusion
    from db import EdDB, SnapshotRow

    payload = bayesian_fusion.fuse(
        _regime(), run.xgb, run.lstm, run.transformer, run.mc, _rules())
    dbp = tmp_path / f"{name}.db"
    edb = EdDB(str(dbp))
    edb.insert_snapshot(SnapshotRow(
        ticker="SPY", timeframe="1m", ts_utc=time.time(), ts_et="2026-08-28 12:00:00",
        et_hour=12, et_minute=0, market_session="rth", spot=450.0,
        mc_paths=payload.mc_paths, mc_horizon=payload.mc_horizon,
        mc_sigma_value=payload.mc_sigma_value, mc_vol_source=payload.mc_vol_source,
        mc_conditioning=payload.mc_conditioning,
        xgb_available=bool(run.xgb.available), lstm_available=bool(run.lstm.available),
        transformer_available=bool(run.transformer.available)))
    con = sqlite3.connect(str(dbp))
    con.row_factory = sqlite3.Row
    row = dict(con.execute(
        "SELECT mc_paths, mc_conditioning, xgb_available, lstm_available, transformer_available "
        "FROM snapshots ORDER BY rowid DESC LIMIT 1").fetchone())
    con.close()
    return row






# ── PROOF 9: the retired source-text prohibition is gone, and the validator still works ────────
