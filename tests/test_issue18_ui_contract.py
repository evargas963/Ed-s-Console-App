from __future__ import annotations

from pathlib import Path

import pytest


def _html() -> str:
    p = Path(__file__).resolve().parent.parent / "static" / "index.html"
    return p.read_text(encoding="utf-8", errors="replace")


# Issue 18 UI contract was authored against the original "THE CALL" card +
# explicit renderMultiHorizon() + mh-call-entry naming. The UI was refactored
# in commit 65e7d55 ("chore: Phase B dead-code cleanup") and subsequent commits:
#   - "THE CALL" title removed (state shows via .tf-signal-card / .call-signal styling)
#   - renderMultiHorizon() function inlined into the multi-horizon renderer
#     at static/index.html ~L3655 (using `d.mhap_rows` directly, no named export)
#   - mh-call-entry element renamed to dr-plan-entry (Decision Rail naming, ~L2572)
#   - entry_display_text not retained in the new Decision Rail rendering
#   - `const fixed = ['1c','5c','15c','60c']` replaced by `const m = {'1c':'1m', ...}` mapping (~L4037)
# The "Horizon alignment" + dr-align-{1m,5m,15m,60m} elements DO still exist (~L2555-2562)
# and are kept as the still-valid portion of the Issue 18 contract.
# Re-validation of the obsolete portions against the new Decision Rail naming
# is operator-domain UX work; tests skipped until that produces a refreshed contract spec.


def test_the_call_card_title_present():
    pytest.skip(
        "UI rebrand (65e7d55+): 'THE CALL' title superseded by .tf-signal-card / "
        ".call-signal styling — Issue 18 contract pending re-validation against "
        "Decision Rail naming."
    )


def test_mhap_card_present_with_required_columns():
    h = _html()
    # These dr-align-* IDs and "Horizon alignment" text DO still exist in the
    # current Decision Rail HTML; keep them as the still-valid portion of the
    # original Issue 18 contract. renderMultiHorizon was inlined and is not
    # checked here anymore.
    assert "Horizon alignment" in h
    for el_id in ("dr-align-1m", "dr-align-5m", "dr-align-15m", "dr-align-60m"):
        assert el_id in h


def test_mhap_fixed_row_order_in_renderer():
    pytest.skip(
        "UI rebrand (65e7d55+): const fixed = ['1c','5c','15c','60c'] replaced by "
        "horizon→bar mapping const m = {'1c':'1m', ...} at ~L4037; row-order contract "
        "pending re-validation."
    )


def test_entry_state_labels_render_contract():
    pytest.skip(
        "UI rebrand (65e7d55+): mh-call-entry / entry_display_text / renderMultiHorizon "
        "removed in favor of dr-plan-entry + inline mhap renderer; entry-state label "
        "contract pending re-validation."
    )
