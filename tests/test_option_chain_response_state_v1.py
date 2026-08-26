"""OPTIONS FLOW — the REST chain response envelope must be retained at the cadence it arrives.

THE MEASURED LOSS. Production received 4,209 chain responses in 24 hours across 58 tickers and
retained the envelope of roughly 39 of them — the once-per-ticker-per-day morning wide chain.
Every other response was parsed for contracts and its envelope discarded, including:

  * interestRate / dividendYield — the vendor's own r and q, while our greeks use r = q = 0.
    Whether that is acceptable is an empirical question that a 09:30 sample cannot answer.
  * underlyingPrice and the 23-field underlying quote block — a native spot arriving on the very
    same response as the chain the greeks were computed from.
  * isChainTruncated — whether the vendor cut the response. RC-491 showed truncation is real
    here, and truncation silently changes what any span or coverage claim means.

MEASURED COST of keeping all of it: ~754 bytes per response, 3.17 MB/day, 0.80 GB/year. Cheap
enough that temporal fidelity is not traded for convenience — every response is kept, not a
sample, and not only the ones where a value changed.

Nothing here is a signal. These are native vendor observations; nothing may enter Decide.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from calibration.option_chain_response_state import (  # noqa: E402
    TABLE_NAME,
    persist_response_state,
    project_response_state,
    response_state_as_of,
)


def _response(**over) -> dict:
    """A vendor-shaped chain response. institutional-synthetic-ok: this exercises PROJECTION
    of a documented envelope shape, and derives no market claim from the values."""
    d = {
        "symbol": "SPY", "status": "SUCCESS", "strategy": "SINGLE", "interval": 1.0,
        "isDelayed": False, "isIndex": False, "interestRate": 4.271, "dividendYield": 1.1234,
        "volatility": 29.0, "underlyingPrice": 767.42, "daysToExpiration": 0.0,
        "numberOfContracts": 229, "isChainTruncated": False, "assetMainType": "OPTION",
        "assetSubType": "",
        "underlying": {"symbol": "SPY", "bid": 767.40, "ask": 767.44, "last": 767.42,
                       "totalVolume": 54210987, "quoteTime": 1787756982006},
        "callExpDateMap": {"2026-08-26:0": {}}, "putExpDateMap": {"2026-08-26:0": {}},
    }
    d.update(over)
    return d


def test_the_vendors_r_and_q_are_retained_not_discarded(tmp_path):
    """interestRate/dividendYield are the whole point: our greeks assume both are zero."""
    db = str(tmp_path / "s.db")
    persist_response_state(db, "SPY", time.time(), _response())
    row = response_state_as_of(db, "SPY", time.time() + 1)
    assert row is not None, "nothing was retained"
    assert row["interest_rate"] == 4.271
    assert row["dividend_yield"] == 1.1234
    assert row["volatility"] == 29.0
    assert row["underlying_price"] == 767.42


def test_truncation_flag_survives_because_it_changes_what_a_span_means(tmp_path):
    db = str(tmp_path / "s.db")
    persist_response_state(db, "SPY", time.time(), _response(isChainTruncated=True))
    row = response_state_as_of(db, "SPY", time.time() + 1)
    assert row["is_chain_truncated"] == 1, (
        "a truncated chain must be recorded as truncated — otherwise a coverage or span claim "
        "computed from it is silently wrong")


def test_unknown_vendor_fields_are_kept_not_dropped(tmp_path):
    """Raw-first is what let breakEven and ssid survive in the contract store; the envelope
    needs the same property, or the next vendor addition is lost the same way."""
    db = str(tmp_path / "s.db")
    persist_response_state(db, "SPY", time.time(),
                           _response(someBrandNewVendorField={"a": 1}, anotherNew="x"))
    row = response_state_as_of(db, "SPY", time.time() + 1)
    extra = json.loads(row["envelope_extra_json"])
    assert extra.get("someBrandNewVendorField") == {"a": 1}
    assert extra.get("anotherNew") == "x"


def test_the_underlying_quote_block_is_stored_whole(tmp_path):
    db = str(tmp_path / "s.db")
    persist_response_state(db, "SPY", time.time(), _response())
    row = response_state_as_of(db, "SPY", time.time() + 1)
    und = json.loads(row["underlying_json"])
    for k in ("bid", "ask", "last", "totalVolume", "quoteTime"):
        assert k in und, f"underlying block lost {k}"


def test_contract_maps_do_not_bloat_the_envelope_row(tmp_path):
    """The contracts are persisted elsewhere; duplicating them here would multiply storage by
    thousands and make the measured 754-bytes-per-response cost a fiction."""
    db = str(tmp_path / "s.db")
    big = _response(callExpDateMap={f"exp{i}": {"strike": [{"x": 1}] * 50} for i in range(40)})
    persist_response_state(db, "SPY", time.time(), big)
    row = response_state_as_of(db, "SPY", time.time() + 1)
    blob = (row["envelope_extra_json"] or "") + (row["underlying_json"] or "")
    assert "callExpDateMap" not in blob and "putExpDateMap" not in blob
    assert len(blob) < 4000, f"envelope row carried contract payload: {len(blob)} bytes"


def test_retention_is_per_response_not_per_day(tmp_path):
    """The defect being closed was keeping ~39 of 4,209 responses. Every call must land."""
    db = str(tmp_path / "s.db")
    t0 = time.time()
    for i in range(25):
        persist_response_state(db, "SPY", t0 + i, _response(interestRate=4.0 + i * 0.001))
    n = sqlite3.connect(db).execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
    assert n == 25, f"retained {n} of 25 responses — this is the sampling defect again"

    # And the as-of read is causal: the value at t0+10 is the one observed then, not the latest.
    row = response_state_as_of(db, "SPY", t0 + 10.5)
    assert abs(row["interest_rate"] - 4.010) < 1e-9, (
        f"as-of read returned {row['interest_rate']} — a later observation leaked backwards")


def test_a_malformed_response_is_skipped_softly(tmp_path):
    """Retention runs on the snapshot path; it must never be able to break a request."""
    db = str(tmp_path / "s.db")
    assert persist_response_state(db, "SPY", time.time(), None)["status"] == "skipped"
    assert persist_response_state(db, "SPY", time.time(), "not a dict")["status"] == "skipped"
    assert project_response_state("SPY", time.time(), []) is None


def test_unparseable_numeric_is_preserved_rather_than_zeroed(tmp_path):
    """A junk value must not become a confident 0.0 — that would fabricate an observation."""
    db = str(tmp_path / "s.db")
    persist_response_state(db, "SPY", time.time(), _response(interestRate="n/a"))
    row = response_state_as_of(db, "SPY", time.time() + 1)
    assert row["interest_rate"] is None, "unparseable rate was coerced into a number"
    assert json.loads(row["envelope_extra_json"])["interestRate"] == "n/a", (
        "the raw unparseable value must be kept so the anomaly stays diagnosable")
