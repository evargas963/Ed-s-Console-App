"""server.py's tier-C payload must attach the V2 decision AFTER the decision bundle
is stamped, not before -- attaching early would silently ship a tier-C payload
built from a pre-stamp, not-yet-final decision bundle. Source-order check: the
ordering itself is the property, not derivable from behavior alone."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent








def test_v2_ui_card_removed_negative_lock():
    """Operator 2026-06-10: the V2 Pilot 1A advisory card was retired — every
    cell was a v1_approximation / not_implemented scaffold with no operator
    value. The v2 engine stays server-side (tests above lock the ms_dict
    attach + calibration-logging ordering). No agent may re-introduce the
    card or its renderer."""
    ui_source = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="v2-pilot-card"' not in ui_source
    assert 'id="v2-a2-card"' not in ui_source
    assert "function renderV2PilotDecision" not in ui_source
    assert "renderV2PilotDecision(d)" not in ui_source
    assert "A2 0DTE Advisory" not in ui_source
    assert "Draft v2 view only. Does not replace the locked v1.1 decision policy." not in ui_source

