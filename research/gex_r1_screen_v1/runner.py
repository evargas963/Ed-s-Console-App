"""GEX-R1-SCREEN runner — economic screen on 0DTE stored chain (not edge)."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.gex_r1_screen_v1.rules import day_rule_pnl
from research.gex_r1_screen_v1.signal import attach_gex_z, load_morning_signals

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
REPORT_DIR = ROOT / "reports"


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


def _block_bootstrap_mean_ci(
    xs: list[float], *, n_boot: int = 400, seed: int = 42
) -> tuple[float, float, float]:
    if not xs:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(xs)
    means = []
    for _ in range(n_boot):
        sample = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    return sum(xs) / n, lo, hi


def _sign_validation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """§8.7 gate 1: +GEX days → smaller range / more reversion vs −GEX."""
    pos = [r for r in rows if r["gex_sign"] > 0 and r.get("regime_score") is not None]
    neg = [r for r in rows if r["gex_sign"] < 0 and r.get("regime_score") is not None]
    def avg(key: str, rs: list[dict]) -> float:
        vs = [float(r[key]) for r in rs if r.get(key) is not None and math.isfinite(float(r[key]))]
        return float(sum(vs) / len(vs)) if vs else float("nan")

    pos_score = avg("regime_score", pos)
    neg_score = avg("regime_score", neg)
    # Expected: +GEX → reversion pays more → higher regime_score
    orientation = "as_assumed" if (
        math.isfinite(pos_score) and math.isfinite(neg_score) and pos_score > neg_score
    ) else "inverted_or_null"
    agrees = [r["sign_agrees_net_gamma"] for r in rows if r.get("sign_agrees_net_gamma") is not None]
    agree_rate = (sum(1 for a in agrees if a) / len(agrees)) if agrees else float("nan")
    return {
        "n_pos_gex": len(pos),
        "n_neg_gex": len(neg),
        "mean_regime_score_pos_gex": pos_score,
        "mean_regime_score_neg_gex": neg_score,
        "sign_orientation": orientation,
        "net_gamma_sign_agreement_rate": agree_rate,
        "note": (
            "as_assumed means +GEX days have higher (reversion−breakout) than −GEX; "
            "inverted_or_null means flip convention or no separation"
        ),
    }


def _walk_forward_conditioned(
    rows: list[dict[str, Any]],
    *,
    min_train: int,
    embargo: int,
    test_block: int,
    seed: int,
) -> dict[str, Any]:
    """Simple sign rule first; logistic on {gex_sign,gex_z} if enough train."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    days = sorted(rows, key=lambda r: r["et_date"])
    if len(days) < min_train + test_block + embargo:
        return {"status": "INSUFFICIENT_DAYS", "n": len(days)}

    conditioned: list[float] = []
    always_rev: list[float] = []
    always_brk: list[float] = []
    random_choice: list[float] = []
    rng = random.Random(seed)
    i = min_train
    while i + embargo + 1 <= len(days):
        train = days[:i]
        test_end = min(len(days), i + embargo + test_block)
        test = days[i + embargo : test_end]
        if not test:
            break
        y = np.array([1 if r["regime_score"] > 0 else 0 for r in train], dtype=int)
        X = np.array(
            [
                [
                    float(r["gex_sign"]),
                    float(r["gex_z"]) if math.isfinite(float(r.get("gex_z") or float("nan"))) else 0.0,
                ]
                for r in train
            ],
            dtype=float,
        )
        use_model = len(train) >= min_train and len(set(y.tolist())) == 2
        clf = None
        scaler = None
        if use_model:
            scaler = StandardScaler()
            Xs = scaler.fit_transform(X)
            clf = LogisticRegression(max_iter=500, random_state=seed)
            clf.fit(Xs, y)
        for r in test:
            # predict reversion pays (1) vs breakout (0)
            if clf is not None and scaler is not None:
                xz = float(r["gex_z"]) if math.isfinite(float(r.get("gex_z") or float("nan"))) else 0.0
                pred = int(
                    clf.predict(scaler.transform([[float(r["gex_sign"]), xz]]))[0]
                )
            else:
                # fallback: +GEX → reversion, −GEX → breakout
                pred = 1 if r["gex_sign"] > 0 else 0
            pnl = r["reversion_pnl"] if pred == 1 else r["breakout_pnl"]
            conditioned.append(float(pnl))
            always_rev.append(float(r["reversion_pnl"]))
            always_brk.append(float(r["breakout_pnl"]))
            random_choice.append(
                float(r["reversion_pnl"] if rng.random() < 0.5 else r["breakout_pnl"])
            )
        i += test_block
    if not conditioned:
        return {"status": "NO_TEST_FOLDS", "n": len(days)}

    def pack(xs: list[float]) -> dict[str, Any]:
        mean, lo, hi = _block_bootstrap_mean_ci(xs, seed=seed)
        return {
            "n_days": len(xs),
            "mean_net_dollars": mean,
            "ci95": [lo, hi],
            "ci_excludes_0": bool(math.isfinite(lo) and math.isfinite(hi) and (lo > 0 or hi < 0) and not (lo <= 0 <= hi)),
            "sum_net_dollars": float(sum(xs)),
        }

    cond = pack(conditioned)
    urev = pack(always_rev)
    ubrk = pack(always_brk)
    urand = pack(random_choice)
    best_uncond = urev if urev["mean_net_dollars"] >= ubrk["mean_net_dollars"] else ubrk
    beats_uncond = cond["mean_net_dollars"] > best_uncond["mean_net_dollars"]
    return {
        "status": "OK",
        "conditioned": cond,
        "always_reversion": urev,
        "always_breakout": ubrk,
        "random_choice": urand,
        "best_unconditional": "reversion" if best_uncond is urev else "breakout",
        "beats_best_unconditional": beats_uncond,
    }


def _shuffle_null(rows: list[dict[str, Any]], *, seed: int, n: int = 200) -> dict[str, Any]:
    """Shuffle gex_sign across days; conditioned mean should collapse."""
    rng = random.Random(seed)
    base_signs = [r["gex_sign"] for r in rows]
    means = []
    for _ in range(n):
        shuf = base_signs[:]
        rng.shuffle(shuf)
        pnls = []
        for r, sg in zip(rows, shuf):
            pred_rev = sg > 0
            pnls.append(r["reversion_pnl"] if pred_rev else r["breakout_pnl"])
        means.append(sum(pnls) / len(pnls))
    means.sort()
    real = []
    for r in rows:
        real.append(r["reversion_pnl"] if r["gex_sign"] > 0 else r["breakout_pnl"])
    real_mean = sum(real) / len(real)
    return {
        "real_sign_rule_mean": real_mean,
        "shuffle_mean_mean": float(sum(means) / len(means)),
        "shuffle_ci95": [means[int(0.025 * n)], means[int(0.975 * n)]],
        "real_outside_shuffle_ci": bool(
            real_mean < means[int(0.025 * n)] or real_mean > means[int(0.975 * n)]
        ),
    }


def run_screen(db_path: Path | str) -> dict[str, Any]:
    prereg = load_prereg()
    rules = prereg["rules"]
    wf = prereg["walk_forward"]
    tickers = list(prereg["tickers"])
    sigs = load_morning_signals(
        str(db_path),
        tickers,
        start_mins=int(prereg["morning_window_et"]["start_mins"]),
        end_mins=int(prereg["morning_window_et"]["end_mins"]),
    )
    feat_rows = attach_gex_z(sigs)
    enriched: list[dict[str, Any]] = []
    skipped_no_bars = 0
    for r in feat_rows:
        pnl = day_rule_pnl(
            str(db_path),
            r["ticker"],
            r["et_date"],
            float(r["spot"]),
            m=float(rules["m_sigma"]),
            max_entries=int(rules["max_entries_per_day"]),
            cost_rt_bp=float(rules["cost_round_trip_bp"]),
            or_minutes=int(rules["or_minutes"]),
            buffer_frac=float(rules["or_buffer_sigma_frac"]),
        )
        if pnl is None:
            skipped_no_bars += 1
            continue
        r = dict(r)
        r["reversion_pnl"] = pnl.reversion_pnl
        r["breakout_pnl"] = pnl.breakout_pnl
        r["regime_score"] = pnl.regime_score
        r["sigma"] = pnl.sigma
        r["n_rev_trades"] = pnl.n_rev_trades
        r["n_brk_trades"] = pnl.n_brk_trades
        enriched.append(r)

    # 2x cost stress rows
    stress_rows: list[dict[str, Any]] = []
    for r in feat_rows:
        pnl = day_rule_pnl(
            str(db_path),
            r["ticker"],
            r["et_date"],
            float(r["spot"]),
            m=float(rules["m_sigma"]),
            max_entries=int(rules["max_entries_per_day"]),
            cost_rt_bp=float(rules["cost_round_trip_bp"]) * float(rules["stress_cost_mult"]),
            or_minutes=int(rules["or_minutes"]),
            buffer_frac=float(rules["or_buffer_sigma_frac"]),
        )
        if pnl is None:
            continue
        rr = dict(r)
        rr["reversion_pnl"] = pnl.reversion_pnl
        rr["breakout_pnl"] = pnl.breakout_pnl
        rr["regime_score"] = pnl.regime_score
        stress_rows.append(rr)

    per_index: dict[str, Any] = {}
    for tk in tickers:
        rows = [r for r in enriched if r["ticker"] == tk]
        sign = _sign_validation(rows)
        wf_res = _walk_forward_conditioned(
            rows,
            min_train=int(wf["min_train_days"]),
            embargo=int(wf["embargo_days"]),
            test_block=int(wf["test_block_days"]),
            seed=int(prereg["randomness"]["seed"]),
        )
        shuf = _shuffle_null(rows, seed=int(prereg["randomness"]["seed"])) if rows else {}
        stress_tk = [r for r in stress_rows if r["ticker"] == tk]
        stress_wf = _walk_forward_conditioned(
            stress_tk,
            min_train=int(wf["min_train_days"]),
            embargo=int(wf["embargo_days"]),
            test_block=int(wf["test_block_days"]),
            seed=int(prereg["randomness"]["seed"]),
        ) if stress_tk else {"status": "NO_STRESS_ROWS"}

        n_test = 0
        if wf_res.get("status") == "OK":
            n_test = int(wf_res["conditioned"]["n_days"])
        sample_ok = n_test >= int(prereg["sample_floor_test_days"])
        screen_alive = False
        if wf_res.get("status") == "OK" and sample_ok:
            c = wf_res["conditioned"]
            screen_alive = bool(
                c["mean_net_dollars"] > 0
                and c["ci_excludes_0"]
                and wf_res["beats_best_unconditional"]
                and shuf.get("real_outside_shuffle_ci")
                and stress_wf.get("status") == "OK"
                and stress_wf["conditioned"]["mean_net_dollars"] > 0
            )
        per_index[tk] = {
            "n_morning_days": len(rows),
            "et_date_first": rows[0]["et_date"] if rows else None,
            "et_date_last": rows[-1]["et_date"] if rows else None,
            "sign_validation": sign,
            "walk_forward": wf_res,
            "shuffle_null": shuf,
            "stress_2x_cost": stress_wf,
            "sample_floor_met": sample_ok,
            "screen_pulse": "ALIVE_CANDIDATE" if screen_alive else "NULL_OR_WEAK",
            "not_edge": True,
        }

    # pooled (disclosed correlated — diagnostic only)
    pooled_rows = list(enriched)
    pooled = {
        "n_rows": len(pooled_rows),
        "note": "same-day cross-ticker rows correlated — not 3x independent n",
        "sign_validation": _sign_validation(pooled_rows),
        "walk_forward": _walk_forward_conditioned(
            pooled_rows,
            min_train=int(wf["min_train_days"]),
            embargo=int(wf["embargo_days"]),
            test_block=int(wf["test_block_days"]),
            seed=int(prereg["randomness"]["seed"]),
        ),
    }

    return {
        "schema": "gex_r1_screen_eval_v1",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "card_id": "GEX-R1-SCREEN",
        "status_label": "SCREEN_NOT_VERDICT",
        "db_path": str(db_path),
        "prereg": prereg,
        "skipped_no_bars": skipped_no_bars,
        "per_index": per_index,
        "pooled_diagnostic": pooled,
        "honesty": prereg["limits"]
        + [
            "Nothing here is edge until Claude independently rebuilds gex_0dte, verifies sign, and clears shuffle null.",
            "Pass/fail is money after costs (§8.6), not classification accuracy.",
        ],
    }


def write_reports(result: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    eval_path = REPORT_DIR / "gex_r1_screen_eval_latest.json"
    eval_path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    lines = [
        "# GEX-R1-SCREEN sign-build note",
        "",
        f"**Generated:** {result['generated_utc']}",
        "**Label:** SCREEN, not verdict. Not edge.",
        "",
        "## Sign validation (§8.7 gate 1)",
        "",
    ]
    for tk, block in result["per_index"].items():
        sv = block["sign_validation"]
        lines += [
            f"### {tk}",
            f"- morning days: {block['n_morning_days']} ({block['et_date_first']} → {block['et_date_last']})",
            f"- +GEX n={sv['n_pos_gex']} mean regime_score={sv['mean_regime_score_pos_gex']}",
            f"- −GEX n={sv['n_neg_gex']} mean regime_score={sv['mean_regime_score_neg_gex']}",
            f"- orientation: **{sv['sign_orientation']}**",
            f"- net_gamma sign agreement: {sv['net_gamma_sign_agreement_rate']}",
            f"- screen_pulse: **{block['screen_pulse']}** (sample_floor_met={block['sample_floor_met']})",
            "",
        ]
    lines += [
        "## Economic walk-forward (dollars after 1bp RT cost)",
        "",
        "See `reports/gex_r1_screen_eval_latest.json` → `per_index.*.walk_forward`.",
        "",
        "## Limits",
        "",
    ]
    for lim in result["honesty"]:
        lines.append(f"- {lim}")
    (REPORT_DIR / "gex_r1_screen_signbuild_note.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GEX-R1-SCREEN history screen")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    args = ap.parse_args(argv)
    print(f"gex_r1_screen: loading {args.db} …", flush=True)
    result = run_screen(args.db)
    write_reports(result)
    for tk, block in result["per_index"].items():
        wf = block["walk_forward"]
        mean = None
        if wf.get("status") == "OK":
            mean = wf["conditioned"]["mean_net_dollars"]
        print(
            f"  {tk}: days={block['n_morning_days']} pulse={block['screen_pulse']} "
            f"sign={block['sign_validation']['sign_orientation']} cond_mean={mean}",
            flush=True,
        )
    print("wrote reports/gex_r1_screen_eval_latest.json", flush=True)
    print("wrote reports/gex_r1_screen_signbuild_note.md", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
