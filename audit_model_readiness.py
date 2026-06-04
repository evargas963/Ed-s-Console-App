#!/usr/bin/env python3
"""
audit_model_readiness.py — Evaluates training data quality for ALL models
before committing to training.

Run: python audit_model_readiness.py

Reports label availability, feature completeness for XGBoost/LSTM/Transformer,
meta-learner readiness, sequence availability, class balance, temporal coverage,
fusion feature completeness, and GO/NO-GO verdict per model.
"""

import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
from db import DB_PATH  # noqa: E402 — canonical resolver (ED_CONSOLE_DB / data/ed_console.db)

MODEL_DIR = SCRIPT_DIR / "models"

# Canonical 1m training default label = product live ML horizon (see ml_horizon).
from timeframe_config import CANONICAL_TIMEFRAME as _CANON_TF, SNAPSHOT_TABLE_1M
from ml_horizon import default_training_label_column, live_inference_horizon_slug, PRIMARY_DECISION_HORIZONS

CANONICAL_TARGET_COL = default_training_label_column()

# ── RTH filter: 09:30–16:00 ET, weekdays (Mon=1..Fri=5) ───────────────────────
RTH_WHERE = """
    (et_hour * 60 + et_minute) >= 570
    AND (et_hour * 60 + et_minute) < 960
    AND CAST(strftime('%w', substr(ts_et, 1, 10)) AS INTEGER) BETWEEN 1 AND 5
"""

# ── XGBoost: DB columns that feed engineer_features (ml_train.py) ──────────────
XGB_DOLLAR_COLS = [
    "candle_body_pts", "candle_range_pts", "nearest_above_dist", "nearest_below_dist"
]
XGB_WALL_COLS = [
    "dist_call_gamma_wall", "dist_put_gamma_wall", "dist_call_delta_wall",
    "dist_put_delta_wall", "dist_call_oi_wall", "dist_put_oi_wall",
    "dist_call_vanna_wall", "dist_put_vanna_wall", "dist_gamma_inflection",
    "dist_delta_inflection", "pin_width_pts",
]
XGB_SCALE_COLS = [
    "net_gamma", "net_delta", "charm_net", "put_call_oi_ratio",
    "spy_chg_pct", "qqq_chg_pct", "iwm_chg_pct", "vix_level", "vix_vs_prev",
    "vwap_dist_pts", "iv_level", "spy_weighted_push", "qqq_weighted_push", "iwm_weighted_push",
    "nvda_chg_pct", "aapl_chg_pct", "msft_chg_pct", "amzn_chg_pct",
    "googl_chg_pct", "avgo_chg_pct", "meta_chg_pct", "tsla_chg_pct",
    "kre_chg_pct", "xbi_chg_pct", "psci_chg_pct", "xrt_chg_pct",
    "zone_since_bars",  # DB column: holds 1m execution-layer data (alias for zone_since_bars_1m)
    "candle_volume", "spread", "atr", "iv_rank",
    "smart_money_score", "breakout_score", "pin_score",
]
XGB_TIME_COLS = ["et_hour", "et_minute"]
XGB_PRED_COLS = []
for hz in PRIMARY_DECISION_HORIZONS:
    for d in ["up", "down", "flat"]:
        XGB_PRED_COLS.append(f"pred_{hz}_{d}_prob")
XGB_CAT_COLS = [
    "zone", "prev_zone", "vwap_side", "candle_direction",
    "session_bucket", "vix_bucket", "charm_direction", "charm_magnitude",
    "iv_direction", "combined_signal", "combined_conviction",
    "pressure_label", "pressure_trend",
]
# bid_ask_imbalance or flow_imbalance (DB uses flow_imbalance)
XGB_IMB_COLS = ["flow_imbalance", "bid_ask_imbalance"]
XGB_ALL_DB_COLS = (
    ["spot"] + XGB_DOLLAR_COLS + XGB_WALL_COLS + XGB_SCALE_COLS +
    XGB_TIME_COLS + XGB_PRED_COLS + XGB_CAT_COLS + XGB_IMB_COLS
)
# Dedupe (flow_imbalance and bid_ask_imbalance — check flow_imbalance)
XGB_ALL_DB_COLS = list(dict.fromkeys(c for c in XGB_ALL_DB_COLS if c != "bid_ask_imbalance"))
# Training-readiness null gate: pred_* horizon columns are inference outputs — sparse NULL is expected.
XGB_TRAINING_NULL_COLS = [c for c in XGB_ALL_DB_COLS if c not in XGB_PRED_COLS]

# ── LSTM/Transformer: FEATURES_5M and FEATURES_1M (lstm_data.py) ───────────────
FEATURES_5M = [
    "spot", "candle_body_pts", "candle_range_pts", "vwap_dist_pts",
    "dist_call_gamma_wall", "dist_put_gamma_wall", "dist_gamma_inflection",
    "dist_delta_inflection", "dist_call_oi_wall", "dist_put_oi_wall",
    "net_gamma", "net_delta", "charm_net",
    "spy_chg_pct", "qqq_chg_pct", "iwm_chg_pct", "spy_weighted_push",
    "qqq_weighted_push", "iwm_weighted_push", "vix_level", "iv_level", "zone", "vwap_side",
]
FEATURES_1M = [
    "spot", "candle_body_pts", "candle_range_pts", "vwap_dist_pts",
    "net_gamma", "net_delta", "spy_chg_pct", "qqq_chg_pct",
    "vix_level", "iv_level", "zone", "vwap_side",
]

# ── Fusion columns ────────────────────────────────────────────────────────────
FUSION_COLS = [
    "fusion_dominant_direction", "fusion_prob_up", "fusion_prob_down",
    "fusion_prob_flat", "fusion_model_agreement", "fusion_confidence",
    "fusion_dominant", "fusion_breakout", "fusion_pinning",
    "fusion_continuation", "fusion_reversal", "fusion_vol_expansion",
    "fusion_mean_reversion", "fusion_n_models_active",
]

NULL_RATE_THRESHOLD = 0.30
MIN_XGB_ROWS = 5000
MIN_LSTM_DAYS_60 = 5
MIN_TRANSFORMER_DAYS_20 = 5
MIN_CLASS_PCT = 0.15
MAX_DOMINANT_PCT = 0.60
MIN_META_ROWS = 1000


def _connect():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _col_exists(conn, col):
    cur = conn.execute(
        f"SELECT 1 FROM pragma_table_info('{SNAPSHOT_TABLE_1M}') WHERE name = ?",
        (col,),
    )
    return cur.fetchone() is not None


def _count(conn, where_extra="", table: str = SNAPSHOT_TABLE_1M):
    """Count rows from normalized 1m table (training data source)."""
    q = f"SELECT COUNT(*) FROM {table} WHERE {RTH_WHERE}"
    if where_extra:
        q += " AND " + where_extra
    return conn.execute(q).fetchone()[0]


def _feature_null_flags(conn, cols: list[str], rth_total: int) -> list[str]:
    flags: list[str] = []
    for col in cols:
        if not _col_exists(conn, col):
            flags.append(col)
            continue
        null_cnt = conn.execute(
            f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} IS NULL"
        ).fetchone()[0]
        null_pct = (null_cnt / rth_total * 100) if rth_total > 0 else 100.0
        if null_pct > NULL_RATE_THRESHOLD * 100:
            flags.append(col)
    return flags


def _balance_primary_flags(conn) -> list[str]:
    flags: list[str] = []
    for horizon in PRIMARY_DECISION_HORIZONS:
        col = f"outcome_{horizon}"
        if not _col_exists(conn, col):
            continue
        tf_filter = f" AND timeframe = '{_CANON_TF}'" if horizon == "1c" else ""
        rows = conn.execute(f"""
            SELECT {col}, COUNT(*) as cnt
            FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} IS NOT NULL{tf_filter}
            GROUP BY {col}
        """).fetchall()
        total = sum(r["cnt"] for r in rows)
        if total == 0:
            continue
        for r in rows:
            pct = (r["cnt"] / total * 100)
            if pct < MIN_CLASS_PCT * 100 or pct > MAX_DOMINANT_PCT * 100:
                flags.append(f"{col}_{r[col]}")
    return [f for f in flags if f.startswith(f"{CANONICAL_TARGET_COL}_")]


def _spy_sequence_day_counts(conn) -> tuple[int, int]:
    days_rows = conn.execute(f"""
        SELECT substr(ts_et, 1, 10) as dt, COUNT(*) as cnt
        FROM {SNAPSHOT_TABLE_1M}
        WHERE ticker = 'SPY' AND timeframe = ? AND {RTH_WHERE}
        GROUP BY dt ORDER BY dt
    """, (_CANON_TF,)).fetchall()
    days_60 = sum(1 for r in days_rows if r["cnt"] >= 60)
    days_20 = sum(1 for r in days_rows if r["cnt"] >= 20)
    return days_60, days_20


def evaluate_training_readiness(db_path: Path | None = None) -> dict:
    """
    Programmatic GO/NO-GO for ml_scheduler pre_train_gate (ops_runner sequence).
    training_ok requires XGB + LSTM + Transformer data-quality gates (section 10).
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    if not path.exists():
        return {
            "training_ok": False,
            "reasons": [f"database not found: {path}"],
        }
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rth_total = _count(conn)
        trainable_where = f"timeframe = '{_CANON_TF}' AND {CANONICAL_TARGET_COL} IS NOT NULL"
        trainable_rows = _count(conn, trainable_where)
        xgb_flags = _feature_null_flags(conn, XGB_TRAINING_NULL_COLS, rth_total)
        lstm_flags = _feature_null_flags(conn, list(set(FEATURES_5M + FEATURES_1M)), rth_total)
        balance_primary_lbl = _balance_primary_flags(conn)
        days_60, days_20 = _spy_sequence_day_counts(conn)
        xgb_go = (
            trainable_rows >= MIN_XGB_ROWS
            and len(xgb_flags) == 0
            and len(balance_primary_lbl) == 0
        )
        lstm_go = (
            days_60 >= MIN_LSTM_DAYS_60
            and len(lstm_flags) == 0
            and len(balance_primary_lbl) == 0
        )
        trans_go = (
            days_20 >= MIN_TRANSFORMER_DAYS_20
            and len(lstm_flags) == 0
            and len(balance_primary_lbl) == 0
        )
        reasons: list[str] = []
        if not xgb_go:
            reasons.append("XGB NO-GO (rows/features/balance)")
        if not lstm_go:
            reasons.append("LSTM NO-GO (SPY sequence days/features/balance)")
        if not trans_go:
            reasons.append("Transformer NO-GO (SPY sequence days/features/balance)")
        training_ok = xgb_go and lstm_go and trans_go
        return {
            "training_ok": training_ok,
            "xgb_go": xgb_go,
            "lstm_go": lstm_go,
            "trans_go": trans_go,
            "trainable_rows": trainable_rows,
            "reasons": reasons,
        }
    finally:
        conn.close()


def main():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        return

    conn = _connect()

    print("=" * 72)
    print("MODEL READINESS AUDIT — Training Data Quality (Canonical 1m)")
    print(f"DB: {DB_PATH}  |  Timeframe: {_CANON_TF}  |  Target: {CANONICAL_TARGET_COL}")
    print("=" * 72)

    # Issue 14: trainable rows = label present; do not require outcome_filled (all horizons).
    trainable_where = f"timeframe = '{_CANON_TF}' AND {CANONICAL_TARGET_COL} IS NOT NULL"

    # ── 0. DB INVENTORY (scope — do not confuse raw logger table with training table) ─
    print("\n" + "-" * 72)
    print("0. DB INVENTORY (table scope)")
    print("-" * 72)
    raw_snap_total = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    norm_total = conn.execute(f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M}").fetchone()[0]
    print(f"   snapshots (raw logger, all tf/tickers):     {raw_snap_total:,}")
    print(f"   {SNAPSHOT_TABLE_1M} (training source):       {norm_total:,}")
    print("   Sections 1–10 below use normalized table + RTH filter unless labeled SPY-only.")
    spy_raw_1m = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT substr(ts_et, 1, 10)) "
        "FROM snapshots WHERE ticker = 'SPY' AND timeframe = ?",
        (_CANON_TF,),
    ).fetchone()
    print(
        f"   SPY raw snapshots ({_CANON_TF}):              {spy_raw_1m[0]:,} rows / "
        f"{spy_raw_1m[1]} calendar days"
    )
    try:
        from db import EdDB

        _cq = EdDB(DB_PATH).confluence_quote_tick_inventory()
        print(
            f"   confluence_quote_ticks (panel thin quotes):  {_cq['total_rows']:,} rows / "
            f"{_cq['distinct_tickers']} tickers"
        )
    except Exception as _cq_exc:
        print(f"   confluence_quote_ticks: unavailable ({_cq_exc})")

    # ── 1. LABEL AVAILABILITY ─────────────────────────────────────────────────
    print("\n" + "-" * 72)
    print("1. LABEL AVAILABILITY (all tickers, normalized, RTH)")
    print("-" * 72)

    rth_total = _count(conn)
    outcome_1c_cnt = _count(conn, f"timeframe = '{_CANON_TF}' AND {CANONICAL_TARGET_COL} IS NOT NULL")
    outcome_filled_cnt = _count(conn, "outcome_filled = 1")

    print(f"   Total RTH snapshots (09:30–16:00, weekdays): {rth_total:,}")
    print(f"   {CANONICAL_TARGET_COL} IS NOT NULL ({_CANON_TF}):             {outcome_1c_cnt:,}")
    print(f"   outcome_filled = 1 (all bar-spec horizons): {outcome_filled_cnt:,}")

    for horizon in PRIMARY_DECISION_HORIZONS:
        col = f"outcome_{horizon}"
        if not _col_exists(conn, col):
            print(f"\n   {col}: column not found")
            continue
        rows = conn.execute(f"""
            SELECT {col}, COUNT(*) as cnt
            FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} IS NOT NULL
            GROUP BY {col}
        """).fetchall()
        total = sum(r["cnt"] for r in rows)
        print(f"\n   {col} (n={total:,}):")
        for r in rows:
            pct = (r["cnt"] / total * 100) if total > 0 else 0
            print(f"      {r[col]}: {r['cnt']:,} ({pct:.1f}%)")

    # ── 2. XGBOOST FEATURE COMPLETENESS ────────────────────────────────────────
    print("\n" + "-" * 72)
    print("2. XGBOOST FEATURE COMPLETENESS")
    print("-" * 72)

    xgb_flags = []
    for col in XGB_ALL_DB_COLS:
        if not _col_exists(conn, col):
            null_pct = 100.0
            null_cnt = rth_total
        else:
            null_cnt = conn.execute(
                f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} IS NULL"
            ).fetchone()[0]
            null_pct = (null_cnt / rth_total * 100) if rth_total > 0 else 0
        zero_cnt = 0
        if _col_exists(conn, col):
            zero_cnt = conn.execute(
                f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} = 0"
            ).fetchone()[0]
        valid_pct = 100.0 - null_pct
        gate_col = col in XGB_TRAINING_NULL_COLS
        flag = " [!] >30% NULL" if null_pct > 30 and gate_col else (
            " (pred col — not in training null gate)" if null_pct > 30 and col in XGB_PRED_COLS else ""
        )
        if null_pct > 30 and gate_col:
            xgb_flags.append(col)
        print(f"   {col:35s}  NULL: {null_cnt:>8,}  zero: {zero_cnt:>8,}  valid: {valid_pct:5.1f}%{flag}")

    # ── 3. LSTM FEATURE COMPLETENESS ───────────────────────────────────────────
    print("\n" + "-" * 72)
    print("3. LSTM FEATURE COMPLETENESS (structure + micro streams — both 1m snapshots)")
    print("   Stream micro: 20×1m bars (FEATURES_1M) | structure: 60×1m bars (FEATURES_5M legacy name)")
    print("-" * 72)

    lstm_flags = []
    for col in set(FEATURES_5M + FEATURES_1M):
        if not _col_exists(conn, col):
            null_pct = 100.0
            null_cnt = rth_total
        else:
            null_cnt = conn.execute(
                f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} IS NULL"
            ).fetchone()[0]
            null_pct = (null_cnt / rth_total * 100) if rth_total > 0 else 0
        zero_cnt = conn.execute(
            f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} = 0"
        ).fetchone()[0] if _col_exists(conn, col) else 0
        valid_pct = 100.0 - null_pct
        flag = " [!] >30% NULL" if null_pct > 30 else ""
        if null_pct > 30:
            lstm_flags.append(col)
        print(f"   {col:35s}  NULL: {null_cnt:>8,}  zero: {zero_cnt:>8,}  valid: {valid_pct:5.1f}%{flag}")

    # ── 4. TRANSFORMER FEATURE COMPLETENESS ────────────────────────────────────
    print("\n" + "-" * 72)
    print("4. TRANSFORMER FEATURE COMPLETENESS")
    print("   (Same 1m snapshot streams as LSTM — encode_snapshot_5m = 60×1m structure lookback, not 5m candles)")
    print("-" * 72)
    print("   See section 3 — Transformer uses encode_snapshot_5m / FEATURES_5M on canonical 1m rows.")

    print("\n" + "-" * 72)
    print("5. ACTIVE BUNDLE READINESS (SPY — 4 horizons × xgb/lstm/transformer/meta)")
    print("-" * 72)

    active_dir = MODEL_DIR / "active" / "SPY"
    bundle_gaps: list[str] = []
    for hz in PRIMARY_DECISION_HORIZONS:
        files = {
            "xgb": active_dir / f"xgb_SPY_{hz}.pkl",
            "lstm": active_dir / f"lstm_SPY_{hz}.pt",
            "transformer": active_dir / f"transformer_SPY_{hz}.pt",
            "meta": active_dir / f"meta_SPY_{hz}.pkl",
        }
        print(f"\n   Horizon {hz}:")
        for kind, path in files.items():
            ok = path.exists()
            print(f"      {kind:12s} {'YES' if ok else 'NO':3s}  {path.name}")
            if not ok:
                bundle_gaps.append(f"{hz}:{kind}")
    if bundle_gaps:
        print(f"\n   INCOMPLETE: missing {len(bundle_gaps)} artifact(s): {', '.join(bundle_gaps)}")
    else:
        print("\n   All 16 SPY active artifacts present (4 horizons × 4 models).")

    _live_hz = live_inference_horizon_slug()
    meta_live = (active_dir / f"meta_SPY_{_live_hz}.pkl").exists()
    xgb_exists = (active_dir / f"xgb_SPY_{_live_hz}.pkl").exists()
    lstm_exists = (active_dir / f"lstm_SPY_{_live_hz}.pt").exists()
    trans_exists = (active_dir / f"transformer_SPY_{_live_hz}.pt").exists()
    print(f"\n   Live inference horizon ({_live_hz}) meta-learner: {'YES' if meta_live else 'NO'}")

    # ── 6. SEQUENCE AVAILABILITY (SPY) ───────────────────────────────────────
    print("\n" + "-" * 72)
    print(f"6. SEQUENCE AVAILABILITY (SPY only — normalized {_CANON_TF}, RTH)")
    print("-" * 72)

    from timeframe_config import CANONICAL_TIMEFRAME as _TF
    days_rows = conn.execute(f"""
        SELECT substr(ts_et, 1, 10) as dt, COUNT(*) as cnt
        FROM {SNAPSHOT_TABLE_1M}
        WHERE ticker = 'SPY' AND timeframe = ? AND {RTH_WHERE}
        GROUP BY dt ORDER BY dt
    """, (_TF,)).fetchall()

    distinct_days = len(days_rows)
    total_spy = sum(r["cnt"] for r in days_rows)
    avg_per_day = (total_spy / distinct_days) if distinct_days > 0 else 0
    days_60 = sum(1 for r in days_rows if r["cnt"] >= 60)
    days_20 = sum(1 for r in days_rows if r["cnt"] >= 20)
    days_lt20 = sum(1 for r in days_rows if r["cnt"] < 20)

    print(f"   Distinct trading days (SPY {_TF}):     {distinct_days}")
    print(f"   Total snapshots:                   {total_spy:,}")
    print(f"   Average snapshots per day:         {avg_per_day:.1f}")
    print(f"   Days with >= 60 snapshots (LSTM):  {days_60}")
    print(f"   Days with >= 20 snapshots (TR):   {days_20}")
    print(f"   Days with < 20 snapshots:         {days_lt20}")

    # ── 7. CLASS BALANCE (canonical default training label) ─────────────────────
    print("\n" + "-" * 72)
    print("7. CLASS BALANCE (per-horizon label present; no outcome_filled gate)")
    print("-" * 72)

    balance_flags = []
    for horizon in PRIMARY_DECISION_HORIZONS:
        col = f"outcome_{horizon}"
        if not _col_exists(conn, col):
            continue
        tf_filter = f" AND timeframe = '{_CANON_TF}'" if horizon == "1c" else ""
        rows = conn.execute(f"""
            SELECT {col}, COUNT(*) as cnt
            FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} IS NOT NULL{tf_filter}
            GROUP BY {col}
        """).fetchall()
        total = sum(r["cnt"] for r in rows)
        if total == 0:
            print(f"   {col}: no data")
            continue
        print(f"\n   {col} (n={total:,}):")
        for r in rows:
            pct = (r["cnt"] / total * 100)
            flags = []
            if pct < 15:
                flags.append("[!] <15%")
            if pct > 60:
                flags.append("[!] >60% dominant")
            flag_str = "  " + " ".join(flags) if flags else ""
            print(f"      {r[col]}: {r['cnt']:,} ({pct:.1f}%){flag_str}")
            if pct < 15 or pct > 60:
                balance_flags.append(f"{col}_{r[col]}")

    # ── 8. TEMPORAL COVERAGE ──────────────────────────────────────────────────
    print("\n" + "-" * 72)
    print("8. TEMPORAL COVERAGE")
    print("-" * 72)

    all_days = conn.execute(f"""
        SELECT substr(ts_et, 1, 10) as dt, COUNT(*) as cnt
        FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE}
        GROUP BY dt ORDER BY dt
    """).fetchall()

    # Single query for rules_signal per day (faster than N queries)
    sig_by_day = {}
    for row in conn.execute(f"""
        SELECT substr(ts_et, 1, 10) as dt, COALESCE(rules_signal, 'NULL') as sig, COUNT(*) as c
        FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE}
        GROUP BY dt, sig
    """).fetchall():
        dt, sig, c = row["dt"], row["sig"], row["c"]
        sig_by_day.setdefault(dt, []).append((sig, c))

    print("   Trading day        Rows   Thin?  rules_signal distribution")
    for r in all_days:
        thin = "[!] <100" if r["cnt"] < 100 else ""
        sig_rows = sig_by_day.get(r["dt"], [])
        sig_str = ", ".join(f"{s}:{c}" for s, c in sig_rows)
        print(f"   {r['dt']}  {r['cnt']:>6,}  {thin:6s}  {sig_str}")

    # ── 9. FUSION FEATURE COMPLETENESS ────────────────────────────────────────
    print("\n" + "-" * 72)
    print("9. FUSION FEATURE COMPLETENESS")
    print("-" * 72)

    for col in FUSION_COLS:
        if not _col_exists(conn, col):
            print(f"   {col:35s}  column not found")
            continue
        null_cnt = conn.execute(
            f"SELECT COUNT(*) FROM {SNAPSHOT_TABLE_1M} WHERE {RTH_WHERE} AND {col} IS NULL"
        ).fetchone()[0]
        null_pct = (null_cnt / rth_total * 100) if rth_total > 0 else 0
        print(f"   {col:35s}  NULL: {null_cnt:>8,}  ({null_pct:.1f}%)")

    # ── 10. SUMMARY VERDICT ───────────────────────────────────────────────────
    print("\n" + "-" * 72)
    print("10. SUMMARY VERDICT - GO / NO-GO per model")
    print("-" * 72)

    trainable_rows = _count(conn, trainable_where)

    # XGBoost (canonical timeframe + default training label column)
    balance_primary_lbl = [f for f in balance_flags if f.startswith(f"{CANONICAL_TARGET_COL}_")]
    xgb_go = (
        trainable_rows >= MIN_XGB_ROWS and
        len(xgb_flags) == 0 and
        len(balance_primary_lbl) == 0
    )
    xgb_reasons = []
    if trainable_rows < MIN_XGB_ROWS:
        xgb_reasons.append(f"need >= {MIN_XGB_ROWS} trainable rows ({_CANON_TF} + {CANONICAL_TARGET_COL}, have {trainable_rows:,})")
    if xgb_flags:
        xgb_reasons.append(f"features >30% NULL: {', '.join(xgb_flags[:5])}{'...' if len(xgb_flags)>5 else ''}")
    if balance_primary_lbl:
        xgb_reasons.append(f"{CANONICAL_TARGET_COL} class imbalance (<15% or >60%)")
    print(f"\n   XGBoost:      {'GO' if xgb_go else 'NO-GO'}")
    for r in xgb_reasons:
        print(f"      - {r}")
    if xgb_go:
        print("      - All criteria met.")

    # LSTM (same trainability gates as XGB for the default label)
    lstm_go = (
        days_60 >= MIN_LSTM_DAYS_60 and
        len(lstm_flags) == 0 and
        len(balance_primary_lbl) == 0
    )
    lstm_reasons = []
    if days_60 < MIN_LSTM_DAYS_60:
        lstm_reasons.append(f"need >= {MIN_LSTM_DAYS_60} days with 60+ snapshots (have {days_60})")
    if lstm_flags:
        lstm_reasons.append(f"features >30% NULL: {', '.join(lstm_flags)}")
    if balance_primary_lbl:
        lstm_reasons.append(f"{CANONICAL_TARGET_COL} class imbalance (<15% or >60%)")
    print(f"\n   LSTM:         {'GO' if lstm_go else 'NO-GO'}")
    for r in lstm_reasons:
        print(f"      - {r}")
    if lstm_go:
        print("      - All criteria met.")

    # Transformer (same feature/null gates; default-label balance)
    trans_go = (
        days_20 >= MIN_TRANSFORMER_DAYS_20 and
        len(lstm_flags) == 0 and
        len(balance_primary_lbl) == 0
    )
    trans_reasons = []
    if days_20 < MIN_TRANSFORMER_DAYS_20:
        trans_reasons.append(f"need >= {MIN_TRANSFORMER_DAYS_20} days with 20+ snapshots (have {days_20})")
    if lstm_flags:
        trans_reasons.append(f"features >30% NULL: {', '.join(lstm_flags)}")
    if balance_primary_lbl:
        trans_reasons.append(f"{CANONICAL_TARGET_COL} class imbalance (<15% or >60%)")
    print(f"\n   Transformer:  {'GO' if trans_go else 'NO-GO'}")
    for r in trans_reasons:
        print(f"      - {r}")
    if trans_go:
        print("      - All criteria met.")

    # Meta-learner
    all_base = xgb_exists and lstm_exists and trans_exists
    meta_go = all_base and trainable_rows >= MIN_META_ROWS
    meta_reasons = []
    if not all_base:
        meta_reasons.append(
            f"need all three base model files (xgb_SPY_{_live_hz}.pkl, lstm_SPY_{_live_hz}.pt, "
            f"transformer_SPY_{_live_hz}.pt) in models/active/SPY/"
        )
    if trainable_rows < MIN_META_ROWS:
        meta_reasons.append(f"need >= {MIN_META_ROWS} rows (have {trainable_rows:,})")
    print(f"\n   Meta-learner: {'GO' if meta_go else 'NO-GO'}")
    for r in meta_reasons:
        print(f"      - {r}")
    if meta_go:
        print("      - All criteria met.")

    # ── 11. ACTIVE ARTIFACT COMPLIANCE (provenance) ────────────────────────────
    print("\n" + "-" * 72)
    print("11. ACTIVE ARTIFACT COMPLIANCE (ML-training tickers only; excludes panel_auto)")
    print("-" * 72)
    try:
        from verify_active_models import check_artifact_compliance, _get_active_tickers
        tickers = _get_active_tickers()
        non_compliant = []
        for tkr in tickers:
            r = check_artifact_compliance(tkr)
            status = "OK" if r["compliant"] else "NON-COMPLIANT"
            print(f"   {tkr}: {status}")
            if not r["compliant"]:
                non_compliant.append(tkr)
                for iss in r.get("issues", [])[:3]:
                    print(f"      ! {iss}")
        if non_compliant:
            print("\n   Run: python ml_scheduler.py --run-now --force-retrain")
        else:
            print("   All active artifacts compliant with governed pipeline.")
    except Exception as e:
        print(f"   Verification skipped: {e}")

    print("\n" + "=" * 72)

    _gate = evaluate_training_readiness(DB_PATH)
    if not _gate.get("training_ok"):
        print("\nPRE-TRAIN GATE: NO-GO — fix data quality before ml_scheduler --run-now")
        for _r in _gate.get("reasons") or []:
            print(f"   - {_r}")
        sys.exit(1)
    print("\nPRE-TRAIN GATE: GO (XGB + LSTM + Transformer data-quality criteria met)")


if __name__ == "__main__":
    main()
