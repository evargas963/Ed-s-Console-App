"""Remote enforcement evidence model — Phase 3D-Verification.

verified=true only for github_api | github_cli | exported_ruleset evidence.
operator_manual_attestation records operator claim; verified remains false.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
ART = REPO_ROOT / "governance" / "artifacts"
EVIDENCE_PATH = ART / "REMOTE_ENFORCEMENT_EVIDENCE.json"
ATTESTATION_TEMPLATE = ART / "REMOTE_ENFORCEMENT_OPERATOR_ATTESTATION.template.json"

API_VERIFIED_METHODS = frozenset({"github_api", "github_cli", "exported_ruleset"})
MANUAL_METHOD = "operator_manual_attestation"
PENDING_METHOD = "pending"

REMOTE_EVIDENCE_FIELDS: tuple[str, ...] = (
    "evidence_source",
    "evidence_timestamp",
    "repository",
    "protected_branch",
    "required_status_checks",
    "required_reviews",
    "allows_force_pushes",
    "allows_deletions",
    "bypass_actors",
    "verification_method",
    "verified_by",
)

OBJECTIVE_AUDIT_CHECK = "objective-audit"
DEFAULT_REPO = "evargas963/Ed-s-Console-App"
# Successful Objective Audit on feature/institutional-key-levels @ b084e71 (operator milestone).
DEFAULT_OBJECTIVE_AUDIT_RUN_ID = 27662986304


def _parse_rulesets_enforcement(rulesets: Any) -> dict[str, Any]:
    """Extract required checks + PR review from GitHub rulesets API payload."""
    out = {
        "required_status_checks": [],
        "pr_review_required": False,
        "required_reviews": None,
        "allows_force_pushes": None,
        "allows_deletions": None,
    }
    items: list[dict] = []
    if isinstance(rulesets, list):
        items = [x for x in rulesets if isinstance(x, dict)]
    elif isinstance(rulesets, dict):
        raw = rulesets.get("data") or rulesets.get("rulesets") or []
        if isinstance(raw, list):
            items = [x for x in raw if isinstance(x, dict)]

    for rs in items:
        if str(rs.get("enforcement") or "").lower() == "disabled":
            continue
        for rule in rs.get("rules") or []:
            if not isinstance(rule, dict):
                continue
            rtype = str(rule.get("type") or "")
            params = rule.get("parameters") or {}
            if rtype == "required_status_checks":
                for check in params.get("required_status_checks") or params.get("status_checks") or []:
                    ctx = check.get("context") if isinstance(check, dict) else check
                    if ctx:
                        out["required_status_checks"].append(str(ctx))
            if rtype in ("pull_request", "required_pull_request_reviews"):
                out["pr_review_required"] = True
                out["required_reviews"] = params.get("required_approving_review_count") or 1
            if rtype == "non_fast_forward":
                out["allows_force_pushes"] = False
            if rtype == "deletion":
                out["allows_deletions"] = False
    out["required_status_checks"] = sorted(set(out["required_status_checks"]))
    return out


def _protection_meets_minimum(evidence: dict[str, Any]) -> bool:
    """Operator minimum: objective-audit required + PR review + no force push/delete."""
    if evidence.get("objective_audit_required") is not True:
        return False
    if evidence.get("pr_review_required") is not True:
        return False
    if evidence.get("allows_force_pushes") is True:
        return False
    if evidence.get("allows_deletions") is True:
        return False
    return True


def empty_remote_evidence() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "artifact": "governance/artifacts/REMOTE_ENFORCEMENT_EVIDENCE.json",
        "verification_method": PENDING_METHOD,
        "evidence_source": None,
        "evidence_timestamp": None,
        "repository": None,
        "protected_branch": "main",
        "required_status_checks": [],
        "objective_audit_required": False,
        "required_reviews": None,
        "pr_review_required": False,
        "allows_force_pushes": None,
        "allows_deletions": None,
        "bypass_actors": [],
        "verified_by": None,
        "operator_attestation": False,
        "github_api_evidence": None,
        "branch_protection_verified": False,
        "required_checks_enforced": False,
        "operator_action_required": False,
        "objective_audit_check_name": None,
        "objective_audit_check_name_verified": False,
    }


def load_remote_evidence() -> dict[str, Any]:
    if not EVIDENCE_PATH.is_file():
        return empty_remote_evidence()
    try:
        data = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_remote_evidence()
    base = empty_remote_evidence()
    base.update({k: v for k, v in data.items() if k != "artifact"})
    return base


def save_remote_evidence(data: dict[str, Any]) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    out = empty_remote_evidence()
    out.update(data)
    EVIDENCE_PATH.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _resolve_gh_executable() -> Optional[str]:
    """Resolve gh — PATH first, then Windows portable install location."""
    found = shutil.which("gh")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        portable = Path(local) / "Programs" / "gh-cli" / "bin" / "gh.exe"
        if portable.is_file():
            return str(portable)
    for candidate in (
        Path(r"C:\Program Files\GitHub CLI\gh.exe"),
        Path(r"C:\Program Files (x86)\GitHub CLI\gh.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _gh_available() -> bool:
    return _resolve_gh_executable() is not None


def _github_token() -> Optional[str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return str(token).strip() if token and str(token).strip() else None


def _github_rest_request(
    method: str,
    url: str,
    *,
    token: Optional[str] = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "EdWebConsole-remote-enforcement")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload: Any = json.loads(raw) if raw.strip() else {"message": exc.reason}
        except json.JSONDecodeError:
            payload = {"message": raw or exc.reason}
        payload["_http_status"] = exc.code
        return exc.code, payload
    except (OSError, json.JSONDecodeError, urllib.error.URLError) as exc:
        return 0, {"_error": str(exc)}


def fetch_public_actions_run_inspection(
    run_id: int | str,
    *,
    repo: str = DEFAULT_REPO,
) -> dict[str, Any]:
    """Public GitHub Actions API — discover exact status check name (no auth required for public repos)."""
    status, run = _github_rest_request(
        "GET", f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
    )
    if status != 200 or not isinstance(run, dict):
        return {
            "run_id": int(run_id),
            "repository": repo,
            "fetch_error": run if isinstance(run, dict) else {"_http_status": status},
        }

    _, jobs_payload = _github_rest_request(
        "GET", f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"
    )
    jobs = (jobs_payload.get("jobs") or []) if isinstance(jobs_payload, dict) else []
    head_sha = str(run.get("head_sha") or "")
    check_runs: list[dict[str, Any]] = []
    if head_sha:
        _, cr_payload = _github_rest_request(
            "GET", f"https://api.github.com/repos/{repo}/commits/{head_sha}/check-runs"
        )
        if isinstance(cr_payload, dict):
            check_runs = [cr for cr in (cr_payload.get("check_runs") or []) if isinstance(cr, dict)]

    status_check_name: str | None = None
    for cr in check_runs:
        if str(cr.get("name") or "") == OBJECTIVE_AUDIT_CHECK:
            status_check_name = OBJECTIVE_AUDIT_CHECK
            break
    if status_check_name is None:
        for job in jobs:
            if str(job.get("name") or "") == OBJECTIVE_AUDIT_CHECK:
                status_check_name = OBJECTIVE_AUDIT_CHECK
                break

    return {
        "run_id": int(run_id),
        "repository": repo,
        "workflow_name": run.get("name"),
        "workflow_path": run.get("path"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "head_branch": run.get("head_branch"),
        "head_sha": head_sha,
        "jobs": [
            {"name": j.get("name"), "conclusion": j.get("conclusion"), "status": j.get("status")}
            for j in jobs
        ],
        "check_runs": [
            {
                "name": cr.get("name"),
                "status": cr.get("status"),
                "conclusion": cr.get("conclusion"),
            }
            for cr in check_runs
        ],
        "status_check_name_for_branch_protection": status_check_name,
    }


def _apply_branch_protection_payload(
    evidence: dict[str, Any],
    protection: Any,
    rulesets: Any,
) -> None:
    if isinstance(protection, dict) and not protection.get("_error") and protection.get("_http_status") is None:
        required_checks = [
            str(c.get("context") or c)
            for c in (protection.get("required_status_checks") or {}).get("checks") or []
        ]
        if not required_checks and protection.get("required_status_checks"):
            contexts = (protection.get("required_status_checks") or {}).get("contexts") or []
            required_checks = [str(c) for c in contexts]
        evidence["required_status_checks"] = required_checks
        evidence["objective_audit_required"] = OBJECTIVE_AUDIT_CHECK in required_checks
        reviews = protection.get("required_pull_request_reviews") or {}
        evidence["required_reviews"] = reviews.get("required_approving_review_count")
        evidence["pr_review_required"] = bool(reviews)
        evidence["allows_force_pushes"] = (protection.get("allow_force_pushes") or {}).get("enabled")
        evidence["allows_deletions"] = (protection.get("allow_deletions") or {}).get("enabled")
        bypass = protection.get("bypass_pull_request_allowances") or {}
        actors: list[str] = []
        for key in ("users", "teams", "apps"):
            for item in bypass.get(key) or []:
                label = item.get("login") or item.get("name") or item.get("slug") or str(item)
                actors.append(f"{key}:{label}")
        evidence["bypass_actors"] = actors
        return

    ruleset_info = _parse_rulesets_enforcement(rulesets)
    if ruleset_info["required_status_checks"]:
        evidence["required_status_checks"] = ruleset_info["required_status_checks"]
        evidence["objective_audit_required"] = OBJECTIVE_AUDIT_CHECK in ruleset_info["required_status_checks"]
    if ruleset_info["pr_review_required"]:
        evidence["pr_review_required"] = True
        evidence["required_reviews"] = ruleset_info["required_reviews"]
    if ruleset_info["allows_force_pushes"] is False:
        evidence["allows_force_pushes"] = False
    if ruleset_info["allows_deletions"] is False:
        evidence["allows_deletions"] = False


def fetch_github_api_evidence(
    protected_branch: str = "main",
    *,
    repo: str = DEFAULT_REPO,
) -> dict[str, Any]:
    """Fetch branch protection via GitHub REST API (GITHUB_TOKEN / GH_TOKEN)."""
    token = _github_token()
    evidence = empty_remote_evidence()
    if not token:
        evidence.update(
            {
                "verification_method": PENDING_METHOD,
                "evidence_source": "github_api_no_token",
                "operator_action_required": True,
                "github_api_evidence": {
                    "auth_error": "GITHUB_TOKEN or GH_TOKEN not set — cannot read branch protection",
                },
            }
        )
        return evidence

    status, repo_body = _github_rest_request(
        "GET", f"https://api.github.com/repos/{repo}", token=token
    )
    if status != 200 or not isinstance(repo_body, dict):
        evidence.update(
            {
                "verification_method": PENDING_METHOD,
                "evidence_source": "github_api_repo_error",
                "operator_action_required": True,
                "github_api_evidence": {"repo": repo_body},
            }
        )
        return evidence

    branch = protected_branch or str(repo_body.get("default_branch") or "main")
    owner, name = repo.split("/", 1) if "/" in repo else ("", repo)
    st_prot, protection = _github_rest_request(
        "GET",
        f"https://api.github.com/repos/{owner}/{name}/branches/{branch}/protection",
        token=token,
    )
    _, rulesets = _github_rest_request(
        "GET", f"https://api.github.com/repos/{owner}/{name}/rulesets", token=token
    )

    evidence.update(
        {
            "verification_method": "github_api",
            "evidence_source": "github_rest_api",
            "evidence_timestamp": _utc_now(),
            "repository": repo,
            "protected_branch": branch,
            "verified_by": "tools/verify_remote_enforcement.py",
            "github_api_evidence": {
                "repo": repo_body,
                "branch_protection": protection,
                "rulesets": rulesets,
                "branch_protection_http_status": st_prot,
            },
        }
    )

    if st_prot in (404, 401, 403):
        evidence["operator_action_required"] = True
    elif st_prot == 200:
        _apply_branch_protection_payload(evidence, protection, rulesets)
    else:
        evidence["operator_action_required"] = True

    evidence["branch_protection_verified"] = _protection_meets_minimum(evidence)
    evidence["required_checks_enforced"] = (
        evidence["branch_protection_verified"] and evidence.get("objective_audit_required") is True
    )
    if not evidence["branch_protection_verified"]:
        evidence["operator_action_required"] = True
    return evidence


def fetch_github_evidence(
    *,
    protected_branch: str = "main",
    repo: str = DEFAULT_REPO,
    run_id: int | str | None = DEFAULT_OBJECTIVE_AUDIT_RUN_ID,
) -> dict[str, Any]:
    """GitHub CLI when available, else REST API with token; always attach public run inspection when run_id set."""
    if _gh_available():
        evidence = fetch_github_cli_evidence(protected_branch)
        if evidence.get("repository"):
            repo = str(evidence["repository"])
    else:
        evidence = fetch_github_api_evidence(protected_branch, repo=repo)

    if run_id is not None:
        inspection = fetch_public_actions_run_inspection(run_id, repo=repo)
        gh_ev = dict(evidence.get("github_api_evidence") or {})
        gh_ev["objective_audit_run_inspection"] = inspection
        evidence["github_api_evidence"] = gh_ev
        check_name = inspection.get("status_check_name_for_branch_protection")
        if check_name:
            evidence["objective_audit_check_name"] = check_name
            evidence["objective_audit_check_name_verified"] = True
        if not evidence.get("repository"):
            evidence["repository"] = repo
        if not evidence.get("evidence_timestamp"):
            evidence["evidence_timestamp"] = _utc_now()

    if not evidence.get("branch_protection_verified"):
        evidence["operator_action_required"] = True
    return evidence


def _run_gh(args: list[str]) -> Optional[dict | list]:
    gh_exe = _resolve_gh_executable()
    if not gh_exe:
        return None
    try:
        proc = subprocess.run(
            [gh_exe, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip() or proc.stdout.strip(), "_exit_code": proc.returncode}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"_raw": proc.stdout}


def fetch_github_cli_evidence(protected_branch: str = "main") -> dict[str, Any]:
    """Fetch branch protection via GitHub CLI. Returns evidence dict (may include errors)."""
    repo_view = _run_gh(["repo", "view", "--json", "nameWithOwner,defaultBranchRef"])
    if not isinstance(repo_view, dict) or repo_view.get("_error"):
        return {
            **empty_remote_evidence(),
            "verification_method": PENDING_METHOD,
            "evidence_source": "github_cli_unavailable",
            "github_api_evidence": {"repo_view_error": repo_view},
        }

    repo = str(repo_view.get("nameWithOwner") or "")
    branch = protected_branch
    default_ref = ((repo_view.get("defaultBranchRef") or {}).get("name") or "")
    if default_ref:
        branch = default_ref

    owner, name = repo.split("/", 1) if "/" in repo else ("", repo)
    protection = _run_gh(["api", f"repos/{owner}/{name}/branches/{branch}/protection"])
    rulesets = _run_gh(["api", f"repos/{owner}/{name}/rulesets"])
    runs = _run_gh(["run", "list", "--workflow", "objective-audit.yml", "--limit", "5", "--json", "databaseId,status,conclusion,headBranch"])

    evidence = empty_remote_evidence()
    evidence.update(
        {
            "verification_method": "github_cli",
            "evidence_source": "gh api + gh run list",
            "evidence_timestamp": _utc_now(),
            "repository": repo,
            "protected_branch": branch,
            "verified_by": "tools/verify_remote_enforcement.py",
            "github_api_evidence": {
                "repo_view": repo_view,
                "branch_protection": protection,
                "rulesets": rulesets,
                "objective_audit_runs": runs,
            },
        }
    )

    _apply_branch_protection_payload(evidence, protection, rulesets)

    evidence["branch_protection_verified"] = _protection_meets_minimum(evidence)
    evidence["required_checks_enforced"] = (
        evidence["branch_protection_verified"] and evidence.get("objective_audit_required") is True
    )
    if not evidence["branch_protection_verified"]:
        evidence["operator_action_required"] = True

    return evidence


def apply_manual_attestation(attestation: dict[str, Any]) -> dict[str, Any]:
    """Operator manual attestation — verified stays false."""
    evidence = empty_remote_evidence()
    evidence.update(
        {
            "verification_method": MANUAL_METHOD,
            "evidence_source": attestation.get("evidence_source") or "operator_manual_attestation",
            "evidence_timestamp": attestation.get("evidence_timestamp") or _utc_now(),
            "repository": attestation.get("repository"),
            "protected_branch": attestation.get("protected_branch") or "main",
            "required_status_checks": list(attestation.get("required_status_checks") or []),
            "objective_audit_required": OBJECTIVE_AUDIT_CHECK
            in list(attestation.get("required_status_checks") or []),
            "required_reviews": attestation.get("required_reviews"),
            "pr_review_required": bool(attestation.get("pr_review_required")),
            "allows_force_pushes": attestation.get("allows_force_pushes"),
            "allows_deletions": attestation.get("allows_deletions"),
            "bypass_actors": list(attestation.get("bypass_actors") or []),
            "verified_by": attestation.get("verified_by"),
            "operator_attestation": True,
            "github_api_evidence": attestation.get("github_api_evidence"),
            "branch_protection_verified": False,
            "required_checks_enforced": False,
            "attestation_note": (
                "Manual attestation is not API verification — branch_protection.verified remains false."
            ),
        }
    )
    return evidence


def derive_statuses(evidence: dict[str, Any]) -> dict[str, Any]:
    method = evidence.get("verification_method") or PENDING_METHOD
    api_verified = method in API_VERIFIED_METHODS and evidence.get("branch_protection_verified") is True
    checks_enforced = api_verified and evidence.get("required_checks_enforced") is True
    pr_required = api_verified and evidence.get("pr_review_required") is True

    if api_verified and checks_enforced:
        no_verify = "mitigated"
        same_actor = "mitigated" if pr_required else "partially_mitigated"
        external = "verified"
    elif evidence.get("operator_attestation"):
        no_verify = "open"
        same_actor = "open"
        external = "attested_not_api_verified"
    else:
        no_verify = "open"
        same_actor = "open"
        external = "required_not_proven"

    return {
        "branch_protection_verified": api_verified,
        "required_checks_enforced": checks_enforced,
        "objective_audit_required": evidence.get("objective_audit_required") is True,
        "pr_review_required": pr_required,
        "no_verify_status": no_verify,
        "same_actor_mutation_status": same_actor,
        "external_enforcement_status": external,
    }


def build_branch_protection_artifact(evidence: dict[str, Any]) -> dict[str, Any]:
    statuses = derive_statuses(evidence)
    verified = statuses["branch_protection_verified"]
    return {
        "schema_version": 2,
        "artifact": "governance/artifacts/BRANCH_PROTECTION_PROOF.json",
        "branch_protection": {
            "required": True,
            "configured": "documented",
            "verified": verified,
            "verification_state": "verified" if verified else "unverified",
            "reason": (
                "Verified via remote evidence."
                if verified
                else "Local repo cannot prove remote branch protection without GitHub API evidence."
            ),
        },
        "remote_evidence": {k: evidence.get(k) for k in REMOTE_EVIDENCE_FIELDS},
        "codeowners_present": (REPO_ROOT / ".github" / "CODEOWNERS").is_file(),
        "ci_workflow_present": (REPO_ROOT / ".github/workflows/objective-audit.yml").is_file(),
        "external_enforcement_proven": verified and statuses["required_checks_enforced"],
        "acceptable_claim": (
            "Branch protection verified on GitHub"
            if verified
            else "Branch protection required but not yet verified"
        ),
        "github_api_evidence": evidence.get("github_api_evidence") if verified else None,
    }


def build_required_status_checks_artifact(evidence: dict[str, Any]) -> dict[str, Any]:
    from tools.check_required_status_checks import _workflow_spec_base

    statuses = derive_statuses(evidence)
    base = _workflow_spec_base()
    base["schema_version"] = 2
    base["remote_evidence"] = {k: evidence.get(k) for k in REMOTE_EVIDENCE_FIELDS}
    base["required_checks"] = {
        "enforced": statuses["required_checks_enforced"],
        "objective_audit_required_on_github": statuses["objective_audit_required"],
        "required_status_checks_on_github": list(evidence.get("required_status_checks") or []),
    }
    base["remote_enforcement_verified"] = statuses["required_checks_enforced"]
    base["verification_state"] = "verified" if statuses["required_checks_enforced"] else "unverified"
    return base


def build_no_verify_artifact(evidence: dict[str, Any]) -> dict[str, Any]:
    statuses = derive_statuses(evidence)
    return {
        "schema_version": 2,
        "artifact": "governance/artifacts/NO_VERIFY_RESISTANCE.json",
        "local_pre_commit_bypassable": True,
        "bypass_command": "git commit --no-verify",
        "mitigation_layers": [
            "CI required checks (objective-audit workflow)",
            "GitHub branch protection requiring CI checks",
            "CODEOWNERS + required PR review",
        ],
        "ci_workflow_exists": (REPO_ROOT / ".github/workflows/objective-audit.yml").is_file(),
        "branch_protection_verified": statuses["branch_protection_verified"],
        "no_verify_status": statuses["no_verify_status"],
        "remote_evidence": {k: evidence.get(k) for k in REMOTE_EVIDENCE_FIELDS},
        "closed_requires": [
            "ci_required_checks_proven_on_github",
            "branch_protection_verified",
        ],
        "acceptable_claim": (
            "No-verify mitigated only when CI + branch protection are both proven on GitHub"
        ),
    }


def build_self_protection_artifact(evidence: dict[str, Any]) -> dict[str, Any]:
    from tools.check_governance_self_protection import MATURITY_REGISTER, PRELOAD_RULES, REQUIRED_SURFACES

    statuses = derive_statuses(evidence)
    return {
        "schema_version": 2,
        "artifact": "governance/artifacts/GOVERNANCE_SELF_PROTECTION.json",
        "surfaces_present": {p: (REPO_ROOT / p).is_file() for p in REQUIRED_SURFACES},
        "preload_rules_present": {p: (REPO_ROOT / p).is_file() for p in PRELOAD_RULES},
        "maturity_truth_source": MATURITY_REGISTER,
        "maturity_truth_source_exists": (REPO_ROOT / MATURITY_REGISTER).is_file(),
        "l5_claim_without_proof_forbidden": True,
        "external_enforcement_required": True,
        "external_enforcement_proven": statuses["external_enforcement_status"] == "verified",
        "same_actor_mutation_status": statuses["same_actor_mutation_status"],
        "remote_evidence": {k: evidence.get(k) for k in REMOTE_EVIDENCE_FIELDS},
        "verify_remote_enforcement_script": (
            REPO_ROOT / "tools" / "verify_remote_enforcement.py"
        ).is_file(),
    }


def build_phase3d_evidence_artifact(evidence: dict[str, Any], *, checker_tests: dict | None = None) -> dict[str, Any]:
    statuses = derive_statuses(evidence)
    wf = REPO_ROOT / ".github/workflows/objective-audit.yml"
    wf_text = wf.read_text(encoding="utf-8") if wf.is_file() else ""
    from tools.check_governance_critical_files import (
        GOVERNANCE_CRITICAL_GLOBS,
        GOVERNANCE_CRITICAL_PATHS,
        _expand_glob_paths,
    )

    label = {
        "verified": "external enforcement verified for protected-branch merge path",
        "attested_not_api_verified": "operator attestation recorded — not API verified",
        "required_not_proven": "external enforcement required but not yet proven",
    }.get(statuses["external_enforcement_status"], statuses["external_enforcement_status"])

    return {
        "schema_version": 2,
        "artifact": "governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3D_EVIDENCE.json",
        "phase": "3D-Verification",
        "label": label,
        "ci_workflow_exists": wf.is_file(),
        "objective_audit_in_ci": "--objective-audit" in wf_text,
        "adversarial_tests_in_ci": "tests/adversarial/" in wf_text,
        "required_checks_spec_exists": (ART / "REQUIRED_STATUS_CHECKS.json").is_file(),
        "branch_protection_required": True,
        "branch_protection_verified": statuses["branch_protection_verified"],
        "required_status_checks_enforced": statuses["required_checks_enforced"],
        "objective_audit_required_on_github": statuses["objective_audit_required"],
        "pull_request_review_required_on_github": statuses["pr_review_required"],
        "pr_review_required_on_github": statuses["pr_review_required"],
        "codeowners_exists": (REPO_ROOT / ".github/CODEOWNERS").is_file(),
        "governance_critical_files_count": len(GOVERNANCE_CRITICAL_PATHS) + len(_expand_glob_paths()),
        "no_verify_status": statuses["no_verify_status"],
        "same_actor_mutation_status": statuses["same_actor_mutation_status"],
        "external_enforcement_status": statuses["external_enforcement_status"],
        "operator_action_required": evidence.get("operator_action_required") is True,
        "objective_audit_check_name": evidence.get("objective_audit_check_name"),
        "objective_audit_check_name_verified": evidence.get("objective_audit_check_name_verified") is True,
        "remote_evidence": {k: evidence.get(k) for k in REMOTE_EVIDENCE_FIELDS},
        "phase3d_checker_tests": checker_tests or {},
        "maturity_changes_proposed": [],
        "maturity_changes_rejected": [
            "L5 institutional enforcement — no adversarial bypass survival + external proof",
            "Branch protection satisfied from docs/CODEOWNERS alone",
            "No-verify mitigated from CI workflow file alone",
            "Manual attestation treated as API verification",
        ],
        "remaining_gaps": _remaining_gaps(statuses, evidence),
    }


def _remaining_gaps(statuses: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not statuses["branch_protection_verified"]:
        gaps.append("GitHub branch protection not API/CLI verified")
    if evidence.get("objective_audit_check_name_verified"):
        gaps.append(
            "Objective Audit GitHub check name verified as "
            f"{evidence.get('objective_audit_check_name')!r} — "
            "main branch protection must require this check (operator_action_required until API proof)"
        )
    elif not statuses["required_checks_enforced"]:
        gaps.append("objective-audit not proven as required GitHub status check")
    if statuses["no_verify_status"] != "mitigated":
        gaps.append("--no-verify remains open until CI + branch protection API verified")
    if evidence.get("operator_attestation") and not statuses["branch_protection_verified"]:
        gaps.append("Operator manual attestation present — awaiting API/ruleset verification")
    if statuses["same_actor_mutation_status"] != "mitigated":
        gaps.append("Same-actor governance mutation without proven PR review enforcement")
    gaps.append("Manual DB/filesystem bypasses remain open (UNIVERSAL_BYPASS_REGISTER)")
    return gaps


def validate_verified_claims(evidence: dict[str, Any], artifact_name: str) -> list[str]:
    """Fail if verified/enforced claims lack evidence fields."""
    errors: list[str] = []
    method = evidence.get("verification_method") or PENDING_METHOD

    if evidence.get("branch_protection_verified") is True:
        if method not in API_VERIFIED_METHODS:
            errors.append(f"{artifact_name}: branch_protection_verified without API verification method")
        if not evidence.get("github_api_evidence"):
            errors.append(f"{artifact_name}: branch_protection_verified without github_api_evidence")
        for field in REMOTE_EVIDENCE_FIELDS:
            if field in ("bypass_actors",) and evidence.get(field) is not None:
                continue
            if evidence.get(field) is None and field not in ("verified_by",):
                errors.append(f"{artifact_name}: verified claim missing remote evidence field {field!r}")

    if method == MANUAL_METHOD and evidence.get("branch_protection_verified") is True:
        errors.append(f"{artifact_name}: manual attestation cannot set branch_protection_verified true")

    if evidence.get("required_checks_enforced") is True and not evidence.get("objective_audit_required"):
        errors.append(f"{artifact_name}: required_checks_enforced but objective-audit not required")

    return errors


def write_all_artifacts(evidence: dict[str, Any], *, generated: str | None = None) -> None:
    from datetime import date

    gen = generated or date.today().isoformat()
    save_remote_evidence(evidence)
    artifacts = {
        "BRANCH_PROTECTION_PROOF.json": build_branch_protection_artifact(evidence),
        "REQUIRED_STATUS_CHECKS.json": build_required_status_checks_artifact(evidence),
        "NO_VERIFY_RESISTANCE.json": build_no_verify_artifact(evidence),
        "GOVERNANCE_SELF_PROTECTION.json": build_self_protection_artifact(evidence),
    }
    for name, payload in artifacts.items():
        payload["generated"] = gen
        (ART / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
