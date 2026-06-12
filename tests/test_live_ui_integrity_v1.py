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
    """Operator 2026-06-10: the Readiness/trust rail block (dr-trust-*) was
    retired — duplicative with the header chips (FRESH / STACK / SIGNALS /
    STACK DEGRADED) and the signal-chain bar. Negative lock: the block and its
    painters must stay removed; the dedicated stack-mode chip remains the
    stack-health surface and stays independent of artifact compliance."""
    html = _html()
    for retired in ("dr-trust-live", "dr-trust-fresh", "dr-trust-stack",
                    "dr-trust-policy", "dr-trust-edge", "dr-trust-block"):
        assert retired not in html, f"{retired} must stay removed (retired rail block)"
    assert 'id="dr-stack-mode-chip"' in html


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


def test_live_ui_a_no_canonical_probability_reads_in_js():
    """LIVE-UI-A: lock the clean JS state — no consumer in static/index.html may read
    canonical.probability_up / probability_down / probability_flat from the Tier C payload
    without provenance gating. Today there are zero such reads (verified path-only); this
    test prevents a future regression that adds a fake-0.333 surface by binding a card to
    these placeholder fields. Provenance-gated reads (canonical_provenance, fusion_active
    via isFusionAuthoritative) remain allowed.
    """
    html = _html()
    # Direct JS attribute access patterns that would leak placeholder probs.
    for pat in (
        "canonical.probability_up",
        "canonical.probability_down",
        "canonical.probability_flat",
        ".canonical_forecast.probability_up",
        ".canonical_forecast.probability_down",
        ".canonical_forecast.probability_flat",
    ):
        assert pat not in html, (
            f"LIVE-UI-A regression: JS now reads {pat!r} — placeholder 1/3-each triplets "
            "for non-tradable canonicals would leak as a real prob. Gate on "
            "isFusionAuthoritative(d) / canonical_provenance, or use a provenance-aware helper."
        )


def test_live_ui_d_horizon_bias_discriminates_withhold_reason():
    """LIVE-UI-D: per-horizon Bias cell must render distinct labels for tri-state withhold
    sources (min_samples / no_data / data_quality / loading) instead of a single uniform
    WAIT bucket. Producer (prediction_engine._pack_horizon_row) stamps emp.withhold_reason;
    UI reads and maps to operator-visible labels with hover-titles explaining the reason.
    """
    html = _html()
    # Helper function must exist and discriminate the documented reason codes.
    assert "const biasFromEmp = (emp) =>" in html, "biasFromEmp helper missing"
    helper_idx = html.index("const biasFromEmp = (emp) =>")
    helper_end = html.index("\n    };", helper_idx) + 6
    helper_body = html[helper_idx:helper_end]
    # All four reason buckets must be handled distinctly.
    assert "'min_samples'" in helper_body, "min_samples branch missing"
    assert "'no_data'" in helper_body, "no_data branch missing"
    assert "'data_quality'" in helper_body, "data_quality branch missing"
    # Distinct operator-visible labels for each withhold bucket.
    assert "'WITHHELD'" in helper_body, "WITHHELD label missing"
    assert "'NO DATA'" in helper_body, "NO DATA label missing"
    assert "'LOADING'" in helper_body, "LOADING fallback label missing"
    # When probs ARE present, helper must return LONG/SHORT/FLAT (real verdict),
    # never falling through to the withhold path.
    assert "'LONG'" in helper_body and "'SHORT'" in helper_body and "'FLAT'" in helper_body


def test_live_ui_d_bias_kv_passes_cls_and_title_for_withhold_reason():
    """LIVE-UI-D: the per-horizon Bias addKV call must thread the metadata object so the
    DOM cell carries the discriminator class + tooltip — otherwise the operator sees
    'WITHHELD' but cannot tell which reason fired."""
    html = _html()
    # The addKV signature must accept opts (cls + title) and apply them.
    addkv_idx = html.index("const addKV = (grid, k, v, opts) =>")
    addkv_body = html[addkv_idx : html.index("\n    };", addkv_idx)]
    assert "opts.cls" in addkv_body, "addKV must apply opts.cls to the value cell"
    assert "opts.title" in addkv_body, "addKV must apply opts.title to the value cell"
    # The Bias call site must pass the bm (biasMeta) object.
    assert "addKV(grid, 'Bias', biasHz, { cls: bm.cls, title: bm.title })" in html, (
        "Bias addKV call must pass bm.cls + bm.title — without this the discriminator is dropped"
    )


def test_live_ui_d_horizon_confidence_discriminates_missing_row():
    """LIVE-UI-D sibling sweep: Horizon Confidence cell must distinguish 'missing assessment'
    from 'present but null' — without this discriminator the operator sees '—' identically
    for both states and can't tell whether to wait or whether the horizon is structurally
    absent. Producer: market_state.build_market_state stamps row.missing + row.row_state
    for missing assessments (mhap None fix @ beeb16e).
    """
    html = _html()
    # The Horizon Confidence render must thread metadata (confMHMeta) for discrimination.
    assert "addKV(grid, 'Horizon Confidence', confMH, confMHMeta)" in html, (
        "Horizon Confidence cell must pass confMHMeta — otherwise missing-row reason is dropped"
    )
    # confMHMeta must discriminate the three states: present / missing-row / loading.
    meta_idx = html.index("const confMHMeta = _confPresent")
    meta_end = html.index(";", meta_idx)
    meta_body = html[meta_idx:meta_end]
    assert "Per-horizon supporting assessment confidence" in meta_body, "present-state tooltip missing"
    assert "Horizon assessment missing" in meta_body, "missing-row tooltip missing"
    assert "Horizon confidence not yet stamped" in meta_body or "No horizon row" in meta_body, (
        "loading-state tooltip missing"
    )
    # The discriminator class must use bias-withheld for missing-row (matches Bias-cell
    # withhold styling for visual consistency across the sibling cells).
    assert "bias-withheld" in meta_body, "missing-row branch must apply bias-withheld class"


def test_live_ui_a_no_dominant_prob_renders_in_js():
    """LIVE-UI-A: market_state.py L1541-1556 was previously stamping placeholder 0.3333
    into ms.dominant_prob for non-tradable canonicals. The producer is now gated. This
    JS-side lock ensures no operator-visible surface renders dominant_prob as a number —
    if a future card binds it, the test fires until the consumer adds a withhold check.
    """
    html = _html()
    # dominant_dir (direction string) IS read at effectiveDirection — that's fine,
    # producer convention sets it to "flat" for non-tradable (fail-closed display).
    # dominant_prob (the numeric placeholder) must not be rendered as a real value.
    for pat in (
        "d.dominant_prob",
        ".dominant_prob",
        "dominantProb",
    ):
        assert pat not in html, (
            f"LIVE-UI-A regression: JS now reads {pat!r} — even with the market_state gate, "
            "this binding would render '0' or empty for withheld (None) values without an "
            "explicit withhold helper. Add a withhold check or use a provenance-aware accessor."
        )
