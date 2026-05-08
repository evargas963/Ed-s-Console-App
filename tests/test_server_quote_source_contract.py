from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server


class _Resp:
    status_code = 200

    def json(self) -> dict:
        return {
            "SPY": {
                "quote": {
                    "lastPrice": None,
                    "mark": 501.25,
                    "bidPrice": 501.2,
                    "askPrice": 501.3,
                    "quoteTime": 1_778_018_399.0,
                    "tradeTime": 1_778_018_398.0,
                }
            }
        }


def test_rest_fast_quote_payload_exposes_field_sources(monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", lambda *_args, **_kwargs: _Resp())

    payload = server._build_rest_fast_quote_payload("SPY", "rest_fast_quote")

    assert payload["spot"] == 501.25
    assert payload["spread_pts"] == 0.1
    assert payload["fast_server_ts"] == 1_778_018_399.0
    assert payload["quote_time_source"] == "schwab_rest_quote"
    assert isinstance(payload["server_received_ts"], float)
    assert payload["quote_source_detail"] == {
        "spot": "mark",
        "bid": "bidPrice",
        "ask": "askPrice",
        "spread": "schwab_bid_ask",
        "carried_forward": False,
    }


def test_tier_a_live_state_rest_bootstrap_row_uses_schwab_time_not_wall_clock(monkeypatch):
    """S017: Tier A GET /api/live/state REST bootstrap must not set fast_server_ts from time.time()."""
    monkeypatch.setattr(server._lmp, "get_quote", lambda _ticker: None)
    monkeypatch.setattr(server._lmp, "next_fast_generation", lambda _ticker: 99)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", lambda *_args, **_kwargs: _Resp())

    out = server._tier_a_live_state_dict("SPY", None)

    assert out.get("_tier") == "A_live"
    assert out["quote_ingestion"] == "rest_tier_a"
    assert out["fast_server_ts"] == 1_778_018_399.0
    assert out["quote_time_source"] == "schwab_rest_quote"
    assert isinstance(out["server_received_ts"], float)
