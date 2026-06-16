#!/usr/bin/env python3
"""Verify Phase 3F evidence index + limitations index integrity."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EVIDENCE_JSON = REPO_ROOT / "governance" / "artifacts" / "EVIDENCE_INDEX.json"
LIMITATIONS_JSON = REPO_ROOT / "governance" / "artifacts" / "CURRENT_LIMITATIONS.json"
REVIEWER_README = REPO_ROOT / "governance" / "REVIEWER_README.md"

PROVEN_VERDICTS = frozenset({"proven", "partially_proven", "detected_not_prevented"})
BANNED_L5_PATTERN = re.compile(r"\bL5\b.*\b(proven|verified|enforced|complete)\b", re.IGNORECASE)
BANNED_GITHUB_VERIFIED = re.compile(
    r"github.*\b(verified|enforced|proven)\b(?!.*not)", re.IGNORECASE
)

REQUIRED_LIMITATION_IDS = frozenset(
    {
        "live_schwab_proof",
        "github_branch_protection",
        "required_status_checks",
        "no_verify_external",
        "manual_mutation_detection_only",
        "r012_route_gap",
        "l5_not_claimed",
    }
)


def run_reviewer_evidence_index_check() -> list[str]:
    errors: list[str] = []
    if not REVIEWER_README.is_file():
        errors.append("governance/REVIEWER_README.md: missing")
    if not EVIDENCE_JSON.is_file():
        errors.append(f"{EVIDENCE_JSON.relative_to(REPO_ROOT)}: missing — run python tools/_build_evidence_index.py")
        return errors
    if not LIMITATIONS_JSON.is_file():
        errors.append(
            f"{LIMITATIONS_JSON.relative_to(REPO_ROOT)}: missing — run python tools/_build_current_limitations.py"
        )
        return errors

    try:
        evidence = json.loads(EVIDENCE_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"EVIDENCE_INDEX.json: unreadable ({exc})")
        return errors

    try:
        limitations = json.loads(LIMITATIONS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"CURRENT_LIMITATIONS.json: unreadable ({exc})")
        return errors

    claims = evidence.get("claims") or []
    if not claims:
        errors.append("EVIDENCE_INDEX.json: claims[] empty")

    for claim in claims:
        if not isinstance(claim, dict):
            errors.append("EVIDENCE_INDEX.json: non-object claim row")
            continue
        cid = claim.get("claim_id") or "?"
        verdict = str(claim.get("verdict") or "")
        for field in ("claim", "evidence_artifact", "code_path", "regenerate_command", "verdict"):
            if not claim.get(field):
                errors.append(f"EVIDENCE_INDEX claim {cid}: missing {field}")
        if verdict in PROVEN_VERDICTS and not claim.get("test_path"):
            errors.append(f"EVIDENCE_INDEX claim {cid}: verdict={verdict} requires test_path")
        blob = json.dumps(claim)
        if BANNED_L5_PATTERN.search(blob):
            errors.append(f"EVIDENCE_INDEX claim {cid}: L5 claim without external/adversarial proof")
        if claim.get("claim_id") == "github_external_enforcement" and verdict not in (
            "required_not_proven",
            "unproven",
            "explicitly_rejected",
        ):
            errors.append(
                f"EVIDENCE_INDEX github_external_enforcement: verdict must be required_not_proven (got {verdict})"
            )

    lim_rows = limitations.get("limitations") or []
    lim_ids = {str(r.get("limitation_id")) for r in lim_rows if isinstance(r, dict)}
    missing_lim = REQUIRED_LIMITATION_IDS - lim_ids
    if missing_lim:
        errors.append(f"CURRENT_LIMITATIONS.json: missing required ids: {sorted(missing_lim)}")

    proposed = limitations.get("maturity_changes_proposed") or []
    if proposed:
        errors.append(f"CURRENT_LIMITATIONS maturity_changes_proposed must be empty (got {proposed})")

    for lim in lim_rows:
        if not isinstance(lim, dict):
            continue
        text = f"{lim.get('title')} {lim.get('detail')}"
        if BANNED_L5_PATTERN.search(text) and lim.get("limitation_id") != "l5_not_claimed":
            errors.append(f"CURRENT_LIMITATIONS {lim.get('limitation_id')}: implies L5 without rejection framing")

    rejected = limitations.get("maturity_changes_rejected") or []
    if not any("L5" in str(x) for x in rejected):
        errors.append("CURRENT_LIMITATIONS.json: maturity_changes_rejected must mention L5")

    no_l5 = [c for c in claims if c.get("claim_id") == "no_l5_claim"]
    if not no_l5 or no_l5[0].get("verdict") != "explicitly_rejected":
        errors.append("EVIDENCE_INDEX must include no_l5_claim with verdict explicitly_rejected")

    return errors


def main() -> int:
    errors = run_reviewer_evidence_index_check()
    if errors:
        for e in errors:
            print(f"check_reviewer_evidence_index: FAIL — {e}", file=sys.stderr)
        return 1
    print("check_reviewer_evidence_index: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
