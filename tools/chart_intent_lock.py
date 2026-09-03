"""Chart-intent + next-RTH residual language locks (RC-163).

Operator mandate 2026-07-30: mechanically detect the Cursor mess-up class —
(1) claiming Collect / accrual Done while Chart render stays OUT-OF-SCOPE or soft
    OBSERVED without an open Chart residual / proven consumer;
(2) scheduling live proof as "Monday proof" when the next RTH is not Monday.

Shared by:
  * tools/check_institutional_correctness.py  (pre-commit BLOCK)
  * tools/pretooluse_guard.py                 (Edit/Write BLOCK)

Keep this module lean — PreToolUse imports it on every edit.

SOFT (documented, not machine-detected without NLP hell):
  * "one viewport" Done without a two-viewport mention
  * treating "freeze without live volume" as Chart proof
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

# ── path scope (residual / handoff / RC / prompt prose) ──────────────────────


def _normalize(rel: str) -> str:
    """The ONE repo-relative spelling (RC-508). Imported lazily so this module stays a leaf
    that PreToolUse can load on every edit without dragging the guard in at import time."""
    from tools.pretooluse_guard import normalize_repo_relative
    return normalize_repo_relative(rel)


_PROMPT_PATH_HINT = re.compile(
    r"(?:prompt|agent.?instruction|claude.?finish|cursor.?prompt|handoff|protocol)",
    re.I,
)


def is_residual_language_path(rel: str) -> bool:
    """Paths whose Write/Edit / staged ADDED text is gated for Chart-intent + next-RTH.

    SIMPLICITY REHAB 2026-08-24 (T2-5): reports/** and .claude/** DROPPED from the
    gated surface — policing every report and agent-scratch markdown for Done-framing
    was 2026-07-30 program-era scope. The law still binds where the claims land:
    charter files, cursor rules, the ledger, and explicit handoff/prompt files.

    RC-508: this carried the RC-506 bug UNFIXED for two more days. `lstrip("./")` strips
    CHARACTERS, not a prefix, so `.cursor/rules/x.mdc` became `cursor/rules/x.mdc` and the
    `.cursor/rules/` test below could never fire — the RC-163 gate was DEAD on a class this
    docstring says it gates — while `.claude/handoff_prompt.md` lost its dot and slipped past
    its own exclusion, so agent scratch was OVER-blocked. MEASURED 2026-09-03 before the fix:
    `.cursor/rules/00-always.mdc` -> False and `.claude/handoff_prompt.md` -> True, both
    inverted. The spelling now has ONE owner."""
    r = _normalize(rel)
    if r in ("AGENTS.md", "CLAUDE.md", "ACTIVE_PROGRAM.md"):
        return True
    if r.startswith(".cursor/rules/"):
        return True
    if r == "governance/root_cause_log.md":
        return True
    if r.startswith(("reports/", ".claude/")):
        return False
    if "handoff" in Path(r).name.lower() and r.endswith((".md", ".txt")):
        return True
    if _PROMPT_PATH_HINT.search(Path(r).name) and r.endswith((".md", ".mdc", ".txt")):
        return True
    return False


# ── Chart intent soft-out ────────────────────────────────────────────────────

_CHART_INTENT_OK = re.compile(r"chart-intent-ok\s*:", re.I)

# Finish language for Collect / accrual / bank / slice (or Chart mandate Done).
_COLLECT_DONE = re.compile(
    r"(?:"
    r"\b(?:Collect(?:\s+slice)?|accrual|bank(?:ed|ing)?|slice)\b"
    r".{0,100}\b(?:ACCEPT|ACCEPTED|CLOSED|Done|COMPLETE(?:D)?)\b"
    r"|"
    r"\b(?:ACCEPT|ACCEPTED|CLOSED|Done|COMPLETE(?:D)?)\b"
    r".{0,100}\b(?:Collect(?:\s+slice)?|accrual|bank(?:ed|ing)?)\b"
    r"|"
    r"\bChart\s+mandate\b.{0,80}\b(?:ACCEPT|ACCEPTED|CLOSED|Done|COMPLETE(?:D)?)\b"
    r"|"
    r"\b(?:ACCEPT|ACCEPTED|CLOSED|Done|COMPLETE(?:D)?)\b.{0,80}\bChart\s+mandate\b"
    r")",
    re.I | re.S,
)

# Chart surface soft-scoped or soft-observed (the escape hatch that launders Done).
_CHART_SOFT = re.compile(
    r"(?:"
    r"OUT-OF-SCOPE[:\s].{0,140}"
    r"(?:[Cc]hart|render|paint|yellow\s+bars?|GEX\s+bars?|gamma\s+bars?|"
    r"option\s+volume|dealer\s+gamma)"
    r"|"
    r"(?:[Cc]hart|render|paint|yellow\s+bars?|GEX\s+bars?|gamma\s+bars?|"
    r"option\s+volume|dealer\s+gamma).{0,140}OUT-OF-SCOPE"
    r"|"
    r"(?:OBSERVED[,\s]+(?:NOT\s+FIXED|not\s+fixed)|soft\s+OBSERVED)"
    r".{0,100}(?:[Cc]hart|render|paint|yellow|GEX\s+bars?)"
    r"|"
    r"(?:[Cc]hart|render|paint|yellow\s+bars?|GEX\s+bars?)"
    r".{0,100}(?:OBSERVED[,\s]+(?:NOT\s+FIXED|not\s+fixed)|soft\s+OBSERVED)"
    r")",
    re.I | re.S,
)

# Honest incompleteness: STATUS PARTIAL naming an open Chart residual.
_PARTIAL_CHART_RESIDUAL = re.compile(
    r"(?:"
    r"\b(?:STATUS\s+)?PARTIAL\b.{0,220}"
    r"\b(?:P0|CHART_CONSUMER|Chart\s+residual|chart\s+consumer|"
    r"Chart\s+(?:render|paint|consumer)\s+residual|"
    r"open\s+Chart\s+residual)\b"
    r"|"
    r"\b(?:P0|CHART_CONSUMER|Chart\s+residual|chart\s+consumer|"
    r"Chart\s+(?:render|paint|consumer)\s+residual|"
    r"open\s+Chart\s+residual)\b.{0,220}\b(?:STATUS\s+)?PARTIAL\b"
    r")",
    re.I | re.S,
)

_PROVEN_CHART_CONSUMER = re.compile(
    r"(?:"
    r"Chart\s+consumer\s+proven|proven\s+Chart\s+consumer|"
    r"latest_accrual_rows|"
    r"option_chain_accrual.{0,60}(?:reader|consumer|faucet)|"
    r"accrual_bank:"
    r")",
    re.I | re.S,
)

# Banking ≠ render Done: Chart product Done claimed via bank/accrual alone.
_BANK_AS_CHART_DONE = re.compile(
    r"(?:"
    r"(?:Chart\s+mandate|accumulate(?:\s+and\s+|\s*/\s*|\s+)render|"
    r"yellow.{0,40}(?:GEX|gamma)|render\s+on\s+the\s+Chart)"
    r".{0,160}(?:accrual|bank(?:ed|ing)?).{0,80}"
    r"\b(?:ACCEPT|ACCEPTED|CLOSED|Done|COMPLETE(?:D)?)\b"
    r"|"
    r"(?:accrual|bank(?:ed|ing)?).{0,80}"
    r"\b(?:ACCEPT|ACCEPTED|CLOSED|Done|COMPLETE(?:D)?)\b.{0,160}"
    r"(?:Chart\s+mandate|accumulate(?:\s+and\s+|\s*/\s*|\s+)render|"
    r"yellow.{0,40}(?:GEX|gamma)|Chart\s+(?:Done|COMPLETE(?:D)?|ACCEPT))"
    r")",
    re.I | re.S,
)


def chart_intent_soft_out_violation(text: str) -> str | None:
    """Return a reason when Collect/Chart Done is claimed while Chart stays soft-out."""
    if not text or not text.strip():
        return None
    if _CHART_INTENT_OK.search(text):
        return None
    if _PARTIAL_CHART_RESIDUAL.search(text):
        return None
    if _PROVEN_CHART_CONSUMER.search(text) and not _CHART_SOFT.search(text):
        # Proven consumer present and no Chart soft-out — banking-complete is honest.
        if _BANK_AS_CHART_DONE.search(text) or _COLLECT_DONE.search(text):
            return None

    soft = _CHART_SOFT.search(text)
    done = _COLLECT_DONE.search(text)
    bank_as_done = _BANK_AS_CHART_DONE.search(text)

    if done and soft:
        return (
            "Chart-intent soft-out: Collect/accrual/bank finish language "
            f"({done.group(0)[:80]!r}) while Chart/render is OUT-OF-SCOPE or soft "
            "OBSERVED — require proven Chart consumer, STATUS PARTIAL naming an open "
            "P0/CHART_CONSUMER residual, or # chart-intent-ok: + operator waiver (RC-163)"
        )
    if bank_as_done and not _PROVEN_CHART_CONSUMER.search(text):
        return (
            "Banking ≠ render Done: Chart mandate framed complete via accrual/bank "
            "without a proven Chart consumer — require latest_accrual_rows / consumer "
            "proof, STATUS PARTIAL + open Chart residual, or # chart-intent-ok: (RC-163)"
        )
    return None


# ── Next-RTH residual weekday lies ───────────────────────────────────────────

_MONDAY_PROOF = re.compile(
    r"\b(?:"
    r"Monday\s+live\s+proof|Monday\s+proof|Monday\s+RTH\s+proof|"
    r"next\s+Monday(?:\s+(?:live\s+)?proof)?|MONDAY_PROOF|MONDAY\s+PROOF"
    r")\b",
    re.I,
)
_NEXT_RTH_OK = re.compile(r"next-rth-ok\s*:", re.I)


def next_rth_et_date(as_of: datetime | None = None) -> date:
    """Next US equity RTH calendar date in America/New_York.

    If `as_of` falls on a trading day before RTH close, that day is still next.
    After close (or on a non-trading day), walk forward to the next trading day.
    """
    from time_et import RTH_END_MINS, is_trading_day_et, now_et

    n = as_of if as_of is not None else now_et()
    if n.tzinfo is None:
        from time_et import ET
        n = n.replace(tzinfo=ET)
    d = n.date()
    mins = n.hour * 60 + n.minute
    if is_trading_day_et(d.isoformat()) and mins < RTH_END_MINS:
        return d
    cur = d + timedelta(days=1)
    for _ in range(21):
        if is_trading_day_et(cur.isoformat()):
            return cur
        cur += timedelta(days=1)
    raise RuntimeError("no trading day found within 21 calendar days")


def next_rth_monday_lie_violation(
    text: str,
    *,
    as_of: datetime | None = None,
) -> str | None:
    """Block hardcoded Monday proof language when next RTH is not Monday."""
    if not text or not text.strip():
        return None
    if _NEXT_RTH_OK.search(text):
        return None
    m = _MONDAY_PROOF.search(text)
    if not m:
        return None
    # Historical gate filenames (gex_r1_monday_collector_gate*) do not match
    # _MONDAY_PROOF — only forward residual phrases like "Monday proof" do.
    nxt = next_rth_et_date(as_of)
    if nxt.weekday() == 0:  # Monday
        return None
    weekday = nxt.strftime("%A")
    return (
        f"Next-RTH residual calendar lie: {m.group(0)!r} but next RTH is "
        f"{nxt.isoformat()} {weekday} (America/New_York via is_trading_day_et) — "
        f"use NEXT_RTH_PROOF + ISO date, or # next-rth-ok: with the computed date (RC-163)"
    )


def residual_language_violations(
    text: str,
    *,
    as_of: datetime | None = None,
) -> list[str]:
    """All residual-language reasons for a text blob (Chart intent + next-RTH)."""
    out: list[str] = []
    for fn in (
        chart_intent_soft_out_violation,
        lambda t: next_rth_monday_lie_violation(t, as_of=as_of),
    ):
        reason = fn(text)
        if reason:
            out.append(reason)
    return out
