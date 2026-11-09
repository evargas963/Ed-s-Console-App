"""compute_terrain computes each value once, and nothing no one reads, to the same last bit.

Real data: SPY's whole chain of 2026-11-09 (12,904 contracts, production's newest complete
capture, valued at its capture time) and the real CRWD, TSLA and MRVL chains of 2026-10-07
(tests/real_chains.py), each valued at its own capture.

Calls are counted with Python's own monitoring (sys.monitoring), the code itself untouched.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import math_exposure_core
import terrain_engine
import time_et
from option_contract import read_chain
from terrain_engine import compute_terrain
from tests.terrain_digest import digest, real_terrains
from time_et import ET

_SPY = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_full_chain_2026_11_09.json").read_text(
        encoding="utf-8"
    )
)

#: the fields deleted with their producers, read by no code and shown on no screen
#: (zero_dte_gamma_share_pct, rr_25d, vanna_agg, call_wall_range, put_wall_range), and the schema
#: version that names the change
CHANGED = frozenset(
    {
        "rr_25d",
        "zero_dte_gamma_share_pct",
        "vanna_agg",
        "call_wall_range",
        "put_wall_range",
        "schema_version",
    }
)

#: every other field of each real chain's terrain, books, profile and per-strike rows included,
#: as compute_terrain produced it before (#892's head, 361871f5), digested by
#: tests/terrain_digest.digest
BEFORE = {
    "CRWD": "4d7657a2461f636e70dcaa354786beb78d2430c4bbecaaceed38415248788d94",
    "TSLA": "89b2cb3ee260d234eb69be1ff390512675046f6b24d11c7902aa8beb565f2153",
    "MRVL": "ba8ced113c65f8b0d86891f960a5928627bccf7c5799210fff68d625d4a0e983",
    "SPY": "c73321bc778059894cceaf6030c5f71a2ef4ac18e220a7b5fcaec05edcf1d009",
}


def test_every_value_is_the_same_to_the_last_bit():
    """Every field still computed is what it was, every number to its last bit, on each chain."""
    assert {tk: digest(s, CHANGED) for tk, s in real_terrains().items()} == BEFORE


def _calls(codes, run) -> dict[str, int]:
    """Run `run`, counting the calls of each function in `codes` (name -> its code object)."""
    mon = sys.monitoring
    tool = next(i for i in range(6) if mon.get_tool(i) is None)
    by_code = {code: name for name, code in codes.items()}
    counts = dict.fromkeys(codes, 0)

    def start(code, _offset):
        counts[by_code[code]] += 1

    mon.use_tool_id(tool, "call count")
    mon.register_callback(tool, mon.events.PY_START, start)
    try:
        for code in codes.values():
            mon.set_local_events(tool, code, mon.events.PY_START)
        run()
    finally:
        for code in codes.values():
            mon.set_local_events(tool, code, 0)
        mon.free_tool_id(tool)
    return counts


def test_each_value_is_computed_once_and_nothing_unread_is_computed():
    """SPY's whole chain: one time to expiry per expiry, one ATM IV map, no unread value.

    Each contract's time to expiry was computed again for every contract (19,623 times for 35
    expiries), the expiries' ATM implied vols twice, and a same-day book merged for a share no
    code read. Now the time to expiry is computed once per expiry and settlement in each place
    that prices (the books, the gamma profile and the charm map), the ATM map once, and the five
    unread values (CHANGED) are gone from the terrain.
    """
    chain = read_chain(_SPY["chain"])
    expiries = {(c.expiration, c.settlement) for c in chain}
    now = datetime.fromtimestamp(_SPY["capture_ts_utc"], ET)
    snap = None

    def run():
        nonlocal snap
        snap = compute_terrain("SPY", chain, _SPY["spot"], now=now)

    counts = _calls(
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
    assert not CHANGED - {"schema_version"} & set(snap.to_dict()), "no unread value served"
