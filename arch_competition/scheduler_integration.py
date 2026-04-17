"""
Scheduler integration: persist evaluation manifests + promotion records; visibility helpers.

Does not copy artifacts to models/active/ or call run_base_models_once.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from arch_competition.eval_runner import (
    EVALUATION_MANIFEST_SCHEMA_VERSION,
    write_evaluation_manifest,
    run_architecture_pair_evaluation,
)
from arch_competition.exceptions import EvaluationLineageError, PromotionGovernanceError
from arch_competition.promotion_engine import (
    PROMOTION_RECORD_SCHEMA_VERSION,
    decide_promotion,
    write_promotion_record,
)

GOVERNED_ARCH_STATE_SCHEMA_VERSION = "1"

# Stable keys for arch_state["{ticker}"]["governed_competition"] (additive changes require version bump).
GOVERNED_ARCH_STATE_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "latest_evaluation_at",
        "latest_promotion_decision",
        "would_promote_challenger",
        "blocked_promotion_flags",
        "reason_codes",
        "rollback_demotion_ready",
        "incumbent_architecture",
        "challenger_architecture",
        "lineage",
        "manifest_paths",
        "auto_promote_to_active_enabled",
        "production_write_held",
        "per_horizon",
    }
)

EVALUATION_MANIFEST_FILENAME = "evaluation_manifest.json"
PROMOTION_DECISION_FILENAME = "promotion_decision.json"
ARCH_COMPETITION_SUMMARY_FILENAME = "arch_competition_summary.json"


def arch_competition_ticker_dir(model_dir: Path, ml_horizon_slug: str, ticker: str) -> Path:
    su = str(ml_horizon_slug).strip().lower()
    return model_dir / "arch_competition" / su / ticker.upper()


def evaluation_manifest_path(model_dir: Path, ml_horizon_slug: str, ticker: str) -> Path:
    return arch_competition_ticker_dir(model_dir, ml_horizon_slug, ticker) / EVALUATION_MANIFEST_FILENAME


def promotion_decision_path(model_dir: Path, ml_horizon_slug: str, ticker: str) -> Path:
    return arch_competition_ticker_dir(model_dir, ml_horizon_slug, ticker) / PROMOTION_DECISION_FILENAME


def arch_competition_summary_path(model_dir: Path, ml_horizon_slug: str) -> Path:
    su = str(ml_horizon_slug).strip().lower()
    return model_dir / "arch_competition" / su / ARCH_COMPETITION_SUMMARY_FILENAME


def scheduler_auto_promote_to_active_enabled() -> bool:
    """Always False: copying to models/active/ is only allowed via arch_competition.manual_control (explicit operator)."""
    return False


def run_governed_architecture_competition_pass(
    *,
    model_dir: Path,
    db_path: str,
    ticker: str,
    parallel_model_dir: Path,
    cascade_model_dir: Path,
    ml_horizon_slug: str,
    allowed_et_dates: Optional[set[str]] = None,
) -> dict[str, Any]:
    """
    Run evaluation runner + promotion engine; write manifest + promotion record under model_dir/arch_competition/.

    Raises:
        EvaluationLineageError, PromotionGovernanceError: fail-closed inputs.
    """
    hz = str(ml_horizon_slug).strip().lower()
    manifest = run_architecture_pair_evaluation(
        db_path=db_path,
        ticker=ticker,
        parallel_model_dir=parallel_model_dir,
        cascade_model_dir=cascade_model_dir,
        ml_horizon_slug=hz,
        allowed_et_dates=allowed_et_dates,
        require_manifest_lineage=True,
        expected_ml_horizon_suffix=hz,
    )
    if manifest.get("schema_version") != EVALUATION_MANIFEST_SCHEMA_VERSION:
        raise PromotionGovernanceError("evaluation manifest schema mismatch")

    record = decide_promotion(manifest, auto_promote=False)
    if record.get("schema_version") != PROMOTION_RECORD_SCHEMA_VERSION:
        raise PromotionGovernanceError("promotion record schema mismatch")

    ev_path = evaluation_manifest_path(model_dir, hz, ticker)
    pr_path = promotion_decision_path(model_dir, hz, ticker)
    write_evaluation_manifest(ev_path, manifest)
    write_promotion_record(pr_path, record)

    summary = build_arch_competition_summary_tick(
        ticker=ticker,
        ml_horizon_slug=hz,
        manifest=manifest,
        promotion_record=record,
        paths={"evaluation_manifest": str(ev_path.resolve()), "promotion_decision": str(pr_path.resolve())},
    )
    sum_path = arch_competition_summary_path(model_dir, hz)
    sum_path.parent.mkdir(parents=True, exist_ok=True)
    _merge_summary_file(sum_path, ticker, summary)

    return {
        "evaluation_manifest": manifest,
        "promotion_record": record,
        "paths": {
            "evaluation_manifest": str(ev_path.resolve()),
            "promotion_decision": str(pr_path.resolve()),
            "summary": str(sum_path.resolve()),
        },
    }


def build_arch_competition_summary_tick(
    *,
    ticker: str,
    ml_horizon_slug: str,
    manifest: dict[str, Any],
    promotion_record: dict[str, Any],
    paths: dict[str, str],
) -> dict[str, Any]:
    """Single-ticker summary fragment for merged summary file + arch_state."""
    lineage = manifest.get("lineage") or {}
    return {
        "ticker": ticker.upper(),
        "ml_horizon_suffix": ml_horizon_slug,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "incumbent_architecture": promotion_record.get("incumbent_architecture"),
        "challenger_architecture": promotion_record.get("challenger_architecture"),
        "latest_promotion_decision": promotion_record.get("promotion_decision"),
        "would_promote_challenger": promotion_record.get("would_promote_challenger"),
        "blocked_promotion_flags": promotion_record.get("blocked_promotion_flags"),
        "reason_codes": promotion_record.get("reason_codes"),
        "rollback_demotion_ready": promotion_record.get("rollback_demotion_ready"),
        "lineage_feature_cache_key": lineage.get("feature_cache_key"),
        "lineage_ml_horizon_suffix": lineage.get("ml_horizon_suffix"),
        "canonical_feature_contract_version": lineage.get("canonical_feature_contract_version"),
        "canonical_timeframe": lineage.get("canonical_timeframe"),
        "manifest_paths": paths,
        "evaluation_manifest_schema": manifest.get("schema_version"),
        "promotion_record_schema": promotion_record.get("schema_version"),
        "n_rows_scored": (manifest.get("metrics") or {}).get("parallel", {}).get("n_rows_scored"),
    }


def build_governed_arch_state_slice(
    *,
    manifest: dict[str, Any],
    promotion_record: dict[str, Any],
    paths: dict[str, str],
    auto_promote_to_active: bool,
) -> dict[str, Any]:
    """Stable schema persisted under each ticker in arch_state.json (per horizon file)."""
    lineage = manifest.get("lineage") or {}
    out = {
        "schema_version": GOVERNED_ARCH_STATE_SCHEMA_VERSION,
        "latest_evaluation_at": manifest.get("created_at_utc"),
        "latest_promotion_decision": promotion_record.get("promotion_decision"),
        "would_promote_challenger": promotion_record.get("would_promote_challenger"),
        "blocked_promotion_flags": promotion_record.get("blocked_promotion_flags"),
        "reason_codes": promotion_record.get("reason_codes"),
        "rollback_demotion_ready": promotion_record.get("rollback_demotion_ready"),
        "incumbent_architecture": promotion_record.get("incumbent_architecture"),
        "challenger_architecture": promotion_record.get("challenger_architecture"),
        "lineage": {
            "feature_cache_key": lineage.get("feature_cache_key"),
            "data_fingerprint": lineage.get("data_fingerprint"),
            "ml_horizon_suffix": lineage.get("ml_horizon_suffix"),
            "training_code_fingerprint": lineage.get("training_code_fingerprint"),
            "canonical_feature_contract_version": lineage.get("canonical_feature_contract_version"),
            "canonical_timeframe": lineage.get("canonical_timeframe"),
        },
        "manifest_paths": {
            "evaluation_manifest": paths.get("evaluation_manifest"),
            "promotion_decision": paths.get("promotion_decision"),
        },
        "auto_promote_to_active_enabled": bool(auto_promote_to_active),
        "production_write_held": not bool(auto_promote_to_active),
        "per_horizon": {
            str(manifest.get("ml_horizon_slug") or ""): {
                "target_column": manifest.get("target_column"),
                "architecture_comparison_summary": manifest.get("architecture_comparison_summary"),
            }
        },
    }
    missing = GOVERNED_ARCH_STATE_REQUIRED_KEYS - out.keys()
    if missing:
        raise PromotionGovernanceError(f"governed arch_state slice missing keys {sorted(missing)}")
    return out


def _merge_summary_file(path: Path, ticker: str, tick_summary: dict[str, Any]) -> None:
    prev: dict[str, Any] = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    tickers = prev.get("tickers") if isinstance(prev.get("tickers"), dict) else {}
    tickers[ticker.upper()] = tick_summary
    out = {
        "schema_version": "1",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tickers": tickers,
    }
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")


def load_architecture_competition_visibility(
    model_dir: Path,
    ml_horizon_slug: str,
    *,
    ticker: Optional[str] = None,
) -> dict[str, Any]:
    """
    UI/diagnostics: current production default (parallel), challenger status, last comparison, paths.

    Fail-closed: raises FileNotFoundError / PromotionGovernanceError if required files missing (optional strict).
    """
    hz = str(ml_horizon_slug).strip().lower()
    arch_path = (
        model_dir / "arch_state.json"
        if hz == "1c"
        else model_dir / f"arch_state_{hz}.json"
    )
    active = "parallel"
    state: dict[str, Any] = {}
    if arch_path.exists():
        try:
            state = json.loads(arch_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    summary_path = arch_competition_summary_path(model_dir, hz)
    summary_blob: dict[str, Any] = {}
    if summary_path.exists():
        try:
            summary_blob = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary_blob = {}

    tickers_summary = summary_blob.get("tickers") if isinstance(summary_blob.get("tickers"), dict) else {}
    if ticker:
        tku = ticker.upper()
        ts = tickers_summary.get(tku)
        gv = (state.get(tku) or {}).get("governed_competition") if isinstance(state.get(tku), dict) else None
        return {
            "ml_horizon_suffix": hz,
            "production_default_runtime": "parallel",
            "active_architecture_in_state": (state.get(tku) or {}).get("active_architecture"),
            "governed_competition": gv,
            "last_comparison": ts,
            "manifest_paths": (ts or {}).get("manifest_paths"),
            "blocked_reasons": (ts or {}).get("blocked_promotion_flags") or (gv or {}).get("blocked_promotion_flags"),
            "reason_codes": (ts or {}).get("reason_codes"),
        }

    return {
        "ml_horizon_suffix": hz,
        "production_default_runtime": "parallel",
        "arch_state_path": str(arch_path.resolve()),
        "summary_path": str(summary_path.resolve()) if summary_path.exists() else None,
        "tickers": list(tickers_summary.keys()),
    }


def validate_persisted_governed_artifacts_or_raise(
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
) -> None:
    """Fail-closed loader guard: both files must exist and match schema versions."""
    ev = evaluation_manifest_path(model_dir, ml_horizon_slug, ticker)
    pr = promotion_decision_path(model_dir, ml_horizon_slug, ticker)
    if not ev.is_file():
        raise PromotionGovernanceError(f"missing evaluation manifest: {ev}")
    if not pr.is_file():
        raise PromotionGovernanceError(f"missing promotion decision: {pr}")
    try:
        mj = json.loads(ev.read_text(encoding="utf-8"))
        pj = json.loads(pr.read_text(encoding="utf-8"))
    except Exception as e:
        raise PromotionGovernanceError(f"invalid JSON in governed artifacts: {e}") from e
    if mj.get("schema_version") != EVALUATION_MANIFEST_SCHEMA_VERSION:
        raise PromotionGovernanceError("evaluation manifest schema mismatch")
    if pj.get("schema_version") != PROMOTION_RECORD_SCHEMA_VERSION:
        raise PromotionGovernanceError("promotion record schema mismatch")


def assert_no_active_directory_write(scheduler_fn: str = "ml_scheduler.run_once") -> None:
    """Test hook: scheduler must not copy to models/active/ (use manual_control for promotion)."""
    if scheduler_auto_promote_to_active_enabled():
        raise PromotionGovernanceError(f"{scheduler_fn}: scheduler must not auto-copy to active/")
