"""Test processes own isolated runtime state and deterministic Schwab capability.

Negative controls poison every inherited input with live-looking values. The
canonical resolvers must still select one process-private root, preserve the
poisoned signal bytes, and fail Schwab closed without a second production
StreamClient.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_KEY = "ci-placeholder-api-key"
PLACEHOLDER_SECRET = "ci-placeholder-app-secret"


def _e2e_server_env(poison_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "ED_CONSOLE_DB": str(poison_root / "production_console.db"),
        "STREAM_CAPTURE_DB_PATH": str(poison_root / "production_stream.db"),
        "SCHWAB_TOKEN_PATH": str(poison_root / "production_token.json"),
        "ED_CI_OFFLINE": "0",
        "SCHWAB_API_KEY": "live-looking-inherited-key",
        "SCHWAB_APP_SECRET": "live-looking-inherited-secret",
        "ED_TERRAIN_QUARANTINE_LEDGER": str(poison_root / "production_terrain.jsonl"),
    })
    script = (
        "import {e2eServerEnv,e2eRuntimeRoot} from './playwright.config.mjs';"
        "console.log(JSON.stringify({env:e2eServerEnv,root:e2eRuntimeRoot}));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    doc = json.loads(result.stdout.strip().splitlines()[-1])
    server_env = doc["env"]
    server_env["_E2E_RUNTIME_ROOT"] = doc["root"]
    return server_env


def test_pytest_boundary_overrides_host_runtime_state(monkeypatch):
    """Pytest is offline and all writable runtime state shares one private root."""
    from config import schwab_live_blocked_for
    from stream_spine import (
        default_active_option_contract_signal_path,
        default_active_ticker_signal_path,
        resolve_stream_db_path,
    )

    root = Path(os.environ["ED_CONSOLE_DB"]).resolve().parent
    assert root.name.startswith("ed-pytest-")
    assert resolve_stream_db_path().parent == root
    assert default_active_option_contract_signal_path().parent == root
    assert default_active_ticker_signal_path().parent == root
    assert Path(os.environ["SCHWAB_TOKEN_PATH"]).parent == root
    assert Path(os.environ["ED_TERRAIN_QUARANTINE_LEDGER"]).parent == root
    assert os.environ["ED_CI_OFFLINE"] == "1"
    assert os.environ["SCHWAB_API_KEY"] == PLACEHOLDER_KEY
    assert os.environ["SCHWAB_APP_SECRET"] == PLACEHOLDER_SECRET
    assert schwab_live_blocked_for() is True

    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH")
    assert resolve_stream_db_path().parent == root
    assert default_active_option_contract_signal_path().parent == root
    assert default_active_ticker_signal_path().parent == root


def test_e2e_boundary_rejects_poisoned_inherited_runtime_state(tmp_path):
    """Live-looking parent values cannot select E2E paths or make Schwab live."""
    server_env = _e2e_server_env(tmp_path)
    root = Path(server_env.pop("_E2E_RUNTIME_ROOT")).resolve()

    assert root.name.startswith("ed-console-e2e-runtime-")
    for key in (
        "ED_CONSOLE_DB",
        "STREAM_CAPTURE_DB_PATH",
        "SCHWAB_TOKEN_PATH",
        "ED_TERRAIN_QUARANTINE_LEDGER",
    ):
        resolved = Path(server_env[key]).resolve()
        assert resolved.parent == root, (key, resolved)
        assert tmp_path not in resolved.parents
    assert server_env["ED_CI_OFFLINE"] == "1"
    assert server_env["SCHWAB_API_KEY"] == PLACEHOLDER_KEY
    assert server_env["SCHWAB_APP_SECRET"] == PLACEHOLDER_SECRET


def test_e2e_signal_writes_cannot_touch_poisoned_parent_signals(tmp_path):
    """Canonical signal writers target the isolated E2E DB, never the parent DB."""
    poison_option = tmp_path / "stream_active_option_contract.json"
    poison_ticker = tmp_path / "stream_active_ticker.json"
    poison_option.write_text("LIVE_OPTION_SENTINEL", encoding="utf-8")
    poison_ticker.write_text("LIVE_TICKER_SENTINEL", encoding="utf-8")
    server_env = _e2e_server_env(tmp_path)
    e2e_root = Path(server_env.pop("_E2E_RUNTIME_ROOT")).resolve()

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json;"
                "from stream_spine import (default_active_option_contract_signal_path,"
                "default_active_ticker_signal_path,write_active_option_contract_signal,"
                "write_active_ticker_signal);"
                "write_active_option_contract_signal('CDE   260904C00021000');"
                "write_active_ticker_signal('CDE');"
                "print(json.dumps({'option':str(default_active_option_contract_signal_path()),"
                "'ticker':str(default_active_ticker_signal_path())}))"
            ),
        ],
        cwd=ROOT,
        env=server_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    paths = json.loads(child.stdout.strip())
    assert Path(paths["option"]).parent == e2e_root
    assert Path(paths["ticker"]).parent == e2e_root
    assert poison_option.read_text(encoding="utf-8") == "LIVE_OPTION_SENTINEL"
    assert poison_ticker.read_text(encoding="utf-8") == "LIVE_TICKER_SENTINEL"
