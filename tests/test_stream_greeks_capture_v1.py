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
import time

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.options.order_flow.state import OrderFlowState as LiveOrderFlowState


def test_gamma_delta_open_interest_are_captured_from_a_real_l1_tick():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.0123, "DELTA": 0.45, "OPEN_INTEREST": 4200}, ts_recv=time.time())
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
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": 777}, ts_recv=time.time())
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g == {"total_volume": 777.0, "total_volume_ts_recv": g["total_volume_ts_recv"]}


def test_a_genuine_zero_volume_is_captured_not_dropped():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": 0}, ts_recv=time.time())
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["total_volume"] == 0.0


def test_a_negative_volume_is_held_as_no_value_never_as_a_number():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": -1}, ts_recv=100.0)
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["total_volume"] is None and g["total_volume_ts_recv"] == 100.0


def test_a_gamma_only_tick_does_not_blank_a_previously_observed_volume():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"TOTAL_VOLUME": 500}, ts_recv=time.time())
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.02}, ts_recv=time.time())
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
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.0123, "DELTA": 0.45, "OPEN_INTEREST": 4200}, ts_recv=time.time())
    st.push_level_one("SPY   260116C00580000", {"BID_PRICE": 12.30, "ASK_PRICE": 12.35}, ts_recv=time.time())
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["gamma"] == 0.0123, "gamma must survive a tick that does not mention it"
    assert g["delta"] == 0.45
    assert g["open_interest"] == 4200.0


def test_each_field_is_independently_updatable():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01, "DELTA": 0.40, "OPEN_INTEREST": 100}, ts_recv=time.time())
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.02}, ts_recv=time.time())
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["gamma"] == 0.02, "gamma updates independently"
    assert g["delta"] == 0.40, "delta from the earlier tick is untouched"
    assert g["open_interest"] == 100.0, "open_interest from the earlier tick is untouched"


def test_a_negative_open_interest_is_held_as_no_value():
    """schwab_count: a negative count is not a number; the stream sent the
    field, so the contract has no open interest now."""
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"OPEN_INTEREST": -5}, ts_recv=time.time())
    assert st.get_stream_greeks("SPY   260116C00580000")["open_interest"] is None


def test_a_genuine_zero_open_interest_is_stored_not_dropped():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"OPEN_INTEREST": 0}, ts_recv=time.time())
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["open_interest"] == 0.0


def test_a_non_finite_gamma_is_held_as_no_value():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": float("nan")}, ts_recv=time.time())
    assert st.get_stream_greeks("SPY   260116C00580000")["gamma"] is None


def test_each_field_carries_its_own_receive_timestamp():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01}, ts_recv=100.0)
    st.push_level_one("SPY   260116C00580000", {"DELTA": 0.40}, ts_recv=105.0)
    g = st.get_stream_greeks("SPY   260116C00580000")
    assert g["gamma_ts_recv"] == 100.0, "an untouched field keeps its OWN last-update time"
    assert g["delta_ts_recv"] == 105.0


def test_greeks_are_symbol_scoped_not_cross_contaminated():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01}, ts_recv=time.time())
    st.push_level_one("SPY   260116P00580000", {"GAMMA": 0.02}, ts_recv=time.time())
    assert st.get_stream_greeks("SPY   260116C00580000")["gamma"] == 0.01
    assert st.get_stream_greeks("SPY   260116P00580000")["gamma"] == 0.02


def test_clear_symbol_drops_streamed_greeks():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01}, ts_recv=time.time())
    st.clear_symbol("SPY   260116C00580000")
    assert st.get_stream_greeks("SPY   260116C00580000") is None


def test_clear_all_drops_streamed_greeks_for_every_symbol():
    st = LiveOrderFlowState()
    st.push_level_one("SPY   260116C00580000", {"GAMMA": 0.01}, ts_recv=time.time())
    st.clear_all()
    assert st.get_stream_greeks("SPY   260116C00580000") is None


def test_greeks_sent_as_minus_999_are_unavailable_through_the_chain_overlay_until_sent_again():
    """Measured 2026-09-30 over the retained stream: 638 contracts went from a value to -999
    (GAMMA, DELTA, THETA, VEGA, RHO and VOLATILITY together); the console kept the last value
    and its time. SPY 260928C00772000 held gamma 0.0702 from 01:00 to 08:05 ET on 2026-09-28
    while Schwab said it had none. Real messages and the contract as the stored chain sent it
    (tests/fixtures/real_option_l1_greeks_unavailable.json); a quote message that carries no
    greek (its bid and ask only) stands in for the messages in between, which Schwab did not send."""
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from math_exposure_core import overlay_streamed_contract_fields
    from math_levels import UNPRICED_NO_VOLATILITY, contract_inputs
    fx = json.loads((ROOT / "tests" / "fixtures" / "real_option_l1_greeks_unavailable.json").read_text(encoding="utf-8"))
    sym, chain = fx["symbol"], [fx["chain_contract"]]
    valued, unavailable, restored = fx["messages"]
    assert unavailable["native"]["GAMMA"] == unavailable["native"]["VOLATILITY"] == -999
    st = LiveOrderFlowState()

    def overlaid(msg):
        st.push_level_one(sym, msg["native"], ts_recv=msg["ts_recv"])
        (ct,), _ = overlay_streamed_contract_fields(chain, {sym: st.get_stream_greeks(sym)})
        return ct

    ct = overlaid(valued)
    assert (ct["gamma"], ct["volatility"]) == (valued["native"]["GAMMA"], valued["native"]["VOLATILITY"])
    ct = overlaid(unavailable)
    assert ct["gamma"] is None and ct["delta"] is None and ct["volatility"] is None, "never the old value"
    assert chain[0]["gamma"] == 0.07, "and never the chain's older value either"
    assert st.get_stream_greeks(sym)["gamma_ts_recv"] == unavailable["ts_recv"]
    at = datetime.fromtimestamp(unavailable["ts_recv"], ZoneInfo("America/New_York"))
    assert contract_inputs([ct], at)[1] == {UNPRICED_NO_VOLATILITY: 1}, "a contract with no volatility is not priced"
    ct = overlaid({"ts_recv": unavailable["ts_recv"] + 60, "native": {"key": sym, "BID_PRICE": 3.0, "ASK_PRICE": 3.1}})
    assert ct["gamma"] is None, "a message that omits the field keeps it unavailable"
    ct = overlaid(restored)
    assert (ct["gamma"], ct["volatility"]) == (restored["native"]["GAMMA"], restored["native"]["VOLATILITY"])
    assert ct["openInterest"] == restored["native"]["OPEN_INTEREST"]
