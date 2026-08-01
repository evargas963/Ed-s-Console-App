"""One-shot patcher: wire RC-163 into institutional gate + pretooluse + AGENTS + settings."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def wire_institutional() -> None:
    p = ROOT / "tools" / "check_institutional_correctness.py"
    src = p.read_text(encoding="utf-8")
    if "def check_chart_intent_and_next_rth" in src:
        print("institutional: already wired")
        return
    insert = '''

def check_chart_intent_and_next_rth() -> list[Violation]:
    """Chart-intent soft-out + next-RTH weekday lies in residual prose (RC-163).

    WHAT WAS OBSERVED (operator 2026-07-30): Cursor repeatedly closed Collect /
    accrual slices as ACCEPT/Done while Chart render (yellow OV / GEX bars) stayed
    OUT-OF-SCOPE or soft OBSERVED with no open P0/CHART_CONSUMER residual — banking
    was treated as product delivery. Separately, forward residuals used a hardcoded
    weekday-named live-proof label when the next RTH (America/New_York +
    is_trading_day_et) was Friday 2026-07-31. Both are the goodwill-instead-of-lock
    class RC-66/RC-160 already named; Chart intent and residual calendars had no
    detector.

    Rule (practical — binds STAGED ADDED text on residual/handoff/RC/prompt paths,
    not historical whole-file prose):
      1. Collect/accrual/bank finish language + Chart OUT-OF-SCOPE / soft OBSERVED
         without proven consumer / STATUS PARTIAL + Chart residual /
         `# chart-intent-ok:` → BLOCK.
      2. Chart mandate framed Done via bank/accrual alone without proven consumer
         → BLOCK (same escape set).
      3. Weekday-named live-proof phrases (Monday proof / Monday live proof /
         MONDAY_PROOF / next Monday) when next RTH weekday ≠ Monday → BLOCK unless
         `# next-rth-ok:` + computed date.

    HOW THE RULE WAS VALIDATED: negative controls in
    tests/test_chart_intent_lock_v1.py inject Done+Chart-OOS and Monday-proof-on-
    Friday blobs and demand a scream; PARTIAL+CHART_CONSUMER, chart-intent-ok,
    next-rth-ok, and NEXT_RTH_PROOF+Friday stay quiet. Live tree staged scan is
    empty outside a commit context (no false block).
    """
    from tools.chart_intent_lock import (
        is_residual_language_path,
        residual_language_violations,
    )

    out: list[Violation] = []
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return out
    for raw in staged:
        rel = raw.strip().replace("\\\\", "/")
        if not rel or not is_residual_language_path(rel):
            continue
        path = REPO / rel
        whole = _read_or_empty(path)
        diff = _git_output_lines(["diff", "--cached", "-U0", "--", rel]) or []
        added = "\\n".join(
            ln[1:] for ln in diff
            if ln.startswith("+") and not ln.startswith("+++")
        )
        text = added if added.strip() else whole
        for reason in residual_language_violations(text):
            out.append(Violation(path, 0, reason))
    return out


'''
    # Fix the accidental double-escaping from writing this as a script string.
    insert = insert.replace("replace(\"\\\\\", \"/\")", 'replace("\\\\", "/")')
    insert = insert.replace('"\\n".join', '"\\n".join')
    # Rebuild insert cleanly without escape confusion:
    insert = _institutional_insert()
    anchor = (
        "# (name, check, enforced). ENFORCED checks must be zero — they block pre-commit."
    )
    if anchor not in src:
        raise SystemExit("anchor missing")
    src = src.replace(anchor, insert + anchor, 1)
    old = (
        '    ("universal_ticker_scope", check_universal_ticker_scope, True),  '
        "# RC-160: no SPY-only work framed as complete\n"
        '    ("chain_width_single_faucet"'
    )
    new = (
        '    ("universal_ticker_scope", check_universal_ticker_scope, True),  '
        "# RC-160: no SPY-only work framed as complete\n"
        '    ("chart_intent_and_next_rth", check_chart_intent_and_next_rth, True),  '
        "# RC-163: Chart Done ≠ bank; no weekday-proof lies\n"
        '    ("chain_width_single_faucet"'
    )
    if old not in src:
        raise SystemExit("CHECKS insert point missing")
    src = src.replace(old, new, 1)
    p.write_text(src, encoding="utf-8")
    print("institutional: wired")


def _institutional_insert() -> str:
    return r'''

def check_chart_intent_and_next_rth() -> list[Violation]:
    """Chart-intent soft-out + next-RTH weekday lies in residual prose (RC-163).

    WHAT WAS OBSERVED (operator 2026-07-30): Cursor repeatedly closed Collect /
    accrual slices as ACCEPT/Done while Chart render (yellow OV / GEX bars) stayed
    OUT-OF-SCOPE or soft OBSERVED with no open P0/CHART_CONSUMER residual — banking
    was treated as product delivery. Separately, forward residuals used a hardcoded
    weekday-named live-proof label when the next RTH (America/New_York +
    is_trading_day_et) was Friday 2026-07-31. Both are the goodwill-instead-of-lock
    class RC-66/RC-160 already named; Chart intent and residual calendars had no
    detector.

    Rule (practical — binds STAGED ADDED text on residual/handoff/RC/prompt paths,
    not historical whole-file prose):
      1. Collect/accrual/bank finish language + Chart OUT-OF-SCOPE / soft OBSERVED
         without proven consumer / STATUS PARTIAL + Chart residual /
         `# chart-intent-ok:` → BLOCK.
      2. Chart mandate framed Done via bank/accrual alone without proven consumer
         → BLOCK (same escape set).
      3. Weekday-named live-proof phrases (Monday proof / Monday live proof /
         MONDAY_PROOF / next Monday) when next RTH weekday ≠ Monday → BLOCK unless
         `# next-rth-ok:` + computed date.

    HOW THE RULE WAS VALIDATED: negative controls in
    tests/test_chart_intent_lock_v1.py inject Done+Chart-OOS and Monday-proof-on-
    Friday blobs and demand a scream; PARTIAL+CHART_CONSUMER, chart-intent-ok,
    next-rth-ok, and NEXT_RTH_PROOF+Friday stay quiet. Live tree staged scan is
    empty outside a commit context (no false block).
    """
    from tools.chart_intent_lock import (
        is_residual_language_path,
        residual_language_violations,
    )

    out: list[Violation] = []
    staged = _git_output_lines(["diff", "--cached", "--name-only"])
    if staged is None:
        return out
    for raw in staged:
        rel = raw.strip().replace("\\", "/")
        if not rel or not is_residual_language_path(rel):
            continue
        path = REPO / rel
        whole = _read_or_empty(path)
        diff = _git_output_lines(["diff", "--cached", "-U0", "--", rel]) or []
        added = "\n".join(
            ln[1:] for ln in diff
            if ln.startswith("+") and not ln.startswith("+++")
        )
        text = added if added.strip() else whole
        for reason in residual_language_violations(text):
            out.append(Violation(path, 0, reason))
    return out


'''


def wire_pretooluse() -> None:
    p = ROOT / "tools" / "pretooluse_guard.py"
    src = p.read_text(encoding="utf-8")
    if "_block_chart_intent_and_next_rth" in src:
        print("pretooluse: already wired")
        return

    src = src.replace(
        "  * RC-160 UNIVERSAL ticker scope: Write/Edit of prompt / agent-instruction paths is BLOCKED when\n"
        "    the new content frames SPY-only / sentinel-complete work without UNIVERSAL or OUT-OF-SCOPE\n"
        "    language — even under otherwise-allowed prefixes (reports/, .claude/).\n"
        "  * ED_PRETOOLUSE_GUARD=off disables it.",
        "  * RC-160 UNIVERSAL ticker scope: Write/Edit of prompt / agent-instruction paths is BLOCKED when\n"
        "    the new content frames SPY-only / sentinel-complete work without UNIVERSAL or OUT-OF-SCOPE\n"
        "    language — even under otherwise-allowed prefixes (reports/, .claude/).\n"
        "  * RC-163 Chart-intent + next-RTH: Write/Edit of residual/handoff/RC/prompt paths is BLOCKED when\n"
        "    Collect/Chart is framed Done while Chart stays soft OUT-OF-SCOPE/OBSERVED, or when forward\n"
        "    residuals say weekday-named live proof while next RTH is not that weekday — even under\n"
        "    allowed prefixes.\n"
        "  * ED_PRETOOLUSE_GUARD=off disables it.",
        1,
    )
    src = src.replace(
        "#: by the RC-66 production-surface rule. RC-160 still gates prompt/agent-instruction content.",
        "#: by the RC-66 production-surface rule. RC-160/RC-163 still gate residual/prompt content.",
        1,
    )

    _old_block = '''def _block_spy_only_prompt(rel: str, tool_input: dict) -> int | None:
    """RC-160: block SPY-only prompt / agent-instruction Writes. Returns exit code or None."""
    try:
        from tools.universal_scope_lock import (
            is_prompt_or_agent_instruction_path,
            spy_only_content_violation,
        )
    except ImportError:
        # Hook command is `python tools/pretooluse_guard.py` → sys.path[0] is tools/.
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        try:
            from tools.universal_scope_lock import (  # type: ignore[no-redef]
                is_prompt_or_agent_instruction_path,
                spy_only_content_violation,
            )
        except ImportError:
            from universal_scope_lock import (  # type: ignore[no-redef]
                is_prompt_or_agent_instruction_path,
                spy_only_content_violation,
            )
    if not is_prompt_or_agent_instruction_path(rel):
        return None
    text = _tool_new_text(tool_input)
    if not text:
        return None
    reason = spy_only_content_violation(text)
    if reason is None:
        return None
    sys.stderr.write(
        "BLOCKED by the UNIVERSAL ticker-scope law (RC-160).\\n\\n"
        f"  File: {rel}\\n"
        f"  {reason}\\n\\n"
        "Default scope is the enrolled universe, not SPY. Narrow work must say OUT-OF-SCOPE:\\n"
        "(or UNIVERSAL / enrolled-universe / # universal-scope-ok:) with the reason.\\n"
        "Do not prompt Claude or Cursor with SPY-only framing for work treated as complete.\\n"
    )
    return 2


def main() -> int:'''

    # Read exact bytes from file for reliable replace
    start = src.index("def _block_spy_only_prompt")
    end = src.index("def main() -> int:")
    new_fns = '''def _import_lock(module: str, names: tuple[str, ...]):
    """Import helpers whether the hook ran as `python tools/X.py` or as a package."""
    try:
        mod = __import__(f"tools.{module}", fromlist=list(names))
        return tuple(getattr(mod, n) for n in names)
    except ImportError:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        try:
            mod = __import__(f"tools.{module}", fromlist=list(names))
            return tuple(getattr(mod, n) for n in names)
        except ImportError:
            mod = __import__(module, fromlist=list(names))
            return tuple(getattr(mod, n) for n in names)


def _block_spy_only_prompt(rel: str, tool_input: dict) -> int | None:
    """RC-160: block SPY-only prompt / agent-instruction Writes. Returns exit code or None."""
    is_prompt_or_agent_instruction_path, spy_only_content_violation = _import_lock(
        "universal_scope_lock",
        ("is_prompt_or_agent_instruction_path", "spy_only_content_violation"),
    )
    if not is_prompt_or_agent_instruction_path(rel):
        return None
    text = _tool_new_text(tool_input)
    if not text:
        return None
    reason = spy_only_content_violation(text)
    if reason is None:
        return None
    sys.stderr.write(
        "BLOCKED by the UNIVERSAL ticker-scope law (RC-160).\\n\\n"
        f"  File: {rel}\\n"
        f"  {reason}\\n\\n"
        "Default scope is the enrolled universe, not SPY. Narrow work must say OUT-OF-SCOPE:\\n"
        "(or UNIVERSAL / enrolled-universe / # universal-scope-ok:) with the reason.\\n"
        "Do not prompt Claude or Cursor with SPY-only framing for work treated as complete.\\n"
    )
    return 2


def _block_chart_intent_and_next_rth(rel: str, tool_input: dict) -> int | None:
    """RC-163: block Chart soft-out Done claims and weekday-proof calendar lies."""
    is_residual_language_path, residual_language_violations = _import_lock(
        "chart_intent_lock",
        ("is_residual_language_path", "residual_language_violations"),
    )
    if not is_residual_language_path(rel):
        return None
    text = _tool_new_text(tool_input)
    if not text:
        return None
    reasons = residual_language_violations(text)
    if not reasons:
        return None
    sys.stderr.write(
        "BLOCKED by the Chart-intent / next-RTH residual law (RC-163).\\n\\n"
        f"  File: {rel}\\n"
        + "".join(f"  {r}\\n" for r in reasons)
        + "\\n"
        "Escapes: # chart-intent-ok: + operator waiver; STATUS PARTIAL naming an open\\n"
        "P0/CHART_CONSUMER residual; proven Chart consumer; or # next-rth-ok: + computed\\n"
        "next RTH ISO date (America/New_York / is_trading_day_et). Prefer NEXT_RTH_PROOF.\\n"
    )
    return 2


def main() -> int:'''
    # Fix doubled backslashes in write strings — use real newlines in stderr.write
    new_fns = new_fns.replace("\\n\\n", "\n\n").replace("\\n", "\n")
    # The above is too aggressive for f-strings. Rebuild carefully:
    new_fns = _pretooluse_fns()
    src = src[:start] + new_fns + src[end:]

    src = src.replace(
        "    # RC-160 runs BEFORE the RC-66 allowlist — prompt drafts under reports/ must still be universal.\n"
        "    blocked = _block_spy_only_prompt(rel, tool_input)\n"
        "    if blocked is not None:\n"
        "        return blocked\n"
        "\n"
        "    if rel.startswith(ALWAYS_ALLOWED_PREFIXES):\n",
        "    # RC-160 / RC-163 run BEFORE the RC-66 allowlist — residual drafts under reports/ still gate.\n"
        "    blocked = _block_spy_only_prompt(rel, tool_input)\n"
        "    if blocked is not None:\n"
        "        return blocked\n"
        "    blocked = _block_chart_intent_and_next_rth(rel, tool_input)\n"
        "    if blocked is not None:\n"
        "        return blocked\n"
        "\n"
        "    if rel.startswith(ALWAYS_ALLOWED_PREFIXES):\n",
        1,
    )
    p.write_text(src, encoding="utf-8")
    print("pretooluse: wired")


def _pretooluse_fns() -> str:
    return '''def _import_lock(module: str, names: tuple[str, ...]):
    """Import helpers whether the hook ran as `python tools/X.py` or as a package."""
    try:
        mod = __import__(f"tools.{module}", fromlist=list(names))
        return tuple(getattr(mod, n) for n in names)
    except ImportError:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        try:
            mod = __import__(f"tools.{module}", fromlist=list(names))
            return tuple(getattr(mod, n) for n in names)
        except ImportError:
            mod = __import__(module, fromlist=list(names))
            return tuple(getattr(mod, n) for n in names)


def _block_spy_only_prompt(rel: str, tool_input: dict) -> int | None:
    """RC-160: block SPY-only prompt / agent-instruction Writes. Returns exit code or None."""
    is_prompt_or_agent_instruction_path, spy_only_content_violation = _import_lock(
        "universal_scope_lock",
        ("is_prompt_or_agent_instruction_path", "spy_only_content_violation"),
    )
    if not is_prompt_or_agent_instruction_path(rel):
        return None
    text = _tool_new_text(tool_input)
    if not text:
        return None
    reason = spy_only_content_violation(text)
    if reason is None:
        return None
    sys.stderr.write(
        "BLOCKED by the UNIVERSAL ticker-scope law (RC-160).\\n\\n"
        f"  File: {rel}\\n"
        f"  {reason}\\n\\n"
        "Default scope is the enrolled universe, not SPY. Narrow work must say OUT-OF-SCOPE:\\n"
        "(or UNIVERSAL / enrolled-universe / # universal-scope-ok:) with the reason.\\n"
        "Do not prompt Claude or Cursor with SPY-only framing for work treated as complete.\\n"
    )
    return 2


def _block_chart_intent_and_next_rth(rel: str, tool_input: dict) -> int | None:
    """RC-163: block Chart soft-out Done claims and weekday-proof calendar lies."""
    is_residual_language_path, residual_language_violations = _import_lock(
        "chart_intent_lock",
        ("is_residual_language_path", "residual_language_violations"),
    )
    if not is_residual_language_path(rel):
        return None
    text = _tool_new_text(tool_input)
    if not text:
        return None
    reasons = residual_language_violations(text)
    if not reasons:
        return None
    sys.stderr.write(
        "BLOCKED by the Chart-intent / next-RTH residual law (RC-163).\\n\\n"
        f"  File: {rel}\\n"
        + "".join(f"  {r}\\n" for r in reasons)
        + "\\n"
        "Escapes: # chart-intent-ok: + operator waiver; STATUS PARTIAL naming an open\\n"
        "P0/CHART_CONSUMER residual; proven Chart consumer; or # next-rth-ok: + computed\\n"
        "next RTH ISO date (America/New_York / is_trading_day_et). Prefer NEXT_RTH_PROOF.\\n"
    )
    return 2


'''


def wire_agents() -> None:
    p = ROOT / "AGENTS.md"
    src = p.read_text(encoding="utf-8")
    if "RC-163" in src and "check_chart_intent_and_next_rth" in src:
        print("AGENTS: already wired")
        return
    needle = (
        "**UNIVERSAL ticker-scope law (operator 2026-07-30, RC-160; enforced by "
        "`check_universal_ticker_scope`, front end `tools/pretooluse_guard.py` / "
        "`tools/universal_scope_lock.py`, Cursor `.cursor/rules/04-universal-ticker-scope.mdc`).** "
        "Collect, Find & Prove, Chart, prompts, and reports default to the enrolled universe — "
        "never SPY-only / sentinel-only framed as complete. Narrow samples require `OUT-OF-SCOPE:` "
        "(or `# universal-scope-ok:`) with reason; sentinel-clean ≠ operable-clean."
    )
    add = (
        needle
        + "\n\n"
        "**Chart-intent + next-RTH residual law (operator 2026-07-30, RC-163; enforced by "
        "`check_chart_intent_and_next_rth`, front end `tools/pretooluse_guard.py` / "
        "`tools/chart_intent_lock.py`, Cursor `.cursor/rules/05-next-rth-residual-language.mdc`).** "
        "Collect/accrual finish language cannot soft-out Chart render (yellow/GEX bars) as "
        "OUT-OF-SCOPE or soft OBSERVED without an open P0/CHART_CONSUMER residual or proven "
        "consumer — banking ≠ render Done. Forward residuals must not use a hardcoded "
        "weekday-named live-proof label when next RTH (America/New_York + `is_trading_day_et`) "
        "is a different weekday; prefer `NEXT_RTH_PROOF` + ISO date. Escapes: `# chart-intent-ok:` "
        "/ `# next-rth-ok:` with operator waiver or computed date."
    )
    if needle not in src:
        raise SystemExit("AGENTS.md needle missing")
    p.write_text(src.replace(needle, add, 1), encoding="utf-8")
    print("AGENTS: wired")


def wire_settings() -> None:
    p = ROOT / ".claude" / "settings.json"
    src = p.read_text(encoding="utf-8")
    if "RC-163" in src:
        print("settings: already wired")
        return
    old = (
        "RC-160 (operator 2026-07-30): the same hook ALSO BLOCKS Write/Edit of "
        "prompt/agent-instruction paths whose new content frames SPY-only / "
        "sentinel-complete work without UNIVERSAL or OUT-OF-SCOPE language — including "
        "under reports/ and .claude/ — via tools/universal_scope_lock.py. Operator escape: "
        "set ED_PRETOOLUSE_GUARD=off - deliberate and visible; an agent may not silently "
        "route around it."
    )
    new = (
        "RC-160 (operator 2026-07-30): the same hook ALSO BLOCKS Write/Edit of "
        "prompt/agent-instruction paths whose new content frames SPY-only / "
        "sentinel-complete work without UNIVERSAL or OUT-OF-SCOPE language — including "
        "under reports/ and .claude/ — via tools/universal_scope_lock.py. RC-163 "
        "(operator 2026-07-30): ALSO BLOCKS residual/handoff/RC/prompt Writes whose new "
        "content claims Collect/Chart Done while Chart render stays soft OUT-OF-SCOPE/"
        "OBSERVED, or schedules live proof with a hardcoded weekday name when next RTH "
        "(America/New_York + is_trading_day_et) is a different weekday — via "
        "tools/chart_intent_lock.py. Operator escape: set ED_PRETOOLUSE_GUARD=off - "
        "deliberate and visible; an agent may not silently route around it."
    )
    if old not in src:
        raise SystemExit("settings.json needle missing")
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    print("settings: wired")


def fix_pretooluse_newlines() -> None:
    """_pretooluse_fns used \\n literals; rewrite stderr strings to real escapes."""
    p = ROOT / "tools" / "pretooluse_guard.py"
    src = p.read_text(encoding="utf-8")
    # If we wrote literal backslash-n pairs wrongly, fix common patterns.
    # Expected Python source uses "\\n" in string literals (one backslash + n in file).
    # Our _pretooluse_fns returns with \\n which becomes \n in the written file — correct
    # for a normal Python string. Verify by compile.
    compile(src, str(p), "exec")
    print("pretooluse: syntax ok")


if __name__ == "__main__":
    wire_institutional()
    wire_pretooluse()
    fix_pretooluse_newlines()
    wire_agents()
    wire_settings()
    print("done")
