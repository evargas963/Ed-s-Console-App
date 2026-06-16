"""Parse and check forbidden phrase lists from CLAUDE.md and AGENTS.md (Phase 1b)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Industry-standard taxonomy labels — NOT excuse / partial-completion language.
CANONICAL_BY_DESIGN_LABEL_RE = re.compile(
    r"\b(?:"
    r"security\s+by\s+design|"
    r"privacy\s+by\s+design|"
    r"secure\s+by\s+design|"
    r"secure\s+by\s+default|"
    r"security-by-design|"
    r"privacy-by-design|"
    r"design\s+review|"
    r"system\s+design|"
    r"architecture\s+design"
    r")\b",
    re.IGNORECASE,
)

# Excuse / partial-completion uses of the by-design family (prose, not control titles).
BY_DESIGN_EXCUSE_RE = re.compile(
    r"\b(?:"
    r"(?:is|are|was|were|be|being|been|that's|that\s+is|this\s+is|it\s+is|it's)\s+by\s+design\b|"
    r"\bby\s+design\s+(?:for|to|because|since|when)\b|"
    r"\b(?:left|kept|skipped|remains?|stays?)\s+(?:incomplete|open|unfixed|as\s+is)?\s*by\s+design\b|"
    r"\bworking\s+by\s+design\b|"
    r"\bintentionally\s+by\s+design\b|"
    r"\b(?:accepted|allowed|expected)\s+(?:as\s+)?by\s+design\b"
    r")",
    re.IGNORECASE,
)

WORKS_AS_DESIGNED_RE = re.compile(r"\bworks\s+as\s+(?:designed|intended)\b", re.IGNORECASE)
POLICY_BY_DESIGN_RE = re.compile(r"\bpolicy\s+by\s+design\b", re.IGNORECASE)

_BY_DESIGN_FAMILY = frozenset({"by design", "works as designed", "policy by design"})


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


def _scrub_canonical_by_design_labels(text: str) -> str:
    return CANONICAL_BY_DESIGN_LABEL_RE.sub("", text.lower())


def find_by_design_excuses(text: str) -> list[str]:
    """Return by-design family excuse phrases found in *text* (canonical labels excluded)."""
    hits: list[str] = []
    if WORKS_AS_DESIGNED_RE.search(text):
        hits.append("works as designed")
    if POLICY_BY_DESIGN_RE.search(text):
        hits.append("policy by design")
    if BY_DESIGN_EXCUSE_RE.search(text):
        hits.append("by design")
    elif "by design" in _scrub_canonical_by_design_labels(text):
        hits.append("by design")
    return hits


def is_canonical_by_design_label(text: str) -> bool:
    """True when text contains a canonical by-design label and no excuse usage."""
    return bool(CANONICAL_BY_DESIGN_LABEL_RE.search(text)) and not find_by_design_excuses(text)


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
    hits: list[str] = []
    for p in pool:
        if p.lower() in _BY_DESIGN_FAMILY:
            continue
        if p.lower() in lower:
            hits.append(p)
    hits.extend(find_by_design_excuses(text))
    return _dedupe_phrases(hits)
