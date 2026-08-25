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

WHAT THIS BLOCKS. The turn's assistant text (every text block after the last user message,
not just the final record), when it
  (a) cites remembered/prior knowledge as the basis of a claim — "per my memory", "we established",
      "the standing verdict", "as I recorded", "previously proven". HONEST LIMIT: the memory
      lexicon is a deterrent over KNOWN phrasings — paraphrase escapes it; memory-as-evidence
      cannot be detected semantically. The operator law it enforces is model-side discipline
      with a tripwire, not a proof. Or
  (b) states a hard verdict (KILL / PROVEN / RETIRED / CONFIRMED / DISPROVEN) without the SHAPE
      of same-turn proof: a backticked command that actually RAN this turn (cross-checked
      against the transcript's tool calls), or an n= with a confidence interval. HONEST LIMIT:
      it cannot verify the numbers are real or the statistics adequate — a weak measurement
      stated with its stats passes, by design (the guard's own founding story, n=66 at 43%
      power recorded as a kill, would pass this check); adequacy review stays with the operator.

WHAT IT DOES NOT BLOCK. Reporting a measurement made THIS turn; quoting a memory in order to
CORRECT or void it (the correction verbs are recognised); ordinary work. The point is not to
forbid referring to the past — it is to forbid the past standing in for evidence.

Contract:
  * Stop hook. Exit 2 blocks the stop and feeds stderr back so the agent must produce the proof.
  * Honours `stop_hook_active` — a guard that cannot be satisfied is a hang, not a control.
  * Reads the transcript at `transcript_path`; if that is unavailable the guard reports the
    failure rather than passing silently (RC-57: unmeasurable is never a pass).
  * Architecture A (RC-450): ED_PROOF_ONLY_GUARD cannot disable this control.
"""
from __future__ import annotations

import json
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
    r"(?:my|the) (?:memory|record) (?:file )?(?:says|states|notes)|"
    r"by your own standing verdict|according to (?:my|the) (?:notes|memory|record)|"
    r"MEMORY\.md\b[^.\n]{0,60}\b(?:says|records|notes|states|shows)|"
    r"(?:the|our|an?) (?:earlier|prior|previous) (?:audit|study|run|measurement|analysis|verdict)\b"
    r"[^.\n]{0,40}\b(?:showed|established|proved|found|settled)|"
    r"as established\b|you(?:'ll| will) recall|known[- ](?:dead|good|settled|retired)"
    r")\b", re.I)

#: Hard verdicts. Stating one is a claim of settled fact and must carry this turn's evidence.
#: Single-word verdicts stay CAPS-ONLY on purpose (re.I floods: 'killed the process',
#: 'settled on a design') — a verdict smuggled into lowercase prose is out of reach of
#: wording-shape detection; only the low-collision multiword phrases are case-insensitive.
VERDICT = re.compile(
    r"\b(KILL(?:ED|S)?|RETIRED|PROVEN|DISPROVEN|CONFIRMED|SETTLED|VOID(?:ED)?|"
    r"NO EFFECT|(?i:NULL RESULT|does not replicate|failed to replicate))\b")

#: Affirmative verdicts assert NEW settled fact; they can never ride a correction.
AFFIRMATIVE_VERDICT = re.compile(r"\b(KILL(?:ED|S)?|RETIRED|PROVEN|CONFIRMED|SETTLED)\b")

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
PROMISED_RC = re.compile(
    r"\b(?:open(?:ed|ing)?|fil(?:e|ed|ing)|creat(?:e|ed|ing)|log(?:ged|ging)?|"
    r"add(?:ed|ing)?|record(?:ed|ing)?)\b[^.\n]{0,40}?\b(RC-\d+)", re.I)

#: Correcting or voiding a remembered claim is the CURE, never the disease.
CORRECTING = re.compile(
    r"\b(i was wrong|disproves|disproven|correcting|correction|retract|reclassif\w*|"
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


def turn_slice(transcript_path: str) -> tuple[str | None, list[str]]:
    """(assistant text of THIS turn, shell commands that RAN WITHOUT ERROR this turn).

    The turn boundary is the LAST user record carrying real text (tool_result records
    are user-role but carry no text block). Assistant text is every text block after
    that boundary concatenated — judging only the final assistant record let a verdict
    hide behind a bland 'Done.' tail record. Commands are the input.command of every
    Bash/PowerShell tool_use block after the boundary; command-carrying tools only —
    a Read file_path is not an executed command.

    RESULT, NOT ISSUANCE (operator requirement, 2026-08-25): a command counts only when
    its tool_result exists in the same transcript and does not carry is_error=true —
    issuing `pytest` that then FAILED is not proof. A command with no result record at
    all (interrupted mid-call) does not count either. HONEST LIMIT: is_error=false
    proves the tool call completed without a harness-level error (for Bash, a nonzero
    exit surfaces as is_error); it cannot judge whether the OUTPUT supports the claim —
    that residue is the operator's read.
    """
    p = Path(transcript_path)
    if not p.exists():
        return None, []
    records: list[tuple[str, list[str], list[tuple[str, str]]]] = []
    result_error_by_id: dict[str, bool] = {}
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
                role = rec.get("type") if rec.get("type") in ("user", "assistant") else msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content")
                texts: list[str] = []
                cmds: list[tuple[str, str]] = []
                if isinstance(content, str):
                    if content.strip():
                        texts.append(content)
                elif isinstance(content, list):
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "text" and c.get("text", "").strip():
                            texts.append(c["text"])
                        elif c.get("type") == "tool_use" and c.get("name") in ("Bash", "PowerShell", "Shell"):
                            cmd = (c.get("input") or {}).get("command")
                            if isinstance(cmd, str) and cmd.strip():
                                cmds.append((str(c.get("id") or ""), cmd))
                        elif c.get("type") == "tool_result":
                            tid = str(c.get("tool_use_id") or "")
                            if tid:
                                result_error_by_id[tid] = bool(c.get("is_error"))
                records.append((role, texts, cmds))
    except OSError:
        return None, []
    boundary = -1
    for i, (role, texts, _c) in enumerate(records):
        if role == "user" and texts:
            boundary = i
    texts_out: list[str] = []
    cmds_out: list[str] = []
    for role, texts, cmds in records[boundary + 1:]:
        if role == "assistant":
            texts_out.extend(texts)
            for tid, cmd in cmds:
                # RESULT REQUIRED: no result record, or is_error=true -> not proof.
                if tid and result_error_by_id.get(tid) is False:
                    cmds_out.append(cmd)
    return ("\n".join(texts_out) if texts_out else None), cmds_out


def _norm_ws(s: str) -> str:
    return " ".join(s.split())


def has_executed_command(text: str, executed: list[str]) -> bool:
    """True when a backticked command-shaped snippet in `text` matches a command that
    actually RAN this turn (whitespace-normalized bidirectional substring). A command
    string in prose is proof-SHAPED; only one that was issued is proof. Restricting the
    match set to Bash/PowerShell commands (never Read file_paths) keeps a merely-
    mentioned filename from becoming proof again."""
    if not executed:
        return False
    ran = [_norm_ws(c) for c in executed]
    for m in COMMAND.finditer(text):
        snippet = _norm_ws(m.group(0).strip("`"))
        if snippet and any(snippet in c or c in snippet for c in ran):
            return True
    return False


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


def defect_report_needs_probe(user_text: str | None, assistant_text: str,
                              executed: list[str] | None = None) -> str | None:
    """When the triggering message alleges a broken surface, the reply must CARRY a same-turn
    probe artifact (a runnable command in backticks / fenced output) — explanation without
    measurement is the E-36 class regardless of whether the explanation is correct.
    When the caller supplies this turn's executed commands, the cited probe must have RUN."""
    if not user_text or not DEFECT_REPORT.search(user_text):
        return None
    probed = (COMMAND.search(assistant_text) if executed is None
              else has_executed_command(assistant_text, executed))
    if probed:
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


def violations(text: str, executed: list[str] | None = None) -> list[str]:
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
    # A cited command is proof only when it actually RAN this turn (tool_use
    # cross-check). executed=None = legacy caller with no transcript: presence-only.
    has_command = (bool(COMMAND.search(text)) if executed is None
                   else has_executed_command(text, executed))
    has_stats = bool(INTERVAL.search(text) and CI.search(text))

    for m in MEMORY_CITATION.finditer(text):
        # A correction exempts a memory citation only when it is ABOUT that citation —
        # same neighbourhood (±200 chars), not anywhere in the message: one hedged
        # aside used to disable the whole guard.
        lo, hi = max(0, m.start() - 200), m.end() + 200
        if CORRECTING.search(text[lo:hi]):
            continue          # quoting memory in order to void it is the fix, not the fault
        out.append(f"memory cited as evidence: {m.group(0)!r}")

    if not (has_command or has_stats):
        aff = AFFIRMATIVE_VERDICT.search(text)
        m = aff or VERDICT.search(text)
        # A correction may carry a correction-class verdict (DISPROVEN/VOID/...); an
        # AFFIRMATIVE verdict (CONFIRMED/PROVEN/KILLED/RETIRED/SETTLED) needs this
        # turn's command or stats no matter what else the message hedges about.
        if m is not None and (aff is not None or not correcting):
            out.append(
                f"verdict {m.group(0)!r} stated with no same-turn proof "
                f"(no backticked command that actually RAN this turn, no n= with an "
                f"interval/power)")
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                              # unreadable hook input is never a block
    if payload.get("stop_hook_active") is True:
        return 0                              # already blocked once; never loop

    tp = payload.get("transcript_path")
    if not tp:
        sys.stderr.write(
            "BLOCKED (RC-87): the Stop payload carries no transcript_path, so the "
            "proof-only guard cannot tell whether this turn cited memory as evidence. "
            "A check that cannot run is reported, never treated as a pass (RC-57).\n")
        return 2
    text, executed = turn_slice(tp)
    if text is None:
        sys.stderr.write(
            "BLOCKED (RC-87): the proof-only guard could not read the transcript at "
            f"{tp!r}, so it cannot tell whether this turn cited memory as evidence. A check that "
            "cannot run is reported, never treated as a pass.\n")
        return 2

    bad = violations(text, executed)
    probe_gap = defect_report_needs_probe(last_user_text(tp), text, executed)
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
