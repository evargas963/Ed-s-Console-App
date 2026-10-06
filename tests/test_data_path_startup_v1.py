"""The capture daemon's start, Schwab to the screen: the stream logs in and subscribes before the
chain sweep sends Schwab anything; why Schwab is not connected reaches the browser on the
daemon's heartbeat; a module that fails to load leaves its reason in the daemon's log."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
from schwab.client import Client
from websockets.asyncio.client import connect

from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_ui import serve_live_ui
from schwab_client import build_client_from_token
from stream_spine import CaptureWriter, HealthRegistry, MessageBus
from tests.test_data_path_rules_v1 import _LocalSchwab

REPO = Path(__file__).resolve().parent.parent


async def _until(cond, limit: float = 10.0) -> None:
    end = time.monotonic() + limit
    while not cond():
        assert time.monotonic() < end, "timed out"
        await asyncio.sleep(0.05)


def test_the_chain_sweep_sends_schwab_nothing_until_the_stream_has_subscribed(tmp_path):
    """The real chain sweep on a schwab-py client of the local stand-in for Schwab's host: no
    request while the stream has not subscribed; the chains once it has."""
    sqlite3.connect(tmp_path / "ed_console.db").close()
    host = _LocalSchwab()
    client = Client("k", httpx.Client(transport=host.transport), enforce_enums=False)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), board=["SPY"])

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(capture.run_chains(
            daemon, tmp_path / "ed_console.db", lambda: client, stop,
            failures=CaptureWriter(tmp_path / "stream_capture.db")))
        await asyncio.sleep(1.5)
        before = list(host.requests)
        daemon.subscribed.set()
        await _until(lambda: any(path == "/marketdata/v1/chains" for _t, _m, path, _a in host.requests))
        stop.set()
        await asyncio.wait_for(task, timeout=30)
        return before
    try:
        before = asyncio.run(go())
    finally:
        host.close()
    assert before == [], f"the chain sweep reached Schwab before the stream subscribed: {before}"


def test_why_schwab_is_not_connected_reaches_the_browser_on_the_daemons_heartbeat(tmp_path):
    """The daemon's one client, built by the real builder from a token file that does not exist:
    the connection fails, and the heartbeat the browser takes from the daemon's price socket says
    NOT CONNECTED, since when, and Schwab's refusal as the builder gave it."""
    schwab_client = capture.one_schwab_client(
        lambda: build_client_from_token(str(tmp_path / "missing_token.json"), "LiveLookingKey", "LiveLookingSecret"))
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), board=["SPY"])
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    async def go():
        stop = asyncio.Event()
        ui = asyncio.create_task(serve_live_ui(bus, stop, heartbeat_fn=daemon.status, host="127.0.0.1", port=port))
        run = asyncio.create_task(daemon.run(schwab_client, stop))
        await _until(lambda: daemon.schwab_failure is not None)
        await asyncio.sleep(0.2)
        async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
            while (msg := json.loads(await asyncio.wait_for(ws.recv(), 5)))["type"] != "feed":
                pass
        stop.set()
        await asyncio.gather(ui, run)
        return msg["feed"]
    feed = asyncio.run(go())
    assert feed["schwab_socket_open"] is False
    line = feed["schwab"]["line"]
    assert feed["schwab"]["cls"] == "neg" and line.startswith("NOT CONNECTED since ") and line.count(" CT: ") == 1
    assert "no Schwab client (Token file not found" in line, line


def test_a_module_that_fails_to_load_leaves_its_reason_in_the_daemons_log(tmp_path):
    """The daemon run with no error output (pythonw on Windows; elsewhere its fd 2 closed), with
    schwab-py missing: the log file under its runtime root has why."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(
        "import sys\n"
        "class _Missing:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'schwab' or name.startswith('schwab.'):\n"
        "            raise ModuleNotFoundError(f\"No module named '{name}'\", name=name)\n"
        "sys.meta_path.insert(0, _Missing())\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(site), "ED_RUNTIME_ROOT": str(tmp_path)}
    module = ["-m", "app.market_data.schwab.streaming.capture"]
    if sys.platform == "win32":
        cmd = [str(Path(sys.executable).with_name("pythonw.exe")), *module]
    else:
        cmd = ["sh", "-c", 'exec "$0" "$@" 2>&-', sys.executable, *module]
    done = subprocess.run(cmd, cwd=REPO, env=env, timeout=120)   # no handle passed: pythonw has none
    log = (tmp_path / "logs" / "stream_capture.log").read_text(encoding="utf-8")
    assert done.returncode == 1
    assert "capture daemon loading (pid " in log
    assert "ModuleNotFoundError: No module named 'schwab'" in log, log
