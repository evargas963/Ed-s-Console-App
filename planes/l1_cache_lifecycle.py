"""
L1 snapshot cache ↔ LRU invariants (pure helpers).

_l1_snapshot_cache and _l1_scope_lru must carry the same key set after maintenance.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


def l1_cache_invariants(snapshot: dict[tuple, Any], lru: OrderedDict[tuple, None]) -> dict[str, Any]:
    """
    Compare key sets. Tuple keys are rendered as 'TICKER|expiry' for JSON/diagnostics.
    """
    ck = set(snapshot.keys())
    lk = set(lru.keys())

    def _fmt(k: tuple) -> str:
        if len(k) >= 2:
            return f"{k[0]}|{k[1]}"
        return repr(k)

    only_c = ck - lk
    only_l = lk - ck
    return {
        "keys_match": len(only_c) == 0 and len(only_l) == 0,
        "cache_scope_count": len(ck),
        "lru_len": len(lru),
        "only_in_cache": sorted(_fmt(x) for x in only_c),
        "only_in_lru": sorted(_fmt(x) for x in only_l),
    }


def reconcile_lru_with_snapshot(snapshot: dict[tuple, Any], lru: OrderedDict[tuple, None]) -> int:
    """
    Drop LRU entries that have no snapshot row (dangling LRU refs).
    Returns number of keys removed from LRU.
    """
    n = 0
    for k in list(lru.keys()):
        if k not in snapshot:
            lru.pop(k, None)
            n += 1
    return n


def ensure_lru_covers_snapshot(snapshot: dict[tuple, Any], lru: OrderedDict[tuple, None]) -> int:
    """
    Ensure every snapshot key appears in LRU (MRU insertion). Used when cache keys exist without
    LRU tracking so cap eviction can use true LRU instead of arbitrary dict order.
    Returns number of keys added to LRU.
    """
    n = 0
    for k in snapshot.keys():
        if k not in lru:
            lru[k] = None
            n += 1
    return n
