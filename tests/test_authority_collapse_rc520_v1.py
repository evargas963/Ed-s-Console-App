"""RC-520 — one semantic responsibility has one canonical file.

WHAT WAS OBSERVED (2026-09-05, 466378c6). Law, current work, defect state, acceptance,
claims, decisions, procedure and history were spread across overlapping files; the ledger
carried 405 CLOSED rows (1.37 MB) in the default read path of 33 executable consumers.

These controls drive the REAL owners — `tools.mission_latch.archive_closed_rows`, the ledger
validators, git itself. The filename-ban check that once sat beside them
(`authority_surfaces_have_one_owner`) was retired 2026-09-11 (RC-550): it refused twelve
retired file NAMES and two documents' heading shapes, which a duplicate under any other
name walked past; its tests went with it.

    pytest tests/test_authority_collapse_rc520_v1.py -q
"""
from __future__ import annotations

import inspect
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_institutional_correctness as gate  # noqa: E402
import tools.mission_latch as latch  # noqa: E402

LEDGER = ROOT / "governance" / "root_cause_log.md"


def _rows(text: str) -> list[list[str]]:
    return [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in text.splitlines() if line.startswith("| RC-")]


def _bold_ids(text: str) -> set[str]:
    ids = set()
    for line in text.splitlines():
        m = re.match(r"- \[ \] \*\*([A-Za-z0-9_:-]+)", line)
        if m:
            ids.add(m.group(1))
        if line.startswith("| ") and not line.startswith(("| ID", "| Phase", "|---")):
            ids.add(line.split("|")[1].strip())
    return ids


# ── the queue is a record: no authority path reads it ───────────────────────────────────
def test_stale_queue_status_grants_no_authority():
    """A stale NEXT/QUEUED/OPEN in a document cannot open a mission or block a turn: the
    latch and the Stop guards read the ledger only."""
    import tools.stop_guard as sg

    for mod in (latch, sg):
        src = inspect.getsource(mod)
        assert "ACTIVE_PROGRAM" not in src and "OPEN_ITEMS" not in src, mod.__name__
    rows = latch.all_rows(ROOT)
    assert rows and all(r.rc_id.startswith("RC-") for r in rows)
    assert not any("NEXT" == r.status or "QUEUED" == r.status for r in rows)


def test_open_work_and_acceptance_have_exactly_one_home_each():
    spec = _bold_ids((ROOT / "OPEN_ITEMS.md").read_text(encoding="utf-8"))
    work = _bold_ids((ROOT / "ACTIVE_PROGRAM.md").read_text(encoding="utf-8"))
    assert spec and work
    assert spec & work == set(), f"an item lives in both files: {sorted(spec & work)}"
    assert not _rows((ROOT / "OPEN_ITEMS.md").read_text(encoding="utf-8"))


def test_defect_rows_live_only_in_the_ledger(repo_index):
    """No tracked .py file carries a `| RC-n | <status> |` row of its own — a second parser
    target would be a second ledger — and the ledger is where every id resolves."""
    ledger_ids = {r[0] for r in _rows(LEDGER.read_text(encoding="utf-8"))}
    assert ledger_ids, "the ledger parsed to no rows — the row grammar or the file moved"
    row_re = re.compile(r"^\| RC-\d+ \| (OPEN|CLOSED|BLOCKED|ARCHIVED) \|", re.M)
    for rel, text, _tree in repo_index.items():
        if rel.parts[0] == "tests" and rel.name == Path(__file__).name:
            continue
        assert not row_re.search(text), f"{rel} carries a ledger row of its own"


# ── 4. compacted history: ARCHIVED rows resolve and are inert ───────────────────────────
def _archived_rows() -> list[list[str]]:
    return [r for r in _rows(LEDGER.read_text(encoding="utf-8")) if r[1] == "ARCHIVED"]


def test_archived_rows_resolve_through_their_git_pointer():
    rows = _archived_rows()
    assert rows, "no ARCHIVED row: the compaction that made the ledger readable is missing"
    shas = {m for r in rows for m in re.findall(r"git show ([0-9a-f]{7,40}):governance/root_cause_log\.md", r[5])}
    assert shas, "an ARCHIVED row without a git pointer cannot be audited"
    assert all(re.search(r"git show [0-9a-f]{7,40}:governance/root_cause_log\.md", r[5]) for r in rows)
    for sha in shas:
        blob = subprocess.run(["git", "show", f"{sha}:governance/root_cause_log.md"], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", check=True).stdout
        full = {r[0]: r for r in _rows(blob)}
        for r in rows:
            assert full[r[0]][1] == "CLOSED", f"{r[0]} was not CLOSED at {sha}"
            assert full[r[0]][2] == r[2], f"{r[0]} opened-date drifted in compaction"


def test_archive_compaction_is_exact_and_leaves_open_rows_alone():
    text = "\n".join([
        "| id | status | opened | due | defect | why | fix |",
        "| RC-1 | CLOSED | 2026-06-01 | 2026-06-02 | Old defect. Long chain | why1 -> why2 | FIXED IN PROGRESS text `python x.py` |",
        "| RC-2 | OPEN | 2026-06-01 | 2026-06-02 | Live defect | why | IN PROGRESS |",
        "| RC-3 | CLOSED | 2026-09-04 | 2026-09-05 | Recent close | why | FIXED |",
        "| RC-4 | CLOSED | 2026-06-01 | 2026-06-02 | Kept by id | why | FIXED |",
        "",
    ])
    new, archived = latch.archive_closed_rows(text, "2026-09-01", "abc1234", keep_ids=("RC-4",))
    assert archived == ["RC-1"]
    rows = {r[0]: r for r in _rows(new)}
    assert rows["RC-1"][1] == "ARCHIVED" and len(rows["RC-1"]) == 7
    assert "git show abc1234:governance/root_cause_log.md" in rows["RC-1"][5]
    assert rows["RC-1"][4] == "Old defect"
    assert not any(m in rows["RC-1"][5] for m in latch.UNFINISHED_MARKERS)
    assert rows["RC-2"] == [c.strip() for c in text.splitlines()[2].strip("|").split("|")]
    assert rows["RC-3"][1] == "CLOSED" and rows["RC-4"][1] == "CLOSED"
    assert new.splitlines()[0] == text.splitlines()[0]


def test_archived_rows_are_skipped_by_the_substance_validators(tmp_path, monkeypatch):
    """The same command-less closure is judged when CLOSED and ignored when ARCHIVED — an
    archived line asserts nothing new; the pointer carries the judged text. Driven through
    the real ledger validator over a hermetic ledger."""
    gov = tmp_path / "governance"
    gov.mkdir()
    (gov / "unproven_register.md").write_text("| status | opened | due | claim | evidence |\n",
                                              encoding="utf-8")
    row = "| RC-777 | {status} | 2026-09-06 | 2099-01-01 | d | why | fixed, no command cited |"
    monkeypatch.setattr(gate, "REPO", tmp_path)
    (gov / "root_cause_log.md").write_text(row.format(status="CLOSED") + "\n", encoding="utf-8")
    closed_hits = [v for v in gate.check_root_cause_log() if "RC-777" in v.msg]
    (gov / "root_cause_log.md").write_text(row.format(status="ARCHIVED") + "\n", encoding="utf-8")
    archived_hits = [v for v in gate.check_root_cause_log() if "RC-777" in v.msg]
    assert closed_hits and "re-runnable command" in closed_hits[0].msg
    assert archived_hits == []


# ── 5. the surviving owners still resolve ───────────────────────────────────────────────
def test_operator_decisions_still_resolve():
    text = (ROOT / "governance" / "OPERATOR_DECISION_REGISTER.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"^\| \*\*(O-\d\d)\*\* \|", text, re.M))
    assert {f"O-{i:02d}" for i in range(1, 14)} <= ids
    assert "R-08" in text and "R-09" in text
    assert (ROOT / "config" / "decision_path_admissions.json").is_file()


def test_unproven_claims_still_fail_closed():
    entry = [(n, e) for n, f, e in gate.CHECKS if n == "measured_claims_cite_evidence"]
    assert entry == [("measured_claims_cite_evidence", True)]
    assert (ROOT / "governance" / "unproven_register.md").is_file()
    assert isinstance(gate.check_measured_claims_cite_evidence(), list)


def test_served_pipeline_quality_is_the_document_not_a_stub():
    text = (ROOT / "PIPELINE_QUALITY.md").read_text(encoding="utf-8")
    assert "Archived Phase 3b" not in text
    assert text.count("\n") > 20 and "## " in text
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    assert 'Path(APP_DIR) / "PIPELINE_QUALITY.md"' in server


# test_moved_source_consumers_are_rewired was deleted 2026-09-11 (RC-550): a one-time migration
# check that had become a permanent ban on thirteen strings and on any .py file MENTIONING a
# root document — a docstring citation read as "reads a root document it has no reason to".
# Mention is not a read; a string ban is not a control.


def test_adapters_point_at_the_owners_and_carry_no_law():
    cursor = (ROOT / ".cursor" / "rules" / "00-always.mdc").read_text(encoding="utf-8")
    assert "AGENTS.md" in cursor and cursor.count("\n") <= 6
    assert sorted(p.name for p in (ROOT / ".cursor" / "rules").iterdir()) == ["00-always.mdc"]
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in claude and claude.count("\n") <= 4
    skill = (ROOT / ".claude" / "skills" / "drift-audit" / "SKILL.md").read_text(encoding="utf-8")
    assert "AGENT_OPERATING_PROCESS_V1.md" in skill and "Phase 3" not in skill
    process = (ROOT / "governance" / "AGENT_OPERATING_PROCESS_V1.md").read_text(encoding="utf-8")
    assert "## 8. SIGN-OFF CHECKLIST" in process
    assert "launch / pre-push / CI). This file" not in process


# test_no_code_owner_file_exists_rc530 was deleted 2026-09-11 (RC-550): it forbade a CODEOWNERS
# file on the premise that no reviewer identity exists. A CODEOWNERS review by an identity the
# coding agent does not hold is the only native GitHub boundary that stops a candidate from
# weakening its own judge (attack matrix on b0bb211f/1a2eaafe, RC-539); a test that refuses
# the boundary is not a control.
