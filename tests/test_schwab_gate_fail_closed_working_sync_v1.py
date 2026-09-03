"""The Schwab crosswalk WORKING csv's fail-closed classification (spot-validation
no-default-zero, underlying-price-row relocation, MC fusion N7 volatility row) must
stay synced with the code it describes -- a stale crosswalk entry silently
misrepresents what the fail-closed gate actually does."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKING = ROOT / "schwab_field_inventory" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv"


def test_working_call_engine_spot_validation_has_no_default_zero_tag():
    for row in csv.DictReader(WORKING.open(newline="", encoding="utf-8")):
        if row["file"] == "call_engine.py" and row["line"] == "998":
            assert "DEFAULT_ZERO_OR" not in (row.get("tags") or "")
            assert "GET_DEFAULT_ZERO" not in (row.get("tags") or "")
            assert "inp.spot" in row["code"]
            return
    pytest.fail("expected call_engine.py:998 in WORKING.csv")


def test_working_server_underlying_price_row_relocated_to_fail_closed_read():
    for row in csv.DictReader(WORKING.open(newline="", encoding="utf-8")):
        if row["file"] != "server.py":
            continue
        if 'chain_json.get("underlyingPrice")' in (row.get("code") or ""):
            assert row["line"] == "6738"
            assert "DEFAULT_ZERO_OR" not in (row.get("tags") or "")
            return
    pytest.fail("expected relocated underlyingPrice row in WORKING.csv")


def test_mc_fusion_n7_volatility_row_classified_true_analytic_after_upstream_trace():
    from tools.classify_schwab_csv_crosswalk import classify

    row = {
        "file": "mc_fusion_adjustment.py",
        "line": "29",
        "tags": "DEFAULT_ZERO_OR",
        "names": "volatility",
        "candidate_schwab_fields": "chains.callExpDateMap.*.volatility|chains.putExpDateMap.*.volatility|chains.volatility",
        "code": 'vol = float(mc_output.get("volatility") or 0.0)',
    }
    classification, _reason = classify(dict(row))
    assert classification == "TRUE_ANALYTIC_REVIEW"
    assert "MonteCarloOutput" in _reason or "simulation" in _reason.lower()
