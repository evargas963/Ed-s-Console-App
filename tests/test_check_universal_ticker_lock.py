"""UNIVERSAL_TICKER_MECHANICAL_LOCK_V1 — checker proof tests.

Mission-required fail/pass cases (operator-approved 2026-07-07): base anchors
are the minimum live proof surface, never the universal proof boundary;
BASE_TICKER_ONLY_CLOSURE is FORBIDDEN; representative-only proof is NOT_PROVEN.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_universal_ticker_lock import (  # noqa: E402
    BASE_ANCHOR_TICKERS,
    REQUIRED_PACKET_FIELDS,
    UNIVERSALITY_CLASSIFICATIONS,
    check_packet_text,
    is_production_python,
    run_check,
    scan_python_source_for_ticker_literals,
)


def _proven_packet(extra: str = "", fields: tuple[str, ...] = REQUIRED_PACKET_FIELDS) -> str:
    body = "\n".join(f"- {f}: provided" for f in fields if f != "UNIVERSALITY_CLASSIFICATION")
    return (
        "# Packet\n"
        f"{body}\n"
        "- UNIVERSALITY_CLASSIFICATION: UNIVERSAL_TICKER_AGNOSTIC_PROVEN\n"
        f"{extra}\n"
    )


# ── FAIL cases ────────────────────────────────────────────────────────────────


def test_base_only_universal_claim_fails():
    """Packet claiming universal-proven on SPY/QQQ/IWM evidence alone FAILS."""
    text = (
        "# Packet\n"
        "Evidence: SPY, QQQ, IWM matrices all green.\n"
        "- UNIVERSALITY_CLASSIFICATION: UNIVERSAL_TICKER_AGNOSTIC_PROVEN\n"
    )
    errs = check_packet_text(text, "reports/fixture.md")
    assert errs, "base-only universal claim must fail"
    assert any("missing" in e or "FORBIDDEN" in e for e in errs)


def test_parent_closure_from_base_only_evidence_fails():
    """Guarded parent lane assigned a closed-class value without a full packet FAILS."""
    text = (
        "# Board\n"
        "Evidence: SPY QQQ IWM only.\n"
        "CARD_FIDELITY_OVERALL = PROVEN\n"
    )
    errs = check_packet_text(text, "reports/fixture.md")
    assert any("CARD_FIDELITY_OVERALL" in e and "closed-class" in e for e in errs)


def test_required_universality_fields_enforced():
    """UNIVERSAL_TICKER_AGNOSTIC_PROVEN without every required field FAILS."""
    fields = tuple(f for f in REQUIRED_PACKET_FIELDS if f != "GUEST_TICKER_PROOF")
    errs = check_packet_text(_proven_packet(fields=fields), "reports/fixture.md")
    assert any("GUEST_TICKER_PROOF" in e for e in errs)


def test_representative_without_downgrade_fails():
    """Representative-sample proof without downgrade language FAILS."""
    text = "# Packet\nRepresentative sample proven across three names.\n"
    errs = check_packet_text(text, "reports/fixture.md")
    assert any("REPRESENTATIVE_ONLY_NOT_PROVEN" in e for e in errs)


def test_production_ticker_literal_branch_fails():
    """A ticker-conditional branch in production logic FAILS the scan."""
    src = (
        "def score_card(ticker, probs):\n"
        "    if ticker == 'NVDA':\n"
        "        return probs * 2\n"
        "    return probs\n"
    )
    errs = scan_python_source_for_ticker_literals(src, "call_engine.py", allowlist={})
    assert len(errs) == 1 and "NVDA" in errs[0]


def test_unknown_classification_fails():
    text = "- UNIVERSALITY_CLASSIFICATION: TOTALLY_PROVEN_TRUST_ME\n"
    errs = check_packet_text(text, "reports/fixture.md")
    assert errs and "TOTALLY_PROVEN_TRUST_ME" in errs[0]


# ── PASS cases ────────────────────────────────────────────────────────────────


def test_base_anchor_evidenced_only_passes():
    """SPY/QQQ/IWM evidence labeled BASE_ANCHOR_EVIDENCED_ONLY PASSES."""
    text = (
        "# Packet\n"
        "Evidence: SPY, QQQ, IWM.\n"
        "- UNIVERSALITY_CLASSIFICATION: BASE_ANCHOR_EVIDENCED_ONLY\n"
        "CARD_FIDELITY_OVERALL = NOT_PROVEN\n"
    )
    assert check_packet_text(text, "reports/fixture.md") == []


def test_supported_universe_matrix_passes():
    """Fully-fielded universal packet with supported-universe evidence PASSES."""
    text = _proven_packet(extra="Universe matrix: SPY QQQ IWM NVDA TSLA PLTR CIFR all green.")
    assert check_packet_text(text, "reports/fixture.md") == []


def test_config_and_fixture_ticker_literals_pass():
    """Module-level config rosters and signature defaults PASS; test files exempt."""
    src = (
        "ROSTER = ('SPY', 'QQQ', 'IWM')\n"
        "DEFAULT_TICKER = 'SPY'\n"
        "def handler(ticker: str = 'SPY'):\n"
        "    return ticker\n"
    )
    assert scan_python_source_for_ticker_literals(src, "server.py", allowlist={}) == []
    # Test fixtures are exempt by surface, not by content.
    assert is_production_python("tests/test_anything.py") is False
    assert is_production_python("tools/check_universal_ticker_lock.py") is False
    assert is_production_python("verification/replay_diagnostic.py") is False
    assert is_production_python("server.py") is True
    assert is_production_python("call_engine.py") is True


def test_negative_board_values_never_match_closed_class():
    """NOT_PROVEN / QUEUED / HOLD / IN_PROGRESS board lines are always allowed."""
    text = (
        "CARD_FIDELITY_OVERALL = NOT_PROVEN\n"
        "MODEL_REAL_MONEY_EDGE = NOT_PROVEN\n"
        "UNIVERSAL_RUNTIME_LIVE_PROOF = NOT_PROVEN\n"
        "REAL_MONEY_READINESS = NOT_PROVEN\n"
    )
    assert check_packet_text(text, "reports/fixture.md") == []


def test_live_repo_passes_lock():
    """The tracked tree passes: allowlist covers exactly the verified legacy sites."""
    result = run_check()
    assert result["ok"], "\n".join(result["errors"])


def test_lock_constants_shape():
    assert BASE_ANCHOR_TICKERS == ("SPY", "QQQ", "IWM")
    assert len(UNIVERSALITY_CLASSIFICATIONS) == 5
    assert len(REQUIRED_PACKET_FIELDS) == 8


# ── REPO_WIDE_UNIVERSALITY_HARDGATE_V1 ────────────────────────────────────────

from tools.check_universal_ticker_lock import (  # noqa: E402
    REPO_REQUIRED_PACKET_FIELDS,
    REPO_UNIVERSALITY_CLASSIFICATIONS,
    UNIVERSE_DIMENSIONS,
)


def _repo_packet(classification: str, extra: str = "",
                 fields: tuple[str, ...] = REPO_REQUIRED_PACKET_FIELDS) -> str:
    body = "\n".join(f"- {f}: provided" for f in fields if f != "UNIVERSALITY_CLASSIFICATION")
    return f"# Packet\n{body}\n- UNIVERSALITY_CLASSIFICATION: {classification}\n{extra}\n"


# FAIL cases (mission item 7) ------------------------------------------------


def test_hardgate_base_ticker_proof_claiming_universal_closure_fails():
    text = "# Packet\nEvidence: SPY QQQ IWM.\nDeclaring universal closure of the quote lane.\n"
    errs = check_packet_text(text, "reports/fixture.md")
    assert any("universal claim" in e for e in errs)


def test_hardgate_one_route_proof_claiming_route_universal_fails():
    text = "# Packet\nProved /api/analytics/state only; claiming route-universal behavior.\n"
    errs = check_packet_text(text, "reports/fixture.md")
    assert any("universal claim" in e for e in errs)


def test_hardgate_one_card_horizon_proof_claiming_universal_fails():
    text = "# Packet\n1c card green; claiming horizon-universal card fidelity.\n"
    errs = check_packet_text(text, "reports/fixture.md")
    assert any("universal claim" in e for e in errs)


def test_hardgate_rth_only_proof_claiming_all_session_fails():
    text = "# Packet\nRTH sample only; asserting all-session closure.\n"
    errs = check_packet_text(text, "reports/fixture.md")
    assert any("universal claim" in e for e in errs)


def test_hardgate_child_slice_proof_closing_parent_lane_fails():
    text = (
        "# Packet\nChild slice ANCHOR_QUOTE_LANE_REFRESHER_V1 green.\n"
        "REAL_MONEY_READINESS = PROVEN\n"
    )
    errs = check_packet_text(text, "reports/fixture.md")
    assert any("REAL_MONEY_READINESS" in e and "closed-class" in e for e in errs)


def test_hardgate_missing_affected_universe_field_fails():
    fields = tuple(f for f in REPO_REQUIRED_PACKET_FIELDS if f != "AFFECTED_UNIVERSE_ENUMERATED")
    errs = check_packet_text(
        _repo_packet("UNIVERSAL_BEHAVIOR_PROVEN", fields=fields), "reports/fixture.md"
    )
    assert any("AFFECTED_UNIVERSE_ENUMERATED" in e for e in errs)


def test_hardgate_representative_only_without_downgrade_fails():
    text = "# Packet\nRepresentative route sample stands as universal proof.\n"
    errs = check_packet_text(text, "reports/fixture.md")
    assert any("REPRESENTATIVE_ONLY_NOT_PROVEN" in e for e in errs)


def test_hardgate_exception_without_operator_approval_fails():
    errs = check_packet_text(
        _repo_packet("EXCEPTION_APPROVED_WITH_SCOPE"), "reports/fixture.md"
    )
    assert any("operator approval" in e for e in errs)


# PASS cases (mission item 7) ------------------------------------------------


def test_hardgate_proper_subset_classification_passes():
    text = (
        "# Packet\nEvidence: one route, RTH only.\n"
        "- UNIVERSALITY_CLASSIFICATION: SUBSET_EVIDENCED_ONLY\n"
        "CARD_FIDELITY_OVERALL = NOT_PROVEN\n"
    )
    assert check_packet_text(text, "reports/fixture.md") == []


def test_hardgate_universal_by_construction_with_lock_passes():
    text = _repo_packet(
        "UNIVERSAL_BY_CONSTRUCTION_WITH_MECHANICAL_LOCK",
        extra="Universal closure holds by construction: keyed loop over the config roster.",
    )
    assert check_packet_text(text, "reports/fixture.md") == []


def test_hardgate_approved_exception_with_scope_passes():
    text = _repo_packet(
        "EXCEPTION_APPROVED_WITH_SCOPE",
        extra="Operator approved exception: $SPX chain excluded, scope limited to equities.",
    )
    assert check_packet_text(text, "reports/fixture.md") == []


def test_hardgate_complete_universe_matrix_passes():
    text = _repo_packet(
        "UNIVERSAL_BEHAVIOR_PROVEN",
        extra=(
            "AFFECTED_UNIVERSE_ENUMERATED covers tickers, routes, horizons, "
            "timeframes, session_states, cache keys, data sources, DB tables, "
            "model paths, trust states, failure modes.\n"
            "Universal closure proven across the enumerated matrix."
        ),
    )
    assert check_packet_text(text, "reports/fixture.md") == []


def test_hardgate_constants_shape():
    assert len(REPO_UNIVERSALITY_CLASSIFICATIONS) == 7
    assert len(REPO_REQUIRED_PACKET_FIELDS) == 8
    assert len(UNIVERSE_DIMENSIONS) == 13
