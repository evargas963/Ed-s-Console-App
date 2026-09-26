"""Governance dashboard UI: structure and API contract only — no client-side policy logic."""
from __future__ import annotations

from pathlib import Path







def test_governance_html_has_dashboard_sections():
    root = Path(__file__).resolve().parent.parent
    html = (root / "static" / "governance.html").read_text(encoding="utf-8")
    for sid in (
        "sec-architecture",
        "sec-drift",
        "sec-operational-policy",
        "sec-notifications",
        "sec-audit",
        "sec-actions",
    ):
        assert f'id="{sid}"' in html


def test_governance_html_only_uses_governance_api_routes():
    root = Path(__file__).resolve().parent.parent
    html = (root / "static" / "governance.html").read_text(encoding="utf-8")
    assert "/api/governance/panel" in html
    assert "/api/governance/manual-promote" in html
    assert "/api/governance/manual-rollback" in html
    assert html.count("/api/governance/manual-promote") >= 1
    assert "manual_promote_to_active_explicit" not in html
    assert "manual_rollback_to_checkpoint_explicit" not in html








