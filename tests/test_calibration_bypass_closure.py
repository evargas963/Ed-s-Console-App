"""
Mechanical closure: calibration_decision_log must not be referenced outside the controlled surface.

Production writes: calibration.writer only (called from signals).
Production reads/updates for study: calibration/* modules with enforce + trusted predicates.
signals.py may only reference the table name in log strings (no SQL).
"""

from __future__ import annotations

from pathlib import Path


_NEEDLE = "calibration_decision_log"
_ROOT = Path(__file__).resolve().parents[1]


def _allowed_path(rel: Path) -> bool:
    s = rel.as_posix()
    if s.startswith("calibration/"):
        return True
    if s.startswith("tests/test_calibration"):
        return True
    if s == "tests/test_v2_advisory_backfill.py":
        return True
    if s == "tests/test_v2_a1_calibration.py":
        return True
    if s == "signals.py":
        return True
    # Approved read-only probes / tooling (controlled SELECT surface).
    if s == "tools/_phase4_prod_probe.py":
        return True
    if s == "tools/_phase4a_fast_count.py":
        return True
    if s == "tools/_phase4a_quantify_anchor_miss.py":
        return True
    if s.startswith("governance/"):
        return True
    if s == "tests/test_action12_14_signal_layer_discrimination_fail_closed.py":
        return True
    if s == "tests/test_payload_audit.py":
        return True
    if s == "tests/test_validate_outcome_join_fail_closed.py":
        return True
    # Tests for calibration backfill modules (which are themselves in the UPDATE allowlist) —
    # they need to INSERT calibration_decision_log fixtures to exercise their backfill targets.
    if s == "tests/test_backfill_outcomes_ticker_key.py":
        return True
    if s == "tests/test_backfill_signal_layer_v1_bundle.py":
        return True
    return False


def test_no_unauthorized_python_references_to_calibration_decision_log() -> None:
    offenders: list[str] = []
    for p in _ROOT.rglob("*.py"):
        parts = set(p.parts)
        if "__pycache__" in parts or ".venv" in parts or "node_modules" in parts or ".claude" in parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _NEEDLE not in text:
            continue
        rel = p.relative_to(_ROOT)
        if not _allowed_path(rel):
            offenders.append(rel.as_posix())
    assert offenders == [], (
        "calibration_decision_log referenced outside controlled modules — add review or move code:\n"
        + "\n".join(offenders)
    )


def test_insert_into_calibration_decision_log_only_writer_and_tests() -> None:
    """INSERT must not appear outside writer (production) and calibration tests."""
    bad: list[str] = []
    for p in _ROOT.rglob("*.py"):
        if "__pycache__" in p.parts or ".claude" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "INSERT INTO calibration_decision_log" not in text:
            continue
        rel = p.relative_to(_ROOT).as_posix()
        ok = (
            rel == "calibration/writer.py"
            or rel.startswith("tests/test_calibration")
            or rel == "tests/test_v2_advisory_backfill.py"
            or rel == "tests/test_v2_a1_calibration.py"
            or rel == "tests/test_action12_14_signal_layer_discrimination_fail_closed.py"
            or rel == "tests/test_payload_audit.py"
            or rel == "tests/test_validate_outcome_join_fail_closed.py"
            or rel == "tests/test_backfill_outcomes_ticker_key.py"
            or rel == "tests/test_backfill_signal_layer_v1_bundle.py"
        )
        if not ok:
            bad.append(rel)
    assert bad == [], f"Unexpected INSERT into calibration_decision_log: {bad}"


def test_update_calibration_decision_log_only_backfill_and_tests() -> None:
    bad: list[str] = []
    for p in _ROOT.rglob("*.py"):
        if "__pycache__" in p.parts or ".claude" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "UPDATE calibration_decision_log" not in text:
            continue
        rel = p.relative_to(_ROOT).as_posix()
        ok = (
            rel == "calibration/backfill_outcomes.py"
            or rel == "calibration/backfill_signal_layer_v1_bundle.py"
            or rel == "calibration/v2_advisory_backfill.py"
            or rel == "calibration/v2_live_logging.py"
            or rel.startswith("tests/test_calibration")
        )
        if not ok:
            bad.append(rel)
    assert bad == [], f"Unexpected UPDATE calibration_decision_log: {bad}"
