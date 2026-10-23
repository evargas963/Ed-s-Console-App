"""Each Playwright run serves the console on its own port.

Two full-suite runs from two worktrees at once used to share 127.0.0.1:8765: one run refused to
start ("is already used"), the other lost 32 tests to ERR_CONNECTION_REFUSED when the first
run's server went away.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def _load_config(env: dict[str, str]) -> dict:
    script = (
        "import c from './playwright.config.mjs';"
        "console.log(JSON.stringify({base:c.use.baseURL,url:c.webServer.url,"
        "command:c.webServer.command,storage:c.use.storageState}));"
    )
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _run_port(config: dict) -> int:
    """The one port the run's server, its readiness URL, the pages and their storage all use."""
    base = urlsplit(config["base"])
    assert base.hostname == "127.0.0.1"
    assert config["url"] == config["base"] + "/"
    assert config["command"].endswith(f"--host 127.0.0.1 --port {base.port}")
    assert [o["origin"] for o in config["storage"]["origins"]] == [config["base"]]
    return base.port


def test_two_runs_at_once_get_two_ports():
    """The second run picks while the first run's server holds its port."""
    env = {k: v for k, v in os.environ.items() if k != "ED_E2E_PORT"}
    first = _load_config(env)
    with socket.socket() as first_server:
        first_server.bind(("127.0.0.1", urlsplit(first["base"]).port))
        first_server.listen()
        second = _load_config(env)
    assert urlsplit(first["base"]).port != urlsplit(second["base"]).port
    assert _run_port(first) != _run_port(second)


def test_a_worker_keeps_the_port_its_run_picked():
    env = {k: v for k, v in os.environ.items() if k != "ED_E2E_PORT"}
    picked = _run_port(_load_config(env))
    assert _run_port(_load_config({**env, "ED_E2E_PORT": str(picked)})) == picked


def test_the_pages_start_as_an_operator_who_chose_spy():
    env = {k: v for k, v in os.environ.items() if k != "ED_E2E_PORT"}
    storage = _load_config(env)["storage"]
    assert storage["cookies"] == []
    assert storage["origins"][0]["localStorage"] == [
        {"name": "ed_ticker", "value": "SPY"},
        {"name": "ed_watchlist_v1", "value": '["SPY","QQQ","IWM","NVDA","TSLA"]'},
    ]
