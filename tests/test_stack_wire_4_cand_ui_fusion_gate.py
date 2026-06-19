"""STACK-WIRE-3-UI-FUSION-TRADABILITY-GATE — UI mirror of the fusion tradability gate.

Static-HTML guard tests. The UI must not steer detail chips, signal-chain steps, or
direction off of bare ``d.fusion_available`` — the split-brain (fusion_available=True +
canonical_provenance="canonical_forecast_missing") was the regression closed for the
server rail in STACK-WIRE-4-CAND. These tests pin the UI side: the helper exists, the
three known consumer sites go through it, and the helper's gate matches
``fusion_contract.is_ms_dict_fusion_authoritative`` semantics (fall-back also requires
provenance ∈ TRADABLE_CANONICAL_PROVENANCE = {"bayesian_fusion"}).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")


def test_is_fusion_authoritative_helper_defined():
    assert "function isFusionAuthoritative(d)" in HTML, "UI helper missing"
    helper_idx = HTML.index("function isFusionAuthoritative(d)")
    helper_body = HTML[helper_idx : HTML.index("\n}\n", helper_idx) + 2]
    # stack_runtime.fusion_active is the primary truth (server-stamped after WIRE-4-CAND).
    assert "stack_runtime" in helper_body
    assert "fusion_active" in helper_body
    # Fallback gate must include BOTH bare flag AND tradable provenance — not flag alone.
    assert "fusion_available" in helper_body
    assert "canonical_provenance" in helper_body
    assert "bayesian_fusion" in helper_body


def test_dr_stack_fusion_chip_uses_helper_not_bare_flag():
    """Operator 2026-06-10: the Stack-behind-the-call rail block (dr-stack-*)
    was retired — duplicative with the signal-chain bar (whose FUSION step is
    pinned to isFusionAuthoritative below). Negative lock: the chip must stay
    removed AND the pre-fix bare-flag steering pattern must not reappear
    anywhere."""
    assert "dr-stack-fusion" not in HTML, "dr-stack-fusion was retired — must stay removed"
    # The pre-fix pattern (bare ternary on d.fusion_available) must stay gone repo-surface-wide.
    assert "d.fusion_available ? 'active'" not in HTML
    assert "d.fusion_available ? 'inactive'" not in HTML


def test_resolve_signal_chain_fusion_step_uses_helper():
    fn_start = HTML.index("function resolveSignalChain(d)")
    fn_end = HTML.index("\n}\n", fn_start)
    body = HTML[fn_start:fn_end]
    # The fusion step of the signal chain must come from the gated helper.
    assert "isFusionAuthoritative(d)" in body
    assert "!!d.fusion_available" not in body, "bare fusion_available read still present in resolveSignalChain"


def test_effective_direction_uses_helper_not_bare_flag():
    fn_start = HTML.index("function effectiveDirection(x)")
    fn_end = HTML.index("\n}\n", fn_start)
    body = HTML[fn_start:fn_end]
    # Direction selector must gate fusion_dominant_direction reads on tradability.
    assert "isFusionAuthoritative(x)" in body
    assert "if (x.fusion_available)" not in body, (
        "effectiveDirection still uses bare fusion_available — split-brain payload would "
        "steer direction off non-tradable fusion_dominant_direction."
    )


def test_is_canonical_tradable_helper_defined():
    """LIVE-UI-A: UI mirror of fusion_contract.canonical_provenance_is_tradable.
    Used to gate non-fusion code paths that still read canonical-derived mass
    (e.g. effectiveDirection fallback, per-horizon fused probs)."""
    assert "function isCanonicalTradable(d)" in HTML, "LIVE-UI-A: isCanonicalTradable helper missing"
    helper_idx = HTML.index("function isCanonicalTradable(d)")
    helper_body = HTML[helper_idx : HTML.index("\n}\n", helper_idx) + 2]
    assert "canonical_provenance" in helper_body
    assert "bayesian_fusion" in helper_body
    assert "toLowerCase" in helper_body, "helper must lowercase before compare (defensive against payload casing)"


def test_effective_direction_fallback_gated_on_canonical_tradable():
    """LIVE-UI-A: when fusion is non-authoritative, effectiveDirection must NOT fall back to
    dominant_dir / prediction_dir unless canonical is tradable."""
    fn_start = HTML.index("function effectiveDirection(x)")
    fn_end = HTML.index("\n}\n", fn_start)
    body = HTML[fn_start:fn_end]
    assert "isCanonicalTradable(x)" in body, (
        "effectiveDirection fallback path must check isCanonicalTradable(x) before reading "
        "dominant_dir / prediction_dir — non-tradable canonical leaks placeholder direction."
    )
    assert body.count("return null") >= 2, (
        "effectiveDirection should have ≥2 null-return paths after LIVE-UI-A gate "
        "(early !x guard + non-tradable canonical withhold)"
    )


def test_per_horizon_move_p_gated_on_fusion_authoritative():
    """LIVE-UI-A: per-horizon Move P and Fused Confidence are fusion-derived mass.
    Must be withheld ('—') when isFusionAuthoritative(d) is false."""
    move_p_idx = HTML.index("addKV(grid, 'Move P',")
    move_p_line_end = HTML.index("\n", move_p_idx)
    move_p_render = HTML[move_p_idx:move_p_line_end]
    assert "fusionActive" in move_p_render or "isFusionAuthoritative" in move_p_render, (
        f"Move P render not gated on fusion authority: {move_p_render!r}"
    )
    fc_idx = HTML.index("addKV(grid, 'Fused Confidence'")
    fc_context_start = HTML.rfind("\n", 0, fc_idx - 400)
    fc_context = HTML[fc_context_start:fc_idx]
    assert "fusionActive" in fc_context or "isFusionAuthoritative" in fc_context, (
        f"Fused Confidence render not gated on fusion authority. Context:\n{fc_context[-400:]!r}"
    )
