"""notification_delivery dedup: UTC-day keys, recency prune, corrupt-state warning."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from arch_competition.notification_delivery import (
    _dedup_store_key,
    _prune_fingerprints,
    _save_dedup_state,
    notification_dedup_state_path,
)


def test_prune_fingerprints_keeps_recent_by_timestamp_not_hash_order():
    old_day = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y%m%d")
    recent = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    fp = {
        f"{old_day}|file:aaa": stale,
        f"{old_day}|file:zzz": stale,
        _dedup_store_key("file", "recent_fp"): recent,
        "file:legacy_low_hex": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    pruned = _prune_fingerprints(fp)
    assert f"{old_day}|file:aaa" not in pruned
    assert _dedup_store_key("file", "recent_fp") in pruned


def test_save_dedup_state_writes_valid_json(tmp_path: Path):
    path = notification_dedup_state_path(tmp_path, "1c", "SPY")
    state = {
        "schema_version": "1",
        "delivered_fingerprints": {_dedup_store_key("file", "abc"): datetime.now(timezone.utc).isoformat()},
    }
    _save_dedup_state(path, state)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert "delivered_fingerprints" in loaded
    assert any("|" in k for k in loaded["delivered_fingerprints"])


def test_load_dedup_state_warns_on_corrupt(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    from arch_competition.notification_delivery import _load_dedup_state

    path = notification_dedup_state_path(tmp_path, "1c", "SPY")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    caplog.set_level(logging.WARNING)
    state = _load_dedup_state(path)
    assert state["delivered_fingerprints"] == {}
    assert any("corrupt" in r.message.lower() or "unreadable" in r.message.lower() for r in caplog.records)
