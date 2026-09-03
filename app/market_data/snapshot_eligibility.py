"""ONE computation: snapshot-collection eligibility.

SNAPSHOT_COLLECTION_ELIGIBLE =
    caller-supplied roster (enrollment or quote-panel candidates)
    ∩ not permanently uncollectable

Enrollment authority stays ``EdDB.logging_universe_authoritative_tickers``.
Quarantine *writes* stay ``server._note_terrain_failure`` / operator release.
This module is the ONE *read* of the durable quarantine ledger and the ONE
set-subtraction that turns that read into snapshot eligibility. It does not
own enrollment rows and does not invent a second quarantine verdict.

Soft backoff / success events are venue weather and never refuse a symbol.
``operator_release`` is the only ledger event that re-admits.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from instrument_identity import ticker_storage_key

_PERMANENT = "quarantine_permanent"
_RELEASE = "operator_release"


def resolve_ledger_path(explicit: str | Path | None = None) -> Path | None:
    """Named ledger location, or None when unset/empty. Existence is not required."""
    if explicit is None:
        return None
    s = str(explicit).strip()
    if not s:
        return None
    return Path(s)


def permanent_refusals_from_ledger(path: str | Path | None) -> frozenset[str]:
    """Replay the durable quarantine ledger. Last admission event wins per ticker.

    This is the durable READ of the same events ``server._quarantine_ledger_append``
    writes. It is not a second quarantine book.
    """
    p = Path(path) if path else None
    if p is None or not p.is_file():
        return frozenset()
    state: dict[str, bool] = {}
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return frozenset()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict):
            continue
        tk = ticker_storage_key(row.get("ticker"))
        if not tk:
            continue
        ev = row.get("event")
        if ev == _PERMANENT:
            state[tk] = True
        elif ev == _RELEASE:
            state[tk] = False
    return frozenset(k for k, refused in state.items() if refused)


def snapshot_collection_eligible(
    candidates: Iterable[str | None],
    *,
    ledger_path: str | Path | None,
) -> list[str]:
    """Eligible snapshot names: candidates minus durable permanent refusals.

    ``ledger_path`` is the governing quarantine log. Callers do not pass a
    competing refused set.
    """
    refused = permanent_refusals_from_ledger(ledger_path)
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        tk = ticker_storage_key(raw)
        if not tk or tk in seen or tk in refused:
            continue
        seen.add(tk)
        out.append(tk)
    return out
