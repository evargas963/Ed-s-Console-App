"""Everything compute_terrain produces on the real chains, written out exactly.

Every field of the TerrainSnapshot, the heavy maps (books, profile, per-strike rows, charm maps)
included: dicts as their items in order, a float by its exact repr, a tuple key as a list, so two
terrains compare alike only when every value, its key and its order compare alike.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

from option_contract import read_chain
from terrain_engine import TerrainSnapshot, compute_terrain
from tests.real_chains import CRWD, MRVL, TSLA
from time_et import ET

_SPY = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_full_chain_2026_11_09.json").read_text(
        encoding="utf-8"
    )
)


def canonical(v):
    """Return `v` written out exactly: dicts as [["d", key, value], ...], floats as ["f", repr]."""
    if is_dataclass(v):
        return canonical(asdict(v))
    if isinstance(v, dict):
        return [["d", canonical(k), canonical(x)] for k, x in v.items()]
    if isinstance(v, (list, tuple)):
        return [canonical(x) for x in v]
    if isinstance(v, float):
        return ["f", repr(v)]
    return v


def real_terrains() -> dict[str, TerrainSnapshot]:
    """compute_terrain of every watchlist-sized real chain held: CRWD, TSLA, MRVL and SPY's."""
    out = {
        c.ticker: compute_terrain(c.ticker, read_chain(c.chain), c.spot, now=c.now)
        for c in (CRWD, TSLA, MRVL)
    }
    out["SPY"] = compute_terrain(
        "SPY",
        read_chain(_SPY["chain"]),
        _SPY["spot"],
        now=datetime.fromtimestamp(_SPY["capture_ts_utc"], ET),
    )
    return out
