"""Stream-coverage eligibility is one schema fact, not two independent rules.

server.gamma_cell_has_contract_identity is the owner. The client paints
stream[j].has_contract_identity onto data-has-contract-identity and counts
only those cells. The JS mirror exists for unstamped fixtures and is locked
here against the Python owner.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import server

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "config" / "gamma_stream_coverage_eligibility_v1.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

PAIRS = [
    ({"call": "C", "put": "P"}, True),
    ({"call": "C", "put": None}, True),
    ({"call": None, "put": "P"}, True),
    ({"call": "", "put": ""}, False),
    ({"call": None, "put": None}, False),
    ({}, False),
    (None, False),
    ("C", False),
]


def test_schema_names_the_one_owner_and_the_unavoidable_mirror():
    assert SCHEMA["schema"] == "gamma_stream_coverage_eligibility_v1"
    assert SCHEMA["owner"] == "server.gamma_cell_has_contract_identity"
    assert SCHEMA["payload_field"] == "has_contract_identity"
    assert SCHEMA["dom_attribute"] == "data-has-contract-identity"
    js = (ROOT / "static" / "js" / "ed-gamma.js").read_text(encoding="utf-8")
    assert SCHEMA["schema"] in js
    assert 'data-has-contract-identity="' in js
    assert "function gammaCellHasContractIdentity" in js
    assert "pair.call || pair.put" in js
    assert "gamma_cell_has_contract_identity" in (ROOT / "server.py").read_text(encoding="utf-8")


def test_python_predicate_is_identity_not_value_state():
    for pair, expected in PAIRS:
        assert server.gamma_cell_has_contract_identity(pair) is expected
    # ZERO OI is still a real contract.
    assert server.gamma_cell_has_contract_identity({"call": "C0", "put": "P0"}) is True


def test_mixed_surface_coverage_excludes_no_contract_includes_zero_oi():
    now = 1_757_000_200.0
    surf = {
        "expirations": [{"expiry": "2026-09-11", "dte": 2}],
        "strikes": [90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0],
        "cells": [
            {"strike": 90.0, "contracts": [{"call": None, "put": None}]},          # NO CONTRACT
            {"strike": 95.0, "contracts": [{"call": "C95", "put": "P95"}]},        # ZERO OI / pending
            {"strike": 100.0, "contracts": [{"call": "C100", "put": "P100"}]},     # computed / live
            {"strike": 105.0, "contracts": [{"call": "C105", "put": None}]},       # stale
            {"strike": 110.0, "contracts": [{"call": "C110", "put": "P110"}]},     # rejected
            {"strike": 115.0, "contracts": [{"call": "C115", "put": "P115"}]},     # pending
            {"strike": 120.0, "contracts": [{"call": "C120", "put": "P120"}]},     # computed / live
        ],
    }
    streamed = {
        "C100": {"gamma_ts_recv": now}, "P100": {"gamma_ts_recv": now},
        "C105": {"gamma_ts_recv": now - 60},
        "C120": {"gamma_ts_recv": now}, "P120": {"gamma_ts_recv": now},
    }
    overlay = {"C100", "P100", "C120", "P120"}
    desired = {"C95", "P95", "C100", "P100", "C105", "C110", "P110", "C115", "P115", "C120", "P120"}
    rejected = {"C110": "vendor refused", "P110": "vendor refused"}
    server._stamp_gamma_surface_cell_stream_state(
        surf, streamed, overlay, rejected, desired, daemon_available=True)
    # Force the ZERO-OI / pending cell and keep NO CONTRACT stamped.
    no_contract = surf["cells"][0]["stream"][0]
    assert no_contract["has_contract_identity"] is False
    assert no_contract["state"] == "unavailable"
    zero = surf["cells"][1]["stream"][0]
    assert zero["has_contract_identity"] is True
    zero["state"] = "pending"
    cov = server._gamma_surface_coverage_summary(surf)
    assert cov["scope"] == "canonical_surface"
    assert cov["total_visible_cells"] == 6, cov
    assert cov["live"] == 2
    assert cov["stale"] == 1
    assert cov["rejected"] == 1
    assert cov["pending"] == 2  # ZERO OI pending + C115 pending
    assert cov["unavailable"] == 0
    assert cov["partial"] == 0
    assert cov["daemon_unavailable"] == 0
    assert cov["live"] + cov["partial"] + cov["stale"] + cov["pending"] + cov[
        "daemon_unavailable"] + cov["rejected"] + cov["unavailable"] == cov["total_visible_cells"]
    assert cov["live_pct"] == round(100.0 * 2 / 6, 1)
    assert cov["meets_live_requirement"] is False
    # NO CONTRACT never entered the denominator — 7 painted cells, 6 eligible.
    assert len(surf["cells"]) == 7


def test_all_eligible_live_is_true_even_with_no_contract_holes():
    now = 1_757_000_200.0
    surf = {
        "cells": [
            {"contracts": [{"call": None, "put": None}]},
            {"contracts": [{"call": "C", "put": "P"}]},
        ]
    }
    server._stamp_gamma_surface_cell_stream_state(
        surf, {"C": {"gamma_ts_recv": now}, "P": {"gamma_ts_recv": now}}, {"C", "P"})
    cov = server._gamma_surface_coverage_summary(surf)
    assert cov["total_visible_cells"] == 1
    assert cov["live"] == 1
    assert cov["meets_live_requirement"] is True
    assert cov["live_pct"] == 100.0


def test_js_mirror_matches_python_owner_on_the_same_pairs():
    node = shutil.which("node")
    if not node:
        pytest.fail("Node.js is required to lock the JS eligibility mirror")
    script = r"""
const { readFileSync } = require('fs');
const vm = require('vm');
const src = readFileSync('static/js/ed-gamma.js', 'utf8');
vm.runInThisContext(src, { filename: 'ed-gamma.js' });
const pairs = %s;
const out = pairs.map(([pair]) => global.EdGamma.gammaCellHasContractIdentity(pair));
process.stdout.write(JSON.stringify(out));
""" % json.dumps([[p] for p, _ in PAIRS if p is None or isinstance(p, dict)])
    r = subprocess.run([node, "-e", script], cwd=str(ROOT), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
    js_out = json.loads(r.stdout)
    expected = [server.gamma_cell_has_contract_identity(p) for p, _ in PAIRS if p is None or isinstance(p, dict)]
    assert js_out == expected


def test_js_ticker_storage_key_matches_python_owner():
    from instrument_identity import ticker_storage_key
    node = shutil.which("node")
    if not node:
        pytest.fail("Node.js is required to lock tickerStorageKey")
    cases = ["SPY", "spy", "QQQ", "$SPX", "SPX", "NDX", ""]
    payload = json.dumps(cases)
    script = """
const { readFileSync } = require('fs');
const vm = require('vm');
const cases = JSON.parse(process.env.TICKER_KEY_CASES);
const ctx = { cases: cases };
vm.createContext(ctx);
const src = readFileSync('static/js/ed-core.js', 'utf8');
const start = src.indexOf('function tickerStorageKey');
const end = src.indexOf('function removeSymbol');
if (start < 0 || end < 0) { process.stderr.write('tickerStorageKey not found'); process.exit(2); }
const fnSrc = src.slice(src.lastIndexOf('var BROKER_INDEX_BARE_ROOTS', start), end);
vm.runInContext(fnSrc + '; this.out = this.cases.map(tickerStorageKey);', ctx);
process.stdout.write(JSON.stringify(ctx.out));
"""
    r = subprocess.run(
        [node, "-e", script],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        env={**__import__("os").environ, "TICKER_KEY_CASES": payload},
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
    js_out = json.loads(r.stdout)
    py_out = [ticker_storage_key(c) for c in cases]
    assert js_out == py_out
