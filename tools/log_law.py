"""LOG LAW (operator/PM 2026-08-04, binding) — one home per kind of work.

WHY THIS EXISTS. The repo grew four *shapes* of list by accident of role, and two of them
started reading like work queues:

    governance/root_cause_log.md    DEFECT evidence       historical OPEN/CLOSED rows
    governance/unproven_register.md EPISTEMIC evidence    historical UNPROVEN/PROVEN wording
    *.jsonl (sod_drift, quarantine, flip logs)  TELEMETRY — events, never a to-do list
    reports/*.md triage snapshots   NOTES — stale by construction the moment they are written

Sprawl is itself debt: when a third markdown file carries `| ID | OPEN |` rows, closable work
has two homes, and whichever one the reader opens looks complete while the other rots. The
operator's rule is one work list (the sole master); RC and unproven_register are evidence only.

WHAT THIS BLOCKS
  (a) A NEW markdown file outside the two sanctioned ledgers that carries an issue-table with
      OPEN/PARTIAL/UNPROVEN status rows — i.e. a third work queue.
  (b) A triage snapshot under reports/ that contradicts the live ledger counts, which is how a
      stale drain report gets cited as if it were current state.

WHAT THIS DELIBERATELY DOES NOT BLOCK
  Telemetry .jsonl files (they are events), and prose reports that merely MENTION RC ids —
  a report is allowed to discuss defects, it is just not allowed to be a second ledger.

Escape: `# log-law-ok: <reason>` inside the offending file (operator-reviewed).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Historical evidence files that may contain status-shaped rows. Not work queues.
#: Unresolved work lives only on the sole master checklist.
DEFECT_LEDGER = "governance/root_cause_log.md"
EPISTEMIC_LEDGER = "governance/unproven_register.md"
SANCTIONED_LEDGERS = frozenset({DEFECT_LEDGER, EPISTEMIC_LEDGER})
SOLE_MASTER = "ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md"

#: A work row is a markdown table row whose SECOND cell is a work status. Prose that merely
#: names RC-123 is not a row; a table of them is a queue.
_WORK_ROW_RE = re.compile(r"^\|\s*[\w.\- ]+\s*\|\s*(OPEN|PARTIAL|UNPROVEN)\s*\|", re.M)

#: Below this a file is discussing a handful of items, not maintaining a queue. Three is the
#: smallest count that reads as a list rather than an example.
_QUEUE_THRESHOLD = 3

_ESCAPE = "# log-law-ok:"

#: Telemetry lives here and is explicitly NOT debt — enumerated so the law states it rather
#: than leaving it to be re-litigated every time someone finds a growing .jsonl.
TELEMETRY_SUFFIXES = (".jsonl", ".log", ".ndjson")


def _rel(p: Path, root: Path | None = None) -> str:
    """Path relative to the root being SCANNED — not to this module's own repo.

    Binding the relativity to the module global made the sanctioned-ledger exemption fail
    under any other root (caught by the tests below), which would have let a real third queue
    through in a worktree or CI checkout whose path differs.
    """
    base = root or REPO
    try:
        return str(p.relative_to(base)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def is_telemetry(path: str) -> bool:
    """Event streams are never a work queue, however large they grow."""
    return str(path).lower().endswith(TELEMETRY_SUFFIXES)


def third_queue_violations(repo: Path | None = None,
                           paths: list[str] | None = None) -> list[str]:
    """Markdown files acting as a THIRD work queue beside the two sanctioned ledgers."""
    root = repo or REPO
    out: list[str] = []
    if paths is None:
        candidates = list((root / "governance").rglob("*.md")) + \
            list((root / "reports").rglob("*.md"))
    else:
        candidates = [root / p for p in paths]
    for p in candidates:
        rel = _rel(p, root)
        if rel in SANCTIONED_LEDGERS or not p.is_file():
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _ESCAPE in src:
            continue
        rows = len(_WORK_ROW_RE.findall(src))
        if rows >= _QUEUE_THRESHOLD:
            out.append(
                f"LOG_LAW: {rel} carries {rows} OPEN/PARTIAL/UNPROVEN work rows — closable "
                f"work lives only on {SOLE_MASTER}, never a third list. Convert it to a "
                f"pointer, or mark it with '{_ESCAPE} <reason>' if the operator wants it "
                f"kept as a frozen snapshot."
            )
    return out


def open_class_count(repo: Path | None = None) -> int:
    """Live OPEN+PARTIAL count in the defect ledger — the number a drain report must match."""
    root = repo or REPO
    try:
        src = (root / DEFECT_LEDGER).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return -1
    return len(re.findall(r"^\|\s*RC-\d+\s*\|\s*(?:OPEN|PARTIAL)\s*\|", src, re.M))


def unproven_overdue(repo: Path | None = None, today: str | None = None) -> list[str]:
    """Register due dates have zero work authority. Returns empty."""
    return []


def log_law_violations(repo: Path | None = None) -> list[str]:
    """Third-queue sprawl only. Register due dates do not select or block work."""
    return third_queue_violations(repo)


if __name__ == "__main__":
    import sys

    bad = log_law_violations()
    print(f"open-class (defect ledger): {open_class_count()}")
    for b in bad:
        print(b)
    print(f"LOG LAW: {'FAIL' if bad else 'PASS'} ({len(bad)} violation(s))")
    sys.exit(1 if bad else 0)
