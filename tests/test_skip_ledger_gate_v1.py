"""Skip-transparency gate -- proof the checker actually catches an unreviewed skip, and
does not false-positive on the two legitimate categories (self-declared, ledgered).

See tools/check_skip_ledger.py's module docstring for why this exists and why it consumes
JUnit XML rather than a conftest hook (verified directly: a pytest_sessionfinish hook's
session.exitstatus mutation did not affect the process exit code under xdist)."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_skip_ledger import find_unlisted_skips  # noqa: E402

_LEDGER = [
    {"file": "tests/test_delta_adds_no_debt_v1.py",
     "reason_contains": "this sandbox account cannot create symlinks"},
]


def _write_junit(tmp_path: Path, cases: list[tuple[str, str, str | None]]) -> Path:
    """cases: (classname, name, skip_message_or_None)."""
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for classname, name, msg in cases:
        tc = ET.SubElement(suite, "testcase", classname=classname, name=name)
        if msg is not None:
            ET.SubElement(tc, "skipped", message=msg)
    p = tmp_path / "report.xml"
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)
    return p


def _write_ledger(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "skip_ledger.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def test_a_self_declared_production_data_skip_is_never_a_violation(tmp_path):
    xml = _write_junit(tmp_path, [
        ("tests.test_pred_1c_eddb_and_audit_contract_v1", "test_x",
         "PRODUCTION-DATA-ONLY: canonical DB not present in workspace"),
    ])
    ledger = _write_ledger(tmp_path, [])
    assert find_unlisted_skips(xml, ledger) == []


def test_an_exact_ledgered_skip_is_never_a_violation(tmp_path):
    xml = _write_junit(tmp_path, [
        ("tests.test_delta_adds_no_debt_v1", "test_symlink_thing",
         "this sandbox account cannot create symlinks (CI's ubuntu-latest runner can)"),
    ])
    ledger = _write_ledger(tmp_path, _LEDGER)
    assert find_unlisted_skips(xml, ledger) == []


def test_the_mutation_this_gate_exists_to_catch():
    """The actual regression class: a NEW skip appears, self-declares nothing, and is not
    reviewed anywhere. This must be caught, not silently pass through."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        xml = _write_junit(tmp_path, [
            ("tests.test_something_new_v1", "test_y", "oops, forgot to seed the fixture"),
        ])
        ledger = _write_ledger(tmp_path, _LEDGER)
        violations = find_unlisted_skips(xml, ledger)
        assert len(violations) == 1
        assert "test_something_new_v1" in violations[0]
        assert "oops, forgot to seed the fixture" in violations[0]


def test_a_ledger_entry_does_not_leak_to_an_unrelated_file(tmp_path):
    """A ledger entry is scoped to its file AND its reason -- it must not blanket-allow
    every skip in a different file that happens to share the substring."""
    xml = _write_junit(tmp_path, [
        ("tests.test_totally_unrelated_v1", "test_z",
         "this sandbox account cannot create symlinks (CI's ubuntu-latest runner can)"),
    ])
    ledger = _write_ledger(tmp_path, _LEDGER)
    violations = find_unlisted_skips(xml, ledger)
    assert len(violations) == 1, "a ledger entry leaked across files"


def test_passing_tests_are_never_flagged():
    """Only <skipped> testcases are inspected; a normal pass must never appear."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        xml = _write_junit(tmp_path, [("tests.test_fine_v1", "test_ok", None)])
        ledger = _write_ledger(tmp_path, [])
        assert find_unlisted_skips(xml, ledger) == []


def test_the_real_ledger_file_is_valid_json_with_required_keys():
    """Structural: the actual repo ledger, not a synthetic one, must stay well-formed."""
    real_ledger_path = REPO / "tests" / "skip_ledger.json"
    entries = json.loads(real_ledger_path.read_text(encoding="utf-8"))
    assert isinstance(entries, list) and entries, "the ledger must be a non-empty list"
    for entry in entries:
        assert set(entry) >= {"file", "reason_contains"}, entry
