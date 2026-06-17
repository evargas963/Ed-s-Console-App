"""Empty ED_CONSOLE_RELOAD_URL disables live reload call."""
from __future__ import annotations



from arch_competition.live_model_reload import build_live_reload_report


def test_empty_reload_url_not_called(monkeypatch):
    monkeypatch.setenv("ED_CONSOLE_RELOAD_URL", "")
    report = build_live_reload_report(
        reloads=[{"ticker": "SPY", "horizon": "1c"}],
    )
    assert report["called"] is False
    assert "empty" in report["reason"].lower()
