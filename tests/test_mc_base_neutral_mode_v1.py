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
        captured.update(kwargs)
        return real_simulate(**kwargs)

    inf_v1 = _minimal_inf_v1(spot)
    with patch("features.inference_snapshot.build_inference_snapshot_v1_from_signal_input",
               return_value=inf_v1), \
        patch("prediction_engine.build_fusion_model_overlay_for_stack",
              return_value={"ticker": "SPY"}), \
        patch("ml_predict.run_unified_stack_ml_once") as rbm, \
        patch("monte_carlo.simulate", side_effect=spy):
        rbm.return_value = {"fusion": layers, "model_outputs": {}, "stack_probs_15c": None}
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
def test_ml_unavailable_mc_still_runs_and_is_explicitly_base_neutral():
    r = _run_stack(layers=ALL_DARK)

    # it RAN — a real simulation, not a withheld placeholder
    assert r.mc.available is True, "base MC must run when its own canonical inputs are valid"
    assert r.mc.simulation_ok is True
    assert r.mc.fallback_used is False
    assert r.mc.n_paths > 0 and r.mc.horizon_bars > 0

    # path-derived outputs are present and finite (these are DRIFT-SENSITIVE, not invariant)
    for fld in ("expected_favorable_excursion", "expected_adverse_excursion",
                "containment_prob", "expansion_prob", "path_dispersion", "expected_move"):
        assert getattr(r.mc, fld) is not None, f"{fld} missing from a valid base simulation"

    # and it is EXPLICITLY labelled neutral — never presented as ML-conditioned
    assert r.mc.assumptions["mc_conditioning"] == "base_neutral"
    assert r.mc.model_version.endswith(":base_neutral")
    assert r.mc.assumptions["per_bar_drift"] == 0.0, "neutral mode must carry exactly zero drift"
    assert r.bundle["mc_conditioned"] is False
    assert r.bundle["unified_stack_team_ok"] is False


# ── PROOF 2: ML available/authorized -> MC runs CONDITIONED as intended ───────────────────────
def test_ml_authorized_mc_runs_conditioned_with_real_directional_prior():
    r = _run_stack(layers=ALL_LIVE)

    assert r.mc.available is True
    assert r.bundle["unified_stack_team_ok"] is True
    assert r.bundle["mc_conditioned"] is True
    assert r.mc.assumptions["mc_conditioning"] == "ml_conditioned"
    assert ":base_neutral" not in r.mc.model_version

    # the authorized probabilities really reached the producer, and really moved the drift
    assert r.sim_kwargs["model_prob_up"] is not None
    assert r.sim_kwargs["model_prob_down"] is not None
    assert r.sim_kwargs["model_prob_up"] > r.sim_kwargs["model_prob_down"]  # bullish team
    assert r.mc.assumptions["per_bar_drift"] > 0.0, "a bullish authorized team must tilt drift up"


def test_conditioned_and_base_are_different_simulations_not_relabelled_ones():
    """Drift is not cosmetic: the same inputs under a real team produce a different path law."""
    base = _run_stack(layers=ALL_DARK)
    cond = _run_stack(layers=ALL_LIVE)

    assert base.mc.assumptions["per_bar_drift"] == 0.0
    assert cond.mc.assumptions["per_bar_drift"] != 0.0
    # sigma IS drift-invariant (computed before path generation) — same vol law both ways
    assert base.mc.assumptions["sigma_annualized"] == cond.mc.assumptions["sigma_annualized"]

    # ...but every PATH-DERIVED output is drift-SENSITIVE. Both runs share the same seed, so the
    # random draws are identical and these differences are the drift term alone. This is the
    # concrete reason a neutral run must never be relabelled as a conditioned one.
    assert cond.mc.median_path > base.mc.median_path, "bullish drift must lift the median path"
    assert cond.mc.expected_favorable_excursion > base.mc.expected_favorable_excursion
    assert cond.mc.expected_adverse_excursion < base.mc.expected_adverse_excursion


# ── PROOF 3: invalid spot or IV -> MC STILL FAILS CLOSED ──────────────────────────────────────
def test_invalid_iv_still_fails_closed():
    r = _run_stack(layers=ALL_DARK, iv=0.0)
    assert r.mc.available is False, "IV=0 must still fail closed even in base mode"
    assert r.mc.fallback_used is True
    assert "mc_conditioning" not in (r.mc.assumptions or {})


def test_absent_canonical_spot_still_fails_closed():
    """No canonical price.spot => MC must refuse outright; base mode is not a licence to guess."""
    r = _run_stack(layers=ALL_DARK, spot=None)
    assert r.mc.available is False, "an absent canonical spot must still fail closed"
    assert "blocked" in r.mc.model_version
    assert ":base_neutral" not in r.mc.model_version, "a refused run is not a base-neutral run"


# ── PROOF 4: ML abstention stays HONEST — never fabricated or revived by base MC ───────────────
def test_base_mode_does_not_revive_or_fabricate_ml_abstention():
    from governed_stack_contract import derive_stack_layers_scored

    r = _run_stack(layers=ALL_DARK)

    # the abstaining layers stay abstained — base MC does not resurrect them
    assert r.xgb.available is False
    assert r.lstm.available is False
    assert r.transformer.available is False
    assert r.bundle["unified_stack_team_ok"] is False
    assert r.bundle["mc_stack_probability_source"] == "uniform_no_stack_tri_class_signal"

    # base mode passed NO directional prior at all — no fabricated uniform view reaches the producer
    assert r.sim_kwargs["model_prob_up"] is None
    assert r.sim_kwargs["model_prob_down"] is None
    assert r.sim_kwargs["model_confidence"] is None

    # participation accounting credits MC only — never the dark ML layers, never meta
    scored = derive_stack_layers_scored(
        xgb_out=r.xgb, lstm_out=r.lstm, transformer_out=r.transformer, mc_out=r.mc,
        ml_bundle=r.bundle, regime=SimpleNamespace(primary="unknown"), fusion_payload=None)
    assert "monte_carlo" in scored
    for claimed in ("xgb", "lstm", "transformer", "meta"):
        assert claimed not in scored, f"base MC must not credit {claimed} participation"


def test_partial_ml_is_not_smuggled_in_as_conditioning():
    """Team gate refused (1 of 3 layers) => MC must be NEUTRAL, not quietly conditioned on that layer."""
    r = _run_stack(layers=PARTIAL)

    assert r.bundle["unified_stack_team_ok"] is False
    assert r.mc.available is True                       # still runs
    assert r.mc.assumptions["mc_conditioning"] == "base_neutral"
    assert r.sim_kwargs["model_prob_up"] is None, "unauthorized partial-ML must not condition MC"
    assert r.mc.assumptions["per_bar_drift"] == 0.0


# ── PROOF 5: persisted mc_* recover WITHOUT falsely claiming ML participation ──────────────────
def test_persisted_mc_fields_recover_without_claiming_ml():
    """The exact fields that were NULL for 3 weeks come back, while every ML claim stays false."""
    import bayesian_fusion

    r = _run_stack(layers=ALL_DARK)
    payload = bayesian_fusion.fuse(
        _regime(), r.xgb, r.lstm, r.transformer, r.mc, _rules())

    # the persisted mc_* family is populated again
    assert payload.mc_available is True
    for fld in ("mc_paths", "mc_horizon", "mc_sigma_value", "mc_containment",
                "mc_expansion", "mc_efe", "mc_eae", "mc_upper_50", "mc_lower_50"):
        assert getattr(payload, fld) is not None, f"{fld} must recover in base mode"

    # ...and nothing in the payload claims ML took part
    assert payload.weight_monte_carlo == 0.0, "MC must still cast no vote in the posterior"
    assert r.bundle["mc_conditioned"] is False


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
def test_persisted_availability_columns_alone_cannot_carry_the_distinction():
    """Why a durable field is required, demonstrated rather than asserted.

    The team gate keys on triplet COMPLETENESS; the snapshot columns store layer `available`.
    So two rows can be byte-identical across xgb/lstm/transformer_available while one simulation
    was ML-conditioned and the other was base-neutral.
    """
    ambiguous = _run_stack(layers=AVAIL_BUT_INCOMPLETE)
    conditioned = _run_stack(layers=ALL_LIVE)

    def flags(r):
        return (bool(r.xgb.available), bool(r.lstm.available), bool(r.transformer.available))

    assert flags(ambiguous) == (True, True, True)
    assert flags(conditioned) == (True, True, True)
    assert flags(ambiguous) == flags(conditioned), "premise: the stored flags are identical"

    # ...yet the actual conditioning differs
    assert ambiguous.mc.assumptions["mc_conditioning"] == "base_neutral"
    assert conditioned.mc.assumptions["mc_conditioning"] == "ml_conditioned"
    assert ambiguous.bundle["unified_stack_team_ok"] is False
    assert conditioned.bundle["unified_stack_team_ok"] is True


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


def test_durable_row_distinguishes_base_neutral_from_ml_conditioned(tmp_path):
    """The stored row itself answers 'was this ML-conditioned?' — no in-memory state required."""
    base = _persist_and_read_back(tmp_path, _run_stack(layers=AVAIL_BUT_INCOMPLETE), "base")
    cond = _persist_and_read_back(tmp_path, _run_stack(layers=ALL_LIVE), "cond")

    # both rows really did run MC, and really are identical on every ML availability column
    assert base["mc_paths"] and cond["mc_paths"]
    for col in ("xgb_available", "lstm_available", "transformer_available"):
        assert base[col] == cond[col] == 1, "premise: availability columns cannot separate these"

    # the durable field separates them, so a base-neutral row can never read as ML-conditioned
    assert base["mc_conditioning"] == "base_neutral"
    assert cond["mc_conditioning"] == "ml_conditioned"
    assert base["mc_conditioning"] != cond["mc_conditioning"]


def test_durable_conditioning_is_null_when_mc_did_not_run(tmp_path):
    """A failed/withheld MC must not claim a conditioning mode it never had."""
    row = _persist_and_read_back(tmp_path, _run_stack(layers=ALL_DARK, iv=0.0), "dead")
    assert row["mc_paths"] is None
    assert row["mc_conditioning"] is None


# ── PROOF 9: the retired source-text prohibition is gone, and the validator still works ────────
def test_governed_stack_validator_passes_and_stale_none_pin_is_retired():
    """signals.py now passes NO directional prior in base mode — the validator must not forbid it,
    and must still catch the legacy-substrate violations it actually exists for."""
    import importlib

    v = importlib.import_module("tools.validate_governed_stack_policy_compliance_v1")

    # the real behaviour the retired pin tried to describe IS present in the source now
    src = (ROOT / "signals.py").read_text(encoding="utf-8", errors="replace")
    assert "_mc_up = _mc_dn = _mc_conf_in = None" in src, "base mode must pass no prior"

    assert v.main() == 0, "validator must pass on the proven base-neutral contract"

    # NEGATIVE CONTROL: the checks it is genuinely scoped to still fire
    real_read = v._read

    def poisoned(p):
        txt = real_read(p)
        return txt + "\npred_move_prob_5m = 1\n" if p.name.startswith("run_phase8") else txt

    with patch.object(v, "_read", side_effect=poisoned):
        # main() returns 0 on PASS and 3 on FAIL
        assert v.main() == 3, "validator must still detect legacy pred_move_prob_* policy substrate"
