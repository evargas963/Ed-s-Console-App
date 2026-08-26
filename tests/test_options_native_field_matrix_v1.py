"""OPTIONS FLOW FOUNDATION — the native Schwab options surface must be fully dispositioned.

OPERATOR REQUIREMENT (2026-08-26): useful native Schwab options truth must not be discarded merely
because today's code does not consume it. Every native field proves ONE of:
    RETAINED_RAW_AND_PROJECTED | RETAINED_RAW | DELIBERATELY_EXCLUDED (with a concrete reason)
and NATIVE_AVAILABLE_BUT_NOT_RETAINED is not an acceptable final state.

This is the machine check for that requirement. It does NOT trust a hand-maintained list: the tool
re-enumerates the surface from EVIDENCE every run — the committed canonical inventory for REST
/chains, and real captured frames for LEVELONE_OPTIONS / OPTIONS_BOOK — and fails when the matrix
and the vendor surface disagree in either direction. A new vendor field with no disposition fails
here; a matrix entry naming a field the evidence does not show fails here too.

Why this matters concretely: the chain ENVELOPE (interestRate, dividendYield, isChainTruncated,
underlying) was received on every fetch and destroyed before any persister saw it. Nothing caught
that, because nothing was checking the surface against what we keep.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.options_native_field_matrix_v1 import (
    FORBIDDEN_DISPOSITION,
    MATRIX_REL,
    VALID_DISPOSITIONS,
    enumerate_surface,
    validate,
)

MATRIX_PATH = REPO / MATRIX_REL


def _matrix() -> dict:
    assert MATRIX_PATH.is_file(), f"{MATRIX_REL} missing — the native surface has no disposition"
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def test_every_native_field_carries_a_disposition_and_none_is_forbidden():
    """The whole requirement, in one assertion driven by the evidence-backed enumerator."""
    problems = validate(_matrix())
    assert not problems, "native options surface is not fully dispositioned:\n  - " + "\n  - ".join(problems)


def test_the_surface_is_enumerated_from_evidence_not_hand_listed():
    """Guard the guard: if the enumerator silently returned nothing, the test above would pass
    vacuously. Pin all seven surfaces non-empty and the census at the reconciled population."""
    surf = enumerate_surface()
    assert set(surf) == {
        "rest_chain_envelope", "rest_chain_underlying", "rest_chain_contract", "levelone_options",
        "options_book_frame", "options_book_price_level", "options_book_market_maker",
    }
    for name, fields in surf.items():
        assert fields, f"{name} enumerated EMPTY — evidence file missing or shape changed"
    assert sum(len(v) for v in surf.values()) >= 171, "census shrank below the reconciled population"


def test_nested_underlying_leaves_are_censused_not_swallowed_by_raw_retention():
    """REGRESSION (2026-08-26): the census reported 148 where the investigation found 171, because
    the 23 chains.underlying.* leaves matched neither the depth-1 envelope filter nor the
    call/putExpDateMap filter and were silently dropped. Being retained inside a raw nested object
    justifies a RETAINED disposition; it never justifies absence from the matrix."""
    surf = enumerate_surface()
    und = surf["rest_chain_underlying"]
    assert len(und) >= 23, f"underlying leaves under-censused: {len(und)}"
    for leaf in ("quoteTime", "tradeTime", "totalVolume", "mark", "symbol"):
        assert leaf in und, f"chains.underlying.{leaf} missing from the census"
    m = _matrix()["surfaces"]["rest_chain_underlying"]
    for leaf in und:
        assert leaf in m, f"chains.underlying.{leaf} has no disposition"


def test_an_inert_writer_cannot_be_counted_as_retention():
    """The load-bearing honesty rule: LEVELONE_OPTIONS / OPTIONS_BOOK have a tested writer and
    projection, but production subscribes to NEITHER service, so nothing is retained today. They
    must NOT read as retained, and their not-wired state must say what is missing."""
    from tools.options_native_field_matrix_v1 import NOT_RETAINED_STATES

    m = _matrix()["surfaces"]
    for surface in ("levelone_options", "options_book_frame", "options_book_price_level",
                    "options_book_market_maker"):
        for name, entry in m[surface].items():
            assert entry["disposition"] in NOT_RETAINED_STATES, (
                f"{surface}.{name} claims {entry['disposition']} while production subscribes to "
                f"neither options service — an inert writer is not retention")
            assert entry["blocked_on"].strip(), f"{surface}.{name} must state what is not wired"


def test_the_chain_fields_the_operator_named_are_retained_in_production_today():
    """These ride a fetch production already makes, so there is no excuse short of retention."""
    m = _matrix()["surfaces"]
    for surface, fields in {
        "rest_chain_envelope": ["interestRate", "dividendYield", "isChainTruncated", "underlying"],
    }.items():
        for f in fields:
            entry = m.get(surface, {}).get(f)
            assert entry, f"{surface}.{f} is absent from the matrix"
            assert entry["disposition"].startswith("RETAINED_RAW"), (
                f"{surface}.{f} must be RETAINED_RAW — production receives and persists it TODAY "
                f"(operator named it explicitly); got {entry['disposition']}")
            assert entry["retained_in"].strip(), f"{surface}.{f} claims retention but names no store"


def test_the_market_maker_fields_the_operator_named_are_ready_and_honestly_labelled():
    """Market snapshot time, MM count, MM id and per-MM size are the spine of the flow product.
    Production subscribes to neither options service, so the honest state is READY-NOT-WIRED — never
    EXCLUDED (that would abandon them) and never RETAINED (that would be an inert-writer lie).
    Each must also name a projection, so wiring the subscription is the ONLY remaining step."""
    m = _matrix()["surfaces"]
    for surface, fields in {
        "options_book_frame": ["BOOK_TIME"],
        "options_book_price_level": ["NUM_BIDS", "NUM_ASKS", "TOTAL_VOLUME"],
        "options_book_market_maker": ["EXCHANGE", "BID_VOLUME", "ASK_VOLUME", "SEQUENCE"],
    }.items():
        for f in fields:
            entry = m.get(surface, {}).get(f)
            assert entry, f"{surface}.{f} is absent from the matrix"
            assert entry["disposition"] == "RETENTION_PATH_READY_NOT_WIRED", (
                f"{surface}.{f}: expected the honest not-wired state, got {entry['disposition']}")
            assert entry["projection"].strip(), (
                f"{surface}.{f} must name the projection that will read it once wired")
            assert entry["blocked_on"].strip(), f"{surface}.{f} must state what is not wired"


def test_l1_temporal_identifiers_are_retained():
    """Quote/trade timestamps and identifiers are the temporal spine of any flow product."""
    l1 = _matrix()["surfaces"]["levelone_options"]
    for f in ("QUOTE_TIME_MILLIS", "TRADE_TIME_MILLIS", "key", "UNDERLYING"):
        assert f in l1, f"LEVELONE_OPTIONS.{f} missing from the matrix"
        assert l1[f]["disposition"] != FORBIDDEN_DISPOSITION


def test_exclusions_are_argued_not_asserted():
    for surface, fields in _matrix()["surfaces"].items():
        for name, entry in fields.items():
            if entry["disposition"] == "DELIBERATELY_EXCLUDED":
                assert len(entry.get("reason", "").strip()) > 40, (
                    f"{surface}.{name}: exclusion needs a concrete reason, not a token string")
            assert entry["disposition"] in VALID_DISPOSITIONS
