"""PATH FACTS: the one owner of "is this path part of this repository's product", consumed by
process_lock_guard (production-checkout rails), and `normalize_repo_relative`, the one
spelling of a repo-relative path. A library, not a hook.
"""
from __future__ import annotations

import posixpath
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Production surfaces across the whole continuum, not just backend.
PRODUCTION_SUFFIXES = (".py", ".html", ".js", ".css", ".sql", ".ts", ".jsx", ".tsx")
#: NOT part of the PRODUCT surface.
NOT_PRODUCT_PREFIXES = (
    "tests/", "governance/", "docs/", "reports/", ".claude/", ".cursor/",
    "scratchpad/", "calibration/",
)


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


def is_production_path(p: str, repo: str | Path | None = None) -> bool:
    """True when `p` is inside `repo` (default: this repository) and part of its product surface.

    Inside-the-repository is answered by resolve-and-compare against the root, never by a
    relative-prefix `startswith`, which an absolute path can never match. A path outside the
    root is not this repository's product. Fails CLOSED: an unresolvable path is production.
    """
    root = REPO if repo is None else Path(repo)
    try:
        root = root.resolve()
    except (OSError, ValueError):
        root = REPO
    resolved, resolvable = _resolve_for_repo(p, root)
    if not resolvable:
        return True
    try:
        rel = resolved.relative_to(root).as_posix()
    except ValueError:
        return False
    return rel.endswith(PRODUCTION_SUFFIXES) and not rel.startswith(NOT_PRODUCT_PREFIXES)


def normalize_repo_relative(p: str) -> str:
    """THE spelling of a repo-relative path (FC-13 / RC-527).

    Forward slashes, dot-segments and duplicate separators collapsed, no leading `./`. A
    leading dot that is part of a NAME — `.github`, `.claude`, `.cursor` — is preserved. Call
    sites once hand-rolled this with `str.lstrip("./")`, which strips CHARACTERS rather than a
    prefix and ate the leading dot of every dot-prefixed path. Foreign and escaping paths are
    NOT judged here (`../x/y.py` stays the caller's problem; `is_production_path` decides ours).
    """
    s = str(p or "").strip().replace("\\", "/")
    if not s:
        return ""
    out = posixpath.normpath(s)
    return "" if out == "." else out
