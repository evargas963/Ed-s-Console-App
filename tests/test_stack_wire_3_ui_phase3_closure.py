"""STACK-WIRE-3-UI Phase 3 closure — five OPEN_ITEMS rows closed in one slice.

Each test pins one of the WIRE-3-UI-* contracts that was filed at STACK-WIRE-0 (@054c873)
and has been sitting unaudited since. Producer side already lands these fields; this slice
is the consumer-side closure with the operator-visible UI bind + withheld semantics.

Rows closed:
  - STACK-WIRE-3-UI-SPREAD-SEMANTIC
  - STACK-WIRE-3-UI-PRESSURE-UNAVAILABLE
  - STACK-WIRE-3-UI-R-UNITS-NONE
  - STACK-WIRE-3-UI-SIGNALS-ENGINE-FAILED-BADGE
  - STACK-WIRE-3-UI-IV-RANK
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")


def test_wire3_ui_spread_semantic_consumer_dispatch():
    """UI dispatches on producer-stamped d.spread_semantic ∈ {"fraction", "dollar"} with
    legacy heuristic preserved as back-compat when the field is absent. Single authority:
    computeSpreadGate(inp) — render() and Playwright spec both call the same function so
    they cannot drift on a future edit.
    Producer: server.py:839 (fast quote, "fraction"), server.py:3058 (Tier A, "dollar").
    """
    # Single authority defined.
    assert "function computeSpreadGate(inp)" in HTML, (
        "Single authority computeSpreadGate(inp) must exist (called by both render() and "
        "Playwright behavioral spec)."
    )
    # Dispatcher gates on the producer tag inside the helper.
    assert "isFraction = sem === 'fraction'" in HTML
    assert "isDollar = sem === 'dollar'" in HTML
    # Fraction is unit-less — must NOT do /spot conversion (the Cursor-flagged bug).
    assert "isFraction\n    ? false" in HTML, (
        "Fraction path must force isPxWidth=false (fraction is already unit-less; gate "
        "compares against 0.05 directly, not 0.05/spot). This is the Cursor-flagged "
        "fraction regression."
    )
    # render() consumes via the helper — no duplicated inline dispatcher.
    assert "computeSpreadGate({" in HTML, "render() must call computeSpreadGate (no inline dup)"
    # The pre-dedup inline pattern (introduced be67e57 first attempt, removed in dedup commit)
    # must not be re-introduced.
    assert "const _spdSemFraction = _spdSemRaw" not in HTML, (
        "render() must not re-inline the dispatcher (use computeSpreadGate via destructure)."
    )
    assert "STACK-WIRE-3-UI-SPREAD-SEMANTIC" in HTML, "marker comment for grep traceability"
    # Back-compat: legacy heuristic dispatch path still present inside the helper.
    assert "pxWidthRaw" in HTML
    assert "_fastLaneSpread" in HTML


def test_wire3_ui_pressure_label_unavailable_treated_as_withheld():
    """Producer can emit pressure_label="unavailable_no_dpi_or_hedging_flow_direction" when
    neither DPI nor hedging flow yields a direction. UI must NOT render that sentinel as a
    pressure value — it is the withheld signal. Current UI does not consume pressure_label at
    all (no DOM bind), so the withhold semantic is trivially satisfied; this guard locks that
    contract so a future re-introduction doesn't accidentally display the sentinel.
    """
    # No DOM bind for pressure_label means the "unavailable" sentinel is never user-visible.
    assert "pressure_label" not in HTML, (
        "If pressure_label is re-introduced to UI, you MUST gate the render on the sentinel "
        "value 'unavailable_no_dpi_or_hedging_flow_direction' and surface as withheld (em-dash), "
        "not as a literal label."
    )
    assert "unavailable_no_dpi_or_hedging_flow_direction" not in HTML


def test_wire3_ui_r_units_none_treated_as_withheld():
    """signal_types.TheCall.r_units is Optional[float] = None (FIND-WIRE1-1 @ e65d2c2);
    market_state.py sets r_units=None when prerequisites missing (FIND-WIRE1-1 producer chain).
    UI must treat None as withheld (em-dash), never as 0.
    Current UI does not consume r_units (no DOM bind) — withhold is trivially satisfied. This
    guard locks that contract.
    """
    assert "r_units" not in HTML, (
        "If r_units is bound to UI, you MUST guard on null/undefined and render as withheld "
        "(em-dash), never substitute 0. r_units=0 means 'zero risk-units' which is a real value; "
        "r_units=None means 'withheld'."
    )


def test_wire3_ui_signals_engine_failed_badge_present():
    """stack_runtime.signals_engine_failed is stamped at server.py:5365-5368 when the signals/
    market-state pipeline crashes (distinct from stack_mode=INVALID which is a fusion/MC
    prerequisite gap). Operator surface MUST distinguish — a signals crash means upstream fields
    are partial/stale, not just fusion missing.
    """
    # HTML element exists.
    assert 'id="dr-signals-engine-fail-chip"' in HTML
    # JS reads the field from stack_runtime, not from d directly.
    assert "rt.signals_engine_failed" in HTML
    # Dedicated update function (chip is independent of stack_mode chip).
    assert "function _updateSignalsEngineFailChip(" in HTML
    assert "SIGNALS ENGINE FAILED" in HTML
    # Wired into the integrity refresh + update orchestration.
    assert "_updateSignalsEngineFailChip(integrity)" in HTML
    assert "signalsEngineFailed" in HTML


def test_wire3_ui_operator_truth_chips_live_ui_b_e_g():
    """LIVE-UI-B/E/G: stack degradation, MH promotion, session boundary chips on Decision Command."""
    assert 'id="dr-stack-integrity-degraded-chip"' in HTML
    assert 'id="dr-mh-promotion-chip"' in HTML
    assert 'id="dr-session-boundary-chip"' in HTML
    assert "function _updateStackIntegrityDegradedChip(" in HTML
    assert "function _updateMhPromotionChip(" in HTML
    assert "function _updateSessionBoundaryChip(" in HTML
    assert "_updateStackIntegrityDegradedChip(integrity)" in HTML
    assert "_updateMhPromotionChip(integrity)" in HTML
    assert "_updateSessionBoundaryChip(integrity)" in HTML


def test_wire3_ui_iv_rank_bound_with_withhold_semantic():
    """iv_rank and iv_percentile land on ms_dict (server.py:4998-4999). UI binds in the
    Volatility regime subsection of the context layer; None renders as em-dash (withheld),
    never zero (zero would mean lowest-on-record which is a real value).
    """
    # Subsection header and both rows present.
    assert "Volatility regime" in HTML
    assert 'id="ctx-iv-rank"' in HTML
    assert 'id="ctx-iv-percentile"' in HTML
    # JS reads from d.iv_rank / d.iv_percentile.
    assert "d.iv_rank" in HTML
    assert "d.iv_percentile" in HTML
    # Withhold semantic: em-dash on None / NaN, NOT zero.
    assert "_fmtIvBp" in HTML
