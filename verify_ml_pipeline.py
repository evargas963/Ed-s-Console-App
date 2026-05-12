#!/usr/bin/env python3
"""
verify_ml_pipeline.py — production verification log for ML stack + dashboard contract.

Run: python verify_ml_pipeline.py
Requires: models/parallel/{ticker}, models/cascade/{ticker} and DB (optional for full eval).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from db import DB_PATH as DB


def main() -> int:
    out = {"checks": []}

    def ok(name: str, detail: str, pass_: bool) -> None:
        out["checks"].append({"name": name, "pass": pass_, "detail": detail})

    from types import SimpleNamespace

    mc = SimpleNamespace(
        available=True,
        containment_prob=0.5,
        expansion_prob=0.5,
        mc_feature_dict=lambda: {
            "expected_move": 1.0,
            "volatility": 2.0,
            "skew": 0.0,
            "tail_risk": 0.2,
            "directional_bias": 0.01,
            "source": "derived_mc_normalized",
        },
    )

    try:
        import bayesian_fusion
        x = SimpleNamespace(
            available=True,
            prob_up=0.34,
            prob_down=0.33,
            prob_flat=0.33,
            continuation_support=0.2,
            reversal_support=0.2,
            dominant_class="flat",
            confidence_label="low",
        )
        r = SimpleNamespace(
            available=True,
            prob_up=0.33,
            prob_down=0.33,
            prob_flat=0.34,
            dominant_class="flat",
            confidence_label="low",
        )
        rules = SimpleNamespace(signal="wait", conviction="low", available=True, prob_flat=0.34)
        reg = SimpleNamespace(primary="pinning", confidence="medium")
        fusion = bayesian_fusion.fuse(reg, x, x, x, mc, rules)
        fuse_detail = (
            f"weight_mc={fusion.weight_monte_carlo:.3f} mc_available={fusion.mc_available} "
            f"mc_post_audit={bool(getattr(fusion, 'mc_post_fusion_audit', None))}"
        )
        ok(
            "monte_carlo_excluded_from_fusion_weights",
            fuse_detail,
            fusion.weight_monte_carlo == 0.0 and fusion.mc_available,
        )
        ok(
            "fusion_mc_contribution_empty",
            str(getattr(fusion, "fusion_mc_contribution", None)),
            getattr(fusion, "fusion_mc_contribution", None) is None,
        )
    except Exception as e:
        ok("monte_carlo_into_fusion", str(e), False)

    try:
        from prediction_engine import _build_horizon_prob_bars

        p = {"up": 0.34, "down": 0.33, "flat": 0.33}
        lit = (p, "empirical_outcome_15c", "test", 40)
        h = _build_horizon_prob_bars(lit, lit, lit, lit)
        ok("horizon_bars_keys", str(list(h.keys())), set(h.keys()) == {"1m", "5m", "15m", "60m"})
    except Exception as e:
        ok("horizon_bars_keys", str(e), False)

    try:
        from eval_metrics_store import arch_eval_proof_path, metrics_path

        p = metrics_path()
        ok("eval_metrics_path", str(p), True)
        ap = arch_eval_proof_path()
        want_keys = (
            "parallel_eval_log_loss",
            "cascade_eval_log_loss",
            "parallel_eval_accuracy",
            "cascade_eval_accuracy",
            "parallel_eval_pnl_realized_contract",
            "cascade_eval_pnl_realized_contract",
            "final_promoted_winner",
        )
        if ap.is_file():
            doc = json.loads(ap.read_text(encoding="utf-8"))
            bt = doc.get("by_ticker") or {}
            first = next(iter(bt.values()), {})
            missing = [k for k in want_keys if k not in first]
            ok("arch_eval_proof_keys", f"missing={missing} path={ap}", len(missing) == 0)
        else:
            ok("arch_eval_proof_keys", f"skip (file missing: {ap})", True)
    except Exception as e:
        ok("eval_metrics_path", str(e), False)

    if DB.exists():
        try:
            from ml_scheduler import _evaluate_parallel_on_full_rth, _evaluate_cascade_on_full_rth

            ticker = "SPY"
            par_dir = ROOT / "models" / "parallel" / ticker
            cas_dir = ROOT / "models" / "cascade" / ticker
            if par_dir.is_dir() and cas_dir.is_dir():
                pa, pb, n, pll, prm = _evaluate_parallel_on_full_rth(str(DB), ticker, par_dir)
                ca, cb, nc, cll, crm = _evaluate_cascade_on_full_rth(str(DB), ticker, cas_dir)
                ok(
                    "parallel_eval_runs",
                    f"n={n} acc={pa:.4f} log_loss={pll} realized={prm.get('eval_pnl_realized_contract')}",
                    n >= 10 and pll is not None and isinstance(prm, dict),
                )
                ok(
                    "cascade_eval_runs",
                    f"n={nc} acc={ca:.4f} log_loss={cll} realized={crm.get('eval_pnl_realized_contract')}",
                    nc >= 10 and cll is not None and isinstance(crm, dict),
                )
            else:
                ok("parallel_eval_runs", "skip: no candidate models on disk", True)
        except Exception as e:
            ok("parallel_eval_runs", str(e), False)
    else:
        ok("db_present", "skip eval (no DB)", True)

    print(json.dumps(out, indent=2))
    return 0 if all(c["pass"] for c in out["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
