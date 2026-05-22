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

import re
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
    """The detail chip on the Decision Command trust row must not read the bare flag."""
    pattern = re.compile(r"domIf\('dr-stack-fusion'[^)]*\)[^;]*;", re.DOTALL)
    match = pattern.search(HTML)
    assert match is not None, "dr-stack-fusion render call not found"
    chip_src = match.group(0)
    assert "isFusionAuthoritative(d)" in chip_src
    # The pre-fix pattern (bare ternary on d.fusion_available) must be gone from the chip.
    assert "d.fusion_available ? 'active'" not in chip_src
    assert "d.fusion_available ? 'inactive'" not in chip_src


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
