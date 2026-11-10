"""compute_terrain computes each value once, and nothing no one reads, with the same values.

Real data: SPY's whole chain of 2026-11-09 (12,904 contracts, production's newest complete
capture, valued at its capture time) and the real CRWD, TSLA and MRVL chains of 2026-10-07
(tests/real_chains.py), each valued at its own capture.

Calls are counted with Python's own monitoring (sys.monitoring), the code itself untouched.
"""

from __future__ import annotations

import gzip
import json
import math
from datetime import datetime
from pathlib import Path

import math_exposure_core
import terrain_engine
import time_et
from option_contract import read_chain
from terrain_engine import compute_terrain
from tests.call_count import calls
from tests.terrain_digest import canonical, real_terrains
from time_et import ET

_FX = Path(__file__).parent / "fixtures"
_SPY = json.loads((_FX / "real_spy_full_chain_2026_11_09.json").read_text(encoding="utf-8"))

#: the fields deleted with their producers, read by no code and shown on no screen
#: (zero_dte_gamma_share_pct, rr_25d, vanna_agg, call_wall_range, put_wall_range)
DELETED = frozenset(
    {"rr_25d", "zero_dte_gamma_share_pct", "vanna_agg", "call_wall_range", "put_wall_range"}
)

#: every field of each real chain's terrain, books, profile and per-strike rows included, as
#: compute_terrain produced it on Windows when the record was written, written out by
#: tests/terrain_digest.canonical
_RECORD = gzip.decompress((_FX / "real_terrains_2026_11_09.json.gz").read_bytes())
BEFORE = json.loads(_RECORD)["terrains"]

#: a number may differ from what it was only in the last digits of a double: Python's math and
#: numpy's exp and log, on one platform and another, round their last bit their own way. On
#: Windows the largest difference measured, every field of every chain, is 0
REL_TOL, ABS_TOL = 1e-9, 1e-6


def _same(was, now, path: str) -> None:
    """Assert `now` is `was`: every key, order, None and text the same, every number within tol."""
    if isinstance(was, list) and len(was) == 2 and was[0] == "f" and isinstance(was[1], str):
        assert isinstance(now, list) and now[0] == "f", (path, was, now)
        x, y = float(was[1]), float(now[1])
        assert (math.isnan(x) and math.isnan(y)) or math.isclose(
            x, y, rel_tol=REL_TOL, abs_tol=ABS_TOL
        ), (path, x, y)
        return
    if isinstance(was, list) and isinstance(now, list):
        assert len(was) == len(now), (path, len(was), len(now))
        for i, (a, b) in enumerate(zip(was, now, strict=True)):
            _same(a, b, f"{path}/{i}")
        return
    assert was == now, (path, was, now)


def test_every_value_is_what_it_was():
    """Every field is what it was when the record was written, on every chain.

    Every key, order, absent value (None stays None: no value is invented, none turned into 0)
    and text exactly; every number within a double's last digits (REL_TOL, ABS_TOL).
    """
    terrains = real_terrains()
    assert sorted(terrains) == sorted(BEFORE)
    for tk, snap in terrains.items():
        _same(BEFORE[tk], canonical(snap), tk)


def test_each_value_is_computed_once_and_nothing_unread_is_computed():
    """SPY's whole chain: one time to expiry per expiry, one ATM IV map, no unread value.

    Each contract's time to expiry was computed again for every contract (19,623 times for 35
    expiries), the expiries' ATM implied vols twice, and a same-day book merged for a share no
    code read. Now the time to expiry is computed once per expiry and settlement in each place
    that prices (the books, the gamma profile and the charm map), the ATM map once, and the five
    unread values (DELETED) are gone from the terrain.
    """
    chain = read_chain(_SPY["chain"])
    expiries = {(c.expiration, c.settlement) for c in chain}
    now = datetime.fromtimestamp(_SPY["capture_ts_utc"], ET)
    snap = None

    def run():
        nonlocal snap
        snap = compute_terrain("SPY", chain, _SPY["spot"], now=now)

    counts = calls(
        {
            "time_to_expiry_years": time_et.time_to_expiry_years.__code__,
            "atm_sigma_by_expiry": terrain_engine.atm_sigma_by_expiry.__code__,
            "merge_exposure_books": math_exposure_core.merge_exposure_books.__code__,
        },
        run,
    )
    assert counts["time_to_expiry_years"] <= 4 * len(expiries), counts
    assert counts["atm_sigma_by_expiry"] == 1, counts
    # the full book, the front expiry's, the <=7 and >7 days' rows and the same-day levels' own
    assert counts["merge_exposure_books"] == 5, counts
    assert not DELETED & set(snap.to_dict()), "no unread value served"
