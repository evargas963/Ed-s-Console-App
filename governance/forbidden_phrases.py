"""Parse and check forbidden phrase lists from CLAUDE.md and AGENTS.md (Phase 1b)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _dedupe_phrases(phrases: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for p in phrases:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def _quoted_phrases_from_lines(lines: list[str]) -> list[str]:
    phrases: list[str] = []
    for line in lines:
        phrases.extend(re.findall(r'"([^"]+)"', line))
    return phrases


def forbidden_phrases_from_claude(text: str | None = None) -> list[str]:
    raw = text if text is not None else (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    idx = raw.find("FORBIDDEN PHRASES")
    if idx < 0:
        raise ValueError("CLAUDE.md missing FORBIDDEN PHRASES section")
    block = raw[idx : idx + 2500]
    phrases = _quoted_phrases_from_lines(
        line for line in block.splitlines() if "•" in line
    )
    if "Any phrase whose effect narrows scope" in block:
        phrases.append("narrows scope to less than the full repo")
    return _dedupe_phrases(phrases)


def forbidden_phrases_from_agents(text: str | None = None) -> list[str]:
    raw = text if text is not None else (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    idx = raw.find("## Banned phrases")
    if idx < 0:
        raise ValueError("AGENTS.md missing ## Banned phrases section")
    tail = raw[idx:]
    end = tail.find("\n## ", len("## Banned phrases"))
    block = tail if end < 0 else tail[:end]
    phrases = _quoted_phrases_from_lines(
        line for line in block.splitlines() if line.lstrip().startswith("-")
    )
    if "Any phrase whose effect narrows scope" in block:
        phrases.append("narrows scope to less than the full repo")
    return _dedupe_phrases(phrases)


def forbidden_phrases_all() -> list[str]:
    return _dedupe_phrases(forbidden_phrases_from_claude() + forbidden_phrases_from_agents())


def find_forbidden_phrases(text: str, phrases: list[str] | None = None) -> list[str]:
    pool = phrases if phrases is not None else forbidden_phrases_all()
    lower = text.lower()
    return [p for p in pool if p.lower() in lower]
