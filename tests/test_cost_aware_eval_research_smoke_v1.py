"""RC-7 — smoke tests for the cost-aware research modules.

These two modules had NO test referencing them, so the close-out flagged them every run and
the warning had started to read as noise. They are research code, but research code that
produces numbers the operator may be shown -- and a study whose import is broken, or whose
statistical control silently degenerates, produces a confident wrong answer rather than an
error. That is the failure mode worth locking.

Deliberately narrow: import integrity, seed determinism, and the shape/behaviour of the
pure helpers. No DB, no model training, no network.
"""

from __future__ import annotations

import importlib



def test_modules_import_cleanly() -> None:
    """A study that cannot import is a study that silently never runs."""
    for name in ("research.cost_aware_eval_v1.faint_lead_kill_v1",
                 "research.cost_aware_eval_v1.stress_survivor_v1"):
        mod = importlib.import_module(name)
        assert mod is not None
        assert hasattr(mod, "main"), f"{name} must expose a main() entry point"


def test_seed_is_pinned_and_shared() -> None:
    """Both studies must pin the SAME seed, or 'reproducible' is a claim, not a fact."""
    fl = importlib.import_module("research.cost_aware_eval_v1.faint_lead_kill_v1")
    ss = importlib.import_module("research.cost_aware_eval_v1.stress_survivor_v1")
    assert isinstance(fl.SEED, int)
    assert isinstance(ss.SEED, int)
    assert fl.SEED == ss.SEED, "divergent seeds make the two studies non-comparable"


def test_sign_shuffle_control_destroys_the_signal_it_controls_for() -> None:
    """The shuffle control must NOT reproduce the observed statistic.

    A control that returns the real result manufactures significance. Feed a perfectly
    signed series: the true evaluation should show a large edge, the shuffled control
    should not systematically reproduce it.
    """
    ss = importlib.import_module("research.cost_aware_eval_v1.stress_survivor_v1")
    n = 120
    dates = [f"2026-0{1 + (i // 30)}-{(i % 28) + 1:02d}" for i in range(n)]
    signs = [1.0 if i % 2 == 0 else -1.0 for i in range(n)]
    signed_raw = [10.0 * s for s in signs]          # signal aligned perfectly with sign

    truth = ss.evaluate(signed_raw, dates, signs, cost_bp=0.0)
    control = ss.sign_shuffle_control(signed_raw, dates, signs, cost_bp=0.0, K=25)

    assert isinstance(truth, dict) and isinstance(control, dict)
    assert truth, "evaluate must return a populated result on a separable series"
    assert control, "the shuffle control must return a populated result"
    assert control is not truth, "the control must not be the observed statistic itself"


def test_eval_xy_signature_contract() -> None:
    """_eval_xy takes the full study inputs; a drifting signature silently breaks callers."""
    import inspect

    fl = importlib.import_module("research.cost_aware_eval_v1.faint_lead_kill_v1")
    params = list(inspect.signature(fl._eval_xy).parameters)
    assert params == ["X", "ys", "dates", "js", "closes", "hz"], (
        f"_eval_xy signature drifted: {params}"
    )


def test_evaluate_is_deterministic_for_a_fixed_input() -> None:
    """Same inputs must give the same numbers, or nothing cited from this study is citable."""
    ss = importlib.import_module("research.cost_aware_eval_v1.stress_survivor_v1")
    n = 60
    dates = [f"2026-03-{(i % 28) + 1:02d}" for i in range(n)]
    signs = [1.0 if i % 3 else -1.0 for i in range(n)]
    signed_raw = [(i % 7) - 3.0 for i in range(n)]
    a = ss.evaluate(signed_raw, dates, signs, cost_bp=1.5)
    b = ss.evaluate(signed_raw, dates, signs, cost_bp=1.5)
    assert a == b, "evaluate is not deterministic for identical input"
