"""LOCK-PM-VERIFY (RC-242) — a verdict about the repo must carry a reading OF the repo.

OPERATOR LAW (non-negotiable, 2026-08-04): material claims about repo state are verified
against the repo, same turn. Prose from another agent is not evidence. (The standing
PM/auditor role this lock was named for is gone — 2026-08-24 Architecture A teardown —
but the claim-shape law is role-free and survives on the Stop path via honesty_guard.)

WHAT THIS BLOCKS. A completion/Stop text that publishes a VERDICT — VERIFIED, ACCEPTED,
COMPLETE, PROVEN, AUDIT_ACCEPT, ON HEAD — about REPO STATE (a HEAD sha, an open-class
count, a control being ENFORCED/ON HEAD, quiet PASS/FAIL, BARS_WORKERS, a kill landed)
while the same turn contains no measurement of that state.

WHAT SATISFIES IT (either one):
  1. Inline git evidence — a git READ invocation with the value it returned nearby, and
     (when the Stop path supplies this turn's command list) a git READ actually ISSUED this
     turn. HONEST LIMIT: the guard checks that the text contains invocation-plus-value and
     that a git read ran; it cannot prove the pasted value is what the command returned,
     that the reading is current, or that it SUPPORTS the claim — that residue is inherent
     to prose and accepted; the hedge path plus operator review is the real backstop.
  2. Hedged reporting — `[UNVERIFIED]`, "Claude reports", "ACCEPTED as claim", "pending
     verification" — judged per paragraph: a hedge covers its own paragraph, never every
     verdict in the message. Saying you have not measured is always legal; that is the
     honest path and it must never be blocked, or the guard would push toward false
     confidence.
BY DESIGN: only the ALL-CAPS verdict register binds (re.I would flood on ordinary
'completed/accepted' prose). A lowercase or reworded verdict is out of scope of
wording-shape detection and is caught by operator review, not by this lock.
(The third path — a fresh reports/pm_verify_latest.json from the PM verify runner — was
removed with the runner in the 2026-08-24 teardown.)

WHY IT IS SHAPED THIS WAY. Per-artifact locks kept arriving one failure at a time — RC-87
(memory cited as proof), RC-241 (a gate state asserted, not read), and this row (a reviewer
accepting the writer's narration). The general shape underneath is one thing: the reviewer and
the reviewed sharing a single source of truth, the chat. So this binds the CLAIM SHAPE rather
than any one artifact.

Hedge path: `[UNVERIFIED]` / "Claude reports". `# pm-verify-ok:` remains a visible
text marker. No env kill-switch: ED_PM_VERIFY_LOCK cannot disable this control (RC-450).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_ESCAPE = "# pm-verify-ok:"

#: The verdict vocabulary. These words END an argument; they are the ones that must be earned.
_VERDICT_RE = re.compile(
    r"\b(VERIFIED|AUDIT_ACCEPT|ACCEPTED|COMPLETE|COMPLETED|PROVEN|CONFIRMED)\b")

#: Claims ABOUT REPO STATE. A verdict on prose ("accepted your explanation") is not this lock's
#: business; a verdict on what the tree contains is.
_REPO_CLAIM_RES: dict[str, re.Pattern[str]] = {
    "head_sha": re.compile(r"\bHEAD\b[^\n]{0,40}\b[0-9a-f]{7,40}\b|\b[0-9a-f]{7,40}\b[^\n]{0,20}\bHEAD\b", re.I),
    "on_head": re.compile(r"\bON[_ ]HEAD\b|\bon HEAD\b", re.I),
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

#: Reading commands that count as a repo read when actually ISSUED this turn.
_GIT_READ_RE = re.compile(
    r"\bgit\s+(?:rev-parse|show|grep|log|ls-tree|cat-file|diff|status)\b", re.I)
_HEX_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)


def _git_evidence(t: str, fields: list[str], executed: list[str] | None) -> bool:
    """Inline git evidence, two conditions instead of one:
    (1) when the caller supplies this turn's executed commands, a git READ must have
        actually been ISSUED this turn — the mere mention of `git log` in prose is not
        a reading (executed=None = legacy caller: mention suffices, as before);
    (2) a head-sha claim must show a hex value within 200 chars after the cited
        invocation — pasted output naturally satisfies this; a bare command does not."""
    m = _GIT_EVIDENCE_RE.search(t)
    if not m:
        return False
    if executed is not None and not any(_GIT_READ_RE.search(c) for c in executed):
        return False
    if "head_sha" in fields and not _HEX_RE.search(t[m.end():m.end() + 200]):
        return False
    return True


def claimed_repo_fields(text: str) -> list[str]:
    """Which repo-state facts this text asserts."""
    return [name for name, rx in _REPO_CLAIM_RES.items() if rx.search(text or "")]


def pm_verify_repo_violations(
    text: str,
    *,
    repo: Path | None = None,
    now: float | None = None,
    executed: list[str] | None = None,
) -> list[str]:
    """BLOCK a repo-state VERDICT that carries no same-turn measurement (RC-242).

    Verdict, claim and hedge are judged PER PARAGRAPH (split on blank lines): one hedge
    about an unrelated topic used to neutralize every verdict in the message. Evidence
    stays text-global — pasted git output legitimately sits in its own block."""
    t = text or ""
    if not t or _ESCAPE in t:
        return []
    fields_all = claimed_repo_fields(t)
    if not fields_all:
        return []
    evidence_ok = _git_evidence(t, fields_all, executed)
    for para in re.split(r"\n\s*\n", t):
        if not _VERDICT_RE.search(para):
            continue
        fields = claimed_repo_fields(para)
        if not fields:
            continue
        if _HEDGE_RE.search(para):
            continue               # saying "I did not measure this" is always legal
        if evidence_ok:
            continue               # a reading was pasted inline AND issued this turn
        return [
            "PM_VERIFY_REPO: claim without same-turn repo measure — this text publishes a "
            f"verdict ({', '.join(sorted(set(_VERDICT_RE.findall(para))))[:60]}) about repo "
            f"state ({', '.join(fields)}) with no measurement behind it. Paste the git "
            "output you read (a git READ issued this turn), or mark the claim "
            f"[UNVERIFIED]. Prose from another agent is not evidence (RC-242). "
            f"Escape: '{_ESCAPE} <reason>'."
        ]
    return []


if __name__ == "__main__":
    import sys

    bad = pm_verify_repo_violations(sys.stdin.read())
    for b in bad:
        print(b)
    raise SystemExit(2 if bad else 0)
