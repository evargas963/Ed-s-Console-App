"""Load frozen pilot pre-registration and derived constants."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_PRREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"

# Must match governance/Framework-ED-Decision-Engine-v1.1.md and prereg_v1.json binding fields.
EXPECTED_FRAMEWORK_DOC_ID = "governance/Framework-ED-Decision-Engine-v1.1.md"
EXPECTED_FRAMEWORK_DOC_VERSION = "1.1"

FROZEN_PILOT_PREREG_ID = "pilot_step3_prereg_v1"


def prereg_path() -> Path:
    return _PRREG_PATH


def load_prereg(*, validate: bool = True) -> dict[str, Any]:
    with open(_PRREG_PATH, encoding="utf-8") as f:
        prereg: dict[str, Any] = json.load(f)
    if validate:
        validate_prereg_integrity(prereg)
    return prereg


def prereg_content_hash(prereg: dict[str, Any]) -> str:
    """SHA-256 of canonical JSON excluding content_hash field (for signing)."""
    body = {k: v for k, v in sorted(prereg.items()) if k != "content_hash"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_prereg_hash(prereg: dict[str, Any]) -> None:
    expected = prereg.get("content_hash")
    actual = prereg_content_hash(prereg)
    if not expected:
        raise ValueError("prereg_v1.json missing content_hash; run pilot_runner --fix-hash")
    if expected != actual:
        raise ValueError(f"prereg content_hash mismatch: file={expected!r} computed={actual!r}")


def validate_framework_binding(prereg: dict[str, Any]) -> None:
    """Hard-fail if prereg is not amended for the locked framework doc version."""
    fid = prereg.get("framework_doc_id")
    fver = prereg.get("framework_doc_version")
    if not fid or not fver:
        raise ValueError(
            "prereg_v1.json missing framework_doc_id or framework_doc_version; "
            "amend prereg per governance/Framework-ED-Decision-Engine-v1.1.md"
        )
    if fid != EXPECTED_FRAMEWORK_DOC_ID:
        raise ValueError(
            f"prereg framework_doc_id mismatch: file={fid!r} expected={EXPECTED_FRAMEWORK_DOC_ID!r}"
        )
    if str(fver) != EXPECTED_FRAMEWORK_DOC_VERSION:
        raise ValueError(
            f"prereg framework_doc_version mismatch: file={fver!r} expected={EXPECTED_FRAMEWORK_DOC_VERSION!r}"
        )


def validate_prereg_integrity(prereg: dict[str, Any]) -> None:
    """Full integrity gate: body hash + framework binding (call from any consumer of frozen prereg)."""
    validate_prereg_hash(prereg)
    validate_framework_binding(prereg)


def pilot_grid(prereg: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in prereg["barrier_grid"]["stop_atr_multiples"]:
        for t in prereg["barrier_grid"]["target_atr_multiples"]:
            for v in prereg["barrier_grid"]["vertical_minutes"]:
                out.append(
                    {
                        "stop_atr": float(s),
                        "target_atr": float(t),
                        "vertical_minutes": int(v),
                        "cell_id": f"s{s}_t{t}_v{v}".replace(".", "p"),
                    }
                )
    return out
