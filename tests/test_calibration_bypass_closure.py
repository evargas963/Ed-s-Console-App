"""
Mechanical closure: calibration_decision_log must not be referenced outside the controlled surface.

Production writes: calibration.writer only (called from signals).
Production reads/updates for study: calibration/* modules with enforce + trusted predicates.
signals.py may only reference the table name in log strings (no SQL).
"""

from __future__ import annotations

from pathlib import Path


_NEEDLE = "calibration_decision_log"

# TEST_SYSTEM_REHAB_V2 final remediation: this file's own `_tracked_py_files()`
# independently re-derived the same git-index observation the shared `repo_index`
# fixture (tests/conftest.py) already builds once per run -- a `subprocess.run(["git",
# "ls-files", ...])` + per-file `.read_text()` re-scan is the same redundant cost the
# `.rglob`/`.glob`/`os.walk` recurrence lock was built to eliminate, just a different
# call shape. `repo_index` was ALSO missing the git-index scoping this file's own
# docstring specifically warned about (it used a raw `root.rglob("*.py")`, so
# `scratchpad/`'s untracked scripts would have silently reached it) -- fixed at the
# shared fixture, not worked around here a second time.


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


def test_no_unauthorized_python_references_to_calibration_decision_log(repo_index) -> None:
    offenders: list[str] = []
    for rel, text, _tree in repo_index.items():
        if _NEEDLE not in text:
            continue
        if not _allowed_path(rel):
            offenders.append(rel.as_posix())
    assert offenders == [], (
        "calibration_decision_log referenced outside controlled modules — add review or move code:\n"
        + "\n".join(offenders)
    )


def test_insert_into_calibration_decision_log_only_writer_and_tests(repo_index) -> None:
    """INSERT must not appear outside writer (production) and calibration tests."""
    bad: list[str] = []
    for relpath, text, _tree in repo_index.items():
        if "INSERT INTO calibration_decision_log" not in text:
            continue
        rel = relpath.as_posix()
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


def test_update_calibration_decision_log_only_backfill_and_tests(repo_index) -> None:
    bad: list[str] = []
    for relpath, text, _tree in repo_index.items():
        if "UPDATE calibration_decision_log" not in text:
            continue
        rel = relpath.as_posix()
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
