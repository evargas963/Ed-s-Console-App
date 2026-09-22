"""server's REST cumulative-delta computation must preserve a genuinely-missing
last-trade size as unavailable rather than coercing it to zero, and use Schwab's
own last size when present -- the REST-path instance of the missing-vs-zero
contract proved elsewhere for the streaming order-flow path.

RC-REHAB-1 (2026-09-22): _update_rest_cum_delta/_rest_cum_delta/_rest_cum_delta_session
moved to server_state_order_flow.py. Targeting them via `server.` would silently break
_rest_cum_delta_session resets specifically -- server.<name> = None rebinds server's own
copy of the name, not server_state_order_flow's module-global that the function's own
`global` statement actually reads/writes, so the reset would never reach the function.
_rest_cum_delta (a dict) doesn't have this problem (mutation-by-reference, not rebinding),
but the session guard does -- tests target the real owning module directly instead of
relying on server.py's re-export for either.
"""
from __future__ import annotations

from datetime import datetime

import server_state_order_flow as sof


def _rth_dt() -> datetime:
    return datetime(2026, 5, 8, 10, 30, tzinfo=__import__('time_et', fromlist=['ET']).ET)


def test_rest_cum_delta_preserves_missing_last_size_as_unavailable():
    sof._rest_cum_delta.clear()
    sof._rest_cum_delta_session = None

    out = sof._update_rest_cum_delta(
        "SPY",
        {"lastPrice": 501.3, "bidPrice": 501.2, "askPrice": 501.3},
        _rth_dt(),
    )

    assert out is None
    assert "SPY" not in sof._rest_cum_delta


def test_rest_cum_delta_uses_schwab_last_size_when_present():
    sof._rest_cum_delta.clear()
    sof._rest_cum_delta_session = None

    out = sof._update_rest_cum_delta(
        "SPY",
        {"lastPrice": 501.3, "lastSize": 7, "bidPrice": 501.2, "askPrice": 501.3},
        _rth_dt(),
    )

    assert out == 7
    assert sof._rest_cum_delta["SPY"] == 7
