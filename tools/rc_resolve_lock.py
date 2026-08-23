"""RC document-without-resolve lock (RC-228).

Operator law 2026-08-03: writers must not leave a growing backlog of OPEN/PARTIAL
documentation. Opening an RC is required (front-loaded five-why); parking it without a
named resolve path, or claiming mission COMPLETE while mission-owned OPEN rows remain,
is the defect this lock detects.

Clauses (both ENFORCED via check_rc_document_without_resolve):
  A) A newly ADDED OPEN RC row must name a resolve path in the fix cell
     (FIXED: / NEXT-DEPTH: / OUT-OF-SCOPE:). Empty / TBD / TODO parking lots BLOCK.
  B) Staging pm_mission.json into a terminal status (DONE / COMPLETE / idle) while any
     RC row that mentions that mission_id is still OPEN BLOCKs. Honest PARTIAL with
     OUT-OF-SCOPE: + tracker is legal; mass-fake CLOSE is not.

Architecture A (RC-450): ED_RC_RESOLVE_GUARD cannot disable this control.
`# mission-rc-open-ok:` remains a visible mission-text marker for clause B only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

RC_LOG_REL = "governance/root_cause_log.md"
PM_MISSION_REL = "governance/pm_mission.json"

RESOLVE_MARKERS = ("FIXED:", "NEXT-DEPTH:", "OUT-OF-SCOPE:")
PARKING_FIXES = frozenset({
    "", "tbd", "todo", "fixme", "...", ".", "open", "none", "n/a", "na",
    "pending", "later", "wip",
})

TERMINAL_MISSION_STATUSES = frozenset({
    "done", "complete", "completed", "idle", "closed",
})
IN_PROGRESS_MISSION_STATUSES = frozenset({
    "active", "ready_for_writer", "ready_for_claude", "ready_for_cursor",
    "in_progress", "in-progress",
})

_ESCAPE = "# mission-rc-open-ok:"


def _norm_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_rc_row(line: str) -> dict | None:
    """Parse a `| RC-` table row into a dict, or None if too short."""
    if not line.startswith("| RC-"):
        return None
    cells = _norm_cells(line)
    if len(cells) < 7:
        return None
    return {
        "id": cells[0],
        "status": cells[1].upper(),
        "opened": cells[2],
        "due": cells[3],
        "defect": cells[4],
        "why": cells[5],
        "fix": cells[6],
        "line": line,
    }


def open_row_missing_resolve_path(status: str, fix_cell: str) -> str | None:
    """Clause A pure predicate: OPEN row whose fix cell is a parking lot → reason."""
    if (status or "").strip().upper() != "OPEN":
        return None
    fix = (fix_cell or "").strip()
    if fix.lower() in PARKING_FIXES:
        return "empty/parking-lot fix cell (no FIXED:/NEXT-DEPTH:/OUT-OF-SCOPE:)"
    up = fix.upper()
    if any(m in up for m in RESOLVE_MARKERS):
        return None
    return (
        "OPEN without FIXED:/NEXT-DEPTH:/OUT-OF-SCOPE: resolve path in the fix cell "
        "(document-without-resolve — open the row AND name how it closes)"
    )


def added_open_rows_without_resolve(added_lines: list[str]) -> list[str]:
    """Clause A over staged '+| RC-' lines (leading '+' already stripped)."""
    out: list[str] = []
    for raw in added_lines:
        line = raw if raw.startswith("|") else f"| {raw.lstrip()}"
        # Normalise to a single leading '| RC-' even if the diff stripped oddly.
        if not line.startswith("| RC-"):
            m = re.search(r"\| RC-\d+", line)
            if m:
                line = line[m.start():]
            elif line.lstrip("| ").startswith("RC-"):
                line = "| " + line.lstrip("| ")
            else:
                continue
        row = parse_rc_row(line)
        if not row:
            continue
        reason = open_row_missing_resolve_path(row["status"], row["fix"])
        if reason:
            out.append(f"{row['id']}: {reason}")
    return out


def _mission_status(doc: dict | None) -> str:
    if not doc:
        return ""
    return str(doc.get("status") or "").strip().lower()


def mission_becoming_terminal(old: dict | None, new: dict | None) -> bool:
    """True when staged mission moves into a terminal status from in-progress (or anew)."""
    new_s = _mission_status(new)
    if new_s not in TERMINAL_MISSION_STATUSES:
        return False
    old_s = _mission_status(old)
    if not old_s:
        return True
    if old_s in TERMINAL_MISSION_STATUSES and old_s == new_s:
        return False  # no transition — leave alone
    return old_s in IN_PROGRESS_MISSION_STATUSES or old_s not in TERMINAL_MISSION_STATUSES


def open_rcs_owned_by_mission(mission_id: str, rc_lines: list[str]) -> list[str]:
    """OPEN rows whose defect/why/fix mention mission_id (case-insensitive)."""
    mid = (mission_id or "").strip()
    if not mid:
        return []
    needle = mid.lower()
    out: list[str] = []
    for line in rc_lines:
        row = parse_rc_row(line)
        if not row or row["status"] != "OPEN":
            continue
        blob = f"{row['defect']} {row['why']} {row['fix']}".lower()
        if needle in blob:
            out.append(row["id"])
    return out


def mission_complete_open_rc_violations(
    old_mission: dict | None,
    new_mission: dict | None,
    rc_lines: list[str],
    *,
    staged_mission_text: str = "",
) -> list[str]:
    """Clause B: terminal mission while OPEN RCs name that mission_id → violations."""
    if _ESCAPE in (staged_mission_text or ""):
        return []
    if not mission_becoming_terminal(old_mission, new_mission):
        return []
    mid = str((new_mission or {}).get("mission_id") or "").strip()
    if not mid:
        return ["pm_mission.json becoming terminal without mission_id — cannot bind RC ownership"]
    open_ids = open_rcs_owned_by_mission(mid, rc_lines)
    if not open_ids:
        return []
    return [
        f"mission {mid!r} status->{_mission_status(new_mission)!r} while OPEN RC(s) still name "
        f"that mission: {', '.join(open_ids)}. CLOSE with FIXED reach, or honest PARTIAL + "
        f"OUT-OF-SCOPE: tracker — do not mass-fake CLOSE (RC-228). Escape: {_ESCAPE} <reason>"
    ]


def staged_rc_resolve_violations(
    *,
    added_rc_lines: list[str],
    old_mission: dict | None,
    new_mission: dict | None,
    rc_file_lines: list[str],
    staged_mission_text: str = "",
) -> list[str]:
    """Combine clause A + B for the commit checker / negative controls."""
    out: list[str] = []
    out.extend(added_open_rows_without_resolve(added_rc_lines))
    out.extend(mission_complete_open_rc_violations(
        old_mission, new_mission, rc_file_lines,
        staged_mission_text=staged_mission_text,
    ))
    return out


def load_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}
