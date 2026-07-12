#!/usr/bin/env python3
"""Mission authorization contract + active-mission ownership registry
(GOV_BRANCH_AUTHORIZATION_AND_MULTI_AGENT_OWNERSHIP_V1).

Root incident (2026-07-12): an agent began work on an undeclared branch,
treated a checked-out `main` as authorization, pushed feature commits directly
to protected `main` via admin bypass (enforce_admins disabled), ignored the
PR-required bypass warning, and pushed again after main went red — while a
sibling agent was active on shared governance surfaces with no ownership
registry.

Design law (fail-closed everywhere):
  CAN_PUSH        != AUTHORIZED_TO_PUSH
  GIT_EXIT_ZERO   != POLICY_PASS
  BYPASS_AVAILABLE != BYPASS_APPROVED
No field defaults to main, direct push, broad scope, or integration authority.
Missing/stale/malformed/expired/consumed authorization refuses.

Artifacts (single canonical location):
  governance/mission_authorization/active/<MISSION_ID>.json   — live contracts
  governance/mission_authorization/consumed/<MISSION_ID>.json — one-time
      integration authorizations after use
  governance/mission_authorization/incidents/*.json           — policy
      violations + red-main breaker states
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTH_DIR = REPO_ROOT / "governance" / "mission_authorization"
ACTIVE_DIR = AUTH_DIR / "active"
CONSUMED_DIR = AUTH_DIR / "consumed"
INCIDENT_DIR = AUTH_DIR / "incidents"

SCHEMA_VERSION = "1"
MISSION_TYPES = (
    "feature_implementation",
    "audit_only",
    "controlled_integration",
    "emergency_operator_remediation",
)
# Semantic ownership domains — overlap detection is NOT filename-only.
SEMANTIC_DOMAINS = (
    "governance_gates",
    "model_loading",
    "model_promotion",
    "generated_inventories",
    "closure_schema",
    "board_state",
    "evidence_lifecycle",
    "shared_runtime_infrastructure",
)
REQUIRED_FIELDS = (
    "schema_version", "mission_id", "agent", "mission_type",
    "authorized_branch", "authorized_worktree", "base_sha",
    "authorized_push_target", "target_branch", "direct_main_permission",
    "pr_required", "integration_owner", "authorized_scope",
    "shared_file_policy", "lease_state", "created_at_epoch",
    "expires_at_epoch", "operator_authorization", "allowed_integration_method",
    "required_checks", "stop_conditions",
)
BYPASS_WARNING_PATTERNS = (
    re.compile(r"bypass", re.IGNORECASE),
    re.compile(r"protected branch", re.IGNORECASE),
    re.compile(r"rule violations", re.IGNORECASE),
    re.compile(r"forced update", re.IGNORECASE),
    re.compile(r"administrator", re.IGNORECASE),
)


def _git(args: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd or REPO_ROOT), capture_output=True,
        text=True, timeout=60,
    )
    return r.stdout.strip()


def load_contract(mission_id: str) -> tuple[dict | None, str]:
    """Load an ACTIVE contract. Returns (contract, reason). Fail-closed on
    missing/malformed/expired/consumed/revoked — never defaults."""
    p = ACTIVE_DIR / f"{mission_id}.json"
    if (CONSUMED_DIR / f"{mission_id}.json").is_file():
        return None, f"authorization {mission_id} already CONSUMED (single-use)"
    if not p.is_file():
        return None, f"authorization {mission_id} missing at {p}"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"authorization {mission_id} malformed: {exc}"
    missing = [f for f in REQUIRED_FIELDS if f not in doc]
    if missing:
        return None, f"authorization {mission_id} missing fields {missing} (no defaults)"
    if str(doc.get("schema_version")) != SCHEMA_VERSION:
        return None, f"authorization {mission_id} schema_version mismatch"
    if doc.get("mission_type") not in MISSION_TYPES:
        return None, f"authorization {mission_id} unknown mission_type"
    if doc.get("lease_state") != "active":
        return None, f"authorization {mission_id} lease_state={doc.get('lease_state')!r} (revoked/stale)"
    try:
        if float(doc["expires_at_epoch"]) < time.time():
            return None, f"authorization {mission_id} EXPIRED"
    except (TypeError, ValueError):
        return None, f"authorization {mission_id} invalid expiry"
    # Broad-default rejection: a feature mission may never carry main powers.
    if doc["mission_type"] != "controlled_integration":
        if doc.get("direct_main_permission") is True:
            return None, "direct_main_permission=true is only valid on controlled_integration"
        if doc.get("target_branch") == "main" or doc.get("authorized_branch") == "main":
            return None, "feature/audit missions may not target or work on main"
    if doc.get("authorized_scope") in ("*", "", None, "all"):
        return None, "authorized_scope must be explicit (broad defaults refused)"
    return doc, "ok"


def validate_workspace(contract: dict, *, cwd: Path) -> list[str]:
    """Pre-edit gate: branch, worktree, ancestry. Nonzero errors on ambiguity."""
    errors: list[str] = []
    branch = _git(["branch", "--show-current"], cwd=cwd)
    if branch != contract["authorized_branch"]:
        errors.append(
            f"current branch {branch!r} != authorized {contract['authorized_branch']!r} "
            "(a checked-out branch is NEVER authorization)"
        )
    wt = _git(["rev-parse", "--show-toplevel"], cwd=cwd).replace("\\", "/").rstrip("/")
    auth_wt = str(contract["authorized_worktree"]).replace("\\", "/").rstrip("/")
    if wt.lower() != auth_wt.lower():
        errors.append(f"worktree {wt!r} != authorized {auth_wt!r}")
    base = contract["base_sha"]
    head = _git(["rev-parse", "HEAD"], cwd=cwd)
    anc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, head],
        cwd=str(cwd), capture_output=True, timeout=60,
    ).returncode
    if anc != 0:
        errors.append(f"HEAD {head[:12]} is not a descendant of authorized base {base[:12]}")
    return errors


def validate_push_destination(
    contract: dict, *, stdin_lines: list[str], remote_url: str | None
) -> list[str]:
    """Pre-push gate on the ACTUAL destination refs (git pre-push stdin:
    '<local-ref> <local-sha> <remote-ref> <remote-sha>'). Fail-closed when the
    destination cannot be established."""
    errors: list[str] = []
    if not stdin_lines:
        errors.append(
            "push destination refs unavailable (no pre-push stdin) — fail closed; "
            "push via the standard git pre-push hook path"
        )
        return errors
    for line in stdin_lines:
        parts = line.split()
        if len(parts) != 4:
            errors.append(f"unparseable pre-push ref line: {line!r} (fail closed)")
            continue
        _lref, _lsha, remote_ref, _rsha = parts
        if remote_ref == "refs/heads/main":
            if contract["mission_type"] != "controlled_integration":
                errors.append(
                    "destination refs/heads/main but mission_type != controlled_integration"
                )
            if contract.get("direct_main_permission") is not True:
                errors.append("destination refs/heads/main without explicit direct_main_permission=true")
            if contract.get("pr_required") is True:
                errors.append("pr_required=true forbids direct main update")
        else:
            expected = f"refs/heads/{contract['authorized_branch']}"
            if remote_ref != expected:
                errors.append(
                    f"destination {remote_ref!r} != authorized target {expected!r}"
                )
    return errors


def classify_push_output(output: str) -> list[str]:
    """Bypass-warning detector: exit-zero pushes carrying protection-bypass
    language are MATERIAL POLICY EVENTS, never successes."""
    hits = []
    for pat in BYPASS_WARNING_PATTERNS:
        for line in output.splitlines():
            if pat.search(line):
                hits.append(line.strip()[:200])
    return sorted(set(hits))


def record_policy_violation(mission_id: str, kind: str, detail: dict) -> Path:
    INCIDENT_DIR.mkdir(parents=True, exist_ok=True)
    p = INCIDENT_DIR / f"{mission_id}.{kind}.{int(time.time())}.json"
    p.write_text(
        json.dumps(
            {"mission_id": mission_id, "kind": kind, "detail": detail,
             "recorded_at": time.time(), "closure_blocked": True},
            indent=2, sort_keys=True, default=str,
        ),
        encoding="utf-8",
    )
    return p


def red_main_breaker_engaged() -> tuple[bool, str]:
    """Any unresolved red-main incident blocks ALL mission pushes until the
    operator clears it (distinct from ordinary feature-branch red CI)."""
    if not INCIDENT_DIR.is_dir():
        return False, ""
    for p in sorted(INCIDENT_DIR.glob("*.red_main.*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True, f"unreadable red-main incident {p.name} (fail closed)"
        if not doc.get("operator_cleared"):
            return True, f"red-main breaker engaged: {p.name}"
    return False, ""


def consume_integration_authorization(mission_id: str) -> tuple[bool, str]:
    """Single-use: move active → consumed atomically. Reuse refuses."""
    src = ACTIVE_DIR / f"{mission_id}.json"
    dst = CONSUMED_DIR / f"{mission_id}.json"
    if dst.is_file():
        return False, "authorization already consumed"
    if not src.is_file():
        return False, "authorization not found"
    doc = json.loads(src.read_text(encoding="utf-8"))
    if doc.get("mission_type") != "controlled_integration":
        return False, "only controlled_integration authorizations are consumable"
    doc["lease_state"] = "consumed"
    doc["consumed_at_epoch"] = time.time()
    CONSUMED_DIR.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(doc, indent=2, sort_keys=True, default=str), encoding="utf-8")
    src.unlink()
    return True, "consumed"


def detect_mission_overlap(contract: dict) -> list[str]:
    """Registry overlap: branch, worktree, file scope, semantic domains, shared
    generated artifacts. Unknown/ambiguous scope on a sibling → stop."""
    errors: list[str] = []
    if not ACTIVE_DIR.is_dir():
        return errors
    mine_files = set(contract.get("authorized_scope", {}).get("files", []))
    mine_domains = set(contract.get("authorized_scope", {}).get("semantic_domains", []))
    unknown_mine = mine_domains - set(SEMANTIC_DOMAINS)
    if unknown_mine:
        errors.append(f"unknown semantic domain(s) {sorted(unknown_mine)} (fail closed)")
    for p in ACTIVE_DIR.glob("*.json"):
        try:
            other = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append(f"unreadable sibling contract {p.name} (fail closed)")
            continue
        if other.get("mission_id") == contract.get("mission_id"):
            continue
        if other.get("lease_state") != "active":
            continue
        if other.get("authorized_branch") == contract.get("authorized_branch"):
            errors.append(f"branch collision with {other.get('mission_id')}")
        if str(other.get("authorized_worktree", "")).lower() == str(
            contract.get("authorized_worktree", "")
        ).lower():
            errors.append(f"worktree collision with {other.get('mission_id')}")
        oscope = other.get("authorized_scope") or {}
        ofiles = set(oscope.get("files", []))
        odomains = set(oscope.get("semantic_domains", []))
        if not ofiles and not odomains:
            errors.append(
                f"sibling {other.get('mission_id')} has UNDECLARED scope — operator resolution required"
            )
        if mine_files & ofiles:
            errors.append(
                f"file overlap with {other.get('mission_id')}: {sorted(mine_files & ofiles)[:4]}"
            )
        if mine_domains & odomains:
            errors.append(
                f"semantic domain overlap with {other.get('mission_id')}: {sorted(mine_domains & odomains)}"
            )
        if other.get("target_branch") == contract.get("target_branch") and contract.get(
            "mission_type"
        ) == "controlled_integration":
            errors.append(f"conflicting integration target with {other.get('mission_id')}")
    return errors


def validate_mission_document_text(text: str) -> list[str]:
    """Prompt/mission-generation lock: an implementation mission document must
    declare every authorization field; missing branch details must never
    default to the checked-out branch."""
    required_markers = (
        "AUTHORIZED_AGENT", "AUTHORIZED_FEATURE_BRANCH", "AUTHORIZED_WORKTREE",
        "EXPECTED_BASE_SHA", "AUTHORIZED_PUSH_TARGET", "DIRECT_MAIN_PUSH",
        "PR_REQUIRED", "MAIN_INTEGRATION_OWNER",
    )
    missing = [m for m in required_markers if m not in text]
    errors = [f"mission document missing {m}" for m in missing]
    if "AUTHORIZED_FEATURE_BRANCH" in text:
        m = re.search(r"AUTHORIZED_FEATURE_BRANCH\s*=\s*(\S+)", text)
        if not m or m.group(1).lower() in ("main", "current", "checked-out"):
            errors.append("AUTHORIZED_FEATURE_BRANCH must be an explicit non-main branch")
    return errors
