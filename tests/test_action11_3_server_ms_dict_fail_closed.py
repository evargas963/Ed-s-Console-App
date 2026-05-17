"""Action 11.3: server.py ms_dict consumer pass — no fabricated neutral/negligible/unknown defaults."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")

_FORBIDDEN_MS_DICT_DEFAULTS = (
    '_dpi.get("direction", "neutral")',
    '_dpi.get("magnitude", "negligible")',
    '_hedging_flow.get("direction", "neutral")',
    '_breakout_score.get("label", "negligible")',
    '_pin_score_val.get("label", "negligible")',
    '_vol_expansion.get("label", "negligible")',
    '_sweep_score.get("label", "negligible")',
    '_index_strength.get("risk_signal", "unknown")',
    '_spy_strength.get("risk_signal", "unknown")',
    '_sector_strength.get("risk_signal", "unknown")',
    '_iwm_deep.get("rotation_signal", "neutral")',
    '_iwm_deep.get("risk_score_label", "neutral")',
    '_smart_money.get("direction", "neutral")',
    '_flow_imbalance.get("normalized", 0)',
    '_smart_money.get("score", 0)',
    '_charm_dir    = "neutral"',
    '_charm_mag    = "negligible"',
    '_charm_raw.get("charm_magnitude", "negligible")',
    'compute_sector_strength(_idx_data) if _idx_data else {}',
)


def test_server_ms_dict_section8_has_no_fail_open_get_defaults():
    for pattern in _FORBIDDEN_MS_DICT_DEFAULTS:
        assert pattern not in SERVER, f"fail-open pattern still present: {pattern}"


def test_server_ms_dict_section8_uses_bare_get_for_dpi():
    assert 'ms_dict["dpi_direction"]         = _dpi.get("direction")' in SERVER
    assert 'ms_dict["hedging_flow_direction"]  = _hedging_flow.get("direction")' in SERVER
