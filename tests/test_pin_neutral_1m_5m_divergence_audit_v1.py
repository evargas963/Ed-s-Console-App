"""Smoke tests for pin_neutral 1m/5m divergence audit helper SQL."""
from __future__ import annotations

from tools.pin_neutral_1m_5m_divergence_audit_v1 import bar_anchor_scope_sql


def test_bar_anchor_scope_supports_table_alias():
    s = bar_anchor_scope_sql("COALESCE(s.outcome_filled,0)=0", alias="s")
    assert "s.zone" in s
    assert "s.timeframe" in s
    assert "COALESCE(s.outcome_filled,0)=0" in s
