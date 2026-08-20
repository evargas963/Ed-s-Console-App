"""RC-438 — refresh Schwab native schema inventory (no live token required)."""
from __future__ import annotations

import json
from pathlib import Path

from tools.refresh_schwab_native_field_inventory import (
    build_capability_matrix_v2,
    build_universe_map,
    diff_definitions_vs_prior,
    extract_streamer_schema,
    load_prior_canonical,
)

REPO = Path(__file__).resolve().parents[1]


def test_extract_streamer_schema_includes_book_and_l1():
    schema = extract_streamer_schema()
    assert schema["schwab_py_version"]
    assert "LevelOneEquityFields" in schema["enums"]
    assert len(schema["enums"]["LevelOneEquityFields"]) == 52
    assert schema["enums"]["BidFields"][2]["name"] == "NUM_BIDS"
    assert schema["enums"]["BidFields"][2]["number"] == 2
    assert schema["timesale_wrapper_present"] is False
    # FOREX has MARKET_MAKER; equity L1 does not
    forex = {f["name"] for f in schema["enums"]["LevelOneForexFields"]}
    equity = {f["name"] for f in schema["enums"]["LevelOneEquityFields"]}
    assert "MARKET_MAKER" in forex
    assert "MARKET_MAKER" not in equity


def test_diff_does_not_invent_field_number_changes():
    schema = extract_streamer_schema()
    prior = load_prior_canonical()
    diff = diff_definitions_vs_prior(schema, prior)
    assert diff["field_number_changes"]["status"] == "NONE_DETECTED_VS_SELF"
    # Book schema still has NUM_* / EXCHANGE in prior terminals
    assert "NUM_BIDS" in diff["nested_book_field_changes"]["prior_had"]
    assert "EXCHANGE" in diff["nested_book_field_changes"]["prior_had"]


def test_matrix_v2_keeps_documented_native_out_of_not_proven_bucket():
    schema = extract_streamer_schema()
    matrix = build_capability_matrix_v2(schema, {"status": "LIVE_BLOCKED"})
    assert matrix["schema_version"] == 2
    tob = next(r for r in matrix["rows"] if "TOB" in r["concept"])
    assert tob["semantic_interpretation"] == "DOCUMENTED_NATIVE"
    assert tob["native_documented_available"] == "AVAILABLE_IN_SCHWAB_PY"
    num = next(r for r in matrix["rows"] if "NUM_BIDS" in r["concept"])
    assert num["native_documented_available"] == "AVAILABLE_IN_SCHWAB_PY"
    assert num["semantic_interpretation"] == "NEEDS_RTH"
    assert "NOT_PROVEN" not in num["semantic_interpretation"]
    assert num["currently_discarded_unused"] == "YES"


def test_universe_map_has_six_buckets():
    u = build_universe_map()
    for k in (
        "NATIVE_USED",
        "NATIVE_UNUSED",
        "DERIVED_TODAY",
        "DERIVABLE",
        "PROXY_INFERRED",
        "UNAVAILABLE",
    ):
        assert k in u
        assert u[k]
    assert any("NUM_BIDS" in x["field"] for x in u["NATIVE_UNUSED"])


def test_refresh_cli_writes_artifacts(tmp_path, monkeypatch):
    # Run against real repo paths (tool writes to fixed locations) — just invoke main
    import tools.refresh_schwab_native_field_inventory as mod

    rc = mod.main(["--skip-live-attempt"])
    assert rc == 0
    assert (REPO / "schwab_field_inventory" / "schwab_native_schema_inventory_v1.json").is_file()
    assert (REPO / "reports" / "of_schwab_native_inventory_refresh_v1.json").is_file()
    doc = json.loads(
        (REPO / "schwab_field_inventory" / "schwab_native_schema_inventory_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert "LevelOneOptionFields" in doc["enums"]
