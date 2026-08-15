"""Mine governance/root_cause_log.md for lock-enforcement failure incidents.

One RC row = one incident. Classification is keyword-based on DEFECT+5WHY.
Writes reports/locks_violation_audit_v1.json.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RC_LOG = ROOT / "governance" / "root_cause_log.md"
OUT = ROOT / "reports" / "locks_violation_audit_v1.json"

# Tight patterns: prefer precision over recall. A lock-violation incident is an RC
# whose defect is that a governing law/lock was soft, bypassed, false-passed, or
# never machine-enforced — not every product bug that mentions "stale".
RULES: list[tuple[str, list[str]]] = [
    (
        "goodwill_instead_of_mechanical_lock",
        [
            r"goodwill",
            r"written law",
            r"no mechanical",
            r"NOT mechanized",
            r"never actually mechanized",
            r"depended on someone choosing",
            r"agent had to remember",
            r"prose as if",
            r"honest limit",
            r"AGENTS\.md with no mechanical",
            r"on agent goodwill",
            r"remember to run",
            r"not a LOCK",
            r"MECHANICAL LOCK",
            r"enforced only on the CONTENT",
            r"must be mechanical",
            r"cannot have you assuming",
        ],
    ),
    (
        "one_faucet_violation",
        [
            r"two faucets",
            r"THREE.*(faucet|spot|way|resolv)",
            r"multi-faucet",
            r"DIFFERENT spot",
            r"single.?source",
            r"one instrument.*two widths",
            r"two chains",
            r"TWO clocks",
            r"four different ways",
            r"THREE different ways",
            r"sixth site",
            r"two call sites each passed",
            r"multiple.*spot",
        ],
    ),
    (
        "stale_ui_presented_as_live",
        [
            r"presented as live",
            r"corpse",
            r"FROZEN at",
            r"chart decays",
            r"viewer-scoped",
            r"bar lag",
            r"111\.?\d* hours",
            r"scorecard.*stale",
            r"live.*coach",
            r"NOTHING RUNS IT",
        ],
    ),
    (
        "false_completion_overclaim",
        [
            r"DID NOT WORK",
            r"reported fixed",
            r"reported complete",
            r"described.*delivered",
            r"called complete",
            r"fix was reported",
            r"after being reported fixed",
        ],
    ),
    (
        "soft_cadence_unenforced",
        [
            r"NOTHING RUNS IT",
            r"never scheduled",
            r"cadence exists only",
            r"exists only in the artifact",
        ],
    ),
    (
        "lock_blind_or_optional_detector",
        [
            r"no tool can answer",
            r"unfalsifiable",
            r"enumeration can only",
            r"documented.*blind",
            r"HONEST LIMIT",
            r"REPORT the agent had to remember",
            r"no gate and no hook",
            r"optional",
        ],
    ),
    (
        "never_exercised_end_to_end",
        [
            r"never exercised",
            r"never actually mechanized",
            r"never actually ran",
        ],
    ),
    (
        "fixed_count_not_authority",
        [
            r"CHAIN_STRIKE_COUNT",
            r"strikeCount=20",
            r"fixed literal cannot",
            r"fixed table was wrong",
            r"LOW_CONFIDENCE while wider",
        ],
    ),
    (
        "ratchet_or_counter_misuse",
        [
            r"debt_ratchet",
            r"COUNT DELTA",
        ],
    ),
    (
        "unlocked_command_or_agent_law",
        [
            r"operator's ruling was explicit",
            r"operator mandated",
            r"must be in the hooks",
            r"\.cursor/rules",
            r"Cursor soft",
            r"agent narrative, not a measurement",
        ],
    ),
]

# Classes that count as "lock enforcement failure" (primary audit set).
PRIMARY = {
    "goodwill_instead_of_mechanical_lock",
    "one_faucet_violation",
    "false_completion_overclaim",
    "soft_cadence_unenforced",
    "lock_blind_or_optional_detector",
    "never_exercised_end_to_end",
    "unlocked_command_or_agent_law",
    "ratchet_or_counter_misuse",
    "fixed_count_not_authority",
    "stale_ui_presented_as_live",
}


def classify(defect: str, five: str) -> list[str]:
    blob = f"{defect} {five}"
    hit: list[str] = []
    for name, pats in RULES:
        for p in pats:
            if re.search(p, blob, re.I):
                hit.append(name)
                break
    return sorted(set(hit))


def parse_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("| RC-"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 6:
            continue
        rid, status, opened, due, defect, five = parts[:6]
        if not re.match(r"RC-\d+$", rid):
            continue
        if status.lower() == "status":
            continue
        rows.append(
            {
                "id": rid,
                "status": status,
                "opened": opened,
                "due": due,
                "defect": defect,
                "five_why": five,
                "classes": classify(defect, five),
            }
        )
    return rows


def main() -> None:
    rows = parse_rows(RC_LOG.read_text(encoding="utf-8"))
    for r in rows:
        r["primary_classes"] = [c for c in r["classes"] if c in PRIMARY]
        r["is_lock_enforcement_failure"] = bool(r["primary_classes"])
    lock_rows = [r for r in rows if r["is_lock_enforcement_failure"]]
    by_class = Counter()
    for r in lock_rows:
        for c in r["primary_classes"]:
            by_class[c] += 1
    open_lock = [r for r in lock_rows if r["status"] == "OPEN"]
    open_all = [r for r in rows if r["status"] == "OPEN"]
    ids = sorted(lock_rows, key=lambda r: int(r["id"].split("-")[1]))

    out = {
        "schema": "locks_violation_audit_v1",
        "method": (
            "Parse governance/root_cause_log.md table; tight keyword-classify DEFECT+5WHY. "
            "One RC = one incident. Counts are exact RC counts for this taxonomy. "
            "Precision-biased: product bugs without lock/enforcement language are excluded."
        ),
        "universe": {
            "total_rc_rows": len(rows),
            "lock_enforcement_failure_rcs": len(lock_rows),
            "untagged_rcs": len(rows) - len(lock_rows),
        },
        "status_split": {
            "lock_failure_open": len(open_lock),
            "lock_failure_closed": sum(1 for r in lock_rows if r["status"] == "CLOSED"),
            "all_open": len(open_all),
        },
        "by_class_rc_count": dict(by_class.most_common()),
        "lock_failure_ids": [r["id"] for r in ids],
        "open_lock_violations": [
            {
                "id": r["id"],
                "due": r["due"],
                "classes": r["primary_classes"],
                "defect": r["defect"],
            }
            for r in open_lock
        ],
        "open_all": [
            {
                "id": r["id"],
                "due": r["due"],
                "classes": r["primary_classes"],
                "defect": r["defect"][:400],
            }
            for r in open_all
        ],
        "catalog": [
            {
                "id": r["id"],
                "status": r["status"],
                "opened": r["opened"],
                "due": r["due"],
                "classes": r["primary_classes"],
                "defect": r["defect"],
            }
            for r in ids
        ],
        "enforcement_gap_themes": [
            "Laws lived in AGENTS.md / Cursor rules / operator chat without a gate that fails the build or blocks the page.",
            "Producer locks (server single_spot) passed while consumer/client multi-faucet defects remained invisible.",
            "Reports and detectors existed but were optional (must remember to run) or had documented blind spots treated as discharge.",
            "Cadence jobs (scorecard) declared but never scheduled — soft ops masquerading as system behavior.",
            "False completion: fix claimed before adversarial re-measure; detector green while screen wrong.",
        ],
        "live_gate_snapshot_note": (
            "Institutional ENFORCED checks currently PASS (33); ADVISORY debt remains "
            "(complexity/length/ruff/mypy/orphan_dict/debt_ratchet). Soft laws (scorecard "
            "cadence, client spot authority honesty) are outside ENFORCED set unless hooked."
        ),
        "tighten_first": [
            {
                "rank": 1,
                "law": "Client/page single spot authority",
                "why": "RC-14/15/29/75/76/77 — producer lock green, screen still multi-faucet",
                "mechanize": "AST/client faucet check in pre-commit + faucet audit FAIL blocks CI",
            },
            {
                "rank": 2,
                "law": "Scorecard / coach freshness cadence",
                "why": "RC-70 OPEN — NOTHING RUNS the daily scorecard; UI still reads file as live",
                "mechanize": "Scheduler OR endpoint refuses file older than N trading hours with explicit STALE",
            },
            {
                "rank": 3,
                "law": "No optional provenance report",
                "why": "RC-73/74 — report without hook = unlocked law",
                "mechanize": "data_faucet_audit in pre-commit/CI as ENFORCED for chart+console surfaces",
            },
            {
                "rank": 4,
                "law": "False-completion / detector blind spots",
                "why": "RC-15/76 — green detector + wrong screen",
                "mechanize": "Forbid shipping detectors with documented blind spots; require screen-level fixture",
            },
            {
                "rank": 5,
                "law": "AGENTS.md laws without gates",
                "why": "RC-41/49/53/56 — written law treated as lock",
                "mechanize": "Any new AGENTS law must name check id or be labeled SOFT explicitly",
            },
        ],
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print("total_rc", len(rows), "lock_failures", len(lock_rows), "open_lock", len(open_lock))
    print("by_class", dict(by_class.most_common()))
    print("ids", [r["id"] for r in ids])


if __name__ == "__main__":
    main()
