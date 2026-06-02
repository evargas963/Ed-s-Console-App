"""Feature CURATION GATE (pre-ablation, no trained model needed) — feature epic step 1-2.

Operator + research-agreed funnel: CURATE then ablate ONCE (no train/ablate/train loop).
This tool does the model-free curation so that when the Stage-2 retrain finishes, ablation
runs on a clean candidate set (populated + de-duplicated + leakage-flagged), not raw columns.

Implements the agreed method (feature_assignment_matrix_v2 / deep-research):
  1. POPULATION purge — drop columns that are all/near-NULL (dead: e.g. bid_ask_imbalance,
     retired sentiment) across the training tickers.
  2. SPEARMAN-HIERARCHICAL clustering — collapse correlated sibling families (m5_ lag dups,
     gamma/delta/oi wall families) to ONE representative per cluster, so ablation importance
     isn't split across siblings (the "reads as zero" failure).
  3. LEAKAGE FLAG — surface model-output-class columns that must NOT enter the feature set
     (pred_*/fusion_*/mc_*/regime_*/rules_*/validation_*) + combined_signal (verify pre-decision).

Read-only on the DB. Output: governance/artifacts/feature_curation_gate.json (the clean
candidate set + cluster map + drop/flag lists) for Cursor scrutiny + the ablation harness.

Usage: python tools/feature_curation_gate.py [--tickers SPY,QQQ,IWM] [--null-thresh 0.98]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

import numpy as np
import pandas as pd
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform
from scipy.stats import spearmanr

from db import DB_PATH

# Leakage class = the CANONICAL forbidden families from feature_contracts (single source of
# truth — do NOT maintain a divergent list here; an earlier divergent list missed combined_*,
# which is post-compute_call policy output written back into snapshots = confirmed circular
# leakage, NOT "verify-suspect"). market-output prefixes added for the wider snapshot scan.
CONTRACT_FORBIDDEN_PREFIXES = ("rules_", "pred_", "combined_", "policy_")  # == feature_contracts.build_xgb_registry
LEAKAGE_PREFIXES = CONTRACT_FORBIDDEN_PREFIXES + (
    "fusion_", "fused_", "mc_", "regime_", "validation_", "xgb_", "lstm_", "transformer_",
)
OUT = Path("governance/artifacts/feature_curation_gate.json")
OVERRIDES_PATH = Path("governance/artifacts/feature_curation_overrides.json")
MANIFEST_PATH = Path("governance/artifacts/feature_ablation_manifest.json")
ABLATION_REPORT_PATH = Path("governance/artifacts/feature_ablation_report.json")


def _protected_db_columns() -> set[str]:
    """Columns that must all stay in the clean set (never collapsed to one cluster rep)."""
    if not OVERRIDES_PATH.is_file():
        return set()
    data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    out: set[str] = set()
    for group in data.get("keep_all_members", []):
        if isinstance(group, dict):
            for col in group.get("members", []):
                if isinstance(col, str) and col.strip():
                    out.add(col.strip())
    return out


def _feature_cone() -> dict:
    """The registered feature columns, from the live code (single source of truth)."""
    import ml_train as t
    import lstm_data as l
    xgb = list(dict.fromkeys(
        list(t.DOLLAR_COLS) + list(t.WALL_DISTANCE_COLS) + list(t.SCALE_INVARIANT_COLS)
        + list(t.CATEGORICALS) + list(t.TIME_COLS)
    ))
    return {
        "xgb": xgb,
        "lstm_5m": list(l.FEATURES_5M),
        "lstm_1m": list(l.FEATURES_1M),
    }


def run(tickers, null_thresh, cluster_thresh):
    cone = _feature_cone()
    # Union of all numeric feature columns we can pull from the normalized table.
    candidate_cols = sorted(set(cone["xgb"]) | set(cone["lstm_5m"]) | set(cone["lstm_1m"]))

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    have = {r[1] for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)")}
    tk_clause = ",".join("?" for _ in tickers)
    present = [c for c in candidate_cols if c in have]
    missing = [c for c in candidate_cols if c not in have]  # registered but NO column = dead

    # ---- 1. POPULATION ----
    total = conn.execute(
        f"SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker IN ({tk_clause}) AND timeframe='1m'",
        tickers,
    ).fetchone()[0]
    pop = {}
    for c in present:
        nn = conn.execute(
            f'SELECT COUNT("{c}") FROM snapshots_1m_normalized WHERE ticker IN ({tk_clause}) AND timeframe=\'1m\'',
            tickers,
        ).fetchone()[0]
        pop[c] = (nn / total) if total else 0.0
    dead = [c for c in present if pop[c] <= (1.0 - null_thresh)]  # ~all-NULL
    live = [c for c in present if c not in dead]

    # ---- numeric matrix for correlation (live, numeric-coercible only) ----
    df = pd.read_sql_query(
        f'SELECT {", ".join(chr(34)+c+chr(34) for c in live)} '
        f"FROM snapshots_1m_normalized WHERE ticker IN ({tk_clause}) AND timeframe='1m'",
        conn, params=tickers,
    )
    conn.close()
    num = df.apply(pd.to_numeric, errors="coerce")
    numeric_cols = [c for c in live if num[c].notna().mean() > 0.5 and num[c].std(skipna=True) > 0]
    catish = [c for c in live if c not in numeric_cols]  # categoricals / constant — not clustered

    # ---- 2. SPEARMAN-HIERARCHICAL CLUSTER ----
    clusters, representatives = {}, []
    if len(numeric_cols) >= 2:
        X = num[numeric_cols].fillna(num[numeric_cols].median())
        rho, _ = spearmanr(X.values)
        rho = np.atleast_2d(rho)
        if rho.shape[0] == len(numeric_cols):
            dist = 1.0 - np.abs(np.nan_to_num(rho, nan=0.0))
            np.fill_diagonal(dist, 0.0)
            dist = (dist + dist.T) / 2.0
            Z = hierarchy.linkage(squareform(dist, checks=False), method="average")
            labels = hierarchy.fcluster(Z, t=cluster_thresh, criterion="distance")
            by = defaultdict(list)
            for col, lab in zip(numeric_cols, labels):
                by[int(lab)].append(col)
            for lab, members in sorted(by.items()):
                # representative = highest-populated member (ties: shortest name = most "base")
                rep = sorted(members, key=lambda c: (-pop.get(c, 0), len(c)))[0]
                clusters[f"cluster_{lab}"] = {"members": sorted(members), "representative": rep,
                                              "redundant_dropped": sorted(set(members) - {rep})}
                representatives.append(rep)

    # ---- 3. LEAKAGE EXCLUSION (canonical forbidden families) ----
    # combined_signal/combined_conviction = ms.call_signal/call_conviction written back into the
    # snapshot AFTER compute_call (market_state.py:1407 -> server.py:4893) = post-decision policy
    # output fed back as a feature = circular leakage. Forbidden by feature_contracts. EXCLUDE
    # from the clean set entirely (not "verify").
    leakage_in_cone = sorted(c for c in present if c.startswith(LEAKAGE_PREFIXES))
    protected = _protected_db_columns() & set(live)
    # reps + categoricals + override-protected members, MINUS leakage-class columns
    clean_candidates = sorted(
        (set(representatives) | set(catish) | protected) - set(leakage_in_cone)
    )
    out = {
        "tickers": tickers, "rows_analyzed": total,
        "thresholds": {"null_thresh": null_thresh, "cluster_distance_thresh": cluster_thresh},
        "override_protected_columns": sorted(protected),
        "counts": {
            "registered_candidates": len(candidate_cols),
            "missing_columns_DEAD": len(missing),
            "near_null_DEAD": len(dead),
            "live_numeric": len(numeric_cols), "live_categorical_or_const": len(catish),
            "clusters": len(clusters),
            "clean_candidate_set": len(clean_candidates),
            "redundant_dropped": sum(len(c["redundant_dropped"]) for c in clusters.values()),
        },
        "DEAD_missing_column": sorted(missing),
        "DEAD_near_null": sorted(dead),
        "leakage_class_EXCLUDED": leakage_in_cone,
        "clusters": clusters,
        "clean_candidate_set": clean_candidates,
        "note": "Curation gate (model-free). Steps 3-6 of the funnel (held-out permutation, "
                "grouped MDA, SHAP-interaction) run AFTER the Stage-2 retrain on the trained "
                "models. This file is the clean candidate set + cluster map for that one pass.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


# ------------------------------------------------------------------------------
# Ablation harness — manifest-only contract (grouped permutation grid)
# ------------------------------------------------------------------------------


def load_ablation_manifest(path: Path | None = None) -> dict:
    """Load the signable ablation contract. Does not read gate JSON or overrides."""
    p = Path(path) if path is not None else MANIFEST_PATH
    if not p.is_file():
        raise FileNotFoundError(f"missing ablation manifest: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def ablation_groups(manifest: dict) -> list[dict]:
    """Groups with disposition ABLATE (primary permutation targets)."""
    return sorted(
        (g for g in manifest.get("groups", []) if g.get("disposition") == "ABLATE"),
        key=lambda g: str(g.get("group_id", "")),
    )


def ablation_grid_cell_specs(manifest: dict) -> list[dict]:
    """Cartesian grid: anchor × model × horizon × ABLATE group."""
    method = manifest["ablation_method"]
    cells: list[dict] = []
    for anchor in method["anchors"]:
        for model in method["models"]:
            for hz in method["horizons"]:
                for grp in ablation_groups(manifest):
                    members = grp.get("members") or {}
                    cells.append(
                        {
                            "anchor_ticker": anchor,
                            "model_family": model,
                            "horizon_slug": hz,
                            "group_id": grp["group_id"],
                            "xgb_members": list(members.get("xgb") or []),
                            "lstm_5m_members": list(members.get("lstm_5m") or []),
                            "lstm_1m_members": list(members.get("lstm_1m") or []),
                        }
                    )
    return cells


def permute_group_columns_together(
    X: pd.DataFrame,
    columns: list[str],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Grouped permutation: one row shuffle applied to all group member columns."""
    out = X.copy()
    present = [c for c in columns if c in out.columns]
    if not present or len(out) == 0:
        return out
    perm = rng.permutation(len(out))
    for col in present:
        out[col] = out[col].iloc[perm].to_numpy()
    return out


def _matthews_corrcoef_safe(y_true, y_pred) -> float | None:
    from sklearn.metrics import matthews_corrcoef

    if len(y_true) == 0:
        return None
    try:
        return float(matthews_corrcoef(y_true, y_pred))
    except ValueError:
        return None


def run_xgb_grouped_permutation_for_cell(
    *,
    ticker: str,
    horizon_slug: str,
    group_id: str,
    xgb_members: list[str],
    db_path: str,
    val_fraction: float = 0.2,
    random_state: int = 42,
    min_rows: int = 200,
) -> dict:
    """One manifest grid cell: chronological holdout grouped permutation (XGB path)."""
    from ml_data_common import holdout_class_metrics, time_ordered_tail_split
    from ml_horizon import normalize_ml_horizon_slug, outcome_column
    from ml_train import (
        apply_xgb_imputation_matrix,
        encode_target,
        engineer_features,
        get_model,
        load_data,
    )

    hz = normalize_ml_horizon_slug(horizon_slug)
    label_col = outcome_column(hz)
    df = load_data(
        db_path=db_path,
        ticker=ticker,
        ml_horizon_slug=hz,
        label_column=label_col,
    )
    if len(df) < min_rows:
        return {
            "anchor_ticker": ticker,
            "model_family": "xgb",
            "horizon_slug": hz,
            "group_id": group_id,
            "status": "skipped",
            "reason": f"insufficient_rows:{len(df)}",
        }

    train_end, n_val = time_ordered_tail_split(len(df))
    if n_val <= 0:
        return {
            "anchor_ticker": ticker,
            "model_family": "xgb",
            "horizon_slug": hz,
            "group_id": group_id,
            "status": "skipped",
            "reason": "no_chronological_holdout",
        }

    X, feat_names, _, _ = engineer_features(df, fit_end=train_end)
    y = encode_target(df, label_col)
    X_train = X.iloc[:train_end]
    y_train = y[:train_end]
    X_val = X.iloc[train_end:].copy()
    y_val = y[train_end:]

    med = X_train.median()
    impute = {f: float(med[f]) if pd.notna(med[f]) else 0.0 for f in feat_names}
    x_train = apply_xgb_imputation_matrix(
        X_train.values.astype(np.float64), feat_names, impute
    )
    x_val = apply_xgb_imputation_matrix(
        X_val.values.astype(np.float64), feat_names, impute
    )

    model = get_model(n_classes=3, early_stopping_rounds=None)
    model.fit(x_train, y_train)
    baseline_pred = model.predict(x_val)
    baseline_mcc = _matthews_corrcoef_safe(y_val, baseline_pred)
    baseline_hcm = holdout_class_metrics(y_val, baseline_pred, 3)

    rng = np.random.default_rng(random_state)
    x_val_perm = permute_group_columns_together(
        pd.DataFrame(x_val, columns=feat_names),
        xgb_members,
        rng,
    ).values.astype(np.float64)
    perm_pred = model.predict(x_val_perm)
    perm_mcc = _matthews_corrcoef_safe(y_val, perm_pred)
    perm_hcm = holdout_class_metrics(y_val, perm_pred, 3)

    return {
        "anchor_ticker": ticker,
        "model_family": "xgb",
        "horizon_slug": hz,
        "group_id": group_id,
        "status": "ok",
        "xgb_members_permuted": list(xgb_members),
        "holdout_rows": int(n_val),
        "baseline_mcc": baseline_mcc,
        "permuted_mcc": perm_mcc,
        "mcc_delta": (
            None
            if baseline_mcc is None or perm_mcc is None
            else round(baseline_mcc - perm_mcc, 6)
        ),
        "baseline_per_class_recall": baseline_hcm.get("per_class_recall"),
        "permuted_per_class_recall": perm_hcm.get("per_class_recall"),
    }


def build_ablation_report(
    manifest_path: Path | None = None,
    *,
    db_path: str | None = None,
    dry_run: bool = False,
    tickers: list[str] | None = None,
    horizons: list[str] | None = None,
    models: list[str] | None = None,
) -> dict:
    """Build grouped-permutation ablation report from manifest-only contract."""
    manifest = load_ablation_manifest(manifest_path)
    method = manifest["ablation_method"]
    groups = ablation_groups(manifest)
    cell_specs = ablation_grid_cell_specs(manifest)

    anchor_filter = set(tickers) if tickers else None
    horizon_filter = set(horizons) if horizons else None
    model_filter = set(models) if models else None

    report: dict = {
        "schema_version": "1",
        "source_manifest": str(manifest_path or MANIFEST_PATH),
        "manifest_totals": manifest.get("totals"),
        "ablation_method": method,
        "ablation_group_ids": [g["group_id"] for g in groups],
        "grid_cell_count": len(cell_specs),
        "cells": [],
    }
    if dry_run:
        report["dry_run"] = True
        report["cells"] = cell_specs
        return report

    db = db_path or str(DB_PATH)
    for spec in cell_specs:
        if anchor_filter and spec["anchor_ticker"] not in anchor_filter:
            continue
        if horizon_filter and spec["horizon_slug"] not in horizon_filter:
            continue
        if model_filter and spec["model_family"] not in model_filter:
            continue
        if spec["model_family"] == "xgb":
            report["cells"].append(
                run_xgb_grouped_permutation_for_cell(
                    ticker=spec["anchor_ticker"],
                    horizon_slug=spec["horizon_slug"],
                    group_id=spec["group_id"],
                    xgb_members=spec["xgb_members"],
                    db_path=db,
                )
            )
        else:
            report["cells"].append(
                {
                    **spec,
                    "status": "pending",
                    "reason": "lstm_transformer_grouped_permutation_not_wired",
                }
            )
    return report


def write_ablation_report(report: dict, path: Path | None = None) -> Path:
    out_path = path or ABLATION_REPORT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM")
    ap.add_argument("--null-thresh", type=float, default=0.98)
    ap.add_argument("--cluster-thresh", type=float, default=0.20,
                    help="hierarchical distance (1-|rho|); 0.20 => |rho|>=0.80 clustered")
    ap.add_argument("--ablation", action="store_true",
                    help="Run grouped-permutation ablation harness (manifest-only)")
    ap.add_argument("--ablation-dry-run", action="store_true",
                    help="Emit ablation grid from manifest without DB/model work")
    ap.add_argument("--manifest-path", default=str(MANIFEST_PATH))
    ap.add_argument("--report-path", default=str(ABLATION_REPORT_PATH))
    ap.add_argument("--horizons", default="", help="Optional comma list to filter ablation grid")
    ap.add_argument("--models", default="", help="Optional comma list to filter ablation grid")
    a = ap.parse_args()

    if a.ablation or a.ablation_dry_run:
        tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
        hz = [h.strip() for h in a.horizons.split(",") if h.strip()] or None
        models = [m.strip() for m in a.models.split(",") if m.strip()] or None
        report = build_ablation_report(
            Path(a.manifest_path),
            dry_run=a.ablation_dry_run,
            tickers=tickers if not a.ablation_dry_run else None,
            horizons=hz,
            models=models,
        )
        out_p = write_ablation_report(report, Path(a.report_path))
        print(
            f"wrote {out_p}  grid_cells={report['grid_cell_count']}  "
            f"ablation_groups={len(report['ablation_group_ids'])}  "
            f"dry_run={bool(report.get('dry_run'))}"
        )
        return

    out = run([t.strip().upper() for t in a.tickers.split(",")], a.null_thresh, a.cluster_thresh)
    c = out["counts"]
    print(f"rows={out['rows_analyzed']}  registered={c['registered_candidates']}")
    print(f"DEAD missing-col={c['missing_columns_DEAD']}  near-null={c['near_null_DEAD']}")
    print(f"clusters={c['clusters']}  redundant-dropped={c['redundant_dropped']}")
    print(f"CLEAN CANDIDATE SET = {c['clean_candidate_set']} (from {c['registered_candidates']})")
    print(f"leakage-class EXCLUDED: {out['leakage_class_EXCLUDED']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
