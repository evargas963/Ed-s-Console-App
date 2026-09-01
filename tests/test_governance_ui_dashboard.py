"""Governance dashboard UI: structure and API contract only — no client-side policy logic."""
from __future__ import annotations

import json
from pathlib import Path

from arch_competition.governance_visibility import build_governance_panel_payload
from arch_competition.manual_control import (
    MANUAL_PROMOTE_CASCADE_INTENT,
    MANUAL_PROMOTE_PARALLEL_INTENT,
    MANUAL_ROLLBACK_INTENT,
)


def _minimal_governed_files(model_dir: Path, *, cascade_ok: bool = True):
    from tests.test_governance_dashboard import _minimal_governed_files as f

    f(model_dir, cascade_ok=cascade_ok)


def test_governance_route_serves_dashboard_html():
    """TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (TestClient adjudication): REWRITE.
    governance_visibility_page takes no parameters, no Request, no auth, no
    middleware; it reads static/governance.html off disk and returns an HTMLResponse
    (with its own 404 HTMLResponse when the file is absent). The StaticFiles mount is
    at /static -- a disjoint prefix -- so there is no route-shadowing question of the
    kind test_single_producer_batch_f02_f13_v1 guards for the RTH-clock route. The
    HTTP round trip re-proved nothing the response object does not already carry."""
    import server

    resp = server.governance_visibility_page()
    assert resp.status_code == 200
    text = resp.body.decode("utf-8")
    assert "sec-architecture" in text
    assert "Governance dashboard" in text


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


def test_panel_payload_contains_all_dashboard_sections(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "proj"
    models_dir = project_root / "models"
    _minimal_governed_files(models_dir, cascade_ok=True)
    (models_dir / "arch_state.json").write_text(
        json.dumps({"SPY": {"active_architecture": "parallel"}}),
        encoding="utf-8",
    )
    p = build_governance_panel_payload(
        models_dir,
        "1c",
        "SPY",
        include_live_drift=False,
        emit_notification_delivery=False,
    )
    assert p["ok"] is True
    assert p["production_default_runtime"] == "parallel"
    assert "incumbent_architecture" in p
    assert "operational_policy" in p
    assert "recent_notification_deliveries" in p
    assert isinstance(p["recent_audit_actions"], list)


def test_api_governance_panel_emit_notifications_query(monkeypatch, tmp_path: Path):
    """TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (TestClient adjudication): KEEP.
    The distinct HTTP-boundary defect is FastAPI's query-string -> bool coercion.
    api_governance_panel declares `emit_notifications: bool = Query(False, ...)`, and
    this test sends the literal STRING "false" the way a browser does. A direct call
    would hand the handler an already-typed Python False and could never catch the
    real regression here: the param losing its bool annotation, so the truthy string
    "false" starts arming live notification delivery on every routine panel refresh."""
    project_root = tmp_path / "proj"
    models_dir = project_root / "models"
    _minimal_governed_files(models_dir, cascade_ok=True)
    (models_dir / "arch_state.json").write_text("{}", encoding="utf-8")

    import server

    monkeypatch.setattr(server, "APP_DIR", str(project_root))
    from fastapi.testclient import TestClient

    c = TestClient(server.app)
    r = c.get("/api/governance/panel", params={"ticker": "SPY", "horizon": "1c", "emit_notifications": "false"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("production_default_runtime") == "parallel"


def test_blocked_panel_disables_promotion_via_payload_flags(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "proj"
    models_dir = project_root / "models"
    _minimal_governed_files(models_dir, cascade_ok=False)
    p = build_governance_panel_payload(models_dir, "1c", "SPY", include_live_drift=False, emit_notification_delivery=False)
    assert p["ok"] is True
    assert p.get("manual_promote_cascade_enabled") is False
    assert p.get("blocked_promotion_flags")


def test_intent_constants_match_manual_control_exports():
    from arch_competition.manual_control import (
        MANUAL_PROMOTE_CASCADE_INTENT as E,
        MANUAL_PROMOTE_PARALLEL_INTENT as P,
        MANUAL_ROLLBACK_INTENT as R,
    )

    assert E == MANUAL_PROMOTE_CASCADE_INTENT
    assert P == MANUAL_PROMOTE_PARALLEL_INTENT
    assert R == MANUAL_ROLLBACK_INTENT
