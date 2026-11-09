"""A digest of everything compute_terrain produces, to the last bit of every number.

Every field of the TerrainSnapshot, the heavy maps (books, profile, per-strike rows, charm maps)
included: dicts as their items in order, a float by its exact repr, a tuple key as a list, so two
snapshots digest alike only when every value, its key and its order are the same.
"""

from __future__ import annotations

import hashlib
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


def _canonical(v):
    if is_dataclass(v):
        return _canonical(asdict(v))
    if isinstance(v, dict):
        return [["d", _canonical(k), _canonical(x)] for k, x in v.items()]
    if isinstance(v, (list, tuple)):
        return [_canonical(x) for x in v]
    if isinstance(v, float):
        return ["f", repr(v)]
    return v


def digest(snap: TerrainSnapshot, without: frozenset[str] = frozenset()) -> str:
    """Return the sha256 of every field of `snap` but those named in `without`."""
    fields = {k: v for k, v in asdict(snap).items() if k not in without}
    text = json.dumps(_canonical(fields), separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
