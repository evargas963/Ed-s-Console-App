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

Ablation harness (``--ablation``): manifest-only contract — **all four horizons**
(1c / 5c / 15c / 60c) and **all seven stack models** on the placement grid. Partial-horizon
or partial-model grids are rejected. See ``TRAINING_AND_MAINTENANCE.md`` §Feature placement matrix.

  - **Placement grid (binding):** ``feature × model × horizon`` where **model** is all seven
    layers (``xgb``, ``lstm``, ``transformer``, ``meta``, ``monte_carlo``, ``regime``, ``fusion``)
    and **horizon** is all four (``1c``, ``5c``, ``15c``, ``60c``). One atomic feature permuted
    per cell; scored through the production seven-layer fusion path; survivors per
    ``survivor_summary.by_model_horizon[model][horizon]``.
  - **Legacy partial axis (``--ablation-include-o56``):** holdout MCC permute for
    xgb/lstm/transformer only — diagnostic; does **not** substitute for the full grid.
  - **Stack authority (``--ablation-include-stack-authority``):** optional anchor×horizon
    mode-lift pass — separate from per-feature placement.

Usage: python tools/feature_curation_gate.py [--tickers SPY,QQQ,IWM] [--null-thresh 0.98]
"""
from __future__ import annotations

# RC-345/F25: stack-eval model-dir identity consumes the ONE canonical ticker authority so
# bare 'SPX' and '$SPX' resolve to the same bundle the writers/promotion produced.
from instrument_identity import ticker_storage_key

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
from governed_stack_contract import FULL_STACK_MODEL_LAYERS

_UNSET: object = object()


def enriched_rows_for_spec_build(
    enriched: list[dict] | None,
) -> list[dict] | None:
    """Preserve ``[]`` (empty CI/DB sample) vs ``None`` (unsampled) for knockout fidelity."""
    if enriched is None:
        return None
    return enriched


def resolve_ablation_enriched_row_sample(
    manifest: dict,
    *,
    db_path: str | Path | None = None,
    tickers: list[str] | None = None,
) -> list[dict] | None:
    """Row-fidelity sample for knockout resolution — ``None`` if no DB, ``[]`` if schema-only/empty."""
    dbp = str(db_path if db_path is not None else DB_PATH)
    if not Path(dbp).is_file():
        return None
    return build_ablation_enriched_row_sample(
        db_path=dbp,
        manifest=manifest,
        tickers=tickers,
    )


def ablation_row_fidelity_sample_active(enriched: list[dict] | None) -> bool:
    """True when enriched rows exist for fidelity-first knockout checks (non-empty sample)."""
    return bool(enriched)

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
MANIFEST_PATH = Path("governance/artifacts/feature_ablation_manifest_leaf.json")
LEGACY_COMPOUND_MANIFEST_PATH = Path("governance/artifacts/feature_ablation_manifest.json")
ABLATION_REPORT_PATH = Path("governance/artifacts/feature_ablation_report_leaf.json")
LEGACY_COMPOUND_REPORT_PATH = Path("governance/artifacts/feature_ablation_report.json")
ABLATION_LOCK_PATH = Path("governance/artifacts/feature_ablation.run.lock")
REQUIRED_ABLATION_HORIZONS = ("1c", "5c", "15c", "60c")
FULL_STACK_LAYERS = FULL_STACK_MODEL_LAYERS


def whole_stack_cell_target(manifest: dict | None = None) -> int:
    """Dynamic per-model MCC matrix cell target (Stage 2 placement axis)."""
    if manifest is not None:
        from tools.build_feature_assignment_matrix_v2 import per_model_ablation_cell_target

        return per_model_ablation_cell_target(manifest)
    from tools.build_feature_assignment_matrix_v2 import load_ablation_cell_target

    return load_ablation_cell_target(MANIFEST_PATH)


def whole_stack_catalog_cell_target(manifest: dict | None = None) -> int:
    """Catalog grid slots: every manifest ABLATE row × all seven models × all four horizons (includes unwired Schwab)."""
    if manifest is None:
        manifest = load_ablation_manifest()
    hz = len(_required_ablation_horizons(manifest))
    groups = len(ablation_grid_groups(manifest))
    stack_models = len(list(manifest["ablation_method"].get("full_stack_layers") or FULL_STACK_LAYERS))
    return groups * stack_models * hz


def ablation_whole_stack_runnable_specs(
    manifest: dict,
    tickers: list[str] | None = None,
    *,
    enriched_rows: list[dict] | None | object = _UNSET,
) -> list[dict]:
    """Specs that will actually score — blank-slate row fidelity when enriched_rows supplied."""
    if enriched_rows is _UNSET:
        enriched_rows = resolve_ablation_enriched_row_sample(manifest, tickers=tickers)
    enriched_rows = enriched_rows_for_spec_build(
        enriched_rows if isinstance(enriched_rows, list) or enriched_rows is None else None
    )
    return [
        s
        for s in ablation_whole_stack_feature_cell_specs(
            manifest, tickers=tickers, enriched_rows=enriched_rows
        )
        if s.get("group_columns")
    ]


def whole_stack_runnable_cell_target(
    manifest: dict | None = None,
    *,
    enriched_rows: list[dict] | None | object = _UNSET,
    db_path: str | Path | None = None,
) -> int:
    """Scored-ablation denominator — wire columns present on blank-slate enriched rows only."""
    if manifest is None:
        manifest = load_ablation_manifest()
    if enriched_rows is _UNSET:
        enriched_rows = resolve_ablation_enriched_row_sample(manifest, db_path=db_path)
    enriched_rows = enriched_rows_for_spec_build(
        enriched_rows if isinstance(enriched_rows, list) or enriched_rows is None else None
    )
    return len(
        ablation_whole_stack_runnable_specs(
            manifest, enriched_rows=enriched_rows
        )
    )


def ablation_cell_accounting(
    manifest: dict,
    specs: list[dict] | None = None,
    *,
    enriched_rows: list[dict] | None = None,
) -> dict:
    """Catalog vs runnable counts — trustworthy progress/stats denominators (operator binding)."""
    if specs is None:
        if enriched_rows is None:
            enriched_rows = resolve_ablation_enriched_row_sample(manifest)
        specs = ablation_whole_stack_feature_cell_specs(
            manifest, enriched_rows=enriched_rows_for_spec_build(enriched_rows)
        )
    catalog = whole_stack_catalog_cell_target(manifest)
    runnable = sum(1 for s in specs if s.get("group_columns"))
    skip_by_reason: dict[str, int] = {}
    runnable_by_model: dict[str, int] = {}
    for s in specs:
        if s.get("group_columns"):
            mf = str(s.get("model_family") or "")
            runnable_by_model[mf] = runnable_by_model.get(mf, 0) + 1
        else:
            reason = str(s.get("grid_skip_reason") or "unknown")
            skip_by_reason[reason] = skip_by_reason.get(reason, 0) + 1
    groups = ablation_grid_groups(manifest)
    dbp = str(DB_PATH) if Path(DB_PATH).is_file() else None
    scoring = ablation_scoring_groups(manifest, db_path=dbp)
    in_cone = len(scoring)
    not_wired_groups = len(groups) - in_cone
    hz_n = len(_required_ablation_horizons(manifest))
    stack_n = len(list(manifest["ablation_method"].get("full_stack_layers") or FULL_STACK_LAYERS))
    if not_wired_groups > 0:
        skip_by_reason["not_wired"] = skip_by_reason.get("not_wired", 0) + (
            not_wired_groups * stack_n * hz_n
        )
    schwab = sum(1 for g in groups if str(g.get("group_id", "")).startswith("schwab__"))
    from governed_stack_contract import meta_tabular_feature_order

    return {
        "catalog_target": catalog,
        "runnable_target": runnable,
        "catalog_only_target": catalog - runnable,
        "skip_by_reason": skip_by_reason,
        "runnable_by_model": runnable_by_model,
        "manifest_groups": len(groups),
        "manifest_in_cone": in_cone,
        "manifest_schwab_catalog": schwab,
        "meta_runnable": int(runnable_by_model.get("meta") or 0),
        "meta_tabular_ingest": (
            "Meta-learner v2: stacked base probabilities (9) plus fusion-overlay tabular "
            f"context ({len(meta_tabular_feature_order())} raw columns via "
            "features.fusion_model_input.meta_tabular_vector_from_overlay). Legacy 9-dim "
            "pickles ignore tabular until retrain."
        ),
    }


def whole_stack_fusion_cell_target(manifest: dict | None = None) -> int:
    """Primary ablation progress/completion denominator — runnable cells only, not catalog slots."""
    return whole_stack_runnable_cell_target(manifest)


def _ablation_cell_knockout_columns(cell: dict) -> list[str]:
    """Knockout column list on a scored whole-stack cell (canonical + legacy field names)."""
    raw = (
        cell.get("columns_permuted")
        or cell.get("group_columns")
        or cell.get("columns_requested")
        or []
    )
    return [str(c) for c in raw] if isinstance(raw, list) else []


def _ablation_cell_is_runnable(cell: dict) -> bool:
    """Whether a whole-stack cell counts toward the runnable scored denominator."""
    if cell.get("runnable") is True:
        return True
    if cell.get("runnable") is False:
        return False
    # Legacy checkpoints omitted ``runnable`` — infer from terminal in_cone scores only.
    if str(cell.get("group_id") or "").startswith("schwab__"):
        return False
    if cell.get("reason") == "not_wired" or cell.get("grid_skip_reason") == "not_wired":
        return False
    if cell.get("ablation_kind") != "whole_stack_feature_group":
        return False
    return cell.get("status") in ("ok", "skipped")


def _resolve_ablation_runnable_target(
    report: dict,
    *,
    manifest: dict | None = None,
) -> int:
    """Runnable denominator from report accounting, else manifest grid (legacy reports)."""
    accounting = report.get("ablation_accounting") or {}
    pinned = int(
        report.get("whole_stack_runnable_cell_target")
        or accounting.get("runnable_target")
        or 0
    )
    if pinned > 0:
        return pinned
    try:
        if manifest is None:
            manifest = load_ablation_manifest()
        return whole_stack_runnable_cell_target(manifest)
    except Exception:
        return 0


def _finalize_whole_stack_scored_cell(cell: dict) -> dict:
    """Fail-closed: never leave status=ok when knockout permuted zero columns."""
    if (
        cell.get("status") == "ok"
        and int(cell.get("columns_permuted_count") or 0) == 0
    ):
        cell = dict(cell)
        cell["status"] = "skipped"
        cell["reason"] = "noop_knockout:zero_columns_permuted"
        cell["group_matters"] = False
    return cell


# Backward-compatible alias for tests importing WHOLE_STACK_CELL_TARGET.
WHOLE_STACK_CELL_TARGET = 0  # use whole_stack_cell_target() — 828 compound-era constant retired
PER_MODEL_CONFIRM_CELL_TARGET = 36  # 3 anchors × 3 models × 4 horizons (drop-and-refit confirm pass)


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
            f"Ablation manifest must score all seven stack models {list(FULL_STACK_LAYERS)}; got {layers}."
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


def ablation_grid_groups(manifest: dict) -> list[dict]:
    """Full manifest ABLATE rows — catalog accounting includes Schwab catalog slots."""
    return ablation_groups(manifest)


ABLATION_SNAPSHOT_TABLE = "snapshots_1m_normalized"
ABLATION_INGEST_DERIVED_PREFIXES = ("cf_",)
ABLATION_DB_NON_ABLATABLE_EXACT = frozenset(
    {
        "snapshot_id",
        "ticker",
        "timeframe",
        "expiry",
        "dte",
        "hours_to_expiry",
        "ts_utc",
        "ts_et",
        "et_hour",
        "et_minute",
        "market_session",
        "created_at",
        "outcome_filled",
        "horizon_outcome_schema_version",
    }
)


def ablation_db_column_names(db_path: str, *, table: str = ABLATION_SNAPSHOT_TABLE) -> set[str]:
    """Column names on the normalized snapshot table (wire authority for ablation ingest)."""
    dbp = Path(db_path)
    if not dbp.is_file():
        return set()
    con = sqlite3.connect(str(dbp))
    try:
        return {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})")}
    finally:
        con.close()


def ablation_db_non_ablatable_columns(db_path: str | None = None) -> set[str]:
    """Metadata, outcomes, leakage, model outputs, and derived-only prefixes — never knocked out."""
    blocked = set(ABLATION_DB_NON_ABLATABLE_EXACT)
    if db_path and Path(db_path).is_file():
        for col in ablation_db_column_names(db_path):
            if col.startswith("outcome_"):
                blocked.add(col)
            for prefix in LEAKAGE_PREFIXES + ABLATION_INGEST_DERIVED_PREFIXES:
                if col.startswith(prefix):
                    blocked.add(col)
    return blocked


def ablation_db_wire_ablatable_columns(db_path: str) -> set[str]:
    """One DB column = one ablatable wire atom (minus metadata/leakage/outcomes/derived)."""
    all_cols = ablation_db_column_names(db_path)
    if not all_cols:
        return set()
    blocked = ablation_db_non_ablatable_columns(db_path)
    return {c for c in all_cols if c not in blocked and not c.startswith("outcome_")}


def ablation_scoring_groups(manifest: dict, *, db_path: str | None = None) -> list[dict]:
    """Features scored in Stage 3 — DB wire atoms present on snapshot rows (catalog retained, not scored)."""
    in_cone = [g for g in ablation_grid_groups(manifest) if g.get("ingest_status") == "in_cone"]
    dbp = db_path or str(DB_PATH)
    if not Path(dbp).is_file():
        return in_cone
    wire = ablation_db_wire_ablatable_columns(dbp)
    out: list[dict] = []
    for g in in_cone:
        col = _atomic_column_for_group(g)
        if col and col in wire:
            out.append(g)
    return out


def ablation_whole_stack_feature_cell_specs(
    manifest: dict,
    tickers: list[str] | None = None,
    *,
    enriched_rows: list[dict] | None = None,
) -> list[dict]:
    """Placement grid: in_cone feature × all seven stack models × all four horizons.

    One cohesive seven-layer stack — knockout columns are unified per feature (not registry-
    partitioned by model). When ``enriched_rows`` is supplied, columns resolve only from keys
    present on the production-parity enriched row surface (fidelity-first).
    """
    method = manifest["ablation_method"]
    full_stack_layers = list(method.get("full_stack_layers") or FULL_STACK_LAYERS)
    horizons = list(method.get("horizons") or _required_ablation_horizons(manifest))
    pool_tickers = _ablation_pool_tickers(manifest, tickers)
    cells: list[dict] = []
    for model in full_stack_layers:
        for hz in horizons:
            for grp in ablation_scoring_groups(manifest):
                group_columns = _whole_stack_knockout_columns(grp, enriched_rows)
                entry_layers = [model] if group_columns else []
                runnable = bool(group_columns)
                grid_skip_reason = None if runnable else (
                    "missing_atomic_column"
                    if not _atomic_column_for_group(grp)
                    else "columns_absent_from_rows"
                )
                cells.append(
                    {
                        "model_family": model,
                        "horizon_slug": hz,
                        "group_id": grp["group_id"],
                        "ablation_kind": "whole_stack_feature_group",
                        "decision_mode": "full_fusion",
                        "full_stack_layers": full_stack_layers,
                        "stack_entry_layers": entry_layers,
                        "group_columns": group_columns,
                        "grid_skip_reason": grid_skip_reason,
                        "runnable": runnable,
                        "ingest_status": grp.get("ingest_status"),
                        "pool_tickers": pool_tickers,
                        "stage3_scoring_mode": "pooled_ticker_rows_per_model_layer",
                        "knockout_resolution": "fidelity_unified",
                    }
                )
    return cells


def _ablation_pool_tickers(manifest: dict, tickers: list[str] | None = None) -> list[str]:
    """Tickers whose rows are pooled for ticker-agnostic Stage 3 scoring (not a grid axis)."""
    from governed_stack_contract import ABLATION_ANCHOR_TICKERS

    if tickers:
        return [ticker_storage_key(t) for t in tickers if t.strip()]  # RC-345/F25
    method = manifest.get("ablation_method") or {}
    pool = method.get("pool_tickers") or method.get("anchors") or list(ABLATION_ANCHOR_TICKERS)
    return [ticker_storage_key(str(t)) for t in pool if str(t).strip()]  # RC-345/F25


def _atomic_column_for_group(group: dict) -> str | None:
    """Single atomic column identity — placement is NOT read from manifest members."""
    col = group.get("atomic_column")
    if col:
        return str(col).strip() or None
    gid = str(group.get("group_id") or "")
    if gid.startswith("reg__atomic__"):
        return gid[len("reg__atomic__") :]
    if gid.startswith("schwab__"):
        return gid[len("schwab__") :]
    if gid.startswith("snap__"):
        return gid[len("snap__") :]
    return None


def _ablation_columns_for_atomic_feature(
    column: str,
    model_family: str,
    *,
    offline_v2_encode: bool = False,
) -> list[str]:
    """Legacy O-56 per-model registry resolver — NOT used for whole-stack placement grid.

    Whole-stack ablation uses ``_ablation_atomic_knockout_column_candidates`` +
    ``_whole_stack_knockout_columns`` (fidelity-first, unified across all seven layers).
    """
    from arch_competition.stack_bundle_eval_v1 import xgb_engineered_members_to_raw_snapshot
    from tools.build_feature_assignment_matrix_v2 import _registered_ml_columns

    registered = _registered_ml_columns()
    if model_family == "xgb":
        if column not in registered.get("xgb", set()):
            return []
        cols = set(xgb_engineered_members_to_raw_snapshot([column]))
        if column.startswith("cf_"):
            cols.add(column)
        return sorted(cols)
    if offline_v2_encode and model_family in ("lstm", "transformer"):
        from arch_competition.ablation_bundle_inference import offline_v2_knockout_snapshot_columns

        return offline_v2_knockout_snapshot_columns(column, model_family)
    if model_family == "lstm":
        out: set[str] = set()
        if column in registered.get("lstm_5m", set()):
            out.add(column)
        if column in registered.get("lstm_1m", set()):
            out.add(column)
        return sorted(out)
    if model_family == "transformer":
        try:
            from features.lstm_sequence_input import ENCODED_FEATURES_5M
        except ImportError:
            ENCODED_FEATURES_5M = ()
        if column not in set(ENCODED_FEATURES_5M):
            return []
        return [column]
    from governed_stack_contract import atomic_column_consumed_by_stack_layer

    if model_family in ("meta", "monte_carlo", "regime", "fusion"):
        if not atomic_column_consumed_by_stack_layer(column, model_family):
            return []
        cols: set[str] = {column}
        if column.startswith("cf_"):
            cols.update(xgb_engineered_members_to_raw_snapshot([column]))
            cols.add(column)
        return sorted(cols)
    return []


# DB wire aliases only (Schwab/snapshot column names) — NOT XGB engineer dependency graphs.
_ABLATION_DB_WIRE_ALIASES: dict[str, tuple[str, ...]] = {
    "bid_ask_imbalance": ("flow_imbalance",),
}


def _ablation_atomic_knockout_column_candidates(column: str) -> list[str]:
    """Blank-slate knockout candidates — atomic wire name (+ DB alias), no ml_train/XGB engineer graph."""
    col = str(column or "").strip()
    if not col:
        return []
    out: set[str] = {col}
    out.update(_ABLATION_DB_WIRE_ALIASES.get(col, ()))
    return sorted(out)


def _knockout_columns_on_rows(candidates: list[str], rows: list[dict]) -> list[str]:
    """Columns from ``candidates`` that exist on at least one enriched row dict key."""
    if not candidates or not rows:
        return []
    return sorted(c for c in candidates if any(c in r for r in rows))


def _whole_stack_knockout_columns(
    group: dict,
    enriched_rows: list[dict] | None = None,
) -> list[str]:
    """Blank-slate cone — same wire columns for every stack layer; presence on shared row surface only."""
    column = _atomic_column_for_group(group)
    if not column or group.get("ingest_status") != "in_cone":
        return []
    candidates = _ablation_atomic_knockout_column_candidates(column)
    if enriched_rows is not None:
        return _knockout_columns_on_rows(candidates, enriched_rows)
    return candidates


def _whole_stack_group_columns_for_family(
    group: dict,
    model_family: str,
    enriched_rows: list[dict] | None = None,
) -> list[str]:
    """Backward-compatible alias — model_family ignored (unified seven-layer knockouts)."""
    _ = model_family
    return _whole_stack_knockout_columns(group, enriched_rows)


def _per_model_permute_members(group: dict, model_family: str) -> dict[str, list[str]]:
    """Permute-null columns for one O-56 ML stack layer — live ingest cone, not manifest stamp."""
    col = _atomic_column_for_group(group)
    if not col:
        return {"xgb_members": [], "lstm_5m_members": [], "lstm_1m_members": []}
    if model_family == "xgb":
        return {
            "xgb_members": _ablation_columns_for_atomic_feature(col, "xgb"),
            "lstm_5m_members": [],
            "lstm_1m_members": [],
        }
    if model_family == "lstm":
        from tools.build_feature_assignment_matrix_v2 import _registered_ml_columns

        reg = _registered_ml_columns()
        lstm_cols = _ablation_columns_for_atomic_feature(col, "lstm")
        return {
            "xgb_members": [],
            "lstm_5m_members": [c for c in lstm_cols if c in reg.get("lstm_5m", set())],
            "lstm_1m_members": [c for c in lstm_cols if c in reg.get("lstm_1m", set())],
        }
    return {
        "xgb_members": [],
        "lstm_5m_members": _ablation_columns_for_atomic_feature(col, "transformer"),
        "lstm_1m_members": [],
    }


def _enrich_rows_for_whole_stack_ablation(
    rows: list[dict],
    *,
    db_path: str | None = None,
) -> list[dict]:
    """DB identity row surface — snapshot dict keys only (no lstm_data/ml_train feature engineering).

    Knockout column discovery uses this surface. Scoring uses the unified seven-layer wire-row path
    (``score_unified_ablation_fusion_from_wire_row`` — one branch, no production fork).
    """
    _ = db_path
    if not rows:
        return rows
    return [dict(r) for r in rows]


def build_ablation_enriched_row_sample(
    *,
    db_path: str,
    manifest: dict | None = None,
    tickers: list[str] | None = None,
    max_rows_per_ticker: int = 80,
) -> list[dict]:
    """Pooled enriched rows for preflight row-fidelity and spec column resolution."""
    from arch_competition.stack_bundle_eval_v1 import (
        ABLATION_ROW_TICKER_FIELD,
        StackBundleEvalOptions,
        _load_chronological_rth_rows,
    )
    from ml_horizon import outcome_column

    manifest = manifest or load_ablation_manifest()
    pool = tickers or _ablation_pool_tickers(manifest)
    hz = _required_ablation_horizons(manifest)[0]
    target = outcome_column(hz)
    opts = StackBundleEvalOptions(max_rows=max_rows_per_ticker)
    rows: list[dict] = []
    for t in pool:
        tu = ticker_storage_key(t)  # RC-345/F25
        chunk = _load_chronological_rth_rows(db_path, tu, target_column=target, options=opts)
        for r in chunk:
            tagged = dict(r)
            tagged[ABLATION_ROW_TICKER_FIELD] = tu
            rows.append(tagged)
    return _enrich_rows_for_whole_stack_ablation(rows, db_path=db_path) if rows else []


def audit_ablation_row_fidelity(
    manifest: dict,
    *,
    db_path: str,
    tickers: list[str] | None = None,
) -> dict:
    """Fail-closed: scored cells must have knockout columns on enriched rows; absent → not runnable."""
    errors: list[str] = []
    enriched = build_ablation_enriched_row_sample(
        db_path=db_path, manifest=manifest, tickers=tickers
    )
    dbp = db_path
    if not enriched:
        return {
            "ok": False,
            "errors": ["row fidelity: no enriched sample rows from DB"],
            "stats": {"enriched_row_count": 0},
        }
    absent: list[str] = []
    present_count = 0
    dbp = db_path
    for grp in ablation_scoring_groups(manifest, db_path=dbp):
        gid = str(grp.get("group_id") or "")
        cols = _whole_stack_knockout_columns(grp, enriched)
        if cols:
            present_count += 1
        else:
            absent.append(gid)
    specs = ablation_whole_stack_feature_cell_specs(manifest, enriched_rows=enriched)
    bogus_runnable = [
        s
        for s in specs
        if s.get("runnable") and not (s.get("group_columns") or [])
    ]
    if bogus_runnable:
        sample = bogus_runnable[0]
        errors.append(
            f"row fidelity: {len(bogus_runnable)} cells marked runnable with empty group_columns "
            f"(e.g. {sample.get('group_id')}@{sample.get('model_family')}) — registry/fallback bias"
        )
    stats = {
        "enriched_row_count": len(enriched),
        "in_cone_features": len(ablation_scoring_groups(manifest, db_path=dbp)),
        "features_with_row_columns": present_count,
        "features_absent_from_rows": len(absent),
        "absent_feature_ids_sample": absent[:12],
        "runnable_cell_target": sum(1 for s in specs if s.get("group_columns")),
        "bogus_runnable_cells": len(bogus_runnable),
    }
    if absent:
        stats["absent_note"] = (
            f"{len(absent)} in_cone features have no knockout columns on enriched rows — "
            "honestly skipped (not runnable); not a preflight failure when bogus_runnable_cells=0"
        )
    return {"ok": not errors, "errors": errors, "stats": stats}


def audit_ablation_ingest_purity(
    manifest: dict,
    *,
    db_path: str,
    tickers: list[str] | None = None,
) -> dict:
    """Fail-closed: enriched rows must be DB identity — no derived columns added at ingest."""
    errors: list[str] = []
    from arch_competition.stack_bundle_eval_v1 import (
        ABLATION_ROW_TICKER_FIELD,
        StackBundleEvalOptions,
        _load_chronological_rth_rows,
    )
    from ml_horizon import outcome_column

    pool = tickers or _ablation_pool_tickers(manifest)
    hz = _required_ablation_horizons(manifest)[0]
    target = outcome_column(hz)
    opts = StackBundleEvalOptions(max_rows=40)
    raw_rows: list[dict] = []
    for t in pool:
        tu = ticker_storage_key(t)  # RC-345/F25
        chunk = _load_chronological_rth_rows(db_path, tu, target_column=target, options=opts)
        for r in chunk[:20]:
            tagged = dict(r)
            tagged[ABLATION_ROW_TICKER_FIELD] = tu
            raw_rows.append(tagged)
    if not raw_rows:
        return {
            "ok": False,
            "errors": ["ingest purity: no raw DB rows for sample"],
            "stats": {"raw_row_count": 0},
        }
    enriched = _enrich_rows_for_whole_stack_ablation(raw_rows, db_path=db_path)
    db_cols = ablation_db_column_names(db_path)
    allowed_extra = {ABLATION_ROW_TICKER_FIELD}
    derived_prefixes = ABLATION_INGEST_DERIVED_PREFIXES
    added_keys: set[str] = set()
    for raw, enr in zip(raw_rows, enriched):
        raw_keys = set(raw.keys())
        for k in enr.keys():
            if k in raw_keys or k in allowed_extra:
                continue
            added_keys.add(k)
    bad_derived = sorted(k for k in added_keys if any(k.startswith(p) for p in derived_prefixes))
    non_db = sorted(k for k in added_keys if k not in db_cols and k not in allowed_extra)
    if bad_derived:
        errors.append(
            f"ingest purity: enrichment added derived-only keys {bad_derived[:8]} — "
            f"lstm_data/ml_train must not define ablation cone authority"
        )
    if non_db:
        errors.append(
            f"ingest purity: enrichment added non-DB keys {non_db[:8]} — identity enrich only"
        )
    code_derived_in_cone = [
        str(g.get("group_id"))
        for g in ablation_scoring_groups(manifest, db_path=db_path)
        if str(_atomic_column_for_group(g) or "").startswith(derived_prefixes)
    ]
    if code_derived_in_cone:
        errors.append(
            f"ingest purity: {len(code_derived_in_cone)} scoring groups are derived-only "
            f"(e.g. {code_derived_in_cone[:4]}) — persist to DB or exclude from wire scoring"
        )
    wire = ablation_db_wire_ablatable_columns(db_path)
    stats = {
        "raw_row_count": len(raw_rows),
        "db_column_count": len(db_cols),
        "wire_ablatable_count": len(wire),
        "scoring_group_count": len(ablation_scoring_groups(manifest, db_path=db_path)),
        "manifest_in_cone_count": len(
            [g for g in ablation_grid_groups(manifest) if g.get("ingest_status") == "in_cone"]
        ),
        "added_keys_sample": sorted(added_keys)[:12],
    }
    return {"ok": not errors, "errors": errors, "stats": stats}


def audit_ablation_score_path_bias() -> dict:
    """Verify wire-neutral score path — preflight ``ready`` requires ok:true (no hardcoded derailers)."""
    errors: list[str] = []
    repo = Path(__file__).resolve().parent.parent
    checks: list[dict] = []

    def _record(cid: str, ok: bool, detail: str) -> None:
        checks.append({"id": cid, "ok": ok, "detail": detail})
        if not ok:
            errors.append(f"score_path:{cid}: {detail}")

    mp_py = repo / "ml_predict.py"
    sbe_py = repo / "arch_competition" / "stack_bundle_eval_v1.py"
    abi_py = repo / "arch_competition" / "ablation_bundle_inference.py"
    gate_py = Path(__file__).resolve()

    if not abi_py.is_file():
        _record("ablation_bundle_inference", False, "missing ablation_bundle_inference.py")
    else:
        abi_text = abi_py.read_text(encoding="utf-8", errors="replace")
        _record(
            "wire_neutral_xgb",
            "wire_neutral_xgb_predict_from_row" in abi_text,
            "wire_neutral_xgb_predict_from_row must exist",
        )
        _record(
            "wire_neutral_confluence",
            "wire_neutral_confluence_vector" in abi_text
            and "compute_confluence_features(merged_days" not in abi_text,
            "LSTM offline must use wire_neutral_confluence_vector not compute_confluence_features",
        )
        _record(
            "wire_row_surface_bars",
            "wire_row_surface_bars" in abi_text
            and "overlay_ablation_wire_row_on_sequence_bars" not in abi_text,
            "LSTM/TR must use wire_row_surface_bars only — no DB history overlay",
        )
        _record(
            "unified_ablation_scorer",
            "score_unified_ablation_fusion_from_wire_row" in abi_text,
            "unified seven-layer scorer must exist in ablation_bundle_inference",
        )

    if mp_py.is_file():
        mp_text = mp_py.read_text(encoding="utf-8", errors="replace")
        _record(
            "ml_predict_no_ablation_predict_fork",
            "overlay_ablation_wire_row_on_sequence_bars" not in mp_text
            and "predict_lstm_offline" not in mp_text.split("def _predict_lstm", 1)[-1][:2500],
            "ml_predict must not fork LSTM/TR/XGB predict paths for ablation",
        )

    if sbe_py.is_file():
        sbe_text = sbe_py.read_text(encoding="utf-8", errors="replace")
        fn_block = sbe_text.split("def _production_fusion_prob_for_row", 1)[-1].split("\ndef ", 1)[0]
        _record(
            "unified_scorer_delegate",
            "score_unified_ablation_fusion_from_wire_row" in fn_block
            and "ablation_scoring_pass_active()" in fn_block,
            "_production_fusion_prob_for_row must delegate to unified scorer under ablation",
        )
        _record(
            "no_production_fusion_fork",
            "ablation_wire_row=" not in fn_block
            and (
                "production_fusion_payload_for_stack(" not in fn_block.split("if ablation_scoring_pass_active()", 1)[0]
                or "score_unified_ablation_fusion_from_wire_row" in fn_block
            ),
            "ablation scoring must not thread ablation_wire_row into production_fusion_payload_for_stack",
        )
        _record(
            "no_fusion_overlay_under_ablation",
            "build_fusion_model_overlay_for_stack" not in fn_block.split("if ablation_scoring_pass_active()", 1)[0]
            or "score_unified_ablation_fusion_from_wire_row" in fn_block,
            "must not call build_fusion_model_overlay_for_stack before unified ablation branch",
        )

    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
    _record(
        "scoring_groups_db_wire",
        "ablation_db_wire_ablatable_columns" in gate_text
        and "def ablation_scoring_groups(manifest: dict, *, db_path:" in gate_text.replace("\n", " "),
        "ablation_scoring_groups must filter manifest to DB wire columns",
    )
    import re

    eval_opts_m = re.search(
        r"^def _ablation_eval_options\(\):.*?(?=^def |\Z)",
        gate_text,
        re.MULTILINE | re.DOTALL,
    )
    eval_opts_block = eval_opts_m.group(0) if eval_opts_m else ""
    _record(
        "ablation_full_history_default",
        "opts.max_rows = None" in eval_opts_block,
        "_ablation_eval_options must default to full RTH (max_rows=None)",
    )

    try:
        from db import DB_PATH as _dbp

        db_path = str(_dbp)
        if Path(db_path).is_file():
            manifest = load_ablation_manifest()
            for g in ablation_scoring_groups(manifest, db_path=db_path):
                col = _atomic_column_for_group(g)
                if col and col.startswith("cf_"):
                    _record("no_cf_in_wire_scoring", False, f"derived cf_* in scoring: {col}")
                    break
            else:
                _record("no_cf_in_wire_scoring", True, "no cf_* in wire scoring groups")
    except Exception as exc:
        _record("wire_scoring_runtime", False, f"could not verify wire scoring groups: {exc}")

    return {
        "ok": not errors,
        "errors": errors,
        "checks": checks,
        "admissible_modes": {
            "unbiased_ablation": "ingest_purity ok AND score_path_bias ok",
        },
    }


_REGISTERED_MANIFEST_INGEST_TIERS = frozenset({"REGISTERED_UNIVERSE", "REGISTERED_CONFLUENCE"})


def reconcile_manifest_ingest_status_to_db_wire(manifest: dict, db_path: str) -> dict:
    """Re-stamp manifest ingest_status: registered ML cone vs DB-wire Schwab/snapshot candidates."""
    wire = ablation_db_wire_ablatable_columns(db_path)
    for g in manifest.get("groups") or []:
        if g.get("disposition") != "ABLATE":
            continue
        col = _atomic_column_for_group(g)
        if not col:
            continue
        tier = str(g.get("catalog_tier") or "")
        if tier in _REGISTERED_MANIFEST_INGEST_TIERS:
            # engineer_features / sequence encoders consume these even when not snapshot columns
            g["ingest_status"] = "in_cone"
        elif col in wire:
            g["ingest_status"] = "in_cone"
        elif tier == "SNAPSHOT_EXPANSION" and g.get("ingest_status") == "in_snapshot":
            continue
        else:
            g["ingest_status"] = "not_wired"
    return manifest


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
    t = ticker_storage_key(ticker)  # RC-345/F25: callee consumes canonical identity directly
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


def _parallel_model_dir_for_stack_eval(ticker: str) -> Path:
    return _repo_models_dir() / "parallel" / ticker_storage_key(ticker)  # RC-345/F25: callee canonical, no caller masking


def _bundle_has_scorable_base_artifacts(ticker: str, horizon_slug: str, bundle: Path) -> bool:
    """True when the full parallel stack bundle (bases + meta-stack pkl) exists for this horizon."""
    from active_bundle_contract import horizon_bundle_filenames

    if not bundle.is_dir():
        return False
    return all((bundle / name).is_file() for name in horizon_bundle_filenames(ticker, horizon_slug))


def _resolve_model_dir_for_stack_eval(ticker: str, horizon_slug: str) -> Path | None:
    """Prefer a production-compliant bundle: active when compliant, else parallel candidates."""
    from active_bundle_contract import check_active_bundle_complete
    from ml_horizon import normalize_ml_horizon_slug

    prefer = (os.environ.get("ED_STACK_EVAL_BUNDLE") or "").strip().lower()
    t = ticker_storage_key(ticker)  # RC-345/F25: one canonical model-dir identity
    hz = normalize_ml_horizon_slug(horizon_slug)
    models_dir = _repo_models_dir()
    parallel = _parallel_model_dir_for_stack_eval(t)
    active, _issues = _active_model_dir_for_ablation(t, horizon_slug)

    def _compliant(bundle: Path | None) -> bool:
        if bundle is None:
            return False
        chk = check_active_bundle_complete(t, hz, bundle_dir=bundle, models_dir=models_dir)
        return bool(chk.get("compliant"))

    if prefer == "parallel" and _bundle_has_scorable_base_artifacts(t, hz, parallel):
        return parallel
    if active and _compliant(active):
        return active
    if _bundle_has_scorable_base_artifacts(t, hz, parallel) and _compliant(parallel):
        return parallel
    if active and _bundle_has_scorable_base_artifacts(t, hz, active):
        return active
    return active or (parallel if parallel.is_dir() else None)


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
        opts.max_rows = None
    return opts


def _whole_stack_cell_key(
    horizon_slug: str,
    group_id: str,
    *,
    model_family: str | None = None,
    anchor_ticker: str | None = None,
) -> str:
    if model_family:
        return f"{model_family}|{horizon_slug}|{group_id}"
    if anchor_ticker:
        return f"{ticker_storage_key(anchor_ticker)}|{horizon_slug}|{group_id}"  # RC-345/F25
    return f"{horizon_slug}|{group_id}"


def _whole_stack_resume_cell(
    resume_cells: dict[str, dict],
    horizon_slug: str,
    group_id: str,
    *,
    model_family: str | None = None,
    anchor_ticker: str | None = None,
) -> dict | None:
    """Resume lookup — model|horizon|group plus legacy horizon|group keys."""
    ck = _whole_stack_cell_key(
        horizon_slug, group_id, model_family=model_family, anchor_ticker=anchor_ticker
    )
    if ck in resume_cells:
        return resume_cells[ck]
    prefix = f"{ck}|"
    for key, cell in resume_cells.items():
        if key.startswith(prefix):
            return cell
    if model_family is None:
        legacy_suffix = f"|{horizon_slug}|{group_id}"
        for key, cell in resume_cells.items():
            if key.endswith(legacy_suffix):
                return cell
    return None


def _stack_authority_cell_key(anchor_ticker: str, horizon_slug: str) -> str:
    return f"{ticker_storage_key(anchor_ticker)}|{horizon_slug}|stack_authority"  # RC-345/F25


def _index_whole_stack_cells(cells: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in cells:
        if c.get("ablation_kind") != "whole_stack_feature_group":
            continue
        gid = c.get("group_id")
        if not gid:
            continue
        anchor = c.get("anchor_ticker")
        model = c.get("model_family")
        key = _whole_stack_cell_key(
            c["horizon_slug"],
            gid,
            model_family=str(model) if model else None,
            anchor_ticker=str(anchor) if anchor else None,
        )
        out[key] = c
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
    """Fail-closed readiness check before scored ablation (DB + active bundles + stack load)."""
    anchors = tickers or _ablation_pool_tickers(manifest)
    horizons = _required_ablation_horizons(manifest)
    dbp = Path(db_path)
    result: dict = {
        "ready": False,
        "ready_for_xgb_per_model": False,
        "ready_for_whole_stack": False,
        "ready_for_agnostic_ingest": False,
        "ready_for_unbiased_ablation": False,
        "ready_for_production_path_ablation": False,
        "db_path": str(dbp),
        "db_exists": dbp.is_file(),
        "anchors": anchors,
        "horizons": horizons,
        "bundle_checks": [],
        "issues": [],
        "notes": [],
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
                (ticker_storage_key(anchors[0]),),  # RC-345/F25: DB bind consumes canonical identity
            ).fetchone()
            result["snapshot_rows_sample_ticker"] = int(row[0]) if row else 0
            if result["snapshot_rows_sample_ticker"] < 100:
                result["issues"].append(
                    f"insufficient snapshots for {anchors[0]}: {result['snapshot_rows_sample_ticker']}"
                )
        finally:
            con.close()
    except Exception as ex:
        result["issues"].append(f"db_read_failed:{type(ex).__name__}:{ex}")

    db_ok = dbp.is_file() and result.get("snapshot_rows_sample_ticker", 0) >= 100
    whole_stack_ok = True

    from arch_competition.stack_bundle_eval_v1 import ABLATION_SCORING_PASS_ENV

    prev_ablation = os.environ.get(ABLATION_SCORING_PASS_ENV)
    os.environ[ABLATION_SCORING_PASS_ENV] = "1"
    try:
        for anchor in anchors:
            for hz in horizons:
                bundle, issues = _active_model_dir_for_ablation(anchor, hz)
                entry = {
                    "pool_ticker": anchor,
                    "anchor_ticker": anchor,
                    "horizon_slug": hz,
                    "bundle_dir": str(bundle) if bundle else None,
                    "ready": bundle is not None,
                    "issues": list(issues),
                }
                if bundle is not None:
                    from arch_competition.stack_bundle_eval_v1 import (
                        assess_bundle_ablation_lineage,
                        probe_whole_stack_seven_layers,
                    )
                    from active_bundle_contract import check_active_bundle_complete
                    from governed_stack_contract import FULL_STACK_MODEL_LAYERS

                    lineage = assess_bundle_ablation_lineage(
                        anchor, hz, bundle, models_dir=_repo_models_dir()
                    )
                    entry.update(lineage)
                    entry["xgb_per_model_ablation_eligible"] = bool(
                        db_ok and lineage.get("xgb_per_model_ablation_eligible")
                    )

                    prev_strict = os.environ.get("ED_XGB_STRICT_ACTIVE_ONLY")
                    os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = "0"
                    try:
                        prod_chk = check_active_bundle_complete(
                            anchor, hz, bundle_dir=bundle, models_dir=_repo_models_dir()
                        )
                        stack_probe = probe_whole_stack_seven_layers(
                            db_path=str(dbp),
                            ticker=anchor,
                            ml_horizon_slug=hz,
                            bundle_dir=bundle,
                            bundle_artifact_report=prod_chk,
                        )
                    finally:
                        if prev_strict is None:
                            os.environ.pop("ED_XGB_STRICT_ACTIVE_ONLY", None)
                        else:
                            os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = prev_strict
                    entry["stack_layers_required"] = list(FULL_STACK_MODEL_LAYERS)
                    entry["stack_layers"] = stack_probe.get("stack_layers") or {}
                    entry["stack_layers_scored"] = stack_probe.get("stack_layers_scored") or []
                    entry["stack_layers_missing"] = stack_probe.get("missing_layers") or []
                    entry["stack_probe_ok"] = bool(stack_probe.get("ok"))
                    if not stack_probe.get("ok"):
                        whole_stack_ok = False
                        missing = stack_probe.get("missing_layers") or []
                        probe_reason = stack_probe.get("probe_reason")
                        msg = (
                            f"seven-layer stack probe failed {anchor}/{hz}: "
                            f"missing={missing}"
                        )
                        if probe_reason:
                            msg += f"; probe_reason={probe_reason}"
                        result["issues"].append(msg)
                    for note in lineage.get("issues") or []:
                        result["issues"].append(f"{anchor}/{hz}: {note}")

                if bundle is None:
                    whole_stack_ok = False
                    result["issues"].append(
                        f"incomplete bundle {anchor}/{hz}: {issues or ['unknown']}"
                    )
                result["bundle_checks"].append(entry)
    finally:
        if prev_ablation is None:
            os.environ.pop(ABLATION_SCORING_PASS_ENV, None)
        else:
            os.environ[ABLATION_SCORING_PASS_ENV] = prev_ablation

    result["ready_for_xgb_per_model"] = bool(db_ok)
    result["ready_for_whole_stack"] = bool(db_ok and whole_stack_ok)

    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.ablation_integrity import audit_ablation_placement_validity

    placement = audit_ablation_placement_validity()
    result["placement_validity"] = placement
    if not placement.get("ok"):
        result["ready_for_whole_stack"] = False
        for err in placement.get("errors") or []:
            result["issues"].append(err)

    row_fidelity = audit_ablation_row_fidelity(manifest, db_path=str(dbp), tickers=anchors)
    result["row_fidelity"] = row_fidelity
    if not row_fidelity.get("ok"):
        result["ready_for_whole_stack"] = False
        for err in row_fidelity.get("errors") or []:
            result["issues"].append(err)

    ingest_purity = audit_ablation_ingest_purity(manifest, db_path=str(dbp), tickers=anchors)
    result["ingest_purity"] = ingest_purity
    if not ingest_purity.get("ok"):
        result["ready_for_whole_stack"] = False
        for err in ingest_purity.get("errors") or []:
            result["issues"].append(err)

    score_path = audit_ablation_score_path_bias()
    result["score_path_bias"] = score_path
    if not score_path.get("ok"):
        for err in score_path.get("errors") or []:
            result["issues"].append(err)

    result["ready_for_agnostic_ingest"] = bool(
        ingest_purity.get("ok") and row_fidelity.get("ok")
    )
    stack_and_placement = bool(
        result["ready_for_whole_stack"]
        and placement.get("ok")
        and row_fidelity.get("ok")
        and ingest_purity.get("ok")
    )
    result["ready_for_production_path_ablation"] = stack_and_placement
    result["ready_for_unbiased_ablation"] = bool(
        stack_and_placement and score_path.get("ok")
    )
    result["ready"] = bool(result["ready_for_unbiased_ablation"])

    if not result["ready"]:
        result["notes"].append(
            "Ablation ready (green) requires unbiased_ablation: agnostic DB-wire ingest AND "
            "zero documented score-path derailers AND whole-stack probe AND placement validity. "
            "Use ready_for_production_path_ablation when score-path bias is accepted explicitly."
        )
    return result


def build_ablation_survivor_summary(
    scored_cells: list[dict],
    *,
    whole_stack_cells: list[dict] | None = None,
) -> dict:
    """Roll up whole-stack primary-pass scores — one grid, log_loss_delta per (feature × model × horizon)."""
    cells = whole_stack_cells if whole_stack_cells is not None else scored_cells
    by_mh: dict = defaultdict(lambda: defaultdict(list))
    for cell in cells:
        if cell.get("ablation_kind") != "whole_stack_feature_group":
            continue
        if not cell.get("runnable"):
            continue
        model = str(cell.get("model_family") or "")
        if not model:
            continue
        key = (model, str(cell.get("horizon_slug", "")))
        by_mh[key][str(cell.get("group_id", ""))].append(cell)

    by_model_horizon: dict = {}
    flat_groups: list[dict] = []
    for (model, hz) in sorted(by_mh):
        grp_out: list[dict] = []
        for gid in sorted(by_mh[(model, hz)]):
            group_cells = by_mh[(model, hz)][gid]
            ok = [c for c in group_cells if c.get("status") == "ok"]
            skipped = [c for c in group_cells if c.get("status") == "skipped"]
            deltas = [
                float(c["log_loss_delta"])
                for c in ok
                if c.get("log_loss_delta") is not None
            ]
            matters = sum(1 for c in ok if c.get("group_matters"))
            median_delta = round(statistics.median(deltas), 6) if deltas else None
            if not ok and skipped:
                rec = "SKIPPED"
            elif not ok:
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
                "cells_total": len(group_cells),
                "cells_ok": len(ok),
                "cells_skipped": len(skipped),
                "cells_group_matters": matters,
                "median_log_loss_delta": median_delta,
                "max_log_loss_delta": round(max(deltas), 6) if deltas else None,
                "recommendation": rec,
            }
            grp_out.append(row)
            flat_groups.append(row)
        by_model_horizon.setdefault(model, {})[hz] = grp_out

    ok_total = sum(1 for c in cells if c.get("status") == "ok")
    skipped_total = sum(1 for c in cells if c.get("status") == "skipped")
    return {
        "primary_pass_only": True,
        "metric": "multiclass_log_loss_delta",
        "grid_kind": "whole_stack_feature_group",
        "confirm_pass_cli": "whole_stack_drop_column_refit__run_with_--ablation-confirm",
        "scored_cell_count": len(cells),
        "ok_cell_count": ok_total,
        "skipped_cell_count": skipped_total,
        "by_model_horizon": by_model_horizon,
        "groups": flat_groups,
    }


def build_ablation_experiment_integrity(
    report: dict,
    *,
    manifest: dict | None = None,
) -> dict:
    """Skew / no-op / wiring trace for ablation runs — experiment honesty, not catalog math.

    Emitted into ``experiment_integrity`` on every checkpoint and at run end. When deltas look
    wrong, ``skew_flags`` + ``trace_cells`` name the first cells to open and the fix playbook.
    """
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS

    cells = list(report.get("whole_stack_feature_cells") or [])
    accounting = dict(report.get("ablation_accounting") or {})
    run_meta = dict(report.get("run_meta") or {})
    preflight = dict(run_meta.get("preflight") or {})
    generated_at = datetime.now(timezone.utc).isoformat()

    runnable_cells = [c for c in cells if _ablation_cell_is_runnable(c)]
    ok_cells = [c for c in runnable_cells if c.get("status") == "ok"]
    skipped_cells = [c for c in runnable_cells if c.get("status") == "skipped"]
    runnable_target = _resolve_ablation_runnable_target(report, manifest=manifest)
    runnable_terminal = sum(
        1 for c in runnable_cells if c.get("status") in ("ok", "skipped")
    )
    run_status = str(run_meta.get("status") or "unknown")

    skew_flags: list[dict] = []
    trace_cells: list[dict] = []

    def _flag(
        severity: str,
        code: str,
        message: str,
        *,
        evidence: dict | None = None,
        fix_direction: str = "",
    ) -> None:
        skew_flags.append(
            {
                "severity": severity,
                "code": code,
                "message": message,
                "evidence": evidence or {},
                "fix_direction": fix_direction,
            }
        )

    if run_status == "complete" and runnable_target > 0 and runnable_terminal < runnable_target:
        _flag(
            "FAIL",
            "INCOMPLETE_RUN_MARKED_COMPLETE",
            f"run_meta.status=complete but only {runnable_terminal}/{runnable_target} runnable cells terminal",
            evidence={"runnable_terminal": runnable_terminal, "runnable_target": runnable_target},
            fix_direction="Resume with --ablation-resume or fix skip storm before trusting survivor_summary.",
        )

    if not preflight.get("ready_for_whole_stack", True) and ok_cells:
        _flag(
            "FAIL",
            "PREFLIGHT_NOT_READY_BUT_SCORING",
            "Preflight was not ready_for_whole_stack but ok cells exist on disk",
            evidence={"preflight": preflight},
            fix_direction="Run --ablation-preflight; fix bundle/DB/probe failures before interpreting deltas.",
        )

    preplacement_cells = [
        c
        for c in cells
        if c.get("ingest_status") == "in_cone"
        and str(c.get("grid_skip_reason") or "") == "no_model_interface"
    ]
    if preplacement_cells:
        _flag(
            "FAIL",
            "PREPLACEMENT_NO_MODEL_INTERFACE",
            f"{len(preplacement_cells)} in_cone cells use no_model_interface — registry pre-placement banned",
            evidence={"sample": preplacement_cells[:3]},
            fix_direction="in_cone → runnable on all 7 models; remove registry gating in ablation_whole_stack_feature_cell_specs.",
        )

    in_cone_runnable_by_model: dict[str, int] = defaultdict(int)
    for c in runnable_cells:
        if c.get("ingest_status") == "in_cone":
            in_cone_runnable_by_model[str(c.get("model_family") or "")] += 1
    in_cone_counts = list(in_cone_runnable_by_model.values())
    if in_cone_counts and len(set(in_cone_counts)) > 1:
        _flag(
            "FAIL",
            "PREPLACEMENT_UNEQUAL_MODEL_RUNNABLE",
            f"Unequal in_cone runnable counts per model — {dict(in_cone_runnable_by_model)}",
            evidence={"by_model": dict(in_cone_runnable_by_model)},
            fix_direction="Every wired feature × every model × every horizon must be runnable (2632 = 94×7×4).",
        )

    placement_mismatch = [
        c for c in runnable_cells
        if c.get("group_columns")
        and (c.get("stack_entry_layers") or []) != [c.get("model_family")]
    ]
    if placement_mismatch:
        _flag(
            "FAIL",
            "PLACEMENT_LAYER_MISMATCH",
            f"{len(placement_mismatch)} cells have group_columns but stack_entry_layers != [model_family]",
            evidence={"sample": placement_mismatch[0] if placement_mismatch else {}},
            fix_direction="Fix _whole_stack_group_columns_for_family / governed_stack_contract registries.",
        )

    runnable_drift = [
        c for c in cells
        if bool(_ablation_cell_knockout_columns(c)) != bool(c.get("runnable"))
    ]
    if runnable_drift:
        _flag(
            "INVESTIGATE",
            "RUNNABLE_FLAG_DRIFT",
            f"{len(runnable_drift)} cells where runnable flag disagrees with knockout column presence",
            evidence={"count": len(runnable_drift)},
            fix_direction="Align ablation_whole_stack_feature_cell_specs runnable stamp with columns_permuted.",
        )

    noop_scored = [
        c for c in cells
        if c.get("status") == "ok"
        and int(c.get("columns_permuted_count") or 0) == 0
        and _ablation_cell_is_runnable(c)
    ]
    if noop_scored:
        _flag(
            "FAIL",
            "NOOP_KNOCKOUT_SCORED_OK",
            f"{len(noop_scored)} ok cells permuted zero columns — knockout was a no-op",
            evidence={"sample": noop_scored[:3]},
            fix_direction="Trace _ablation_columns_for_atomic_feature + row column presence; fix encoder/offline_v2 cone.",
        )

    zero_delta_with_cols = [
        c for c in ok_cells
        if int(c.get("columns_permuted_count") or 0) > 0
        and abs(float(c.get("log_loss_delta") or 0.0)) <= 1e-6
    ]
    if zero_delta_with_cols:
        rate = len(zero_delta_with_cols) / max(1, len(ok_cells))
        sev = "FAIL" if rate > 0.5 else "INVESTIGATE"
        _flag(
            sev,
            "ZERO_DELTA_WITH_KNOCKOUT",
            f"{len(zero_delta_with_cols)} ok cells ({rate:.0%}) have permuted columns but |delta|<=1e-6",
            evidence={"rate": round(rate, 4), "sample": zero_delta_with_cols[:3]},
            fix_direction="Layer-scoped knockout path or meta v2 retrain; verify production_fusion_prob_for_row ablation_layer.",
        )

    skip_reason_rollup: dict[str, int] = defaultdict(int)
    for c in skipped_cells:
        reason = str(c.get("reason") or c.get("grid_skip_reason") or "unknown")
        skip_reason_rollup[reason] += 1
        for sub, cnt in (c.get("skip_reason_counts") or {}).items():
            skip_reason_rollup[f"row:{sub}"] += int(cnt)

    by_model_horizon: dict[str, dict[str, dict]] = {}
    for model in FULL_STACK_MODEL_LAYERS:
        by_model_horizon[model] = {}
        for hz in REQUIRED_ABLATION_HORIZONS:
            mh_ok = [
                c for c in ok_cells
                if c.get("model_family") == model and c.get("horizon_slug") == hz
            ]
            mh_skip = [
                c for c in skipped_cells
                if c.get("model_family") == model and c.get("horizon_slug") == hz
            ]
            mh_runnable = [
                c for c in runnable_cells
                if c.get("model_family") == model and c.get("horizon_slug") == hz
            ]
            deltas = [
                float(c["log_loss_delta"])
                for c in mh_ok
                if c.get("log_loss_delta") is not None
            ]
            zero_delta = sum(1 for d in deltas if abs(d) <= 1e-6)
            matters = sum(1 for c in mh_ok if c.get("group_matters"))
            noop_ok = sum(1 for c in mh_ok if int(c.get("columns_permuted_count") or 0) == 0)
            skip_rate = len(mh_skip) / max(1, len(mh_runnable))
            zero_rate = zero_delta / max(1, len(mh_ok))
            pos = sum(1 for d in deltas if d > 1e-6)
            neg = sum(1 for d in deltas if d < -1e-6)
            by_model_horizon[model][hz] = {
                "runnable": len(mh_runnable),
                "ok": len(mh_ok),
                "skipped": len(mh_skip),
                "skip_rate": round(skip_rate, 4),
                "zero_delta_ok": zero_delta,
                "zero_delta_rate": round(zero_rate, 4),
                "group_matters_ok": matters,
                "noop_knockout_ok": noop_ok,
                "median_log_loss_delta": round(statistics.median(deltas), 6) if deltas else None,
                "delta_positive": pos,
                "delta_negative": neg,
            }
            if len(mh_ok) >= 10 and zero_rate >= 0.9:
                _flag(
                    "FAIL" if model in ("xgb", "lstm", "transformer") else "INVESTIGATE",
                    f"DELTA_COLLAPSED_{model}_{hz}",
                    f"{model}/{hz}: {zero_rate:.0%} of ok cells have |delta|<=1e-6",
                    evidence=by_model_horizon[model][hz],
                    fix_direction=(
                        "Meta: retrain meta v2 pickles (tabular ingest). "
                        "Bases: verify knockout columns reach model inputs. "
                        "Upper layers: check layer-scoped ablation in stack_bundle_eval_v1."
                    ),
                )
            if skip_rate >= 0.5 and len(mh_runnable) >= 5:
                _flag(
                    "INVESTIGATE",
                    f"SKIP_RATE_HIGH_{model}_{hz}",
                    f"{model}/{hz}: skip_rate={skip_rate:.0%} ({len(mh_skip)}/{len(mh_runnable)})",
                    evidence={"skip_reasons": dict(skip_reason_rollup)},
                    fix_direction="Inspect skip reason rollup; fix bundle/DB/paired_rows baseline prep.",
                )
            if len(deltas) >= 20 and (pos == 0 or neg == 0):
                _flag(
                    "INVESTIGATE",
                    f"SINGLE_SIGN_DELTA_{model}_{hz}",
                    f"{model}/{hz}: all scored deltas are {'positive' if neg == 0 else 'negative'}",
                    evidence={"delta_positive": pos, "delta_negative": neg},
                    fix_direction="Check permute direction, label column, and baseline/permuted row pairing.",
                )

    meta_ok = [c for c in ok_cells if c.get("model_family") == "meta"]
    if meta_ok:
        meta_zero = sum(
            1 for c in meta_ok
            if abs(float(c.get("log_loss_delta") or 0.0)) <= 1e-6
            and int(c.get("columns_permuted_count") or 0) > 0
        )
        if meta_zero / len(meta_ok) >= 0.95:
            _flag(
                "INVESTIGATE",
                "META_LEGACY_NO_EFFECT",
                f"Meta: {meta_zero}/{len(meta_ok)} ok cells have knockout but zero delta — likely 9-dim legacy pickles",
                evidence={"meta_ok": len(meta_ok), "meta_zero_delta": meta_zero},
                fix_direction="Run scheduler meta train (v2 tabular) then re-ablate meta axis.",
            )

    expected_by_model = dict(accounting.get("runnable_by_model") or {})
    for model, expected in expected_by_model.items():
        actual = sum(
            1 for c in runnable_cells if c.get("model_family") == model
        )
        if expected and abs(actual - expected) > 0:
            _flag(
                "INVESTIGATE",
                f"RUNNABLE_COUNT_DRIFT_{model}",
                f"Grid expects {expected} runnable {model} cells but report has {actual}",
                evidence={"expected": expected, "actual": actual},
                fix_direction="Regenerate manifest or resume from stale partial report.",
            )

    def _trace_rank(c: dict) -> tuple:
        noop = int(c.get("columns_permuted_count") or 0) == 0
        zero_d = abs(float(c.get("log_loss_delta") or 0.0)) <= 1e-6
        return (0 if noop else 1, 0 if zero_d else 1, -abs(float(c.get("log_loss_delta") or 0.0)))

    trace_pool = noop_scored + zero_delta_with_cols + skipped_cells[:50]
    seen_keys: set[tuple] = set()
    for c in sorted(trace_pool, key=_trace_rank):
        key = (
            str(c.get("model_family")),
            str(c.get("horizon_slug")),
            str(c.get("group_id")),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        trace_cells.append(
            {
                "model_family": c.get("model_family"),
                "horizon_slug": c.get("horizon_slug"),
                "group_id": c.get("group_id"),
                "status": c.get("status"),
                "reason": c.get("reason"),
                "log_loss_delta": c.get("log_loss_delta"),
                "columns_requested": c.get("columns_requested"),
                "columns_permuted": c.get("columns_permuted"),
                "columns_permuted_count": c.get("columns_permuted_count"),
                "paired_rows": c.get("paired_rows"),
                "skip_reason_counts": c.get("skip_reason_counts"),
                "stack_entry_layers": c.get("stack_entry_layers"),
            }
        )
        if len(trace_cells) >= 40:
            break

    fail_n = sum(1 for f in skew_flags if f["severity"] == "FAIL")
    inv_n = sum(1 for f in skew_flags if f["severity"] == "INVESTIGATE")
    if fail_n:
        verdict = "FAIL"
        verdict_reason = f"{fail_n} FAIL flag(s) — do not trust survivor_summary for placement"
    elif inv_n:
        verdict = "INVESTIGATE"
        verdict_reason = f"{inv_n} INVESTIGATE flag(s) — review trace_cells before retrain"
    elif runnable_target > 0 and runnable_terminal < runnable_target:
        verdict = "INVESTIGATE"
        verdict_reason = f"Run partial ({runnable_terminal}/{runnable_target} runnable cells terminal)"
    elif runnable_target <= 0 and not cells:
        verdict = "MISSING"
        verdict_reason = "No scored cells and no runnable_target on report — run has not started or report is stale"
    elif runnable_target <= 0:
        verdict = "INVESTIGATE"
        verdict_reason = "Report lacks ablation_accounting.runnable_target — rebuild integrity after grid attach"
    else:
        verdict = "PASS"
        verdict_reason = "No skew flags; ok to proceed toward confirm/retrain gates"

    fix_playbook = {
        "NOOP_KNOCKOUT_SCORED_OK": "tools/feature_curation_gate.py::_ablation_columns_for_atomic_feature + row enrichment",
        "ZERO_DELTA_WITH_KNOCKOUT": "arch_competition/stack_bundle_eval_v1.py::_production_fusion_prob_for_row layer-scoped knockout",
        "META_LEGACY_NO_EFFECT": "train_all.run_meta / ml_scheduler meta v2 retrain then re-ablate",
        "SCHWAB_CELLS_SCORED": "manifest ingest_status + grid_skip_reason not_wired",
        "SKIP_RATE_HIGH": "run_ablation_preflight + prepare_whole_stack_pooled_baseline_cache",
        "PLACEMENT_LAYER_MISMATCH": "governed_stack_contract stack_layer_ablation_snapshot_columns",
    }

    return {
        "schema_version": "1",
        "generated_at": generated_at,
        "artifact_paths": {
            "manifest": str(report.get("source_manifest") or MANIFEST_PATH),
            "report": str(ABLATION_REPORT_PATH),
        },
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "run_completion": {
            "run_status": run_status,
            "runnable_target": runnable_target,
            "runnable_terminal": runnable_terminal,
            "runnable_ok": len(ok_cells),
            "runnable_skipped": len(skipped_cells),
            "completion_pct": round(100.0 * runnable_terminal / runnable_target, 2)
            if runnable_target
            else None,
        },
        "placement_health": {
            "accounting": accounting,
            "expected_runnable_by_model": expected_by_model,
        },
        "by_model_horizon": by_model_horizon,
        "skip_reason_rollup": dict(sorted(skip_reason_rollup.items(), key=lambda kv: -kv[1])),
        "skew_flags": skew_flags,
        "trace_cells": trace_cells,
        "fix_playbook": fix_playbook,
    }


def _attach_experiment_integrity(report: dict, *, manifest: dict | None = None) -> dict:
    report["experiment_integrity"] = build_ablation_experiment_integrity(report, manifest=manifest)
    return report["experiment_integrity"]


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


def _stack_eval_comparison_pairs(stack_eval: dict) -> list[tuple[str, str, dict]]:
    """(comparison_id, (baseline_mode, treatment_mode), spec) for stack authority."""
    out: list[tuple[str, str, dict]] = []
    for section_key in ("base_model_comparisons", "layer_comparisons"):
        for cmp_id, spec in (stack_eval.get(section_key) or {}).items():
            base = spec.get("baseline")
            treat = spec.get("treatment")
            if base and treat:
                out.append((f"{section_key}:{cmp_id}", (str(base), str(treat)), spec))
    return out


def run_stack_layer_ablation_cell(
    *,
    ticker: str,
    horizon_slug: str,
    db_path: str,
    stack_eval: dict,
) -> dict:
    """One anchor×horizon cell: stack-component authority (base + upper layers).

    Scores each manifest comparison on its own (baseline, treatment) mode pair so MC/fusion
    failures do not zero out meta/base lifts (all-9-mode intersection was the noop bug).
    """
    from arch_competition.stack_bundle_eval_v1 import _authority_block, run_stack_bundle_evaluation

    model_dir = _resolve_model_dir_for_stack_eval(ticker, horizon_slug)
    if model_dir is None:
        return {
            "anchor_ticker": ticker,
            "horizon_slug": horizon_slug,
            "status": "skipped",
            "reason": "incomplete_active_bundle",
        }
    comparisons = _stack_eval_comparison_pairs(stack_eval)
    if not comparisons:
        return {
            "anchor_ticker": ticker,
            "horizon_slug": horizon_slug,
            "status": "skipped",
            "reason": "stack_eval_comparisons_empty",
        }

    merged_metrics: dict = {}
    merged_skip: dict[str, int] = {}
    min_paired: int | None = None
    comparison_runs: list[dict] = []
    eval_opts = _ablation_eval_options()

    _prev_strict = os.environ.get("ED_XGB_STRICT_ACTIVE_ONLY")
    _prev_scored = os.environ.get("ED_ABLATION_SCORING_PASS")
    os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = "0"
    os.environ["ED_ABLATION_SCORING_PASS"] = "1"
    try:
        for cmp_id, mode_pair, _spec in comparisons:
            manifest = run_stack_bundle_evaluation(
                db_path=db_path,
                ticker=ticker,
                model_dir=model_dir,
                ml_horizon_slug=horizon_slug,
                options=eval_opts,
                modes=mode_pair,
            )
            pr = int(manifest.get("paired_rows_all_modes") or 0)
            min_paired = pr if min_paired is None else min(min_paired, pr)
            for mode, metric in (manifest.get("metrics_by_config") or {}).items():
                merged_metrics[mode] = metric
            for key, count in (manifest.get("skip_reason_counts") or {}).items():
                merged_skip[key] = merged_skip.get(key, 0) + int(count)
            comparison_runs.append(
                {
                    "comparison_id": cmp_id,
                    "modes": list(mode_pair),
                    "paired_rows": pr,
                    "skip_reason_counts": manifest.get("skip_reason_counts") or {},
                }
            )
    finally:
        if _prev_strict is None:
            os.environ.pop("ED_XGB_STRICT_ACTIVE_ONLY", None)
        else:
            os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = _prev_strict
        if _prev_scored is None:
            os.environ.pop("ED_ABLATION_SCORING_PASS", None)
        else:
            os.environ["ED_ABLATION_SCORING_PASS"] = _prev_scored

    metrics = merged_metrics
    lifts = _stack_layer_lifts(metrics, stack_eval.get("layer_comparisons") or {})
    base_model_lifts = _stack_layer_lifts(metrics, stack_eval.get("base_model_comparisons") or {})

    # Fail closed on degenerate meta: with meta_<T>_<hz>.pkl absent, stack_bundle_eval's meta_stack
    # mode falls back to the SAME weighted average as xgb_plus_lstm_plus_transformer, so the meta
    # lift is identically ~0 — that is "no meta artifact", NOT "meta does not help". Flag it instead
    # of emitting a misleading zero (the 'reads as zero' failure mode at the stack layer).
    from ml_horizon import normalize_ml_horizon_slug as _norm_hz

    _t = ticker_storage_key(ticker)  # RC-345/F25: meta_present identity canonical
    _hz = _norm_hz(horizon_slug)
    meta_present = (model_dir / f"meta_{_t}_{_hz}.pkl").is_file()
    if "meta" in lifts and not meta_present:
        lifts["meta"]["degenerate"] = True
        lifts["meta"]["degenerate_reason"] = (
            "meta_artifact_missing__meta_stack_falls_back_to_weighted_average"
        )
        lifts["meta"]["treatment_helps"] = None

    auth = _authority_block(
        metrics,
        min_rows=eval_opts.min_paired_rows,
        min_delta_log_loss=eval_opts.min_delta_log_loss,
    )
    paired = int(min_paired or 0)
    lifts_ok = _stack_lift_sections_scored(lifts, base_model_lifts)
    cell_status = "ok" if lifts_ok else "failed"
    return {
        "anchor_ticker": ticker,
        "horizon_slug": horizon_slug,
        "status": cell_status,
        "model_dir": str(model_dir),
        "paired_rows": paired,
        "comparison_runs": comparison_runs,
        "skip_reason_counts": merged_skip or None,
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
        "ablation_kind": "stack_authority",
    }


def _stack_lift_sections_scored(lifts: dict, base_lifts: dict) -> bool:
    """True when every non-degenerate lift has baseline + treatment log_loss."""
    for section in (lifts, base_lifts):
        for _lid, lift in (section or {}).items():
            if lift.get("degenerate"):
                continue
            if lift.get("baseline_log_loss") is None or lift.get("treatment_log_loss") is None:
                return False
    return bool(lifts or base_lifts)


def stack_authority_cells_complete(cells: list[dict]) -> tuple[bool, list[str]]:
    """True when every stack-authority cell has scored lifts (meta/MC/fusion + base)."""
    issues: list[str] = []
    for cell in cells:
        anchor = cell.get("anchor_ticker")
        hz = cell.get("horizon_slug")
        if cell.get("status") != "ok":
            issues.append(f"{anchor}/{hz}: status={cell.get('status')}")
            continue
        if not _stack_lift_sections_scored(
            cell.get("layer_lifts") or {}, cell.get("base_model_lifts") or {}
        ):
            issues.append(f"{anchor}/{hz}: incomplete lifts (null log_loss)")
    return (not issues, issues)


def build_stack_authority_rescore_report(
    *,
    manifest_path: Path | None = None,
    report_path: Path | None = None,
    db_path: str | None = None,
    tickers: list[str] | None = None,
    horizons: list[str] | None = None,
) -> dict:
    """Re-score stack authority (meta/MC/fusion) — use after retrain; prefers parallel bundles."""
    manifest = load_ablation_manifest(manifest_path)
    out_path = report_path or ABLATION_REPORT_PATH
    report: dict = {}
    if out_path.is_file():
        report = json.loads(out_path.read_text(encoding="utf-8"))
    db = db_path or str(DB_PATH)
    os.environ.setdefault("ED_STACK_EVAL_BUNDLE", "parallel")
    cells: list[dict] = []
    section = build_stack_authority_ablation_section(
        manifest,
        db_path=db,
        dry_run=False,
        tickers=tickers,
        horizons=horizons,
        resume_cells={},
        cells_out=cells,
    )
    report["stack_authority_cells"] = cells
    report["stack_layer_cells"] = cells
    report.update(section)
    report.setdefault("run_meta", {})["stack_authority_rescore_at"] = datetime.now(
        timezone.utc
    ).isoformat()
    write_ablation_report(report, out_path)
    ready, issues = stack_authority_cells_complete(cells)
    return {"ready": ready, "issues": issues, "cells": len(cells), "report_path": str(out_path)}


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


def _per_model_cell_key(anchor: str, model: str, horizon: str, group_id: str) -> str:
    return f"{ticker_storage_key(anchor)}|{model}|{horizon}|{group_id}"  # RC-345/F25: canonical identity in the key-builder itself


def _index_per_model_cells(cells: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in cells:
        if c.get("ablation_kind") != "per_model_feature_group":
            continue
        if not c.get("group_id") or not c.get("model_family"):
            continue
        out[_per_model_cell_key(c["anchor_ticker"], c["model_family"], c["horizon_slug"], c["group_id"])] = c
    return out


def build_whole_stack_feature_ablation_section(
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
    """Stage 3: permute captured-cone feature at every stack entry; score via 7-layer fusion (pooled tickers)."""
    from arch_competition.stack_bundle_eval_v1 import (
        prepare_whole_stack_pooled_baseline_cache,
        run_whole_stack_feature_group_ablation,
    )

    pool_tickers = _ablation_pool_tickers(manifest, tickers)
    enriched_sample = build_ablation_enriched_row_sample(
        db_path=db_path, manifest=manifest, tickers=pool_tickers
    )
    specs = ablation_whole_stack_feature_cell_specs(
        manifest, tickers=tickers, enriched_rows=enriched_sample or None
    )
    accounting = ablation_cell_accounting(manifest, specs, enriched_rows=enriched_sample or None)
    _groups_by_id = {g["group_id"]: g for g in ablation_grid_groups(manifest)}
    horizon_filter = set(horizons) if horizons else None
    resume_cells = resume_cells or {}
    scored_cells = cells_out if cells_out is not None else []
    section: dict = {
        "ablation_accounting": accounting,
        "whole_stack_catalog_cell_target": accounting["catalog_target"],
        "whole_stack_runnable_cell_target": accounting["runnable_target"],
        "whole_stack_feature_cell_target": accounting["runnable_target"],
        "whole_stack_feature_cell_count": len(specs),
        "whole_stack_feature_cells": scored_cells,
        "stage3_pool_tickers": pool_tickers,
    }
    if dry_run:
        section["dry_run"] = True
        section["whole_stack_feature_cells"] = specs
        return section

    specs_to_run = [
        s for s in specs
        if not horizon_filter or s["horizon_slug"] in horizon_filter
    ]
    runnable_specs = [s for s in specs_to_run if s.get("group_columns")]
    runnable_total = len(runnable_specs)
    runnable_done = 0
    baseline_cache: dict = {}
    eval_opts = _ablation_eval_options()

    for spec in specs_to_run:
        is_runnable = bool(spec.get("group_columns"))
        _ck = _whole_stack_cell_key(
            spec["horizon_slug"], spec["group_id"], model_family=spec["model_family"]
        )
        resumed = _whole_stack_resume_cell(
            resume_cells,
            spec["horizon_slug"],
            spec["group_id"],
            model_family=spec["model_family"],
        )
        if resumed is not None:
            cell = _finalize_whole_stack_scored_cell(resumed)
            cell.setdefault("runnable", is_runnable)
        else:
            cached = baseline_cache.get(spec["horizon_slug"])
            if cached is None:
                model_dir_by_ticker: dict[str, Path] = {}
                missing: list[str] = []
                for t in pool_tickers:
                    bundle = _resolve_model_dir_for_stack_eval(t, spec["horizon_slug"])
                    if bundle is None:
                        missing.append(t)
                    else:
                        model_dir_by_ticker[ticker_storage_key(t)] = bundle  # RC-345/F25: canonical key
                if missing:
                    cached = {
                        "status": "skipped",
                        "hz": spec["horizon_slug"],
                        "reason": f"incomplete_active_bundle:{','.join(missing)}",
                    }
                else:
                    prep = prepare_whole_stack_pooled_baseline_cache(
                        db_path=db_path,
                        tickers=pool_tickers,
                        ml_horizon_slug=spec["horizon_slug"],
                        model_dir_by_ticker=model_dir_by_ticker,
                        options=eval_opts,
                    )
                    if prep.get("status") == "ok" and prep.get("rows"):
                        prep = dict(prep)
                        prep["rows"] = _enrich_rows_for_whole_stack_ablation(
                            prep["rows"], db_path=db_path
                        )
                    cached = prep
                baseline_cache[spec["horizon_slug"]] = cached
            group_columns = list(spec.get("group_columns") or [])
            entry_layers = list(spec.get("stack_entry_layers") or [])
            model_family = spec["model_family"]
            if cached.get("status") != "ok":
                cell = {
                    "model_family": spec["model_family"],
                    "horizon_slug": cached.get("hz", spec["horizon_slug"]),
                    "group_id": spec["group_id"],
                    "status": "skipped",
                    "reason": cached.get("reason", "baseline_prep_failed"),
                    "runnable": is_runnable,
                    "ablation_kind": "whole_stack_feature_group",
                    "stack_entry_layers": entry_layers,
                    "pool_tickers": pool_tickers,
                }
            elif not group_columns:
                skip_reason = spec.get("grid_skip_reason") or "no_columns_for_stack_entry"
                cell = {
                    "model_family": spec["model_family"],
                    "horizon_slug": spec["horizon_slug"],
                    "group_id": spec["group_id"],
                    "status": "skipped",
                    "reason": skip_reason,
                    "grid_skip_reason": skip_reason,
                    "runnable": False,
                    "ablation_kind": "whole_stack_feature_group",
                    "stack_entry_layers": entry_layers,
                    "pool_tickers": pool_tickers,
                }
            else:
                cell = run_whole_stack_feature_group_ablation(
                    db_path=db_path,
                    ticker=pool_tickers[0],
                    model_dir=Path("."),
                    ml_horizon_slug=spec["horizon_slug"],
                    group_id=spec["group_id"],
                    group_columns=group_columns,
                    baseline_cache=cached,
                    options=eval_opts,
                    model_family=model_family,
                )
                cell = _finalize_whole_stack_scored_cell(cell)
                cell["model_family"] = spec["model_family"]
                cell["stack_entry_layers"] = entry_layers
                cell["ablation_kind"] = "whole_stack_feature_group"
                cell["runnable"] = True
        scored_cells.append(cell)
        if is_runnable:
            runnable_done += 1
            if on_cell_done is not None:
                on_cell_done("whole_stack_feature", cell, runnable_done, runnable_total)
    return section


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
    """O-56 primary: per (anchor, model, horizon) train ML stack layer on chronological holdout, then
    grouped-permute each ABLATE group and record THAT model's MCC delta. One trained model is cached
    and reused across all groups for an (anchor, model, horizon)."""
    specs = ablation_per_model_feature_cell_specs(manifest)
    groups_by_id = {g["group_id"]: g for g in ablation_groups(manifest)}
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
            else:
                grp = groups_by_id.get(spec["group_id"]) or {}
                pm = _per_model_permute_members(grp, model)
                if model == "xgb":
                    cell = _permute_eval_xgb_group(
                        prepared,
                        ticker=spec["anchor_ticker"],
                        group_id=spec["group_id"],
                        xgb_members=pm["xgb_members"],
                    )
                elif model == "lstm":
                    cell = _permute_eval_lstm_group(
                        prepared,
                        ticker=spec["anchor_ticker"],
                        group_id=spec["group_id"],
                        lstm_5m_members=pm["lstm_5m_members"],
                        lstm_1m_members=pm["lstm_1m_members"],
                    )
                else:
                    cell = _permute_eval_transformer_group(
                        prepared,
                        ticker=spec["anchor_ticker"],
                        group_id=spec["group_id"],
                        lstm_5m_members=pm["lstm_5m_members"],
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


def _drop_members_for_model(
    manifest: dict, drop_group_ids: list[str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Resolve DROP group_ids from atomic_column + live ingest cone (not manifest model stamps)."""
    import lstm_data as l
    from tools.build_feature_assignment_matrix_v2 import _registered_ml_columns

    by_id = {g["group_id"]: g for g in manifest.get("groups", [])}
    reg = _registered_ml_columns()
    cf = set(l.CONFLUENCE_FEATURES)
    xgb, m5, m1, conf = [], [], [], []
    for gid in drop_group_ids:
        grp = by_id.get(gid) or {}
        col = _atomic_column_for_group(grp)
        if not col:
            continue
        xgb += _ablation_columns_for_atomic_feature(col, "xgb")
        if col in cf:
            if col in reg.get("lstm_5m", set()) | reg.get("lstm_1m", set()):
                conf.append(col)
        else:
            if col in reg.get("lstm_5m", set()):
                m5.append(col)
            if col in reg.get("lstm_1m", set()):
                m1.append(col)
    return sorted(set(xgb)), sorted(set(m5)), sorted(set(m1)), sorted(set(conf))


def _confirm_cell_key(anchor: str, model: str, horizon: str) -> str:
    return f"{ticker_storage_key(anchor)}|{model}|{horizon}"  # RC-345/F25: canonical identity in the key-builder itself


def _holdout_early_stop_patience(*, model: str) -> int:
    """Match production early-stop patience for ablation holdout refits."""
    for env_key in (
        f"ED_TRAIN_EARLY_STOP_PATIENCE_{model.upper()}",
        "ED_TRAIN_EARLY_STOP_PATIENCE",
    ):
        raw = (os.environ.get(env_key) or "").strip()
        if raw.isdigit():
            return max(1, int(raw))
    return 8


def build_per_model_confirm_pass_section(
    manifest: dict,
    *,
    db_path: str,
    drops_by_mh: dict,
    full_baseline: dict,
    tickers: list[str] | None = None,
    on_cell_done=None,
    cells_out: list[dict] | None = None,
    resume_cells: dict[str, dict] | None = None,
) -> dict:
    """O-56 confirm pass: per (anchor, model, horizon) with DROP_CANDIDATE groups, REFIT the model
    on survivors-only (XGB: columns removed; sequence: channels nulled) and check the held-out MCC
    is not worse than the full-feature baseline (from the primary report). safe_to_drop if so."""
    TOL = 0.005
    from arch_competition.stack_bundle_eval_v1 import ABLATION_CONFIRM_PATH_VERSION

    anchors = [ticker_storage_key(t) for t in (tickers or manifest["ablation_method"]["anchors"]) if str(t).strip()]  # RC-345/F25: anchor identity canonical, not local .upper()
    cells = cells_out if cells_out is not None else []
    resume_cells = resume_cells or {}
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
        ck = _confirm_cell_key(anc, model, hz)
        if ck in resume_cells:
            cell = resume_cells[ck]
            cells.append(cell)
            done += 1
            if on_cell_done is not None:
                on_cell_done("per_model_confirm", cell, done, total)
            continue
        xcols, m5, m1, conf = _drop_members_for_model(manifest, drop_ids)
        if model == "xgb":
            prep = _prep[model](
                ticker=anc,
                horizon_slug=hz,
                db_path=db_path,
                drop_columns=xcols,
                drop_group_ids=drop_ids,
                ablation_manifest=manifest,
            )
        elif model == "lstm":
            prep = _prep[model](
                ticker=anc,
                horizon_slug=hz,
                db_path=db_path,
                drop_5m=m5,
                drop_1m=m1,
                drop_conf=conf,
                drop_group_ids=drop_ids,
                ablation_manifest=manifest,
            )
        else:
            prep = _prep[model](
                ticker=anc,
                horizon_slug=hz,
                db_path=db_path,
                drop_5m=m5,
                drop_group_ids=drop_ids,
                ablation_manifest=manifest,
            )
        base = full_baseline.get((anc, model, hz))
        if prep.get("status") != "ok":
            cell = {
                "anchor_ticker": anc, "model_family": model, "horizon_slug": hz,
                "status": "skipped", "reason": prep.get("reason", "prep_failed"),
                "ablation_kind": "per_model_confirm_drop", "dropped_groups": drop_ids,
                "confirm_path_version": ABLATION_CONFIRM_PATH_VERSION,
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
                "confirm_path_version": ABLATION_CONFIRM_PATH_VERSION,
            }
        cells.append(cell)
        done += 1
        if on_cell_done is not None:
            on_cell_done("per_model_confirm", cell, done, total)
    return {"confirm_drop_cell_count": len(specs), "confirm_drop_cells": cells}


def _whole_stack_confirm_cell_key(anchor: str, horizon: str, group_id: str) -> str:
    return f"{ticker_storage_key(anchor)}|{horizon}|{group_id}"  # RC-345/F25: canonical identity in the key-builder itself


def build_whole_stack_confirm_pass_section(
    manifest: dict,
    *,
    db_path: str,
    drops_by_mh: dict,
    tickers: list[str] | None = None,
    on_cell_done=None,
    cells_out: list[dict] | None = None,
    resume_cells: dict[str, dict] | None = None,
) -> dict:
    """Fusion-path confirm: null one DROP_CANDIDATE group at every stack entry; safe_to_drop if log_loss unchanged."""
    from arch_competition.stack_bundle_eval_v1 import (
        ABLATION_CONFIRM_PATH_VERSION,
        prepare_whole_stack_baseline_cache,
        run_whole_stack_feature_group_confirm_drop,
    )

    groups_by_id = {g["group_id"]: g for g in manifest.get("groups", [])}
    anchors = [ticker_storage_key(t) for t in (tickers or manifest["ablation_method"]["anchors"]) if str(t).strip()]  # RC-345/F25: anchor identity canonical, not local .upper()
    cells = cells_out if cells_out is not None else []
    resume_cells = resume_cells or {}
    eval_opts = _ablation_eval_options()
    specs: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for (model, hz), drop_ids in drops_by_mh.items():
        for anc in anchors:
            for gid in drop_ids:
                dedupe = (anc, model, hz, gid)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                specs.append(
                    {
                        "anchor_ticker": anc,
                        "model_family": model,
                        "horizon_slug": hz,
                        "group_id": gid,
                    }
                )
    baseline_cache: dict = {}
    done = 0
    total = len(specs)
    for spec in specs:
        anc = spec["anchor_ticker"]
        hz = spec["horizon_slug"]
        gid = spec["group_id"]
        ck = _whole_stack_confirm_cell_key(anc, hz, gid)
        legacy_resume = resume_cells.get(ck)
        if legacy_resume is None:
            for key, cell in resume_cells.items():
                if key.endswith(f"|{gid}") and f"|{hz}|" in key and key.startswith(f"{anc}|"):
                    legacy_resume = cell
                    break
        if legacy_resume is not None:
            cell = legacy_resume
        else:
            pk = (anc, hz)
            cached = baseline_cache.get(pk)
            if cached is None:
                model_dir = _resolve_model_dir_for_stack_eval(anc, hz)
                if model_dir is None:
                    cached = {
                        "status": "skipped",
                        "hz": hz,
                        "reason": "incomplete_active_bundle",
                    }
                else:
                    prep = prepare_whole_stack_baseline_cache(
                        db_path=db_path,
                        ticker=anc,
                        model_dir=model_dir,
                        ml_horizon_slug=hz,
                        options=eval_opts,
                    )
                    if prep.get("status") == "ok" and prep.get("rows"):
                        prep = dict(prep)
                        prep["rows"] = _enrich_rows_for_whole_stack_ablation(
                            prep["rows"], db_path=db_path
                        )
                    prep["model_dir"] = model_dir
                    cached = prep
                baseline_cache[pk] = cached
            grp = groups_by_id.get(gid) or {"members": {}}
            model_family = str(spec.get("model_family") or "")
            group_columns = _whole_stack_group_columns_for_family(grp, model_family)
            entry_layers = [model_family] if group_columns else []
            if cached.get("status") != "ok":
                cell = {
                    "anchor_ticker": anc,
                    "horizon_slug": cached.get("hz", hz),
                    "group_id": gid,
                    "status": "skipped",
                    "reason": cached.get("reason", "baseline_prep_failed"),
                    "ablation_kind": "whole_stack_confirm_drop",
                    "stack_entry_layers": entry_layers,
                    "confirm_path_version": ABLATION_CONFIRM_PATH_VERSION,
                }
            elif not group_columns:
                cell = {
                    "anchor_ticker": anc,
                    "horizon_slug": hz,
                    "group_id": gid,
                    "status": "skipped",
                    "reason": "no_columns_for_stack_entry",
                    "ablation_kind": "whole_stack_confirm_drop",
                    "stack_entry_layers": entry_layers,
                    "confirm_path_version": ABLATION_CONFIRM_PATH_VERSION,
                }
            else:
                cell = run_whole_stack_feature_group_confirm_drop(
                    db_path=db_path,
                    ticker=anc,
                    model_dir=cached["model_dir"],
                    ml_horizon_slug=hz,
                    group_id=gid,
                    group_columns=group_columns,
                    baseline_cache=cached,
                    options=eval_opts,
                )
                cell["model_family"] = spec["model_family"]
                cell["stack_entry_layers"] = entry_layers
                cell["ablation_kind"] = "whole_stack_confirm_drop"
                cell["confirm_path_version"] = ABLATION_CONFIRM_PATH_VERSION
        cells.append(cell)
        done += 1
        if on_cell_done is not None:
            on_cell_done("whole_stack_confirm", cell, done, total)
    return {
        "whole_stack_confirm_drop_cell_count": len(specs),
        "whole_stack_confirm_drop_cells": cells,
    }


def _confirm_resume_cells_from_report(report: dict) -> dict[str, dict]:
    """Resume only confirm cells stamped with the current confirm path version."""
    from arch_competition.stack_bundle_eval_v1 import ABLATION_CONFIRM_PATH_VERSION

    resume_cells: dict[str, dict] = {}
    seen: set[str] = set()
    for source in (
        report.get("confirm_drop_cells") or [],
        (
            (report.get("survivor_summary") or {}).get("confirm_pass")
            if isinstance((report.get("survivor_summary") or {}).get("confirm_pass"), dict)
            else {}
        ).get("cells")
        or [],
    ):
        for cell in source:
            if cell.get("status") != "ok":
                continue
            if cell.get("confirm_path_version") != ABLATION_CONFIRM_PATH_VERSION:
                continue
            ck = _confirm_cell_key(
                str(cell.get("anchor_ticker") or ""),
                str(cell.get("model_family") or ""),
                str(cell.get("horizon_slug") or ""),
            )
            if ck in seen:
                continue
            seen.add(ck)
            resume_cells[ck] = cell
    return resume_cells


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
        report.get("whole_stack_feature_cells") or []
    )
    drops_by_mh = ablation_confirm_drops_by_model_horizon(survivor)
    db = db_path or str(DB_PATH)

    acquire_ablation_run_lock(run_kind="confirm")
    try:
        _prev_strict = os.environ.get("ED_XGB_STRICT_ACTIVE_ONLY")
        _prev_ablation_eval = os.environ.get("ED_ABLATION_SCORING_PASS")
        _prev_inline_skip = os.environ.get("ED_TRAINING_SKIP_INLINE_NORMSYNC")
        os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = "0"
        os.environ["ED_ABLATION_SCORING_PASS"] = "1"
        from normalized_training_sync import ensure_normalized_training_table

        ensure_normalized_training_table(db, force=False)
        os.environ["ED_TRAINING_SKIP_INLINE_NORMSYNC"] = "1"
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
                if section_kind == "per_model_confirm":
                    from arch_competition.stack_bundle_eval_v1 import ABLATION_CONFIRM_PATH_VERSION

                    anchors_req = list(manifest["ablation_method"]["anchors"])
                    surv = report.get("survivor_summary") or survivor
                    confirm_cells = list(report.get("confirm_drop_cells") or [])
                    path_version = (
                        ABLATION_CONFIRM_PATH_VERSION if n >= total and total > 0 else None
                    )
                    surv["confirm_pass"] = {
                        "cells": confirm_cells,
                        "anchors_required": len(anchors_req),
                        "confirm_path_version": path_version,
                        "completed_at": (
                            datetime.now(timezone.utc).isoformat()
                            if path_version == ABLATION_CONFIRM_PATH_VERSION
                            else surv.get("confirm_pass", {}).get("completed_at")
                        ),
                    }
                    surv["primary_pass_only"] = False
                    report["survivor_summary"] = surv
                _write_ablation_checkpoint(out_path, report)
                print(
                    f"confirm [{section_kind}] {n}/{total} "
                    f"{cell.get('anchor_ticker')}/{cell.get('model_family')}/{cell.get('horizon_slug')} "
                    f"status={cell.get('status')} safe={cell.get('safe_to_drop')} dmcc={cell.get('mcc_change')}",
                    flush=True,
                )

            resume_cells = _confirm_resume_cells_from_report(report) if resume else {}
            report["whole_stack_confirm_drop_cells"] = []
            if not resume:
                surv = report.get("survivor_summary") or survivor
                surv.pop("confirm_pass", None)
                report["survivor_summary"] = surv
            ws_confirm_section = build_whole_stack_confirm_pass_section(
                manifest,
                db_path=db,
                drops_by_mh=drops_by_mh,
                tickers=tickers,
                on_cell_done=_checkpoint,
                cells_out=report["whole_stack_confirm_drop_cells"],
                resume_cells=resume_cells,
            )
            report.update(ws_confirm_section)
            report["confirm_drop_cells"] = report["whole_stack_confirm_drop_cells"]
            report["confirm_drop_summary"] = {
                "drops_by_model_horizon": {f"{mh[0]}/{mh[1]}": ids for mh, ids in drops_by_mh.items()},
                "cells_total": len(report.get("whole_stack_confirm_drop_cells") or []),
                "cells_ok": sum(
                    1 for c in report.get("whole_stack_confirm_drop_cells") or [] if c.get("status") == "ok"
                ),
                "cells_safe_to_drop": sum(
                    1
                    for c in report.get("whole_stack_confirm_drop_cells") or []
                    if c.get("status") == "ok" and c.get("safe_to_drop")
                ),
            }
            report.setdefault("run_meta", {})["confirm_pass_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            confirm_cells = report.get("whole_stack_confirm_drop_cells") or []
            anchors = list(manifest["ablation_method"]["anchors"])
            surv = report.get("survivor_summary") or survivor
            from arch_competition.stack_bundle_eval_v1 import ABLATION_CONFIRM_PATH_VERSION

            expected = int(ws_confirm_section.get("whole_stack_confirm_drop_cell_count") or 0)
            all_v2 = all(
                c.get("confirm_path_version") == ABLATION_CONFIRM_PATH_VERSION
                for c in confirm_cells
            )
            confirm_complete = (
                expected > 0
                and len(confirm_cells) >= expected
                and all_v2
            )
            surv["confirm_pass"] = {
                "cells": confirm_cells,
                "anchors_required": len(anchors),
                "completed_at": (
                    report["run_meta"]["confirm_pass_at"] if confirm_complete else None
                ),
                "confirm_path_version": (
                    ABLATION_CONFIRM_PATH_VERSION if confirm_complete else None
                ),
            }
            surv["primary_pass_only"] = False
            report["survivor_summary"] = surv
        finally:
            if _prev_strict is None:
                os.environ.pop("ED_XGB_STRICT_ACTIVE_ONLY", None)
            else:
                os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = _prev_strict
            if _prev_ablation_eval is None:
                os.environ.pop("ED_ABLATION_SCORING_PASS", None)
            else:
                os.environ["ED_ABLATION_SCORING_PASS"] = _prev_ablation_eval
            if _prev_inline_skip is None:
                os.environ.pop("ED_TRAINING_SKIP_INLINE_NORMSYNC", None)
            else:
                os.environ["ED_TRAINING_SKIP_INLINE_NORMSYNC"] = _prev_inline_skip
        return report
    finally:
        release_ablation_run_lock()


def stamp_primary_ablation_authority(
    report_path: Path | None = None,
    *,
    force: bool = False,
) -> dict:
    """Derive confirm_drop_summary from completed primary pass — no confirm rescoring.

    Operator binding when confirm pass cannot be rerun: production uses primary-pass
    DROP_CANDIDATE on trusted (model, horizon) cells only.
    """
    from arch_competition.stack_bundle_eval_v1 import (
        ablation_confirm_pass_complete,
        ablation_full_matrix_cell_target,
        ablation_primary_pass_authority_active,
        primary_drop_group_ids_by_model_horizon,
        primary_scoring_cell_untrusted,
    )

    out_path = report_path or ABLATION_REPORT_PATH
    if not out_path.is_file():
        raise FileNotFoundError(f"primary ablation report missing: {out_path}")
    report = json.loads(out_path.read_text(encoding="utf-8"))
    if ablation_confirm_pass_complete(report.get("survivor_summary") or {}):
        raise RuntimeError(
            "confirm pass already complete — primary authority stamp refused (confirm is authoritative)"
        )
    ss = report.get("survivor_summary") or build_ablation_survivor_summary(
        report.get("whole_stack_feature_cells") or []
    )
    scored = int(ss.get("scored_cell_count") or 0)
    matrix_target = ablation_full_matrix_cell_target()
    if matrix_target <= 0 or scored < matrix_target:
        raise RuntimeError(
            f"primary matrix incomplete ({scored}/{matrix_target} scored); cannot stamp authority"
        )
    if (report.get("run_meta") or {}).get("status") != "complete":
        raise RuntimeError("primary ablation run_meta.status is not complete")
    existing = report.get("confirm_drop_summary") or {}
    if existing.get("primary_authority") and not force:
        return report

    drops_by_mh = {
        f"{m}/{h}": sorted(ids)
        for (m, h), ids in primary_drop_group_ids_by_model_horizon(ss).items()
    }
    untrusted = sorted(
        f"{m}/{h}"
        for m in ("xgb", "lstm", "transformer", "meta", "monte_carlo", "regime", "fusion")
        for h in REQUIRED_ABLATION_HORIZONS
        if primary_scoring_cell_untrusted(m, h)
    )
    drop_group_count = sum(len(v) for v in drops_by_mh.values())
    report["confirm_drop_summary"] = {
        "authority": "primary_pass",
        "primary_authority": True,
        "stamped_at": datetime.now(timezone.utc).isoformat(),
        "drops_by_model_horizon": drops_by_mh,
        "cells_total": 0,
        "cells_ok": 0,
        "cells_safe_to_drop": drop_group_count,
        "confirm_pass_skipped": True,
        "untrusted_cells_excluded": untrusted,
    }
    ss["primary_pass_authority"] = True
    ss["primary_pass_only"] = True
    ss.pop("confirm_pass", None)
    report["survivor_summary"] = ss
    report.setdefault("run_meta", {})["primary_authority_stamped_at"] = report[
        "confirm_drop_summary"
    ]["stamped_at"]
    out_path = report_path or ABLATION_REPORT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.is_file():
        try:
            prior = json.loads(out_path.read_text(encoding="utf-8"))
            if (prior.get("run_meta") or {}).get("status") == "complete" and not prior.get("dry_run"):
                bak = out_path.with_name(out_path.stem + ".complete.bak" + out_path.suffix)
                if not bak.is_file():
                    bak.write_text(json.dumps(prior, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not ablation_primary_pass_authority_active(ss, report=report):
        raise RuntimeError("stamp wrote but primary authority probe failed — report unreadable?")
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


def _split_lstm_confluence_members(members: list[str]) -> tuple[list[str], list[str]]:
    """Route cf_* manifest members to X_conf (not X_5m) — CONFLUENCE_FEATURES order."""
    from lstm_data import CONFLUENCE_FEATURES

    cf = frozenset(CONFLUENCE_FEATURES)
    conf = [m for m in members if m in cf]
    m5 = [m for m in members if m not in cf]
    return m5, conf


def _conf_channel_indices(drop_conf: list[str]) -> list[int]:
    from lstm_data import CONFLUENCE_FEATURES

    return sorted(CONFLUENCE_FEATURES.index(f) for f in drop_conf if f in CONFLUENCE_FEATURES)


def _zero_conf_channels(X_conf: np.ndarray, drop_conf: list[str]) -> None:
    """In-place zero of X_conf columns for atomic cf_* ablation drops."""
    for idx in _conf_channel_indices(drop_conf):
        X_conf[:, idx] = 0.0


def _permute_conf_columns(
    X_conf: np.ndarray,
    col_indices: list[int],
    rng: np.random.Generator,
) -> np.ndarray:
    """Grouped row permutation on X_conf (N, F) — one shuffle for all listed columns."""
    out = np.array(X_conf, copy=True)
    if not col_indices or len(out) == 0:
        return out
    perm = rng.permutation(len(out))
    for c in col_indices:
        out[:, c] = out[perm, c]
    return out


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
# Each xgb/lstm/transformer layer is trained per (anchor, horizon) on a chronological
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
                    pm = _per_model_permute_members(grp, model)
                    specs.append(
                        {
                            "anchor_ticker": anchor,
                            "model_family": model,
                            "horizon_slug": hz,
                            "group_id": grp["group_id"],
                            **pm,
                        }
                    )
    return specs


def _prepare_xgb_holdout(
    *,
    ticker: str,
    horizon_slug: str,
    db_path: str,
    min_rows: int = 200,
    drop_columns: list[str] | None = None,
    drop_group_ids: list[str] | None = None,
    ablation_manifest: dict | None = None,
) -> dict:
    """Train ONE XGB model per (ticker, horizon) on the chronological holdout; reuse across groups.

    Confirm pass uses the same transform order as production: null raw snapshot columns for
    ``drop_group_ids``, engineer, then remove engineered ``drop_columns``."""
    from ml_data_common import holdout_class_metrics, time_ordered_tail_split
    from ml_horizon import normalize_ml_horizon_slug, outcome_column
    from ml_train import (
        apply_xgb_imputation_matrix,
        encode_target,
        engineer_features,
        get_model,
        load_data,
    )
    from arch_competition.stack_bundle_eval_v1 import (
        null_snapshot_dataframe_for_drop_groups,
    )

    hz = normalize_ml_horizon_slug(horizon_slug)
    label_col = outcome_column(hz)
    df = load_data(db_path=db_path, ticker=ticker, ml_horizon_slug=hz, label_column=label_col)
    if drop_group_ids and ablation_manifest:
        df = null_snapshot_dataframe_for_drop_groups(df, ablation_manifest, drop_group_ids)
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


def _prepare_lstm_holdout(
    *,
    ticker: str,
    horizon_slug: str,
    db_path: str,
    min_rows: int = 200,
    drop_5m: list[str] | None = None,
    drop_1m: list[str] | None = None,
    drop_conf: list[str] | None = None,
    drop_group_ids: list[str] | None = None,
    ablation_manifest: dict | None = None,
) -> dict:
    """Train ONE dual-stream LSTM per (ticker, horizon) on the chronological holdout.

    Confirm pass: null raw snapshot columns for ``drop_group_ids``, then post-normalize channel
    zero for ``drop_5m``/``drop_1m`` members and ``drop_conf`` cf_* on X_conf — same transform
    order as production retrain."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        return {"status": "skipped", "reason": "torch_unavailable"}

    from ml_data_common import equal_sample_weights, holdout_class_metrics, time_ordered_tail_split
    from ml_horizon import normalize_ml_horizon_slug
    from lstm_data import (
        ENCODED_FEATURES_1M, ENCODED_FEATURES_5M, FEATURES_1M, FEATURES_5M,
        CONFLUENCE_FEATURES, build_lstm_dataset,
    )
    from lstm_model import (
        BATCH_SIZE, CLIP_GRAD_NORM, EPOCHS, LEARNING_RATE, WEIGHT_DECAY,
        _validate_lstm_dataset_shape, apply_masks, apply_normalization, build_model,
        compute_feature_masks, compute_normalization,
    )

    hz = normalize_ml_horizon_slug(horizon_slug)
    _quick = (os.environ.get("ED_SURVIVOR_VALIDATION_QUICK") or "").strip().lower() in (
        "1", "true", "yes", "on"
    )
    _epochs = 2 if _quick else EPOCHS
    try:
        dataset = build_lstm_dataset(
            tickers=[ticker],
            db_path=db_path,
            ml_horizon_slug=hz,
            confirm_drop_group_ids=drop_group_ids,
            confirm_ablation_manifest=ablation_manifest,
        )
    except Exception as exc:
        return {"status": "skipped", "hz": hz, "reason": str(exc)}
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
    if drop_conf:
        _zero_conf_channels(X_conf, drop_conf)

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
    patience = _holdout_early_stop_patience(model="lstm")
    bad_epochs = 0
    for _epoch in range(1, _epochs + 1):
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
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break
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
        "mask_5m": mask_5m, "mask_1m": mask_1m, "mask_conf": mask_conf,
        "encoded_features_5m": ENCODED_FEATURES_5M, "encoded_features_1m": ENCODED_FEATURES_1M,
        "features_5m": FEATURES_5M, "features_1m": FEATURES_1M,
        "confluence_features": list(CONFLUENCE_FEATURES),
    }


def _permute_eval_lstm_group(prepared: dict, *, ticker: str, group_id: str,
                             lstm_5m_members: list[str], lstm_1m_members: list[str],
                             random_state: int = 42) -> dict:
    from ml_data_common import holdout_class_metrics

    m5_members, conf_members = _split_lstm_confluence_members(lstm_5m_members)
    pre5 = _pre_mask_encoded_indices(m5_members, prepared["features_5m"], prepared["encoded_features_5m"])
    pre1 = _pre_mask_encoded_indices(lstm_1m_members, prepared["features_1m"], prepared["encoded_features_1m"])
    ch5 = _post_mask_channel_indices(pre5, prepared["mask_5m"])
    ch1 = _post_mask_channel_indices(pre1, prepared["mask_1m"])
    ch_conf = _conf_channel_indices(conf_members)
    rng = np.random.default_rng(random_state)
    v5 = _permute_sequence_channels(prepared["val_5m"], ch5, rng)
    v1 = _permute_sequence_channels(prepared["val_1m"], ch1, rng)
    v_conf = _permute_conf_columns(prepared["val_conf"], ch_conf, rng)
    perm_pred = _lstm_predict_numpy(prepared["model"], v5, v1, v_conf, prepared["device"])
    perm_mcc = _matthews_corrcoef_safe(prepared["y_val"], perm_pred)
    perm_hcm = holdout_class_metrics(prepared["y_val"], perm_pred, 3)
    base_mcc = prepared["baseline_mcc"]
    return {
        "anchor_ticker": ticker, "model_family": "lstm", "horizon_slug": prepared["hz"],
        "group_id": group_id, "status": "ok", "ablation_kind": "per_model_feature_group",
        "members_permuted_count": len(ch5) + len(ch1) + len(ch_conf),
        "lstm_5m_channels_permuted": ch5, "lstm_1m_channels_permuted": ch1,
        "lstm_conf_channels_permuted": ch_conf,
        "holdout_rows": prepared["n_val"],
        "baseline_mcc": base_mcc, "permuted_mcc": perm_mcc,
        "mcc_delta": (None if base_mcc is None or perm_mcc is None else round(base_mcc - perm_mcc, 6)),
        "group_matters": bool(base_mcc is not None and perm_mcc is not None and (base_mcc - perm_mcc) > 1e-4),
        "baseline_per_class_recall": prepared["baseline_hcm"].get("per_class_recall"),
        "permuted_per_class_recall": perm_hcm.get("per_class_recall"),
    }


def _prepare_transformer_holdout(
    *,
    ticker: str,
    horizon_slug: str,
    db_path: str,
    min_rows: int = 200,
    drop_5m: list[str] | None = None,
    drop_group_ids: list[str] | None = None,
    ablation_manifest: dict | None = None,
) -> dict:
    """Train ONE transformer per (ticker, horizon) on the chronological holdout.

    Confirm pass: null raw snapshot columns for ``drop_group_ids``, normalize, mask, then
    post-normalize channel zero for ``drop_5m`` members — matches production retrain order."""
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
    _quick = (os.environ.get("ED_SURVIVOR_VALIDATION_QUICK") or "").strip().lower() in (
        "1", "true", "yes", "on"
    )
    _epochs = 2 if _quick else EPOCHS
    try:
        X, y, _days, _tk, n_features = prepare_transformer_data(
            db_path,
            ticker,
            ml_horizon_slug=hz,
            confirm_drop_group_ids=drop_group_ids,
            confirm_ablation_manifest=ablation_manifest,
        )
    except Exception as exc:
        return {"status": "skipped", "hz": hz, "reason": str(exc)}
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
    patience = _holdout_early_stop_patience(model="transformer")
    bad_epochs = 0
    for _epoch in range(1, _epochs + 1):
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
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                break
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
    include_o56: bool = False,
    include_stack_authority: bool = False,
) -> dict:
    """Build ablation report from manifest-only contract.

    Primary (only): feature × all seven stack models × all four horizons — full_fusion log_loss per cell.
    Legacy O-56 MCC and stack-authority passes are retired from this entrypoint.
    """
    if include_o56 or include_stack_authority:
        raise SystemExit(
            "Parallel ablation paths retired: --ablation is the single whole-stack grid only. "
            "Remove --ablation-include-o56 and --ablation-include-stack-authority."
        )
    manifest = load_ablation_manifest(manifest_path)
    _enforce_full_stack_ablation_contract(manifest, horizons=horizons)
    method = manifest["ablation_method"]
    effective_horizons = _required_ablation_horizons(manifest)
    groups = ablation_groups(manifest)
    db = db_path or str(DB_PATH)
    out_path = report_path or ABLATION_REPORT_PATH
    grid_specs = ablation_whole_stack_feature_cell_specs(manifest, tickers=tickers)
    accounting = ablation_cell_accounting(manifest, grid_specs)

    resume_whole_stack: dict[str, dict] = {}
    resume_per_model: dict[str, dict] = {}
    resume_stack: dict[str, dict] = {}
    started_at = datetime.now(timezone.utc).isoformat()
    if resume and out_path.is_file():
        prior = json.loads(out_path.read_text(encoding="utf-8"))
        resume_whole_stack = _index_whole_stack_cells(
            prior.get("whole_stack_feature_cells") or []
        )
        resume_per_model = _index_per_model_cells(prior.get("per_model_feature_cells") or [])
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
        "ablation_accounting": accounting,
        "whole_stack_catalog_cell_target": accounting["catalog_target"],
        "whole_stack_runnable_cell_target": accounting["runnable_target"],
        "whole_stack_feature_cell_target": accounting["runnable_target"],
        "whole_stack_feature_cell_count": accounting["catalog_target"],
        "whole_stack_catalog_cell_count": accounting["catalog_target"],
        "whole_stack_runnable_cell_count": accounting["runnable_target"],
        "per_model_feature_cell_count": manifest["totals"]["per_model_feature_cell_count"],
        "stack_authority_cell_count": int(
            (manifest.get("totals") or {}).get("stack_authority_cell_count") or 0
        ),
        "grid_cell_count": int(
            (manifest.get("totals") or {}).get("grid_cell_count")
            or manifest["totals"]["per_model_feature_cell_count"]
        ),
        "whole_stack_feature_cells": [],
        "per_model_feature_cells": [],
        "stack_authority_cells": [],
        "stack_layer_cells": [],
        "run_meta": {
            "started_at": started_at,
            "resume": bool(resume),
            "db_path": db,
            "tickers": tickers,
            "include_o56": bool(include_o56),
            "include_stack_authority": bool(include_stack_authority),
        },
    }

    if dry_run:
        whole_stack_section = build_whole_stack_feature_ablation_section(
            manifest, db_path=db, dry_run=True, tickers=tickers, horizons=effective_horizons
        )
        report.update(whole_stack_section)
        if include_o56:
            feature_section = build_per_model_feature_ablation_section(
                manifest, db_path=db, dry_run=True, tickers=tickers, horizons=effective_horizons
            )
            report.update(feature_section)
        if include_stack_authority:
            stack_section = build_stack_authority_ablation_section(
                manifest, db_path=db, dry_run=True, tickers=tickers, horizons=effective_horizons
            )
            report.update(stack_section)
        report["dry_run"] = True
        return report

    from arch_competition.stack_bundle_eval_v1 import ABLATION_SCORING_PASS_ENV

    _prev_strict = os.environ.get("ED_XGB_STRICT_ACTIVE_ONLY")
    _prev_ablation_eval = os.environ.get(ABLATION_SCORING_PASS_ENV)
    os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = "0"
    os.environ[ABLATION_SCORING_PASS_ENV] = "1"
    report["run_meta"]["ed_xgb_strict_active_only"] = "0"
    report["run_meta"]["ed_ablation_scoring_pass"] = "1"
    report["run_meta"]["note"] = (
        "Offline ablation scoring pass: survivor mask disabled; production loaders unchanged. "
        "Whole-stack scores all seven models × four horizons via offline v2/v3 encoder lineage."
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
            f"Operational window capped: last {eval_opts.max_rows} chronological RTH rows "
            "(override via ED_ABLATION_MAX_ROWS). Set ED_ABLATION_FULL_HISTORY=1 to affirm full replay."
        )
    elif eval_opts.max_rows is None:
        report["run_meta"]["eval_window_note"] = (
            "Full chronological RTH history (default). Override with ED_ABLATION_MAX_ROWS if needed."
        )
    pf = run_ablation_preflight(manifest, db_path=db, tickers=tickers or [])
    report["run_meta"]["preflight"] = pf
    report["run_progress"] = {
        "phase": "starting",
        "cells_done": 0,
        "cells_total": accounting["runnable_target"],
        "catalog_cells_total": accounting["catalog_target"],
    }
    _write_ablation_checkpoint(out_path, report)
    print(
        f"ablation run started max_rows={eval_opts.max_rows} full_history={full_hist} "
        f"runnable_cells={accounting['runnable_target']} catalog_slots={accounting['catalog_target']} "
        f"include_o56={bool(report['run_meta'].get('include_o56'))} "
        f"include_stack_authority={bool(report['run_meta'].get('include_stack_authority'))}",
        flush=True,
    )
    acquire_ablation_run_lock(run_kind="primary")
    try:
        try:
            return _build_ablation_report_scored(
                manifest=manifest,
                report=report,
                db=db,
                tickers=tickers,
                effective_horizons=effective_horizons,
                out_path=out_path,
                resume_whole_stack=resume_whole_stack,
                resume_per_model=resume_per_model,
                resume_stack=resume_stack,
                include_o56=include_o56,
                include_stack_authority=include_stack_authority,
            )
        finally:
            release_ablation_run_lock()
    finally:
        if _prev_strict is None:
            os.environ.pop("ED_XGB_STRICT_ACTIVE_ONLY", None)
        else:
            os.environ["ED_XGB_STRICT_ACTIVE_ONLY"] = _prev_strict
        if _prev_ablation_eval is None:
            os.environ.pop("ED_ABLATION_SCORING_PASS", None)
        else:
            os.environ["ED_ABLATION_SCORING_PASS"] = _prev_ablation_eval


def _build_ablation_report_scored(
    *,
    manifest: dict,
    report: dict,
    db: str,
    tickers: list[str] | None,
    effective_horizons: list[str],
    out_path: Path,
    resume_whole_stack: dict[str, dict],
    resume_per_model: dict[str, dict],
    resume_stack: dict[str, dict],
    include_o56: bool = False,
    include_stack_authority: bool = False,
) -> dict:
    def _checkpoint(section_kind: str, cell: dict, n: int, total: int) -> None:
        accounting = report.get("ablation_accounting") or {}
        report["run_progress"] = {
            "phase": section_kind,
            "cells_done": n,
            "cells_total": total,
            "catalog_cells_total": accounting.get("catalog_target"),
            "last_cell": {
                "anchor_ticker": cell.get("anchor_ticker"),
                "model_family": cell.get("model_family"),
                "horizon_slug": cell.get("horizon_slug"),
                "group_id": cell.get("group_id"),
                "status": cell.get("status"),
                "log_loss_delta": cell.get("log_loss_delta"),
                "runnable": cell.get("runnable"),
            },
        }
        report["survivor_summary"] = build_ablation_survivor_summary(
            report.get("whole_stack_feature_cells") or []
        )
        _attach_experiment_integrity(report)
        _write_ablation_checkpoint(out_path, report)
        label = cell.get("group_id") or "stack_authority"
        delta = cell.get("log_loss_delta")
        delta_s = f" delta={delta}" if delta is not None else ""
        mf = cell.get("model_family")
        mf_s = f"{mf}/" if mf else ""
        print(
            f"ablation [{section_kind}] {n}/{total} "
            f"{cell.get('anchor_ticker')}/{mf_s}{cell.get('horizon_slug')}/{label} "
            f"status={cell.get('status')}{delta_s}",
            flush=True,
        )

    whole_stack_section = build_whole_stack_feature_ablation_section(
        manifest,
        db_path=db,
        dry_run=False,
        tickers=tickers,
        horizons=effective_horizons,
        resume_cells=resume_whole_stack,
        on_cell_done=_checkpoint,
        cells_out=report["whole_stack_feature_cells"],
    )
    report.update(whole_stack_section)
    report["survivor_summary"] = build_ablation_survivor_summary(
        report.get("whole_stack_feature_cells") or []
    )
    _attach_experiment_integrity(report, manifest=manifest)

    ws_ok = sum(
        1
        for c in report.get("whole_stack_feature_cells") or []
        if _ablation_cell_is_runnable(c) and c.get("status") == "ok"
    )
    runnable_cells = [
        c for c in report.get("whole_stack_feature_cells") or [] if _ablation_cell_is_runnable(c)
    ]
    runnable_terminal = sum(
        1 for c in runnable_cells if c.get("status") in ("ok", "skipped")
    )
    runnable_target = int(
        report.get("whole_stack_runnable_cell_target")
        or (report.get("ablation_accounting") or {}).get("runnable_target")
        or 0
    )
    report["run_meta"]["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["run_meta"]["whole_stack_ok"] = ws_ok
    report["run_meta"]["whole_stack_runnable_ok"] = ws_ok
    report["run_meta"]["whole_stack_runnable_terminal"] = runnable_terminal
    report["run_meta"]["whole_stack_skipped"] = runnable_terminal - ws_ok
    report["run_meta"]["whole_stack_only"] = True
    report["run_meta"]["per_model_ok"] = 0
    report["run_meta"]["per_model_skipped"] = 0
    report["run_meta"]["status"] = (
        "complete"
        if runnable_target > 0 and runnable_terminal >= runnable_target
        else "partial"
    )
    _attach_experiment_integrity(report, manifest=manifest)
    _write_ablation_checkpoint(out_path, report)
    return report


def write_ablation_report(report: dict, path: Path | None = None) -> Path:
    out_path = path or ABLATION_REPORT_PATH
    if report.get("whole_stack_feature_cells"):
        _attach_experiment_integrity(report)
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
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return int(exit_code.value) == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
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


def acquire_ablation_run_lock(*, run_kind: str = "primary") -> None:
    """Single-instance guard — refuse a second scored ablation/confirm on this host."""
    existing = _read_ablation_lock()
    if existing:
        pid = int(existing.get("pid") or 0)
        if _pid_alive(pid):
            kind = str(existing.get("run_kind") or "ablation")
            raise SystemExit(
                f"{kind} already running (pid={pid}, lock={ABLATION_LOCK_PATH}); "
                "stop that process before starting another run"
            )
        ABLATION_LOCK_PATH.unlink(missing_ok=True)
    ABLATION_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    ABLATION_LOCK_PATH.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "run_kind": run_kind,
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def release_ablation_run_lock() -> None:
    ABLATION_LOCK_PATH.unlink(missing_ok=True)


def ablation_report_status(report_path: Path | None = None) -> dict:
    """Certified on-disk ablation progress (runnable-cell denominator — not catalog slots)."""
    out_path = report_path or ABLATION_REPORT_PATH
    lock = _read_ablation_lock()
    lock_pid = int((lock or {}).get("pid") or 0)
    lock_live = _pid_alive(lock_pid) if lock else False
    catalog_target = whole_stack_catalog_cell_target()
    runnable_target = whole_stack_runnable_cell_target()
    base: dict = {
        "report_path": str(out_path.resolve()),
        "lock_path": str(ABLATION_LOCK_PATH.resolve()),
        "lock_pid": lock_pid if lock else None,
        "ablation_process_live": lock_live,
        "whole_stack_feature_cells": 0,
        "whole_stack_runnable_cell_target": runnable_target,
        "whole_stack_catalog_cell_target": catalog_target,
        "whole_stack_runnable_done": 0,
        "whole_stack_runnable_ok": 0,
        "catalog_only_cells": 0,
        "run_status": "missing",
        "complete": False,
        "resume_recommended": False,
        "confirm_cells_done": 0,
        "confirm_cells_total": PER_MODEL_CONFIRM_CELL_TARGET,
        "confirm_path_version": None,
        "confirm_complete": False,
        "confirm_resume_recommended": False,
        # Backward-compatible aliases (whole-stack primary pass — not O-56 per-model)
        "per_model_feature_cells": 0,
        "per_model_feature_target": runnable_target,
        "stack_authority_cells": 0,
        "stack_authority_target": 0,
    }
    if lock:
        base["lock_run_kind"] = lock.get("run_kind")
    if not out_path.is_file():
        return base
    try:
        report = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        base["run_status"] = "unreadable"
        base["error"] = str(exc)
        return base
    from arch_competition.stack_bundle_eval_v1 import ablation_confirm_pass_complete

    cells = report.get("whole_stack_feature_cells") or []
    accounting = report.get("ablation_accounting") or {}
    meta = report.get("run_meta") or {}
    prog = report.get("run_progress") or {}
    ss = report.get("survivor_summary") or {}
    confirm_summary = report.get("confirm_drop_summary") or {}
    runnable_target = _resolve_ablation_runnable_target(report)
    catalog_target = int(
        report.get("whole_stack_catalog_cell_target")
        or accounting.get("catalog_target")
        or catalog_target
    )
    runnable_cells = [c for c in cells if _ablation_cell_is_runnable(c)]
    catalog_only = len(cells) - len(runnable_cells)
    runnable_done = sum(1 for c in runnable_cells if c.get("status") in ("ok", "skipped"))
    runnable_ok = sum(1 for c in runnable_cells if c.get("status") == "ok")
    status = str(meta.get("status") or prog.get("phase") or "partial")
    complete = (
        runnable_target > 0
        and runnable_done >= runnable_target
        and status == "complete"
    )
    confirm_total = int(
        prog.get("cells_total")
        or confirm_summary.get("cells_total")
        or PER_MODEL_CONFIRM_CELL_TARGET
    )
    if prog.get("phase") == "per_model_confirm" and prog.get("cells_done") is not None:
        confirm_done = int(prog["cells_done"])
    else:
        confirm_done = len(report.get("confirm_drop_cells") or [])
    confirm_pass = ss.get("confirm_pass")
    confirm_version = (
        confirm_pass.get("confirm_path_version")
        if isinstance(confirm_pass, dict)
        else None
    )
    confirm_complete = ablation_confirm_pass_complete(ss)
    resume_v2 = _confirm_resume_cells_from_report(report)
    integrity = report.get("experiment_integrity") or {}
    base.update(
        {
            "ablation_accounting": accounting,
            "whole_stack_feature_cells": len(cells),
            "whole_stack_runnable_cell_target": runnable_target,
            "whole_stack_catalog_cell_target": catalog_target,
            "whole_stack_runnable_done": runnable_done,
            "whole_stack_runnable_ok": runnable_ok,
            "catalog_only_cells": catalog_only,
            "per_model_feature_cells": runnable_done,
            "per_model_feature_target": runnable_target,
            "run_status": status,
            "started_at": meta.get("started_at"),
            "last_progress": prog.get("last_cell"),
            "complete": complete,
            "resume_recommended": (not complete) and runnable_done > 0,
            "confirm_cells_done": confirm_done,
            "confirm_cells_total": confirm_total,
            "confirm_path_version": confirm_version,
            "confirm_complete": confirm_complete,
            "confirm_resume_recommended": bool(resume_v2) and not confirm_complete,
            "experiment_integrity_verdict": integrity.get("verdict"),
            "experiment_integrity_reason": integrity.get("verdict_reason"),
            "experiment_skew_flag_count": len(integrity.get("skew_flags") or []),
        }
    )
    return base


def format_ablation_integrity_report(integrity: dict) -> str:
    """Human-readable skew trace for operator / agent triage."""
    lines = [
        f"experiment_integrity verdict={integrity.get('verdict')} — {integrity.get('verdict_reason')}",
        f"manifest: {(integrity.get('artifact_paths') or {}).get('manifest')}",
        f"report:   {(integrity.get('artifact_paths') or {}).get('report')}",
    ]
    rc = integrity.get("run_completion") or {}
    lines.append(
        f"progress: {rc.get('runnable_terminal')}/{rc.get('runnable_target')} terminal "
        f"({rc.get('runnable_ok')} ok, {rc.get('runnable_skipped')} skipped)"
    )
    flags = integrity.get("skew_flags") or []
    if flags:
        lines.append(f"skew_flags ({len(flags)}):")
        for f in flags[:20]:
            lines.append(
                f"  [{f.get('severity')}] {f.get('code')}: {f.get('message')}"
            )
            if f.get("fix_direction"):
                lines.append(f"    fix: {f['fix_direction']}")
    else:
        lines.append("skew_flags: none")
    trace = integrity.get("trace_cells") or []
    if trace:
        lines.append(f"trace_cells (first {min(8, len(trace))}):")
        for t in trace[:8]:
            lines.append(
                f"  {t.get('model_family')}/{t.get('horizon_slug')}/{t.get('group_id')} "
                f"status={t.get('status')} delta={t.get('log_loss_delta')} "
                f"perm={t.get('columns_permuted_count')} reason={t.get('reason')}"
            )
    skip_roll = integrity.get("skip_reason_rollup") or {}
    if skip_roll:
        top = list(skip_roll.items())[:8]
        lines.append("skip_reason_rollup top: " + ", ".join(f"{k}={v}" for k, v in top))
    return "\n".join(lines)


def audit_ablation_experiment_integrity(report_path: Path | None = None) -> dict:
    """Load on-disk report and rebuild experiment_integrity (no rescoring)."""
    out_path = report_path or ABLATION_REPORT_PATH
    if not out_path.is_file():
        return {"verdict": "MISSING", "verdict_reason": f"no report at {out_path}"}
    report = json.loads(out_path.read_text(encoding="utf-8"))
    integrity = build_ablation_experiment_integrity(report)
    report["experiment_integrity"] = integrity
    _write_ablation_checkpoint(out_path, report)
    return integrity


def guard_ablation_confirm_fresh_start(
    report_path: Path,
    *,
    resume: bool,
    force_restart: bool = False,
) -> None:
    """Refuse to wipe partial v2 confirm cells without --ablation-confirm-resume."""
    if resume or force_restart or not report_path.is_file():
        return
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    resume_cells = _confirm_resume_cells_from_report(report)
    if resume_cells:
        raise SystemExit(
            f"refusing fresh confirm: {report_path} has {len(resume_cells)} "
            f"v2-tagged confirm cell(s). Use --ablation-confirm-resume to continue."
        )


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
    n_whole = len(report.get("whole_stack_feature_cells") or [])
    runnable_target = int(
        report.get("whole_stack_runnable_cell_target")
        or (report.get("ablation_accounting") or {}).get("runnable_target")
        or 0
    )
    if runnable_target <= 0:
        try:
            runnable_target = whole_stack_runnable_cell_target(load_ablation_manifest())
        except FileNotFoundError:
            runnable_target = 0
    runnable_cells = [
        c for c in (report.get("whole_stack_feature_cells") or []) if c.get("runnable")
    ]
    runnable_terminal = sum(
        1 for c in runnable_cells if c.get("status") in ("ok", "skipped")
    )
    status = str((report.get("run_meta") or {}).get("status") or "")
    if (
        runnable_target > 0
        and runnable_terminal >= runnable_target
        and status == "complete"
    ):
        raise SystemExit(
            f"refusing fresh ablation: {report_path} already complete "
            f"({runnable_terminal}/{runnable_target} runnable cells; "
            f"{n_whole} catalog slots on disk). "
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
    from arch_competition.stack_bundle_eval_v1 import (
        ablation_confirm_pass_complete,
        ablation_primary_pass_authority_active,
    )

    if abl.get("complete") and ablation_confirm_pass_complete():
        mask_src = "confirm_pass"
    elif abl.get("complete") and ablation_primary_pass_authority_active():
        mask_src = "primary_pass_authority"
    elif abl.get("complete"):
        mask_src = "confirm_incomplete"
    else:
        mask_src = "report_incomplete"
    return {
        "ablation": abl,
        "ml_train_processes": trains,
        "ED_APPLY_ABLATION_SURVIVORS": survivors_env,
        "survivor_mask_source": mask_src,
    }


SURVIVOR_EDGE_PROBE_PATH = Path("governance/artifacts/survivor_edge_probe.json")
SURVIVOR_VALIDATION_RUN_PATH = Path("governance/artifacts/survivor_validation_run.json")
SURVIVOR_INFERENCE_BACKTEST_PATH = Path("governance/artifacts/survivor_inference_backtest.json")
SURVIVOR_STACK_REFIT_BACKTEST_PATH = Path(
    "governance/artifacts/survivor_stack_refit_backtest.json"
)
SURVIVOR_EDGE_MCC_MIN = 0.01
# Powered holdout floor for survivor quality gates (NOT "p<0.05" — use bootstrap CI in backtest).
SURVIVOR_MIN_PAIRED_ROWS_POWERED = 400
SURVIVOR_MIN_LOG_LOSS_DELTA = 0.02
FULL_STACK_LAYERS_SCORED = (
    "xgb",
    "lstm",
    "transformer",
    "meta_stack",
    "fusion_without_mc",
    "full_fusion",
)


def write_leaf_ablation_manifest(manifest_path: Path | None = None) -> Path:
    """Write Schwab-expanded ablation manifest (replaces compound→leaf split)."""
    from tools.build_feature_assignment_matrix_v2 import write_feature_ablation_manifest

    return write_feature_ablation_manifest(manifest_path or MANIFEST_PATH)


def _holdout_multiclass_log_loss_xgb(prepared: dict) -> tuple[float | None, int]:
    from sklearn.metrics import log_loss

    if prepared.get("status") != "ok":
        return None, 0
    model = prepared.get("model")
    y_val = prepared.get("y_val")
    x_val = prepared.get("x_val")
    if model is None or y_val is None or x_val is None or len(y_val) == 0:
        return None, 0
    try:
        proba = model.predict_proba(x_val)
        ll = float(log_loss(y_val, proba, labels=[0, 1, 2]))
        return ll, int(len(y_val))
    except Exception:
        return None, int(len(y_val))


def _holdout_multiclass_log_loss_lstm(prepared: dict) -> tuple[float | None, int]:
    from sklearn.metrics import log_loss

    if prepared.get("status") != "ok":
        return None, 0
    y_val = prepared.get("y_val")
    if y_val is None or len(y_val) == 0:
        return None, 0
    try:
        import torch

        model = prepared["model"]
        device = prepared["device"]
        model.eval()
        with torch.no_grad():
            b5 = torch.tensor(prepared["val_5m"], dtype=torch.float32, device=device)
            b1 = torch.tensor(prepared["val_1m"], dtype=torch.float32, device=device)
            bc = torch.tensor(prepared["val_conf"], dtype=torch.float32, device=device)
            logits = model(b1, b5, bc)
            proba = torch.softmax(logits, dim=-1).cpu().numpy()
        ll = float(log_loss(y_val, proba, labels=[0, 1, 2]))
        return ll, int(len(y_val))
    except Exception:
        return None, int(len(y_val))


def _holdout_multiclass_log_loss_transformer(prepared: dict) -> tuple[float | None, int]:
    from sklearn.metrics import log_loss

    if prepared.get("status") != "ok":
        return None, 0
    y_val = prepared.get("y_val")
    if y_val is None or len(y_val) == 0:
        return None, 0
    try:
        import torch

        model = prepared["model"]
        device = prepared["device"]
        model.eval()
        with torch.no_grad():
            bx = torch.tensor(prepared["val_X"], dtype=torch.float32, device=device)
            logits = model(bx)
            proba = torch.softmax(logits, dim=-1).cpu().numpy()
        ll = float(log_loss(y_val, proba, labels=[0, 1, 2]))
        return ll, int(len(y_val))
    except Exception:
        return None, int(len(y_val))


def run_survivor_stack_refit_backtest(
    *,
    tickers: list[str] | None = None,
    db_path: str | None = None,
    min_paired_rows: int | None = None,
) -> dict:
    """Quality gate: refit full-feature vs survivor-only on holdout; score multiclass log_loss.

    Unlike run_survivor_inference_backtest (mask on old weights), this refits both variants and
    compares holdout log_loss — the correct pre-production test. Reports every ML stack layer × horizon
    × anchor; stack layers (meta/MC/fusion) scored when bundle staging is available."""
    from arch_competition.stack_bundle_eval_v1 import (
        ablated_drop_group_ids_for_model_horizon,
        ablated_drop_members_for_model_horizon,
    )

    _db = db_path or str(DB_PATH)
    anchors = [ticker_storage_key(t) for t in (tickers or SURVIVOR_RETRAIN_DEFAULT_TICKERS) if str(t).strip()]  # RC-345/F25: anchor identity canonical, not local .upper()
    min_n = int(
        min_paired_rows
        if min_paired_rows is not None
        else os.environ.get("ED_SURVIVOR_MIN_PAIRED_ROWS", str(SURVIVOR_MIN_PAIRED_ROWS_POWERED))
    )
    manifest = load_ablation_manifest()
    out: dict = {
        "schema_version": "2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "survivor_refit_vs_full_refit_holdout",
        "primary_metric": "multiclass_log_loss",
        "min_paired_rows_required": min_n,
        "min_log_loss_delta_required": SURVIVOR_MIN_LOG_LOSS_DELTA,
        "stack_layers": list(FULL_STACK_LAYERS_SCORED),
        "anchors": anchors,
        "horizons": list(REQUIRED_ABLATION_HORIZONS),
        "ready_for_production": False,
        "issues": [],
        "base_model_cells": [],
        "stack_layer_cells": [],
    }
    _prep = {
        "xgb": (_prepare_xgb_holdout, _holdout_multiclass_log_loss_xgb),
        "lstm": (_prepare_lstm_holdout, _holdout_multiclass_log_loss_lstm),
        "transformer": (_prepare_transformer_holdout, _holdout_multiclass_log_loss_transformer),
    }
    prev_quick = os.environ.get("ED_SURVIVOR_VALIDATION_QUICK")
    os.environ["ED_SURVIVOR_VALIDATION_QUICK"] = "1"
    try:
        for anc in anchors:
            for model in ("xgb", "lstm", "transformer"):
                for hz in REQUIRED_ABLATION_HORIZONS:
                    hz_n = hz
                    drop_ids = sorted(ablated_drop_group_ids_for_model_horizon(model, hz_n))
                    xcols, m5, m1, conf = (
                        ablated_drop_members_for_model_horizon(model, hz_n)
                        if drop_ids
                        else ([], [], [], [])
                    )
                    prep_fn, ll_fn = _prep[model]
                    if model == "xgb":
                        full_prep = prep_fn(
                            ticker=anc, horizon_slug=hz_n, db_path=_db,
                            drop_columns=None, drop_group_ids=None, ablation_manifest=manifest,
                        )
                        surv_prep = prep_fn(
                            ticker=anc, horizon_slug=hz_n, db_path=_db,
                            drop_columns=list(xcols), drop_group_ids=drop_ids,
                            ablation_manifest=manifest,
                        ) if drop_ids else full_prep
                    elif model == "lstm":
                        full_prep = prep_fn(
                            ticker=anc, horizon_slug=hz_n, db_path=_db,
                            drop_5m=None, drop_1m=None, drop_group_ids=None,
                            ablation_manifest=manifest,
                        )
                        surv_prep = prep_fn(
                            ticker=anc, horizon_slug=hz_n, db_path=_db,
                            drop_5m=list(m5), drop_1m=list(m1), drop_conf=list(conf),
                            drop_group_ids=drop_ids,
                            ablation_manifest=manifest,
                        ) if drop_ids else full_prep
                    else:
                        full_prep = prep_fn(
                            ticker=anc, horizon_slug=hz_n, db_path=_db,
                            drop_5m=None, drop_group_ids=None, ablation_manifest=manifest,
                        )
                        surv_prep = prep_fn(
                            ticker=anc, horizon_slug=hz_n, db_path=_db,
                            drop_5m=list(m5), drop_group_ids=drop_ids,
                            ablation_manifest=manifest,
                        ) if drop_ids else full_prep

                    ll_full, n_full = ll_fn(full_prep)
                    ll_surv, n_surv = ll_fn(surv_prep)
                    cell: dict = {
                        "anchor_ticker": anc,
                        "model_family": model,
                        "horizon_slug": hz_n,
                        "drop_group_count": len(drop_ids),
                        "full_refit": {
                            "status": full_prep.get("status"),
                            "holdout_log_loss": round(ll_full, 6) if ll_full is not None else None,
                            "n_holdout": n_full,
                        },
                        "survivor_refit": {
                            "status": surv_prep.get("status"),
                            "holdout_log_loss": round(ll_surv, 6) if ll_surv is not None else None,
                            "n_holdout": n_surv,
                        },
                        "powered": bool(n_full >= min_n and n_surv >= min_n),
                        "survivor_better": None,
                        "log_loss_delta_full_minus_survivor": None,
                        "bootstrap": {},
                    }
                    if ll_full is not None and ll_surv is not None:
                        cell["log_loss_delta_full_minus_survivor"] = round(ll_full - ll_surv, 6)
                        cell["survivor_better"] = bool(ll_full - ll_surv > SURVIVOR_MIN_LOG_LOSS_DELTA)
                    if full_prep.get("status") != "ok" or surv_prep.get("status") != "ok":
                        out["issues"].append(
                            f"refit_failed:{anc}/{model}/{hz_n}:"
                            f"full={full_prep.get('reason', full_prep.get('status'))}:"
                            f"surv={surv_prep.get('reason', surv_prep.get('status'))}"
                        )
                    elif not cell["powered"]:
                        out["issues"].append(
                            f"underpowered:{anc}/{model}/{hz_n}:n={n_full} need>={min_n}"
                        )
                    out["base_model_cells"].append(cell)
    finally:
        if prev_quick is None:
            os.environ.pop("ED_SURVIVOR_VALIDATION_QUICK", None)
        else:
            os.environ["ED_SURVIVOR_VALIDATION_QUICK"] = prev_quick

    powered = [c for c in out["base_model_cells"] if c.get("powered")]
    edge_powered = [c for c in powered if int(c.get("drop_group_count") or 0) > 0]
    better = [c for c in edge_powered if c.get("survivor_better")]
    out["summary"] = {
        "base_cells_total": len(out["base_model_cells"]),
        "base_cells_powered": len(powered),
        "edge_cells_with_drops": len(edge_powered),
        "edge_cells_survivor_better": len(better),
    }
    if not edge_powered:
        out["issues"].append("no_edge_cells_with_drops_to_score")
    elif len(edge_powered) < len([c for c in out["base_model_cells"] if c.get("drop_group_count")]):
        out["issues"].append("some_edge_cells_underpowered_see_base_model_cells")
    out["ready_for_production"] = bool(edge_powered) and len(better) == len(edge_powered)
    SURVIVOR_STACK_REFIT_BACKTEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    SURVIVOR_STACK_REFIT_BACKTEST_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def run_survivor_inference_backtest(**kwargs) -> dict:
    """REMOVED — masking survivors on models/active/ was the wrong experiment."""
    raise SystemExit(
        "run_survivor_inference_backtest is removed; use run_survivor_stack_refit_backtest "
        "(holdout refit full vs survivor stacks)."
    )


def run_survivor_validation_run(
    *,
    tickers: list[str] | None = None,
    db_path: str | None = None,
) -> dict:
    """Production-path validation before full retrain: quick holdout + parity counts per EDGE cell."""
    from arch_competition.stack_bundle_eval_v1 import (
        ablated_drop_group_ids_for_model_horizon,
        ablated_drop_members_for_model_horizon,
        ablation_survivors_training_enabled,
        drop_ablated_xgb_engineered_columns,
    )
    from ml_horizon import normalize_ml_horizon_slug, outcome_column
    from ml_train import engineer_features, load_data

    _db = db_path or str(DB_PATH)
    anchors = [ticker_storage_key(t) for t in (tickers or SURVIVOR_RETRAIN_DEFAULT_TICKERS) if str(t).strip()]  # RC-345/F25: anchor identity canonical, not local .upper()
    manifest = load_ablation_manifest()
    edge = run_survivor_edge_probe(tickers=anchors)
    out: dict = {
        "schema_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "anchors": anchors,
        "edge_probe_summary": edge.get("summary") or {},
        "ready_for_full_retrain": False,
        "issues": list(edge.get("issues") or []),
        "cells": [],
    }
    if not ablation_survivors_training_enabled():
        out["issues"].append("ED_APPLY_ABLATION_SURVIVORS not enabled")
    if not edge.get("ready_for_full_retrain"):
        out["issues"].append("edge_probe_not_ready")

    prev_quick = os.environ.get("ED_SURVIVOR_VALIDATION_QUICK")
    os.environ["ED_SURVIVOR_VALIDATION_QUICK"] = "1"
    try:
        for anc in anchors:
            for model in ("xgb", "lstm", "transformer"):
                for hz in REQUIRED_ABLATION_HORIZONS:
                    hz_n = normalize_ml_horizon_slug(hz)
                    drop_ids = sorted(ablated_drop_group_ids_for_model_horizon(model, hz_n))
                    if not drop_ids:
                        continue
                    xcols, m5, m1, conf = ablated_drop_members_for_model_horizon(model, hz_n)
                    cell: dict = {
                        "anchor_ticker": anc,
                        "model_family": model,
                        "horizon_slug": hz_n,
                        "drop_group_count": len(drop_ids),
                        "parity_ok": False,
                    }
                    if model == "xgb":
                        label = outcome_column(hz_n)
                        df = load_data(db_path=_db, ticker=anc, ml_horizon_slug=hz_n, label_column=label)
                        X_full, fn_full, _, _ = engineer_features(df)
                        _, _, n_prod_drop = drop_ablated_xgb_engineered_columns(X_full, fn_full, hz_n)
                        prep = _prepare_xgb_holdout(
                            ticker=anc,
                            horizon_slug=hz_n,
                            db_path=_db,
                            drop_columns=list(xcols),
                            drop_group_ids=drop_ids,
                            ablation_manifest=manifest,
                        )
                        cell["production_cols_dropped"] = n_prod_drop
                        cell["confirm_status"] = prep.get("status")
                        cell["parity_ok"] = (
                            prep.get("status") == "ok"
                            and n_prod_drop == len([c for c in xcols if c in fn_full])
                        )
                    elif model == "lstm":
                        prep = _prepare_lstm_holdout(
                            ticker=anc,
                            horizon_slug=hz_n,
                            db_path=_db,
                            drop_5m=list(m5),
                            drop_1m=list(m1),
                            drop_conf=list(conf),
                            drop_group_ids=drop_ids,
                            ablation_manifest=manifest,
                        )
                        cell["confirm_status"] = prep.get("status")
                        cell["parity_ok"] = prep.get("status") == "ok"
                    else:
                        prep = _prepare_transformer_holdout(
                            ticker=anc,
                            horizon_slug=hz_n,
                            db_path=_db,
                            drop_5m=list(m5),
                            drop_group_ids=drop_ids,
                            ablation_manifest=manifest,
                        )
                        cell["confirm_status"] = prep.get("status")
                        cell["parity_ok"] = prep.get("status") == "ok"
                    if not cell["parity_ok"]:
                        out["issues"].append(
                            f"validation_failed:{anc}/{model}/{hz_n}:{prep.get('reason', prep.get('status'))}"
                        )
                    out["cells"].append(cell)
    finally:
        if prev_quick is None:
            os.environ.pop("ED_SURVIVOR_VALIDATION_QUICK", None)
        else:
            os.environ["ED_SURVIVOR_VALIDATION_QUICK"] = prev_quick

    out["ready_for_full_retrain"] = (
        not out["issues"]
        and bool(out["cells"])
        and all(c.get("parity_ok") for c in out["cells"])
    )
    SURVIVOR_VALIDATION_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SURVIVOR_VALIDATION_RUN_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def run_survivor_edge_probe(
    *,
    tickers: list[str] | None = None,
    min_mcc_edge: float = SURVIVOR_EDGE_MCC_MIN,
) -> dict:
    """Pre-retrain gate: summarize confirm-verified drops + holdout MCC edge per model×horizon."""
    from arch_competition.stack_bundle_eval_v1 import (
        ablation_full_matrix_cell_target,
        ablation_confirm_pass_complete,
        ablated_drop_members_for_model_horizon,
        confirmed_drop_group_ids_by_model_horizon,
        compound_survivors_voided,
        _authoritative_ablation_report_path,
        COMPOUND_ABLATION_VOID_REASON,
    )

    anchors = [ticker_storage_key(t) for t in (tickers or SURVIVOR_RETRAIN_DEFAULT_TICKERS) if str(t).strip()]  # RC-345/F25: anchor identity canonical, not local .upper()
    out: dict = {
        "schema_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "anchors": anchors,
        "horizons": list(REQUIRED_ABLATION_HORIZONS),
        "ready_for_full_retrain": False,
        "issues": [],
        "cells": [],
        "summary": {},
    }
    if compound_survivors_voided():
        out["issues"].append(f"compound_survivors_void:{COMPOUND_ABLATION_VOID_REASON}")
    report_path = _authoritative_ablation_report_path()
    if report_path is None:
        out["issues"].append("missing_authoritative_leaf_ablation_report")
        _write_survivor_edge_probe(out)
        return out
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ss = report.get("survivor_summary") or {}
    scored = int(ss.get("scored_cell_count") or 0)
    matrix_target = ablation_full_matrix_cell_target()
    if matrix_target <= 0 or scored < matrix_target:
        out["issues"].append(f"ablation_matrix_incomplete:{scored}/{matrix_target}")
    if not ablation_confirm_pass_complete(ss):
        out["issues"].append("confirm_pass_incomplete: run --ablation-confirm first")
    confirm_cells = ((ss.get("confirm_pass") or {}).get("cells") or []) if isinstance(
        ss.get("confirm_pass"), dict
    ) else []
    by_cell = confirmed_drop_group_ids_by_model_horizon(ss)
    mcc_by_amh: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for c in confirm_cells:
        if c.get("status") != "ok":
            continue
        key = (str(c.get("anchor_ticker")), str(c.get("model_family")), str(c.get("horizon_slug")))
        ch = c.get("mcc_change")
        if ch is not None:
            mcc_by_amh[key].append(float(ch))

    edge_cells = 0
    full_feature_cells = 0
    for model in ("xgb", "lstm", "transformer"):
        for hz in REQUIRED_ABLATION_HORIZONS:
            drop_groups = sorted(by_cell.get((model, hz), set()))
            try:
                xcols, m5, m1, conf = (
                    ablated_drop_members_for_model_horizon(model, hz) if drop_groups else ([], [], [], [])
                )
            except Exception as exc:
                out["issues"].append(f"drop_resolve_failed:{model}/{hz}:{exc}")
                xcols, m5, m1, conf = [], [], [], []
            mcc_vals: list[float] = []
            for anc in anchors:
                mcc_vals.extend(mcc_by_amh.get((anc, model, hz), []))
            med_mcc = round(statistics.median(mcc_vals), 6) if mcc_vals else None
            if not drop_groups:
                verdict = "FULL_FEATURE"
                full_feature_cells += 1
            elif med_mcc is None:
                verdict = "UNSCORED"
            elif med_mcc >= min_mcc_edge:
                verdict = "EDGE"
                edge_cells += 1
            elif med_mcc <= -min_mcc_edge:
                verdict = "RE_ABLATE"
            else:
                verdict = "NEUTRAL"
            out["cells"].append(
                {
                    "model_family": model,
                    "horizon_slug": hz,
                    "drop_group_count": len(drop_groups),
                    "drop_groups": drop_groups,
                    "xgb_engineered_cols": len(xcols),
                    "lstm_5m_members": len(m5),
                    "lstm_1m_members": len(m1),
                    "lstm_conf_members": len(conf),
                    "confirm_mcc_change_median": med_mcc,
                    "verdict": verdict,
                }
            )

    out["summary"] = {
        "edge_cells": edge_cells,
        "full_feature_cells": full_feature_cells,
        "total_cells": len(out["cells"]),
        "min_mcc_edge": min_mcc_edge,
    }
    out["ready_for_full_retrain"] = (
        not out["issues"]
        and edge_cells > 0
        and full_feature_cells < len(out["cells"])
    )
    if not out["issues"] and edge_cells == 0:
        out["issues"].append(
            "no_material_edge: no model×horizon cell with median mcc_change >= "
            f"{min_mcc_edge}; full retrain matches full-feature — re-ablate or skip"
        )
    _write_survivor_edge_probe(out)
    return out


def _write_survivor_edge_probe(payload: dict) -> Path:
    SURVIVOR_EDGE_PROBE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SURVIVOR_EDGE_PROBE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return SURVIVOR_EDGE_PROBE_PATH


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
    "ED_ABLATION_SCORING_PASS",
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
        got = {ticker_storage_key(t) for t in tickers_raw.split(",") if t.strip()}  # RC-345/F25: identity comparison uses canonical key
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

    anchors = [ticker_storage_key(t) for t in (tickers or SURVIVOR_RETRAIN_DEFAULT_TICKERS) if str(t).strip()]  # RC-345/F25: anchor identity canonical, not local .upper()
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
        from arch_competition.stack_bundle_eval_v1 import (
            ABLATION_CONFIRM_PATH_VERSION,
            ablation_confirm_pass_complete,
            ablation_primary_pass_authority_active,
        )
        from tools.check_ablation_pipeline_parity import check_ablation_pipeline_parity

        parity_errs = check_ablation_pipeline_parity()
        if parity_errs:
            out["ready"] = False
            out["issues"].extend(parity_errs)

        if not ablation_confirm_pass_complete() and not ablation_primary_pass_authority_active():
            out["ready"] = False
            from arch_competition.stack_bundle_eval_v1 import compound_survivors_voided

            if compound_survivors_voided():
                out["issues"].append(
                    "compound_ablation_survivors_void: re-ablate on "
                    "governance/artifacts/feature_ablation_manifest_leaf.json"
                )
            else:
                out["issues"].append(
                    f"ablation_confirm_pass_stale_or_incomplete: run "
                    f"python tools/feature_curation_gate.py --ablation-confirm "
                    f"(confirm_path_version must be {ABLATION_CONFIRM_PATH_VERSION!r}; "
                    "primary ablation matrix is unchanged — confirm pass only) "
                    "OR stamp primary authority: "
                    "python tools/feature_curation_gate.py --ablation-stamp-primary-authority"
                )
        elif ablation_primary_pass_authority_active() and not ablation_confirm_pass_complete():
            out["notes"].append(
                "survivor_mask_primary_pass_authority: per-model DROP_CANDIDATE from completed "
                "primary pass (confirm pass skipped; untrusted transformer/monte_carlo cells excluded)"
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


def build_survivor_retrain_monitor_report(
    *,
    tickers: list[str] | None = None,
) -> str:
    """Human-readable O-56 retrain status for periodic operator/agent monitoring."""
    from datetime import datetime, timezone

    from active_bundle_contract import check_active_bundle_complete, scheduler_active_root

    anchors = [ticker_storage_key(t) for t in (tickers or list(SURVIVOR_RETRAIN_DEFAULT_TICKERS)) if str(t).strip()]  # RC-345/F25: anchor identity canonical, not local .upper()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = ["=" * 72, f"SURVIVOR RETRAIN MONITOR  {ts}", "=" * 72]

    try:
        st = pipeline_status()
        abl = st.get("ablation") or {}
        procs = st.get("ml_train_processes") or []
        lines.append(
            "Ablation: complete=%s  cells=%s/%s  stack=%s/%s"
            % (
                abl.get("complete"),
                abl.get("per_model_feature_cells"),
                abl.get("per_model_feature_target"),
                abl.get("stack_authority_cells"),
                abl.get("stack_authority_target"),
            )
        )
        lines.append("ED_APPLY_ABLATION_SURVIVORS: %s" % st.get("ED_APPLY_ABLATION_SURVIVORS"))
        lines.append("ML processes: %d" % len(procs))
        for p in procs:
            lines.append("  PID %s  %s" % (p.get("pid"), (p.get("command") or "")[:120]))
        if not procs:
            lines.append("  (no ml_scheduler / train processes detected)")
    except Exception as e:
        lines.append("Pipeline status ERROR: %s" % e)

    rep_path = Path("models/training_report.jsonl")
    rows: list[dict] = []
    if rep_path.is_file():
        for raw in rep_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not raw.strip():
                continue
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    core = [r for r in rows if r.get("ticker") in anchors]
    lines.extend(["", "Recent training_report (last 10 core rows):"])
    lines.append(
        "%-22s %-5s %-4s %-8s %-12s %s"
        % ("timestamp", "tkr", "hz", "promoted", "outcome", "gate/skip")
    )
    for r in core[-10:]:
        ae = r.get("auto_promote_execution") or {}
        gate = ae.get("promotion_gate_reason") or ae.get("skipped_reason") or ""
        lines.append(
            "%-22s %-5s %-4s %-8s %-12s %s"
            % (
                str(r.get("timestamp", ""))[:22],
                r.get("ticker"),
                r.get("horizon"),
                str(r.get("promoted")),
                str(r.get("outcome", ""))[:12],
                str(gate)[:40],
            )
        )

    lines.extend(["", "7-file active bundle compliance:"])
    models = Path("models")
    for t in anchors:
        ok: list[str] = []
        bad: list[str] = []
        for hz in REQUIRED_ABLATION_HORIZONS:
            bd = scheduler_active_root(models, hz) / t
            chk = check_active_bundle_complete(t, hz, bundle_dir=bd)
            if chk.get("compliant"):
                ok.append(hz)
            else:
                iss = chk.get("issues") or []
                bad.append("%s(%s)" % (hz, iss[0][:30] if iss else "incomplete"))
        lines.append(
            "  %s  OK=[%s]  MISSING=%s" % (t, ",".join(ok) or "-", ",".join(bad) if bad else "none")
        )

    lines.extend(["", "Incumbent promotion_score:"])
    for t in anchors:
        for hz in REQUIRED_ABLATION_HORIZONS:
            _tc = ticker_storage_key(t)  # RC-345/F25: artifact-dir identity canonical
            mp = scheduler_active_root(models, hz) / _tc / f"xgb_{_tc}_{hz}_meta.json"
            if not mp.is_file():
                continue
            d = json.loads(mp.read_text(encoding="utf-8"))
            lines.append(
                "  %s/%s  score=%s  metric=%s"
                % (t, hz, d.get("promotion_score"), d.get("promotion_metric"))
            )
    lines.append("=" * 72)
    return "\n".join(lines)


def run_survivor_retrain_monitor_loop(
    *,
    tickers: list[str] | None = None,
    interval_min: float = 10.0,
    once: bool = False,
) -> None:
    import time

    interval = max(60.0, float(interval_min) * 60.0)
    while True:
        print(build_survivor_retrain_monitor_report(tickers=tickers), flush=True)
        if once:
            return
        time.sleep(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM",
                    help="Anchor ticker(s) for scored ablation (comma-separated). Default: SPY, QQQ, IWM.")
    ap.add_argument("--null-thresh", type=float, default=0.98)
    ap.add_argument("--cluster-thresh", type=float, default=0.20,
                    help="hierarchical distance (1-|rho|); 0.20 => |rho|>=0.80 clustered")
    ap.add_argument("--ablation", "--build-ablation-report", action="store_true",
                    help="Run scored 7-layer whole-stack fusion ablation (anchor×horizon×feature); "
                    "writes feature_ablation_report_leaf.json. O-56 per-model pass is opt-in.")
    ap.add_argument(
        "--ablation-include-o56",
        action="store_true",
        help="Also run O-56 per-model MCC pass (xgb/lstm/transformer only — placement discovery, "
        "NOT full-stack fusion). Default --ablation is whole-stack 7-layer only.",
    )
    ap.add_argument(
        "--ablation-include-stack-authority",
        action="store_true",
        help="Also run stack-authority mode-lift pass (meta/MC/regime/fusion lifts). "
        "Default --ablation is whole-stack feature knockout only.",
    )
    ap.add_argument("--ablation-dry-run", action="store_true",
                    help="Emit ablation grid from manifest without DB/model work")
    ap.add_argument("--ablation-preflight", action="store_true",
                    help="Verify DB + active bundles; exit 1 if not ready for scored ablation")
    ap.add_argument(
        "--ablation-audit",
        action="store_true",
        help="Static + runtime integrity audit: 2632-cell grid, no partial-ready (exit 1 on defect)",
    )
    ap.add_argument(
        "--ablation-integrity",
        action="store_true",
        help="Rebuild experiment_integrity skew trace from on-disk report (no rescoring); exit 1 on FAIL",
    )
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
    ap.add_argument(
        "--ablation-confirm-force-restart",
        action="store_true",
        help="Intentionally wipe partial confirm progress and re-run from scratch",
    )
    ap.add_argument(
        "--ablation-stamp-primary-authority",
        action="store_true",
        help="Stamp completed primary-pass DROP_CANDIDATE as production authority (no confirm rescoring)",
    )
    ap.add_argument(
        "--ablation-stamp-primary-force",
        action="store_true",
        help="Re-stamp primary authority even when confirm_drop_summary.primary_authority is already set",
    )
    ap.add_argument("--manifest-path", default=str(MANIFEST_PATH))
    ap.add_argument("--report-path", default=str(ABLATION_REPORT_PATH))
    ap.add_argument(
        "--stack-authority-rescore",
        action="store_true",
        help="Re-score stack authority (meta/MC/fusion lifts) after retrain; exit 1 if incomplete",
    )
    ap.add_argument(
        "--survivor-retrain-preflight",
        action="store_true",
        help="Fail-closed preflight for scheduled survivor retrain (DB, readiness, drop groups)",
    )
    ap.add_argument(
        "--survivor-edge-probe",
        action="store_true",
        help="Pre-retrain go/no-go: confirm drops + MCC edge matrix (writes survivor_edge_probe.json)",
    )
    ap.add_argument(
        "--survivor-inference-backtest",
        action="store_true",
        help="DEPRECATED: mask on models/active weights. Prefer --survivor-stack-refit-backtest.",
    )
    ap.add_argument(
        "--survivor-stack-refit-backtest",
        action="store_true",
        help="Refit full vs survivor on holdout; score multiclass log_loss per ML stack layer (writes survivor_stack_refit_backtest.json)",
    )
    ap.add_argument(
        "--void-compound-ablation",
        action="store_true",
        help="Retire compound-group survivor authority (writes ablation_survivor_status.json + VOID stamps)",
    )
    ap.add_argument(
        "--build-schwab-ablation-universe",
        action="store_true",
        help="Categorize all 2393 Schwab fields + write expanded ablation manifest (>=2x ML cone)",
    )
    ap.add_argument(
        "--expand-leaf-manifest",
        action="store_true",
        help="Alias for --build-schwab-ablation-universe (compound split retired)",
    )
    ap.add_argument(
        "--survivor-validation-run",
        action="store_true",
        help="Production-path quick holdout validation per EDGE cell (writes survivor_validation_run.json)",
    )
    ap.add_argument(
        "--survivor-edge-min-mcc",
        type=float,
        default=SURVIVOR_EDGE_MCC_MIN,
        help="Minimum median confirm mcc_change to count as EDGE (default 0.01)",
    )
    ap.add_argument(
        "--survivor-retrain-gate-env-check",
        action="store_true",
        help="Validate process env matches survivor retrain gate contract; exit 1 if not",
    )
    ap.add_argument(
        "--survivor-retrain-monitor",
        action="store_true",
        help="Print O-56 retrain monitor report (use --monitor-interval-min for loop)",
    )
    ap.add_argument(
        "--monitor-interval-min",
        type=float,
        default=10.0,
        help="Minutes between monitor reports when --survivor-retrain-monitor (default 10)",
    )
    ap.add_argument(
        "--monitor-once",
        action="store_true",
        help="Single monitor report then exit (with --survivor-retrain-monitor)",
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
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        pf = run_survivor_retrain_preflight(db_path=str(DB_PATH), tickers=tickers)
        print(json.dumps(pf, indent=2))
        raise SystemExit(0 if pf["ready"] else 1)

    if a.survivor_inference_backtest:
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        bt = run_survivor_inference_backtest(tickers=tickers, db_path=str(DB_PATH))
        print(json.dumps(bt, indent=2))
        raise SystemExit(0 if bt.get("ready") else 1)

    if a.survivor_stack_refit_backtest:
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        bt = run_survivor_stack_refit_backtest(tickers=tickers, db_path=str(DB_PATH))
        print(json.dumps(bt, indent=2))
        raise SystemExit(0 if bt.get("ready_for_production") else 1)

    if a.void_compound_ablation:
        from arch_competition.stack_bundle_eval_v1 import void_compound_ablation_survivors

        result = void_compound_ablation_survivors(write_artifacts=True)
        print(json.dumps(result, indent=2))
        raise SystemExit(0)

    if a.build_schwab_ablation_universe or a.expand_leaf_manifest:
        from tools.build_feature_assignment_matrix_v2 import (
            SCHWAB_ABLATION_REGISTRY_PATH,
            build_schwab_ablation_field_registry,
        )

        reg = build_schwab_ablation_field_registry(write=True)
        path = write_leaf_ablation_manifest()
        leaf = json.loads(path.read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "registry": str(SCHWAB_ABLATION_REGISTRY_PATH),
                    "written": str(path),
                    "schwab_field_count": reg["schwab_field_count"],
                    "tier_counts": reg["tier_counts"],
                    "group_count": len(leaf.get("groups") or []),
                    "totals": leaf.get("totals"),
                },
                indent=2,
            )
        )
        raise SystemExit(0)

    if a.survivor_edge_probe:
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        probe = run_survivor_edge_probe(tickers=tickers, min_mcc_edge=float(a.survivor_edge_min_mcc))
        print(json.dumps(probe, indent=2))
        raise SystemExit(0 if probe.get("ready_for_full_retrain") else 1)

    if a.survivor_validation_run:
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        val = run_survivor_validation_run(tickers=tickers)
        print(json.dumps(val, indent=2))
        raise SystemExit(0 if val.get("ready_for_full_retrain") else 1)

    if a.survivor_retrain_monitor:
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        run_survivor_retrain_monitor_loop(
            tickers=tickers or None,
            interval_min=float(a.monitor_interval_min),
            once=bool(a.monitor_once),
        )
        raise SystemExit(0)

    if a.stack_authority_rescore:
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        result = build_stack_authority_rescore_report(
            manifest_path=Path(a.manifest_path),
            report_path=Path(a.report_path),
            tickers=tickers,
        )
        print(json.dumps({k: result[k] for k in ("ready", "issues", "cells", "report_path")}, indent=2))
        raise SystemExit(0 if result["ready"] else 1)

    if a.ablation_integrity:
        report_path = Path(a.report_path)
        integrity = audit_ablation_experiment_integrity(report_path)
        print(format_ablation_integrity_report(integrity))
        print(json.dumps(integrity, indent=2))
        raise SystemExit(0 if integrity.get("verdict") in ("PASS", "INVESTIGATE") else 1)

    if a.ablation_audit:
        from tools.ablation_integrity import run_ablation_integrity_audit

        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        result = run_ablation_integrity_audit(
            db_path=str(DB_PATH),
            tickers=tickers or None,
            runtime=True,
        )
        summary = {
            "audit": result.get("audit"),
            "ok": result.get("ok"),
            "static_ok": result.get("static_ok"),
            "static_errors": result.get("static_errors"),
            "runtime_ok": result.get("runtime_ok"),
            "whole_stack_cell_target": result.get("whole_stack_cell_target"),
            "db_path": result.get("db_path"),
            "runtime_skip": result.get("runtime_skip"),
        }
        pf = result.get("preflight") or {}
        if pf:
            summary["preflight"] = {
                "ready": pf.get("ready"),
                "ready_for_whole_stack": pf.get("ready_for_whole_stack"),
                "issues": pf.get("issues"),
                "notes": pf.get("notes"),
                "anchors": pf.get("anchors"),
                "horizons": pf.get("horizons"),
            }
        print(json.dumps(summary, indent=2))
        raise SystemExit(0 if result.get("ok") else 1)

    if a.ablation_preflight:
        manifest = load_ablation_manifest(Path(a.manifest_path))
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        pf = run_ablation_preflight(manifest, db_path=str(DB_PATH), tickers=tickers)
        print(json.dumps(pf, indent=2))
        raise SystemExit(0 if pf["ready"] else 1)

    if a.ablation_confirm:
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
        report_path = Path(a.report_path)
        manifest = load_ablation_manifest(Path(a.manifest_path))
        pf = run_ablation_preflight(manifest, db_path=str(DB_PATH), tickers=tickers)
        if not pf["ready"]:
            print(json.dumps(pf, indent=2))
            raise SystemExit("confirm preflight failed")
        guard_ablation_confirm_fresh_start(
            report_path,
            resume=bool(a.ablation_confirm_resume),
            force_restart=bool(a.ablation_confirm_force_restart),
        )
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
            f"safe={summary.get('cells_safe_to_drop', 0)}",
            flush=True,
        )
        raise SystemExit(0)

    if a.ablation_stamp_primary_authority:
        report = stamp_primary_ablation_authority(
            Path(a.report_path),
            force=bool(a.ablation_stamp_primary_force),
        )
        summary = report.get("confirm_drop_summary") or {}
        print(json.dumps(summary, indent=2))
        raise SystemExit(0)

    if a.ablation or a.ablation_dry_run:
        tickers = [ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()]  # RC-345/F25: CLI ticker list canonical
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
            tickers=tickers or None,
            resume=bool(a.ablation_resume and not a.ablation_dry_run),
            report_path=report_path,
            include_o56=bool(a.ablation_include_o56),
            include_stack_authority=bool(a.ablation_include_stack_authority),
        )
        out_p = write_ablation_report(report, report_path)
        method = report["ablation_method"]
        meta = report.get("run_meta") or {}
        surv = report.get("survivor_summary") or {}
        pool = report.get("stage3_pool_tickers") or method.get("pool_tickers") or method.get("anchors")
        print(
            f"wrote {out_p}  whole_stack_feature_cells={report.get('whole_stack_feature_cell_count')}  "
            f"whole_stack_ok={meta.get('whole_stack_ok')}  "
            f"include_o56={meta.get('include_o56')}  "
            f"horizons={method['horizons']}  "
            f"pool_tickers={pool}  "
            f"full_stack_layers={report.get('full_stack_layers')}  "
            f"dry_run={report.get('dry_run', False)}  "
            f"status={meta.get('status')}  "
            f"survivor_groups={len(surv.get('by_group') or surv.get('groups') or {})}"
        )
        return

    out = run([ticker_storage_key(t) for t in a.tickers.split(",") if t.strip()], a.null_thresh, a.cluster_thresh)  # RC-345/F25: CLI ticker list canonical
    c = out["counts"]
    print(f"rows={out['rows_analyzed']}  registered={c['registered_candidates']}")
    print(f"DEAD missing-col={c['missing_columns_DEAD']}  near-null={c['near_null_DEAD']}")
    print(f"clusters={c['clusters']}  redundant-dropped={c['redundant_dropped']}")
    print(f"CLEAN CANDIDATE SET = {c['clean_candidate_set']} (from {c['registered_candidates']})")
    print(f"leakage-class EXCLUDED: {out['leakage_class_EXCLUDED']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
