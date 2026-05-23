"""Shared active-bundle completeness contract (G3-R1).

Single definition used by verify_active_models and ml_predict strict resolution.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml_horizon import PRIMARY_DECISION_HORIZONS, normalize_ml_horizon_slug

MODELS_DIR = Path(__file__).resolve().parent / "models"
ACTIVE_DIR = MODELS_DIR / "active"

# (model_kind, model_file, meta_file) per horizon bundle — six files total.
BUNDLE_ARTIFACT_TRIPLE = (
    ("xgb", "xgb_{ticker}_{hz}.pkl", "xgb_{ticker}_{hz}_meta.json"),
    ("lstm", "lstm_{ticker}_{hz}.pt", "lstm_{ticker}_{hz}_meta.json"),
    ("transformer", "transformer_{ticker}_{hz}.pt", "transformer_{ticker}_{hz}_meta.json"),
)


def active_bundle_dir(ticker: str, hz: str, *, models_dir: Path | None = None) -> Path:
    """Production active root for (ticker, horizon)."""
    su = normalize_ml_horizon_slug(hz)
    root = models_dir or MODELS_DIR
    if su == "1c":
        return root / "active" / ticker
    return root / f"active_{su}" / ticker


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

    return result


def strict_active_bundle_dir_for_horizon(ticker: str, hz: str, *, models_dir: Path | None = None) -> Path | None:
    """Best active dir for hz that satisfies full bundle contract (G3-R1)."""
    root = models_dir or MODELS_DIR
    su = normalize_ml_horizon_slug(hz)
    cands = [root / f"active_{su}" / ticker, root / "active" / ticker] if su != "1c" else [
        root / "active" / ticker,
        root / f"active_{su}" / ticker,
    ]
    seen: set[Path] = set()
    for d in cands:
        if d in seen:
            continue
        seen.add(d)
        if check_active_bundle_complete(ticker, hz, bundle_dir=d, models_dir=root)["compliant"]:
            return d
    return None


def check_candidate_bundle_complete(
    ticker: str,
    hz: str,
    candidate_dir: Path,
) -> dict[str, Any]:
    """Same 6-file contract as active bundles, applied to parallel/cascade candidate dirs."""
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
