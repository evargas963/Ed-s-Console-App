from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARD_CONSUMER_CONTRACT = ROOT / "governance" / "artifacts" / "CARD_CONSUMER_CONTRACT_V1.json"
CARD_TRUST_CONTRACT = ROOT / "docs" / "CARD_TRUST_CONTRACT.md"


def _html() -> str:
    p = Path(__file__).resolve().parent.parent / "static" / "index.html"
    return p.read_text(encoding="utf-8", errors="replace")


# Issue 18 UI contract was authored against the original "THE CALL" card + explicit
# renderMultiHorizon() + mh-call-entry naming. The UI was refactored in commit 65e7d55
# ("chore: Phase B dead-code cleanup") + later commits to the current Decision Rail
# naming. Each assertion below now exercises the EQUIVALENT current element.


def test_the_call_card_title_present():
    """Call card now uses ``.tf-signal-card`` styling (replaced the explicit 'THE CALL' title).

    The card exists if ``.tf-signal-card`` CSS class is defined AND ``tf-signal-<slug>``
    rendering elements are referenced — the visual "Call card" is now derived from the
    primary-horizon mhap row via this styling.
    """
    h = _html()
    assert ".tf-signal-card" in h, "Call-card CSS class .tf-signal-card not present"
    assert "tf-signal-" in h, "tf-signal-<slug> rendering pattern not present"


def test_mhap_card_present_with_required_columns():
    """Operator 2026-06-10: the rail Horizon-alignment block (dr-align-*) was
    retired — duplicative with the horizon pills, which carry per-horizon
    direction + confidence (and the ALL pill the ALIGNED/SPLIT tag)."""
    h = _html()
    assert "Horizon alignment" not in h
    for el_id in ("dr-align-1m", "dr-align-5m", "dr-align-15m", "dr-align-60m", "dr-align-class-chip"):
        assert el_id not in h, f"{el_id} must stay removed (duplicative rail block)"
    # The pills remain the per-horizon surface.
    for el_id in ("tf-signal-1c", "tf-signal-5c", "tf-signal-15c", "tf-signal-60c"):
        assert f'id="{el_id}"' in h


def test_horizon_stack_exec_card_removed_negative_lock():
    """Operator 2026-06-11: Horizon Stack exec-card retired — duplicated mhap_rows
    on the pills and mislabeled all-WAIT as 'Mixed stack'. Same delete+lock pattern
    as dr-align-* (2026-06-10); alignment still surfaces on ALL via deriveTag."""
    h = _html()
    assert 'id="horizon-stack-card"' not in h
    for el_id in ("hs-1m", "hs-5m", "hs-15m", "hs-60m", "hs-summary"):
        assert el_id not in h, f"{el_id} must stay removed (duplicative exec card)"
    assert "function hsLine" not in h
    assert "alignClsUi" not in h
    assert "Mixed stack, confirmation needed" not in h
    assert "Mixed stack, no clean continuation" not in h
    # ALL pill still owns cross-horizon alignment vocabulary.
    idx = h.find("function deriveTag(slug, dir)")
    assert idx != -1
    chunk = h[idx : idx + 600]
    assert "alignment_state_display" in chunk
    assert "return 'ALIGNED'" in chunk or "return 'SPLIT'" in chunk


def test_mhap_fixed_row_order_in_renderer():
    """Fixed 4-horizon order asserted via the horizon→bar mapping in the renderer.

    The original ``const fixed = ['1c','5c','15c','60c']`` array was replaced by
    a horizon→bar mapping ``const m = { '1c': '1m', '5c': '5m', '15c': '15m', '60c': '60m' }``
    around static/index.html:~L4037 — same canonical set, mapped to display labels.
    """
    h = _html()
    assert "{ '1c': '1m', '5c': '5m', '15c': '15m', '60c': '60m' }" in h


def test_tf_trade_signal_cards_keep_color_under_direction_withhold():
    """LONG/SHORT horizon cards must not be grayscale-washed when lane is stale."""
    h = _html()
    assert "card.setAttribute('data-tf-signal-dir', sigDir)" in h
    assert "tf-signal-card--trade-active" in h
    assert "tf-signal-card--non-actionable" in h
    assert '[data-tf-signal-dir="long"]' in h
    assert '[data-tf-signal-dir="short"]' in h
    assert "function resolveHorizonCardVisualState" in h
    assert "window.resolveHorizonCardVisualState = resolveHorizonCardVisualState" in h


def test_horizon_direction_decoupled_from_final_tradeable():
    """Per-horizon pills must paint LONG/SHORT from mhap_rows.call — not final_tradeable."""
    h = _html()
    idx = h.find("function resolveHorizonCardVisualState")
    assert idx != -1
    chunk = h[idx : idx + 1200]
    assert "isConsolidated" in chunk
    assert "nonActionable" in chunk
    assert "if (!tradeable) nonActionable = true" in chunk
    row_idx = h.find("const visual = resolveHorizonCardVisualState")
    assert row_idx != -1
    assert "data-horizon-direction" in h[row_idx : row_idx + 800]
    assert "data-horizon-actionability" in h[row_idx : row_idx + 800]


def test_render_timeframe_signal_row_includes_consolidated_slug():
    h = _html()
    assert "{ slug: 'consolidated', ui: 'ALL' }" in h
    assert "slug === 'consolidated'" in h
    assert "d.final_bias" in h
    assert "4H synth" in h


def test_individual_horizon_cards_primary_agree_conflict_vocabulary():
    """Per-horizon pills: PRIMARY on clock horizon; AGREE/CONFLICT vs primary; ALL owns synthesis."""
    h = _html()
    assert "Primary horizon pill tagged PRIMARY" in h
    idx = h.find("function deriveTag(slug, dir)")
    assert idx != -1
    chunk = h[idx : idx + 950]
    assert "return 'PRIMARY'" in chunk
    assert "return 'AGREE'" in chunk
    assert "return 'CONFLICT'" in chunk
    assert "return 'LEAD'" not in chunk
    assert "return 'WITH LEAD'" not in chunk
    assert "String(slug).toLowerCase() === prim" in chunk


def test_all_and_plan_trust_engine_final_tradeable_only():
    """ALL/PLAN lighting must follow d.final_tradeable — no UI re-count of mhap rows."""
    h = _html()
    assert "function engineTradeableSetup" in h
    idx = h.find("function engineTradeableSetup")
    assert idx != -1
    chunk = h[idx : idx + 380]
    assert "d.final_tradeable" in chunk
    assert "MIN_TRADEABLE_HORIZONS_FOR_ALL_PLAN" not in h
    assert "function alignedDirectionalHorizonCount" not in h
    idx_plan = h.find("function paintTradePlanCard")
    assert idx_plan != -1
    plan_chunk = h[idx_plan : idx_plan + 1600]
    assert "engineTradeableSetup" in plan_chunk
    idx_row = h.find("const tradeable = engineTradeableSetup(d)")
    assert idx_row != -1
    vis_idx = h.find("function resolveHorizonCardVisualState")
    assert vis_idx != -1
    vis_chunk = h[vis_idx : vis_idx + 900]
    assert "if (tradeable && dir === 'LONG')" in vis_chunk
    assert "isConsolidated" in vis_chunk
    idx_cons = h.find("if (slug === 'consolidated') {\n      if (tradeable)")
    assert idx_cons != -1
    cons_chunk = h[idx_cons : idx_cons + 520]
    assert "dir = 'FLAT'" in cons_chunk


def test_trade_active_glow_only_on_all_card():
    """Entry-armed / trade-active chrome applies to ALL synthesis card only."""
    h = _html()
    idx = h.find("const isPrimaryTrade =")
    assert idx != -1
    chunk = h[idx : idx + 280]
    assert "slug === 'consolidated'" in chunk
    assert "slug === prim" not in chunk


def test_unavailable_reason_code_mapped_to_operator_short_text():
    """Raw PRIMARY_HORIZON_DATA_MISSING must not paint on cards (5-col overflow)."""
    h = _html()
    assert "function formatUnavailableReasonCode" in h
    assert "PRIMARY_HORIZON_DATA_MISSING" in h
    assert "formatUnavailableReasonCode(rc)" in h
    assert "dir === 'UNAVAILABLE'" in h
    assert "max-width: min(1024px" in h


def test_derive_source_for_horizon_no_implicit_blend_when_fusion_ok():
    """Horizon chip must not read BLEND merely because empirical histogram exists."""
    h = _html()
    idx = h.find("function deriveSourceForHorizon(d, slug)")
    body = h[idx : idx + 2200]
    assert "if (hzFusionOk && empPresent) return 'BLEND';" not in body


def test_render_tier_c_pending_shell_repaints_cards_when_mhap_present():
    h = _html()
    assert "renderTierCPendingShell" in h
    assert "renderTimeframeSignalRow(merged)" in h
    assert "renderDecisionCommandRail(merged)" in h


def test_timeframe_cards_show_loading_when_analytics_pending_without_mhap():
    h = _html()
    assert "tf-signal-card--analytics-loading" in h
    assert "analyticsLoading && mhap.length === 0" in h


def test_timeframe_pills_render_from_mhap_rows_only():
    """Dead branch removed (2026-06-10): no producer ever emitted d.timeframe_cards,
    so the pills must read mhap_rows directly with no phantom server-list fork."""
    h = _html()
    assert "timeframe_cards" not in h
    assert "useServer" not in h


def test_institutional_lane_stale_coherence_hooks():
    h = _html()
    assert "INSTITUTIONAL_BUNDLE_TRUST_SEC" in h
    assert "function laneStaleOperatorLabel" in h
    assert "window.laneStaleOperatorLabel = laneStaleOperatorLabel" in h
    assert "SYNCING ANALYTICS" in h
    assert "bundleWithinTrustWindow(integrity, ld" in h
    assert "function bundleDirectionWithheld(integrity, d, nowMs)" in h
    idx = h.find("function bundleDirectionWithheld")
    chunk = h[idx : idx + 1400]
    assert "bundleWithinTrustWindow(integrity, ld, nowMs)" in chunk


def test_tf_dim_neutral_cards_have_operator_legibility_styles():
    """WAIT/neutral timeframe cards must separate from row chrome (AGENTS legibility gate)."""
    h = _html()
    assert ".tf-signal-card.tf-state-dim" in h
    idx = h.find(".tf-signal-card.tf-state-dim {")
    assert idx != -1
    chunk = h[idx : idx + 520]
    assert "box-shadow" in chunk
    assert "#6b9fd4" in chunk
    assert "#334155" not in chunk


# ── UI card provenance spec — per-pill chip surfaces ───────────────────────
# Brief: ACTIVE_PROGRAM.md §UI card provenance spec. Chip vocabulary is the
# five-state set EMPIRICAL | ML FUSION | BLEND | UNAVAILABLE | DEGRADED,
# carried per pill via .tf-source-chip + .tf-source-detail. (The unified
# signal-rail-card that used to sit below the pills was retired 2026-06-10;
# see test_signal_rail_card_removed_negative_lock.)

def test_tf_source_chip_css_five_variants_defined():
    """Per-pill provenance chip CSS class + 5 variants are defined."""
    h = _html()
    assert ".tf-source-chip {" in h
    assert ".tf-source-chip--empirical" in h
    assert ".tf-source-chip--ml-fusion" in h
    assert ".tf-source-chip--blend" in h
    assert ".tf-source-chip--unavailable" in h
    assert ".tf-source-chip--degraded" in h


def test_tf_source_detail_subline_defined():
    """Operator-text subline class is defined under the chip."""
    h = _html()
    assert ".tf-source-detail {" in h


def test_tf_signal_cards_have_chip_and_detail_elements():
    """Each tf-signal-card carries a chip + detail element (four horizons + consolidated ALL)."""
    h = _html()
    assert h.count('class="tf-source-chip ') >= 5
    assert h.count('class="tf-source-detail"') >= 5
    assert 'id="tf-signal-consolidated"' in h
    # Six pills: 1M/5M/15M/60M + ALL + PLAN (operator 2026-06-10). PLAN track is
    # wider (operator 2026-06-11: values were ellipsizing); signal pills stay 1fr.
    assert 'grid-template-columns: repeat(5, minmax(0, 1fr)) minmax(0, 1.26fr)' in h


def test_trade_plan_card_sits_beside_all_card_with_same_chrome():
    """Operator 2026-06-10: trade plan promoted out of the Decision Command rail into
    its own pill card next to ALL — same tf-signal-card chrome, painted every refresh."""
    h = _html()
    # Card + value surfaces exist in the pill row.
    assert 'id="tf-signal-plan"' in h
    for el_id in ("tf-plan-state", "tf-plan-entry", "tf-plan-stop", "tf-plan-targets", "tf-plan-invalidation", "tf-plan-size"):
        assert f'id="{el_id}"' in h, f"PLAN card element {el_id} missing"
    # PLAN renders after ALL in the same row (right next to it).
    row_start = h.find('id="timeframe-signal-row"')
    all_idx = h.find('id="tf-signal-consolidated"', row_start)
    plan_idx = h.find('id="tf-signal-plan"', row_start)
    assert row_start != -1 and all_idx != -1 and plan_idx != -1
    assert all_idx < plan_idx, "PLAN card must sit immediately after the ALL card"
    # Painter wired into renderTimeframeSignalRow for both loading + live paths.
    assert "function paintTradePlanCard(loadingHint)" in h
    assert "paintTradePlanCard(loadHint);" in h
    assert "paintTradePlanCard(null);" in h
    # Reads the bundle's plan fields — no parallel derivation.
    for field in ("entry_display_text", "stop_display_text", "targets_display", "invalidation", "size_modifier_display", "entry_state"):
        idx = h.find("function paintTradePlanCard(loadingHint)")
        assert f"d.{field}" in h[idx : idx + 4500], f"PLAN card must read d.{field}"
    # No-wrap contract: plan values stay on one line (ellipsis + title tooltip).
    plan_css = h.find(".tf-plan-kv .tf-plan-v")
    assert plan_css != -1
    assert "white-space: nowrap" in h[plan_css : plan_css + 200]
    assert "text-overflow: ellipsis" in h[plan_css : plan_css + 200]
    # Direction-withhold coverage: plan values are direction-bearing once armed.
    assert "'tf-signal-plan'," in h


def test_derive_source_for_horizon_js_helpers_present():
    """Top-level JS helpers map payload to chip vocabulary.

    Server may stamp d.mh_prob_source_by_horizon[slug] with either brief-style
    values (EMPIRICAL | ML FUSION | BLEND | UNAVAILABLE | DEGRADED) or the
    current internal stamping (fusion_ml_primary / empirical_support_blend /
    fusion_directional_missing). deriveSourceForHorizon handles both.
    """
    h = _html()
    assert "function deriveSourceForHorizon(d, slug)" in h
    assert "function sourceChipCssClass(source)" in h
    assert "function sourceChipTitle(source)" in h
    assert "function sourceOperatorText(source, d, slug)" in h
    # Server internal vocabulary is recognized
    assert "'fusion_ml_primary'" in h
    assert "'guest_anchor_fusion'" in h
    assert "'empirical_support_blend'" in h
    assert "'fusion_directional_missing'" in h
    # Window exports for diag / test inspection
    assert "window.deriveSourceForHorizon = deriveSourceForHorizon" in h


def test_paint_source_chip_uses_new_selectors():
    """paintSourceChip targets .tf-source-chip + .tf-source-detail (new design),
    not the dormant legacy .tf-source element."""
    h = _html()
    assert "function paintSourceChip(card, payload, slugKey, dirVal)" in h
    assert "card.querySelector('.tf-source-chip')" in h
    assert "card.querySelector('.tf-source-detail')" in h
    # Delegates to top-level deriveSourceForHorizon helpers
    assert "deriveSourceForHorizon(payload, slugKey)" in h


def test_chip_vocabulary_operator_text_strings_present():
    """Operator-readable text matches the brief verbatim — used both in tooltip
    titles and in the .tf-source-detail subline below each chip."""
    h = _html()
    assert "Stack trained" in h
    assert "Stack + history" in h
    assert "No ML — WAIT" in h
    assert "Data quality hold" in h
    # Empirical operator text is computed: "N similar setups" — sample-count form
    assert "similar setups" in h
    # mh_prob_source_by_horizon is the payload field the chip reads
    assert "mh_prob_source_by_horizon" in h


def test_guest_anchor_provisional_chip_vocabulary():
    """Guest anchor v2: compact ANCHOR chip + affiliation rationale on payload."""
    h = _html()
    assert "function guestAnchorChipLabel(d)" in h
    assert "function sourceChipDisplayText(source, d)" in h
    assert "guest_anchor_active" in h
    assert "guest_anchor_weights_ticker" in h
    assert "guest_anchor_rationale" in h
    assert "tf-source-chip--provisional" in h
    assert "not ticker-trained" in h
    # Chip paints compact label — long PROVISIONAL · ANCHOR (TICKER) must not be card text.
    assert "sourceChipDisplayText(source, payload)" in h
    idx = h.find("function sourceChipDisplayText(source, d)")
    assert idx != -1
    chunk = h[idx : idx + 420]
    assert "ANCHOR ·" in chunk or "'ANCHOR · '" in chunk
    assert "PROVISIONAL · ANCHOR (" not in chunk


def test_tf_source_chip_cannot_bleed_across_pill_row():
    """nowrap provenance chips must clip inside each pill — no cross-card purple bar."""
    h = _html()
    card_idx = h.find(".tf-signal-card {")
    assert card_idx != -1
    card_chunk = h[card_idx : card_idx + 520]
    assert "overflow: hidden" in card_chunk
    chip_idx = h.find(".tf-source-chip {")
    assert chip_idx != -1
    chip_chunk = h[chip_idx : chip_idx + 520]
    assert "max-width: 100%" in chip_chunk
    assert "text-overflow: ellipsis" in chip_chunk


def test_loading_shell_clears_new_chip_and_detail_elements():
    """The analytics-loading shell loop clears .tf-source-chip + .tf-source-detail
    (the new elements), not the dormant legacy .tf-source element."""
    h = _html()
    assert "'tf-source-chip tf-source-chip--unavailable'" in h
    idx = h.find("analyticsLoading && mhap.length === 0")
    assert idx != -1, "loading-shell guard must be present"
    chunk = h[idx : idx + 2200]
    assert ".tf-source-chip" in chunk
    assert ".tf-source-detail" in chunk


# ── UI design lock — operator verdicts 2026-05-27 + 2026-06-10 ────────────
# These surfaces were intentionally removed and MUST NOT be re-introduced.
# Re-adding any of them fails this suite — mechanical enforcement against
# any agent reverting the operator-approved pill-row design back to
# parallel / dormant / redundant surfaces.
#
# Removed:
#   - Cursor's parallel dr-fusion-authority-strip + dr-empirical-context-line
#     inside the Decision Rail ("no co-existing your design rules")
#   - Decision Command verdict row (dr-trade-pill / dr-bias-pill /
#     dr-desk-confidence / dr-confidence-pill)
#   - Decision Command title strip ("DECISION COMMAND · Operator surface…")
#   - Dormant legacy .tf-source CSS rules
#   - The unified signal-rail-card itself (operator 2026-06-10): its verdict
#     moved to the ALL pill, its plan to the PLAN pill
# Single source of truth = ALL/PLAN pills + .tf-source-chip system.

def test_no_decision_verdict_row_pills():
    """Operator removed the redundant TRADE/LONG/56%/LOW pill row 2026-05-27."""
    h = _html()
    assert 'class="decision-verdict-row"' not in h
    assert 'id="dr-trade-pill"' not in h
    assert 'id="dr-bias-pill"' not in h
    assert 'id="dr-desk-confidence"' not in h
    assert 'id="dr-confidence-pill"' not in h


def test_no_cursor_parallel_fusion_strip():
    """Cursor's parallel UI surface removed per "no co-existing" instruction."""
    h = _html()
    assert 'id="dr-fusion-authority-strip"' not in h
    assert 'id="dr-empirical-context-line"' not in h
    assert 'dr-fusion-authority-strip--active' not in h
    assert 'dr-fusion-authority-strip--muted' not in h


def test_no_legacy_tf_source_classes():
    """Dormant pre-mockup .tf-source CSS removed; chip system uses .tf-source-chip."""
    h = _html()
    assert '.tf-source.tf-source--hidden' not in h
    assert '.tf-source.tf-source--empirical {' not in h
    assert '.tf-source.tf-source--ml {' not in h
    assert '.tf-source.tf-source--blend {' not in h
    assert 'class="tf-source tf-source--hidden"' not in h


def test_no_decision_command_title_strip():
    """Operator removed the 'DECISION COMMAND · Operator surface…' header strip 2026-05-27."""
    h = _html()
    assert '<span class="signal-card-title">Decision Command</span>' not in h
    assert 'Operator surface · bar horizons map' not in h


def test_signal_rail_card_removed_negative_lock():
    """Operator 2026-06-10: the signal-rail-card was retired — the ALL pill is
    the consolidated verdict and the PLAN pill is the trade plan. No agent may
    re-introduce the card or its renderer."""
    h = _html()
    assert 'id="signal-rail-card"' not in h
    assert "function renderSignalRailCard" not in h
    assert "renderSignalRailCard(" not in h
    assert ".fas-armed-tag {" not in h
    assert ".fas-degraded-tag {" not in h
    assert 'id="src-ecl-probs"' not in h
    # 2026-06-10 second wave: rail Why/gates + Readiness/trust +
    # Stack-behind-the-call blocks retired (duplicative with pills, header
    # chips and the signal-chain bar). WAIT reason moved to the ALL pill.
    for el_id in (
        "dr-action-chip", "dr-live-ready-chip", "dr-exact-reason",
        "dr-threshold-gate", "dr-ranking-gate", "dr-blocking-reason",
        "dr-stack-contrib", "dr-stack-fusion", "dr-stack-mc",
        "dr-stack-bases", "dr-stack-gov",
    ):
        assert el_id not in h, f"{el_id} must stay removed (retired rail block)"
    assert "'WAIT — ' + why" in h, "ALL pill must carry the WAIT/blocker reason when synth withheld"


# ── Signals Rail — operator design 2026-05-27 (binding) ───────────────────
# Vertical analytics column to the right of the horizon pill row.
# Severity grammar: quiet → building → hot (+ positive green). Each slot is a
# self-contained signal (Level Test first). Adding / removing slots =
# changing #signals-rail children.

def test_signals_rail_layout_present():
    """Top-stack split (post-2026-05-27 restructure for height uniformity):
    .top-stack-row contains horizon pills + Signals Rail as direct flex
    siblings (align-items: stretch makes the Level Test slot match the
    rendered horizon-card height). Header + multi-slot variants stay
    reverted."""
    h = _html()
    assert 'class="top-stack-row"' in h
    # Old top-stack-col wrapper was removed so signals-rail-col could
    # flex-stretch directly against tf-signal-row-outer
    assert 'class="top-stack-col"' not in h
    assert 'class="signals-rail-col"' in h
    assert 'id="signals-rail"' in h
    # Header + count removed per operator 2026-05-27 design revert
    assert 'class="signals-rail-hd"' not in h
    assert 'id="signals-count"' not in h


def test_signals_rail_three_severity_variants_defined():
    """One severity color grammar across rail slots — operator learns one grammar."""
    h = _html()
    assert '.signal-slot--quiet' in h
    assert '.signal-slot--building' in h
    assert '.signal-slot--hot' in h
    assert '.signal-slot--positive' in h


def test_level_test_slot_present():
    """First occupant of the rail — Pass 4b Level Test."""
    h = _html()
    assert 'id="slt-level-test"' in h
    assert 'id="slt-level-test-headline"' in h
    assert 'id="slt-level-test-ico"' in h
    assert 'id="slt-level-test-name"' in h
    assert 'id="slt-level-test-body"' in h


def test_dr_level_test_chip_removed_dedup_lock():
    """Old dr-level-test-chip (Decision Rail header) was removed —
    Signals Rail slt-level-test slot is the single source of truth for
    Pass 4b level-test info. Lock against re-introducing the duplicate."""
    h = _html()
    assert 'id="dr-level-test-chip"' not in h


def test_update_level_test_chip_targets_new_slot():
    """JS function rewritten to populate slt-level-test, severity branches.
    Quiet state hides slot entirely (operator design: card only shows when
    level is actually under pressure, ≥2 prior tests). Content trimmed to
    fit the 148px height that matches horizon card uniformity."""
    h = _html()
    assert 'function _updateLevelTestChip' in h
    assert "$('slt-level-test')" in h
    assert "if (severity === 'hot')" in h
    assert "else if (severity === 'building')" in h
    # Trimmed institutional payoff copy
    assert 'Repeated probes' in h
    assert 'strong hold' in h
    assert 'Pressure building' in h


def test_level_test_slot_uniform_height_with_horizon_cards():
    """Operator design: rail card height matches .tf-signal-card min-height
    (148px) for uniform sibling-card aesthetic."""
    h = _html()
    idx = h.find('#slt-level-test {')
    assert idx != -1
    chunk = h[idx : idx + 200]
    assert 'height: 148px' in chunk


def test_signals_rail_no_multi_slot_design():
    """Operator reverted multi-slot rail 2026-05-27: removed Stack Integrity /
    Order Flow / Proximity slots + their JS updaters. Only Level Test remains."""
    h = _html()
    # Slots that were removed must stay removed
    assert 'id="slt-stack-integrity"' not in h
    assert 'id="slt-order-flow"' not in h
    assert 'id="slt-proximity"' not in h
    # Updater functions that were removed must stay removed
    assert 'function _updateStackIntegritySlot' not in h
    assert 'function _updateOrderFlowSlot' not in h
    assert 'function _updateProximitySlot' not in h
    # Aggregate count helper removed (no rail header anymore)
    assert 'function _updateSignalsRailCount' not in h


def test_decision_rail_stack_chips_restored():
    """Stack Integrity chips moved BACK to Decision Rail header after the
    multi-slot rail design was reverted. Lock against re-removal."""
    h = _html()
    assert 'id="dr-stack-mode-chip"' in h
    assert 'id="dr-signals-engine-fail-chip"' in h
    assert 'id="dr-stack-integrity-degraded-chip"' in h


def test_signals_rail_paint_cycle_wired():
    """Only Level Test fires in the paint cycle (multi-slot variant reverted)."""
    h = _html()
    idx = h.find('function _updateLiveUiAe(opts)')
    assert idx != -1
    chunk = h[idx : idx + 1200]
    assert '_updateLevelTestChip();' in chunk


def test_top_stack_row_gap_for_visual_offset():
    """Operator iterated on rail position: 12px (initial) → 60px (rail right)
    → 28px (rail back ~32px / quarter-inch left). Lock to 28px."""
    h = _html()
    idx = h.find('.top-stack-row {')
    assert idx != -1
    chunk = h[idx : idx + 200]
    assert 'gap: 28px' in chunk


def test_entry_state_labels_render_contract():
    """Entry state contract — the entry surface is the PLAN pill card
    (tf-plan-entry; the rail dr-plan-* block was retired 2026-06-10);
    entry_display_text is still the live field; renderMultiHorizon was inlined into the
    mhap renderer that reads d.mhap_rows directly.
    """
    h = _html()
    assert "tf-plan-entry" in h
    assert "dr-plan-entry" not in h  # rail Trade-plan block retired (duplicative)
    assert "entry_display_text" in h  # unchanged live field name
    # Inline mhap renderer pattern (renderMultiHorizon was inlined into this block).
    assert "d.mhap_rows" in h


def test_ui_latency_contract_nonblocking_tier_c_and_analytics_poll():
    """UI_LATENCY_CONTRACT — quote lane must not suppress Tier C poll; switch must not block on 120s Tier C."""
    h = _html()
    assert "UI_LATENCY_CONTRACT" in h
    assert "_lastSseAnalyticsPayloadMs" in h
    assert "_tierCRestAbortController" in h
    assert "_edTierCCacheByTicker" in h
    assert "function _snapshotCacheRestore" in h
    assert "function manualFullRefresh" in h
    assert "function _analyticsUiPending" in h
    assert "ANALYTICS_PENDING_POLL_MS" in h
    assert "TIER-C-NONBLOCK-SWITCH" in h
    assert "_fetchTierCRestAndApply" in h
    assert "triggerRefresh() { fetchState(false)" in h
    assert "manualFullRefresh() { fetchState(true)" in h
    assert "_lastSsePayloadAcceptedMs < SSE_POLL_SUPPRESS_MS" not in h
    poll_idx = h.find("function pollStateFallback")
    assert poll_idx != -1
    poll_chunk = h[poll_idx : poll_idx + 1200]
    assert "_lastSseAnalyticsPayloadMs" in poll_chunk
    assert "_analyticsUiPending()" in poll_chunk
    assert "await fetchJsonWithTimeout(url, { signal: fetchAbortSignal }, 120000)" not in h
    assert "_slowFetchAc && _slowFetchAc.abort()" not in h
    tier_idx = h.find("async function _fetchTierCRestAndApply")
    assert tier_idx != -1
    tier_chunk = h[tier_idx : tier_idx + 900]
    assert "tierCSignal" in tier_chunk


def test_ui_maximize_contract_sla_warm_and_partial_render():
    """UI_MAXIMIZE_CONTRACT — binding SLA budgets, server warm POST, real partial Tier C paint (no fake fusion)."""
    h = _html()
    assert "UI_MAXIMIZE_CONTRACT" in h
    assert "ED_UI_MAXIMIZE_SLA_MS" in h
    assert "first_quote: 500" in h
    assert "fusion_cards_panel_warm: 2000" in h
    assert "function _scheduleServerAnalyticsWarm" in h
    assert "/api/analytics/warm" in h
    assert "function renderTierCPartialAnalytics" in h
    assert "analytics_partial_tier_c" in h
    assert "ANALYTICS_PENDING_POLL_MS = 800" in h
    assert "_streamingPostLastTicker" in h
    partial_idx = h.find("function renderTierCPartialAnalytics")
    assert partial_idx != -1
    partial_chunk = h[partial_idx : partial_idx + 2800]
    assert "__renderKeyLevelsLive" in partial_chunk
    assert "renderTimeframeSignalRow" in partial_chunk
    assert "renderKind: 'tier_c_partial_analytics'" in partial_chunk
    render_idx = h.find("function render(d, fullRenderSource)")
    assert render_idx != -1
    render_chunk = h[render_idx : render_idx + 600]
    assert "renderTierCPartialAnalytics" in render_chunk
    pending_idx = h.find("function _analyticsUiPending")
    assert pending_idx != -1
    pending_chunk = h[pending_idx : pending_idx + 400]
    assert "analytics_partial_tier_c" in pending_chunk


def test_card_consumer_contract_fidelity_classification_v1_recorded():
    reg = json.loads(CARD_CONSUMER_CONTRACT.read_text(encoding="utf-8"))
    fc = reg.get("fidelity_classification_v1") or {}
    assert fc.get("display_trust_gate") == "analyticsCardTrustGate"
    assert fc.get("card_fidelity_overall") == "NOT_PROVEN"
    assert fc.get("universal_runtime_live_proof") == "NOT_PROVEN"
    assert "STALE_WITHHELD" in (fc.get("parity_status_vocabulary") or [])
    assert "DOM_MISMATCH" in (fc.get("parity_status_vocabulary") or [])
    sem = fc.get("acceptance_semantics") or {}
    assert sem.get("trust_withheld_ui_fidelity") == "PASS"
    assert sem.get("stale_withheld_non_rth_closure") == "NOT_ADMISSIBLE"
    assert sem.get("true_dom_mismatch") == "FAIL"


def test_card_consumer_contract_explainability_surface_design_recorded():
    reg = json.loads(CARD_CONSUMER_CONTRACT.read_text(encoding="utf-8"))
    exp = reg.get("explainability_surface_v1") or {}
    assert exp.get("status") == "DESIGN_APPROVED_PENDING_UI"
    assert exp.get("display_trust_gate") == "analyticsCardTrustGate"
    assert exp.get("ui_implementation_approved") is False
    by_name = {row["field_name"]: row for row in reg["fields"]}
    assert by_name["pred_headline"]["decision_status"] == "DESIGN_APPROVED_PENDING_UI"
    assert by_name["reversal_risk"]["decision_status"] == "DESIGN_APPROVED_PENDING_UI"


def test_card_consumer_contract_registry_file_exists():
    assert CARD_CONSUMER_CONTRACT.is_file()
    reg = json.loads(CARD_CONSUMER_CONTRACT.read_text(encoding="utf-8"))
    assert reg["schema_version"] == 1
    assert "execution_channel" in reg


def test_card_trust_contract_references_consumer_registry():
    body = CARD_TRUST_CONTRACT.read_text(encoding="utf-8")
    assert "CARD_CONSUMER_CONTRACT_V1.json" in body
    assert "meta-label-ready" in body.lower() or "meta-label-ready" in body
    assert "FUTURE_LANE_WITH_REASON" in body
    assert "call_state" in body


def test_card_consumer_contract_execution_separated_from_horizon_in_ui():
    """Registry rule: horizon pills = forecast; execution = final_tradeable + call_state channel."""
    h = _html()
    assert "function engineTradeableSetup" in h
    assert "function resolveHorizonCardVisualState" in h
    idx = h.find("function resolveHorizonCardVisualState")
    chunk = h[idx : idx + 1200]
    assert "nonActionable" in chunk
    assert "isConsolidated" in chunk
    row_idx = h.find("const tradeable = engineTradeableSetup(d)")
    assert row_idx != -1
    assert "const mhap = Array.isArray(d.mhap_rows)" in h


def test_card_consumer_contract_stale_and_pending_hooks_in_ui():
    h = _html()
    assert "analytics_pending_shell" in h
    assert "tf-signal-card--analytics-loading" in h
    assert "function updateAnalyticsFreshnessUI" in h
    assert "analytics_stale" in h
    assert "function bundleDirectionWithheld" in h
    assert "data-direction-withhold" in h


def test_card_consumer_contract_final_tradeable_gates_all_plan():
    h = _html()
    idx = h.find("function engineTradeableSetup")
    assert idx != -1
    chunk = h[idx : idx + 520]
    assert "d.final_tradeable" in chunk
    assert "resolveCardTrustGate" in chunk
    idx_cons = h.find("if (slug === 'consolidated') {\n      if (tradeable)")
    assert idx_cons != -1
    cons_chunk = h[idx_cons : idx_cons + 520]
    assert "dir = 'FLAT'" in cons_chunk


def test_analytics_card_trust_gate_canonical_function_present():
    h = _html()
    assert "function analyticsCardTrustGate(d, opts)" in h
    assert "window.analyticsCardTrustGate = analyticsCardTrustGate" in h
    assert "CARD_TRUST_REQUIRED_HORIZON_COUNT = 4" in h
    idx = h.find("function analyticsCardTrustGate")
    chunk = h[idx : idx + 2200]
    assert "analytics_stale" in chunk
    assert "analytics_pending_shell" in chunk
    assert "analytics_partial_tier_c" in chunk
    assert "mhap_incomplete" in chunk
    assert "client_ticker_cache" in chunk


def test_card_trust_gate_wired_before_trusted_timeframe_paint():
    h = _html()
    assert "const cardTrust = resolveCardTrustGate(d)" in h
    row_idx = h.find("function renderTimeframeSignalRow")
    trust_idx = h.find("const cardTrust = resolveCardTrustGate(d)")
    assert row_idx != -1 and trust_idx > row_idx
    assert "paintUntrustedTimeframeCardRow(d, cardTrust.reason)" in h
    assert "tf-signal-card--card-trust-withheld" in h
    assert "tf-signal-card--trade-active" in h
    untrusted_idx = h.find("function paintUntrustedTimeframeCardRow")
    untrusted_chunk = h[untrusted_idx : untrusted_idx + 1800]
    assert "tf-signal-card--trade-active" not in untrusted_chunk


def test_engine_tradeable_setup_requires_card_trust():
    h = _html()
    idx = h.find("function engineTradeableSetup")
    chunk = h[idx : idx + 420]
    assert "resolveCardTrustGate(d, { checkTicker: false }).trusted" in chunk


def test_bundle_direction_withheld_uses_card_trust_gate():
    h = _html()
    idx = h.find("function bundleDirectionWithheld")
    chunk = h[idx : idx + 900]
    assert "cardBundleActive" in chunk
    assert "analyticsCardTrustGate(ld, { checkTicker: false })" not in chunk
    assert "resolveCardTrustGate(ld, { checkTicker: false })" in chunk


def test_decision_rail_withholds_when_card_trust_fails():
    h = _html()
    idx = h.find("function renderDecisionCommandRail")
    chunk = h[idx : idx + 12000]
    assert "const cardTrust = resolveCardTrustGate(d)" in chunk
    assert "!cardTrust.trusted" in chunk


def test_render_exported_for_e2e_full_pipeline():
    h = _html()
    assert "window.render = render" in h


def test_quote_plane_fields_absent_from_card_trust_gate():
    """Quote-plane L1 diagnostics must not be card-trust inputs (separate transport)."""
    h = _html()
    idx = h.find("function analyticsCardTrustGate")
    assert idx != -1
    chunk = h[idx : idx + 2600]
    for token in (
        "plane_quote_authority",
        "streaming_fallback",
        "streaming_fallback_explicit",
        "_lastPlaneDiag",
        "rest_fallback_explicit",
        "_quote_authority",
        "getCurrentFeedState",
        "computeFeedState",
    ):
        assert token not in chunk, f"analyticsCardTrustGate must not read {token}"


def test_full_render_analytical_path_does_not_consume_plane_diag_for_cards():
    h = _html()
    render_idx = h.find("function render(d, fullRenderSource)")
    assert render_idx != -1
    render_end = h.find("\n// ── Liquidity Map", render_idx)
    assert render_end != -1
    chunk = h[render_idx:render_end]
    assert "renderTimeframeSignalRow(d)" in chunk
    assert "renderDecisionCommandRail(d)" in chunk
    assert "_lastPlaneDiag" not in chunk


def test_live_plane_apply_core_does_not_mutate_card_decision_fields():
    h = _html()
    idx = h.find("function _livePlaneApplyCore")
    assert idx != -1
    chunk = h[idx : idx + 900]
    for field in ("final_tradeable", "final_bias", "final_confidence", "mhap_rows"):
        assert field not in chunk, f"_livePlaneApplyCore must not write {field}"


def test_plane_diag_commit_does_not_touch_last_data_card_fields():
    h = _html()
    idx = h.find("function _commitPlaneDiagnosticsIfCurrent")
    assert idx != -1
    chunk = h[idx : idx + 700]
    assert "window._lastPlaneDiag = j" in chunk
    assert "window._lastData" not in chunk
    assert "mhap_rows" not in chunk
    assert "final_tradeable" not in chunk


def test_execution_state_chip_consumer_present():
    h = _html()
    assert 'id="tf-execution-state-chip"' in h
    assert "function paintExecutionStateChip(d)" in h
    assert "function normalizeExecutionCallState(raw)" in h
    assert "window.paintExecutionStateChip = paintExecutionStateChip" in h
    idx = h.find("function renderTimeframeSignalRow")
    row_chunk = h[idx : idx + 400]
    assert "paintExecutionStateChip(d)" in row_chunk
    paint_idx = h.find("function paintExecutionStateChip")
    paint_chunk = h[paint_idx : paint_idx + 2200]
    assert "d.call_state" in paint_chunk
    assert "normalizeExecutionCallState" in paint_chunk
    assert "resolveCardTrustGate" in paint_chunk
    assert "d.final_bias" not in paint_chunk
    assert "d.final_tradeable" not in paint_chunk
    assert "d.mhap_rows" not in paint_chunk


def test_execution_state_chip_distinct_from_forecast_direction():
    h = _html()
    assert "tf-exec-chip" in h
    assert "tf-exec-state-bar" in h
    idx = h.find("function paintExecutionStateChip")
    chunk = h[max(0, idx - 280) : idx + 400]
    assert "separate execution channel" in chunk
    setup_idx = h.find("function setupForecastSentence")
    assert setup_idx != -1
    setup_use = h.count("setupForecastSentence(")
    assert setup_use == 1, "setupForecastSentence remains defined-only (not execution chip path)"


def test_card_contract_documents_field_lineage_vocabulary():
    data = json.loads(CARD_CONSUMER_CONTRACT.read_text(encoding="utf-8"))
    vocab = data.get("field_lineage_vocabulary_v1")
    assert isinstance(vocab, dict), "field_lineage_vocabulary_v1 missing"
    classes = vocab.get("lineage_classes")
    assert isinstance(classes, list) and len(classes) == 7
    for name in (
        "SCHWAB_NATIVE_FIELD",
        "SCHWAB_NATIVE_ALIAS_OR_NORMALIZATION",
        "LEGITIMATE_ENGINEERED_FIELD",
        "SUSPICIOUS_ENGINEERED_FIELD_NATIVE_MAY_EXIST",
        "DANGEROUS_PROXY_FIELD",
        "FALLBACK_FIELD",
        "UNKNOWN_LINEAGE_FIELD",
    ):
        assert name in classes
    minimum = vocab.get("trade_determinative_minimum_fields")
    assert "call_state" in minimum
    assert "mhap_rows" in minimum
    assert "fusion_triplets" in minimum


def test_attach_operator_field_lineage_additive_only():
    from features.inference_snapshot import attach_operator_field_lineage

    md = {
        "spot": 501.25,
        "bid": 501.2,
        "ask": 501.3,
        "call_state": "WAIT",
        "mhap_rows": [{"horizon": "1c", "call": "WAIT", "confidence": None}],
        "up_prob_1c": 0.4,
        "down_prob_1c": 0.3,
        "flat_prob_1c": 0.3,
        "fusion_available": True,
        "wait_reason": "no_primary",
        "kl_em_upper": 505.0,
        "analytics_stale": False,
        "quote_source_detail": {
            "spot": "mark",
            "bid": "bidPrice",
            "ask": "askPrice",
            "spread": "schwab_bid_ask_live",
            "carried_forward": False,
        },
        "spread_source": "schwab_bid_ask_live",
    }
    before = {k: v for k, v in md.items()}
    attach_operator_field_lineage(md)
    assert "field_lineage" in md
    for key, val in before.items():
        assert md[key] == val


def test_attach_operator_field_lineage_trade_determinative_minimum():
    from features.inference_snapshot import (
        OPERATOR_FIELD_LINEAGE_CLASSES,
        attach_operator_field_lineage,
    )

    md = {
        "spot": 500.0,
        "bid": 499.9,
        "ask": 500.1,
        "call_state": "WATCH",
        "mhap_rows": [],
        "fusion_available": False,
        "wait_reason": "",
        "analytics_stale": True,
        "quote_source_detail": {
            "spot": "lastPrice",
            "bid": "bidPrice",
            "ask": "askPrice",
            "carried_forward": False,
        },
    }
    attach_operator_field_lineage(md)
    fl = md["field_lineage"]
    for key in ("call_state", "mhap_rows", "spot", "bid", "ask", "wait_reason", "expected_move", "analytics_stale"):
        assert key in fl
    assert "fusion_triplets" in fl
    for hz in ("1c", "5c", "15c", "60c"):
        assert hz in fl["fusion_triplets"]
        assert fl["fusion_triplets"][hz]["lineage_class"] in OPERATOR_FIELD_LINEAGE_CLASSES
    assert fl["spot"]["lineage_class"] == "SCHWAB_NATIVE_ALIAS_OR_NORMALIZATION"
    assert fl["spot"]["schwab_leaf"] == "quotes.*.lastPrice"
    assert fl["wait_reason"]["lineage_class"] == "UNKNOWN_LINEAGE_FIELD"


def test_operator_mirror_resolver_present_and_exported():
    h = _html()
    assert "function resolveCardTrustGate(d, opts)" in h
    assert "function hasOperatorCardMirrorFields(d)" in h
    assert "window.resolveCardTrustGate = resolveCardTrustGate" in h
    idx = h.find("function resolveCardTrustGate")
    chunk = h[idx : idx + 1400]
    assert "operator_card_actionable" in chunk
    assert "authority: 'operator_mirror'" in chunk
    assert "analyticsCardTrustGate(d, opts)" in chunk


def test_operator_actionable_false_vetoes_trade_active_class():
    h = _html()
    idx = h.find("function renderTimeframeSignalRow")
    chunk = h[idx : idx + 9000]
    assert "operatorMirrorVeto" in chunk
    assert "!operatorMirrorVeto &&" in h
    assert "tf-signal-card--trade-active" in h
    assert "data-operator-actionability-veto" in h


def test_operator_actionable_false_vetoes_plan_active_even_when_final_tradeable():
    h = _html()
    idx = h.find("function paintTradePlanCard")
    chunk = h[idx : idx + 3200]
    assert "engineTradeableSetup(d)" in chunk
    assert "opVeto" in chunk
    assert "tf-signal-card--operator-actionability-veto" in chunk
    assert "tf-glow-3" in chunk
    assert "!opVeto" in chunk


def test_operator_actionable_false_preserves_all_bias_with_non_actionable():
    h = _html()
    idx = h.find("else if (operatorMirrorVeto)")
    assert idx != -1
    chunk = h[idx : idx + 400]
    assert "final_bias" in chunk
    assert "tf-signal-card--non-actionable" in h


def test_operator_trust_reason_surfaced_in_ui():
    h = _html()
    assert "function operatorActionabilityReasonText(d, trust)" in h
    assert "operator_actionability_reason" in h
    assert "operator_stale_reason_codes" in h
    assert "Not actionable:" in h


def test_mirror_absent_falls_back_to_analytics_card_trust_gate():
    h = _html()
    idx = h.find("function resolveCardTrustGate")
    chunk = h[idx : idx + 1600]
    assert "hasOperatorCardMirrorFields(d)" in chunk
    assert "authority: 'analyticsCardTrustGate'" in chunk
    assert "function analyticsCardTrustGate(d, opts)" in h


def test_final_tradeable_cannot_override_operator_false():
    h = _html()
    idx = h.find("function engineTradeableSetup")
    chunk = h[idx : idx + 520]
    assert "resolveCardTrustGate" in chunk
    assert "d.final_tradeable" in chunk
    gate_idx = h.find("function resolveCardTrustGate")
    gate_chunk = h[gate_idx : gate_idx + 1200]
    assert "operator_card_actionable === true" in gate_chunk


def test_tier_c_fingerprint_includes_operator_mirror_fields():
    h = _html()
    idx = h.find("function _tierCCardRenderFingerprint")
    chunk = h[idx : idx + 1800]
    assert "operator_card_actionable" in chunk
    assert "operator_card_trust_state" in chunk
    assert "operator_stale_reason_codes" in chunk
    assert "operator_actionability_reason" in chunk
    assert "final_tradeable" in chunk


def test_card_consumer_contract_operator_mirror_s3a_recorded():
    reg = json.loads(CARD_CONSUMER_CONTRACT.read_text(encoding="utf-8"))
    s3a = reg.get("operator_mirror_actionability_v1") or {}
    assert s3a.get("lane_id") == "S3A_OPERATOR_ACTIONABILITY_UI_FAIL_CLOSED_V1"
    assert s3a.get("ui_resolver") == "resolveCardTrustGate"
    assert s3a.get("card_fidelity_overall") == "NOT_CLOSED_NOT_PROVEN"
    assert s3a.get("stale_withheld_rth_freshness") == "FAIL"
    assert "operator_card_actionable" in (s3a.get("authority_when_mirrors_present") or [])


def test_card_trust_contract_documents_s3a_operator_mirrors():
    body = CARD_TRUST_CONTRACT.read_text(encoding="utf-8")
    assert "S3A operator mirror UI fail-closed" in body
    assert "resolveCardTrustGate" in body
    assert "operator_card_actionable" in body
    assert "does not" in body.lower() or "does **not**" in body


def test_t0_money_path_latency_object_initialized():
    h = _html()
    assert "window.__edMoneyPathLatency" in h
    assert "initialized: true" in h
    assert "last_render_ms" in h
    assert "last_event_to_paint_ms" in h
    assert "rest_poll_overlap_count" in h
    assert "rest_poll_in_flight" in h
    assert "server_build_ts_regression_seen_count" in h
    assert "latest_quote_age_ms" in h
    assert "latest_bundle_age_ms" in h
    assert "quote_ahead_seen_count" in h
    assert "long_task_count" in h
    assert "last_long_task_ms" in h


def test_t0_performance_marks_and_measures_present():
    h = _html()
    for mark in (
        "money_path_sse_received",
        "money_path_rest_received",
        "money_path_render_scheduled",
        "money_path_render_started",
        "money_path_render_completed",
        "money_path_horizon_cards_painted",
        "money_path_plan_painted",
        "money_path_all_card_painted",
        "money_path_fast_quote_received",
    ):
        assert mark in h, f"missing Performance mark {mark}"


def test_t0_render_coherence_guard_instruments_ts_regression_without_behavior_change():
    h = _html()
    idx = h.find("function _renderCoherenceGuards")
    chunk = h[idx : idx + 2200]
    assert "server_build_ts_regression_seen_count" in chunk
    assert "out_of_order_accept_via_gen_despite_ts_regression_count" in chunk
    assert "decision_generation_accept_count" in chunk
    assert "out_of_order_reject_count" in chunk
    assert "Intentional: newer decision_generation_id accepts even when _server_build_ts regresses" in chunk


def test_t0_poll_overlap_instrumentation_present():
    h = _html()
    idx = h.find("async function pollStateFallback")
    assert idx != -1
    fin = h.find("\nfunction startStatePollFallback", idx)
    chunk = h[idx : fin if fin != -1 else idx + 8000]
    assert "rest_poll_start_count" in chunk
    assert "rest_poll_overlap_count" in chunk
    assert "rest_poll_in_flight" in chunk
    assert "rest_poll_complete_count" in chunk


def test_t0_long_task_observer_fail_safe():
    h = _html()
    idx = h.find("function _edMplInstallLongTaskObserver")
    chunk = h[idx : idx + 900]
    assert "PerformanceObserver" in chunk
    assert "longtask" in chunk
    assert "catch (e)" in chunk


def test_t0_instrumentation_does_not_remove_card_trust_gate():
    h = _html()
    assert "function analyticsCardTrustGate(d, opts)" in h
    assert "function resolveCardTrustGate(d, opts)" in h
    assert "function engineTradeableSetup(d)" in h
    idx = h.find("function engineTradeableSetup")
    chunk = h[idx : idx + 520]
    assert "resolveCardTrustGate" in chunk
    assert "d.final_tradeable" in chunk


def test_card_trust_contract_documents_t0_instrumentation_lane():
    body = CARD_TRUST_CONTRACT.read_text(encoding="utf-8")
    assert "T0 money-path latency" in body
    assert "__edMoneyPathLatency" in body
    assert "does not" in body.lower() or "does **not**" in body
    assert "NOT_PROVEN" in body or "not closure" in body.lower()


def test_t0_schwab_csv_first_declaration_in_contract():
    body = CARD_TRUST_CONTRACT.read_text(encoding="utf-8")
    idx = body.find("## 18. T0 money-path latency")
    assert idx != -1
    chunk = body[idx : idx + 2800]
    assert "Schwab CSV authority checked: yes" in chunk
    assert "CSV row(s): NO_SCHWAB_EQUIVALENT" in chunk
    assert "SCHWAB_CSV_CHECKED" in chunk
    assert "__edMoneyPathLatency" in chunk
    assert "does not fix lag" in chunk.lower() or "does not close card fidelity" in chunk.lower()


def test_t0_sse_transport_result_accounted_once_per_outcome():
    h = _html()
    idx = h.find("const _didRenderSse = render(data, 'sse');")
    assert idx != -1
    chunk = h[idx : idx + 500]
    assert chunk.count("_edMplOnSseTransportResult") == 1
    assert "_edMplOnSseTransportResult(_didRenderSse)" in chunk


def _t1_contract_chunk(body: str) -> str:
    idx = body.find("## 19. T1 stale-label and latency contract")
    assert idx != -1, "T1 contract section missing"
    return body[idx : idx + 6500]


def test_t1_contract_quote_freshness_thresholds_defined():
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    assert "≤ 3s" in chunk or "<= 3s" in chunk
    assert "10s" in chunk
    assert "fresh" in chunk.lower()
    assert "aging" in chunk.lower()
    assert "stale" in chunk.lower()


def test_t1_contract_card_bundle_freshness_thresholds_defined():
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    assert "15s" in chunk
    assert "45s" in chunk
    assert "120s" in chunk
    assert "frozen" in chunk.lower()


def test_t1_contract_quote_ahead_read_only_semantics():
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    assert "quote-ahead" in chunk.lower() or "quote newer" in chunk.lower() or "Quote-ahead" in chunk
    assert "read-only" in chunk.lower()
    assert "must not" in chunk.lower() or "must **not**" in chunk


def test_t1_contract_frozen_card_non_actionable_semantics():
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    assert "frozen" in chunk.lower()
    assert "actionable" in chunk.lower()
    assert "trade-active" in chunk.lower() or "armed" in chunk.lower()


def test_t1_contract_stale_label_visibility_requirement():
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    assert "mechanically testable" in chunk.lower() or "visible" in chunk.lower()
    assert "silent" in chunk.lower()


def test_t1_contract_t0_diagnostic_mapping_defined():
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    for field in (
        "latest_quote_age_ms",
        "latest_bundle_age_ms",
        "quote_ahead_seen_count",
        "last_event_to_paint_ms",
        "out_of_order_reject_count",
        "server_build_ts_regression_seen_count",
    ):
        assert field in chunk


def test_t1_contract_non_closure_caveats_preserved():
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    assert "does not fix lag" in chunk.lower() or "does **not** fix lag" in chunk
    assert "stale_withheld_rth_freshness" in chunk
    assert "real-money readiness" in chunk.lower() or "real_money_readiness" in chunk


def test_t1_contract_downstream_t2_t3_t4_t5_requirements():
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    assert "T2" in chunk
    assert "T3" in chunk
    assert "T4" in chunk
    assert "T5" in chunk
    assert "rAF" in chunk or "sequence_id" in chunk
    assert "money_path_snapshot" in chunk


def test_t1_contract_no_implementation_of_forbidden_transport_primitives():
    h = _html()
    assert "money_path_snapshot" not in h
    assert "sequence_id" not in h
    assert "requestAnimationFrame" not in h
    assert "WebSocket" not in h
    chunk = _t1_contract_chunk(CARD_TRUST_CONTRACT.read_text(encoding="utf-8"))
    assert "no browser WebSocket" in chunk.lower() or "no `money_path_snapshot`" in chunk


def test_t1_registry_stale_label_latency_contract_v1():
    import json

    reg = json.loads(
        (ROOT / "governance/artifacts/CARD_CONSUMER_CONTRACT_V1.json").read_text(encoding="utf-8")
    )
    t1 = reg["stale_label_latency_contract_v1"]
    assert t1["lane_id"] == "T1_STALE_LABEL_AND_LATENCY_CONTRACT_V1"
    assert t1["quote_freshness_states"]["fresh_ms_max"] == 3000
    assert t1["card_bundle_freshness_states"]["frozen_ms_min"] == 120000
    assert "latest_quote_age_ms" in t1["t0_diagnostic_mapping"]
    assert "browser WebSocket" in t1["does_not_implement"]
    assert "lag_fix" in t1["does_not_close"]
