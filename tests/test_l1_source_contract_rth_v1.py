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
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "NOT_PROVEN"
    assert payload["live_attempted"] is True
    assert payload["blockers"]
    assert payload["live_receipts"] == 0


def test_production_streaming_l1_path_is_schwab_levelone_only():
    facts = T.production_l1_path_facts()
    assert facts["uses_level_one_equity_subs"] is True
    assert facts["uses_level_one_equity_handler"] is True
    assert facts["pushes_level_one"] is True
    assert facts["uses_timesale_subs"] is False
    assert facts["imports_alpaca"] is False
    assert facts["quote_fallback_is_named"] is True
    src = (ROOT / "order_flow_streaming.py").read_text(encoding="utf-8")
    assert "push_level_one(sym, item)" in src
    assert "add_level_one_equity_handler" in src


def test_live_clock_comes_from_time_et_now_et_not_a_local_clock(tmp_path, monkeypatch):
    """Clock authority is time_et.now_et. A local datetime.now would ignore this freeze."""
    frozen = datetime(2026, 8, 22, 18, 5, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr(T, "now_et", lambda: frozen)
    out = tmp_path / "clock.json"
    rc = T.main(["--live", "--out", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["measured_et"] == frozen.isoformat()
    assert payload["weekday"] == "Saturday"
    assert payload["trading_day"] is False
    assert "RTH_ONLY" in payload["blockers"]


def test_default_universe_is_core_not_spy_only():
    uni = T.default_universe_from_core()
    assert "SPY" in uni and "QQQ" in uni and "IWM" in uni
    assert len(uni) >= 8
    assert l1.source_contract()["production_l1_service"] == "LEVELONE_EQUITIES"
