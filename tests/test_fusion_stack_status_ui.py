"""LIVE-UI-D: fused_stack_status UI parser wired in static/index.html."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_index_html_fused_stack_status_parser_and_styles():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert "function parseFusedStackStatus(" in html
    assert "function formatFusedStackStatusDisplay(" in html
    assert "stack_failed|" in html
    assert "fusion_unavailable|" in html
    assert "fusion_ok|" in html
    assert "stack-status--failed" in html
    assert "stack-status--unavailable" in html
    assert "parseFusedStackStatus(st)" in html
    assert "formatFusedStackStatusDisplay(stackParsed)" in html
