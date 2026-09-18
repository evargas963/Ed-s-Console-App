"""Stream-coverage eligibility is one schema fact owned by the server stamp.

server.gamma_cell_has_contract_identity reuses instrument_identity.vendor_option_root.
The client consumes only stream[j].has_contract_identity === true. There is no JS
identity parser and no JS ticker normalizer.
"""
from __future__ import annotations

import json
from pathlib import Path

import server

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "config" / "gamma_stream_coverage_eligibility_v1.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def osi(root: str, yymmdd: str = "260911", cp: str = "C", strike: str = "00001000") -> str:
    return f"{root:<6}{yymmdd}{cp}{strike}"


C = osi("SPY", cp="C")
P = osi("SPY", cp="P")
C95 = osi("SPY", strike="00095000")
P95 = osi("SPY", cp="P", strike="00095000")
C100 = osi("SPY", strike="00100000")
P100 = osi("SPY", cp="P", strike="00100000")
C105 = osi("SPY", strike="00105000")
C110 = osi("SPY", strike="00110000")
P110 = osi("SPY", cp="P", strike="00110000")
C115 = osi("SPY", strike="00115000")
P115 = osi("SPY", cp="P", strike="00115000")
C120 = osi("SPY", strike="00120000")
P120 = osi("SPY", cp="P", strike="00120000")

PAIRS = [
    ({"call": C, "put": P}, True),
    ({"call": C, "put": None}, True),
    ({"call": None, "put": P}, True),
    ({"call": "", "put": ""}, False),
    ({"call": None, "put": None}, False),
    ({}, False),
    (None, False),
    ("C", False),
    ({"call": "C", "put": "P"}, False),
    ({"call": "C95", "put": "P95"}, False),
    ({"call": "X", "put": "Y"}, False),
    ({"call": 123, "put": None}, False),
    ({"call": ["not", "a", "string"], "put": None}, False),
    ({"call": {"symbol": C}, "put": None}, False),
]


def test_schema_names_the_one_owner_and_forbids_a_js_parser():
    assert SCHEMA["schema"] == "gamma_stream_coverage_eligibility_v1"
    assert SCHEMA["owner"] == "server.gamma_cell_has_contract_identity"
    assert SCHEMA["validator"] == "instrument_identity.vendor_option_root"
    assert SCHEMA["payload_field"] == "has_contract_identity"
    assert SCHEMA["dom_attribute"] == "data-has-contract-identity"
    assert "mirror_owner" not in SCHEMA
    js = (ROOT / "static" / "js" / "ed-gamma.js").read_text(encoding="utf-8")
    assert SCHEMA["schema"] in js
    assert 'data-has-contract-identity="' in js
    assert "function gammaCellHasContractIdentity" not in js
    assert "pair.call || pair.put" not in js
    assert "has_contract_identity === true" in js
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "gamma_cell_has_contract_identity" in src
    assert "vendor_option_root" in src
    assert "total_eligible_cells" in src
    assert '"total_visible_cells": relevant' not in src


def test_python_predicate_reuses_vendor_option_root_not_truthy_pairs():
    from instrument_identity import vendor_option_root

    owner = server.gamma_cell_has_contract_identity
    src = __import__("inspect").getsource(owner)
    assert "vendor_option_root" in src
    assert "pair.get(\"call\") or pair.get(\"put\")" not in src
    for pair, expected in PAIRS:
        assert owner(pair) is expected
    assert vendor_option_root(C) == "SPY"
    assert vendor_option_root("C95") == ""
    assert owner({"call": C, "put": P}) is True


def test_mixed_surface_coverage_excludes_no_contract_includes_zero_oi():
    now = 1_757_000_200.0
    surf = {
        "expirations": [{"expiry": "2026-09-11", "dte": 2}],
        "strikes": [90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0],
        "cells": [
            {"strike": 90.0, "contracts": [{"call": None, "put": None}]},
            {"strike": 95.0, "contracts": [{"call": C95, "put": P95}]},
            {"strike": 100.0, "contracts": [{"call": C100, "put": P100}]},
            {"strike": 105.0, "contracts": [{"call": C105, "put": None}]},
            {"strike": 110.0, "contracts": [{"call": C110, "put": P110}]},
            {"strike": 115.0, "contracts": [{"call": C115, "put": P115}]},
            {"strike": 120.0, "contracts": [{"call": C120, "put": P120}]},
        ],
    }
    streamed = {
        C100: {"gamma_ts_recv": now}, P100: {"gamma_ts_recv": now},
        C105: {"gamma_ts_recv": now - 60},
        C120: {"gamma_ts_recv": now}, P120: {"gamma_ts_recv": now},
    }
    overlay = {C100, P100, C120, P120}
    desired = {C95, P95, C100, P100, C105, C110, P110, C115, P115, C120, P120}
    rejected = {C110: "vendor refused", P110: "vendor refused"}
    server._stamp_gamma_surface_cell_stream_state(
        surf, streamed, overlay, rejected, desired, daemon_available=True)
    no_contract = surf["cells"][0]["stream"][0]
    assert no_contract["has_contract_identity"] is False
    assert no_contract["state"] == "unavailable"
    zero = surf["cells"][1]["stream"][0]
    assert zero["has_contract_identity"] is True
    zero["state"] = "pending"
    cov = server._gamma_surface_coverage_summary(surf)
    assert cov["scope"] == "canonical_surface"
    assert "total_visible_cells" not in cov
    assert cov["total_eligible_cells"] == 6, cov
    assert cov["live"] == 2
    assert cov["stale"] == 1
    assert cov["rejected"] == 1
    assert cov["pending"] == 2
    assert cov["unavailable"] == 0
    assert cov["live"] + cov["partial"] + cov["stale"] + cov["pending"] + cov[
        "daemon_unavailable"] + cov["rejected"] + cov["unavailable"] == cov["total_eligible_cells"]
    assert cov["meets_live_requirement"] is False


def test_all_eligible_live_is_true_even_with_no_contract_holes():
    now = 1_757_000_200.0
    surf = {
        "cells": [
            {"contracts": [{"call": None, "put": None}]},
            {"contracts": [{"call": C, "put": P}]},
        ]
    }
    server._stamp_gamma_surface_cell_stream_state(
        surf, {C: {"gamma_ts_recv": now}, P: {"gamma_ts_recv": now}}, {C, P})
    cov = server._gamma_surface_coverage_summary(surf)
    assert cov["total_eligible_cells"] == 1
    assert cov["live"] == 1
    assert cov["meets_live_requirement"] is True


def test_missing_or_malformed_stamp_is_ineligible_on_the_client():
    js = (ROOT / "static" / "js" / "ed-gamma.js").read_text(encoding="utf-8")
    assert "cellState.has_contract_identity === true" in js
    assert "function gammaCellHasContractIdentity" not in js


def test_canonical_eligible_count_is_not_named_visible():
    now = 1_757_000_200.0
    surf = {
        "cells": [
            {"contracts": [{"call": C, "put": P}],
             "stream": [{"state": "live"}]},
        ]
    }
    server._stamp_gamma_surface_cell_stream_state(
        surf, {C: {"gamma_ts_recv": now}, P: {"gamma_ts_recv": now}}, {C, P})
    cov = server._gamma_surface_coverage_summary(surf)
    assert cov["scope"] == "canonical_surface"
    assert "total_eligible_cells" in cov
    assert "total_visible_cells" not in cov
    js = (ROOT / "static" / "js" / "ed-gamma.js").read_text(encoding="utf-8")
    assert "scope: 'visible_surface'" in js
    assert "total_visible_cells: total" in js


def test_js_has_no_ticker_normalizer():
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    gamma = (ROOT / "static" / "js" / "ed-gamma.js").read_text(encoding="utf-8")
    assert "function tickerStorageKey" not in core
    assert "BROKER_INDEX_BARE_ROOTS" not in core
    assert "tickerStorageKey" not in gamma
    assert "requested_ticker" in gamma


def test_gamma_surface_echoes_requested_ticker():
    tk = server.ticker_storage_key("SPY")
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    server._GAMMA_SURFACE_CACHE.pop(tk, None)
    body = json.loads(server.get_options_gamma_surface("SPY").body)
    assert body["requested_ticker"] == "SPY"
    assert body["ticker"] == tk
