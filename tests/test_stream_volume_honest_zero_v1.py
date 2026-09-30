"""A streamed option volume of 0 is 0 (AGENTS.md rule 2): the old handling (`or` between
TOTAL_VOLUME and VOLUME, then `> 0`) dropped a reported 0 and kept the earlier number. Through the
real push_level_one. Stand-in (named): a LEVELONE_OPTIONS message carrying TOTAL_VOLUME 500, then
one carrying 0, for a real contract symbol."""
from __future__ import annotations

import app.options.order_flow.state as st

SYM = "SPY   260925C00660000"


def test_a_reported_zero_volume_replaces_the_earlier_number():
    st.clear_all_live_state()
    try:
        st.push_level_one(SYM, {"key": SYM, "TOTAL_VOLUME": 500}, ts_recv=1000.0)
        st.push_level_one(SYM, {"key": SYM, "TOTAL_VOLUME": 0}, ts_recv=1001.0)
        g = st.get_stream_greeks(SYM)
        assert (g["total_volume"], g["total_volume_ts_recv"]) == (0, 1001.0)
    finally:
        st.clear_all_live_state()


def test_a_volume_sent_as_not_a_number_is_unavailable_never_the_earlier_number():
    st.clear_all_live_state()
    try:
        st.push_level_one(SYM, {"key": SYM, "TOTAL_VOLUME": 500}, ts_recv=1000.0)
        st.push_level_one(SYM, {"key": SYM, "TOTAL_VOLUME": -999}, ts_recv=1001.0)
        g = st.get_stream_greeks(SYM)
        assert (g["total_volume"], g["total_volume_ts_recv"]) == (None, 1001.0)
    finally:
        st.clear_all_live_state()
