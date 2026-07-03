"""LIVE_UI_INTEGRITY_V1 — coherence headline, stack INVALID chip, lane-stale labels.

Mirrors client derivations in static/index.html (_refreshLiveUiIntegrityDerivations).
"""

from __future__ import annotations

import re
from pathlib import Path

import importlib.util
import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "static" / "index.html"
HARNESS = ROOT / "tools" / "run_universal_card_fidelity_runtime.py"

CARD_TRUST_REQUIRED_HORIZONS = ("1c", "5c", "15c", "60c")
CARD_TRUST_REQUIRED_HORIZON_COUNT = 4


def _load_harness_module():
    name = "run_universal_card_fidelity_runtime_for_live_ui_integrity"
    spec = importlib.util.spec_from_file_location(name, HARNESS)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_HARNESS = _load_harness_module()
analytics_card_trust_gate = _HARNESS.analytics_card_trust_gate
engine_tradeable_setup = _HARNESS.engine_tradeable_setup


def _full_trusted_card_payload(ticker: str = "SPY", **overrides) -> dict:
    base = {
        "ticker": ticker,
        "analytics_stale": False,
        "analytics_pending_shell": False,
        "analytics_refresh_in_progress": False,
        "analytics_partial_tier_c": False,
        "final_tradeable": True,
        "final_bias": "LONG",
        "entry_state": "confirmed",
        "fusion_available": True,
        "mhap_rows": [
            {"horizon": "1c", "call": "LONG", "confidence": 0.71},
            {"horizon": "5c", "call": "LONG", "confidence": 0.65},
            {"horizon": "15c", "call": "LONG", "confidence": 0.62},
            {"horizon": "60c", "call": "WAIT", "confidence": 0.50},
        ],
    }
    base.update(overrides)
    return base


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
    assert "_updateDbContentionChip()" in ae
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


# ── UI transport fidelity (audit/ui-realtime-transport-fidelity) ─────────────

from verification.ui_realtime_transport_audit import (
    audit_payload_metadata,
    audit_core_vs_guest_ticker_switching,
    compute_feed_state,
    is_duplicate_tier_c_payload,
    lane_stale_operator_label,
    parse_sqlite_contention_from_text,
    render_coherence_guard,
    should_discard_inflight_response,
    should_skip_tier_c_duplicate_render,
    simulate_switch_guard_matrix,
    snapshot_cache_restore_marks_stale,
    tier_c_card_render_fingerprint,
    ticker_switch_pair_kind,
    tier_c_payload_fingerprint,
)
from instrument_identity import ticker_storage_key


def test_render_coherence_guard_rejects_wrong_ticker():
    payload = {"ticker": "QQQ", "_server_build_ts": 1000.0, "decision_generation_id": 2}
    guard = render_coherence_guard(
        payload,
        active_ticker="SPY",
        last_render_timestamp=0,
        last_rendered_decision_gen=0,
    )
    assert guard.ok is False
    assert guard.reason == "ticker"


def test_render_coherence_guard_rejects_older_generation_id():
    payload = {"ticker": "SPY", "_server_build_ts": 2000.0, "decision_generation_id": 3}
    guard = render_coherence_guard(
        payload,
        active_ticker="SPY",
        last_render_timestamp=0,
        last_rendered_decision_gen=5,
    )
    assert guard.ok is False
    assert guard.reason == "gen"


def test_render_coherence_guard_accepts_newer_gen_when_ts_regresses():
    """Newer decision_generation_id may accept even if _server_build_ts regresses (Tier C cache)."""
    payload = {"ticker": "SPY", "_server_build_ts": 900.0, "decision_generation_id": 8}
    guard = render_coherence_guard(
        payload,
        active_ticker="SPY",
        last_render_timestamp=1000.0,
        last_rendered_decision_gen=7,
    )
    assert guard.ok is True


def test_should_discard_inflight_when_generation_superseded():
    discard, reason = should_discard_inflight_response(
        my_generation=2,
        request_generation=5,
        payload_ticker="SPY",
        active_ticker="SPY",
    )
    assert discard is True
    assert reason == "generation_superseded"


def test_should_discard_inflight_on_ticker_mismatch():
    discard, reason = should_discard_inflight_response(
        my_generation=5,
        request_generation=5,
        payload_ticker="IWM",
        active_ticker="SPY",
    )
    assert discard is True
    assert reason == "ticker_mismatch"


def test_ticker_switch_enters_analytics_loading_state_in_html():
    html = _html()
    fetch_fn = html.split("async function fetchState(")[1].split("async function pollStateFallback(")[0]
    assert "ANALYTICS" in fetch_fn
    assert "FETCHING" in fetch_fn
    assert "loading-overlay" in fetch_fn
    assert "willChange" in fetch_fn


def test_duplicate_tier_c_payload_fingerprint_detects_repeat():
    payload = {
        "ticker": "SPY",
        "decision_generation_id": 4,
        "_server_build_ts": 1710000000.0,
        "analytics_version": 12,
        "_update_source": "sse",
    }
    fp = tier_c_payload_fingerprint(payload)
    assert is_duplicate_tier_c_payload(payload, fp) is True
    assert is_duplicate_tier_c_payload(payload, None) is False


def test_compute_feed_state_stale_follows_age_rules():
    now_ms = 1_710_000_000_000
    stale = compute_feed_state(
        sse_phase="live",
        last_fast_ts=now_ms / 1000.0 - 45,
        now_ms=now_ms,
        plane_authority="streaming",
        plane_gen_ok=True,
        streaming_connected=True,
    )
    assert stale["state"] == "STALE"
    fresh = compute_feed_state(
        sse_phase="live",
        last_fast_ts=now_ms / 1000.0 - 1,
        now_ms=now_ms,
        plane_authority="streaming",
        plane_gen_ok=True,
        streaming_connected=True,
    )
    assert fresh["state"] == "LIVE"


def test_lane_stale_syncing_within_trust_window():
    now_ms = 1_710_000_000_000
    bundle_ts = now_ms / 1000.0 - 10
    label = lane_stale_operator_label(
        last_fast_ts=bundle_ts + 2,
        last_render_ts=bundle_ts,
        bundle_ts=bundle_ts,
        decision_generation_id=10,
        tier_c_painted_at_gen=5,
        pending_full_analytics=False,
        payload={
            "mhap_rows": [{"horizon": "1c", "call": "LONG"}],
            "analytics_refresh_in_progress": True,
        },
        now_ms=now_ms,
    )
    assert label["show"] is True
    assert label["label"] == "SYNCING ANALYTICS…"


def test_audit_payload_metadata_flags_missing_generation_id():
    meta = audit_payload_metadata({"ticker": "SPY", "_server_build_ts": 1.0}, tier="C")
    assert meta["complete"] is False
    assert "decision_generation_id" in meta["missing_fields"]


def test_rest_sse_metadata_contract_in_html_and_server():
    html = _html()
    server = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "decision_generation_id" in html
    assert "_server_build_ts" in html
    assert "_update_source" in html
    assert "decision_generation_id" in server or "_server_build_ts" in server


def test_sqlite_lock_event_counter_from_log_sample():
    sample = (
        "sqlite_tier1_lock_wait op=insert_snapshot ticker=SPY\n"
        "database is locked\n"
        "sqlite_tier1_busy_retry op=insert_snapshot\n"
    )
    counts = parse_sqlite_contention_from_text(sample)
    assert counts["sqlite_lock_wait_count"] == 1
    assert counts["sqlite_database_locked_count"] == 1
    assert counts["sqlite_busy_retry_count"] == 1


@pytest.mark.parametrize(
    "old_t,new_t,expected_pair",
    [
        ("SPY", "QQQ", "core_to_core"),
        ("SPY", "NVDA", "core_to_guest"),
        ("TSLA", "IWM", "guest_to_core"),
        ("NVDA", "AAPL", "guest_to_guest"),
    ],
)
def test_ticker_switch_pair_classification(old_t, new_t, expected_pair):
    assert ticker_switch_pair_kind(old_t, new_t) == expected_pair


@pytest.mark.parametrize(
    "old_t,new_t",
    [
        ("SPY", "QQQ"),
        ("SPY", "NVDA"),
        ("PLTR", "IWM"),
        ("NVDA", "TSLA"),
    ],
)
def test_wrong_ticker_payload_rejected_after_switch(old_t, new_t):
    result = simulate_switch_guard_matrix(old_t, new_t, stale_payload_ticker=old_t)
    assert result["wrong_ticker_discarded"] is True
    assert result["wrong_ticker_discard_reason"] == "ticker_mismatch"


def test_guest_stale_cache_restore_only_with_degraded_markers():
    cached = {
        "ticker": "NVDA",
        "mhap_rows": [{"horizon": "1c", "call": "LONG"}],
        "analytics_stale": False,
    }
    restored = snapshot_cache_restore_marks_stale(cached)
    assert restored["analytics_stale"] is True
    assert restored["analytics_refresh_in_progress"] is True
    assert restored["_update_source"] == "client_ticker_cache"
    assert restored["analytics_pending_shell"] is False


def test_special_index_ticker_storage_keys():
    assert ticker_storage_key("SPX") == "$SPX"
    assert ticker_storage_key("$SPX") == "$SPX"
    assert ticker_storage_key("$VIX") == "$VIX"
    assert ticker_storage_key("VIX") == "$VIX"


def test_core_vs_guest_audit_reports_tier_agnostic_guards():
    audit = audit_core_vs_guest_ticker_switching()
    assert audit["transport_guards_tier_agnostic"] is True
    assert audit["wrong_ticker_discarded_all_pairs"] is True
    assert audit["cache_restore_stale_all_pairs"] is True
    assert "SPY" in audit["core_tickers"]
    assert "NVDA" in audit["guest_sample_tickers"]
    assert "21" in audit["question_21_answer"] or "tier-agnostic" in audit["question_21_answer"]


def test_set_active_ticker_does_not_branch_on_base_tier_in_html():
    html = _html()
    body = html.split("function setActiveTicker(")[1].split("function _scheduleServerAnalyticsWarm")[0]
    assert "is_base_money_path" not in body
    assert "is_guest_ticker" not in body


def _sample_tier_c_payload(**overrides):
    base = {
        "ticker": "SPY",
        "decision_generation_id": 5,
        "_server_build_ts": 1_710_000_000.0,
        "analytics_version": 12,
        "analytics_stale": False,
        "analytics_refresh_in_progress": False,
        "analytics_pending_shell": False,
        "final_bias": "LONG",
        "entry_state": "watching",
        "validation_passed": False,
        "wait_reason": "tape stack disagrees",
        "mhap_rows": [
            {"horizon": "1c", "call": "LONG", "confidence": 0.71},
            {"horizon": "5c", "call": "LONG", "confidence": 0.65},
        ],
        "horizon_prob_bars": {"1m": {"up": 0.2, "down": 0.6, "flat": 0.2}},
        "_update_source": "sse",
    }
    base.update(overrides)
    return base


def test_duplicate_tier_c_payload_skips_redundant_render():
    payload = _sample_tier_c_payload()
    fp = tier_c_card_render_fingerprint(payload)
    skip, reason = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=fp,
        last_scope=("SPY", 3),
    )
    assert skip is True
    assert reason == "duplicate_fingerprint"


def test_changed_decision_generation_id_triggers_render():
    payload = _sample_tier_c_payload(decision_generation_id=6)
    prev = tier_c_card_render_fingerprint(_sample_tier_c_payload(decision_generation_id=5))
    skip, _ = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=prev,
        last_scope=("SPY", 3),
    )
    assert skip is False


def test_changed_ticker_scope_resets_dedup():
    payload = _sample_tier_c_payload(ticker="NVDA")
    fp = tier_c_card_render_fingerprint(payload)
    skip, reason = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="NVDA",
        request_generation=4,
        last_fingerprint=fp,
        last_scope=("SPY", 3),
    )
    assert skip is False
    assert reason == "scope_changed"


def test_changed_stale_flag_triggers_render():
    payload = _sample_tier_c_payload(analytics_stale=True)
    prev = tier_c_card_render_fingerprint(_sample_tier_c_payload(analytics_stale=False))
    skip, _ = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=prev,
        last_scope=("SPY", 3),
    )
    assert skip is False


def test_changed_mhap_direction_triggers_render():
    payload = _sample_tier_c_payload(
        mhap_rows=[{"horizon": "1c", "call": "SHORT", "confidence": 0.71}],
    )
    prev = tier_c_card_render_fingerprint(_sample_tier_c_payload())
    skip, _ = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=prev,
        last_scope=("SPY", 3),
    )
    assert skip is False


def test_wrong_ticker_rejected_before_dedup_helper():
    payload = _sample_tier_c_payload(ticker="QQQ")
    guard = render_coherence_guard(payload, active_ticker="SPY")
    assert guard.ok is False
    skip, reason = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker="SPY",
        request_generation=3,
        last_fingerprint=tier_c_card_render_fingerprint(payload),
        last_scope=("SPY", 3),
    )
    assert skip is False
    assert reason == "wrong_ticker"


@pytest.mark.parametrize("ticker", ["SPY", "NVDA", "PLTR", "VIX"])
def test_core_and_guest_share_tier_c_dedup_rules(ticker):
    payload = _sample_tier_c_payload(ticker=ticker)
    fp = tier_c_card_render_fingerprint(payload)
    skip, _ = should_skip_tier_c_duplicate_render(
        payload,
        active_ticker=ticker,
        request_generation=1,
        last_fingerprint=fp,
        last_scope=(ticker.upper(), 1),
    )
    assert skip is True


def test_index_html_tier_c_dedup_hooks_present():
    html = _html()
    assert "function _tierCCardRenderFingerprint(" in html
    assert "function _shouldSkipTierCCardRender(" in html
    assert "function _resetTierCCardRenderDedup(" in html
    assert "function _commitTierCCardRenderFingerprint(" in html
    assert "_shouldSkipTierCCardRender(d)" in html
    assert "_resetTierCCardRenderDedup()" in html.split("function setActiveTicker(")[1]
    assert "window._tierCCardRenderFingerprint = _tierCCardRenderFingerprint" in html


def test_db_contention_operator_dom_and_client_hooks():
    html = _html()
    assert 'id="ub-pill-db"' in html
    assert 'id="dr-db-contention-chip"' in html
    assert "function paintDbContentionPill(" in html
    assert "function pollDbContentionDiagnostics(" in html
    assert "function startDbContentionPoll(" in html
    assert "/api/diagnostics/sqlite-contention" in html
    assert "not a model verdict" in html.lower()
    paint_body = html.split("function paintDbContentionPill(")[1].split("let _dbContentionPollTid")[0]
    assert "mhap_rows" not in paint_body
    assert "final_bias" not in paint_body


def test_db_degraded_coexists_with_lane_stale_integrity():
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    _now = 1_700_000_100.0
    db = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 1,
            "sqlite_lock_wait_max_ms": 150.0,
            "recent_events": [
                {"kind": "lock_wait", "wait_ms": 150.0, "ts_utc": _now - 10.0}
            ],
        },
        now_utc=_now,
    )
    integrity = _derive_integrity(
        last_fast_ts=100.0,
        last_render_ts=50.0,
        bundle_ts=40.0,
        decision_generation_id=5,
        tier_c_painted_at_gen=3,
        pending_full_analytics=True,
        stack_mode="OK",
    )
    assert db["show"] is True
    assert _lane_stale_chip_label(integrity) is not None


def test_core_and_guest_share_db_contention_surface_attach():
    import copy

    from server import _attach_db_contention_operator_surface

    for ticker in ("SPY", "NVDA"):
        ms = {"ticker": ticker, "mhap_rows": [{"horizon": "1c", "call": "LONG"}]}
        before = copy.deepcopy(ms)
        _attach_db_contention_operator_surface(ms)
        assert ms["mhap_rows"] == before["mhap_rows"]
        op = ms["db_contention_operator"]
        assert op["diagnostics_source"] == "/api/diagnostics/sqlite-contention"
        assert "state" in op


def test_switch_operator_states_dom_and_hooks():
    html = _html()
    assert 'id="dr-switch-state-chip"' in html
    assert "function deriveSwitchOperatorState(" in html
    assert "function paintSwitchStateChip(" in html
    assert "GUEST DATA WARMING" in html
    assert "wrong_ticker_payload_rejected_count" in html
    assert "stale_generation_payload_rejected_count" in html
    paint_body = html.split("function paintSwitchStateChip(")[1].split("function _bumpSwitchDiagRejection")[0]
    assert "mhap_rows" not in paint_body
    assert "final_bias" not in paint_body


@pytest.mark.parametrize(
    "pair,expected_kind",
    [
        (("SPY", "QQQ"), "core_to_core"),
        (("SPY", "NVDA"), "core_to_guest"),
        (("PLTR", "IWM"), "guest_to_core"),
        (("NVDA", "TSLA"), "guest_to_guest"),
    ],
)
def test_switch_timing_diag_pair_classification(pair, expected_kind):
    from verification.ui_realtime_transport_audit import (
        enrich_switch_diag_record,
        ticker_switch_pair_kind,
    )

    old_t, new_t = pair
    assert ticker_switch_pair_kind(old_t, new_t) == expected_kind
    rec = enrich_switch_diag_record(
        {
            "old_ticker": old_t,
            "new_ticker": new_t,
            "request_generation": 7,
            "client_wall_start_ms": 1_710_000_000_000,
            "first_quote_ms": 120.0,
            "first_full_state_ms": 800.0,
            "cards_first_render_ms": 900.0,
        }
    )
    assert rec["pair_kind"] == expected_kind
    assert rec["is_core"] == (new_t in ("SPY", "QQQ", "IWM"))
    assert rec["is_guest"] == (new_t not in ("SPY", "QQQ", "IWM"))
    assert rec["fast_quote_first_seen_ms"] == 120.0
    assert rec["tier_c_first_seen_ms"] == 800.0


def test_special_index_switch_storage_key_in_diag():
    from verification.ui_realtime_transport_audit import (
        enrich_switch_diag_record,
        is_special_index_ticker,
    )

    assert is_special_index_ticker("SPX") is True
    assert is_special_index_ticker("$VIX") is True
    rec = enrich_switch_diag_record({"old_ticker": "SPY", "new_ticker": "$VIX"})
    assert rec["is_special_index"] is True
    assert rec["storage_key"] == "$VIX"
    assert rec["selected_ticker"] == "$VIX"


def test_wrong_ticker_and_stale_generation_rejection_counted():
    from verification.ui_realtime_transport_audit import simulate_switch_guard_matrix

    wrong = simulate_switch_guard_matrix("SPY", "NVDA", stale_payload_ticker="SPY")
    assert wrong["wrong_ticker_payload_rejected_count"] == 1
    assert wrong["stale_generation_payload_rejected_count"] == 1


def test_no_contention_switch_operator_ok_state():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": False,
            "db_contention_state_at_switch": "OK",
            "stale_cache_restored": False,
            "analytics_pending": False,
            "cards_first_render_ms": 500.0,
        }
    )
    assert op["state"] == "READY"
    assert op["show"] is False


def test_guest_stale_cache_switch_state():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": True,
            "stale_cache_restored": True,
            "db_contention_state_at_switch": "OK",
            "analytics_pending": False,
        }
    )
    assert op["state"] == "CACHE STALE — REFRESHING"


def test_guest_incomplete_switch_state():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": True,
            "guest_incomplete_reason": "guest_mhap_missing",
            "db_contention_state_at_switch": "OK",
        }
    )
    assert op["state"] == "GUEST DATA INCOMPLETE"


def test_db_degraded_coexists_with_switch_pending():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": True,
            "db_contention_state_at_switch": "DB_DEGRADED",
            "analytics_pending": True,
            "analytics_light_first_seen_ms": None,
        }
    )
    assert op["state"] == "DB DEGRADED — CARDS MAY LAG"


def test_switch_operator_state_does_not_imply_model_wrong():
    from verification.ui_realtime_transport_audit import derive_switch_operator_state

    op = derive_switch_operator_state(
        {
            "is_guest": False,
            "analytics_pending": True,
            "analytics_light_first_seen_ms": 100.0,
        }
    )
    msg = (op.get("operator_message") or "").lower()
    assert "not a model verdict" in msg
    assert op["state"] == "ANALYTICS PENDING"


def test_guest_switch_sla_report_classifications():
    from verification.ui_realtime_transport_audit import (
        GUEST_SWITCH_SLA_CLASSIFICATIONS,
        build_guest_switch_sla_report,
    )

    report = build_guest_switch_sla_report(audit_date="2026-06-18")
    for tag in report.get("classifications", []):
        assert tag in GUEST_SWITCH_SLA_CLASSIFICATIONS
    assert "GUEST_COLD_START_UX_GAP_FIXED" in report["classifications"]
    assert "LIVE_GUEST_SLA_NOT_PROVEN" in report["classifications"]


@pytest.mark.parametrize("ticker", ["SPY", "QQQ", "IWM"])
def test_analytics_stale_suppresses_engine_tradeable_setup(ticker):
    payload = _full_trusted_card_payload(ticker, analytics_stale=True)
    assert analytics_card_trust_gate(payload, active_ticker=ticker)["trusted"] is False
    assert engine_tradeable_setup(payload) is False


@pytest.mark.parametrize("ticker", ["SPY", "QQQ", "IWM"])
def test_pending_shell_suppresses_engine_tradeable_setup(ticker):
    payload = _full_trusted_card_payload(ticker, analytics_pending_shell=True)
    assert analytics_card_trust_gate(payload, active_ticker=ticker)["trusted"] is False
    assert engine_tradeable_setup(payload) is False


@pytest.mark.parametrize("ticker", ["SPY", "QQQ", "IWM"])
def test_cache_restore_stale_suppresses_engine_tradeable_setup(ticker):
    cached = _full_trusted_card_payload(ticker, analytics_stale=False)
    restored = snapshot_cache_restore_marks_stale(cached)
    assert restored["analytics_stale"] is True
    assert analytics_card_trust_gate(restored, active_ticker=ticker)["trusted"] is False
    assert engine_tradeable_setup(restored) is False


@pytest.mark.parametrize("ticker", ["SPY", "QQQ", "IWM"])
def test_partial_mhap_suppresses_engine_tradeable_setup(ticker):
    payload = _full_trusted_card_payload(
        ticker,
        mhap_rows=[
            {"horizon": "1c", "call": "LONG", "confidence": 0.71},
            {"horizon": "5c", "call": "LONG", "confidence": 0.65},
        ],
    )
    assert analytics_card_trust_gate(payload, active_ticker=ticker)["trusted"] is False
    assert engine_tradeable_setup(payload) is False


@pytest.mark.parametrize("ticker", ["SPY", "QQQ", "IWM"])
def test_ticker_mismatch_fails_card_trust_gate(ticker):
    payload = _full_trusted_card_payload(ticker)
    result = analytics_card_trust_gate(payload, active_ticker="OTHER")
    assert result["trusted"] is False
    assert result["reason"] == "ticker_mismatch"


@pytest.mark.parametrize("ticker", ["SPY", "QQQ", "IWM"])
def test_trusted_full_payload_passes_card_trust_gate(ticker):
    payload = _full_trusted_card_payload(ticker)
    result = analytics_card_trust_gate(payload, active_ticker=ticker)
    assert result["trusted"] is True
    assert engine_tradeable_setup(payload) is True


def test_fusion_unavailable_fails_card_trust_gate():
    payload = _full_trusted_card_payload("SPY", fusion_available=False)
    assert analytics_card_trust_gate(payload, active_ticker="SPY")["trusted"] is False
    assert analytics_card_trust_gate(payload, active_ticker="SPY")["reason"] == "fusion_unavailable"


def test_wrong_ticker_render_coherence_guard_blocks_before_card_paint():
    payload = _full_trusted_card_payload("QQQ")
    guard = render_coherence_guard(payload, active_ticker="SPY")
    assert guard.ok is False
    assert guard.reason == "ticker"
    assert analytics_card_trust_gate(payload, active_ticker="SPY")["trusted"] is False


def test_index_html_exports_card_trust_gate_helpers():
    html = _html()
    assert "window.analyticsCardTrustGate = analyticsCardTrustGate" in html
    assert "window.engineTradeableSetup = engineTradeableSetup" in html
    assert "window.paintUntrustedTimeframeCardRow = paintUntrustedTimeframeCardRow" in html
    assert "window.render = render" in html


def test_quote_plane_hypothetical_fields_do_not_affect_card_trust_gate():
    """Even if plane keys appear on ms_dict, card trust ignores them (not gate inputs)."""
    payload = _full_trusted_card_payload("SPY")
    payload["plane_quote_authority"] = "rest_fallback_explicit"
    payload["streaming_fallback_explicit"] = True
    payload["rest_fallback_explicit"] = True
    assert analytics_card_trust_gate(payload, active_ticker="SPY")["trusted"] is True
    assert engine_tradeable_setup(payload) is True


def test_syncing_non_cache_refresh_in_progress_still_passes_card_trust_gate():
    """Server refresh without client cache restore: last trusted bundle may paint (SYNCING)."""
    payload = _full_trusted_card_payload(
        "SPY",
        analytics_refresh_in_progress=True,
        analytics_stale=False,
        _update_source="sse_tier_c",
    )
    gate = analytics_card_trust_gate(payload, active_ticker="SPY")
    assert gate["trusted"] is True
    assert engine_tradeable_setup(payload) is True


def test_client_ticker_cache_refresh_fail_closed_vs_syncing_non_cache():
    cached = _full_trusted_card_payload("SPY", analytics_stale=False)
    restored = snapshot_cache_restore_marks_stale(cached)
    assert analytics_card_trust_gate(restored, active_ticker="SPY")["trusted"] is False
    syncing = _full_trusted_card_payload(
        "SPY",
        analytics_refresh_in_progress=True,
        analytics_stale=False,
        _update_source="sse_tier_c",
    )
    assert analytics_card_trust_gate(syncing, active_ticker="SPY")["trusted"] is True
