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

from db import EdDB, MIN_SAMPLES_STATISTICAL
from similarity_audit import (
    build_similar_inspection_bundle,
    inspection_row_projection,
    normalize_anchor_distances_for_issue19_sql,
    relaxed_constraints_vs_previous_tier,
    similarity_trace_machine_summary,
    validate_selected_rows_match_tier,
    widening_steps_are_sequential,
)
from timeframe_config import CANONICAL_TIMEFRAME


_FAR_NAD = 50.0
_FAR_NBD = 50.0


def test_normalize_anchor_distances_abs_signed_inputs():
    assert normalize_anchor_distances_for_issue19_sql(-1.0, -2.5) == (1.0, 2.5)
    assert normalize_anchor_distances_for_issue19_sql(None, -1.0) == (None, 1.0)
    assert normalize_anchor_distances_for_issue19_sql(0.5, 0.25) == (0.5, 0.25)


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


def test_issue21_trace_completeness_structured_constraints(db):
    ts0 = 1_790_000_000.0
    with db._connect() as conn:
        for i in range(35):
            _insert_full_row(
                conn,
                ticker="AUD1",
                ts=ts0 + i * 60,
                zone="ix21_trace",
                vwap_side="below",
                nad=1.0,
                nbd=1.0,
            )
        conn.commit()
    _similar, tr = db.get_similar_setups(
        ticker="AUD1",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ix21_trace",
        vwap_side="below",
        nearest_above_dist=_FAR_NAD,
        nearest_below_dist=_FAR_NBD,
        return_trace=True,
    )
    assert tr.get("trace_schema") == "similarity_trace_issue21_v1"
    assert "query_context" in tr
    assert tr["final_selected_tier"] == tr["chosen_tier"]
    assert tr["final_selected_row_count"] == len(_similar)
    assert tr["stop_reason"] == "tier_stop_satisfied"
    assert isinstance(tr["withheld_horizons"], list)
    assert tr["final_tier_stop_viable"] is True
    assert "widening_analysis" in tr
    for entry in tr["tiers"]:
        assert "constraint_definition" in entry
        assert "relaxed_vs_previous_tier" in entry
        assert "labeled_counts" in entry
        assert "tier_stop_viable" in entry
        assert entry["relaxed_vs_previous_tier"] == relaxed_constraints_vs_previous_tier(int(entry["tier"]))
    assert widening_steps_are_sequential(tr["tiers"])
    ms = similarity_trace_machine_summary(tr)
    assert ms.get("schema") == "similarity_trace_summary_v1"
    assert ms.get("final_selected_tier") == tr["chosen_tier"]


def test_issue21_constraint_integrity_selected_rows(db):
    ts0 = 1_791_000_000.0
    with db._connect() as conn:
        for i in range(40):
            _insert_full_row(
                conn,
                ticker="AUD2",
                ts=ts0 + i * 60,
                zone="ix21_ok",
                vwap_side="above",
                nad=2.0,
                nbd=2.0,
            )
        conn.commit()
    similar, tr = db.get_similar_setups(
        ticker="AUD2",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ix21_ok",
        vwap_side="above",
        nearest_above_dist=_FAR_NAD,
        nearest_below_dist=_FAR_NBD,
        return_trace=True,
    )
    tier = int(tr["chosen_tier"])
    ctx = tr["query_context"]
    audit = validate_selected_rows_match_tier(similar, tier, ctx)
    assert audit["violations_total"] == 0


def test_issue21_widening_relaxation_order_matches_issue19(db):
    """Tiers 1–4 attempted in order; each step relaxes only the documented constraint."""
    ts0 = 1_792_000_000.0
    with db._connect() as conn:
        for i in range(25):
            _insert_full_row(
                conn,
                ticker="AUD3",
                ts=ts0 + i * 60,
                zone="ix21_widen",
                vwap_side="above",
                nad=1.0,
                nbd=1.0,
            )
        for j in range(15):
            _insert_full_row(
                conn,
                ticker="AUD3",
                ts=ts0 + 80_000 + j * 60,
                zone="ix21_widen",
                vwap_side="below",
                nad=1.0,
                nbd=1.0,
            )
        conn.commit()
    similar, tr = db.get_similar_setups(
        ticker="AUD3",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ix21_widen",
        vwap_side="above",
        nearest_above_dist=_FAR_NAD,
        nearest_below_dist=_FAR_NBD,
        return_trace=True,
    )
    assert tr["chosen_tier"] == 4
    assert widening_steps_are_sequential(tr["tiers"])
    expected = {
        1: relaxed_constraints_vs_previous_tier(1),
        2: relaxed_constraints_vs_previous_tier(2),
        3: relaxed_constraints_vs_previous_tier(3),
        4: relaxed_constraints_vs_previous_tier(4),
        5: relaxed_constraints_vs_previous_tier(5),
    }
    for e in tr["tiers"]:
        assert e["relaxed_vs_previous_tier"] == expected[int(e["tier"])]
    assert tr["widening_analysis"]["widening_occurred"] is True
    assert len(similar) == 40


def test_issue21_inspection_bundle_includes_required_fields(db):
    ts0 = 1_793_000_000.0
    with db._connect() as conn:
        for i in range(32):
            _insert_full_row(
                conn,
                ticker="AUD4",
                ts=ts0 + i * 60,
                zone="ix21_insp",
                vwap_side="below",
                nad=1.5,
                nbd=1.5,
            )
        conn.commit()
    similar, tr = db.get_similar_setups(
        ticker="AUD4",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ix21_insp",
        vwap_side="below",
        nearest_above_dist=_FAR_NAD,
        nearest_below_dist=_FAR_NBD,
        return_trace=True,
    )
    bundle = build_similar_inspection_bundle(similar, tr, max_rows=10)
    assert bundle["schema"] == "similar_set_inspection_v1"
    assert len(bundle["rows"]) <= 10
    r0 = bundle["rows"][0]
    for k in (
        "ts_utc", "zone", "vwap_side", "nearest_above_dist", "nearest_below_dist",
        "nearest_above_dist_bucket_derived", "nearest_below_dist_bucket_derived",
        "outcome_1c", "outcome_5c",
    ):
        assert k in r0
    raw_p = inspection_row_projection(similar[0])
    assert raw_p["zone"] == "ix21_insp"


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
