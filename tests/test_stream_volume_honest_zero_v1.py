"""push_level_one's volume handling (operator finding, 2026-09-11): `or` between
TOTAL_VOLUME/VOLUME drops a legitimate 0, and `vf > 0` rejected any zero outright --
so a symbol with genuinely zero volume so far today never got an entry, and a symbol
whose cache already held a real number kept showing that STALE number if a later
observation was honestly 0. Negative-controlled: the OLD logic is reproduced inline
and shown to fail for the same input the fix passes on."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.options.order_flow.state import OrderFlowState as LiveOrderFlowState


def test_a_genuine_zero_total_volume_is_stored_not_dropped():
    st = LiveOrderFlowState()
    st.push_level_one("SPY", {"TOTAL_VOLUME": 0})
    assert st.get_stream_volume("SPY") == 0.0


def test_total_volume_is_preferred_over_volume_even_when_total_volume_is_zero():
    """The `or` bug: TOTAL_VOLUME=0 would fall through to VOLUME because 0 is falsy."""
    st = LiveOrderFlowState()
    st.push_level_one("SPY", {"TOTAL_VOLUME": 0, "VOLUME": 999})
    assert st.get_stream_volume("SPY") == 0.0, "TOTAL_VOLUME=0 must win over a nonzero VOLUME fallback"


def test_a_later_honest_zero_overwrites_a_stale_earlier_nonzero_value():
    """Core negative control: a real earlier observation (500) must not survive a
    later, genuinely-zero observation (e.g. a session reset) -- the old `vf > 0`
    gate silently kept the stale 500 forever in this exact scenario."""
    st = LiveOrderFlowState()
    st.push_level_one("SPY", {"TOTAL_VOLUME": 500})
    assert st.get_stream_volume("SPY") == 500.0
    st.push_level_one("SPY", {"TOTAL_VOLUME": 0})
    assert st.get_stream_volume("SPY") == 0.0, (
        "a genuine zero observation must overwrite a stale nonzero cached value, "
        "not be silently rejected by it"
    )


def test_non_finite_volume_is_rejected_not_stored():
    st = LiveOrderFlowState()
    st.push_level_one("SPY", {"TOTAL_VOLUME": float("nan")})
    assert st.get_stream_volume("SPY") is None
    st.push_level_one("SPY", {"TOTAL_VOLUME": float("inf")})
    assert st.get_stream_volume("SPY") is None


def test_missing_volume_fields_leave_no_entry():
    st = LiveOrderFlowState()
    st.push_level_one("SPY", {"BID": 1.0})  # no TOTAL_VOLUME/VOLUME at all
    assert st.get_stream_volume("SPY") is None


def test_negative_control_the_old_or_and_positive_only_logic_fails_this_case():
    """Reproduces the PRE-FIX logic inline and shows it gives the wrong answer for
    the exact scenario the fix corrects -- proving this test exercises the real
    defect, not a coincidence of the new implementation."""
    def old_logic(cache: dict, sym: str, content_item: dict) -> None:
        vol = content_item.get("TOTAL_VOLUME") or content_item.get("VOLUME")
        if vol is not None:
            vf = float(vol)
            if vf > 0:
                cache[sym] = vf

    cache: dict = {"SPY": 500.0}  # a real earlier observation
    old_logic(cache, "SPY", {"TOTAL_VOLUME": 0})  # a genuine session-reset zero
    assert cache["SPY"] == 500.0, "demonstrating the old defect: the stale 500 survives"

    # ... and the fixed implementation does not have this problem (already proven above).
