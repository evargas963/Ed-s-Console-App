"""LOCK-PM-VERIFY (RC-242) — a verdict about the repo must carry a reading OF the repo.

OPERATOR LAW (non-negotiable, 2026-08-04): the PM/auditor verifies material claims against the
repo, same turn. Prose from the writer is not evidence. Absence of a mechanical lock is itself
a failure.

WHAT THIS BLOCKS. A completion/Stop text that publishes a VERDICT — VERIFIED, ACCEPTED,
COMPLETE, PROVEN, AUDIT_ACCEPT, ON HEAD — about REPO STATE (a HEAD sha, `granted=`, an
open-class count, a control being ENFORCED/ON HEAD, quiet PASS/FAIL, BARS_WORKERS, a kill
landed) while the same turn contains no measurement of that state.

WHAT SATISFIES IT (any one):
  1. Inline git evidence in the same text — a `git rev-parse` / `git show` / `git grep`
     invocation together with the value it returned. Pasting what the repo said IS the law.
  2. A FRESH `reports/pm_verify_latest.json` written this turn by tools/pm_verify_repo.py.
     Freshness is required because a stale measurement is how yesterday's truth gets published
     as today's verdict.
  3. Hedged reporting — `[UNVERIFIED]`, "Claude reports", "ACCEPTED as claim", "pending
     verification". Saying you have not measured is always legal; that is the honest path and
     it must never be blocked, or the guard would push toward false confidence.

WHY IT IS SHAPED THIS WAY. Per-artifact locks kept arriving one failure at a time — RC-87
(memory cited as proof), RC-241 (the GO state asserted, not read), and this row (the PM
accepting the writer's narration). The general shape underneath is one thing: the reviewer and
the reviewed sharing a single source of truth, the chat. So this binds the CLAIM SHAPE rather
than any one artifact.

Escape: `# pm-verify-ok: <reason>` (operator-reviewed), and ED_PM_VERIFY_LOCK=off.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REPORT_REL = "reports/pm_verify_latest.json"

#: How recently the measurement must have been taken to count as "this turn". Generous enough
#: for a long turn, far short of a session — a measurement from hours ago is not a reading of
#: the repo as it stands now.
FRESH_WINDOW_SEC: float = 45 * 60.0

_ESCAPE = "# pm-verify-ok:"

#: The verdict vocabulary. These words END an argument; they are the ones that must be earned.
_VERDICT_RE = re.compile(
    r"\b(VERIFIED|AUDIT_ACCEPT|ACCEPTED|COMPLETE|COMPLETED|PROVEN|CONFIRMED)\b")

#: Claims ABOUT REPO STATE. A verdict on prose ("accepted your explanation") is not this lock's
#: business; a verdict on what the tree contains is.
_REPO_CLAIM_RES: dict[str, re.Pattern[str]] = {
    "head_sha": re.compile(r"\bHEAD\b[^\n]{0,40}\b[0-9a-f]{7,40}\b|\b[0-9a-f]{7,40}\b[^\n]{0,20}\bHEAD\b", re.I),
    "on_head": re.compile(r"\bON[_ ]HEAD\b|\bon HEAD\b", re.I),
    "go_granted": re.compile(r"\bgranted\s*=\s*(?:true|false)\b|\boperator_go\b", re.I),
    "open_class": re.compile(r"\bopen[- ]class\b[^\n]{0,20}\d|\bopen[- ]class\s*=\s*\d", re.I),
    "enforced": re.compile(r"\bENFORCED\b", re.I),
    "quiet_verdict": re.compile(r"\bquiet\b[^\n]{0,30}\b(PASS|FAIL)\b", re.I),
    "bars_workers": re.compile(r"\bBARS_WORKERS\b", re.I),
    "kill_landed": re.compile(r"\bkill\b[^\n]{0,20}\blanded\b", re.I),
}

#: Hedges — explicit statements that the claim is NOT measured. Always legal.
_HEDGE_RE = re.compile(
    r"\[UNVERIFIED\]|\bUNVERIFIED\b|\bClaude(?:\s+\w+){0,2}\s+(?:reports|claims)\b"
    r"|\bACCEPTED as claim\b|\bpending (?:verification|verify|measure)\b"
    r"|\bnot (?:yet )?(?:measured|verified) (?:this turn)?\b|\bunmeasured\b",
    re.I,
)

#: Inline git evidence: a real invocation against the repo, in the same text.
_GIT_EVIDENCE_RE = re.compile(
    r"\bgit\s+(?:rev-parse|show|grep|log|ls-tree|cat-file|diff)\b", re.I)


def _report_path(repo: Path | None = None) -> Path:
    return (repo or REPO) / REPORT_REL


def fresh_measurement(repo: Path | None = None, now: float | None = None) -> dict | None:
    """The pm_verify report IF it was measured inside the freshness window, else None."""
    p = _report_path(repo)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    ts = data.get("measured_at_utc")
    if not isinstance(ts, (int, float)):
        return None
    if (now if now is not None else time.time()) - float(ts) > FRESH_WINDOW_SEC:
        return None
    return data


def claimed_repo_fields(text: str) -> list[str]:
    """Which repo-state facts this text asserts."""
    return [name for name, rx in _REPO_CLAIM_RES.items() if rx.search(text or "")]


def pm_verify_repo_violations(
    text: str,
    *,
    repo: Path | None = None,
    now: float | None = None,
) -> list[str]:
    """BLOCK a repo-state VERDICT that carries no same-turn measurement (RC-242)."""
    try:
        from tools.hard_law_runtime import env_guard_is_disabled as _egd
    except ImportError:
        from hard_law_runtime import env_guard_is_disabled as _egd  # type: ignore
    if _egd("ED_PM_VERIFY_LOCK"):
        return []
    t = text or ""
    if not t or _ESCAPE in t:
        return []
    if not _VERDICT_RE.search(t):
        return []                      # no verdict published — nothing to earn
    fields = claimed_repo_fields(t)
    if not fields:
        return []                      # a verdict about prose, not about the tree
    if _HEDGE_RE.search(t):
        return []                      # saying "I did not measure this" is always legal
    if _GIT_EVIDENCE_RE.search(t):
        return []                      # the reading is pasted inline
    if fresh_measurement(repo, now) is not None:
        return []                      # measured this turn by tools/pm_verify_repo.py
    return [
        "PM_VERIFY_REPO: claim without same-turn repo measure — this text publishes a verdict "
        f"({', '.join(sorted(set(_VERDICT_RE.findall(t))))[:60]}) about repo state "
        f"({', '.join(fields)}) with no measurement behind it. Run "
        "`python tools/pm_verify_repo.py` this turn, or paste the git output you read, or "
        "mark the claim [UNVERIFIED]. Prose from the other agent is not evidence (RC-242). "
        f"Escape: '{_ESCAPE} <reason>'."
    ]


if __name__ == "__main__":
    import sys

    bad = pm_verify_repo_violations(sys.stdin.read())
    for b in bad:
        print(b)
    raise SystemExit(2 if bad else 0)
