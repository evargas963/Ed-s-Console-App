"""LIVE_UI_INTEGRITY_V1 — coherence headline, stack INVALID chip, lane-stale labels.

Mirrors client derivations in static/index.html (_refreshLiveUiIntegrityDerivations).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "static" / "index.html"


def _html() -> str:
    return INDEX.read_text(encoding="utf-8", errors="replace")


def _derive_integrity(
    *,
    last_fast_ts: float,
    last_render_ts: float,
    bundle_ts: float,
    decision_generation_id: int | None,
    tier_c_painted_at_gen: int,
    pending_full_analytics: bool,
    stack_mode: str,
) -> dict:
    """Keep aligned with _refreshLiveUiIntegrityDerivations in index.html."""
    quote_ahead = last_fast_ts > 0 and last_render_ts > 0 and last_fast_ts > last_render_ts
    gen = decision_generation_id
    gen_stale = gen is not None and gen > tier_c_painted_at_gen
    slow_stale_vs_fast = bundle_ts > 0 and last_fast_ts > 0 and bundle_ts < last_fast_ts
    return {
        "quoteAhead": quote_ahead,
        "pending": pending_full_analytics,
        "genStale": gen_stale,
        "slowStaleVsFast": slow_stale_vs_fast,
        "stackMode": stack_mode.upper(),
        "gen": gen,
    }


def _stack_mode_chip_label(integrity: dict) -> str | None:
    if integrity["stackMode"] == "INVALID":
        return "STACK INVALID (fusion/MC prerequisites)"
    return None


def _lane_stale_chip_label(integrity: dict) -> str | None:
    if integrity["genStale"]:
        return "LANE STALE — CARDS PAINTING…"
    if integrity["quoteAhead"] or integrity["slowStaleVsFast"]:
        return "LANE STALE — QUOTE AHEAD"
    if integrity["pending"]:
        return "LANE STALE — PENDING ANALYTICS"
    return None


def _freshness_pill_suffix(integrity: dict) -> str:
    return " · PRICE AHEAD" if integrity["slowStaleVsFast"] else ""


def test_index_html_live_ui_integrity_dom_and_hook():
    html = _html()
    assert 'id="coherence-headline"' in html
    assert 'id="dr-stack-mode-chip"' in html
    assert 'id="dr-lane-stale-chip"' in html
    assert "function _refreshLiveUiIntegrityDerivations(" in html
    assert "function _updateCoherenceHeadline(" in html
    assert "function _updateStackModeChip(" in html
    assert "function _updateLaneStaleChip(" in html
    ae = html.split("function _updateLiveUiAe(")[1].split("function _fastRolloutBump(")[0]
    assert "_updateCoherenceHeadline(integrity)" in ae
    assert "_updateStackModeChip(integrity)" in ae
    assert "_updateLaneStaleChip(integrity)" in ae
    assert "_refreshLiveUiIntegrityDerivations(opts)" in ae


def test_stack_mode_invalid_renders_dedicated_chip():
    html = _html()
    integrity = _derive_integrity(
        last_fast_ts=0,
        last_render_ts=0,
        bundle_ts=0,
        decision_generation_id=1,
        tier_c_painted_at_gen=1,
        pending_full_analytics=False,
        stack_mode="INVALID",
    )
    label = _stack_mode_chip_label(integrity)
    assert label == "STACK INVALID (fusion/MC prerequisites)"
    assert "STACK INVALID (fusion/MC prerequisites)" in html
    assert 'id="dr-stack-mode-chip"' in html
    trust = html.split("domIf('dr-trust-stack'")[1].split("domIf('dr-trust-policy'")[0]
    assert "stack_mode" not in trust
    assert "d.active_compliant" in html
    assert "OK (active artifacts compliant)" in trust


def test_coherence_headline_shows_quote_and_bundle_ages():
    html = _html()
    assert "function _updateCoherenceHeadline(" in html
    assert "Quote ' + quoteAge + ' · Bundle ' + bundleAge" in html
    assert "function _formatLaneAgeSec(" in html


def test_price_ahead_suffix_when_slow_stale_vs_fast():
    html = _html()
    integrity = _derive_integrity(
        last_fast_ts=1000.0,
        last_render_ts=900.0,
        bundle_ts=980.0,
        decision_generation_id=5,
        tier_c_painted_at_gen=5,
        pending_full_analytics=False,
        stack_mode="FULL",
    )
    assert integrity["slowStaleVsFast"] is True
    assert _freshness_pill_suffix(integrity) == " · PRICE AHEAD"
    assert "window._priceAheadOfBundle = slowStaleVsFast" in html
    assert "pillText += ' · PRICE AHEAD'" in html


def test_lane_stale_chip_quote_ahead_vs_cards_painting():
    html = _html()
    quote = _derive_integrity(
        last_fast_ts=2000.0,
        last_render_ts=1000.0,
        bundle_ts=1000.0,
        decision_generation_id=3,
        tier_c_painted_at_gen=3,
        pending_full_analytics=False,
        stack_mode="FULL",
    )
    assert _lane_stale_chip_label(quote) == "LANE STALE — QUOTE AHEAD"
    assert "LANE STALE — QUOTE AHEAD" in html

    gen = _derive_integrity(
        last_fast_ts=1000.0,
        last_render_ts=1000.0,
        bundle_ts=1000.0,
        decision_generation_id=10,
        tier_c_painted_at_gen=5,
        pending_full_analytics=False,
        stack_mode="FULL",
    )
    assert _lane_stale_chip_label(gen) == "LANE STALE — CARDS PAINTING…"
    assert "LANE STALE — CARDS PAINTING…" in html


def test_invalid_chip_persists_when_liveready_false_for_other_reasons():
    html = _html()
    chip_fn = html.split("function _updateStackModeChip(")[1].split("function _updateLaneStaleChip(")[0]
    assert "validation_passed" not in chip_fn
    assert "liveReady" not in chip_fn
    integrity = _derive_integrity(
        last_fast_ts=0,
        last_render_ts=0,
        bundle_ts=0,
        decision_generation_id=None,
        tier_c_painted_at_gen=0,
        pending_full_analytics=False,
        stack_mode="INVALID",
    )
    assert _stack_mode_chip_label(integrity) is not None


def test_dr_trust_stack_compliance_semantic_preserved():
    html = _html()
    trust = html.split("domIf('dr-trust-stack'")[1].split("domIf('dr-trust-policy'")[0]
    assert "d.active_compliant" in html
    assert "OK (active artifacts compliant)" in trust
    assert "stack_runtime" not in trust


def test_coherence_updaters_only_invoked_from_live_ui_ae():
    html = _html()
    assert len(re.findall(r"function _updateLiveUiAe\(", html)) == 1
    ae = html.split("function _updateLiveUiAe(")[1].split("function _fastRolloutBump(")[0]
    for fn in (
        "_updateCoherenceHeadline",
        "_updateStackModeChip",
        "_updateSignalsEngineFailChip",
        "_updateLaneStaleChip",
        "_updateStackIntegrityDegradedChip",
        "_updateMhPromotionChip",
        "_updateSessionBoundaryChip",
    ):
        assert ae.count(fn + "(integrity)") == 1


def test_live_ui_b_stack_integrity_degraded_chip():
    html = _html()
    assert 'id="dr-stack-integrity-degraded-chip"' in html
    assert "stack_integrity_v1" in html
    assert "stackIntegrityDegraded" in html
    assert "function _updateStackIntegrityDegradedChip(" in html
    assert "STACK DEGRADED" in html


def test_live_ui_e_mh_promotion_chip():
    html = _html()
    assert 'id="dr-mh-promotion-chip"' in html
    assert "mh_promoted_directional" in html
    assert "function _updateMhPromotionChip(" in html
    assert "MH PROMOTED" in html


def test_live_ui_g_session_boundary_chip():
    html = _html()
    assert 'id="dr-session-boundary-chip"' in html
    assert "sessionBoundaryWarning" in html
    assert "time_warning" in html
    assert "function _updateSessionBoundaryChip(" in html


def test_parse_conf_withholds_null_not_zero():
    html = _html()
    assert "return null" in html.split("function parseConf(")[1].split("function horizonRowMissing")[0]
    assert "confPct == null" in html
    assert "confidence withheld" in html
