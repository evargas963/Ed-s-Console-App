"""Shared active-bundle completeness contract (G3-R1).

Single definition used by verify_active_models and ml_predict strict resolution.
PR3 (P2-1): canonical active root = scheduler_active_root(hz) only.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug

MODELS_DIR = Path(__file__).resolve().parent / "models"
ACTIVE_DIR = MODELS_DIR / "active"

# (model_kind, model_file, meta_file) per horizon bundle — six base files + meta-stack pkl.
BUNDLE_ARTIFACT_TRIPLE = (
    ("xgb", "xgb_{ticker}_{hz}.pkl", "xgb_{ticker}_{hz}_meta.json"),
    ("lstm", "lstm_{ticker}_{hz}.pt", "lstm_{ticker}_{hz}_meta.json"),
    ("transformer", "transformer_{ticker}_{hz}.pt", "transformer_{ticker}_{hz}_meta.json"),
)
META_STACK_KIND = "meta_stack"
META_STACK_MODEL_PATTERN = "meta_{ticker}_{hz}.pkl"


def scheduler_active_root(models_dir: Path, ml_horizon_slug: str) -> Path:
    """Canonical production root for a horizon (P2-1). 1c → models/active; else models/active_{hz}."""
    su = normalize_ml_horizon_slug(ml_horizon_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        return models_dir / "active"
    return models_dir / f"active_{su}"


def active_bundle_dir(ticker: str, hz: str, *, models_dir: Path | None = None) -> Path:
    """Production active directory for (ticker, horizon) under the canonical root."""
    root = models_dir or MODELS_DIR
    return scheduler_active_root(root, hz) / ticker.upper()


def meta_stack_artifact_filename(ticker: str, hz: str) -> str:
    """Trained meta-learner on stacked base probabilities (Layer 2)."""
    t = ticker.upper()
    su = normalize_ml_horizon_slug(hz)
    return META_STACK_MODEL_PATTERN.format(ticker=t, hz=su)


def horizon_bundle_filenames(ticker: str, hz: str) -> tuple[str, ...]:
    """Seven filenames: model + meta × 3 bases + meta-stack pkl for one (ticker, horizon) bundle."""
    from training_cache import parallel_artifact_basenames

    return tuple(parallel_artifact_basenames(ticker, hz))


def bundle_artifact_paths(ticker: str, hz: str, bundle_dir: Path) -> list[tuple[str, Path, Path]]:
    """Return (kind, model_path, meta_path) for each artifact in the bundle."""
    t = ticker.upper()
    su = normalize_ml_horizon_slug(hz)
    out: list[tuple[str, Path, Path]] = []
    for kind, model_pat, meta_pat in BUNDLE_ARTIFACT_TRIPLE:
        out.append(
            (
                kind,
                bundle_dir / model_pat.format(ticker=t, hz=su),
                bundle_dir / meta_pat.format(ticker=t, hz=su),
            )
        )
    return out


def legacy_layout_source_dirs(
    ticker: str,
    hz: str,
    *,
    models_dir: Path | None = None,
) -> tuple[Path, ...]:
    """
    Legacy dirs that may hold misplaced horizon artifacts (split-brain migration).

    Non-1c horizons may have weights under models/active/{T}/ instead of active_{hz}/{T}/.
    """
    root = models_dir or MODELS_DIR
    t = ticker.upper()
    su = normalize_ml_horizon_slug(hz)
    canonical = active_bundle_dir(ticker, hz, models_dir=root)
    legacy: list[Path] = []
    if su != DEFAULT_ML_HORIZON_SLUG:
        legacy.append(root / "active" / t)
    wrong_slug = root / f"active_{su}" / t
    if wrong_slug != canonical:
        legacy.append(wrong_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        legacy.append(root / "active_1c" / t)
    seen: set[Path] = set()
    ordered: list[Path] = []
    for d in legacy:
        if d in seen or d == canonical:
            continue
        seen.add(d)
        ordered.append(d)
    return tuple(ordered)


def check_active_bundle_complete(
    ticker: str,
    hz: str,
    *,
    bundle_dir: Path | None = None,
    models_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Return completeness for one (ticker, horizon) active bundle.

    Keys: compliant (bool), bundle_dir, artifacts (dict), issues (list).
    """
    bd = bundle_dir or active_bundle_dir(ticker, hz, models_dir=models_dir)
    result: dict[str, Any] = {
        "ticker": ticker.upper(),
        "horizon": normalize_ml_horizon_slug(hz),
        "bundle_dir": str(bd),
        "compliant": True,
        "artifacts": {},
        "issues": [],
    }
    if not bd.is_dir():
        result["compliant"] = False
        result["issues"].append(f"missing bundle dir: {bd}")
        return result

    for kind, model_path, meta_path in bundle_artifact_paths(ticker, hz, bd):
        art = {"exists": model_path.is_file(), "meta_exists": meta_path.is_file(), "issues": []}
        if not model_path.is_file():
            art["issues"].append(f"{model_path.name} missing")
            result["compliant"] = False
        if not meta_path.is_file():
            art["issues"].append(f"{meta_path.name} missing")
            result["compliant"] = False
        elif model_path.is_file():
            try:
                from model_contract import validate_artifact_contract

                raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                ok, reason = validate_artifact_contract(raw_meta, kind)
                if not ok:
                    art["issues"].append(f"model contract incompatible: {reason}")
                    result["compliant"] = False
            except Exception as ex:
                art["issues"].append(f"contract check failed: {ex}")
                result["compliant"] = False
        result["artifacts"][kind] = art

    meta_pkl = bd / meta_stack_artifact_filename(ticker, hz)
    meta_art = {"exists": meta_pkl.is_file(), "meta_exists": False, "issues": []}
    if not meta_pkl.is_file():
        meta_art["issues"].append(f"{meta_pkl.name} missing")
        result["compliant"] = False
    result["artifacts"][META_STACK_KIND] = meta_art

    return result


def strict_active_bundle_dir_for_horizon(ticker: str, hz: str, *, models_dir: Path | None = None) -> Path | None:
    """Canonical active dir for hz when the full bundle contract passes (P2-4: no tie-break)."""
    bd = active_bundle_dir(ticker, hz, models_dir=models_dir)
    if check_active_bundle_complete(ticker, hz, bundle_dir=bd, models_dir=models_dir)["compliant"]:
        return bd
    return None


def check_candidate_bundle_complete(
    ticker: str,
    hz: str,
    candidate_dir: Path,
) -> dict[str, Any]:
    """Same 7-file contract as active bundles, applied to parallel/cascade candidate dirs."""
    return check_active_bundle_complete(ticker, hz, bundle_dir=candidate_dir)


def candidate_bundles_complete(
    ticker: str,
    hz: str,
    parallel_dir: Path,
    cascade_dir: Path,
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    par = check_candidate_bundle_complete(ticker, hz, parallel_dir)
    cas = check_candidate_bundle_complete(ticker, hz, cascade_dir)
    return par["compliant"] and cas["compliant"], par, cas


def _validate_horizon_bundle_in_dir(src_dir: Path, ticker: str, hz: str) -> list[str]:
    missing: list[str] = []
    for name in horizon_bundle_filenames(ticker, hz):
        if not (src_dir / name).is_file():
            missing.append(name)
    return missing


def promote_horizon_bundle_from_candidate(
    src_dir: Path,
    *,
    ticker: str,
    hz: str,
    models_dir: Path | None = None,
) -> Path:
    """
    Copy the seven-file bundle for (ticker, hz) into the canonical active dir (P2-2).

    Uses atomic directory replace via manual_control._replace_active_dir_from_source.
    """
    missing = _validate_horizon_bundle_in_dir(src_dir, ticker, hz)
    if missing:
        raise FileNotFoundError(
            f"partial candidate bundle for {ticker} hz={hz}: missing {missing[:3]}"
            + ("…" if len(missing) > 3 else "")
        )
    active_ticker_dir = active_bundle_dir(ticker, hz, models_dir=models_dir)
    include = frozenset(horizon_bundle_filenames(ticker, hz))
    from arch_competition.manual_control import _replace_active_dir_from_source

    _replace_active_dir_from_source(src_dir, active_ticker_dir, include_names=include)
    return active_ticker_dir


def consolidate_horizon_layout_plan(
    ticker: str,
    hz: str,
    *,
    models_dir: Path | None = None,
) -> dict[str, Any]:
    """Plan moves from legacy dirs into canonical active_{hz}/{T}/ (dry-run helper)."""
    root = models_dir or MODELS_DIR
    canonical = active_bundle_dir(ticker, hz, models_dir=root)
    canonical.mkdir(parents=True, exist_ok=True)
    moves: list[dict[str, str]] = []
    for fname in horizon_bundle_filenames(ticker, hz):
        dest = canonical / fname
        if dest.is_file():
            continue
        for legacy in legacy_layout_source_dirs(ticker, hz, models_dir=root):
            src = legacy / fname
            if src.is_file():
                moves.append({"file": fname, "from": str(src), "to": str(dest)})
                break
    return {
        "ticker": ticker.upper(),
        "horizon": normalize_ml_horizon_slug(hz),
        "canonical_dir": str(canonical),
        "moves": moves,
    }


def apply_consolidate_horizon_layout_plan(
    plan: dict[str, Any],
    *,
    remove_from_legacy: bool = False,
) -> list[str]:
    """Apply a plan from consolidate_horizon_layout_plan; returns copied filenames."""
    copied: list[str] = []
    for move in plan.get("moves") or []:
        if not isinstance(move, dict):
            continue
        src = Path(str(move.get("from") or ""))
        dest = Path(str(move.get("to") or ""))
        fname = str(move.get("file") or dest.name)
        if not src.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(fname)
        if remove_from_legacy and src.is_file():
            try:
                src.unlink()
            except OSError:
                pass
    return copied
