"""RC-262 — the one-faucet live check must measure values, not spelling.

WHAT WAS MEASURED (2026-08-06, against the running server on 127.0.0.1:8000):

  * 19 single-subject endpoints, 400 numeric fields, 249 of them (62%) produced
    by more than one endpoint, 12-13 disagreeing on every run.
  * `book_imbalance_5` returned -0.314 from /api/analytics/light and +0.212
    from /api/state at the same instant. Opposite signs on a directional
    order-flow signal, reproduced three times over ~30 minutes.
  * `spot` spanned 769.79 to 775.43 across 14 endpoints -- and WHICH endpoint
    was the outlier changed between runs, so the defect is nondeterministic.
  * `lo`/`hi` expected-range bands: /api/terrain says 755/785 while
    /api/desk/structure says 723.6/831.8.

  Meanwhile `check_single_spot_authority` was GREEN throughout, because it bans
  one string in two files and has never compared two values.

The negative controls at the bottom prove this check earns its result: it fails
on a real disagreement, passes on genuine agreement, and stays silent on the
things that are SUPPOSED to differ between two samples.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_one_faucet_live as OF  # noqa: E402


# ---------------------------------------------------------------- shape ----

def test_exclusions_are_data_and_carry_a_reason():
    """A silent exclusion is how a check quietly stops covering things."""
    assert OF.EXCLUDED, "exclusions must be enumerated, not implicit"
    for endpoint, reason in OF.EXCLUDED.items():
        assert endpoint.startswith("/api/"), endpoint
        assert len(reason) > 10, f"{endpoint} excluded without a real reason"
    overlap = set(OF.EXCLUDED) & set(OF.SINGLE_SUBJECT)
    assert overlap == set(), f"endpoint both compared and excluded: {overlap}"


def test_single_subject_list_is_not_empty_and_has_no_duplicates():
    assert len(OF.SINGLE_SUBJECT) >= 10
    assert len(set(OF.SINGLE_SUBJECT)) == len(OF.SINGLE_SUBJECT)


def test_lists_are_never_descended_into():
    """Row zero of two different collections is not a faucet comparison.

    Descending into lists is exactly how a naive version of this check
    manufactured a fake $475 spot spread by comparing SPY against whatever
    subject happened to be first in a radar payload.
    """
    payload = {"rows": [{"spot": 100.0}, {"spot": 200.0}], "spot": 771.42}
    leaves = OF.numeric_leaves(payload)
    assert leaves == {"spot": 771.42}, leaves


def test_booleans_are_not_treated_as_numbers():
    assert OF.numeric_leaves({"available": True, "spot": 1.0}) == {"spot": 1.0}


# ------------------------------------------------------ volatile fields ----

@pytest.mark.parametrize("name", [
    "exchange_quote_ts", "decision_timestamp_utc", "l1_build_total",
    "fast_generation_id", "levels_age_sec", "chain_gate_wait_ms",
    "busy_retry_count", "now", "uptime",
])
def test_volatile_fields_are_not_flagged(name):
    """Counters and clocks SHOULD differ between two samples.

    Flagging them is how a check trains its readers to ignore it.
    """
    assert OF.is_volatile(name), f"{name} must be treated as volatile"


@pytest.mark.parametrize("name", [
    "spot", "bid", "ask", "book_imbalance_5", "order_flow_score",
    "cum_delta_proxy", "gex", "flip", "lo", "hi",
])
def test_domain_measurements_are_never_treated_as_volatile(name):
    """The fields the check exists to protect must not be excused."""
    assert not OF.is_volatile(name), f"{name} must be compared, not excused"
    assert name not in OF.META, f"{name} must not be filtered as meta"


# --------------------------------------------------- negative controls -----

def _census(monkeypatch, responses):
    monkeypatch.setattr(
        OF, "SINGLE_SUBJECT", tuple(responses), raising=True)
    monkeypatch.setattr(
        OF, "fetch",
        lambda base, endpoint, ticker: responses[endpoint], raising=True)
    produced, unreachable = OF.census("http://x", "SPY")
    multi = {f: m for f, m in produced.items() if len(m) > 1}
    return {f: m for f, m in multi.items() if len(set(m.values())) > 1}


def test_negative_control_disagreement_is_detected(monkeypatch):
    """The exact live defect: opposite signs under one field name."""
    disagreeing = _census(monkeypatch, {
        "/api/state": {"book_imbalance_5": 0.21212121212121213},
        "/api/analytics/light": {"book_imbalance_5": -0.3140096618357488},
    })
    assert "book_imbalance_5" in disagreeing
    assert len(disagreeing["book_imbalance_5"]) == 2


def test_negative_control_agreement_passes(monkeypatch):
    """The check must be able to pass, or it is noise rather than a signal."""
    assert _census(monkeypatch, {
        "/api/state": {"spot": 771.42},
        "/api/terrain": {"spot": 771.42},
        "/api/levels": {"spot": 771.42},
    }) == {}


def test_negative_control_single_faucet_is_not_a_finding(monkeypatch):
    """One producer per field is the GOAL. It must never be reported."""
    assert _census(monkeypatch, {
        "/api/state": {"only_here": 1.0},
        "/api/terrain": {"somewhere_else": 2.0},
    }) == {}


def test_negative_control_volatile_disagreement_is_ignored(monkeypatch):
    """Two clocks read microseconds apart must not fail the build."""
    assert _census(monkeypatch, {
        "/api/state": {"exchange_quote_ts": 1786015898.808, "spot": 771.42},
        "/api/live/state": {"exchange_quote_ts": 1786015904.952, "spot": 771.42},
    }) == {}


def test_negative_control_tiny_real_difference_still_fails(monkeypatch):
    """No tolerance band. One cent of disagreement is still two faucets.

    A threshold here would be the same mistake as the spelling gate: it would
    let the defect exist quietly until it grew.
    """
    disagreeing = _census(monkeypatch, {
        "/api/state": {"spot": 771.42},
        "/api/fast-quote": {"spot": 771.43},
    })
    assert "spot" in disagreeing


# ------------------------------------------------------------- contract ----

def test_exit_code_contract(monkeypatch):
    """0 agree · 1 disagreement · 2 unreachable. A gate nobody can script is a report."""
    monkeypatch.setattr(OF, "SINGLE_SUBJECT", ("/api/spot",), raising=True)
    monkeypatch.setattr(OF, "fetch", lambda b, e, t: None, raising=True)
    assert OF.main(["--base", "http://127.0.0.1:9"]) == 2

    monkeypatch.setattr(
        OF, "SINGLE_SUBJECT", ("/api/spot", "/api/terrain"), raising=True)
    monkeypatch.setattr(
        OF, "fetch", lambda b, e, t: {"spot": 771.42}, raising=True)
    assert OF.main([]) == 0

    payloads = {"/api/spot": {"spot": 771.42}, "/api/terrain": {"spot": 775.43}}
    monkeypatch.setattr(
        OF, "fetch", lambda b, e, t: payloads.get(e, {"spot": 771.42}),
        raising=True)
    assert OF.main([]) == 1
