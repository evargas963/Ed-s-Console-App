"""OrderFlowState.push_level_one previously discarded GAMMA/DELTA/OPEN_INTEREST entirely --
confirmed present in the installed schwab-py SDK's LEVELONE_OPTIONS field enum
(.venv/Lib/site-packages/schwab/streaming.py LevelOneOptionFields: DELTA=28, GAMMA=29,
OPEN_INTEREST=9), and these are exactly the per-contract inputs
math_exposure_core.compute_exposures_by_strike needs (gamma * oi * multiplier * spot^2 * 0.01)
to project net_gex_1pct -- so every streamed option L1 tick was silently dropping fields a
live GEX recompute needs, keeping the heatmap bound to the ~60s wide-chain REST cadence even
for the one contract already streaming. This is the foundation for feeding fresher-than-REST
Greeks into the existing ONE FAUCET projection (project_gamma_surface), not a second one --
capture and merge only, no new exposure math here."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.options.order_flow.state import OrderFlowState as LiveOrderFlowState


def test_gamma_delta_open_interest_are_captured_from_a_real_l1_tick():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.0123, "DELTA": 0.45, "OPEN_INTEREST": 4200})
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["gamma"] == 0.0123
    assert g["delta"] == 0.45
    assert g["open_interest"] == 4200.0


def test_total_volume_is_captured_alongside_the_greeks():
    """Independent-review finding (2026-09-12): 'the current hook is triggered by
    GAMMA/DELTA/OPEN_INTEREST; that does not complete volume-only update delivery.'
    TOTAL_VOLUME is captured into the SAME per-symbol record, with its own freshness stamp,
    so the exposure/per-strike overlay can apply the same newer-than-REST precedence rule to
    it that gamma/delta/open_interest already get."""
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": 12345}, ts_recv=500.0)
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["total_volume"] == 12345.0
    assert g["total_volume_ts_recv"] == 500.0


def test_a_volume_only_tick_alone_is_captured_without_any_greek_present():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": 777})
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g == {"total_volume": 777.0, "total_volume_ts_recv": g["total_volume_ts_recv"]}


def test_a_genuine_zero_volume_is_captured_not_dropped():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": 0})
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["total_volume"] == 0.0


def test_a_negative_volume_is_rejected_not_stored_in_greeks_either():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": -1})
    assert st.get_stream_greeks("SPY   260116C00580000") is None


def test_a_gamma_only_tick_does_not_blank_a_previously_observed_volume():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": 500})
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.02})
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["total_volume"] == 500.0
    assert g["gamma"] == 0.02


def test_never_observed_symbol_returns_none_not_a_dict_of_nones():
    st = LiveOrderFlowState()
    assert st.get_stream_greeks("SPY   260116C00580000") is None


def test_a_bid_ask_only_tick_does_not_blank_a_previously_observed_gamma():
    """A quote tick that carries BID_PRICE/ASK_PRICE but not GAMMA must not erase a gamma
    value learned on an earlier tick -- explicit per-field presence, not a group overwrite."""
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.0123, "DELTA": 0.45, "OPEN_INTEREST": 4200})
    st.push_level_one("SPY   260116C00580000", {"BID_PRICE": 12.30, "ASK_PRICE": 12.35})
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["gamma"] == 0.0123, "gamma must survive a tick that does not mention it"
    assert g["delta"] == 0.45
    assert g["open_interest"] == 4200.0


def test_each_field_is_independently_updatable():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01, "DELTA": 0.40, "OPEN_INTEREST": 100})
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.02})
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["gamma"] == 0.02, "gamma updates independently"
    assert g["delta"] == 0.40, "delta from the earlier tick is untouched"
    assert g["open_interest"] == 100.0, "open_interest from the earlier tick is untouched"


def test_a_negative_open_interest_is_rejected_not_stored():
    """float_nonnegative_or_none is this repo's canonical reader for vendor counts
    (already used for TOTAL_VOLUME); a corrupt negative OI tick must not be stored."""
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"OPEN_INTEREST": -5})
    assert st.get_stream_greeks("SPY   260116C00580000") is None


def test_a_genuine_zero_open_interest_is_stored_not_dropped():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"OPEN_INTEREST": 0})
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["open_interest"] == 0.0


def test_a_non_finite_gamma_is_rejected_not_stored():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": float("nan")})
    assert st.get_stream_greeks("SPY   260116C00580000") is None


def test_each_field_carries_its_own_receive_timestamp():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01}, ts_recv=100.0)
    st.push_level_one("SPY   260116C00580000", {"DELTA": 0.40}, ts_recv=105.0)
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["gamma_ts_recv"] == 100.0, "an untouched field keeps its OWN last-update time"
    assert g["delta_ts_recv"] == 105.0


def test_greeks_are_symbol_scoped_not_cross_contaminated():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01})
    st.push_level_one("SPY   260116P00580000", {"GAMMA": 0.02})
    assert st.get_stream_greeks("SPY   260116C00580000")["gamma"] == 0.01
    assert st.get_stream_greeks("SPY   260116P00580000")["gamma"] == 0.02


def test_clear_symbol_drops_streamed_greeks():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01})
    st.clear_symbol("SPY   260116C00580000")
    assert st.get_stream_greeks("SPY   260116C00580000") is None


def test_clear_all_drops_streamed_greeks_for_every_symbol():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01})
    st.clear_all()
    assert st.get_stream_greeks("SPY   260116C00580000") is None
