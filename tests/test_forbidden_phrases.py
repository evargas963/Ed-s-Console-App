"""CLAUDE.md + AGENTS.md forbidden phrase enforcement (Phase 1b)."""
from __future__ import annotations

from governance.forbidden_phrases import (
    find_forbidden_phrases,
    forbidden_phrases_all,
    forbidden_phrases_from_claude,
)


def test_forbidden_phrases_list_non_empty():
    phrases = forbidden_phrases_all()
    assert len(phrases) >= 8
    assert "scope of current section" in phrases
    assert forbidden_phrases_from_claude(), "CLAUDE Schwab-only list must remain non-empty"


def test_detects_forbidden_scope_narrowing():
    hits = find_forbidden_phrases("We can treat this as scope of current section only.")
    assert "scope of current section" in hits


def test_detects_scanner_capability_phrase():
    hits = find_forbidden_phrases("The scanner doesn't walk that path.")
    assert any("scanner" in h.lower() for h in hits)


def test_clean_technical_prose_passes():
    hits = find_forbidden_phrases(
        "Read server.py end-to-end and cite file:line for each market-field site."
    )
    assert hits == []


def test_detects_by_design_excuse_phrase():
    hits = find_forbidden_phrases("The asymmetry is by design for this horizon.")
    assert "by design" in hits


def test_security_by_design_control_title_not_forbidden():
    hits = find_forbidden_phrases('("T1-09", "Security by design"),')
    assert hits == []


def test_detects_out_of_scope_excuse():
    hits = find_forbidden_phrases("panel_auto training is not in scope of this slice.")
    assert any("not in scope" in h.lower() or "out of scope" in h.lower() for h in hits)
