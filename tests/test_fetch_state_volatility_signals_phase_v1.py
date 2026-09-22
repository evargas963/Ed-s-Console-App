"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, fourth extracted phase.

_volatility_signals_for_state (server.py) is the Volatility Signals phase (IV skew,
realized vol, ATR, IV rank/percentile), moved out of _fetch_state's body into a standalone
function returning a _VolatilitySignalsForState NamedTuple.

This extraction also fixes a live regression the FIRST decomposition slice (GARCH,
tests/test_fetch_state_garch_phase_v1.py) introduced: the original inline code
pre-initialized every volatility-signals output EXCEPT `_closes` (`_iv_skew = {}`,
`_realized_vol = None`, `_atr = None`, `_iv_rank = None`, `_iv_percentile = None`,
`_bars = None`, but no `_closes = None`). On a cold ticker (`_bars` empty -- the accumulator
warmup case this same phase already logs specially), `_closes` was never bound. Before the
GARCH extraction, the downstream reference to `_closes` lived inside the GARCH phase's own
try/except and the resulting UnboundLocalError was silently swallowed to a debug log
(observable outcome: `_garch_sigma_bars` stays None). After the GARCH extraction, that same
reference became a bare call argument evaluated in _fetch_state's own frame -- outside any
try/except -- so it started raising an UNCAUGHT NameError out of _fetch_state on every cold
ticker. This test file's `test_cold_ticker_no_bars_does_not_crash_and_flows_cleanly_into_garch`
is the test that would have caught that regression before it shipped, and proves the fix.
"""
from __future__ import annotations

import random
from types import SimpleNamespace
from unittest import mock

import server as srv
import server_state_volatility as sv
from math_exposure import compute_realized_vol, compute_atr


class _FakeAccumulator:
    def __init__(self, bars):
        self._bars = bars

    def get_bars(self, ticker):
        return self._bars


def _synthetic_bars(n: int = 30, seed: int = 7, start: float = 450.0):
    rng = random.Random(seed)
    price = start
    bars = []
    for _ in range(n):
        price *= 1 + rng.gauss(0, 0.0006)
        bars.append(SimpleNamespace(close=price))
    return bars


def test_cold_ticker_no_bars_does_not_crash_and_flows_cleanly_into_garch():
    """THE regression test: a cold ticker (empty accumulator, the real warmup state on
    every fresh ticker or shortly after a restart) must produce closes=None, not an
    unbound variable, and that None must flow harmlessly into the GARCH phase without
    raising."""
    with mock.patch.object(srv, "_candles_1m", _FakeAccumulator([])):
        result = srv._volatility_signals_for_state("SPY", [{"strike": 450}], 450.0, 18.0, None, None)

    assert result.closes is None
    assert result.atr is None
    assert result.realized_vol is None

    # The exact downstream call _fetch_state makes immediately after this phase -- must
    # not raise, matching the pre-GARCH-extraction observable outcome (garch stays None).
    garch_result = srv._garch_sigma_bars_for_state(result.closes, 18.0, result.realized_vol, 450.0)
    assert garch_result is None


def test_warm_ticker_matches_the_original_inline_computation_chain():
    bars = _synthetic_bars()
    with mock.patch.object(srv, "_candles_1m", _FakeAccumulator(bars)):
        result = srv._volatility_signals_for_state(
            "SPY", [{"strike": 450}], bars[-1].close, 18.0, None, None
        )

    expected_closes = [float(b.close) for b in bars if b.close is not None]
    expected_realized_vol = compute_realized_vol(expected_closes, bar_minutes=1.0)
    expected_atr = compute_atr(bars)

    assert result.closes == expected_closes
    assert result.realized_vol == expected_realized_vol
    assert result.atr == expected_atr


def test_iv_rank_and_percentile_require_atm_iv_and_db_and_tick_ts():
    """Matches the original inline guard `if _atm_iv and _ed_db and _tick_ts is not None`
    -- any one missing must skip the DB read entirely, never partially run it."""
    bars = _synthetic_bars()
    fake_db = mock.Mock()
    fake_db.get_recent_iv_levels.return_value = [15.0, 16.0, 17.0, 18.0, 19.0]

    with mock.patch.object(srv, "_candles_1m", _FakeAccumulator(bars)):
        # Missing atm_iv
        r1 = srv._volatility_signals_for_state("SPY", [], 450.0, None, fake_db, 123.0)
        assert r1.iv_rank is None and r1.iv_percentile is None
        # Missing db
        r2 = srv._volatility_signals_for_state("SPY", [], 450.0, 18.0, None, 123.0)
        assert r2.iv_rank is None and r2.iv_percentile is None
        # Missing tick_ts
        r3 = srv._volatility_signals_for_state("SPY", [], 450.0, 18.0, fake_db, None)
        assert r3.iv_rank is None and r3.iv_percentile is None
        # All present -- the DB read must actually run (the wiring's job); the real
        # rank/percentile math has its own coverage elsewhere and is stubbed here so this
        # test isn't coupled to compute_iv_rank's internal sample-size threshold.
        # RC-REHAB-1 (2026-09-22): _volatility_signals_for_state moved to
        # server_state_volatility (module extraction) -- it resolves compute_iv_rank/
        # compute_iv_percentile/compute_iv_skew via that module's own bound-name import,
        # not server's, so the patch target moves with it.
        with mock.patch.object(sv, "compute_iv_rank", return_value=42.0), \
             mock.patch.object(sv, "compute_iv_percentile", return_value=77.0):
            r4 = srv._volatility_signals_for_state("SPY", [], 450.0, 18.0, fake_db, 123.0)
        assert fake_db.get_recent_iv_levels.called, "the DB history read must run when all three gates pass"
        assert r4.iv_rank == 42.0 and r4.iv_percentile == 77.0


def test_a_volatility_calc_failure_is_swallowed_to_defaults_not_raised():
    with mock.patch.object(sv, "compute_iv_skew", side_effect=RuntimeError("synthetic")):
        result = srv._volatility_signals_for_state("SPY", [{"strike": 450}], 450.0, 18.0, None, None)
    assert result.iv_skew == {}
    assert result.atr is None
    assert result.closes is None


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _volatility_signals_for_state exactly once, and
    must not directly call compute_iv_skew/compute_realized_vol/compute_atr itself --
    proving no second inline copy of this phase survived the extraction."""
    import ast
    from pathlib import Path

    src = Path(srv.__file__).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch_state_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    calls_in_fetch_state = [
        n.func.id for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls_in_fetch_state.count("_volatility_signals_for_state") == 1
    for leaked in ("compute_iv_skew", "compute_realized_vol", "compute_atr", "compute_iv_rank", "compute_iv_percentile"):
        assert leaked not in calls_in_fetch_state, (
            f"_fetch_state still calls {leaked} directly -- the volatility-signals phase "
            f"was not fully extracted, a second inline computation site survived"
        )
