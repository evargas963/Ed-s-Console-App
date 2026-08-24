"""HONESTY GUARD — blocks dodge / omission / MD-as-lock theater (RC-209).

OPERATOR LAW (2026-08-02, non-negotiable): do not lie directly or by omission; do not dodge
a plain question with an answer that does not answer; an .md file is never a mechanical lock.

RESEARCH BASIS (institutional / scientific integrity — fail-closed on detectable artifacts):
  - PCAOB AS 1215 (Audit Documentation): retain information inconsistent with conclusions;
    documentation must let an experienced outsider understand the work
    (https://pcaobus.org/oversight/standards/auditing-standards/details/AS1215).
  - Simmons, Nelson, Simonsohn (2011) False-Positive Psychology: disclose flexibility;
    do not hide researcher degrees of freedom (Psych Sci).
  - Nosek et al. (2015) TOP Guidelines / COS preregistration: transparent deviations;
    confirmatory honesty (Science; https://www.cos.io/initiatives/prereg).
  - Claerbout & Karrenbach (1992); Peng (2011) Reproducible Research: do not claim what
    the reader cannot rebuild (Science 2011).
  - Stop-hook answer-slot pattern: parse direct operator asks (yes/no, score) and BLOCK
    if required answer tokens are absent (AS 1215 \"stands alone\" analogue for chat).

WHY THIS EXISTS. Agents wrote plan/brief/strength .md files as if they were locks; Soft
catalog rows were labeled \"owned.\" proof_only_guard covers memory-as-evidence, not honesty
to the operator. When asked \"is there a lock against lying?\" nothing forced a Yes/No.

WHAT THIS BLOCKS (exit 2 on Stop):
  (a) Yes/no asks without Yes/No in the final assistant text.
  (b) Score asks without an N/10 score.
  (c) Claiming a mechanical lock via .md/.mdc, or a lock claim naming no mechanism.
  (d) A repo-state verdict with no same-turn reading of the repo (pm_verify_lock).
SIMPLICITY REHAB 2026-08-24: the soft_partial catalog branches were removed — their
subject file (governance/plus_player_attributes.json) left the tree with the retired
plus_player checks (RC-470), which made those branches permanently unreachable. RC-233
PM_COVERAGE (per-item disposition tokens on chat prose) was retired: AGENTS.md already
rules that live chat prose is bound by the law itself and operator review — the
operator is present in the same turn and is the detector.

Contract: Stop hook; stop_hook_active respected. Architecture A: ED_HONESTY_GUARD cannot disable this control.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

YES_NO_ASK = re.compile(
    r"\b(is there|are you sure|do we have|does .+ exist|yes or no|did you|"
    r"can you (?:confirm|say)|was i (?:unclear|wrong)|am i )\b",
    re.I,
)
SCORE_ASK = re.compile(r"\b(score|how strong|/10|out of (?:ten|10)|rating)\b", re.I)
HAS_YES_NO = re.compile(r"\b(yes|no)\b", re.I)
HAS_SCORE = re.compile(r"\b(\d{1,2})\s*/\s*10\b|\bscore[:\s]+(\d{1,2})\b", re.I)
MD_AS_LOCK = re.compile(
    r"\b(mechanical lock|locked|enforced)\b[^.!\n]{0,80}\b\.(md|mdc)\b|"
    r"\b\.(md|mdc)\b[^.!\n]{0,80}\b(mechanical lock|is the lock|as the lock)\b",
    re.I,
)
DELIVERABLE_ASK = re.compile(
    r"\b(return ONLY|plain scores|files changed|list (?:the )?files|pytest|"
    r"score each surface|every surface|10/10)\b",
    re.I,
)
DEFLECTION = re.compile(
    r"\b(as appropriate|going forward|should consider|we could|might want to|"
    r"happy to help|let me know if)\b",
    re.I,
)
HAS_SURFACE_SCORES = re.compile(
    r"\b\d{1,2}\s*/\s*10\b.*\b(honesty|soft|research|find|evidence|decide|collect|completeness|"
    r"cursor|coherence|surface)\b|\bsurface\s*\d+\s*[:\-]\s*\d{1,2}\s*/\s*10",
    re.I,
)
HAS_FILES_CHANGED = re.compile(r"\bfiles changed\b|\bchanged files\b", re.I)


def last_assistant_text(transcript_path: str) -> str | None:
    try:
        from tools.proof_only_guard import last_assistant_text as _lat
    except ImportError:
        from proof_only_guard import last_assistant_text as _lat  # type: ignore
    return _lat(transcript_path)


def last_user_text(transcript_path: str) -> str | None:
    try:
        from tools.proof_only_guard import last_user_text as _lut
    except ImportError:
        from proof_only_guard import last_user_text as _lut  # type: ignore
    return _lut(transcript_path)


def honesty_violations(user_text: str | None, assistant_text: str) -> list[str]:
    """Callee for tests — pure function over user ask + assistant final text."""
    out: list[str] = []
    u = user_text or ""
    a = assistant_text or ""
    if YES_NO_ASK.search(u) and not HAS_YES_NO.search(a):
        out.append(
            "direct yes/no question went unanswered — final text has no clear Yes or No "
            "(operator law: do not dodge)"
        )
    if SCORE_ASK.search(u) and not HAS_SCORE.search(a):
        out.append(
            "score/strength question went unanswered — final text has no N/10 score "
            "(operator law: answer plainly)"
        )
    if MD_AS_LOCK.search(a):
        out.append(
            "claimed a mechanical lock via an .md/.mdc file — prose is never a lock "
            "(operator law: lock = .py that BLOCKs)"
        )
    # LOCK-7 (RC-232): a claim of "locked/encoded via rule/mandate/process" must NAME its
    # mechanism — a CHECK id (check_*) or a guard .py — or it is process-md theater.
    import re as _re
    _lock_claim = _re.search(
        r"\b(locked|encoded|enforced)\s+(?:via|in|by|through)\s+(?:the\s+)?"
        r"(rule|mandate|process\s+doc|charter|memo|agreement|standing\s+law)\b",
        a, _re.I)
    if _lock_claim and not _re.search(r"\bcheck_\w+\b|\b\w+_guard\.py\b|\b\w+_lock\.py\b", a):
        out.append(
            "claimed 'locked via " + _lock_claim.group(2) + "' without naming a CHECK id "
            "(check_*) or a guard/lock .py — a lock claim that names no mechanism is theater "
            "(LOCK-7/RC-232)"
        )
    if DELIVERABLE_ASK.search(u):
        if SCORE_ASK.search(u) or "10/10" in u.lower() or "plain scores" in u.lower():
            if not HAS_SURFACE_SCORES.search(a) and not HAS_SCORE.search(a):
                out.append(
                    "operator asked for plain surface scores — final text lacks N/10 scores "
                    "(PCAOB AS 1215: documentation must stand alone)"
                )
        if "files changed" in u.lower() and not HAS_FILES_CHANGED.search(a):
            out.append(
                "operator asked for files changed — final text must name changed paths "
                "(Peng 2011 reproducible research: reader must see what moved)"
            )
        if DEFLECTION.search(a) and not HAS_SCORE.search(a) and not HAS_FILES_CHANGED.search(a):
            out.append(
                "deflection phrase without the requested deliverable (scores/paths) — "
                "answer the question asked (AS 1215 / instruction fidelity)"
            )
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if payload.get("stop_hook_active") is True:
        return 0
    tp = payload.get("transcript_path")
    if not tp:
        return 0
    text = last_assistant_text(tp)
    if text is None:
        sys.stderr.write(
            "BLOCKED (RC-209): honesty_guard could not read the transcript — unmeasurable "
            "is never a pass.\n"
        )
        return 2
    bad = honesty_violations(last_user_text(tp), text)
    # RC-233 PM_COVERAGE RETIRED (SIMPLICITY REHAB, operator full-go 2026-08-24): it
    # forced disposition tokens onto chat prose per detected bullet in the operator's
    # paste — a response-formatting rule. AGENTS.md's own line governs: live chat prose
    # is bound by the law itself and operator review, and the operator is present in
    # the same turn.
    # RC-242 LOCK-PM-VERIFY: a verdict about REPO STATE must carry a reading OF the repo.
    # Wired here because .claude/settings.json and .cursor/hooks.json BOTH run honesty_guard
    # at Stop, so the PM seat and the writer seat are bound by one implementation — parity by
    # construction rather than by two files agreeing.
    try:
        from tools.pm_verify_lock import pm_verify_repo_violations
    except ImportError:
        from pm_verify_lock import pm_verify_repo_violations  # type: ignore
    bad.extend(pm_verify_repo_violations(text))
    if not bad:
        return 0
    sys.stderr.write(
        "BLOCKED (RC-209) — OPERATOR LAW: no lie, no omission, no dodge; .md is not a lock.\n\n"
        + "\n".join(f"    {b}" for b in bad)
        + "\n\nAnswer the question plainly (Yes/No or N/10). Do not substitute a report file "
          "for a .py BLOCK. Remove soft_partial theater or stop claiming 10/10.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
