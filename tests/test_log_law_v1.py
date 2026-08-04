"""LOG LAW (operator/PM 2026-08-04) — negative controls.

One defect ledger, one epistemic ledger, telemetry stays telemetry. The failure this locks
against is SPRAWL: `reports/rc_open_drain_latest.md` carried 21 `| RC-… | OPEN |` rows beside
the real ledger, so closable work had two homes and whichever list a reader opened looked
authoritative while the other rotted.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.log_law import (  # noqa: E402
    DEFECT_LEDGER,
    EPISTEMIC_LEDGER,
    is_telemetry,
    log_law_violations,
    open_class_count,
    third_queue_violations,
    unproven_overdue,
)

_QUEUE = """# Some report

| id | status | note |
|---|---|---|
| RC-901 | OPEN | first |
| RC-902 | OPEN | second |
| RC-903 | PARTIAL | third |
"""


def _mk(tmp_path: Path, rel: str, body: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_third_work_queue_blocks(tmp_path):
    _mk(tmp_path, "reports/some_triage.md", _QUEUE)
    bad = third_queue_violations(tmp_path)
    assert bad and bad[0].startswith("LOG_LAW:")
    assert "some_triage.md" in bad[0]


def test_the_two_sanctioned_ledgers_are_never_flagged(tmp_path):
    _mk(tmp_path, DEFECT_LEDGER, _QUEUE)
    _mk(tmp_path, EPISTEMIC_LEDGER, _QUEUE.replace("OPEN", "UNPROVEN"))
    assert third_queue_violations(tmp_path) == []


def test_prose_mentioning_rc_ids_is_not_a_queue(tmp_path):
    _mk(tmp_path, "reports/notes.md",
        "RC-901 was fixed, and RC-902 is OPEN in the ledger. See RC-903 too.")
    assert third_queue_violations(tmp_path) == []


def test_two_rows_is_discussion_not_a_queue(tmp_path):
    _mk(tmp_path, "reports/small.md",
        "| id | status |\n|---|---|\n| RC-901 | OPEN |\n| RC-902 | OPEN |\n")
    assert third_queue_violations(tmp_path) == []


def test_operator_escape_allows_a_frozen_snapshot(tmp_path):
    _mk(tmp_path, "reports/frozen_audit.md",
        "# audit\n`# log-law-ok: frozen dated record`\n" + _QUEUE)
    assert third_queue_violations(tmp_path) == []


def test_telemetry_is_never_debt():
    assert is_telemetry("governance/sod_drift_events.jsonl")
    assert is_telemetry("logs/ed_server.log")
    assert not is_telemetry("governance/root_cause_log.md")


def test_overdue_epistemic_row_blocks(tmp_path):
    _mk(tmp_path, EPISTEMIC_LEDGER,
        "| UNPROVEN | 2026-07-01 | 2026-07-10 | that something holds |\n")
    bad = unproven_overdue(tmp_path, today="2026-08-04")
    assert bad and "OVERDUE" in bad[0]


def test_future_dated_hypothesis_is_not_debt(tmp_path):
    """A pre-registered claim whose data has not accrued is the instrument working — forcing
    it to a verdict early is how contaminated or underpowered data becomes a citation."""
    _mk(tmp_path, EPISTEMIC_LEDGER,
        "| UNPROVEN | 2026-08-01 | 2026-08-28 | that something holds |\n")
    assert unproven_overdue(tmp_path, today="2026-08-04") == []


def test_live_repo_satisfies_the_law():
    """The law must be green on the tree that ships it — a lock nobody can satisfy is theater."""
    assert log_law_violations(REPO) == []


def test_open_class_count_reads_the_live_ledger():
    n = open_class_count(REPO)
    assert n >= 0, "the defect ledger must be readable for the count to mean anything"


def test_rc238_the_law_is_actually_REGISTERED_not_merely_present():
    """RC-238: a lock that exists and passes is NOT a lock that blocks.

    This module shipped green while its CHECKS registration sat commented out awaiting the
    operator GO, and a green run cannot distinguish 'enforced' from 'present'. This asserts
    the WIRING: the check must be registered ENFORCED in the live CHECKS list, so the line
    cannot silently revert to a comment without a test failing.
    """
    import tools.check_institutional_correctness as gate

    entry = [c for c in gate.CHECKS if c[0] == "log_law"]
    assert entry, "log_law is not registered in CHECKS — the LOG LAW is inert"
    name, fn, enforced = entry[0]
    assert enforced is True, "log_law must be ENFORCED (blocking), not advisory"
    assert fn is gate.check_log_law
    assert fn() == [], "the registered check must be green on the tree that ships it"
