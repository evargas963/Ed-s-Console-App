"""P0.1-B: fail-closed live runner + production L1 path. Not a live rate."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import l1_trade_observation as l1
import tools.l1_source_contract_rth_v1 as T

ROOT = Path(__file__).resolve().parent.parent


def test_session_blockers_without_token_are_external_data():
    blockers = T.session_blockers(require_rth=True)
    assert "EXTERNAL_DATA_UNAVAILABLE" in blockers


def test_analyze_historical_frames_is_not_a_rate():
    frames = ROOT / "reports" / "of_capability_probe" / "20260820T134927Z" / "frames"
    scored = T.analyze_frame_dir(frames)
    assert scored["is_live_rate"] is False
    assert scored["frame_files"] == 12
    assert scored["total_observations"] >= 1
    assert "LEVELONE_EQUITIES" in scored["services"]
    assert scored["field_presence_counts"]["LAST_PRICE"] >= 1
    assert scored["field_presence_counts"]["TRADE_TIME_MILLIS"] >= 1


def test_live_cli_does_not_claim_pass_when_blocked(tmp_path):
    out = tmp_path / "report.json"
    rc = T.main(["--live", "--out", str(out)])
    assert rc == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "NOT_PROVEN"
    assert payload["live_attempted"] is True
    assert payload["blockers"]
    assert payload["live_receipts"] == 0


def test_production_streaming_l1_path_is_schwab_levelone_only():
    facts = T.production_l1_wiring_facts()
    assert facts["proof_class"] == "static_wiring"
    assert facts["constructs_stream_client"] is True
    assert facts["registers_level_one_handler"] is True
    assert facts["subscribes_level_one"] is True
    assert facts["consumes_via_push_level_one"] is True
    assert facts["timesale_subs_present"] is False
    assert facts["named_rest_fallback"] is True


def test_live_clock_comes_from_time_et_now_et_not_a_local_clock(tmp_path, monkeypatch):
    """Clock authority is time_et.now_et. A local datetime.now would ignore this freeze."""
    frozen = datetime(2026, 8, 22, 18, 5, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr(T, "now_et", lambda: frozen)
    out = tmp_path / "clock.json"
    rc = T.main(["--live", "--out", str(out)])
    assert rc == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["measured_et"] == frozen.isoformat()
    assert payload["weekday"] == "Saturday"
    assert payload["trading_day"] is False
    assert "RTH_ONLY" in payload["blockers"]
    assert payload["next_rth"] == "2026-08-24 Monday"


def test_default_universe_is_core_not_spy_only():
    uni = T.default_universe_from_core()
    assert "SPY" in uni and "QQQ" in uni and "IWM" in uni
    assert len(uni) >= 8
    assert l1.source_contract()["production_l1_service"] == "LEVELONE_EQUITIES"


def test_source_text_dead_code_is_not_wiring_proof():
    dead = '''
def unused():
    return "level_one_equity_subs add_level_one_equity_handler StreamClient push_level_one"
'''
    facts = T.production_l1_wiring_facts(dead)
    assert facts["constructs_stream_client"] is False
    assert facts["registers_level_one_handler"] is False
    assert facts["subscribes_level_one"] is False
    assert facts["consumes_via_push_level_one"] is False


def test_hardcoded_weekday_is_not_next_rth_authority():
    src = (ROOT / "tools" / "l1_source_contract_rth_v1.py").read_text(encoding="utf-8")
    assert '"2026-08-24 Monday"' not in src
    from time_et import next_rth_session_et
    sat = datetime(2026, 8, 22, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    assert next_rth_session_et(sat) == ("2026-08-24", "Monday")
    holiday = datetime(2026, 7, 3, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert next_rth_session_et(holiday) == ("2026-07-06", "Monday")
    early_after = datetime(2026, 11, 27, 14, 0, tzinfo=ZoneInfo("America/New_York"))
    assert next_rth_session_et(early_after) == ("2026-11-30", "Monday")
    dst = datetime(2026, 3, 8, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert next_rth_session_et(dst) == ("2026-03-09", "Monday")


def test_live_success_path_uses_production_collect(tmp_path, monkeypatch):
    receipts = [{"symbol": "SPY", "item": {"key": "SPY", "LAST_PRICE": 1}}]

    def _collect(client, account_id, symbols, duration_sec=8.0):
        assert "SPY" in symbols and "QQQ" in symbols
        return receipts

    import order_flow_streaming as ofs
    monkeypatch.setattr(T, "session_blockers", lambda require_rth=True: [])
    monkeypatch.setattr(ofs, "collect_level_one_receipts", _collect)
    out = tmp_path / "live.json"
    rc = T.main(["--live", "--out", str(out), "--symbols", "SPY,QQQ,IWM"])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS"
    assert payload["live_receipts"] == 1


def test_collect_level_one_receipts_calls_production_bind():
    import order_flow_streaming as ofs

    class _SC:
        def __init__(self, client, account_id):
            self.client = client
            self.account_id = account_id
            self.handler = None
            self.subs = None
            self.logged_in = False

        async def login(self):
            self.logged_in = True

        def add_level_one_equity_handler(self, fn):
            self.handler = fn

        async def level_one_equity_subs(self, symbols):
            self.subs = list(symbols)
            self.handler({"content": [{"key": symbols[0], "LAST_PRICE": 10}]})

        async def handle_message(self):
            raise RuntimeError("done")

        async def logout(self):
            return None

    made = []

    def factory(client, account_id):
        sc = _SC(client, account_id)
        made.append(sc)
        return sc

    rec = ofs.collect_level_one_receipts(
        object(), 123, ["SPY", "QQQ"], duration_sec=0.05,
        stream_client_factory=factory, login=True,
    )
    assert made and made[0].logged_in is True
    assert made[0].subs == ["SPY", "QQQ"]
    assert rec and rec[0]["symbol"] == "SPY"
