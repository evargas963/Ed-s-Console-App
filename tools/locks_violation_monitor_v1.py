"""Snapshot lock-violation RC statuses; detect OPEN->CLOSED transitions.

Reads reports/locks_violation_audit_v1.json for the tracked set, parses
governance/root_cause_log.md, writes reports/locks_violation_monitor_v1.json.
Exit 0 always; prints a one-line STATUS for loops.

When newly_closed is non-empty, the monitoring agent MUST adversarially audit
each closed RC's claimed remedy (code + evidence + gate strength) before
accepting CLOSED as fixed — status flip alone is not proof.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "reports" / "locks_violation_audit_v1.json"
RC_LOG = ROOT / "governance" / "root_cause_log.md"
OUT = ROOT / "reports" / "locks_violation_monitor_v1.json"
PREV = ROOT / "reports" / "locks_violation_monitor_prev_v1.json"


def parse_rc_rows(text: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in text.splitlines():
        if not line.startswith("| RC-"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 6:
            continue
        rid = parts[0]
        if not re.match(r"RC-\d+$", rid):
            continue
        if parts[1].lower() == "status":
            continue
        rows[rid] = {
            "status": parts[1],
            "opened": parts[2],
            "due": parts[3],
            "defect": parts[4],
        }
    return rows


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    tracked = list(audit.get("lock_failure_ids") or audit.get("lock_tagged_ids") or [])
    rows = parse_rc_rows(RC_LOG.read_text(encoding="utf-8"))

    open_ids: list[str] = []
    closed_ids: list[str] = []
    missing: list[str] = []
    outstanding: list[dict] = []
    for rid in tracked:
        if rid not in rows:
            missing.append(rid)
            continue
        st = rows[rid]["status"]
        if st == "OPEN":
            open_ids.append(rid)
            outstanding.append(
                {
                    "id": rid,
                    "due": rows[rid]["due"],
                    "defect": rows[rid]["defect"][:240],
                }
            )
        else:
            closed_ids.append(rid)

    prev: dict = {}
    if PREV.exists():
        try:
            prev = json.loads(PREV.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    prev_open = set(prev.get("open_ids") or [])
    now_open = set(open_ids)
    newly_closed = sorted(prev_open - now_open, key=lambda x: int(x.split("-")[1]))
    newly_opened = sorted(now_open - prev_open, key=lambda x: int(x.split("-")[1]))

    all_open = sorted(
        [rid for rid, r in rows.items() if r["status"] == "OPEN"],
        key=lambda x: int(x.split("-")[1]),
    )
    adjacent_open = [rid for rid in all_open if rid not in set(tracked)]

    snap = {
        "schema": "locks_violation_monitor_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "tracked_count": len(tracked),
        "closed_count": len(closed_ids),
        "open_count": len(open_ids),
        "missing_count": len(missing),
        "all_fixed": len(open_ids) == 0 and len(missing) == 0,
        "open_ids": open_ids,
        "closed_ids": closed_ids,
        "missing": missing,
        "outstanding": outstanding,
        "newly_closed_since_prev": newly_closed,
        "newly_opened_since_prev": newly_opened,
        "adjacent_open_rcs_not_in_lock_set": adjacent_open,
        "prev_open_ids": sorted(prev_open, key=lambda x: int(x.split("-")[1]))
        if prev_open
        else [],
    }
    OUT.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    PREV.write_text(
        json.dumps({"open_ids": open_ids, "generated_utc": snap["generated_utc"]}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    status = "ALL_FIXED" if snap["all_fixed"] else "OUTSTANDING"
    print(
        f"LOCK_VIOLATION_MONITOR {status} "
        f"closed={len(closed_ids)}/{len(tracked)} "
        f"open={open_ids} "
        f"newly_closed={newly_closed} "
        f"newly_opened={newly_opened} "
        f"adjacent_open={adjacent_open}"
    )
    if snap["all_fixed"]:
        print("LOCK_VIOLATION_MONITOR_COMPLETE all tracked lock-failure RCs are CLOSED")


if __name__ == "__main__":
    main()
