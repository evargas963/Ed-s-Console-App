"""Skip-transparency gate (Phase 3.5 follow-up, 2026-09-20).

WHY THIS EXISTS. A full-suite run that reports "N passed, M skipped" was being read as
"green" without anyone checking what the M skips actually were. A direct audit found 8 of
10 skips in one run were tests whose real assertions had NEVER executed in ANY CI
environment -- neither pytest.yml nor hardening.yml provisions the canonical DB, a
populated snapshots DB, index.json, or the calibration accumulation-validation output five
specific test files depend on. That gap was invisible unless someone read `-rs` output by
hand and traced each reason.

THE MECHANISM. Every skip must be self-declaring or reviewed, never silent:
  - A reason containing the literal substring "PRODUCTION-DATA-ONLY" is self-declaring: a
    test whose real assertions need real production data this environment cannot fabricate
    without defeating the test's own purpose (synthesizing "governed prediction outcomes"
    or "a captured Schwab chain" would just test the author's assumptions, not reality).
    Any current or future test can use this convention with no ledger edit required.
  - Anything else must be an exact, reviewed entry in tests/skip_ledger.json (a PR-reviewed
    exception, same category as the CAPS gate's `# caps-ok:` markers -- a static,
    human-reviewed allowlist for a lint-style tool, not a runtime substitution of live data).
  - A skip matching NEITHER is a violation: something skipped that nobody has actually
    looked at and signed off on, which is exactly how the 8 gaps above stayed invisible.

WHY A JUNIT-XML-CONSUMING SCRIPT, NOT A CONFTEST HOOK. Tried first: a `pytest_sessionfinish`
hook in conftest.py mutating `session.exitstatus` after reading
`terminalreporter.stats["skipped"]`. Verified directly (a throwaway probe under
`-n 2 --dist loadfile`): the aggregated skip list WAS visible in the controller process, but
mutating `session.exitstatus` there did not change the final process exit code under xdist
-- confirmed empirically, not assumed. pytest's own `--junitxml` output is the standard,
well-supported aggregation format xdist already produces correctly for exactly this
purpose; consuming it as a separate, composable step matches this repo's own convention of
independent `tools/check_*.py` scripts (see hardening.yml) rather than fighting pytest/xdist
hook-ordering internals.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SELF_DECLARING_MARKER = "PRODUCTION-DATA-ONLY"


def _load_ledger(ledger_path: Path) -> list[dict]:
    return json.loads(ledger_path.read_text(encoding="utf-8"))


def _classname_and_message(testcase: ET.Element) -> tuple[str, str] | None:
    skipped = testcase.find("skipped")
    if skipped is None:
        return None
    classname = testcase.get("classname", "") or ""  # caps-ok: JUnit attribute; a blank classname yields a node id no ledger file stem matches, so the skip is reported
    name = testcase.get("name", "") or ""  # caps-ok: JUnit attribute; display part of the node id, never a pass condition
    message = skipped.get("message", "") or ""  # caps-ok: a skip with no message carries no PRODUCTION-DATA-ONLY marker and matches no reason_contains, so it is reported
    return f"{classname}::{name}", message


def _file_to_dotted_stem(file_path: str) -> str:
    """'tests/test_x_v1.py' -> 'tests.test_x_v1'. A suffix strip, not str.rstrip (which
    treats its argument as a character set, not a literal suffix, and would over-strip)."""
    stem = file_path[:-len(".py")] if file_path.endswith(".py") else file_path
    return stem.replace("/", ".")


def _is_ledgered(nodeid: str, message: str, ledger: list[dict]) -> bool:
    for entry in ledger:
        if _file_to_dotted_stem(entry["file"]) in nodeid.replace("/", ".") \
                and entry["reason_contains"] in message:
            return True
    return False


def find_unlisted_skips(junit_xml_path: Path, ledger_path: Path) -> list[str]:
    """Returns one human-readable violation string per skip that is neither self-declaring
    (PRODUCTION-DATA-ONLY) nor an exact reviewed entry in the ledger. Empty = clean."""
    ledger = _load_ledger(ledger_path)
    tree = ET.parse(junit_xml_path)
    violations = []
    for testcase in tree.iter("testcase"):
        parsed = _classname_and_message(testcase)
        if parsed is None:
            continue
        nodeid, message = parsed
        if SELF_DECLARING_MARKER in message:
            continue
        if _is_ledgered(nodeid, message, ledger):
            continue
        violations.append(
            f"{nodeid}: skipped with reason {message!r} -- neither self-declared "
            f"({SELF_DECLARING_MARKER}) nor listed in {ledger_path.name}. Either the test "
            f"is hiding a real gap, or this is a legitimate one-off that needs a reviewed "
            f"ledger entry."
        )
    return violations


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: check_skip_ledger.py <junit_xml_path> [ledger_path]", file=sys.stderr)
        return 2
    junit_xml_path = Path(argv[1])
    ledger_path = Path(argv[2]) if len(argv) > 2 else (
        Path(__file__).resolve().parent.parent / "tests" / "skip_ledger.json"
    )
    violations = find_unlisted_skips(junit_xml_path, ledger_path)
    if violations:
        print("SKIP LEDGER VIOLATIONS -- an unreviewed skip reached the suite:")
        for v in violations:
            print(f"  {v}")
        return 1
    print("skip ledger clean: every skip is self-declared or reviewed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
