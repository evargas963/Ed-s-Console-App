"""Fixtures shared by the test files that run the console's feed, loaded by tests/conftest.py
(pytest_plugins) after its runtime boundary is set.
"""

from __future__ import annotations

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp


@pytest.fixture
def feed():
    """The console's state cleared before and after, and no daemon bound after."""
    ofs.stop_order_flow_stream()
    ofs._option_contract_last_update_ts.clear()
    ofls.clear_all_live_state()
    lmp._by_ticker.clear()
    yield
    ofs.stop_order_flow_stream()
    ofs.bind_daemon(None)
    lmp._by_ticker.clear()
    lmp.record_feed_down()
