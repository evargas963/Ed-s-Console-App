"""One-off: compare _diag_spy.json vs _diag_qqq.json — pipeline order for first divergence."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPY = json.loads((ROOT / "_diag_spy.json").read_text(encoding="utf-8"))
QQQ = json.loads((ROOT / "_diag_qqq.json").read_text(encoding="utf-8"))


def tri(d, hz):
    u, dn, f = d.get(f"up_prob_{hz}"), d.get(f"down_prob_{hz}"), d.get(f"flat_prob_{hz}")
    return u, dn, f, (u is None or dn is None or f is None)


STAGES = [
    ("A_api", ["server_ts", "selected_exp"]),
    (
        "B_model_fusion_canonical",
        [
            "fusion_available",
            "fusion_n_models_active",
            "xgb_available",
            "lstm_available",
            "transformer_available",
            "dominant_dir",
            "confidence",
            "canonical_provenance",
            "forward_provenance",
        ],
    ),
    (
        "C_empirical",
        [
            "samples_used",
            "match_tier",
            "tier_label",
            "empirical_confidence",
        ],
    ),
]

HZ = ("1c", "5c", "15c", "60c")


def main():
    print("=== SPY vs QQQ (from /api/state JSON, force=1) ===\n")
    first = None
    for stage, keys in STAGES:
        print(f"--- {stage} ---")
        for k in keys:
            a, b = SPY.get(k), QQQ.get(k)
            same = a == b
            print(f"  {k}: SPY={a!r} QQQ={b!r}  {'SAME' if same else 'DIFF'}")
            if not same and first is None:
                first = (stage, k, a, b)
        print()

    print("--- C_horizon_triplets ---")
    for hz in HZ:
        a = tri(SPY, hz)
        b = tri(QQQ, hz)
        same = a == b
        print(f"  {hz}: SPY up,dn,fl,any_none={a} | QQQ={b}  {'SAME' if same else 'DIFF'}")
        if not same and first is None:
            first = ("C_horizon_triplets", hz, a, b)
    print()

    SPY.get("timeframe_reads")  # wrong - horizon_prob_bars might not be top-level
    # MarketState may not serialize horizon_prob_bars - check
    for key in ("horizon_prob_bars",):
        if key in SPY or key in QQQ:
            print(f"--- {key} ---")
            print("  SPY:", json.dumps(SPY.get(key), default=str)[:500])
            print("  QQQ:", json.dumps(QQQ.get(key), default=str)[:500])
            if SPY.get(key) != QQQ.get(key) and first is None:
                first = (key, "blob", SPY.get(key), QQQ.get(key))

    print("--- D_mhap_rows ---")
    rs, rq = SPY.get("mhap_rows") or [], QQQ.get("mhap_rows") or []
    for i, hz in enumerate(["1c", "5c", "15c", "60c"]):
        row_s = rs[i] if i < len(rs) else {}
        row_q = rq[i] if i < len(rq) else {}
        if row_s != row_q:
            print(f"  {hz} DIFF\n    SPY: {row_s}\n    QQQ: {row_q}")
            if first is None:
                first = ("D_mhap", hz, row_s, row_q)
        else:
            print(f"  {hz} SAME {row_s}")

    print("\n--- E_final_decision ---")
    finals = [
        "final_bias",
        "final_tradeable",
        "primary_horizon",
        "trade_mode",
        "alignment_state_display",
        "contradiction_state",
        "conflict_level_display",
        "wait_reason",
        "entry_state",
        "call_signal",
        "call_conviction",
        "validation_summary",
        "entry_display_text",
    ]
    for k in finals:
        a, b = SPY.get(k), QQQ.get(k)
        if a != b:
            print(f"  DIFF {k}: SPY={a!r} QQQ={b!r}")
            if first is None:
                first = ("E_final", k, a, b)
        else:
            print(f"  SAME {k}: {a!r}")

    print("\n=== FIRST DIVERGENCE (pipeline order scan) ===")
    print(first)


if __name__ == "__main__":
    main()
