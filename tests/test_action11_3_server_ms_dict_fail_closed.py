"""Action 11.3/11.3b: server.py ms_dict assembly — no fabricated .get(key, default) fallbacks."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")

_FORBIDDEN_MS_DICT_DEFAULTS = (
    # 11.3 — Section 8 + sector/IWM/smart-money
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
    # 11.3b — EM, iv skew, level density, vol_oi, iv_model_spread, compliance
    '_em_progress.get("breached", False)',
    '_em_progress.get("severity", "unknown")',
    '_iv_skew.get("interpretation", "")',
    '_level_density.get("count", 0)',
    '_level_density.get("density_label", "unknown")',
    '_level_density.get("level_names", [])',
    '_vol_oi_ratio.get("label", "unknown")',
    '_iv_model_spread.get("label", "unknown")',
    '_comp.get("issues", [])',
    '"severity": "unknown"',
)


def test_server_ms_dict_assembly_has_no_fail_open_get_defaults():
    for pattern in _FORBIDDEN_MS_DICT_DEFAULTS:
        assert pattern not in SERVER, f"fail-open pattern still present: {pattern}"












