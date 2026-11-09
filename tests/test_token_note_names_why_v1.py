"""The Schwab token's note says why the token file gives no age, never a fake one."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

READ = (
    "import json, server, time_et; "
    "print(json.dumps(server.schwab_token_countdown(server._schwab_token_creation_ts(), "
    "time_et.now())))"
)


def _countdown(token_path: Path) -> dict:
    """Read the countdown in a fresh interpreter whose token file is `token_path`."""
    env = {**os.environ, "SCHWAB_TOKEN_PATH": str(token_path)}
    done = subprocess.run(
        [sys.executable, "-c", READ],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_missing_token_file_is_named_with_its_error(tmp_path):
    out = _countdown(tmp_path / "no_such_token.json")
    assert out["schwab_token_age_days"] is None
    assert out["schwab_token_urgency"] == "unknown"
    assert out["schwab_token_note"].startswith("token file unreadable (FileNotFoundError")


def test_a_token_file_without_its_time_is_named_with_its_error(tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"token": {}}), encoding="utf-8")
    out = _countdown(token)
    assert out["schwab_token_age_days"] is None
    assert "KeyError" in out["schwab_token_note"]


def test_a_readable_token_file_gives_its_age(tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"creation_timestamp": 0}), encoding="utf-8")
    out = _countdown(token)
    assert out["schwab_token_age_days"] > 6 and out["schwab_token_urgency"] == "red"
