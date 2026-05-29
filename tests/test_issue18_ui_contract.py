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
    """Horizon-alignment block exists with the 4 dr-align-* slots (current Decision Rail)."""
    h = _html()
    assert "Horizon alignment" in h
    for el_id in ("dr-align-1m", "dr-align-5m", "dr-align-15m", "dr-align-60m"):
        assert el_id in h


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


def test_render_tier_c_pending_shell_repaints_cards_when_mhap_present():
    h = _html()
    assert "renderTierCPendingShell" in h
    assert "renderTimeframeSignalRow(merged)" in h
    assert "renderDecisionCommandRail(merged)" in h


def test_timeframe_cards_show_loading_when_analytics_pending_without_mhap():
    h = _html()
    assert "tf-signal-card--analytics-loading" in h
    assert "analyticsLoading && mhap.length === 0" in h


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


# ── UI card provenance spec — chip + signal-rail-card surfaces ─────────────
# Brief: ACTIVE_PROGRAM.md §UI card provenance spec. Chip vocabulary is the
# five-state set EMPIRICAL | ML FUSION | BLEND | UNAVAILABLE | DEGRADED. The
# unified signal-rail-card below the 4 horizon pills carries the fusion
# verdict (top) + empirical context (bottom), with Entry armed / Stack
# degraded inline authority tags (same shape language, opposite verdicts).

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
    """Each of the four tf-signal-cards carries a chip + detail element.

    There are exactly four cards (1c/5c/15c/60c), so each class must appear
    at least four times in the HTML body.
    """
    h = _html()
    assert h.count('class="tf-source-chip ') >= 4
    assert h.count('class="tf-source-detail"') >= 4


def test_signal_rail_card_css_and_html_present():
    """Unified signal-rail-card — fusion verdict + empirical context below the
    four pills. CSS defines all 4 state variants and the inline structure."""
    h = _html()
    assert ".signal-rail-card {" in h
    assert ".signal-rail-card--up" in h
    assert ".signal-rail-card--down" in h
    assert ".signal-rail-card--withheld" in h
    assert ".signal-rail-card--armed" in h
    # HTML structure
    assert 'id="signal-rail-card"' in h
    assert 'id="signal-rail-top"' in h
    assert 'id="signal-rail-bottom"' in h
    # Sub-section IDs that renderSignalRailCard populates
    assert 'id="src-fas-label"' in h
    assert 'id="src-fas-dir"' in h
    assert 'id="src-fas-agreement"' in h
    assert 'id="src-ecl-tier"' in h
    assert 'id="src-ecl-n"' in h
    assert 'id="src-ecl-probs"' in h


def test_authority_tags_defined_for_armed_and_degraded():
    """Solid-color authority pills — same shape language, opposite verdicts.

    fas-armed-tag (solid green) when primary horizon fires; fas-degraded-tag
    (solid red) when stack_integrity_v1.degraded is true.
    """
    h = _html()
    assert ".fas-armed-tag {" in h
    assert ".fas-degraded-tag {" in h
    assert "Entry armed" in h
    assert "Stack degraded" in h


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


def test_render_signal_rail_card_function_present():
    """renderSignalRailCard paints the unified card; hides itself when mhap empty."""
    h = _html()
    assert "function renderSignalRailCard(d)" in h
    assert "window.renderSignalRailCard = renderSignalRailCard" in h
    # Hidden in pending-shell case
    assert "if (pending && mhap.length === 0) { card.style.display = 'none'; return; }" in h
    # Authority tags applied in the top section
    assert "'fas-degraded-tag'" in h
    assert "'fas-armed-tag'" in h
    # "Not tradable" fallback when fusion is withheld
    assert "Not tradable — empirical context only" in h
    # canonical_provenance gate uses isCanonicalTradable + isFusionAuthoritative
    assert "isFusionAuthoritative(d)" in h
    assert "isCanonicalTradable(d)" in h


def test_signal_rail_empirical_tracks_primary_horizon():
    """Empirical context binds to the PRIMARY decision horizon (not a fixed 5m), with a
    dynamic EMPIRICAL label, so the base rate corresponds to the trade armed on top.
    Anti-revert lock for the 2026-05-28 fix (was hardcoded horizon_prob_bars['5m'])."""
    h = _html()
    # dynamic label element present
    assert 'id="src-ecl-label"' in h
    # JS reads the primary horizon's bar via the shared pLabel mapping, not a fixed 5m
    assert "d.horizon_prob_bars[pLabel]" in h
    assert "labelEl.textContent = 'Empirical (' + primary + ')'" in h
    # the empirical bottom must not re-pin to the fixed-5m bar
    assert "d.horizon_prob_bars['5m']" not in h


def test_paint_source_chip_uses_new_selectors():
    """paintSourceChip targets .tf-source-chip + .tf-source-detail (new design),
    not the dormant legacy .tf-source element."""
    h = _html()
    assert "function paintSourceChip(card, payload, slugKey, dirVal)" in h
    assert "card.querySelector('.tf-source-chip')" in h
    assert "card.querySelector('.tf-source-detail')" in h
    # Delegates to top-level deriveSourceForHorizon helpers
    assert "deriveSourceForHorizon(payload, slugKey)" in h


def test_render_signal_rail_card_wired_into_all_render_entry_points():
    """renderSignalRailCard is invoked from every render path that paints the row.

    render() (full analytical), renderTierCPendingShell (pending shell),
    renderTierALive (instant quote), renderTierBLight (L1 context). All four
    must call it so the rail card stays in lockstep with the horizon pills.
    """
    h = _html()
    # 4 call sites + 1 definition + 1 window export ≥ 6 occurrences
    assert h.count("renderSignalRailCard(") >= 5
    assert "renderSignalRailCard(d)" in h         # render() full path
    assert "renderSignalRailCard(merged)" in h    # renderTierCPendingShell
    assert "renderSignalRailCard(window._lastData)" in h  # Tier A + Tier B


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


# ── UI design lock — operator verdict 2026-05-27 ──────────────────────────
# These surfaces were intentionally removed and MUST NOT be re-introduced.
# Re-adding any of them fails this suite — mechanical enforcement against
# Cursor (or any agent) reverting the operator-approved chip + signal-rail-card
# design back to parallel / dormant / redundant surfaces.
#
# Removed:
#   - Cursor's parallel dr-fusion-authority-strip + dr-empirical-context-line
#     inside the Decision Rail ("no co-existing your design rules")
#   - Decision Command verdict row (dr-trade-pill / dr-bias-pill /
#     dr-desk-confidence / dr-confidence-pill) — duplicated signal-rail-card
#   - Decision Command title strip ("DECISION COMMAND · Operator surface…")
#   - Dormant legacy .tf-source CSS rules
# Single source of truth = signal-rail-card + .tf-source-chip system.

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


def test_signal_rail_card_is_present_positive_lock():
    """Single source of truth — the unified signal-rail-card MUST stay."""
    h = _html()
    assert 'id="signal-rail-card"' in h
    assert 'function renderSignalRailCard(d)' in h
    assert 'Entry armed' in h
    assert 'Stack degraded' in h


# ── Signals Rail — operator design 2026-05-27 (binding) ───────────────────
# Vertical analytics column to the right of horizon row + signal-rail-card.
# Severity grammar matches signal-rail-card: quiet → building → hot (+ positive
# green). Each slot is a self-contained signal (Level Test first). Adding /
# removing slots = changing #signals-rail children.

def test_signals_rail_layout_present():
    """Top-stack split (post-2026-05-27 restructure for height uniformity):
    .top-stack-row contains horizon pills + Signals Rail as direct flex
    siblings (align-items: stretch makes the Level Test slot match the
    rendered horizon-card height). #signal-rail-card was promoted to a
    full-width sibling BELOW the row. Header + multi-slot variants stay
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
    """Same color contract as signal-rail-card — operator learns one grammar."""
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
    """Entry state contract — mh-call-entry was renamed to dr-plan-entry (Decision Rail);
    entry_display_text is still the live field; renderMultiHorizon was inlined into the
    mhap renderer that reads d.mhap_rows directly.
    """
    h = _html()
    assert "dr-plan-entry" in h  # replaced mh-call-entry element id
    assert "entry_display_text" in h  # unchanged live field name
    # Inline mhap renderer pattern (renderMultiHorizon was inlined into this block).
    assert "d.mhap_rows" in h
