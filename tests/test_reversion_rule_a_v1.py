"""RC-7 seams for the Rule-A reversion generator (pure units)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from research.pilot_step3.data_loader import Bar1m
from tools.reversion_rule_a_study_v1 import (
    M_SIGMA,
    WARMUP_BARS,
    RuleACandidate,
    rule_a_multiples,
    scan_rule_a_candidates,
    vwap_and_deviation_sigma,
)

ET = ZoneInfo("America/New_York")
REAL = "schwab_1m_accumulator_sqlite"


def _bars(closes, *, vol=100.0):
    t0 = datetime(2026, 7, 22, 10, 0, tzinfo=ET)
    out = []
    for i, c in enumerate(closes):
        s = (t0 + timedelta(minutes=i)).timestamp()
        out.append(Bar1m(s, s + 60.0, c, c + 0.05, c - 0.05, c, vol, REAL))
    return out


def test_vwap_sigma_warmup_and_flat_tape():
    bars = _bars([100.0] * 40)
    vwaps, sigmas = vwap_and_deviation_sigma(bars)
    assert abs(vwaps[-1] - 100.0) < 1e-9
    assert all(s is None for s in sigmas[: WARMUP_BARS - 1])
    assert sigmas[-1] is None  # zero-variance tape has no sigma (fail-closed, no trigger)


def test_scan_triggers_side_and_gap():
    # Flat 35 bars (warm-up), then a sharp extension ABOVE vwap.
    closes = [100.0 + 0.01 * (i % 3) for i in range(35)] + [100.6, 100.7, 100.8, 100.9, 101.0]
    cands = scan_rule_a_candidates(_bars(closes))
    assert cands, "extension beyond M_SIGMA must trigger"
    assert all(c.side == "SHORT" for c in cands)          # above VWAP -> fade short
    assert all(c.deviation >= M_SIGMA * c.sigma for c in cands)
    for a, b in zip(cands, cands[1:], strict=False):
        assert b.i_sig - a.i_sig >= 5                      # min gap hygiene


def test_rule_a_multiples_geometry_and_fail_closed():
    cand = RuleACandidate(i_sig=40, side="SHORT", deviation=0.9, sigma=0.3, signal_ts=0.0)
    m = rule_a_multiples(cand, atr_t1=0.45)
    assert m is not None
    stop_atr, target_atr = m
    assert abs(stop_atr - (0.3 / 0.45)) < 1e-9             # 1 sigma beyond
    assert abs(target_atr - (0.9 / 0.45)) < 1e-9           # back to VWAP
    assert rule_a_multiples(cand, atr_t1=0.0) is None      # no ATR -> no candidate
