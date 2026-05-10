"""CSV-derived detection vocabulary — V3-A."""

from __future__ import annotations

import re
from dataclasses import dataclass


def _split_camel(s: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return s


def tokenize_for_vocabulary(blob: str, *, min_len: int = 3) -> set[str]:
    """
    Tokenize CSV-sourced text: `.`, camelCase boundaries, `_`, `-`, non-alnum;
    lowercase; drop tokens shorter than min_len (default 3).
    """
    if not blob:
        return set()
    t = _split_camel(blob)
    out: set[str] = set()
    for piece in re.split(r"[\s\.\_\-]+", t):
        p = piece.strip().lower()
        if len(p) >= min_len and re.fullmatch(r"[a-z0-9]+", p):
            out.add(p)
    return out


@dataclass(frozen=True)
class CsvVocabulary:
    """Immutable token set derived from dictionary CSV at scanner init (V3-A)."""

    tokens: frozenset[str]
    min_len: int

    @classmethod
    def from_dictionary_rows(
        cls,
        rows: list[dict[str, str]],
        *,
        min_len: int = 3,
    ) -> CsvVocabulary:
        acc: set[str] = set()
        for r in rows:
            for col in ("canonical_field", "description", "category", "likely_use", "csv_description"):
                raw = (r.get(col) or "").strip()
                if not raw:
                    continue
                acc |= tokenize_for_vocabulary(raw, min_len=min_len)
        return cls(frozenset(acc), min_len)

    def contains_word(self, word: str) -> bool:
        w = word.lower()
        return len(w) >= self.min_len and w in self.tokens

    def words_in_line(self, line: str) -> list[str]:
        """Whole-token hits: alphanumeric / underscore segments vs vocabulary."""
        found: list[str] = []
        seen: set[str] = set()
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", line):
            seg = m.group(0).lower()
            if self.contains_word(seg) and seg not in seen:
                seen.add(seg)
                found.append(seg)
        return found

    def words_in_text(self, text: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for line in text.splitlines():
            for w in self.words_in_line(line):
                if w not in seen:
                    seen.add(w)
                    found.append(w)
        return found

    def id_intersects_vocab(self, idents: set[str]) -> set[str]:
        return {i for i in idents if self.contains_word(i.lower())}
