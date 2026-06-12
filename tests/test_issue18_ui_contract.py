from __future__ import annotations

from pathlib import Path


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
    assert '[data-tf-signal-dir="long"]' in h
    assert '[data-tf-signal-dir="short"]' in h


def test_render_timeframe_signal_row_includes_consolidated_slug():
    h = _html()
    assert "{ slug: 'consolidated', ui: 'ALL' }" in h
    assert "slug === 'consolidated'" in h
    assert "d.final_bias" in h
    assert "4H synth" in h


def test_individual_horizon_cards_no_primary_tag():
    """Stack honesty: 1M–60M show fusion direction + AGREE/CONFLICT only; ALL owns synthesis."""
    h = _html()
    assert "no PRIMARY on individual pills" in h
    idx = h.find("function deriveTag(slug, dir)")
    assert idx != -1
    chunk = h[idx : idx + 900]
    assert "return 'PRIMARY'" not in chunk
    assert "slug === prim" not in chunk
    assert "synthesis lives on ALL" in chunk


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
    chunk = h[idx : idx + 900]
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
        assert f"d.{field}" in h[idx : idx + 3600], f"PLAN card must read d.{field}"
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
