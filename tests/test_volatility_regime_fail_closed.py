"""volatility_regime classification guards and threshold wiring."""

from __future__ import annotations

from types import SimpleNamespace




def _inp(**kwargs):
    base = dict(
        realized_vol=0.15,
        atr=1.0,
        iv_level=0.20,
        iv_direction="expanding",
        vix_level=22.0,
        vix_vs_prev=0.5,
        garch_sigma_bars=[0.2, 0.21, 0.22, 0.23, 0.24, 0.25],
    )
    base.update(kwargs)
    return SimpleNamespace(**base)




















# ── FORMULA_P1A_REALIZED_VOL_ANNUALIZATION_FIX_V1 — timeframe-aware RV locks ──


def _rv_closes(n: int = 40) -> list[float]:
    # Deterministic alternating log-return series with nonzero variance.
    closes = [100.0]
    for i in range(1, n):
        closes.append(closes[-1] * (1.001 if i % 2 else 0.999))
    return closes


def _rv_per_bar_unrounded(closes: list[float]) -> float:
    import numpy as np

    prices = np.array(closes, dtype=np.float64)
    return float(np.std(np.diff(np.log(prices)), ddof=1))










def test_server_realized_vol_call_site_passes_1m_interval():
    """Source lock: the 1m candle path must pass bar_minutes=1.0."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert "compute_realized_vol(_closes, bar_minutes=1.0)" in src
    assert "compute_realized_vol(_closes)\n" not in src


# ── VOL_INPUT_CONTRACT 1.0.0 (lane V1) — MSD-001 rapid-branch restoration ────




