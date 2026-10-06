"""PATH SPELLING — `normalize_repo_relative`, the ONE spelling of a repo-relative path (RC-527).
A library, not a guard: it is on no hook roster.
"""
from __future__ import annotations

import posixpath

def normalize_repo_relative(p: str) -> str:
    """THE spelling of a repo-relative path (FC-13 / RC-527).

    Forward slashes, dot-segments and duplicate separators collapsed, no leading `./`. A
    leading dot that is part of a NAME — `.github`, `.claude`, `.cursor` — is preserved. Call
    sites once hand-rolled this with `str.lstrip("./")`, which strips CHARACTERS rather than a
    prefix and ate the leading dot of every dot-prefixed path. Foreign and escaping paths are
    NOT judged here (`../x/y.py` stays the caller's problem).
    """
    s = str(p or "").strip().replace("\\", "/")
    if not s:
        return ""
    out = posixpath.normpath(s)
    return "" if out == "." else out
