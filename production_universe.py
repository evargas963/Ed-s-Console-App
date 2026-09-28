"""
Authoritative production ticker validation (Issue 22 universe hygiene).

Goal: one normalized string form for enrollment + runtime loops + validators.

Rules (code-grounded, conservative):
- Uppercase/strip.
- Reject empty.
- No name list: whether a well-formed symbol is real is Schwab's answer (a symbol Schwab refuses
  is held off the levels loop, server._terrain_quarantine_blocks).
- Allow broker-index storage keys like '$SPX' / '$VIX' (see instrument_identity.BROKER_INDEX_BARE_ROOTS).
- Allow 1-5 upper-case characters (Schwab equity tickers are short; longer symbols exist but are
  not supported by this validator — enroll via a supported symbol).

This module is intentionally strict: invalid symbols must not enter logging_universe.
"""

from __future__ import annotations

from typing import Iterable

from instrument_identity import ticker_storage_key


def normalize_production_ticker(raw: str | None) -> str:
    """Normalize user input to canonical storage key where applicable."""
    return ticker_storage_key(raw)


def is_symbol_form(seg: str) -> bool:
    """A symbol's form, the same for every instrument: `$` and letters (an index as Schwab names
    it), or 1-5 upper-case characters."""
    if not seg or len(seg) > 10:
        return False
    if seg.startswith("$") and seg[1:].isalpha():
        return True
    return seg.isupper() and 1 <= len(seg) <= 5


def is_valid_production_ticker(raw: str | None) -> bool:
    return is_symbol_form(normalize_production_ticker(raw))


def filter_valid_tickers(tickers: Iterable[str | None]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in tickers:
        t = normalize_production_ticker(x or "")
        if not is_valid_production_ticker(t):
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out
