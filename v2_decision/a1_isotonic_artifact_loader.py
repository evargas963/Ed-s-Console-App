"""Runtime loader for A1 isotonic artifacts."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .a1_conformal_artifact_contract import (
    current_pointer_path,
    is_eligible_for_current_pointer_isotonic,
)


log = logging.getLogger(__name__)


def load_a1_isotonic_artifact(
    *,
    ticker: str,
    horizon: str,
    module_id: str = "A",
    expression_profile_id: str = "A1",
    now_epoch_seconds: float | None = None,
) -> dict | None:
    """Returns runtime-eligible isotonic artifact for (ticker, horizon) or None.

    Reads _current.json pointer per artifact_kind="isotonic", follows to artifact,
    applies all eligibility + freshness checks. Returns None on any failure.
    Never raises in production. Logs at debug.
    """
    try:
        data_root = Path("data")
        pointer_path = current_pointer_path(
            ticker=ticker,
            horizon=horizon,
            module_id=module_id,
            expression_profile_id=expression_profile_id,
            data_root=data_root,
            artifact_kind="isotonic",
        )
        if not pointer_path.is_file():
            return None
        pointer_payload = json.loads(pointer_path.read_text(encoding="utf-8"))
        relative = pointer_payload.get("artifact_relative_path") if isinstance(pointer_payload, dict) else None
        if not isinstance(relative, str) or not relative:
            return None
        artifact_path = Path(relative)
        if not artifact_path.is_absolute():
            artifact_path = data_root / artifact_path
        if not artifact_path.is_file():
            return None
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        if not isinstance(artifact, dict):
            return None
        if ticker not in artifact.get("ticker_universe", []):
            return None
        if artifact.get("horizon") != horizon:
            return None
        eligible, reason = is_eligible_for_current_pointer_isotonic(artifact)
        if not eligible:
            log.debug("A1 isotonic artifact rejected: %s", reason)
            return None
        now = float(now_epoch_seconds) if now_epoch_seconds is not None else time.time()
        max_age = float(artifact["governed_max_age_seconds"])
        generated_at = float(artifact["generated_at_epoch_seconds"])
        if now - generated_at > max_age:
            return None
        return artifact
    except Exception:
        log.debug("A1 isotonic artifact load failed", exc_info=True)
        return None
