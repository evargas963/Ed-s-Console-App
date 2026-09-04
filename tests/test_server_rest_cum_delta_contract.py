"""server's REST cumulative-delta computation must preserve a genuinely-missing
last-trade size as unavailable rather than coercing it to zero, and use Schwab's
own last size when present -- the REST-path instance of the missing-vs-zero
contract proved elsewhere for the streaming order-flow path."""
from __future__ import annotations

from datetime import datetime

import server


def _rth_dt() -> datetime:
    return datetime(2026, 5, 8, 10, 30, tzinfo=__import__('app.domain.time_et', fromlist=['ET']).ET)


def test_rest_cum_delta_preserves_missing_last_size_as_unavailable():
    server._rest_cum_delta.clear()
    server._rest_cum_delta_session = None

    out = server._update_rest_cum_delta(
        "SPY",
        {"lastPrice": 501.3, "bidPrice": 501.2, "askPrice": 501.3},
        _rth_dt(),
    )

    assert out is None
    assert "SPY" not in server._rest_cum_delta


def test_rest_cum_delta_uses_schwab_last_size_when_present():
    server._rest_cum_delta.clear()
    server._rest_cum_delta_session = None

    out = server._update_rest_cum_delta(
        "SPY",
        {"lastPrice": 501.3, "lastSize": 7, "bidPrice": 501.2, "askPrice": 501.3},
        _rth_dt(),
    )

    assert out == 7
    assert server._rest_cum_delta["SPY"] == 7
