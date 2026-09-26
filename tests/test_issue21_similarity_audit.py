"""
Issue 21 — similarity tier audit trace, constraint integrity, inspection scaffolding.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB
from math_probabilities import MIN_SAMPLES_STATISTICAL
from timeframe_config import CANONICAL_TIMEFRAME


_FAR_NAD = 50.0
_FAR_NBD = 50.0




def _insert_full_row(conn, *, ticker: str, ts: float, zone: str, vwap_side: str, nad: float, nbd: float):
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
          nearest_above_dist, nearest_below_dist,
          outcome_1c, outcome_5c, outcome_15c, outcome_60c,
          horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "test",
            450.0,
            zone,
            vwap_side,
            nad,
            nbd,
            "up", "up", "up", "up",
            3,
        ),
    )


# TEST_SYSTEM_REHAB_V2 final remediation (perf): each of the 5 tests below used to
# construct its own fresh `EdDB(tmp_path / "...")`, independently paying the full
# ~4s schema-init + migration bootstrap (measured: ~20s of pure redundant, byte-
# identical DDL/migration work across this one file). `_primed_eddb_template`
# builds that ONE schema-migrated, zero-row database exactly once per worker;
# `db` copies the plain file (cheap -- no schema/migration re-run needed on an
# already-current file) into each test's own isolated tmp_path so row-level
# mutations never leak between tests (measured: ~9s total after the change, a
# reopened copy still re-validates the schema in ~1.2-1.7s vs a ~2.7s-4s first
# build, since WAL/migration checks still run but touch zero rows).
@pytest.fixture(scope="module")
def _primed_eddb_template(tmp_path_factory):
    template_path = tmp_path_factory.mktemp("i21_eddb_template") / "template.db"
    template_db = EdDB(template_path, allow_noncanonical=True)
    with template_db._connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    return template_path


@pytest.fixture
def db(tmp_path, _primed_eddb_template):
    dest = tmp_path / "primed.db"
    shutil.copy(_primed_eddb_template, dest)
    return EdDB(dest, allow_noncanonical=True)










def test_issue21_withheld_horizons_when_sparse(db):
    ts0 = 1_794_000_000.0
    with db._connect() as conn:
        for i in range(20):
            _insert_full_row(
                conn,
                ticker="AUD5",
                ts=ts0 + i * 60,
                zone="ix21_sparse",
                vwap_side="above",
                nad=1.0,
                nbd=1.0,
            )
        conn.commit()
    _similar, tr = db.get_similar_setups(
        ticker="AUD5",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ix21_sparse",
        vwap_side="above",
        nearest_above_dist=_FAR_NAD,
        nearest_below_dist=_FAR_NBD,
        return_trace=True,
    )
    assert tr["stop_reason"] == "max_tier_broadest_pool_forced"
    assert tr["chosen_tier"] == 5
    wh = tr["withheld_horizons"]
    assert isinstance(wh, list) and len(wh) > 0
    assert any(x["labeled_count"] < MIN_SAMPLES_STATISTICAL for x in wh)
    weak = tr["tier_stop_weak_horizons"]
    assert weak[0]["labeled_count"] <= weak[-1]["labeled_count"]
