"""Action 12.13: signal_layer_v1 fail-closed MTF signs + direction probs + fusion blend."""

from __future__ import annotations

import math




def _synth_bars(n: int, t0: float = 1_000_000.0) -> list[dict]:
    bars = []
    for k in range(n):
        be = t0 + float(k + 1) * 60.0
        bs = be - 60.0
        c = 100.0 + 0.02 * float(k) + 0.15 * math.sin(k * 0.05)
        bars.append(
            {
                "bar_start_ts_utc": bs,
                "bar_end_ts_utc": be,
                "open": c - 0.01,
                "high": c + 0.05,
                "low": c - 0.05,
                "close": c,
                "volume": 1e6 + float(k) * 100.0,
            }
        )
    return bars








def test_signal_layer_f_rejects_nan() -> None:
    from pathlib import Path

    from features.signal_layer_v1 import _f

    assert _f(float("nan")) is None
    assert _f(float("inf")) is None
    src = Path(__file__).resolve().parents[1] / "features" / "signal_layer_v1.py"
    body = src.read_text(encoding="utf-8")
    assert "return float_finite_or_none(x)" in body
    assert "math.isnan" not in body.split("def _f")[1].split("\ndef ")[0]












