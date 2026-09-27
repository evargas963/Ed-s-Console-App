"""Census #7 / RC-223 — JS date labels must name an explicit IANA timeZone.

Session date grouping uses America/New_York (time_et). Operator display uses
America/Chicago. Bare toLocaleDateString (browser ambient TZ) is banned on tracked
static HTML so a traveling operator cannot regroup sessions.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SESSION_TZ = "America/New_York"
DISPLAY_TZ = "America/Chicago"

# Call sites that format calendar dates for humans or for session keys.
_LOCALE_DATE_RE = re.compile(r"\.toLocaleDateString\s*\(")

# Tracked UI surfaces that may group/label by calendar date.
_SCAN_RELS = (
    "static/index.html",
)


def _call_span(text: str, open_paren_idx: int) -> str:
    """Return the argument text of a '(' … matching ')' call, or '' if unbalanced."""
    depth = 0
    for i in range(open_paren_idx, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_idx + 1 : i]
    return ""


def bare_locale_date_violations(text: str, *, rel: str = "snippet") -> list[str]:
    """Return violation messages for toLocaleDateString calls lacking timeZone:."""
    out: list[str] = []
    for m in _LOCALE_DATE_RE.finditer(text):
        # Skip comment-only lines (single-line // before the match on that line).
        line_start = text.rfind("\n", 0, m.start()) + 1
        prefix = text[line_start:m.start()]
        if "//" in prefix:
            continue
        args = _call_span(text, m.end() - 1)
        if "timeZone" not in args and "timeZone" not in args.replace(" ", ""):
            line_no = text.count("\n", 0, m.start()) + 1
            out.append(
                f"{rel}:{line_no}: bare toLocaleDateString (no explicit timeZone) — "
                f"session keys use {SESSION_TZ}; display uses {DISPLAY_TZ} (RC-223)"
            )
    return out


def scan_tracked_static(repo: Path | None = None) -> list[str]:
    """Scan tracked static HTML for bare locale-date clocks."""
    root = repo if repo is not None else REPO
    out: list[str] = []
    for rel in _SCAN_RELS:
        path = root / rel
        if not path.is_file():
            continue
        out.extend(
            bare_locale_date_violations(
                path.read_text(encoding="utf-8", errors="ignore"), rel=rel
            )
        )
    return out
