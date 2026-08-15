"""
Mechanical closure: calibration_decision_log must not be referenced outside the controlled surface.

Production writes: calibration.writer only (called from signals).
Production reads/updates for study: calibration/* modules with enforce + trusted predicates.
signals.py may only reference the table name in log strings (no SQL).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


_NEEDLE = "calibration_decision_log"
_ROOT = Path(__file__).resolve().parents[1]


def _tracked_py_files() -> list[Path]:
    """Repo-wide is the GIT INDEX (RC-274, RC-286, RC-307).

    All three scanners below walked the disk behind a hand-written skip list of
    `__pycache__`, `.venv`, `node_modules`, `.claude` — and not `scratchpad/`, which holds 93
    untracked throwaway scripts. `scratchpad/_server_RELANDED_20260802.py` is a saved copy of
    an old server, so it mentions `calibration_decision_log` and has been failing this gate as
    an unauthorized production reference to code the repository does not contain. Every
    hand-maintained skip list is correct on the day it is written; the index is the definition.
    """
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                         cwd=_ROOT, capture_output=True, text=True, check=True).stdout
    return [_ROOT / rel for rel in sorted(p for p in out.split("\0") if p)
            if (_ROOT / rel).exists()]


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
    # execution_identity_v1 (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY_V1):
    # single owner of the identity linkage triggers on calibration_decision_log
    # + its adversarial suite (tmp-DB fixtures only; never the production DB).
    if s == "execution_identity.py":
        return True
    if s == "tests/test_execution_identity_v1.py":
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
    # server.py: table name only in boot diagnostic log strings + the read-only
    # /api/ops/calibration_rowcount health probe, which delegates the SELECT to
    # calibration.writer.compute_calibration_rate_health (no SQL in server.py).
    if s == "server.py":
        return True
    # operable_surface_gate: G1-G4 reporting tool. READ-ONLY by construction as of
    # 2026-07-19 — its ALTER/UPDATE quarantine writer was moved into
    # calibration/operable_surface_quarantine.py so every write to this table stays inside
    # the audited surface. Its test seeds fixtures in tmp_path only, never production.
    if s == "tools/operable_surface_gate.py":
        return True
    if s == "tests/test_operable_surface_gate.py":
        return True
    # Read-only audit / observability tooling and probes (SELECT/COUNT, sqlite_master,
    # or table name in help/provenance/audit strings — never INSERT/UPDATE).
    if s == "tools/check_base_ticker_observability.py":
        return True
    if s == "tools/check_card_direction_integrity.py":
        return True
    if s == "tools/check_card_signal_fidelity.py":
        return True
    if s == "tools/replay_money_path_probe.py":
        return True
    if s == "tools/_build_institutional_audit_phase2.py":
        return True
    if s == "verification/base_ticker_observability.py":
        return True
    if s == "verification/db_sqlite_contention_impact_audit.py":
        return True
    # Tests that seed throwaway calibration_decision_log fixtures in in-test sqlite DBs
    # (same controlled-fixture class as the test_backfill_* / test_v2_* tests above).
    if s == "tests/test_base_ticker_observability.py":
        return True
    if s == "tests/test_fusion_temperature_calibration.py":
        return True
    if s == "tests/test_track_b_calibration_backfill_insert.py":
        return True
    # incumbent_eval_v1 (Study #1 racetrack): read-only SELECT via sqlite
    # mode=ro URI against recorded rows; never INSERT/UPDATE. Its test seeds a
    # throwaway fixture table in a tmp-path DB (same controlled-fixture class
    # as the test_backfill_* / test_v2_* tests above).
    if s == "research/incumbent_eval_v1/runner.py":
        return True
    if s == "research/incumbent_eval_v1/__init__.py":
        return True
    if s == "tests/test_incumbent_eval_v1.py":
        return True
    # challenger_eval_v1 (Study #2 racetrack): same controlled read-only class.
    if s == "research/challenger_eval_v1/runner.py":
        return True
    if s == "research/challenger_eval_v1/__init__.py":
        return True
    if s == "tests/test_challenger_eval_v1.py":
        return True
    # structural_eval_v1 (Study #3 racetrack): same controlled read-only class.
    if s == "research/structural_eval_v1/runner.py":
        return True
    if s == "research/structural_eval_v1/__init__.py":
        return True
    if s == "tests/test_structural_eval_v1.py":
        return True
    return False


def test_no_unauthorized_python_references_to_calibration_decision_log() -> None:
    offenders: list[str] = []
    for p in _tracked_py_files():
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
    for p in _tracked_py_files():
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
            or rel == "tests/test_execution_identity_v1.py"  # scan TOKEN in the write-path inventory lock; no INSERT executed
            or rel == "tests/test_action12_14_signal_layer_discrimination_fail_closed.py"
            or rel == "tests/test_payload_audit.py"
            or rel == "tests/test_validate_outcome_join_fail_closed.py"
            or rel == "tests/test_backfill_outcomes_ticker_key.py"
            or rel == "tests/test_backfill_signal_layer_v1_bundle.py"
            or rel == "tests/test_base_ticker_observability.py"
            or rel == "tests/test_fusion_temperature_calibration.py"
            or rel == "tests/test_track_b_calibration_backfill_insert.py"
            or rel == "tests/test_incumbent_eval_v1.py"  # tmp-path fixture DB only; production runner is SELECT-only (mode=ro)
            or rel == "tests/test_challenger_eval_v1.py"  # tmp-path fixture DB only; production runner is SELECT-only (mode=ro)
            or rel == "tests/test_structural_eval_v1.py"  # tmp-path fixture DB only; production runner is SELECT-only (mode=ro)
            or rel == "tests/test_operable_surface_gate.py"  # tmp-path fixture DB only; the gate tool itself is SELECT-only
        )
        if not ok:
            bad.append(rel)
    assert bad == [], f"Unexpected INSERT into calibration_decision_log: {bad}"


def test_update_calibration_decision_log_only_backfill_and_tests() -> None:
    bad: list[str] = []
    for p in _tracked_py_files():
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
            rel == "calibration/operable_surface_quarantine.py"  # sole writer of research_excluded; moved here 2026-07-19 out of tools/
            or rel == "calibration/backfill_outcomes.py"
            or rel == "calibration/backfill_signal_layer_v1_bundle.py"
            or rel == "calibration/v2_advisory_backfill.py"
            or rel == "calibration/v2_live_logging.py"
            or rel.startswith("tests/test_calibration")
            or rel == "tests/test_operable_surface_gate.py"  # tmp-path fixture DB only
        )
        if not ok:
            bad.append(rel)
    assert bad == [], f"Unexpected UPDATE calibration_decision_log: {bad}"
