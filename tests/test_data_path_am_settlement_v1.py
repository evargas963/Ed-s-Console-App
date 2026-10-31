"""An AM-settled contract past the year Schwab's /markets answers is priced to the open of its own
date. $SPX's 2027-12-17 expiry, captured 2026-10-07 10:37 ET, 288 contracts with open interest."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import time_et
from math_levels import contract_inputs
from terrain_engine import compute_terrain

_SPX = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spx_chain_2026_10_07_2027_12_17.json").read_text(
        encoding="utf-8"
    )
)


def test_every_contract_is_priced_to_the_open_of_its_date_through_the_terrain():
    at = datetime.fromtimestamp(_SPX["ts_utc"], time_et.ET)
    priced, _unpriced = contract_inputs(_SPX["chain"], at)
    settles = datetime(2027, 12, 17, 9, 30, tzinfo=time_et.ET)
    assert len(priced) == 288
    assert {row[3] for row in priced} == {
        (settles.timestamp() - at.timestamp()) / time_et.YEAR_SECONDS
    }
    snap = compute_terrain("$SPX", _SPX["chain"], _SPX["spot"], now=at)
    assert snap.to_dict()["flip_diag"]["unpriced"] == {}
    assert snap.call_charm_wall is not None
