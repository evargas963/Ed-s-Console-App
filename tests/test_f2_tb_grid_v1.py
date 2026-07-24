"""F2 grid runner — unit seams for the pure economics/verdict machinery."""
from __future__ import annotations

from research.pilot_step3.f2_tb_grid_runner import (
    CellEconomics,
    apply_grid_verdicts,
    bootstrap_mean_ci,
    deflated_sharpe_prob,
    evaluate_cell,
    load_prereg,
    session_means,
    sign_shuffle_null,
)


def test_prereg_loads_and_family_is_175():
    p = load_prereg()
    assert p["family"]["n_cells"] == 175
    assert p["prereg_id"] == "F2_TB_GRID_V1_PREREG_V1"


def test_session_means_aggregates_per_day():
    rows = [("d1", 10.0), ("d1", 20.0), ("d2", -6.0)]
    m = session_means(rows)
    assert m == {"d1": 15.0, "d2": -6.0}


def test_bootstrap_ci_deterministic_and_positive_on_positive_values():
    vals = [5.0, 6.0, 4.0, 5.5, 4.5, 5.0, 6.5, 4.8]
    a = bootstrap_mean_ci(vals, n_boot=500, seed=7)
    b = bootstrap_mean_ci(vals, n_boot=500, seed=7)
    assert a == b
    assert a["ci95"][0] > 0
    assert a["p_value"] <= 2.0 / 500 + 1e-12


def test_sign_shuffle_null_is_centered_and_seeded():
    vals = [3.0, -2.0, 4.0, 1.5, -1.0, 2.5] * 20
    a = sign_shuffle_null(vals, n_shuffles=300, seed=11)
    b = sign_shuffle_null(vals, n_shuffles=300, seed=11)
    assert a == b
    assert a["null_q975"] > 0  # upper tail of a symmetric null


def test_dsr_high_for_strong_steady_edge():
    sessions = [3.0 + 0.1 * (i % 5) for i in range(80)]  # relentless positive
    p = deflated_sharpe_prob(sessions, n_trials=175, sr_std_across_trials=0.2)
    assert p is not None and p > 0.99


def _cell(
    key: str, day_bp: float, *, day_spread: float = 1.0, n_days: int = 80, per_day: int = 5
) -> CellEconomics:
    rows = []
    for d in range(n_days):
        wiggle = day_spread * ((((d * 37) % 13) - 6) / 6.0)  # deterministic day-level variance
        for k in range(per_day):
            rows.append((f"2026-{d:02d}", day_bp + wiggle + 0.3 * (k - 2)))
    return evaluate_cell(
        key, rows, len(rows), extra_cost_bp=1.0, n_boot=400, shuffle_k=100, seed=99
    )


def test_grid_verdicts_survive_kill_undersampled_and_anti_signal():
    strong = _cell("strong", 6.0)
    weak = _cell("weak", 0.05)
    # Anti-signal is real but moderate: a -9 Sharpe sibling would (correctly!)
    # inflate the cross-trial DSR hurdle enough to deflate even the strong cell
    # - which is DSR doing its job, verified while building this fixture.
    anti = _cell("anti", -1.2)
    thin_rows = [("2026-01", 5.0), ("2026-02", 4.0)]
    thin = evaluate_cell(
        "thin", thin_rows, 2, extra_cost_bp=1.0, n_boot=400, shuffle_k=100, seed=5
    )
    out = apply_grid_verdicts(
        {"strong": strong, "weak": weak, "anti": anti, "thin": thin},
        n_trials=4,
        min_sessions=60,
        min_candidates=100,
        psr_threshold=0.95,
    )
    assert out["strong"]["verdict"] == "SURVIVE_ECONOMIC"
    assert out["thin"]["verdict"] == "UNDER_SAMPLED"
    assert out["anti"]["verdict"] == "KILL"
    assert out["anti"]["anti_signal"] is True
    assert out["weak"]["verdict"] == "KILL"
    assert out["weak"]["anti_signal"] is False


def test_stress_screen_kills_edge_thinner_than_double_cost():
    # +1.3bp mean with wide session spread: clears its own CI but the extra
    # 1bp stress pushes the session-mean CI back over zero.
    marginal = _cell("marginal", 1.3, day_spread=3.6)
    out = apply_grid_verdicts(
        {"marginal": marginal},
        n_trials=1,
        min_sessions=60,
        min_candidates=100,
        psr_threshold=0.95,
    )
    scr = out["marginal"]["screen"]
    assert scr["ci95_above_zero"] is True
    assert scr["stress_2x_ok"] is False
    assert out["marginal"]["verdict"] == "KILL"
