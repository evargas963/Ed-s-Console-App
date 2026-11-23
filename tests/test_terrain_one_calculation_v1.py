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

import time_et
from calc import math_exposure_core, terrain_engine
from calc.terrain_engine import compute_terrain
from option_contract import read_chain
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

#: the one field read another way since the record was written (test_every_value_is_what_it_was)
ATM_IV = "atm_iv_pct_by_expiry"
#: the words of the regime and the headline as the record holds them, and as they are said since
#: every name is the industry's (operator 2026-11-22): the words alone, never which one is said
WORDS = (
    ("LONG_GAMMA_CHOP", "POSITIVE_GAMMA"),
    ("SHORT_GAMMA_TREND", "NEGATIVE_GAMMA"),
    ("Dealer gamma is", "Net GEX is"),
)

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


def _per_strike_keys(record: list, rename: dict[str, str], drop: set[str]) -> list:
    """Return a written-out terrain with its per-strike rows' keys renamed and some dropped."""
    return [
        [
            d,
            key,
            [[dd, rename.get(k, k), v] for dd, k, v in value if k not in drop]
            if key == "per_strike"
            else value,
        ]
        for d, key, value in record
    ]


def _as_said_now(record: list) -> list:
    """Return a written-out terrain with its regime's and headline's old words as said now."""
    out = []
    for d, key, value in record:
        if key in ("regime", "headline"):
            for old, new in WORDS:
                value = value.replace(old, new)
        out.append([d, key, value])
    return out


def _field(record: list, key: str) -> list:
    """Return one field of a written-out terrain: its value as written."""
    return next(value for _d, k, value in record if k == key)


def test_every_value_is_what_it_was():
    """Every field is what it was when the record was written, on every chain.

    Every key, order, absent value (None stays None: no value is invented, none turned into 0)
    and text exactly; every number within a double's last digits (REL_TOL, ABS_TOL). The record
    was written while the whole book's GEX rows were keyed `all`, beside the fixed `near` and
    `far` DTE buckets the one expiry choice deleted; the whole book's rows are now `gex`, and each
    expiry's own (`by_expiry`, new) are proved in tests/test_strikes_follow_the_expiry_v1.py. It
    was written, too, while each expiry's ATM IV was its strike nearest the price's; it is read
    where the two sides of the forward meet now, which takes the contracts' quotes, and these
    chains were stored without them (ATM_IV: its expiries and their order are what they were;
    its values are proved on real chains kept with their quotes in
    tests/test_terrain_engine_v1.py).
    """
    terrains = real_terrains()
    assert sorted(terrains) == sorted(BEFORE)
    for tk, snap in terrains.items():
        was = _as_said_now(_per_strike_keys(BEFORE[tk], {"all": "gex"}, {"near", "far"}))
        now = _per_strike_keys(canonical(snap), {}, {"by_expiry", "charm"})
        _same([e for e in was if e[1] != ATM_IV], [e for e in now if e[1] != ATM_IV], tk)
        assert [e[1] for e in _field(was, ATM_IV)] == [e[1] for e in _field(now, ATM_IV)], tk
        # the whole book's charm rows (new) are its charm map's nets, the map the record holds
        nets = {k: b["net_charm"] for k, b in snap.charm_by_strike.items()}
        assert snap.per_strike["charm"] == sorted(
            (k, v) for k, v in nets.items() if v is not None
        ), tk


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
    held = time_et.sessions()

    def run():
        nonlocal snap
        snap = compute_terrain("SPY", chain, _SPY["spot"], now=now, sessions=held)

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
    # the full book, the front expiry's, the same-day levels' own, and each listed expiry's rows
    # (the strike views at the expiry chosen) once
    dated = {c.expiry for c in chain if c.expiry is not None}
    assert counts["merge_exposure_books"] == 3 + len(dated), counts
    assert not DELETED & set(snap.to_dict()), "no unread value served"
