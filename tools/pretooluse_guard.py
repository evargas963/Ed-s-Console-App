"""PATH FACTS — the ONE owner of "is this path ours / production / a compliance surface".

HISTORY: born as the RC-66 lane (a root-cause row demanded before editing any production
file), retired under RC-470; then the RC-160/RC-163/RC-186 content gates and the RC-498
mutation-side mission latch lived here. BEDROCK 2026-09-06 (dual-signoff Claude + ChatGPT,
operator order to REPAIR): all of those are removed and this module is OFF the hook rosters.
KEEP/MERGE/DELETE 2026-09-10: the inert hook shape (`main`/`decide`, which returned 0 for
every event, and an unreadable payload too) is deleted — a file called *_guard that judges
nothing is a superseded mechanism wearing a name. What remains is a LIBRARY, not a guard:
`classify_path`, consumed by process_lock_guard (production-checkout rails), and
`normalize_repo_relative`, the ONE spelling of a repo-relative path (RC-527).
"""
from __future__ import annotations

import posixpath
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent

#: Editing these is how you COMPLY (open the row, write the test, record evidence) — never blocked
#: by path class.
ALWAYS_ALLOWED_PREFIXES = (
    "governance/", "docs/", "reports/", "tests/", ".claude/", "calibration/",
)
#: Production surfaces across the whole continuum, not just backend.
PRODUCTION_SUFFIXES = (".py", ".html", ".js", ".css", ".sql", ".ts", ".jsx", ".tsx")
#: NOT part of the PRODUCT surface. Deliberately NOT the same list as
#: ALWAYS_ALLOWED_PREFIXES: that one answers "is editing this HOW you comply with RC-66",
#: this one answers "is this file part of the product". They diverge on `scratchpad/`
#: (not product, but writing scratch is not RC-66 compliance either) and on `.cursor/`.
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
    A path that cannot be resolved returns (None, False) and every caller must treat that as
    OURS — unmeasurable is never ungoverned."""
    try:
        raw = Path(p)
        if not raw.is_absolute():
            raw = root / raw
        return raw.resolve(), True
    except (OSError, ValueError):
        return None, False


def classify_path(p: str, repo: str | Path | None = None) -> PathFacts:
    """THE path authority (FC-13). Every caller consumes this; nobody re-derives it.

    Q1 governance is answered by resolve-and-compare against the governing root (RC-259). Q2
    is only meaningful once Q1 is true — a relative-prefix `startswith` test can never match
    an absolute path, which is how an absolute scratchpad file was once classified as
    production. `repo` names the governing root and defaults to this repository.

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
    """THE spelling of a repo-relative path (FC-13 / RC-527).

    Forward slashes, dot-segments and duplicate separators collapsed, no leading `./`. A
    leading dot that is part of a NAME — `.github`, `.claude`, `.cursor` — is preserved. Call
    sites once hand-rolled this with `str.lstrip("./")`, which strips CHARACTERS rather than a
    prefix and ate the leading dot of every dot-prefixed path. Foreign and escaping paths are
    NOT judged here (`../x/y.py` stays the caller's problem; `classify_path` decides ours).
    """
    s = str(p or "").strip().replace("\\", "/")
    if not s:
        return ""
    out = posixpath.normpath(s)
    return "" if out == "." else out
