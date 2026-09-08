"""PATH FACTS — the ONE owner of "is this path ours / production / a compliance surface".

HISTORY: born as the RC-66 lane (a root-cause row demanded before editing any production
file), retired under RC-470; then the RC-160/RC-163/RC-186 content gates and the RC-498
mutation-side mission latch lived here. BEDROCK 2026-09-06 (dual-signoff Claude + ChatGPT,
operator order to REPAIR): all of those are removed and this module is OFF the hook rosters.
The content gates matched English in prompts and residual prose, which AGENTS.md rules out
as enforcement; the latch made every feature edit a defect mission and could not see the
property it stood for (a defect found on the way gets recorded). Work identity is the branch
and PR; defects get rows by doctrine; the Stop seam holds an unfinished row and CLOSE
requires cited evidence.

What remains is `classify_path` — consumed by process_lock_guard (production-checkout rails)
— `normalize_repo_relative`, the ONE spelling of a repo-relative path (RC-527), and `decide`,
kept importable for the path-facts tests; it returns 0.
"""
from __future__ import annotations

import json
import posixpath
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


def normalize_repo_relative(p: str) -> str:
    """THE spelling of a repo-relative path (FC-13 / RC-527, ported from #221's row 508).

    Forward slashes, dot-segments and duplicate separators collapsed, no leading `./`. A
    leading dot that is part of a NAME — `.github`, `.claude`, `.cursor` — is preserved,
    because that is the whole point.

    WHY THIS EXISTS. Call sites hand-rolled this, and the idiom they copied was
    `str.lstrip("./")`, which strips CHARACTERS rather than a prefix: it ate the leading dot of
    every dot-prefixed path, so `.github/workflows/hardening.yml` was keyed as
    `github/workflows/hardening.yml` in the credential firewall's skip set and a closure that
    shipped a workflow fix was refused as not shipping it (#221's row 506/row 507). The
    repository already declares a path AUTHORITY here — `classify_path` — but it answers the
    GOVERNANCE question (ours? product? compliance lane?) and offered no primitive for the
    string, so every caller needing the string built one. This is that primitive; it lives
    beside `classify_path` because it is the same semantic domain, and callers import it
    lazily so a leaf lock consumes it without a cycle.

    Foreign and escaping paths are NOT judged here: `../x/y.py` normalises to `../x/y.py` and
    stays the caller's problem — deciding whether a path is ours is `classify_path`'s job.
    """
    s = str(p or "").strip().replace("\\", "/")
    if not s:
        return ""
    out = posixpath.normpath(s)
    return "" if out == "." else out


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

    # BEDROCK 2026-09-06 (dual-signoff Claude + ChatGPT, operator order to REPAIR): this seam
    # blocks nothing any more, by design.
    #   * The RC-160 / RC-163 / RC-186 content gates matched English in prompts, residual
    #     prose and a JSON approval file — free-text matching, which AGENTS.md rules out as
    #     enforcement. The laws stand in AGENTS.md; the structural half of RC-160 (SPY-only
    #     defaults and SPY-gated Chart features in CODE) stays in the gate at commit/merge.
    #   * The RC-498 mutation-side latch ("a row before a production mutation") was a proxy
    #     for "a defect found on the way gets recorded", a property this seam cannot see. It
    #     made every feature edit a defect mission, expired at midnight (RC-521) and
    #     deadlocked on legitimate child rows. Work identity is the branch and PR; defects
    #     get rows by doctrine; the Stop seam holds an unfinished row (stop_guard) and CLOSE
    #     requires cited evidence (check_root_cause_log).
    # What remains here is `classify_path`, the ONE owner of "is this path ours / production /
    # compliance", consumed by process_lock_guard. `decide` stays
    # importable for the path-facts tests and returns 0 for every governed edit.
    _ = facts.rel
    return 0


if __name__ == "__main__":
    sys.exit(main())
