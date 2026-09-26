"""
Offline stack bundle evaluation (Issue: authority / XGB vs full stack / MC / Fusion).

Reuses:
- ml_scheduler._load_rth_rows_for_ticker — chronological RTH rows, causal inference_snapshot.
- ml_predict.run_unified_stack_ml_once — production-parallel unified stack ML layers + meta combiner.
- signals._run_model_stack — adds Monte Carlo as one team (no solo-green when team blocked).
- bayesian_fusion.fuse — posterior directional triplet.

Primary promotion metric (aligned with arch_competition.promotion_engine): multiclass log_loss (lower better).
Secondary: balanced_accuracy, macro_f1, calibration ECE (top-class bins), Brier (multiclass from metrics.py).

No naive random split: rows are ts_utc ascending from DB (same contract as ml_scheduler eval).
"""

from __future__ import annotations

# RC-345/F25: bundle-eval artifact/model identity consumes the ONE canonical ticker authority
# so eval lookups resolve to the same artifact the writers/promotion/readers produced.
from instrument_identity import ticker_storage_key

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from ml_horizon import normalize_ml_horizon_slug

log = logging.getLogger(__name__)






































def group_snapshot_columns(group: dict, enriched_rows: list[dict] | None = None) -> list[str]:
    """Union of knockout columns for one atomic feature — fidelity-first, not registry-partitioned."""
    from tools.feature_curation_gate import (
        _whole_stack_knockout_columns,
    )

    return _whole_stack_knockout_columns(group, enriched_rows)










def ablation_full_matrix_cell_target() -> int:
    from tools.feature_curation_gate import load_ablation_manifest, whole_stack_fusion_cell_target

    manifest = load_ablation_manifest(ABLATION_LEAF_MANIFEST_PATH)
    return whole_stack_fusion_cell_target(manifest)

# Never null these raw snapshot keys — required for labels, joins, pct math, sequence encode.
ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS: frozenset[str] = frozenset(
    {
        "spot",
        "ticker",
        "timeframe",
        "ts_utc",
        "ts_et",
        "et_hour",
        "et_minute",
        "outcome_1c",
        "outcome_5c",
        "outcome_15c",
        "outcome_60c",
        "outcome_filled",
    }
)

ABLATION_SURVIVORS_ENV = "ED_APPLY_ABLATION_SURVIVORS"
ABLATION_DROP_GROUPS_ENV = "ED_ABLATION_DROP_GROUPS"
ABLATION_LEAF_MANIFEST_PATH = Path("reports/artifacts/feature_ablation_manifest_leaf.json")
LEGACY_COMPOUND_REPORT_PATH = Path("reports/artifacts/feature_ablation_report.json")
ABLATION_LEAF_REPORT_PATH = Path("reports/artifacts/feature_ablation_report_leaf.json")
ABLATION_SURVIVOR_STATUS_PATH = Path("reports/artifacts/ablation_survivor_status.json")
ABLATION_LEAF_FEATURE_GRAIN = "schwab_expanded_atomic"
ABLATION_AUTHORITATIVE_GRAINS = frozenset(
    {"atomic_leaf_or_derived_column", "schwab_expanded_atomic"}
)
COMPOUND_ABLATION_VOID_REASON = "compound_workbook_groups_retired_use_leaf_manifest"
# Bump when confirm holdout transform order changes; preflight blocks until --ablation-confirm re-run.
ABLATION_CONFIRM_PATH_VERSION = "2"
# Operator may bind production to completed primary-pass DROP_CANDIDATE when confirm was not run.
ABLATION_PRIMARY_AUTHORITY_ENV = "ED_ABLATION_PRIMARY_AUTHORITY"
# Primary-pass cells with known scoring-path anomalies — excluded from production placement masks.
PRIMARY_SCORING_UNTRUSTED_CELLS: frozenset[tuple[str, str]] = frozenset(
    {
        ("transformer", "15c"),
        ("monte_carlo", "15c"),
        ("transformer", "1c"),
        ("transformer", "5c"),
    }
)

# Offline ablation lineage — fail-closed; never relaxes production loaders.
ABLATION_SCORING_PASS_ENV = "ED_ABLATION_SCORING_PASS"
# Pre-train observe experiment: live cards score from candidate bundles + survivor masks (not strict active).
LIVE_ABLATION_EXPERIMENT_ENV = "ED_LIVE_ABLATION_EXPERIMENT"


def ablation_scoring_pass_active() -> bool:
    """True during offline ablation scoring passes (disables survivor-mask application only)."""
    import os

    return os.environ.get(ABLATION_SCORING_PASS_ENV, "").strip().lower() in ("1", "true", "yes")


def live_ablation_experiment_active() -> bool:
    """True when operator runs pre-train card observe from ablation survivors (ACTIVE_PROGRAM experiment lane)."""
    import os

    return os.environ.get(LIVE_ABLATION_EXPERIMENT_ENV, "").strip().lower() in ("1", "true", "yes")


def unified_stack_bundle_relaxation_active() -> bool:
    """Offline ablation scoring OR live pre-train experiment — not strict models/active promotion gate."""
    return ablation_scoring_pass_active() or live_ablation_experiment_active()


def ablation_experiment_serve_masks_active() -> bool:
    """Apply per-(model, horizon) survivor nulls on live serve (observe experiment or post-confirm train)."""
    if ablation_scoring_pass_active():
        return False
    return live_ablation_experiment_active() or ablation_survivors_training_enabled()


def bundle_dir_has_unified_stack_artifacts(bundle_dir: Path, ticker: str, hz: str) -> bool:
    """Minimum xgb+lstm+transformer artifacts for unified seven-layer stack scoring."""
    t = ticker_storage_key(ticker)  # RC-345/F25
    su = normalize_ml_horizon_slug(hz)
    names = (
        f"xgb_{t}_{su}.pkl",
        f"lstm_{t}_{su}.pt",
        f"transformer_{t}_{su}.pt",
    )
    return all((bundle_dir / n).is_file() for n in names)


def resolve_experiment_bundle_dir(ticker: str, hz: str, *, models_dir: Path) -> Path:
    """Pre-train observe path: models/parallel/{ticker} before scheduler promotion to models/active/."""
    t = ticker_storage_key(ticker)  # RC-345/F25
    su = normalize_ml_horizon_slug(hz)
    parallel = models_dir / "parallel" / t
    if bundle_dir_has_unified_stack_artifacts(parallel, t, su):
        return parallel
    from active_bundle_contract import active_bundle_dir

    active = active_bundle_dir(t, su, models_dir=models_dir)
    if bundle_dir_has_unified_stack_artifacts(active, t, su):
        return active
    raise FileNotFoundError(
        f"{LIVE_ABLATION_EXPERIMENT_ENV}=1: no unified-stack candidate bundle for {t} hz={su} "
        f"(need xgb+lstm+transformer under models/parallel/{t} or canonical active root)"
    )








def ablation_manifest_feature_grain(manifest: dict) -> str:
    return str((manifest.get("ablation_method") or {}).get("feature_grain") or "compound_workbook_group")


def _read_json_path(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def report_survivor_authority_voided(report: dict) -> bool:
    """True when this specific report must not drive survivor drops."""
    auth = report.get("survivor_authority") or {}
    if str(auth.get("status") or "").upper() == "VOID":
        return True
    grain = str((report.get("ablation_method") or {}).get("feature_grain") or "")
    if grain == ABLATION_LEAF_FEATURE_GRAIN or grain in ABLATION_AUTHORITATIVE_GRAINS:
        return False
    return True


def compound_survivors_voided() -> bool:
    """True when compound-workbook survivor drops are retired (leaf manifest required)."""
    status = _read_json_path(ABLATION_SURVIVOR_STATUS_PATH)
    if status and str(status.get("compound_survivors") or "").upper() == "VOID":
        return True
    legacy = _read_json_path(LEGACY_COMPOUND_REPORT_PATH)
    if legacy is None:
        return False
    return report_survivor_authority_voided(legacy)






def _authoritative_ablation_report_path() -> Path | None:
    """Leaf-grain report only; compound workbook report is never authoritative for drops."""
    leaf = _read_json_path(ABLATION_LEAF_REPORT_PATH)
    if leaf is not None and not report_survivor_authority_voided(leaf):
        return ABLATION_LEAF_REPORT_PATH
    return None


def _authoritative_ablation_manifest_path() -> Path:
    if not ABLATION_LEAF_MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            f"missing authoritative ablation manifest: {ABLATION_LEAF_MANIFEST_PATH} "
            f"(legacy compound manifest is not admissible)"
        )
    return ABLATION_LEAF_MANIFEST_PATH


def ablation_survivors_training_enabled() -> bool:
    import os

    # Ablation primary/confirm passes score on the FULL feature set — never apply survivor
    # drops while measuring MCC delta or drop-and-refit (chicken-and-egg with confirm pass).
    if ablation_scoring_pass_active():
        return False
    return os.environ.get(ABLATION_SURVIVORS_ENV, "").strip().lower() in ("1", "true", "yes")


def ablation_confirm_pass_complete(
    survivor_summary: dict | None = None,
    *,
    require_current_path: bool = True,
) -> bool:
    """True when survivor_summary.confirm_pass is populated and matches the current confirm path."""
    if survivor_summary is None:
        report_path = _authoritative_ablation_report_path()
        if report_path is None:
            return False
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return False
        survivor_summary = report.get("survivor_summary") or {}
    confirm = survivor_summary.get("confirm_pass")
    if not isinstance(confirm, dict) or not confirm.get("cells"):
        return False
    if require_current_path:
        return confirm.get("confirm_path_version") == ABLATION_CONFIRM_PATH_VERSION
    return True


def primary_scoring_cell_untrusted(model_family: str, horizon_slug: str) -> bool:
    return (
        str(model_family).strip().lower(),
        str(horizon_slug).strip().lower(),
    ) in PRIMARY_SCORING_UNTRUSTED_CELLS


def _primary_matrix_complete(survivor_summary: dict) -> bool:
    scored = int(survivor_summary.get("scored_cell_count") or 0)
    matrix_target = ablation_full_matrix_cell_target()
    return matrix_target > 0 and scored >= matrix_target


def _report_primary_authority_stamped(report: dict) -> bool:
    summary = report.get("confirm_drop_summary") or {}
    ss = report.get("survivor_summary") or {}
    return bool(
        summary.get("primary_authority")
        or ss.get("primary_pass_authority")
        or summary.get("authority") == "primary_pass"
    )


def ablation_primary_pass_authority_active(
    survivor_summary: dict | None = None,
    *,
    report: dict | None = None,
) -> bool:
    """Use completed primary-pass DROP_CANDIDATE as production authority when confirm was not run."""
    import os

    if ablation_confirm_pass_complete(survivor_summary):
        return False
    if report is None:
        report_path = _authoritative_ablation_report_path()
        if report_path is not None:
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError):
                report = None
    if survivor_summary is None:
        survivor_summary = (report or {}).get("survivor_summary") or {}
    if not _primary_matrix_complete(survivor_summary):
        return False
    if report and _report_primary_authority_stamped(report):
        return True
    if survivor_summary.get("primary_pass_authority"):
        return True
    if os.environ.get(ABLATION_PRIMARY_AUTHORITY_ENV, "").strip().lower() in ("1", "true", "yes"):
        return True
    if live_ablation_experiment_active():
        return True
    return False


def primary_drop_group_ids_by_model_horizon(
    survivor_summary: dict,
) -> dict[tuple[str, str], set[str]]:
    """DROP_CANDIDATE groups per (model, horizon) from the primary rollup (trusted cells only)."""
    out: dict[tuple[str, str], set[str]] = {}
    for model, by_hz in (survivor_summary.get("by_model_horizon") or {}).items():
        mf = str(model)
        for hz, rows in (by_hz or {}).items():
            if primary_scoring_cell_untrusted(mf, str(hz)):
                continue
            drops = {
                str(r["group_id"])
                for r in rows
                if r.get("recommendation") == "DROP_CANDIDATE" and r.get("group_id")
            }
            if drops:
                out[(mf, str(hz))] = drops
    return out


def globally_safe_drop_group_ids_from_primary(survivor_summary: dict) -> list[str]:
    by_cell = primary_drop_group_ids_by_model_horizon(survivor_summary)
    if not by_cell:
        return []
    return sorted(set.intersection(*by_cell.values()))


def effective_drop_group_ids_by_model_horizon(
    survivor_summary: dict,
) -> dict[tuple[str, str], set[str]]:
    if ablation_confirm_pass_complete(survivor_summary):
        return confirmed_drop_group_ids_by_model_horizon(survivor_summary)
    if ablation_primary_pass_authority_active(survivor_summary):
        return primary_drop_group_ids_by_model_horizon(survivor_summary)
    return {}


def confirmed_drop_group_ids_by_model_horizon(
    survivor_summary: dict,
) -> dict[tuple[str, str], set[str]]:
    """O-56-faithful per-cell drop sets: {(model_family, horizon_slug): {group_id, ...}}.

    A group is included for a cell ONLY when the confirm pass (drop-and-refit) verified it
    ``safe_to_drop`` for that cell on EVERY anchor. The primary pass's DROP_CANDIDATE
    recommendation is a screen, not a verified drop — never sufficient on its own.

    Confirm cells carry ``dropped_groups`` (batched DROP set per anchor); legacy ``group_id`` /
    ``group_ids`` are also accepted.
    """
    from collections import defaultdict

    out: dict[tuple[str, str], set[str]] = {}
    confirm = survivor_summary.get("confirm_pass")
    if not isinstance(confirm, dict):  # live report carries a status string until the pass runs
        return out
    cells = [c for c in (confirm.get("cells") or []) if c.get("status") == "ok"]
    by_mh: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for cell in cells:
        key = (str(cell.get("model_family")), str(cell.get("horizon_slug")))
        by_mh[key].append(cell)

    anchors_required = int(confirm.get("anchors_required") or 0)
    for key, group in by_mh.items():
        safe = [c for c in group if c.get("safe_to_drop")]
        need = anchors_required if anchors_required > 0 else len(group)
        if len(safe) < need:
            continue
        batch_sets: list[set[str]] = []
        for c in safe:
            dg: list[str] = list(c.get("dropped_groups") or [])
            if c.get("group_id"):
                dg.append(str(c["group_id"]))
            if c.get("group_ids"):
                dg.extend(str(g) for g in c["group_ids"])
            batch_sets.append({str(g) for g in dg if g})
        if not batch_sets:
            continue
        intersection = set.intersection(*batch_sets)
        if intersection:
            out[key] = intersection
    return out


def globally_safe_drop_group_ids(survivor_summary: dict) -> list[str]:
    """Groups safe to null in the SHARED snapshot: the INTERSECTION of confirm-verified per-cell
    drops across every cell. A group survives the mask if ANY (model, horizon) still needs it."""
    by_cell = confirmed_drop_group_ids_by_model_horizon(survivor_summary)
    if not by_cell:
        return []
    return sorted(set.intersection(*by_cell.values()))


def resolve_ablation_drop_group_ids() -> list[str]:
    """Feature groups to null in the SHARED snapshot/dataframe when ED_APPLY_ABLATION_SURVIVORS=1.

    The snapshot is the ONE shared input to every model (XGB tabular + LSTM/Transformer channels),
    so this mask is necessarily GLOBAL: a group is only safe to drop here when it is a confirm-
    verified non-survivor for EVERY (model, horizon) cell (the intersection). True per-model ×
    horizon survivor sets (O-56) are applied at each model's feature assembly via
    confirmed_drop_group_ids_by_model_horizon(), NOT by destroying shared snapshot columns.

    Fail-closed: returns [] (train/serve on the FULL feature set) unless there is an explicit
    ED_ABLATION_DROP_GROUPS override, OR a COMPLETE primary matrix (>= ABLATION_FULL_MATRIX_CELL_TARGET
    scored cells) WITH a populated confirm pass yielding a globally-safe intersection. The primary-
    pass MCC-delta screen alone never deletes features from the money path; there is no fabricated
    default drop set.
    """
    import os

    if not ablation_survivors_training_enabled():
        return []
    override = (os.environ.get(ABLATION_DROP_GROUPS_ENV) or "").strip()
    if override:
        return sorted({g.strip() for g in override.split(",") if g.strip()})
    report_path = _authoritative_ablation_report_path()
    if report_path is None:
        if compound_survivors_voided():
            log.warning(
                "ablation survivor mask: compound-group survivors VOID; fail-closed (full feature set). "
                "Re-ablate on %s.",
                ABLATION_LEAF_MANIFEST_PATH,
            )
        else:
            log.warning(
                "ablation survivor mask ON but no authoritative leaf report; fail-closed (full feature set)."
            )
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        log.warning("ablation survivor mask: report unreadable (%s); fail-closed.", e)
        return []
    ss = report.get("survivor_summary") or {}
    scored = int(ss.get("scored_cell_count") or 0)
    matrix_target = ablation_full_matrix_cell_target()
    if matrix_target <= 0 or scored < matrix_target:
        log.warning(
            "ablation survivor mask: primary matrix incomplete (%d/%d scored); fail-closed.",
            scored, matrix_target,
        )
        return []
    if ablation_confirm_pass_complete(ss):
        drop_ids = globally_safe_drop_group_ids(ss)
        if not drop_ids:
            log.warning(
                "ablation survivor mask: no confirm-verified globally-safe drops (run --ablation-confirm; "
                "per-model survivors apply at feature assembly, not the shared snapshot); "
                "fail-closed (full feature set)."
            )
        return drop_ids
    if ablation_primary_pass_authority_active(ss, report=report):
        drop_ids = globally_safe_drop_group_ids_from_primary(ss)
        if not drop_ids:
            log.warning(
                "ablation survivor mask: primary-pass authority active but no globally-safe "
                "intersection across trusted cells; per-model drops still apply at feature assembly."
            )
        return drop_ids
    log.warning(
        "ablation survivor mask: confirm incomplete and primary authority not active "
        "(stamp with --ablation-stamp-primary-authority or set ED_LIVE_ABLATION_EXPERIMENT=1); "
        "fail-closed (full feature set)."
    )
    return []






# Categoricals with locked MVP vocabulary — must null to None/NA, not generic "neutral".
ABLATION_MVP_LOCKED_CATEGORICAL_COLUMNS: frozenset[str] = frozenset(
    {"zone", "prev_zone", "vwap_side"}
)


def ablation_null_value_for_snapshot_column(col: str, *, for_pandas: bool = False):
    """Null-out value for one dropped snapshot column (train + ablation confirm pass)."""
    from ml_train import CATEGORICALS

    if col in ABLATION_MVP_LOCKED_CATEGORICAL_COLUMNS:
        if for_pandas:
            import pandas as pd

            return pd.NA
        return None
    if col in CATEGORICALS:
        return "neutral"
    if for_pandas:
        import pandas as pd

        return pd.NA
    return None




def ablation_survivors_fingerprint_part() -> str:
    """Cache-key fragment when survivor mask is on (global + per-model×horizon confirm drops)."""
    if not ablation_survivors_training_enabled():
        return "ablation_survivors=off"
    global_part = ",".join(resolve_ablation_drop_group_ids())
    per_model_part = "unavailable"
    try:
        report_path = _authoritative_ablation_report_path()
        if report_path is not None:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            ss_fp = report.get("survivor_summary") or {}
            by_cell = effective_drop_group_ids_by_model_horizon(ss_fp)
            per_model_part = "|".join(
                f"{m}/{h}:{','.join(sorted(g))}" for (m, h), g in sorted(by_cell.items())
            )
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return f"ablation_survivors=on|global={global_part}|per_model={per_model_part}"






# ─────────────────────────────────────────────────────────────────────────────
# O-56 PER-MODEL × HORIZON survivor application (the ablated-training path).
# Each xgb/lstm/transformer layer trains on ITS OWN survivor set for the horizon being trained — this is what
# "train on the ablated data" means. Full-feature training is NOT a valid retrain target when an
# ablation matrix exists (AGENTS §Ablation contract). These resolvers FAIL LOUD (raise) when
# survivors are enabled but the matrix is missing/incomplete — they never silently fall through to
# full features on a real retrain.
# ─────────────────────────────────────────────────────────────────────────────
class AblatedTrainingUnavailable(RuntimeError):
    """Survivors enabled for a retrain but the ablation matrix can't be applied — fail loud."""


def _load_ablation_report_or_raise() -> dict:
    if compound_survivors_voided() and _authoritative_ablation_report_path() is None:
        raise AblatedTrainingUnavailable(
            f"Compound-group ablation survivors are VOID ({COMPOUND_ABLATION_VOID_REASON}). "
            f"Re-ablate on {ABLATION_LEAF_MANIFEST_PATH} before enabling {ABLATION_SURVIVORS_ENV}."
        )
    report_path = _authoritative_ablation_report_path()
    if report_path is None:
        raise AblatedTrainingUnavailable(
            f"{ABLATION_SURVIVORS_ENV}=1 but no authoritative leaf ablation report; "
            f"run ablation on {ABLATION_LEAF_MANIFEST_PATH} first."
        )
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        raise AblatedTrainingUnavailable(f"ablation report unreadable: {e}") from e


def _load_ablation_manifest_or_raise() -> dict:
    manifest_path = _authoritative_ablation_manifest_path()
    if not manifest_path.is_file():
        raise AblatedTrainingUnavailable(f"ablation manifest missing at {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        raise AblatedTrainingUnavailable(f"ablation manifest unreadable: {e}") from e
    if ablation_manifest_feature_grain(manifest) not in ABLATION_AUTHORITATIVE_GRAINS:
        raise AblatedTrainingUnavailable(
            f"Manifest {manifest_path} grain {ablation_manifest_feature_grain(manifest)!r} is not "
            f"authoritative; require one of {sorted(ABLATION_AUTHORITATIVE_GRAINS)}."
        )
    return manifest


@lru_cache(maxsize=None)
def ablated_drop_group_ids_for_model_horizon(model_family: str, horizon_slug: str) -> list[str]:
    """The ablation's DROP set for one (model, horizon) cell (O-56). Requires confirm-verified

    Cached: the report/manifest are static within a training process, and this is called per-row by
    the sequence-model mask — without the cache it re-reads + re-parses the ~900KB report on every
    snapshot (catastrophic O(rows × file-parse)). Cache makes it one parse per (model, horizon).
    drops only; primary-pass DROP_CANDIDATE is never applied on the money path.
    Raises AblatedTrainingUnavailable if the matrix is missing/incomplete or confirm not run."""
    ss = _load_ablation_report_or_raise().get("survivor_summary") or {}
    scored = int(ss.get("scored_cell_count") or 0)
    matrix_target = ablation_full_matrix_cell_target()
    if matrix_target <= 0 or scored < matrix_target:
        raise AblatedTrainingUnavailable(
            f"ablation matrix incomplete ({scored}/{matrix_target} scored); "
            "cannot apply per-model survivors."
        )
    key = (str(model_family), str(horizon_slug))
    if primary_scoring_cell_untrusted(key[0], key[1]):
        return []
    if ablation_confirm_pass_complete(ss):
        confirmed = confirmed_drop_group_ids_by_model_horizon(ss)
        return sorted(confirmed.get(key, set()))
    if ablation_primary_pass_authority_active(ss):
        primary = primary_drop_group_ids_by_model_horizon(ss)
        return sorted(primary.get(key, set()))
    if live_ablation_experiment_active():
        return []
    raise AblatedTrainingUnavailable(
        "ED_APPLY_ABLATION_SURVIVORS=1 requires a completed --ablation-confirm pass "
        "or primary-pass authority (--ablation-stamp-primary-authority / "
        f"{ABLATION_PRIMARY_AUTHORITY_ENV}=1). Primary-pass DROP_CANDIDATE alone is not applied."
    )


@lru_cache(maxsize=None)
def ablated_drop_members_for_model_horizon(
    model_family: str, horizon_slug: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Resolve a cell's DROP groups to concrete members: (xgb_cols, lstm_5m, lstm_1m, lstm_conf)."""
    drop_ids = ablated_drop_group_ids_for_model_horizon(model_family, horizon_slug)
    if not drop_ids:
        return (), (), (), ()
    from tools.feature_curation_gate import _drop_members_for_model

    xgb, m5, m1, conf = _drop_members_for_model(_load_ablation_manifest_or_raise(), list(drop_ids))
    return tuple(xgb), tuple(m5), tuple(m1), tuple(conf)


@lru_cache(maxsize=None)
def ablation_drop_snapshot_columns_for_model_horizon(model_family: str, horizon_slug: str) -> tuple[str, ...]:
    """Raw snapshot columns to null for one (model, horizon) cell — the sequence-model survivor mask
    operates at the snapshot level (the encoder turns nulled columns into absence flags)."""
    drop_ids = ablated_drop_group_ids_for_model_horizon(model_family, horizon_slug)
    if not drop_ids:
        return ()
    manifest = _load_ablation_manifest_or_raise()
    by_id = {g["group_id"]: g for g in manifest.get("groups") or []}
    cols: set[str] = set()
    for gid in drop_ids:
        grp = by_id.get(gid)
        if grp:
            cols.update(group_snapshot_columns(grp))
    return tuple(sorted(c for c in cols if c not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS))


def apply_ablation_survivor_nulls_to_snapshot_for_model(snap, *, model_family: str, horizon_slug: str):
    """Per-row sequence-model survivor mask: null this (model, horizon) cell's dropped snapshot
    columns. No-op when survivors off. Fail-loud (raises) if the matrix can't be applied."""
    if (
        not ablation_experiment_serve_masks_active()
        and not ablation_survivors_training_enabled()
    ) or not isinstance(snap, dict):
        return snap
    cols = ablation_drop_snapshot_columns_for_model_horizon(model_family, horizon_slug)
    if not cols:
        return snap
    for col in cols:
        if col in snap:
            snap[col] = ablation_null_value_for_snapshot_column(col, for_pandas=False)
    return snap


def null_snapshot_dict_for_drop_groups(
    snap: dict,
    manifest: dict,
    drop_group_ids: list[str],
) -> dict:
    """Confirm-path snapshot nulling — does not require confirm_pass or survivors env."""
    if not drop_group_ids or not isinstance(snap, dict):
        return snap
    by_id = {g["group_id"]: g for g in (manifest.get("groups") or [])}
    cols: set[str] = set()
    for gid in drop_group_ids:
        grp = by_id.get(gid)
        if grp:
            cols.update(group_snapshot_columns(grp))
    out = dict(snap)
    for col in cols:
        if col in out and col not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS:
            out[col] = ablation_null_value_for_snapshot_column(col, for_pandas=False)
    return out




def drop_ablated_xgb_engineered_columns(
    X,
    feat_names: list[str],
    horizon_slug: str,
) -> tuple[Any, list[str], int]:
    """Remove confirm-verified XGB engineered columns after ``engineer_features`` (O-56).

    Production must match ``--ablation-confirm`` holdout refit, which drops engineered names
    post-engineer — not raw snapshot columns pre-engineer (many manifest xgb members are
    engineered-only and never appear on the raw training frame).
    """
    xcols, _, _, _ = ablated_drop_members_for_model_horizon("xgb", horizon_slug)
    drop_set = {c for c in xcols if c not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS}
    if not drop_set:
        return X, feat_names, 0
    keep = [f for f in feat_names if f not in drop_set]
    n_dropped = len(feat_names) - len(keep)
    if n_dropped == 0:
        return X, feat_names, 0
    return X[keep], keep, n_dropped


def apply_ablation_survivor_nulls_to_dataframe_for_model(df, *, model_family: str, horizon_slug: str):
    """Null raw snapshot columns for one (model, horizon) cell before feature engineering.

    XGB also drops engineered survivors in ``train_ticker`` via ``drop_ablated_xgb_engineered_columns``
    after ``engineer_features`` — matching the confirm-pass refit path."""
    if not ablation_survivors_training_enabled() or df is None or len(df) == 0:
        return df
    drop_ids = ablated_drop_group_ids_for_model_horizon(model_family, horizon_slug)
    if not drop_ids:
        return df
    manifest = _load_ablation_manifest_or_raise()
    by_id = {g["group_id"]: g for g in manifest.get("groups") or []}
    raw_cols: set[str] = set()
    for gid in drop_ids:
        grp = by_id.get(gid)
        if grp:
            raw_cols.update(group_snapshot_columns(grp))
    if model_family == "xgb":
        xcols, _, _, _ = ablated_drop_members_for_model_horizon("xgb", horizon_slug)
        for col in xcols:
            if col in df.columns:
                raw_cols.add(col)
    drop = sorted(
        c for c in raw_cols
        if c not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS and c in df.columns
    )
    if not drop:
        return df
    out = df.copy()
    for col in drop:
        out[col] = ablation_null_value_for_snapshot_column(col, for_pandas=True)
    return out


def zero_ablated_sequence_channels_for_model(
    X_5m: np.ndarray,
    X_1m: np.ndarray,
    mask_5m: np.ndarray,
    mask_1m: np.ndarray,
    *,
    model_family: str,
    horizon_slug: str,
    features_5m: list[str],
    features_1m: list[str],
    encoded_features_5m: list[str],
    encoded_features_1m: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Zero post-normalize LSTM/Transformer channels for confirm-verified drops (O-56).

    Matches ``--ablation-confirm`` holdout refit when groups carry lstm stream members; also
    zeros channels mapped from raw members present on the encoded streams."""
    from tools.feature_curation_gate import (
        _post_mask_channel_indices,
        _pre_mask_encoded_indices,
    )

    _, m5_raw, m1_raw, conf_raw = ablated_drop_members_for_model_horizon(model_family, horizon_slug)
    out5 = np.array(X_5m, copy=True)
    out1 = np.array(X_1m, copy=True)
    if m5_raw:
        ch5 = _post_mask_channel_indices(
            _pre_mask_encoded_indices(list(m5_raw), features_5m, encoded_features_5m),
            mask_5m,
        )
        for c in ch5:
            out5[:, :, c] = 0.0
    if m1_raw:
        ch1 = _post_mask_channel_indices(
            _pre_mask_encoded_indices(list(m1_raw), features_1m, encoded_features_1m),
            mask_1m,
        )
        for c in ch1:
            out1[:, :, c] = 0.0
    return out5, out1


def zero_ablated_lstm_conf_channels(
    X_conf: np.ndarray,
    *,
    model_family: str,
    horizon_slug: str,
) -> np.ndarray:
    """Zero post-normalize X_conf columns for confirm-verified cf_* drops (O-56)."""
    from tools.feature_curation_gate import _zero_conf_channels

    _, _, _, conf_raw = ablated_drop_members_for_model_horizon(model_family, horizon_slug)
    if not conf_raw:
        return X_conf
    out = np.array(X_conf, copy=True)
    _zero_conf_channels(out, list(conf_raw))
    return out




















