"""Static checks that pilot_step3 Python modules do not import legacy decision stack."""

from __future__ import annotations

from pathlib import Path

# Substrings that must not appear in executable pilot modules (docstrings minimal).
_FORBIDDEN = (
    "from signals",
    "import signals",
    "call_engine",
    "multi_horizon_decision",
    "prediction_engine",
    "bayesian_fusion",
    "ml_train",
    "train_all",
    "outcome_1c",
    "outcome_5c",
    "outcome_15c",
    "outcome_60c",
)


def legacy_stack_contamination_scan(*, pilot_dir: Path | None = None) -> tuple[bool, list[str]]:
    """
    Scan *.py under pilot_step3 (excluding __init__.py) for forbidden legacy imports/names.
    Returns (passes, violation_messages).
    """
    base = pilot_dir or Path(__file__).resolve().parent
    violations: list[str] = []
    for path in sorted(base.glob("*.py")):
        if path.name in ("__init__.py", "scaffold_audit.py"):
            continue
        text = path.read_text(encoding="utf-8")
        low = text.lower()
        for sub in _FORBIDDEN:
            if sub.lower() in low:
                violations.append(f"{path.name}: contains forbidden substring {sub!r}")
    return (len(violations) == 0, violations)
