"""PROOF-ONLY GUARD — blocks a turn that cites MEMORY or a PRIOR VERDICT as evidence (RC-87).

OPERATOR LAW, 2026-07-27, non-negotiable: "no memory ever cited. only proof."

WHY THIS EXISTS. Every other lock in this repo fires on an artifact — a tool call, a file, a
commit. The agent's most expensive failure has no artifact: it is a SENTENCE. On 2026-07-27 the
agent repeatedly cited "GEX-R1 RETIRED BY MEASUREMENT" as settled fact across several answers.
The operator challenged it. The measurement that followed showed the retirement study had n=66,
a 95% CI of [-0.289, +0.194] which CONTAINS the founding -0.22 it was used to reject, and 43%
power to detect that effect. The verdict was a coin flip recorded as a kill, and it had been
propagating through the agent's reasoning for days because a memory line said "RETIRED".

The failure is structural, not incidental: a conclusion inherits the confidence of its LABEL
instead of the quality of its INPUTS, and prose is the one surface with no gate on it.

WHAT THIS BLOCKS. The agent's final message of a turn, when it
  (a) cites remembered/prior knowledge as the basis of a claim — "per my memory", "we established",
      "the standing verdict", "as I recorded", "previously proven" — or
  (b) states a hard verdict (KILL / PROVEN / RETIRED / CONFIRMED / DISPROVEN) without an
      accompanying same-turn proof: a runnable command in backticks, or an n= with a confidence
      interval.

WHAT IT DOES NOT BLOCK. Reporting a measurement made THIS turn; quoting a memory in order to
CORRECT or void it (the correction verbs are recognised); ordinary work. The point is not to
forbid referring to the past — it is to forbid the past standing in for evidence.

Contract:
  * Stop hook. Exit 2 blocks the stop and feeds stderr back so the agent must produce the proof.
  * Honours `stop_hook_active` — a guard that cannot be satisfied is a hang, not a control.
  * Reads the transcript at `transcript_path`; if that is unavailable the guard reports the
    failure rather than passing silently (RC-57: unmeasurable is never a pass).
  * ED_PROOF_ONLY_GUARD=off disables it. Deliberate and visible: an operator may switch it off;
    an agent may not silently route around it.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Citing remembered knowledge as the ground of a claim. These are the phrases that let a stale
#: conclusion re-enter as evidence without anyone re-deriving it.
MEMORY_CITATION = re.compile(
    r"\b("
    r"per my memory|from memory|my memory (?:says|records|has)|i remember|as i recall|"
    r"we (?:established|determined|concluded|proved|already know)|"
    r"the standing verdict|standing verdict|as (?:i )?recorded|previously (?:proven|established|measured)|"
    r"it (?:was|is) already (?:proven|established|settled)|"
    r"(?:my|the) (?:memory|record) (?:file )?(?:says|states)|"
    r"by your own standing verdict|according to (?:my|the) (?:notes|memory|record)"
    r")\b", re.I)

#: Hard verdicts. Stating one is a claim of settled fact and must carry this turn's evidence.
VERDICT = re.compile(
    r"\b(KILL(?:ED|S)?|RETIRED|PROVEN|DISPROVEN|CONFIRMED|SETTLED|VOID(?:ED)?|"
    r"NULL RESULT|NO EFFECT|does not replicate|failed to replicate)\b")

#: Same-turn proof. A runnable command, or a sample size beside an interval.
#: E-36 follow-up: curl / live-URL probes ARE proof commands — the first control run of the
#: defect-report rule showed a genuine live probe failing to count as evidence.
COMMAND = re.compile(
    r"`[^`]*(python|pytest|SELECT |tools/|\.py|npm |node |git |curl |127\.0\.0\.1)[^`]*`", re.I)
INTERVAL = re.compile(r"\bn\s*=\s*\d+", re.I)
CI = re.compile(r"(95%\s*CI|confidence interval|\bpower\b|\bp\s*=\s*0?\.\d+)", re.I)

#: RC-86 — a COMMITMENT made in prose that never became an artifact. On 2026-07-27 the agent wrote
#: "Opening it as RC-86 and fixing now" in two separate turns and never created the row or the fix;
#: the operator found the gap. stop_guard.py cannot see it, because it only inspects rows that
#: EXIST — work promised but never opened leaves nothing to inspect. RC-87 gated CLAIMS made in
#: prose; this gates PROMISES made in prose, which is the same unguarded surface.
PROMISED_RC = re.compile(r"\b(?:open(?:ing)?|fil(?:e|ing)|creat(?:e|ing))\b[^.\n]{0,40}?\b(RC-\d+)",
                         re.I)

#: Correcting or voiding a remembered claim is the CURE, never the disease.
CORRECTING = re.compile(
    r"\b(i was wrong|disproves|disproven|correcting|correction|retract|reclassif|"
    r"void(?:ing)? (?:that|this|the)|no longer (?:cite|claim)|stop citing|"
    r"unproven|cannot be cited|not settled|insufficient (?:power|evidence))\b", re.I)


def last_assistant_text(transcript_path: str) -> str | None:
    """Concatenated text of the final assistant message in the transcript."""
    p = Path(transcript_path)
    if not p.exists():
        return None
    last: str | None = None
    try:
        with p.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = rec.get("message") or {}
                if rec.get("type") != "assistant" and msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    last = content
                elif isinstance(content, list):
                    parts = [c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text"]
                    if any(parts):
                        last = "\n".join(parts)
    except OSError:
        return None
    return last


def last_user_text(transcript_path: str) -> str | None:
    """Concatenated text of the final USER message (the turn's trigger)."""
    p = Path(transcript_path)
    if not p.exists():
        return None
    last: str | None = None
    try:
        with p.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = rec.get("message") or {}
                if rec.get("type") != "user" and msg.get("role") != "user":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    last = content
                elif isinstance(content, list):
                    parts = [c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text"]
                    if any(parts):
                        last = "\n".join(parts)
    except OSError:
        return None
    return last


#: E-36 (2026-07-29): the operator reported a dead screen and the reply EXPLAINED from the
#: screenshot instead of probing the live system at answer time — right by luck, unverifiable
#: by the operator. A defect report is an order to MEASURE FIRST.
DEFECT_REPORT = re.compile(
    r"not (?:work|render|refresh|show|updat)|broken|still not|doesn'?t work|"
    r"why did you break|no (?:candles|bars|data|volume)|blank (?:screen|chart|page)|went dark",
    re.I)


def defect_report_needs_probe(user_text: str | None, assistant_text: str) -> str | None:
    """When the triggering message alleges a broken surface, the reply must CARRY a same-turn
    probe artifact (a runnable command in backticks / fenced output) — explanation without
    measurement is the E-36 class regardless of whether the explanation is correct."""
    if not user_text or not DEFECT_REPORT.search(user_text):
        return None
    if COMMAND.search(assistant_text):
        return None
    return ("the operator reported a broken surface and this reply carries NO same-turn probe "
            "artifact. Measure first: probe the live system, paste the output, then explain. "
            "Being right from a screenshot is luck wearing a lab coat (E-36).")


def rc_rows_present() -> set[str]:
    """RC ids that actually exist in the governance log."""
    log = REPO / "governance" / "root_cause_log.md"
    try:
        return set(re.findall(r"^\| (RC-\d+) ", log.read_text(encoding="utf-8"), re.M))
    except OSError:
        return set()


def violations(text: str) -> list[str]:
    """Memory-as-evidence, verdicts with no same-turn proof, and promises with no artifact."""
    out: list[str] = []
    # RC-86: a row the turn says it is opening must EXIST by the time the turn ends.
    promised = {m.group(1) for m in PROMISED_RC.finditer(text)}
    if promised:
        existing = rc_rows_present()
        for rc in sorted(promised - existing):
            out.append(
                f"this turn says it is opening/filing {rc}, but no '| {rc} ' row exists in "
                f"governance/root_cause_log.md — a promise that never became an artifact")
    correcting = bool(CORRECTING.search(text))
    has_command = bool(COMMAND.search(text))
    has_stats = bool(INTERVAL.search(text) and CI.search(text))

    for m in MEMORY_CITATION.finditer(text):
        if correcting:
            continue          # quoting memory in order to void it is the fix, not the fault
        out.append(f"memory cited as evidence: {m.group(0)!r}")

    if not (has_command or has_stats or correcting):
        for m in VERDICT.finditer(text):
            out.append(
                f"verdict {m.group(0)!r} stated with no same-turn proof "
                f"(no runnable command in backticks, no n= with an interval/power)")
            break
    return out


def main() -> int:
    try:
        from tools.hard_law_runtime import env_guard_is_disabled, stop_reentry_bypasses_hard_laws
    except ImportError:
        from hard_law_runtime import env_guard_is_disabled, stop_reentry_bypasses_hard_laws  # type: ignore
    if env_guard_is_disabled("ED_PROOF_ONLY_GUARD"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                              # unreadable hook input is never a block
    if payload.get("stop_hook_active") is True and stop_reentry_bypasses_hard_laws(payload):
        return 0

    tp = payload.get("transcript_path")
    if not tp:
        return 0                              # nothing to inspect — not a finding
    text = last_assistant_text(tp)
    if text is None:
        sys.stderr.write(
            "BLOCKED (RC-87): the proof-only guard could not read the transcript at "
            f"{tp!r}, so it cannot tell whether this turn cited memory as evidence. A check that "
            "cannot run is reported, never treated as a pass.\n")
        return 2

    bad = violations(text)
    probe_gap = defect_report_needs_probe(last_user_text(tp), text)
    if probe_gap:
        bad.append(probe_gap)
    if not bad:
        return 0

    sys.stderr.write(
        "BLOCKED (RC-87) — OPERATOR LAW: no memory ever cited, only proof.\n\n"
        + "\n".join(f"    {b}" for b in bad)
        + "\n\nA remembered conclusion carries the confidence of its LABEL, not the quality of its\n"
          "INPUTS. 'GEX-R1 RETIRED BY MEASUREMENT' propagated for days; the measurement behind it\n"
          "had n=66, a 95% CI of [-0.289, +0.194] containing the -0.22 it was used to reject, and\n"
          "43% power. A coin flip recorded as a kill.\n\n"
        "Do ONE of these, then continue:\n"
        "  1. RE-DERIVE the claim this turn and show the command output that establishes it.\n"
        "  2. State it as UNPROVEN and say what measurement would settle it.\n"
        "  3. If you are quoting memory in order to CORRECT or VOID it, say so explicitly.\n\n"
        "Do not restate the claim more carefully. Re-derive it or drop it.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
