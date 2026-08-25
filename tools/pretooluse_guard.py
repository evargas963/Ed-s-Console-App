"""FRONT-END content gates — blocks the EDIT, not just the commit.

HISTORY: born as the RC-66 lane (a root-cause row demanded before editing any production
file, after a 2026-07-26 unanalyzed CSS patch); that lane was retired with its commit-time
twin under RC-470 (governance/retired_checks.md). What survives here are the RC-160/RC-163/
RC-186 content gates listed in the contract below.

This runs as a PreToolUse hook on Edit/Write/NotebookEdit. Exit 2 BLOCKS the tool call.

Scope: the whole continuum — backend .py, frontend .html/.js/.css, SQL, config. Not just Python,
because the violation that triggered this was in the frontend.

Contract:
  * RC-470/RC-471: the RC-66 lane (a root-cause row required before editing a PRODUCTION
    file) is RETIRED — governance/retired_checks.md; feature-branch edits are autonomous
    (operator ruling 2026-08-24). The content gates below are what this guard still blocks.
  * RC-160 UNIVERSAL ticker scope: Write/Edit of prompt / agent-instruction paths is BLOCKED when
    the new content frames SPY-only / sentinel-complete work without UNIVERSAL or OUT-OF-SCOPE
    language — even under otherwise-allowed prefixes (reports/, .claude/).
  * RC-163 Chart-intent + next-RTH: Write/Edit of residual/handoff/RC/prompt paths is BLOCKED when
    Collect/Chart is framed Done while Chart stays soft OUT-OF-SCOPE/OBSERVED, or when forward
    residuals say weekday-named live proof while next RTH is not that weekday — even under
    allowed prefixes.
  * RC-186 mockup-before-code: Write/Edit of a surface listed in
    governance/ui_mockup_approvals.json is BLOCKED until the operator has approved a rendered
    mockup variant there (status='approved') — escape `# ui-mockup-ok: <reason>` for
    non-redesign bug fixes.
  * Architecture A (RC-450): ED_PRETOOLUSE_GUARD / ED_UI_MOCKUP_LOCK cannot disable this control.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent

#: Editing these is how you COMPLY (open the row, write the test, record evidence) — never blocked
#: by path class. RC-160/RC-163 still gate residual/prompt content.
ALWAYS_ALLOWED_PREFIXES = (
    "governance/", "docs/", "reports/", "tests/", ".claude/", "calibration/",
)
#: Production surfaces across the whole continuum, not just backend.
PRODUCTION_SUFFIXES = (".py", ".html", ".js", ".css", ".sql", ".ts", ".jsx", ".tsx")
#: NOT part of the PRODUCT surface. Deliberately NOT the same list as
#: ALWAYS_ALLOWED_PREFIXES: that one answers "is editing this HOW you comply with RC-66",
#: this one answers "is this file part of the product". They diverge on `scratchpad/`
#: (3298 in-repo .py files: not product, but writing scratch is not RC-66 compliance either)
#: and on `.cursor/` (compliance surface, and holds no production-suffix file today).
#: Keeping them separate is what lets one resolve-and-compare serve both questions without
#: silently loosening RC-66 or silently widening the product surface.
NOT_PRODUCT_PREFIXES = (
    "tests/", "governance/", "docs/", "reports/", ".claude/", ".cursor/",
    "scratchpad/", "calibration/",
)


class PathFacts(NamedTuple):
    """The answers a caller may ask about a path. One computation, three questions."""

    governed: bool      # Q1 — does THIS repository's law apply to this path
    rel: str            # repo-relative posix when governed and resolvable, else normalised input
    production: bool    # Q2 — governed AND part of the product surface
    rc66_exempt: bool   # governed AND editing it is how you comply with RC-66


def _resolve_for_repo(p: str, root: Path) -> tuple[Path | None, bool]:
    """Resolve `p` for governance. Relative input is joined to `root`, never to the CWD.

    Returns (resolved, resolvable). A path that cannot be resolved returns (None, False)
    and every caller must treat that as OURS — unmeasurable is never ungoverned.
    """
    try:
        raw = Path(p)
        if not raw.is_absolute():
            raw = root / raw
        return raw.resolve(), True
    except (OSError, ValueError):
        return None, False


def classify_path(p: str, repo: str | Path | None = None) -> PathFacts:
    """THE path authority (FC-13). Every caller consumes this; nobody re-derives it.

    Q1 governance is answered by resolve-and-compare against the governing root — the
    semantics proven by RC-259. Q2 is only meaningful once Q1 is true, which is the
    distinction the previous independent classifiers lost: a relative-prefix `startswith`
    test can never match an absolute path, so an absolute scratchpad file was classified as
    production even though `scratchpad/` sat in the exemption list.

    `repo` names the governing root and defaults to this repository. It exists because the
    turn ledger is per-entry repo-scoped (RC-258: an unscoped row is inert rather than
    universally valid), so "is this ours" has to be asked of a specific tree. Parameterising
    the root keeps ONE computation of the geometry while preserving that scoping — the
    formula lives here once; only the tree it is asked about varies.

    Fails CLOSED: an unresolvable path is governed, is production, and is not exempt.
    """
    root = REPO if repo is None else Path(repo)
    try:
        root = root.resolve()
    except (OSError, ValueError):
        root = REPO
    resolved, resolvable = _resolve_for_repo(p, root)
    if not resolvable:
        return PathFacts(governed=True, rel=Path(p).as_posix(),
                         production=True, rc66_exempt=False)
    try:
        rel = resolved.relative_to(root).as_posix()
    except ValueError:
        # Genuinely outside the governing tree — governed by that tree's own rules, not ours.
        return PathFacts(governed=False, rel=resolved.as_posix(),
                         production=False, rc66_exempt=False)
    return PathFacts(
        governed=True,
        rel=rel,
        production=rel.endswith(PRODUCTION_SUFFIXES) and not rel.startswith(NOT_PRODUCT_PREFIXES),
        rc66_exempt=rel.startswith(ALWAYS_ALLOWED_PREFIXES),
    )


def is_foreign_path(p: str) -> bool:
    """True when the target lives OUTSIDE this repository (RC-259).

    This guard enforces THIS repository's root-cause law. A path in another
    checkout is governed by that repository's own rules, and blocking it is
    both an over-reach and — measured 2026-08-05/06 — actively harmful:
    `_rel()` falls back to the absolute path when `relative_to` raises, and an
    absolute path matches NO entry in ALWAYS_ALLOWED_PREFIXES. So the guard
    applied its strictest rule to a foreign tree while silently disabling the
    `tests/`, `governance/`, `docs/`, `reports/`, `.claude/` and `calibration/`
    escape hatches that make the rule survivable. An edit to
    <other-repo>/tests/test_x.py was refused as a PRODUCTION file.

    Fails CLOSED for this repository: anything that resolves under REPO, or
    that cannot be resolved at all, is treated as ours and stays governed.

    Thin accessor over `classify_path` so the resolve-and-compare exists once.
    """
    return not classify_path(p).governed


def _rel(p: str) -> str:
    return classify_path(p).rel


def _git(args: list[str]) -> str | None:
    try:
        # RC-187: pin the decode to what git emits. text=True alone uses the locale codepage
        # (cp1252 on this host), which throws in the capture reader THREAD on UTF-8 governance
        # content — outside this except — and silently degraded the RC-66 check to never-block.
        r = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


# RC-471: _has_new_rc_row removed — its only caller was the RC-66 edit-time lane,
# retired under RC-470 (governance/retired_checks.md).


def _tool_new_text(tool_input: dict) -> str:
    """Extract the text the tool is about to write (Write content / Edit new_string / MultiEdit)."""
    chunks: list[str] = []
    content = tool_input.get("content")
    if isinstance(content, str) and content:
        chunks.append(content)
    new_string = tool_input.get("new_string")
    if isinstance(new_string, str) and new_string:
        chunks.append(new_string)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for ed in edits:
            if isinstance(ed, dict):
                ns = ed.get("new_string")
                if isinstance(ns, str) and ns:
                    chunks.append(ns)
    return "\n".join(chunks)


def _import_lock(module: str, names: tuple[str, ...]):
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
        "BLOCKED by the UNIVERSAL ticker-scope law (RC-160).\n\n"
        f"  File: {rel}\n"
        f"  {reason}\n\n"
        "Default scope is the enrolled universe, not SPY. Narrow work must say OUT-OF-SCOPE:\n"
        "(or UNIVERSAL / enrolled-universe / # universal-scope-ok:) with the reason.\n"
        "Do not prompt Claude or Cursor with SPY-only framing for work treated as complete.\n"
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
        "BLOCKED by the Chart-intent / next-RTH residual law (RC-163).\n\n"
        f"  File: {rel}\n"
        + "".join(f"  {r}\n" for r in reasons)
        + "\n"
        "Escapes: # chart-intent-ok: + operator waiver; STATUS PARTIAL naming an open\n"
        "P0/CHART_CONSUMER residual; proven Chart consumer; or # next-rth-ok: + computed\n"
        "next RTH ISO date (America/New_York / is_trading_day_et). Prefer NEXT_RTH_PROOF.\n"
    )
    return 2


def _block_unapproved_ui_redesign(rel: str, tool_input: dict) -> int | None:
    """RC-186: block edits to mockup-gated UI surfaces before an operator-approved mockup.
    RC-189: judge MultiEdit PER EDIT (one escape must not unlock its siblings) and gate the
    approval registry itself (self-approve was Cursor's top break)."""
    (mockup_approval_violation, registry_mutation_violation, tool_input_texts) = _import_lock(
        "ui_mockup_lock",
        ("mockup_approval_violation", "registry_mutation_violation", "tool_input_texts"),
    )
    texts = tool_input_texts(tool_input) or [""]
    for text in texts:
        reason = registry_mutation_violation(rel, text)
        if reason is None:
            reason = mockup_approval_violation(rel, text)
        if reason is None:
            continue
        sys.stderr.write(
            "BLOCKED by the mockup-before-code law (RC-186/RC-189).\n\n"
            f"  File: {rel}\n"
            f"  {reason}\n"
        )
        return 2
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0                         # unreadable hook input is never a block
    return decide(payload)


def decide(payload: dict) -> int:
    """Decide one hook payload. Split out of main() so it can be TESTED.

    Until RC-259 the whole decision lived inside a function that read stdin,
    so nothing could exercise it without a subprocess -- which is why an
    over-reach into another repository, and the allowlist being void for
    foreign paths, both survived unnoticed. A guard nobody can unit-test is a
    guard nobody verifies.
    """
    tool = payload.get("tool_name") or ""
    # Cursor continuum: Write/StrReplace/Delete (+ path); Claude: Edit/Write (+ file_path).
    if tool not in ("Edit", "Write", "StrReplace", "NotebookEdit", "MultiEdit", "Delete", "EditNotebook"):
        return 0
    tool_input = payload.get("tool_input") or {}
    fp = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("target_notebook")
        or ""
    )
    if not fp:
        return 0

    # RC-259: this guard enforces THIS repository's root-cause law. A path in
    # another checkout is governed by that repository's rules. Blocking it was
    # not merely over-reach: _rel() falls back to the absolute path, which
    # matches no ALWAYS_ALLOWED_PREFIXES entry, so the guard applied its
    # strictest rule to a foreign tree while disabling every compliance route.
    facts = classify_path(fp)
    if not facts.governed:
        return 0

    rel = facts.rel

    # RC-160 / RC-163 run BEFORE the RC-66 allowlist — residual drafts under reports/ still gate.
    blocked = _block_spy_only_prompt(rel, tool_input)
    if blocked is not None:
        return blocked
    blocked = _block_chart_intent_and_next_rth(rel, tool_input)
    if blocked is not None:
        return blocked
    blocked = _block_unapproved_ui_redesign(rel, tool_input)
    if blocked is not None:
        return blocked

    # RC-470: the RC-66 edit-time block (an RC row required before editing any
    # production file - the edit-time mirror of check_recursive_five_why_front_loaded)
    # is retired with that check - governance/retired_checks.md. Operator ruling
    # 2026-08-24: feature-branch edits are autonomous; defect rows are still required
    # for defects (root_cause_log at commit/CI) but ordinary work is not a defect.
    # The RC-160 / RC-163 / RC-186 content gates above are unchanged.
    return 0


if __name__ == "__main__":
    sys.exit(main())
