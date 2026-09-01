"""OPTIONS_ORDER_FLOW_V1 — freshness/health semantic audit.

order_flow_streaming.py's OWN streaming_connected/streaming_healthy only prove "my local
read-only DB-poll task is alive and a row landed recently" — a proxy for daemon health, not
the daemon's real Schwab-socket truth. _read_daemon_upstream_health reads the CANONICAL
DAEMON's own status file (tools/run_stream_capture.py's write_status, fed by real message-
handler health.beat() calls) so a consumer can tell "local replay looks fine" apart from
"the Schwab websocket itself is actually connected and fresh, per service." This file proves
it fails closed (never fabricates RUNNING) on every failure mode, and reports real state
when the status file is genuinely fresh.
"""

from __future__ import annotations

import json
import time

import order_flow_streaming as ofs


def test_missing_status_file_reports_unknown_never_running(tmp_path, monkeypatch):
    monkeypatch.setattr(ofs, "_DAEMON_STATUS_PATH", tmp_path / "does_not_exist.json")
    out = ofs._read_daemon_upstream_health(("LEVELONE_OPTIONS", "OPTIONS_BOOK"))
    assert out == {
        "LEVELONE_OPTIONS": {"state": "UNKNOWN", "age_sec": None},
        "OPTIONS_BOOK": {"state": "UNKNOWN", "age_sec": None},
    }


def test_corrupt_status_file_reports_unknown_never_crashes(tmp_path, monkeypatch):
    p = tmp_path / "status.json"
    p.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(ofs, "_DAEMON_STATUS_PATH", p)
    out = ofs._read_daemon_upstream_health(("LEVELONE_OPTIONS",))
    assert out["LEVELONE_OPTIONS"]["state"] == "UNKNOWN"


def test_stale_status_file_reports_unknown_even_if_health_says_running(tmp_path, monkeypatch):
    """The daemon PROCESS may be dead — a health entry from its last snapshot before it
    died would still say 'RUNNING' verbatim; the status file's OWN write-timestamp must be
    checked first, or a dead daemon's stale file would masquerade as live forever."""
    p = tmp_path / "status.json"
    p.write_text(json.dumps({
        "ts": time.time() - 999,   # far past _DAEMON_STATUS_STALE_SEC=30
        "health": {"LEVELONE_OPTIONS": {"state": "RUNNING", "age_sec": 0.1}},
    }), encoding="utf-8")
    monkeypatch.setattr(ofs, "_DAEMON_STATUS_PATH", p)
    out = ofs._read_daemon_upstream_health(("LEVELONE_OPTIONS",))
    assert out["LEVELONE_OPTIONS"]["state"] == "UNKNOWN", (
        "a stale status file must not let a dead daemon's last snapshot masquerade as live")


def test_fresh_status_file_reports_real_per_service_state(tmp_path, monkeypatch):
    p = tmp_path / "status.json"
    p.write_text(json.dumps({
        "ts": time.time(),
        "health": {
            "LEVELONE_OPTIONS": {"state": "RUNNING", "age_sec": 0.4},
            "OPTIONS_BOOK": {"state": "STALE", "age_sec": 42.0},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(ofs, "_DAEMON_STATUS_PATH", p)
    out = ofs._read_daemon_upstream_health(("LEVELONE_OPTIONS", "OPTIONS_BOOK"))
    assert out["LEVELONE_OPTIONS"] == {"state": "RUNNING", "age_sec": 0.4}
    assert out["OPTIONS_BOOK"] == {"state": "STALE", "age_sec": 42.0}


def test_a_fresh_l1_quote_never_implies_a_fresh_book_service(tmp_path, monkeypatch):
    """A fresh LEVELONE_OPTIONS message must not be treated as evidence OPTIONS_BOOK is
    also fresh — the two are wholly separate Schwab services and must be reported
    separately, never blended into one flag."""
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"ts": time.time(), "health": {
        "LEVELONE_OPTIONS": {"state": "RUNNING", "age_sec": 0.1},
        "OPTIONS_BOOK": {"state": "DOWN", "age_sec": None},
    }}), encoding="utf-8")
    monkeypatch.setattr(ofs, "_DAEMON_STATUS_PATH", p)
    out = ofs._read_daemon_upstream_health(("LEVELONE_OPTIONS", "OPTIONS_BOOK"))
    assert out["LEVELONE_OPTIONS"]["state"] == "RUNNING"
    assert out["OPTIONS_BOOK"]["state"] == "DOWN"


def test_service_missing_from_health_dict_reports_unknown(tmp_path, monkeypatch):
    """A service the status file simply never mentions (e.g. daemon hasn't been touched
    by that service yet this run) reads UNKNOWN, not a fabricated state."""
    p = tmp_path / "status.json"
    p.write_text(json.dumps({"ts": time.time(), "health": {}}), encoding="utf-8")
    monkeypatch.setattr(ofs, "_DAEMON_STATUS_PATH", p)
    out = ofs._read_daemon_upstream_health(("LEVELONE_OPTIONS",))
    assert out["LEVELONE_OPTIONS"]["state"] == "UNKNOWN"


def test_diagnostics_wire_daemon_upstream_health(tmp_path, monkeypatch):
    """The public diagnostics functions actually surface this field, not just the
    internal helper — end-to-end wiring, not an orphan function."""
    p = tmp_path / "status.json"
    p.write_text(json.dumps({
        "ts": time.time(),
        "health": {"LEVELONE_EQUITIES": {"state": "RUNNING", "age_sec": 0.2},
                   "LEVELONE_OPTIONS": {"state": "RUNNING", "age_sec": 0.3},
                   "OPTIONS_BOOK": {"state": "RUNNING", "age_sec": 0.3}},
    }), encoding="utf-8")
    monkeypatch.setattr(ofs, "_DAEMON_STATUS_PATH", p)

    diag = ofs.get_streaming_diagnostics()
    assert diag["daemon_upstream_health"]["LEVELONE_EQUITIES"]["state"] == "RUNNING"

    opt_diag = ofs.get_option_contract_streaming_diagnostics()
    assert opt_diag["daemon_upstream_health"]["LEVELONE_OPTIONS"]["state"] == "RUNNING"
    assert opt_diag["daemon_upstream_health"]["OPTIONS_BOOK"]["state"] == "RUNNING"
