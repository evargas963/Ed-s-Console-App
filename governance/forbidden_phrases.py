"""Parse and check CLAUDE.md FORBIDDEN PHRASES (Phase 1b)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def forbidden_phrases_from_claude(text: str | None = None) -> list[str]:
    raw = text if text is not None else (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    idx = raw.find("FORBIDDEN PHRASES")
    if idx < 0:
        raise ValueError("CLAUDE.md missing FORBIDDEN PHRASES section")
    block = raw[idx : idx + 2500]
    phrases: list[str] = []
    for line in block.splitlines():
        if "•" not in line:
            continue
        phrases.extend(re.findall(r'"([^"]+)"', line))
    # Catch-all line without quotes
    if "Any phrase whose effect narrows scope" in block:
        phrases.append("narrows scope to less than the full repo")
    deduped: list[str] = []
    seen: set[str] = set()
    for p in phrases:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def find_forbidden_phrases(text: str, phrases: list[str] | None = None) -> list[str]:
    pool = phrases if phrases is not None else forbidden_phrases_from_claude()
    lower = text.lower()
    return [p for p in pool if p.lower() in lower]
