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
    vacuously. Pin that all six surfaces are non-empty and the count is the real one."""
    surf = enumerate_surface()
    assert set(surf) == {
        "rest_chain_envelope", "rest_chain_contract", "levelone_options",
        "options_book_frame", "options_book_price_level", "options_book_market_maker",
    }
    for name, fields in surf.items():
        assert fields, f"{name} enumerated EMPTY — evidence file missing or shape changed"
    assert sum(len(v) for v in surf.values()) >= 140, "surface shrank unexpectedly; re-check evidence"


def test_the_fields_the_operator_named_are_retained_not_excluded():
    """These are the specific losses the mission was opened over. None may regress to excluded."""
    m = _matrix()["surfaces"]
    must_retain = {
        "rest_chain_envelope": ["interestRate", "dividendYield", "isChainTruncated", "underlying"],
        "options_book_frame": ["BOOK_TIME"],
        "options_book_price_level": ["NUM_BIDS", "NUM_ASKS"],
        "options_book_market_maker": ["EXCHANGE", "BID_VOLUME", "ASK_VOLUME"],
    }
    for surface, fields in must_retain.items():
        for f in fields:
            entry = m.get(surface, {}).get(f)
            assert entry, f"{surface}.{f} is absent from the matrix"
            assert entry["disposition"] in ("RETAINED_RAW", "RETAINED_RAW_AND_PROJECTED"), (
                f"{surface}.{f} must be retained (operator named it explicitly); "
                f"got {entry['disposition']}")
            assert entry["retained_in"].strip(), f"{surface}.{f} claims retention but names no store"


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
