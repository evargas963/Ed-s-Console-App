"""The agent hooks the operator asked for (2026-10-10): ruff on each edited Python file
(tools/ruff_edited_file.py, PostToolUse) and a Stop hook that keeps the turn going until ruff and the
touched files' tests pass (tools/stop_gate.py), letting it end when it already did once."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import stop_gate  # noqa: E402


def _hook(script: str, event: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools" / script)], input=json.dumps(event),
                          capture_output=True, text=True, cwd=ROOT)


def test_an_edited_python_file_with_a_finding_is_reported_and_a_clean_one_passes(tmp_path):
    bad, clean, doc = tmp_path / "bad.py", tmp_path / "clean.py", tmp_path / "notes.md"
    bad.write_text("import os\n", encoding="utf-8")
    clean.write_text("x = 1\n", encoding="utf-8")
    doc.write_text("import os\n", encoding="utf-8")
    found = _hook("ruff_edited_file.py", {"tool_name": "Edit", "tool_input": {"file_path": str(bad)}})
    assert found.returncode == 2 and "F401" in found.stderr
    for path in (clean, doc):
        assert _hook("ruff_edited_file.py", {"tool_name": "Write", "tool_input": {"file_path": str(path)}}).returncode == 0


def test_the_stop_hook_lets_the_turn_end_once_it_has_kept_it_going():
    done = _hook("stop_gate.py", {"stop_hook_active": True})
    assert done.returncode == 0 and done.stderr == ""


def test_a_touched_module_brings_every_test_that_imports_it():
    tests = stop_gate.tests_for(["live_price_rows.py", "app/options/order_flow/streaming.py"])
    assert "tests/test_watchlist_chg_pct_universality_v1.py" in tests      # import live_price_rows
    assert "tests/test_live_push_channel_v1.py" in tests                  # import app.options.order_flow.streaming
    assert "tests/test_schwab_as_sent_v1.py" not in stop_gate.tests_for(["live_price_rows.py"])
