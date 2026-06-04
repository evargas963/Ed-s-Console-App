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

Ablation harness (``--ablation``): manifest-only contract (O-56) — **all four horizons**
(1c / 5c / 15c / 60c) and **all six stack layers**. Partial-horizon runs are rejected.

  - **Primary — per-model grouped permutation (feature→model→horizon):** grid is
    anchor × **model** × horizon × ABLATE-group. For each (anchor, model, horizon) the base model
    (XGB / LSTM / Transformer) is trained on a chronological holdout, each ABLATE group is
    grouped-permuted, and THAT model's **MCC delta** is recorded. Each base model gets its OWN
    per-horizon survivor set (``survivor_summary.by_model_horizon[model][horizon]``).
  - **Stack authority (separate pass):** per anchor×horizon ``full_fusion`` mode comparisons
    (base-model + meta / Monte Carlo / fusion lifts). This is stack-component authority, NOT the
    feature ablation — it never replaces or collapses the per-model feature pass.

Usage: python tools/feature_curation_gate.py [--tickers SPY,QQQ,IWM] [--null-thresh 0.98]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import statistics
from collections import defaultdict
from datetime import datetime, timezone
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
ABLATION_LOCK_PATH = Path("governance/artifacts/feature_ablation.run.lock")
REQUIRED_ABLATION_HORIZONS = ("1c", "5c", "15c", "60c")
WHOLE_STACK_CELL_TARGET = 828  # O-56: per-model feature cells (3 anchors x 3 models x 4 hz x 23 groups)
FULL_STACK_LAYERS = ("xgb", "lstm", "transformer", "meta", "monte_carlo", "fusion")


def _required_ablation_horizons(manifest: dict) -> list[str]:
    method = manifest["ablation_method"]
    return list(method.get("horizons_required") or method["horizons"])


def _enforce_full_stack_ablation_contract(
    manifest: dict,
    *,
    horizons: list[str] | None,
) -> None:
    """Reject partial-horizon ablation — operator binding: entire stack, all timeframes."""
    required = _required_ablation_horizons(manifest)
    if horizons is not None and set(horizons) != set(required):
        raise SystemExit(
            f"Ablation requires ALL horizons {required}; partial runs are rejected (got {horizons})."
        )
    layers = list(manifest["ablation_method"].get("full_stack_layers") or FULL_STACK_LAYERS)
    if set(layers) != set(FULL_STACK_LAYERS):
        raise SystemExit(
            f"Ablation manifest must score all six stack layers {list(FULL_STACK_LAYERS)}; got {layers}."
        )


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
    """Groups with disposition ABLATE — full cartesian grid targets (no horizon pre-cull)."""
    return sorted(
        (g for g in manifest.get("groups", []) if g.get("disposition") == "ABLATE"),
        key=lambda g: str(g.get("group_id", "")),
    )


def ablation_whole_stack_feature_cell_specs(manifest: dict) -> list[dict]:
    """Cartesian grid: anchor × horizon × ABLATE group (production-path feature ablation)."""
    method = manifest["ablation_method"]
    full_stack_layers = list(method.get("full_stack_layers") or FULL_STACK_LAYERS)
    cells: list[dict] = []
    for anchor in method["anchors"]:
        for hz in method["horizons"]:
            for grp in ablation_groups(manifest):
                members = grp.get("members") or {}
                cells.append(
                    {
                        "anchor_ticker": anchor,
                        "horizon_slug": hz,
                        "group_id": grp["group_id"],
                        "ablation_kind": "whole_stack_feature_group",
                        "decision_mode": method.get("decision_mode", "full_fusion"),
                        "full_stack_layers": full_stack_layers,
                        "stack_layers_scored": full_stack_layers,
                        "xgb_members": list(members.get("xgb") or []),
                        "lstm_5m_members": list(members.get("lstm_5m") or []),
                        "lstm_1m_members": list(members.get("lstm_1m") or []),
                    }
                )
    return cells


def ablation_stack_authority_cell_specs(manifest: dict) -> list[dict]:
    """Cartesian grid: anchor × horizon for stack-component authority (not feature ablation)."""
    method = manifest["ablation_method"]
    stack_auth = method.get("stack_authority_pass") or method.get("stack_eval") or {}
    layers = list(method.get("stack_layers") or [])
    cells: list[dict] = []
    for anchor in method["anchors"]:
        for hz in method["horizons"]:
            cells.append(
                {
                    "anchor_ticker": anchor,
                    "horizon_slug": hz,
                    "ablation_kind": "stack_authority",
                    "stack_layers": layers,
                    "eval_engine": stack_auth.get("engine"),
                    "modes": list(stack_auth.get("modes") or []),
                }
            )
    return cells


def ablation_stack_layer_cell_specs(manifest: dict) -> list[dict]:
    """Backward-compatible alias for stack authority grid specs."""
    return ablation_stack_authority_cell_specs(manifest)


def _repo_models_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "models"


def _active_model_dir_for_ablation(
    ticker: str, horizon_slug: str
) -> tuple[Path | None, list[str]]:
    """Resolve production bundle for ablation/scoring — files must exist; label meta drift is warned not blocking."""
    from active_bundle_contract import active_bundle_dir, bundle_artifact_paths
    from ml_horizon import normalize_ml_horizon_slug

    models_dir = _repo_models_dir()
    hz = normalize_ml_horizon_slug(horizon_slug)
    t = ticker.strip().upper()
    bundle = active_bundle_dir(t, hz, models_dir=models_dir)
    if not bundle.is_dir():
        return None, [f"missing bundle dir: {bundle}"]
    issues: list[str] = []
    for _kind, model_path, meta_path in bundle_artifact_paths(t, hz, bundle):
        if not model_path.is_file():
            issues.append(f"missing {model_path.name}")
        if not meta_path.is_file():
            issues.append(f"missing {meta_path.name}")
    if issues:
        return None, issues
    return bundle, []


def _active_model_dir_for_stack_eval(ticker: str, horizon_slug: str) -> Path | None:
    """Resolve production active bundle dir for stack_bundle_eval (ticker leaf with artifacts)."""
    bundle, _issues = _active_model_dir_for_ablation(ticker, horizon_slug)
    return bundle


def _ablation_eval_options():
    from arch_competition.stack_bundle_eval_v1 import StackBundleEvalOptions

    opts = StackBundleEvalOptions(min_paired_rows=50)
    full_hist = os.environ.get("ED_ABLATION_FULL_HISTORY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    raw_max = os.environ.get("ED_ABLATION_MAX_ROWS", "").strip()
    if full_hist:
        opts.max_rows = None
    elif raw_max:
        opts.max_rows = int(raw_max)
    else:
        # Operational default: chronological tail — ~0.8s/row full_fusion on 54k+ RTH is multi-day.
        opts.max_rows = 500
    return opts


def _whole_stack_cell_key(anchor_ticker: str, horizon_slug: str, group_id: str) -> str:
    return f"{anchor_ticker.strip().upper()}|{horizon_slug}|{group_id}"


def _stack_authority_cell_key(anchor_ticker: str, horizon_slug: str) -> str:
    return f"{anchor_ticker.strip().upper()}|{horizon_slug}|stack_authority"


def _index_whole_stack_cells(cells: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in cells:
        if c.get("ablation_kind") != "whole_stack_feature_group":
            continue
        gid = c.get("group_id")
        if not gid:
            continue
        out[_whole_stack_cell_key(c["anchor_ticker"], c["horizon_slug"], gid)] = c
    return out


def _index_stack_authority_cells(cells: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in cells:
        if c.get("ablation_kind") != "stack_authority":
            continue
        out[_stack_authority_cell_key(c["anchor_ticker"], c["horizon_slug"])] = c
    return out


def run_ablation_preflight(
    manifest: dict,
    *,
    db_path: str,
    tickers: list[str] | None = None,
) -> dict:
    """Fail-closed readiness check before scored ablation (DB + active bundles)."""
    method = manifest["ablation_method"]
    anchors = tickers or list(method["anchors"])
    horizons = _required_ablation_horizons(manifest)
    dbp = Path(db_path)
    result: dict = {
        "ready": True,
        "db_path": str(dbp),
        "db_exists": dbp.is_file(),
        "anchors": anchors,
        "horizons": horizons,
        "bundle_checks": [],
        "issues": [],
    }
    if not dbp.is_file():
        result["ready"] = False
        result["issues"].append(f"database missing: {dbp}")
        return result
    try:
        con = sqlite3.connect(str(dbp))
        try:
            row = con.execute(
                "SELECT COUNT(*) FROM snapshots WHERE ticker=?",
                (anchors[0].upper(),),
            ).fetchone()
            result["snapshot_rows_sample_ticker"] = int(row[0]) if row else 0
            if result["snapshot_rows_sample_ticker"] < 100:
                result["ready"] = False
                result["issues"].append(
                    f"insufficient snapshots for {anchors[0]}: {result['snapshot_rows_sample_ticker']}"
                )
        finally:
            con.close()
    except Exception as ex:
        result["ready"] = False
        result["issues"].append(f"db_read_failed:{type(ex).__name__}:{ex}")

    for anchor in anchors:
        for hz in horizons:
            bundle, issues = _active_model_dir_for_ablation(anchor, hz)
            entry = {
                "anchor_ticker": anchor,
                "horizon_slug": hz,
                "bundle_dir": str(bundle) if bundle else None,
                "ready": bundle is not None,
                "issues": issues,
            }
            contract_note: list[str] = []
            if bundle is not None:
                from active_bundle_contract import check_active_bundle_complete

                chk = check_active_bundle_complete(
                    anchor, hz, bundle_dir=bundle, models_dir=_repo_models_dir()
                )
                if not chk.get("compliant"):
                    for kind, art in (chk.get("artifacts") or {}).items():
                        contract_note.extend(
                            f"{kind}:{msg}" for msg in (art.get("issues") or [])
                        )
                    entry["contract_warnings"] = contract_note
            if bundle is None:
                result["ready"] = False
                result["issues"].append(
                    f"incomplete bundle {anchor}/{hz}: {issues or ['unknown']}"
                )
            result["bundle_checks"].append(entry)
    return result


def build_ablation_survivor_summary(scored_cells: list[dict]) -> dict:
    """Roll up primary-pass scores — operator input before confirm pass / retrain."""
    by_mh: dict = defaultdict(lambda: defaultdict(list))
    for cell in scored_cells:
        if cell.get("ablation_kind") != "per_model_feature_group":
            continue
        key = (str(cell.get("model_family", "")), str(cell.get("horizon_slug", "")))
        by_mh[key][str(cell.get("group_id", ""))].append(cell)

    by_model_horizon: dict = {}
    flat_groups: list[dict] = []
    for (model, hz) in sorted(by_mh):
        grp_out: list[dict] = []
        for gid in sorted(by_mh[(model, hz)]):
            cells = by_mh[(model, hz)][gid]
            ok = [c for c in cells if c.get("status") == "ok"]
            deltas = [float(c["mcc_delta"]) for c in ok if c.get("mcc_delta") is not None]
            matters = sum(1 for c in ok if c.get("group_matters"))
            median_delta = round(statistics.median(deltas), 6) if deltas else None
            if not ok:
                rec = "UNSCORED"
            elif matters >= max(1, len(ok) // 2):
                rec = "KEEP_CANDIDATE"
            elif deltas and median_delta is not None and median_delta <= 1e-6:
                rec = "DROP_CANDIDATE"
            else:
                rec = "REVIEW"
            row = {
                "model_family": model,
                "horizon_slug": hz,
                "group_id": gid,
                "cells_total": len(cells),
                "cells_ok": len(ok),
                "cells_group_matters": matters,
                "median_mcc_delta": median_delta,
                "max_mcc_delta": round(max(deltas), 6) if deltas else None,
                "recommendation": rec,
            }
            grp_out.append(row)
            flat_groups.append(row)
        by_model_horizon.setdefault(model, {})[hz] = grp_out

    ok_total = sum(1 for c in scored_cells if c.get("status") == "ok")
    return {
        "primary_pass_only": True,
        "metric": "mcc_delta",
        "confirm_pass": "per_model_grouped_drop_column_refit__run_with_--ablation-confirm",
        "scored_cell_count": len(scored_cells),
        "ok_cell_count": ok_total,
        "skipped_cell_count": len(scored_cells) - ok_total,
        "by_model_horizon": by_model_horizon,
        "groups": flat_groups,
    }


def _write_ablation_checkpoint(report_path: Path, report: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = report_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(report_path)


def _stack_layer_lifts(
    metrics_by_config: dict,
    layer_comparisons: dict,
) -> dict:
    """Per-layer log_loss delta from stack_eval layer_comparisons contract."""
    lifts: dict = {}
    for layer_id, cmp in layer_comparisons.items():
        base_m = metrics_by_config.get(cmp.get("baseline")) or {}
        treat_m = metrics_by_config.get(cmp.get("treatment")) or {}
        b_ll = base_m.get("multiclass_log_loss")
        t_ll = treat_m.get("multiclass_log_loss")
        delta = None
        helps = None
        if b_ll is not None and t_ll is not None:
            delta = round(float(b_ll) - float(t_ll), 6)
            helps = bool(float(b_ll) - float(t_ll) > 1e-6)
        lifts[layer_id] = {
            "baseline_mode": cmp.get("baseline"),
            "treatment_mode": cmp.get("treatment"),
            "metric": cmp.get("metric", "multiclass_log_loss"),
            "description": cmp.get("description"),
            "baseline_log_loss": b_ll,
            "treatment_log_loss": t_ll,
            "log_loss_delta": delta,
            "treatment_helps": helps,
        }
    return lifts


def run_stack_layer_ablation_cell(
    *,
    ticker: str,
    horizon_slug: str,
    db_path: str,
    stack_eval: dict,
) -> dict:
    """One anchor×horizon cell: stack-component authority (base + upper layers)."""
    from arch_competition.stack_bundle_eval_v1 import run_stack_bundle_evaluation

    model_dir = _active_model_dir_for_stack_eval(ticker, horizon_slug)
    if model_dir is None:
        return {
            "anchor_ticker": ticker,
            "horizon_slug": horizon_slug,
            "status": "skipped",
            "reason": "incomplete_active_bundle",
        }
    modes = tuple(stack_eval.get("modes") or ())
    if not modes:
        return {
            "anchor_ticker": ticker,
            "horizon_slug": horizon_slug,
            "status": "skipped",
            "reason": "stack_eval_modes_empty",
        }
    manifest = run_stack_bundle_evaluation(
        db_path=db_path,
        ticker=ticker,
        model_dir=model_dir,
        ml_horizon_slug=horizon_slug,
        options=_ablation_eval_options(),
        modes=modes,
    )
    metrics = manifest.get("metrics_by_config") or {}
    lifts = _stack_layer_lifts(metrics, stack_eval.get("layer_comparisons") or {})
    base_model_lifts = _stack_layer_lifts(metrics, stack_eval.get("base_model_comparisons") or {})

    # Fail closed on degenerate meta: with meta_<T>_<hz>.pkl absent, stack_bundle_eval's meta_stack
    # mode falls back to the SAME weighted average as xgb_plus_lstm_plus_transformer, so the meta
    # lift is identically ~0 — that is "no meta artifact", NOT "meta does not help". Flag it instead
    # of emitting a misleading zero (the 'reads as zero' failure mode at the stack layer).
    from ml_horizon import normalize_ml_horizon_slug as _norm_hz

    _t = ticker.strip().upper()
    _hz = _norm_hz(horizon_slug)
    meta_present = (model_dir / f"meta_{_t}_{_hz}.pkl").is_file()
    if "meta" in lifts and not meta_present:
        lifts["meta"]["degenerate"] = True
        lifts["meta"]["degenerate_reason"] = (
            "meta_artifact_missing__meta_stack_falls_back_to_weighted_average"
        )
        lifts["meta"]["treatment_helps"] = None

    auth = manifest.get("authority_decision") or {}
    paired = int(manifest.get("paired_rows_all_modes") or 0)
    cell_status = "ok" if paired >= 50 else "failed"
    return {
        "anchor_ticker": ticker,
        "horizon_slug": horizon_slug,
        "status": cell_status,
        "model_dir": str(model_dir),
        "paired_rows": paired,
        "skip_reason_counts": manifest.get("skip_reason_counts"),
        "metrics_by_mode": {
            mode: {
                "n_rows_scored": m.get("n_rows_scored"),
                "multiclass_log_loss": m.get("multiclass_log_loss"),
                "balanced_accuracy": m.get("balanced_accuracy"),
                "macro_f1": m.get("macro_f1"),
            }
            for mode, m in metrics.items()
        },
        "layer_lifts": lifts,
        "base_model_lifts": base_model_lifts,
        "meta_artifact_present": meta_present,
        "authority": {
            "monte_carlo_improves": auth.get(
                "monte_carlo_improves_vs_fusion_without_mc_log_loss"
            ),
            "bayesian_fusion_improves_vs_meta": auth.get(
                "bayesian_fusion_improves_vs_meta_stack_log_loss"
            ),
            "full_fusion_beats_xgb_only": auth.get("full_fusion_beats_xgb_only_log_loss"),
        },
    }


def build_stack_authority_ablation_section(
    manifest: dict,
    *,
    db_path: str,
    dry_run: bool = False,
    tickers: list[str] | None = None,
    horizons: list[str] | None = None,
    resume_cells: dict[str, dict] | None = None,
    on_cell_done=None,
    cells_out: list[dict] | None = None,
) -> dict:
    """Stack-component authority section (base-model + meta/MC/fusion lifts)."""
    method = manifest["ablation_method"]
    stack_eval = method.get("stack_authority_pass") or method.get("stack_eval") or {}
    specs = ablation_stack_authority_cell_specs(manifest)
    anchor_filter = set(tickers) if tickers else None
    horizon_filter = set(horizons) if horizons else None
    resume_cells = resume_cells or {}
    scored_cells = cells_out if cells_out is not None else []

    section: dict = {
        "stack_layers": list(method.get("stack_layers") or []),
        "stack_authority_engine": stack_eval.get("engine"),
        "stack_authority_cell_count": len(specs),
        "stack_authority_cells": scored_cells,
        "stack_layer_cell_count": len(specs),
        "stack_layer_cells": scored_cells,
    }
    if dry_run:
        section["dry_run"] = True
        section["stack_authority_cells"] = specs
        section["stack_layer_cells"] = specs
        return section

    total = len(specs)
    done = 0
    for spec in specs:
        if anchor_filter and spec["anchor_ticker"] not in anchor_filter:
            continue
        if horizon_filter and spec["horizon_slug"] not in horizon_filter:
            continue
        ck = _stack_authority_cell_key(spec["anchor_ticker"], spec["horizon_slug"])
        if ck in resume_cells:
            cell = resume_cells[ck]
        else:
            cell = run_stack_layer_ablation_cell(
                ticker=spec["anchor_ticker"],
                horizon_slug=spec["horizon_slug"],
                db_path=db_path,
                stack_eval=stack_eval,
            )
        scored_cells.append(cell)
        done += 1
        if on_cell_done is not None:
            on_cell_done("stack_authority", cell, done, total)
    return section


def build_stack_layer_ablation_section(
    manifest: dict,
    *,
    db_path: str,
    dry_run: bool = False,
    tickers: list[str] | None = None,
    horizons: list[str] | None = None,
) -> dict:
    """Backward-compatible alias."""
    return build_stack_authority_ablation_section(
        manifest,
        db_path=db_path,
        dry_run=dry_run,
        tickers=tickers,
        horizons=horizons,
    )



def _per_model_cell_key(anchor: str, model: str, horizon: str, group_id: str) -> str:
    return f"{anchor.strip().upper()}|{model}|{horizon}|{group_id}"


def _index_per_model_cells(cells: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in cells:
        if c.get("ablation_kind") != "per_model_feature_group":
            continue
        if not c.get("group_id") or not c.get("model_family"):
            continue
        out[_per_model_cell_key(c["anchor_ticker"], c["model_family"], c["horizon_slug"], c["group_id"])] = c
    return out


def build_per_model_feature_ablation_section(
    manifest: dict,
    *,
    db_path: str,
    dry_run: bool = False,
    tickers: list[str] | None = None,
    horizons: list[str] | None = None,
    resume_cells: dict[str, dict] | None = None,
    on_cell_done=None,
    cells_out: list[dict] | None = None,
) -> dict:
    """O-56 primary: per (anchor, model, horizon) train base model on chronological holdout, then
    grouped-permute each ABLATE group and record THAT model's MCC delta. One trained model is cached
    and reused across all groups for an (anchor, model, horizon)."""
    specs = ablation_per_model_feature_cell_specs(manifest)
    anchor_filter = set(tickers) if tickers else None
    horizon_filter = set(horizons) if horizons else None
    resume_cells = resume_cells or {}
    scored_cells = cells_out if cells_out is not None else []
    section: dict = {
        "per_model_feature_cell_count": len(specs),
        "per_model_feature_cells": scored_cells,
    }
    if dry_run:
        section["dry_run"] = True
        section["per_model_feature_cells"] = specs
        return section

    runnable = [
        s for s in specs
        if (not anchor_filter or s["anchor_ticker"] in anchor_filter)
        and (not horizon_filter or s["horizon_slug"] in horizon_filter)
    ]
    total = len(runnable)
    done = 0
    prepared_cache: dict = {}
    _prep = {
        "xgb": _prepare_xgb_holdout,
        "lstm": _prepare_lstm_holdout,
        "transformer": _prepare_transformer_holdout,
    }
    for spec in runnable:
        model = spec["model_family"]
        ck = _per_model_cell_key(
            spec["anchor_ticker"], model, spec["horizon_slug"], spec["group_id"]
        )
        if ck in resume_cells:
            cell = resume_cells[ck]
        else:
            pk = (spec["anchor_ticker"], model, spec["horizon_slug"])
            prepared = prepared_cache.get(pk)
            if prepared is None:
                prepared = _prep[model](
                    ticker=spec["anchor_ticker"],
                    horizon_slug=spec["horizon_slug"],
                    db_path=db_path,
                )
                prepared_cache[pk] = prepared
            if prepared.get("status") != "ok":
                cell = {
                    "anchor_ticker": spec["anchor_ticker"],
                    "model_family": model,
                    "horizon_slug": prepared.get("hz", spec["horizon_slug"]),
                    "group_id": spec["group_id"],
                    "status": "skipped",
                    "reason": prepared.get("reason", "prep_failed"),
                    "ablation_kind": "per_model_feature_group",
                }
            elif model == "xgb":
                cell = _permute_eval_xgb_group(
                    prepared, ticker=spec["anchor_ticker"], group_id=spec["group_id"],
                    xgb_members=spec["xgb_members"],
                )
            elif model == "lstm":
                cell = _permute_eval_lstm_group(
                    prepared, ticker=spec["anchor_ticker"], group_id=spec["group_id"],
                    lstm_5m_members=spec["lstm_5m_members"],
                    lstm_1m_members=spec["lstm_1m_members"],
                )
            else:
                cell = _permute_eval_transformer_group(
                    prepared, ticker=spec["anchor_ticker"], group_id=spec["group_id"],
                    lstm_5m_members=spec["lstm_5m_members"],
                )
        scored_cells.append(cell)
        done += 1
        if on_cell_done is not None:
            on_cell_done("per_model_feature", cell, done, total)
    return section


def ablation_confirm_drop_group_ids(survivor_summary: dict) -> list[str]:
    """Groups flagged DROP_CANDIDATE by primary-pass survivor rollup."""
    out: list[str] = []
    for g in survivor_summary.get("groups") or []:
        if g.get("recommendation") == "DROP_CANDIDATE":
            out.append(str(g["group_id"]))
    return sorted(set(out))



def ablation_confirm_drops_by_model_horizon(survivor_summary: dict) -> dict:
    """{(model_family, horizon_slug): sorted [DROP_CANDIDATE group_ids]} from the per-model rollup."""
    out: dict = {}
    for model, by_hz in (survivor_summary.get("by_model_horizon") or {}).items():
        for hz, rows in by_hz.items():
            drops = sorted(r["group_id"] for r in rows if r.get("recommendation") == "DROP_CANDIDATE")
            if drops:
                out[(model, hz)] = drops
    return out


def _drop_members_for_model(manifest: dict, drop_group_ids: list[str]) -> tuple[list, list, list]:
    """Resolve DROP group_ids -> (xgb_cols, lstm_5m_members, lstm_1m_members) from the manifest."""
    by_id = {g["group_id"]: g for g in manifest.get("groups", [])}
    xgb, m5, m1 = [], [], []
    for gid in drop_group_ids:
        mem = (by_id.get(gid) or {}).get("members") or {}
        xgb += mem.get("xgb") or []
        m5 += mem.get("lstm_5m") or []
        m1 += mem.get("lstm_1m") or []
    return sorted(set(xgb)), sorted(set(m5)), sorted(set(m1))


def build_per_model_confirm_pass_section(
    manifest: dict,
    *,
    db_path: str,
    drops_by_mh: dict,
    full_baseline: dict,
    tickers: list[str] | None = None,
    on_cell_done=None,
    cells_out: list[dict] | None = None,
) -> dict:
    """O-56 confirm pass: per (anchor, model, horizon) with DROP_CANDIDATE groups, REFIT the model
    on survivors-only (XGB: columns removed; sequence: channels nulled) and check the held-out MCC
    is not worse than the full-feature baseline (from the primary report). safe_to_drop if so."""
    TOL = 0.005
    anchors = [t.strip().upper() for t in (tickers or manifest["ablation_method"]["anchors"])]
    cells = cells_out if cells_out is not None else []
    _prep = {
        "xgb": _prepare_xgb_holdout,
        "lstm": _prepare_lstm_holdout,
        "transformer": _prepare_transformer_holdout,
    }
    specs = [
        (anc, model, hz, drop_ids)
        for (model, hz), drop_ids in sorted(drops_by_mh.items())
        for anc in anchors
    ]
    total = len(specs)
    done = 0
    for (anc, model, hz, drop_ids) in specs:
        xcols, m5, m1 = _drop_members_for_model(manifest, drop_ids)
        if model == "xgb":
            prep = _prep[model](ticker=anc, horizon_slug=hz, db_path=db_path, drop_columns=xcols)
        elif model == "lstm":
            prep = _prep[model](ticker=anc, horizon_slug=hz, db_path=db_path, drop_5m=m5, drop_1m=m1)
        else:
            prep = _prep[model](ticker=anc, horizon_slug=hz, db_path=db_path, drop_5m=m5)
        base = full_baseline.get((anc, model, hz))
        if prep.get("status") != "ok":
            cell = {
                "anchor_ticker": anc, "model_family": model, "horizon_slug": hz,
                "status": "skipped", "reason": prep.get("reason", "prep_failed"),
                "ablation_kind": "per_model_confirm_drop", "dropped_groups": drop_ids,
            }
        else:
            surv = prep.get("baseline_mcc")
            safe = base is not None and surv is not None and surv >= base - TOL
            cell = {
                "anchor_ticker": anc, "model_family": model, "horizon_slug": hz,
                "status": "ok", "ablation_kind": "per_model_confirm_drop",
                "dropped_groups": drop_ids,
                "baseline_mcc_full": base, "survivors_mcc": surv,
                "mcc_change": (None if base is None or surv is None else round(surv - base, 6)),
                "safe_to_drop": bool(safe), "tolerance": TOL,
            }
        cells.append(cell)
        done += 1
        if on_cell_done is not None:
            on_cell_done("per_model_confirm", cell, done, total)
    return {"confirm_drop_cell_count": len(specs), "confirm_drop_cells": cells}


def build_ablation_confirm_report(
    manifest_path: Path | None = None,
    *,
    report_path: Path | None = None,
    db_path: str | None = None,
    tickers: list[str] | None = None,
    resume: bool = False,
) -> dict:
    """Per-model drop-and-refit confirm pass over DROP_CANDIDATE groups from an existing primary report."""
    manifest = load_ablation_manifest(manifest_path)
    out_path = report_path or ABLATION_REPORT_PATH
    if not out_path.is_file():
        raise FileNotFoundError(f"primary ablation report missing: {out_path}")

    report = json.loads(out_path.read_text(encoding="utf-8"))
    survivor = report.get("survivor_summary") or build_ablation_survivor_summary(
        report.get("per_model_feature_cells") or []
    )
    drops_by_mh = ablation_confirm_drops_by_model_horizon(survivor)
    full_baseline = {
        (c["anchor_ticker"], c["model_family"], c["horizon_slug"]): c["baseline_mcc"]
        for c in (report.get("per_model_feature_cells") or [])
        if c.get("status") == "ok" and c.get("baseline_mcc") is not None
    }
    db = db_path or str(DB_PATH)

    _prev_strict = os.environ.get("ED_XGB_STRICT_ACTIVE_ONLY")
    _prev_ablation_eval = os.environ.get("ED_ABLATION_SCORED_EVAL")
    os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = "0"
    os.environ["ED_ABLATION_SCORED_EVAL"] = "1"
    try:

        def _checkpoint(section_kind: str, cell: dict, n: int, total: int) -> None:
            report["run_progress"] = {
                "phase": section_kind, "cells_done": n, "cells_total": total,
                "last_cell": {
                    "anchor_ticker": cell.get("anchor_ticker"),
                    "model_family": cell.get("model_family"),
                    "horizon_slug": cell.get("horizon_slug"),
                    "status": cell.get("status"),
                    "safe_to_drop": cell.get("safe_to_drop"),
                    "mcc_change": cell.get("mcc_change"),
                },
            }
            _write_ablation_checkpoint(out_path, report)
            print(
                f"confirm [{section_kind}] {n}/{total} "
                f"{cell.get('anchor_ticker')}/{cell.get('model_family')}/{cell.get('horizon_slug')} "
                f"status={cell.get('status')} safe={cell.get('safe_to_drop')} dmcc={cell.get('mcc_change')}",
                flush=True,
            )

        report["confirm_drop_cells"] = []
        confirm_section = build_per_model_confirm_pass_section(
            manifest,
            db_path=db,
            drops_by_mh=drops_by_mh,
            full_baseline=full_baseline,
            tickers=tickers,
            on_cell_done=_checkpoint,
            cells_out=report["confirm_drop_cells"],
        )
        report.update(confirm_section)
        report["confirm_drop_summary"] = {
            "drops_by_model_horizon": {f"{mh[0]}/{mh[1]}": ids for mh, ids in drops_by_mh.items()},
            "cells_total": len(report.get("confirm_drop_cells") or []),
            "cells_ok": sum(
                1 for c in report.get("confirm_drop_cells") or [] if c.get("status") == "ok"
            ),
            "cells_safe_to_drop": sum(
                1
                for c in report.get("confirm_drop_cells") or []
                if c.get("status") == "ok" and c.get("safe_to_drop")
            ),
        }
        report.setdefault("run_meta", {})["confirm_pass_at"] = datetime.now(
            timezone.utc
        ).isoformat()
        confirm_cells = report.get("confirm_drop_cells") or []
        anchors = list(manifest["ablation_method"]["anchors"])
        surv = report.get("survivor_summary") or survivor
        surv["confirm_pass"] = {
            "cells": confirm_cells,
            "anchors_required": len(anchors),
            "completed_at": report["run_meta"]["confirm_pass_at"],
        }
        surv["primary_pass_only"] = False
        report["survivor_summary"] = surv
    finally:
        if _prev_strict is None:
            os.environ.pop("ED_XGB_STRICT_ACTIVE_ONLY", None)
        else:
            os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = _prev_strict
        if _prev_ablation_eval is None:
            os.environ.pop("ED_ABLATION_SCORED_EVAL", None)
        else:
            os.environ["ED_ABLATION_SCORED_EVAL"] = _prev_ablation_eval
    return report


def _pre_mask_encoded_indices(
    raw_members: list[str],
    base_features: list[str],
    encoded_names: list[str],
) -> list[int]:
    """Map manifest raw DB columns to pre-mask encoder channel indices."""
    base_set = set(base_features)
    out: list[int] = []
    for raw in raw_members:
        if raw not in base_set:
            continue
        for i, name in enumerate(encoded_names):
            if name == raw or name == f"{raw}__present":
                out.append(i)
    return sorted(set(out))


def _post_mask_channel_indices(pre_indices: list[int], mask: np.ndarray) -> list[int]:
    """Map pre-mask encoder indices to post-variance-mask tensor channels."""
    keep = np.flatnonzero(mask)
    old_to_new = {int(old): int(new) for new, old in enumerate(keep)}
    return [old_to_new[i] for i in pre_indices if i in old_to_new]


def _permute_sequence_channels(
    X: np.ndarray,
    channel_indices: list[int],
    rng: np.random.Generator,
) -> np.ndarray:
    """Grouped permutation on (N, T, F) — one row shuffle for all channels in the group."""
    out = np.array(X, copy=True)
    if not channel_indices or len(out) == 0:
        return out
    perm = rng.permutation(len(out))
    for c in channel_indices:
        out[:, :, c] = out[perm, :, c]
    return out


# ════════════════════════════════════════════════════════════════════════════════
# O-56 — PER-MODEL × PER-HORIZON GROUPED PERMUTATION (feature→model→horizon)
# Each base model (xgb/lstm/transformer) is trained per (anchor, horizon) on a chronological
# holdout; each ABLATE group is grouped-permuted and the MODEL's own MCC delta is measured.
# Survivors are resolved per (model, horizon) — not one global list. full_fusion stays a SEPARATE
# stack-authority pass (never the feature ablation).
# ════════════════════════════════════════════════════════════════════════════════


def _matthews_corrcoef_safe(y_true, y_pred) -> float | None:
    from sklearn.metrics import matthews_corrcoef

    if len(y_true) == 0:
        return None
    try:
        return float(matthews_corrcoef(y_true, y_pred))
    except ValueError:
        return None


def permute_group_columns_together(X, columns: list[str], rng: np.random.Generator):
    """Tabular grouped permutation: one row shuffle applied to all group member columns."""
    out = X.copy()
    present = [c for c in columns if c in out.columns]
    if not present or len(out) == 0:
        return out
    perm = rng.permutation(len(out))
    for col in present:
        out[col] = out[col].iloc[perm].to_numpy()
    return out


def ablation_per_model_feature_cell_specs(manifest: dict) -> list[dict]:
    """Cartesian anchor × model × horizon × ABLATE-group cell specs (O-56 grid)."""
    method = manifest["ablation_method"]
    anchors = list(method["anchors"])
    models = list(method.get("models") or ["xgb", "lstm", "transformer"])
    horizons = list(method.get("horizons") or method.get("horizons_required") or [])
    specs: list[dict] = []
    for anchor in anchors:
        for model in models:
            for hz in horizons:
                for grp in ablation_groups(manifest):
                    members = grp.get("members") or {}
                    specs.append(
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
    return specs


def _prepare_xgb_holdout(*, ticker: str, horizon_slug: str, db_path: str,
                         min_rows: int = 200, drop_columns: list[str] | None = None) -> dict:
    """Train ONE XGB model per (ticker, horizon) on the chronological holdout; reuse across groups.

    ``drop_columns`` (confirm pass only): engineered feature columns to REMOVE before fit — a true
    drop-column refit on survivors. Default None = full feature set (primary path, unchanged)."""
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
    df = load_data(db_path=db_path, ticker=ticker, ml_horizon_slug=hz, label_column=label_col)
    if len(df) < min_rows:
        return {"status": "skipped", "hz": hz, "reason": f"insufficient_rows:{len(df)}"}
    train_end, n_val = time_ordered_tail_split(len(df))
    if n_val <= 0:
        return {"status": "skipped", "hz": hz, "reason": "no_chronological_holdout"}
    X, feat_names, _, _ = engineer_features(df, fit_end=train_end)
    if drop_columns:
        _drop = set(drop_columns)
        feat_names = [f for f in feat_names if f not in _drop]
        X = X[feat_names]
    y = encode_target(df, label_col)
    X_train, y_train = X.iloc[:train_end], y[:train_end]
    X_val, y_val = X.iloc[train_end:].copy(), y[train_end:]
    med = X_train.median()
    impute = {f: float(med[f]) if pd.notna(med[f]) else 0.0 for f in feat_names}
    x_train = apply_xgb_imputation_matrix(X_train.values.astype(np.float64), feat_names, impute)
    x_val = apply_xgb_imputation_matrix(X_val.values.astype(np.float64), feat_names, impute)
    model = get_model(n_classes=3, early_stopping_rounds=None)
    model.fit(x_train, y_train)
    base_pred = model.predict(x_val)
    return {
        "status": "ok", "hz": hz, "model": model, "feat_names": feat_names,
        "x_val": x_val, "y_val": y_val, "n_val": int(n_val),
        "baseline_mcc": _matthews_corrcoef_safe(y_val, base_pred),
        "baseline_hcm": holdout_class_metrics(y_val, base_pred, 3),
    }


def _permute_eval_xgb_group(prepared: dict, *, ticker: str, group_id: str,
                            xgb_members: list[str], random_state: int = 42) -> dict:
    from ml_data_common import holdout_class_metrics

    feat_names = prepared["feat_names"]
    present = [c for c in xgb_members if c in feat_names]
    rng = np.random.default_rng(random_state)
    x_perm = permute_group_columns_together(
        pd.DataFrame(prepared["x_val"], columns=feat_names), xgb_members, rng
    ).values.astype(np.float64)
    perm_pred = prepared["model"].predict(x_perm)
    perm_mcc = _matthews_corrcoef_safe(prepared["y_val"], perm_pred)
    perm_hcm = holdout_class_metrics(prepared["y_val"], perm_pred, 3)
    base_mcc = prepared["baseline_mcc"]
    return {
        "anchor_ticker": ticker, "model_family": "xgb", "horizon_slug": prepared["hz"],
        "group_id": group_id, "status": "ok", "ablation_kind": "per_model_feature_group",
        "members_permuted": present, "members_permuted_count": len(present),
        "holdout_rows": prepared["n_val"],
        "baseline_mcc": base_mcc, "permuted_mcc": perm_mcc,
        "mcc_delta": (None if base_mcc is None or perm_mcc is None else round(base_mcc - perm_mcc, 6)),
        "group_matters": bool(base_mcc is not None and perm_mcc is not None and (base_mcc - perm_mcc) > 1e-4),
        "baseline_per_class_recall": prepared["baseline_hcm"].get("per_class_recall"),
        "permuted_per_class_recall": perm_hcm.get("per_class_recall"),
    }


def _lstm_predict_numpy(model, X_5m_v, X_1m_v, X_conf_v, device, batch_size: int = 64) -> np.ndarray:
    import torch

    model.eval()
    preds: list[np.ndarray] = []
    with torch.no_grad():
        for i in range(0, len(X_5m_v), batch_size):
            b5 = torch.tensor(X_5m_v[i : i + batch_size], dtype=torch.float32, device=device)
            b1 = torch.tensor(X_1m_v[i : i + batch_size], dtype=torch.float32, device=device)
            bc = torch.tensor(X_conf_v[i : i + batch_size], dtype=torch.float32, device=device)
            preds.append(model(b1, b5, bc).argmax(dim=1).cpu().numpy())
    return np.concatenate(preds) if preds else np.array([], dtype=int)


def _transformer_predict_numpy(model, X_v, device, batch_size: int = 64) -> np.ndarray:
    import torch

    model.eval()
    preds: list[np.ndarray] = []
    with torch.no_grad():
        for i in range(0, len(X_v), batch_size):
            bx = torch.tensor(X_v[i : i + batch_size], dtype=torch.float32, device=device)
            preds.append(model(bx).argmax(dim=1).cpu().numpy())
    return np.concatenate(preds) if preds else np.array([], dtype=int)


def _prepare_lstm_holdout(*, ticker: str, horizon_slug: str, db_path: str,
                          min_rows: int = 200,
                          drop_5m: list[str] | None = None,
                          drop_1m: list[str] | None = None) -> dict:
    """Train ONE dual-stream LSTM per (ticker, horizon) on the chronological holdout.

    ``drop_5m``/``drop_1m`` (confirm pass only): raw member names whose channels are nulled
    (constant) before refit — channel-drop refit on survivors. Default None = primary path."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        return {"status": "skipped", "reason": "torch_unavailable"}

    from ml_data_common import equal_sample_weights, holdout_class_metrics, time_ordered_tail_split
    from ml_horizon import normalize_ml_horizon_slug
    from lstm_data import (
        ENCODED_FEATURES_1M, ENCODED_FEATURES_5M, FEATURES_1M, FEATURES_5M, build_lstm_dataset,
    )
    from lstm_model import (
        BATCH_SIZE, CLIP_GRAD_NORM, EPOCHS, LEARNING_RATE, WEIGHT_DECAY,
        _validate_lstm_dataset_shape, apply_masks, apply_normalization, build_model,
        compute_feature_masks, compute_normalization,
    )

    hz = normalize_ml_horizon_slug(horizon_slug)
    dataset = build_lstm_dataset(tickers=[ticker], db_path=db_path, ml_horizon_slug=hz)
    try:
        _validate_lstm_dataset_shape(dataset, ticker=ticker)
    except Exception as exc:
        return {"status": "skipped", "hz": hz, "reason": str(exc)}
    n_rows = len(dataset.y)
    if n_rows < min_rows:
        return {"status": "skipped", "hz": hz, "reason": f"insufficient_rows:{n_rows}"}

    X_5m = np.array(dataset.X_5m, copy=True)
    X_1m = np.array(dataset.X_1m, copy=True)
    X_conf = np.array(dataset.X_conf, copy=True)
    mask_5m, mask_1m, mask_conf, _ = compute_feature_masks(X_5m, X_1m, X_conf)
    X_5m, X_1m, X_conf = apply_masks(X_5m, X_1m, X_conf, mask_5m, mask_1m, mask_conf)
    train_end, n_val = time_ordered_tail_split(n_rows)
    if n_val <= 0:
        return {"status": "skipped", "hz": hz, "reason": "no_chronological_holdout"}
    norm_stats = compute_normalization(X_5m[:train_end], X_1m[:train_end], X_conf[:train_end])
    X_5m, X_1m, X_conf = apply_normalization(X_5m, X_1m, X_conf, norm_stats)
    X_5m = np.nan_to_num(X_5m, nan=0.0)
    X_1m = np.nan_to_num(X_1m, nan=0.0)
    X_conf = np.nan_to_num(X_conf, nan=0.0)

    if drop_5m:
        for c in _post_mask_channel_indices(
            _pre_mask_encoded_indices(drop_5m, FEATURES_5M, ENCODED_FEATURES_5M), mask_5m):
            X_5m[:, :, c] = 0.0
    if drop_1m:
        for c in _post_mask_channel_indices(
            _pre_mask_encoded_indices(drop_1m, FEATURES_1M, ENCODED_FEATURES_1M), mask_1m):
            X_1m[:, :, c] = 0.0

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model(X_5m.shape[2], X_1m.shape[2], X_conf.shape[1]).to(device)
    sample_w = np.asarray(equal_sample_weights(train_end), dtype=np.float32)
    train_loader = DataLoader(
        TensorDataset(
            torch.tensor(X_5m[:train_end]), torch.tensor(X_1m[:train_end]),
            torch.tensor(X_conf[:train_end]), torch.tensor(dataset.y[:train_end]),
            torch.tensor(sample_w),
        ),
        batch_size=BATCH_SIZE, shuffle=True,
    )
    val_loader = DataLoader(
        TensorDataset(
            torch.tensor(X_5m[train_end:]), torch.tensor(X_1m[train_end:]),
            torch.tensor(X_conf[train_end:]), torch.tensor(dataset.y[train_end:]),
            torch.ones(n_val),
        ),
        batch_size=BATCH_SIZE, shuffle=False,
    )
    class_counts = np.bincount(dataset.y[:train_end], minlength=3).astype(float)
    class_counts[class_counts == 0] = 1.0
    cw = 1.0 / class_counts
    cw = cw / cw.sum() * 3.0
    criterion = nn.CrossEntropyLoss(weight=torch.tensor(cw, dtype=torch.float32).to(device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)

    best_state, best_loss = None, float("inf")
    for _epoch in range(1, EPOCHS + 1):
        model.train()
        for b5, b1, bc, by, bw in train_loader:
            b5, b1, bc, by, bw = (t.to(device) for t in (b5, b1, bc, by, bw))
            optimizer.zero_grad()
            loss = (criterion(model(b1, b5, bc), by) * bw).sum() / bw.sum()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP_GRAD_NORM)
            optimizer.step()
        model.eval()
        vs, vt = 0.0, 0
        with torch.no_grad():
            for b5, b1, bc, by, _w in val_loader:
                b5, b1, bc, by = (t.to(device) for t in (b5, b1, bc, by))
                vs += criterion(model(b1, b5, bc), by).item() * len(by)
                vt += len(by)
        vl = vs / max(vt, 1)
        if vl < best_loss:
            best_loss = vl
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)

    y_val = dataset.y[train_end:]
    base_pred = _lstm_predict_numpy(model, X_5m[train_end:], X_1m[train_end:], X_conf[train_end:], device)
    return {
        "status": "ok", "hz": hz, "model": model, "device": device,
        "val_5m": X_5m[train_end:], "val_1m": X_1m[train_end:], "val_conf": X_conf[train_end:],
        "y_val": y_val, "n_val": int(n_val),
        "baseline_mcc": _matthews_corrcoef_safe(y_val, base_pred),
        "baseline_hcm": holdout_class_metrics(y_val, base_pred, 3),
        "mask_5m": mask_5m, "mask_1m": mask_1m,
        "encoded_features_5m": ENCODED_FEATURES_5M, "encoded_features_1m": ENCODED_FEATURES_1M,
        "features_5m": FEATURES_5M, "features_1m": FEATURES_1M,
    }


def _permute_eval_lstm_group(prepared: dict, *, ticker: str, group_id: str,
                             lstm_5m_members: list[str], lstm_1m_members: list[str],
                             random_state: int = 42) -> dict:
    from ml_data_common import holdout_class_metrics

    pre5 = _pre_mask_encoded_indices(lstm_5m_members, prepared["features_5m"], prepared["encoded_features_5m"])
    pre1 = _pre_mask_encoded_indices(lstm_1m_members, prepared["features_1m"], prepared["encoded_features_1m"])
    ch5 = _post_mask_channel_indices(pre5, prepared["mask_5m"])
    ch1 = _post_mask_channel_indices(pre1, prepared["mask_1m"])
    rng = np.random.default_rng(random_state)
    v5 = _permute_sequence_channels(prepared["val_5m"], ch5, rng)
    v1 = _permute_sequence_channels(prepared["val_1m"], ch1, rng)
    perm_pred = _lstm_predict_numpy(prepared["model"], v5, v1, prepared["val_conf"], prepared["device"])
    perm_mcc = _matthews_corrcoef_safe(prepared["y_val"], perm_pred)
    perm_hcm = holdout_class_metrics(prepared["y_val"], perm_pred, 3)
    base_mcc = prepared["baseline_mcc"]
    return {
        "anchor_ticker": ticker, "model_family": "lstm", "horizon_slug": prepared["hz"],
        "group_id": group_id, "status": "ok", "ablation_kind": "per_model_feature_group",
        "members_permuted_count": len(ch5) + len(ch1),
        "lstm_5m_channels_permuted": ch5, "lstm_1m_channels_permuted": ch1,
        "holdout_rows": prepared["n_val"],
        "baseline_mcc": base_mcc, "permuted_mcc": perm_mcc,
        "mcc_delta": (None if base_mcc is None or perm_mcc is None else round(base_mcc - perm_mcc, 6)),
        "group_matters": bool(base_mcc is not None and perm_mcc is not None and (base_mcc - perm_mcc) > 1e-4),
        "baseline_per_class_recall": prepared["baseline_hcm"].get("per_class_recall"),
        "permuted_per_class_recall": perm_hcm.get("per_class_recall"),
    }


def _prepare_transformer_holdout(*, ticker: str, horizon_slug: str, db_path: str,
                                 min_rows: int = 200, drop_5m: list[str] | None = None) -> dict:
    """Train ONE transformer per (ticker, horizon) on the chronological holdout.

    ``drop_5m`` (confirm pass only): raw member names whose channels are nulled before refit —
    channel-drop refit on survivors. Default None = primary path (unchanged)."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        return {"status": "skipped", "reason": "torch_unavailable"}

    from collections import Counter
    from ml_data_common import equal_sample_weights, holdout_class_metrics, time_ordered_tail_split
    from ml_horizon import normalize_ml_horizon_slug
    from lstm_data import ENCODED_FEATURES_5M, FEATURES_5M
    from transformer_train import (
        BATCH_SIZE, EPOCHS, LEARNING_RATE, N_CLASSES, build_transformer, prepare_transformer_data,
    )

    hz = normalize_ml_horizon_slug(horizon_slug)
    X, y, _days, _tk, n_features = prepare_transformer_data(db_path, ticker, ml_horizon_slug=hz)
    if X is None or y is None or len(y) == 0:
        return {"status": "skipped", "hz": hz, "reason": "no_sequence_data"}
    n_rows = len(y)
    if n_rows < min_rows:
        return {"status": "skipped", "hz": hz, "reason": f"insufficient_rows:{n_rows}"}
    train_end, n_val = time_ordered_tail_split(n_rows)
    if n_val <= 0:
        return {"status": "skipped", "hz": hz, "reason": "no_chronological_holdout"}

    fit_flat = X[:train_end].reshape(-1, n_features)
    mean, std = fit_flat.mean(axis=0), fit_flat.std(axis=0)
    std[std < 1e-8] = 1.0
    X = np.nan_to_num((X - mean) / std, nan=0.0, posinf=0.0, neginf=0.0)
    var = X[:train_end].reshape(-1, n_features).var(axis=0)
    feature_mask = var > 1e-8
    X = X[:, :, feature_mask]
    n_feat = X.shape[2]

    if drop_5m:
        for c in _post_mask_channel_indices(
            _pre_mask_encoded_indices(drop_5m, FEATURES_5M, ENCODED_FEATURES_5M), feature_mask):
            X[:, :, c] = 0.0

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_transformer(n_feat).to(device)
    sample_w = np.asarray(equal_sample_weights(train_end), dtype=np.float32)
    Xt = torch.from_numpy(X).float()
    yt = torch.from_numpy(y).long()
    wt = torch.from_numpy(sample_w).float()
    train_dl = DataLoader(TensorDataset(Xt[:train_end], yt[:train_end], wt[:train_end]),
                          batch_size=BATCH_SIZE, shuffle=True)
    val_dl = DataLoader(TensorDataset(Xt[train_end:], yt[train_end:], torch.ones(n_val)),
                        batch_size=BATCH_SIZE, shuffle=False)
    tc = Counter(y[:train_end].tolist())
    tot = len(y[:train_end])
    weights = torch.tensor([tot / (N_CLASSES * tc.get(i, 1)) for i in range(N_CLASSES)],
                           dtype=torch.float32).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)

    best_state, best_loss = None, float("inf")
    for _epoch in range(1, EPOCHS + 1):
        model.train()
        for bx, by, bw in train_dl:
            bx, by, bw = bx.to(device), by.to(device), bw.to(device)
            optimizer.zero_grad()
            loss = (criterion(model(bx), by) * bw).sum() / bw.sum()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)  # production fidelity
            optimizer.step()
        model.eval()
        vs, vt = 0.0, 0
        with torch.no_grad():
            for bx, by, _w in val_dl:
                bx, by = bx.to(device), by.to(device)
                vs += criterion(model(bx), by).item() * len(by)
                vt += len(by)
        vl = vs / max(vt, 1)
        if vl < best_loss:
            best_loss = vl
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)

    y_val = y[train_end:]
    base_pred = _transformer_predict_numpy(model, X[train_end:], device)
    return {
        "status": "ok", "hz": hz, "model": model, "device": device,
        "val_X": X[train_end:], "y_val": y_val, "n_val": int(n_val),
        "baseline_mcc": _matthews_corrcoef_safe(y_val, base_pred),
        "baseline_hcm": holdout_class_metrics(y_val, base_pred, 3),
        "feature_mask": feature_mask, "encoded_features_5m": ENCODED_FEATURES_5M,
        "features_5m": FEATURES_5M,
    }


def _permute_eval_transformer_group(prepared: dict, *, ticker: str, group_id: str,
                                    lstm_5m_members: list[str], random_state: int = 42) -> dict:
    from ml_data_common import holdout_class_metrics

    pre = _pre_mask_encoded_indices(lstm_5m_members, prepared["features_5m"], prepared["encoded_features_5m"])
    ch = _post_mask_channel_indices(pre, prepared["feature_mask"])
    rng = np.random.default_rng(random_state)
    vX = _permute_sequence_channels(prepared["val_X"], ch, rng)
    perm_pred = _transformer_predict_numpy(prepared["model"], vX, prepared["device"])
    perm_mcc = _matthews_corrcoef_safe(prepared["y_val"], perm_pred)
    perm_hcm = holdout_class_metrics(prepared["y_val"], perm_pred, 3)
    base_mcc = prepared["baseline_mcc"]
    return {
        "anchor_ticker": ticker, "model_family": "transformer", "horizon_slug": prepared["hz"],
        "group_id": group_id, "status": "ok", "ablation_kind": "per_model_feature_group",
        "transformer_channels_permuted": ch, "members_permuted_count": len(ch),
        "holdout_rows": prepared["n_val"],
        "baseline_mcc": base_mcc, "permuted_mcc": perm_mcc,
        "mcc_delta": (None if base_mcc is None or perm_mcc is None else round(base_mcc - perm_mcc, 6)),
        "group_matters": bool(base_mcc is not None and perm_mcc is not None and (base_mcc - perm_mcc) > 1e-4),
        "baseline_per_class_recall": prepared["baseline_hcm"].get("per_class_recall"),
        "permuted_per_class_recall": perm_hcm.get("per_class_recall"),
    }


def build_ablation_report(
    manifest_path: Path | None = None,
    *,
    db_path: str | None = None,
    dry_run: bool = False,
    tickers: list[str] | None = None,
    horizons: list[str] | None = None,
    resume: bool = False,
    report_path: Path | None = None,
) -> dict:
    """Build ablation report from manifest-only contract.

    Primary: whole-stack feature group permutation → full_fusion log_loss (all 6 layers, all 4 hz).
    Secondary: stack-component authority (base-model + meta/MC/fusion mode lifts).
    """
    manifest = load_ablation_manifest(manifest_path)
    _enforce_full_stack_ablation_contract(manifest, horizons=horizons)
    method = manifest["ablation_method"]
    effective_horizons = _required_ablation_horizons(manifest)
    groups = ablation_groups(manifest)
    db = db_path or str(DB_PATH)
    out_path = report_path or ABLATION_REPORT_PATH

    resume_whole: dict[str, dict] = {}
    resume_stack: dict[str, dict] = {}
    started_at = datetime.now(timezone.utc).isoformat()
    if resume and out_path.is_file():
        prior = json.loads(out_path.read_text(encoding="utf-8"))
        resume_whole = _index_per_model_cells(prior.get("per_model_feature_cells") or [])
        resume_stack = _index_stack_authority_cells(
            prior.get("stack_authority_cells") or prior.get("stack_layer_cells") or []
        )
        started_at = prior.get("run_meta", {}).get("started_at") or started_at

    report: dict = {
        "schema_version": "3",
        "source_manifest": str(manifest_path or MANIFEST_PATH),
        "manifest_totals": manifest.get("totals"),
        "ablation_method": method,
        "full_stack_layers": list(method.get("full_stack_layers") or FULL_STACK_LAYERS),
        "horizons_required": effective_horizons,
        "ablation_group_ids": [g["group_id"] for g in groups],
        "per_model_feature_cell_count": manifest["totals"]["per_model_feature_cell_count"],
        "stack_authority_cell_count": manifest["totals"]["stack_authority_cell_count"],
        "grid_cell_count": manifest["totals"]["grid_cell_count"],
        "per_model_feature_cells": [],
        "stack_authority_cells": [],
        "stack_layer_cells": [],
        "run_meta": {
            "started_at": started_at,
            "resume": bool(resume),
            "db_path": db,
            "tickers": tickers,
        },
    }

    if dry_run:
        feature_section = build_per_model_feature_ablation_section(
            manifest, db_path=db, dry_run=True, tickers=tickers, horizons=effective_horizons
        )
        stack_section = build_stack_authority_ablation_section(
            manifest, db_path=db, dry_run=True, tickers=tickers, horizons=effective_horizons
        )
        report.update(feature_section)
        report.update(stack_section)
        report["dry_run"] = True
        return report

    _prev_strict = os.environ.get("ED_XGB_STRICT_ACTIVE_ONLY")
    _prev_ablation_eval = os.environ.get("ED_ABLATION_SCORED_EVAL")
    os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = "0"
    os.environ["ED_ABLATION_SCORED_EVAL"] = "1"
    report["run_meta"]["ed_xgb_strict_active_only"] = "0"
    report["run_meta"]["ed_ablation_scored_eval"] = "1"
    report["run_meta"]["note"] = (
        "Scored ablation: on-disk active bundles (file presence); label_config_version drift "
        "relaxed for pre-retrain eval only — not for live serving."
    )
    eval_opts = _ablation_eval_options()
    full_hist = os.environ.get("ED_ABLATION_FULL_HISTORY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    report["run_meta"]["eval_options"] = {
        "min_paired_rows": eval_opts.min_paired_rows,
        "max_rows": eval_opts.max_rows,
        "full_history": full_hist,
        "full_history_env": "ED_ABLATION_FULL_HISTORY=1",
        "override_max_rows_env": "ED_ABLATION_MAX_ROWS",
    }
    if not full_hist and eval_opts.max_rows:
        report["run_meta"]["eval_window_note"] = (
            f"Default operational window: last {eval_opts.max_rows} chronological RTH rows "
            "(~0.8s/row full_fusion → full 54k+ history is multi-day). Set ED_ABLATION_FULL_HISTORY=1 "
            "for full replay."
        )
    pf = run_ablation_preflight(manifest, db_path=db, tickers=tickers or [])
    report["run_meta"]["preflight"] = pf
    report["run_progress"] = {"phase": "starting", "cells_done": 0, "cells_total": manifest["totals"]["per_model_feature_cell_count"]}
    _write_ablation_checkpoint(out_path, report)
    print(
        f"ablation run started max_rows={eval_opts.max_rows} full_history={full_hist} "
        f"per_model_feature_cells={manifest['totals']['per_model_feature_cell_count']}",
        flush=True,
    )
    acquire_ablation_run_lock()
    try:
        try:
            return _build_ablation_report_scored(
                manifest=manifest,
                report=report,
                db=db,
                tickers=tickers,
                effective_horizons=effective_horizons,
                out_path=out_path,
                resume_whole=resume_whole,
                resume_stack=resume_stack,
            )
        finally:
            release_ablation_run_lock()
    finally:
        if _prev_strict is None:
            os.environ.pop("ED_XGB_STRICT_ACTIVE_ONLY", None)
        else:
            os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = _prev_strict
        if _prev_ablation_eval is None:
            os.environ.pop("ED_ABLATION_SCORED_EVAL", None)
        else:
            os.environ["ED_ABLATION_SCORED_EVAL"] = _prev_ablation_eval


def _build_ablation_report_scored(
    *,
    manifest: dict,
    report: dict,
    db: str,
    tickers: list[str] | None,
    effective_horizons: list[str],
    out_path: Path,
    resume_whole: dict[str, dict],
    resume_stack: dict[str, dict],
) -> dict:
    def _checkpoint(section_kind: str, cell: dict, n: int, total: int) -> None:
        report["run_progress"] = {
            "phase": section_kind,
            "cells_done": n,
            "cells_total": total,
            "last_cell": {
                "anchor_ticker": cell.get("anchor_ticker"),
                "horizon_slug": cell.get("horizon_slug"),
                "group_id": cell.get("group_id"),
                "status": cell.get("status"),
                "log_loss_delta": cell.get("log_loss_delta"),
            },
        }
        report["survivor_summary"] = build_ablation_survivor_summary(
            report.get("per_model_feature_cells") or []
        )
        _write_ablation_checkpoint(out_path, report)
        label = cell.get("group_id") or "stack_authority"
        delta = cell.get("log_loss_delta")
        delta_s = f" delta={delta}" if delta is not None else ""
        print(
            f"ablation [{section_kind}] {n}/{total} "
            f"{cell.get('anchor_ticker')}/{cell.get('horizon_slug')}/{label} "
            f"status={cell.get('status')}{delta_s}",
            flush=True,
        )

    feature_section = build_per_model_feature_ablation_section(
        manifest,
        db_path=db,
        dry_run=False,
        tickers=tickers,
        horizons=effective_horizons,
        resume_cells=resume_whole,
        on_cell_done=_checkpoint,
        cells_out=report["per_model_feature_cells"],
    )
    report.update(feature_section)

    report["stack_layer_cells"] = report["stack_authority_cells"]
    stack_section = build_stack_authority_ablation_section(
        manifest,
        db_path=db,
        dry_run=False,
        tickers=tickers,
        horizons=effective_horizons,
        resume_cells=resume_stack,
        on_cell_done=_checkpoint,
        cells_out=report["stack_authority_cells"],
    )
    report.update(stack_section)
    report["stack_layer_cells"] = report["stack_authority_cells"]

    report["survivor_summary"] = build_ablation_survivor_summary(
        report.get("per_model_feature_cells") or []
    )
    ok = sum(
        1 for c in report.get("per_model_feature_cells") or [] if c.get("status") == "ok"
    )
    report["run_meta"]["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["run_meta"]["per_model_ok"] = ok
    report["run_meta"]["per_model_skipped"] = (
        len(report.get("per_model_feature_cells") or []) - ok
    )
    report["run_meta"]["status"] = (
        "complete"
        if ok + report["run_meta"]["per_model_skipped"]
        >= report["per_model_feature_cell_count"]
        else "partial"
    )
    return report


def write_ablation_report(report: dict, path: Path | None = None) -> Path:
    out_path = path or ABLATION_REPORT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # INSURANCE (post-incident 2026-06-03): never silently destroy a COMPLETE scored report.
    # If one already exists at out_path, snapshot it to <name>.complete.bak.json before overwrite
    # — protects against dry-run / fresh-restart / any accidental clobber by any caller.
    if out_path.is_file():
        try:
            prior = json.loads(out_path.read_text(encoding="utf-8"))
            if (prior.get("run_meta") or {}).get("status") == "complete" and not prior.get("dry_run"):
                bak = out_path.with_name(out_path.stem + ".complete.bak" + out_path.suffix)
                bak.write_text(json.dumps(prior, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out_path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_ablation_lock() -> dict | None:
    if not ABLATION_LOCK_PATH.is_file():
        return None
    try:
        data = json.loads(ABLATION_LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def acquire_ablation_run_lock() -> None:
    """Single-instance guard — refuse a second scored ablation on this host."""
    existing = _read_ablation_lock()
    if existing:
        pid = int(existing.get("pid") or 0)
        if _pid_alive(pid):
            raise SystemExit(
                f"ablation already running (pid={pid}, lock={ABLATION_LOCK_PATH}); "
                "stop that process before starting another run"
            )
        ABLATION_LOCK_PATH.unlink(missing_ok=True)
    ABLATION_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    ABLATION_LOCK_PATH.write_text(
        json.dumps(
            {"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()},
            indent=2,
        ),
        encoding="utf-8",
    )


def release_ablation_run_lock() -> None:
    ABLATION_LOCK_PATH.unlink(missing_ok=True)


def ablation_report_status(report_path: Path | None = None) -> dict:
    """Certified on-disk ablation progress (no agent summaries)."""
    out_path = report_path or ABLATION_REPORT_PATH
    lock = _read_ablation_lock()
    lock_pid = int((lock or {}).get("pid") or 0)
    lock_live = _pid_alive(lock_pid) if lock else False
    base: dict = {
        "report_path": str(out_path.resolve()),
        "lock_path": str(ABLATION_LOCK_PATH.resolve()),
        "lock_pid": lock_pid if lock else None,
        "ablation_process_live": lock_live,
        "per_model_feature_cells": 0,
        "per_model_feature_target": WHOLE_STACK_CELL_TARGET,
        "stack_authority_cells": 0,
        "stack_authority_target": 12,
        "run_status": "missing",
        "complete": False,
        "resume_recommended": False,
    }
    if not out_path.is_file():
        return base
    try:
        report = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        base["run_status"] = "unreadable"
        base["error"] = str(exc)
        return base
    whole = report.get("per_model_feature_cells") or []
    stack = report.get("stack_authority_cells") or report.get("stack_layer_cells") or []
    meta = report.get("run_meta") or {}
    prog = report.get("run_progress") or {}
    n_whole = len(whole)
    n_stack = len(stack)
    status = str(meta.get("status") or prog.get("phase") or "partial")
    complete = n_whole >= WHOLE_STACK_CELL_TARGET and n_stack >= 12 and status == "complete"
    base.update(
        {
            "per_model_feature_cells": n_whole,
            "stack_authority_cells": n_stack,
            "run_status": status,
            "started_at": meta.get("started_at"),
            "last_progress": prog.get("last_cell"),
            "complete": complete,
            "resume_recommended": (not complete) and n_whole > 0,
        }
    )
    return base


def guard_ablation_fresh_start(
    report_path: Path,
    *,
    resume: bool,
    force_restart: bool,
) -> None:
    """Refuse to wipe a completed primary report without an explicit force flag."""
    if resume or force_restart or not report_path.is_file():
        return
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    n_whole = len(report.get("per_model_feature_cells") or [])
    n_stack = len(
        report.get("stack_authority_cells") or report.get("stack_layer_cells") or []
    )
    status = str((report.get("run_meta") or {}).get("status") or "")
    if n_whole >= WHOLE_STACK_CELL_TARGET and n_stack >= 12 and status == "complete":
        raise SystemExit(
            f"refusing fresh ablation: {report_path} already complete "
            f"({n_whole}/{WHOLE_STACK_CELL_TARGET} whole-stack cells). "
            "Use --ablation-resume to continue a partial run or --ablation-force-restart "
            "to intentionally overwrite."
        )


def pipeline_status() -> dict:
    """One-shot host status: ablation + ML train processes."""
    import subprocess

    abl = ablation_report_status()
    trains: list[dict] = []
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
                "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if "|" not in line:
                continue
            pid_s, cmd = line.split("|", 1)
            if any(
                k in cmd
                for k in (
                    "_train_parallel",
                    "_train_cascade",
                    "ml_scheduler.py",
                    "feature_curation_gate.py --ablation",
                )
            ):
                trains.append({"pid": int(pid_s), "command": cmd[:240]})
    except (OSError, subprocess.CalledProcessError, ValueError):
        pass
    survivors_env = os.environ.get("ED_APPLY_ABLATION_SURVIVORS", "")
    return {
        "ablation": abl,
        "ml_train_processes": trains,
        "ED_APPLY_ABLATION_SURVIVORS": survivors_env,
        "survivor_mask_source": (
            "report"
            if abl.get("complete")
            else "default_drop_groups (report incomplete — still valid for train)"
        ),
    }


SURVIVOR_RETRAIN_DEFAULT_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "IWM")
SURVIVOR_RETRAIN_REQUIRED_ENVS: tuple[tuple[str, str], ...] = (
    ("ED_APPLY_ABLATION_SURVIVORS", "1"),
    ("ED_SCHEDULER_AUTO_PROMOTE", "1"),
    ("ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY", "1"),
)
SURVIVOR_RETRAIN_FORBIDDEN_ENVS: tuple[str, ...] = (
    "ED_TRAIN_ROLLING_RTH_SESSIONS_TABULAR",
    "ED_TRAIN_ROLLING_RTH_SESSIONS_SEQUENCE",
    "ED_TRAIN_ROLLING_DAYS_TABULAR",
    "ED_TRAIN_ROLLING_DAYS_SEQUENCE",
    "ED_ABLATION_SCORED_EVAL",
    "ED_DISABLE_AUTO_PROMOTE",
)


def validate_survivor_retrain_gate_env(environ: dict | None = None) -> dict:
    """Fail-closed env contract for the 3:30 PM CT survivor retrain gate."""
    import os

    env = dict(environ if environ is not None else os.environ)
    issues: list[str] = []
    for key, want in SURVIVOR_RETRAIN_REQUIRED_ENVS:
        got = (env.get(key) or "").strip().lower()
        if got not in ("1", "true", "yes", "on"):
            issues.append(f"missing_or_off:{key} (required={want!r})")
    for key in SURVIVOR_RETRAIN_FORBIDDEN_ENVS:
        if (env.get(key) or "").strip():
            issues.append(f"forbidden_env_set:{key}={env.get(key)!r}")
    tickers_raw = (env.get("ED_ML_SCHEDULER_TICKERS") or "").strip()
    if not tickers_raw:
        issues.append("missing:ED_ML_SCHEDULER_TICKERS")
    else:
        got = {t.strip().upper() for t in tickers_raw.split(",") if t.strip()}
        want = set(SURVIVOR_RETRAIN_DEFAULT_TICKERS)
        if got != want:
            issues.append(f"ED_ML_SCHEDULER_TICKERS must be exactly {sorted(want)} got {sorted(got)}")
    return {"ok": not issues, "issues": issues}


def run_survivor_retrain_preflight(
    *,
    db_path: str,
    tickers: list[str] | None = None,
) -> dict:
    """DB + readiness + survivor mask — required before the scheduled retrain gate."""
    from arch_competition.stack_bundle_eval_v1 import (
        ablation_drop_snapshot_columns,
        ablation_survivors_training_enabled,
        resolve_ablation_drop_group_ids,
    )

    anchors = [t.strip().upper() for t in (tickers or SURVIVOR_RETRAIN_DEFAULT_TICKERS)]
    dbp = Path(db_path)
    out: dict = {
        "ready": True,
        "db_path": str(dbp),
        "anchors": anchors,
        "horizons": list(REQUIRED_ABLATION_HORIZONS),
        "issues": [],
    }
    if not dbp.is_file():
        out["ready"] = False
        out["issues"].append(f"database missing: {dbp}")
        return out

    drop_ids = resolve_ablation_drop_group_ids()
    drop_cols = ablation_drop_snapshot_columns()
    survivors_on = ablation_survivors_training_enabled()
    out["survivor_mask_enabled"] = survivors_on
    out["survivor_drop_group_ids"] = drop_ids
    out["survivor_drop_column_count"] = len(drop_cols)
    out.setdefault("notes", [])
    if survivors_on:
        from arch_competition.stack_bundle_eval_v1 import ablation_confirm_pass_complete

        if not ablation_confirm_pass_complete():
            out["ready"] = False
            out["issues"].append(
                "ablation_confirm_pass_incomplete: run "
                "python tools/feature_curation_gate.py --ablation-confirm before "
                "ED_APPLY_ABLATION_SURVIVORS=1 retrain (primary-pass DROP_CANDIDATE is never applied)"
            )
        elif not drop_ids:
            out["notes"].append(
                "survivor_mask_confirm_ok_but_no_globally_safe_intersection: per-model drops apply at "
                "feature assembly; shared snapshot stays full-feature"
            )
    elif not survivors_on:
        out["notes"].append("survivor_mask_off: training on the full feature set (canonical default)")

    try:
        from audit_model_readiness import evaluate_training_readiness

        readiness = evaluate_training_readiness(dbp)
        out["training_readiness"] = readiness
        if not readiness.get("training_ok"):
            out["ready"] = False
            out["issues"].extend(readiness.get("reasons") or ["audit_model_readiness NO-GO"])
    except Exception as ex:
        out["ready"] = False
        out["issues"].append(f"readiness_check_failed:{type(ex).__name__}:{ex}")

    try:
        from training_cache import db_training_floor_stats
        from training_provenance import MIN_ROWS_FOR_PROMOTION, MIN_USABLE_DAYS_FOR_PROMOTION

        per_ticker: list[dict] = []
        for tkr in anchors:
            for hz in REQUIRED_ABLATION_HORIZONS:
                from ml_horizon import outcome_column

                label = outcome_column(hz)
                stats = db_training_floor_stats(db_path, tkr, label_column=label)
                row = {
                    "ticker": tkr,
                    "horizon": hz,
                    "label_column": label,
                    **stats,
                }
                per_ticker.append(row)
                if int(stats.get("labeled_rows") or 0) < int(MIN_ROWS_FOR_PROMOTION):
                    out["ready"] = False
                    out["issues"].append(
                        f"{tkr}/{hz}: labeled_rows={stats.get('labeled_rows')} < {MIN_ROWS_FOR_PROMOTION}"
                    )
                if int(stats.get("usable_days") or 0) < int(MIN_USABLE_DAYS_FOR_PROMOTION):
                    out["ready"] = False
                    out["issues"].append(
                        f"{tkr}/{hz}: usable_days={stats.get('usable_days')} < {MIN_USABLE_DAYS_FOR_PROMOTION}"
                    )
        out["training_floor"] = per_ticker
    except Exception as ex:
        out["ready"] = False
        out["issues"].append(f"training_floor_failed:{type(ex).__name__}:{ex}")

    if not MANIFEST_PATH.is_file():
        out["ready"] = False
        out["issues"].append(f"manifest missing: {MANIFEST_PATH}")
    return out


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
    ap.add_argument("--ablation-preflight", action="store_true",
                    help="Verify DB + active bundles; exit 1 if not ready for scored ablation")
    ap.add_argument("--ablation-resume", action="store_true",
                    help="Resume scored ablation from existing report checkpoint")
    ap.add_argument("--ablation-force-restart", action="store_true",
                    help="Allow fresh ablation to overwrite an already-complete primary report")
    ap.add_argument("--pipeline-status", action="store_true",
                    help="Print certified ablation + ML train process status (JSON)")
    ap.add_argument("--ablation-confirm", action="store_true",
                    help="Confirm pass: drop-column inference on DROP_CANDIDATE groups (requires primary report)")
    ap.add_argument("--ablation-confirm-resume", action="store_true",
                    help="Resume confirm pass from existing report checkpoint")
    ap.add_argument("--manifest-path", default=str(MANIFEST_PATH))
    ap.add_argument("--report-path", default=str(ABLATION_REPORT_PATH))
    ap.add_argument(
        "--survivor-retrain-preflight",
        action="store_true",
        help="Fail-closed preflight for scheduled survivor retrain (DB, readiness, drop groups)",
    )
    ap.add_argument(
        "--survivor-retrain-gate-env-check",
        action="store_true",
        help="Validate process env matches survivor retrain gate contract; exit 1 if not",
    )
    a = ap.parse_args()

    if a.pipeline_status:
        print(json.dumps(pipeline_status(), indent=2))
        raise SystemExit(0)

    if a.survivor_retrain_gate_env_check:
        chk = validate_survivor_retrain_gate_env()
        print(json.dumps(chk, indent=2))
        raise SystemExit(0 if chk["ok"] else 1)

    if a.survivor_retrain_preflight:
        tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
        pf = run_survivor_retrain_preflight(db_path=str(DB_PATH), tickers=tickers)
        print(json.dumps(pf, indent=2))
        raise SystemExit(0 if pf["ready"] else 1)

    if a.ablation_preflight:
        manifest = load_ablation_manifest(Path(a.manifest_path))
        tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
        pf = run_ablation_preflight(manifest, db_path=str(DB_PATH), tickers=tickers)
        print(json.dumps(pf, indent=2))
        raise SystemExit(0 if pf["ready"] else 1)

    if a.ablation_confirm:
        tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
        report_path = Path(a.report_path)
        manifest = load_ablation_manifest(Path(a.manifest_path))
        pf = run_ablation_preflight(manifest, db_path=str(DB_PATH), tickers=tickers)
        if not pf["ready"]:
            print(json.dumps(pf, indent=2))
            raise SystemExit("confirm preflight failed")
        report = build_ablation_confirm_report(
            Path(a.manifest_path),
            report_path=report_path,
            tickers=tickers,
            resume=bool(a.ablation_confirm_resume),
        )
        out_p = write_ablation_report(report, report_path)
        summary = report.get("confirm_drop_summary") or {}
        print(
            f"wrote {out_p}  confirm_cells={summary.get('cells_total', 0)}  "
            f"confirm_ok={summary.get('cells_ok', 0)}  "
            f"safe_to_drop={summary.get('cells_safe_to_drop', 0)}  "
            f"drop_groups={summary.get('drop_candidate_groups', [])}"
        )
        return

    if a.ablation or a.ablation_dry_run:
        tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
        report_path = Path(a.report_path)
        if a.ablation_dry_run:
            # FOOTGUN FIX: a dry-run has no scored data — it must NEVER overwrite the live scored
            # report. Redirect dry-runs to a separate .dryrun.json so a completed run is safe.
            report_path = report_path.with_name(
                report_path.stem + ".dryrun" + report_path.suffix
            )
        if a.ablation and not a.ablation_dry_run:
            manifest = load_ablation_manifest(Path(a.manifest_path))
            pf = run_ablation_preflight(manifest, db_path=str(DB_PATH), tickers=tickers)
            if not pf["ready"]:
                print(json.dumps(pf, indent=2))
                raise SystemExit(
                    "ablation preflight failed — fix issues above or run --ablation-preflight"
                )
            guard_ablation_fresh_start(
                report_path,
                resume=bool(a.ablation_resume),
                force_restart=bool(a.ablation_force_restart),
            )
        report = build_ablation_report(
            Path(a.manifest_path),
            dry_run=a.ablation_dry_run,
            tickers=tickers if not a.ablation_dry_run else None,
            resume=bool(a.ablation_resume and not a.ablation_dry_run),
            report_path=report_path,
        )
        out_p = write_ablation_report(report, report_path)
        method = report["ablation_method"]
        meta = report.get("run_meta") or {}
        surv = report.get("survivor_summary") or {}
        print(
            f"wrote {out_p}  per_model_feature_cells={report['per_model_feature_cell_count']}  "
            f"stack_authority_cells={report['stack_authority_cell_count']}  "
            f"total_grid={report['grid_cell_count']}  "
            f"horizons={method['horizons']}  "
            f"full_stack_layers={report.get('full_stack_layers')}  "
            f"scored_ok={meta.get('per_model_ok', 'n/a')}  "
            f"survivor_groups={len(surv.get('groups') or [])}  "
            f"run_status={meta.get('status', 'dry_run')}  "
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
