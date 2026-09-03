"""FIND-LIVEUI-6 static guard — Phase 2 direction-withhold wiring.

Locks the implementation shape that the LIVE-UI-1 inventory specified
(docs/STACK_WIRING_INTEGRITY_MAP.md, "Live-UI direction transports
(LIVE-UI-1, Phase 2)"):

  * bundleDirectionWithheld(integrity, d, nowMs) helper — pure function, returns
    {withheld, reason}. Keyed on the conditions in the inventory:
    analytics_pending_shell, _priceAheadOfBundle, slowStaleVsFast,
    quoteAhead, genStale, pending_full_analytics — plus the institutional
    bundle-trust window (bundleWithinTrustWindow) that suppresses false STALE.
  * horizonDirectionWithheld(integrity, d, hz, nowMs) — extends bundle-level with
    horizon_fusion_available(hz) (MHMLB-NS1 hook), else fusion_available.
  * _updateDirectionWithheldMarkers — sets data-direction-withhold on a
    closed list of bundle-level IDs + per-horizon IDs + tf-signal-{slug}.
  * _updateTierCLaneStaleMarkers alignment — must include
    slowStaleVsFast and/or window._priceAheadOfBundle so the card-level
    lane-stale dim matches the bundleDirectionWithheld() cross-tier rule.
  * _updateLiveUiAe wires _updateDirectionWithheldMarkers into the same
    refresh cycle as _updateTierCLaneStaleMarkers / _updateCoherenceHeadline.
  * CSS rule for [data-direction-withhold] in the existing <style> block.

OF strip is intentionally NOT covered by these helpers — it has its own
order_flow_stale clock (FIND-WIRE5-2..3 already locks producer side).
"""

from __future__ import annotations

import re
from pathlib import Path

INDEX_HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _src() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_bundle_direction_withheld_helper_exists():
    """Signature gained nowMs when the institutional bundle-trust window landed."""
    src = _src()
    assert "function bundleDirectionWithheld(integrity, d, nowMs)" in src
    assert "window.bundleDirectionWithheld = bundleDirectionWithheld" in src


def test_horizon_direction_withheld_helper_exists():
    src = _src()
    assert "function horizonDirectionWithheld(integrity, d, hz, nowMs)" in src
    assert "window.horizonDirectionWithheld = horizonDirectionWithheld" in src


def test_bundle_direction_withheld_covers_all_inventory_conditions():
    """Every reason the LIVE-UI-1 inventory names must be reachable in the helper body."""
    src = _src()
    fn_match = re.search(
        r"function bundleDirectionWithheld\(integrity, d, nowMs\)\s*\{(.+?)\n\}",
        src,
        re.DOTALL,
    )
    assert fn_match, "bundleDirectionWithheld must be defined with extractable body"
    body = fn_match.group(1)
    for reason in (
        "pending_shell",
        "price_ahead_of_bundle",
        "slow_stale_vs_fast",
        "quote_ahead",
        "gen_stale",
        "pending_full_analytics",
    ):
        assert f"'{reason}'" in body or f'"{reason}"' in body, (
            f"bundleDirectionWithheld must emit reason {reason!r} per LIVE-UI-1 inventory"
        )


def test_horizon_direction_withheld_reads_horizon_fusion_available_map():
    """MHMLB-NS1 hook: per-horizon availability map preferred, else bundle-level fusion_available."""
    src = _src()
    fn_match = re.search(
        r"function horizonDirectionWithheld\(integrity, d, hz, nowMs\)\s*\{(.+?)\n\}",
        src,
        re.DOTALL,
    )
    assert fn_match, "horizonDirectionWithheld must be defined"
    body = fn_match.group(1)
    assert "horizon_fusion_available" in body
    assert "horizon_fusion_unavailable" in body
    assert "fusion_unavailable" in body
    assert "bundleDirectionWithheld(integrity, d, nowMs)" in body


def test_update_direction_withheld_markers_function_exists():
    src = _src()
    assert "function _updateDirectionWithheldMarkers()" in src
    assert "data-direction-withhold" in src


def test_bundle_direction_id_registry_present():
    """ID registry must include every direction-bearing element named in renderDecisionCommandRail."""
    src = _src()
    list_match = re.search(
        r"_LIVEUI6_BUNDLE_DIRECTION_IDS\s*=\s*\[(.+?)\];",
        src,
        re.DOTALL,
    )
    assert list_match, "bundle ID registry must exist"
    body = list_match.group(1)
    # dr-trade-pill / dr-bias-pill / dr-desk-confidence / dr-confidence-pill,
    # the rail Trade-plan block (dr-plan-*) and the rail Why/gates ids
    # (dr-action-chip / dr-blocking-reason / dr-exact-reason /
    # dr-live-ready-chip) were retired; the ALL pill (verdict + WAIT reason)
    # and PLAN pill (entry/stop/targets/invalidation/size) are the
    # bundle-level direction surfaces.
    for expected in (
        "tf-signal-consolidated",
        "tf-signal-plan",
    ):
        assert f"'{expected}'" in body, (
            f"_LIVEUI6_BUNDLE_DIRECTION_IDS must register {expected!r}"
        )
    for retired in (
        "dr-action-chip",
        "dr-blocking-reason",
        "dr-exact-reason",
        "dr-live-ready-chip",
    ):
        assert f"'{retired}'" not in body, (
            f"{retired!r} was retired 2026-06-10 — must stay out of the registry"
        )


def test_per_horizon_id_registry_uses_canonical_slugs():
    """Per-horizon map keyed on 1c/5c/15c/60c (NOT product labels 1m/5m/15m/60m).
    Values are empty since the rail Horizon-alignment block (dr-align-*) was
    retired 2026-06-10 — the marker loop still covers each #tf-signal-{slug} card."""
    src = _src()
    map_match = re.search(
        r"_LIVEUI6_HORIZON_DIRECTION_IDS\s*=\s*\{(.+?)\};",
        src,
        re.DOTALL,
    )
    assert map_match, "per-horizon ID map must exist"
    body = map_match.group(1)
    for hz in ("1c", "5c", "15c", "60c"):
        assert f"'{hz}'" in body
    assert "dr-align" not in body, "rail dr-align-* ids must stay removed (duplicative)"
    # The loop itself still marks the pill cards per horizon.
    assert "document.getElementById('tf-signal-' + hz)" in src


def test_tier_c_lane_stale_markers_includes_slow_stale_vs_fast():
    """Operator call-out: _updateTierCLaneStaleMarkers must include slowStaleVsFast / _priceAheadOfBundle."""
    src = _src()
    fn_match = re.search(
        r"function _updateTierCLaneStaleMarkers\(\)\s*\{(.+?)\n\}",
        src,
        re.DOTALL,
    )
    assert fn_match, "_updateTierCLaneStaleMarkers must exist"
    body = fn_match.group(1)
    assert "slowStaleVsFast" in body, (
        "_updateTierCLaneStaleMarkers must check integrity.slowStaleVsFast — operator call-out "
        "in FIND-LIVEUI-6 plan; pre-fix only checked quoteAhead || pending || genStale, leaving "
        "the price-ahead-of-bundle case undimmed at the card level"
    )
    assert "_priceAheadOfBundle" in body


def test_update_live_ui_ae_calls_direction_withheld_marker():
    """Wire-in: _updateLiveUiAe must invoke _updateDirectionWithheldMarkers each refresh."""
    src = _src()
    fn_match = re.search(
        r"function _updateLiveUiAe\(opts\)\s*\{(.+?)\n\}",
        src,
        re.DOTALL,
    )
    assert fn_match, "_updateLiveUiAe must exist"
    body = fn_match.group(1)
    assert "_updateDirectionWithheldMarkers()" in body


def test_css_data_direction_withhold_rule_exists():
    """CSS rule must dim + mark direction-withheld nodes — visible operator signal, not silent."""
    src = _src()
    style_match = re.search(r"<style>(.+?)</style>", src, re.DOTALL)
    assert style_match, "must have a <style> block"
    css = style_match.group(1)
    assert "[data-direction-withhold]" in css
    assert "STALE" in css, "CSS must emit a visible 'STALE' badge via ::after content"


def test_of_strip_remains_on_its_own_clock_not_in_marker_registry():
    """Bundle-level ID registry must NOT include OF strip ids — OF has its own order_flow_stale gate."""
    src = _src()
    list_match = re.search(
        r"_LIVEUI6_BUNDLE_DIRECTION_IDS\s*=\s*\[(.+?)\];",
        src,
        re.DOTALL,
    )
    assert list_match, "bundle ID registry must exist"
    body = list_match.group(1)
    # Common OF-strip ids that must NOT appear — keeping the inventory's
    # "L1 OF lane vs Tier C bundle lane independent clocks" rule honest.
    for forbidden in ("of-verdict", "b-of-verdict", "order-flow", "of-strip"):
        assert forbidden not in body, (
            f"_LIVEUI6_BUNDLE_DIRECTION_IDS must NOT include {forbidden!r} — "
            "OF strip is gated by order_flow_stale (its own clock), not bundleDirectionWithheld"
        )
