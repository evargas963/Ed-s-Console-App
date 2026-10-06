"""The launcher (launch.py): the environment each process starts from, and what it does about a
console already on its port, against real local listeners on free ports."""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

import launch


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _never_asked(question: str) -> str:
    raise AssertionError(f"the launcher asked: {question}")


def test_the_console_starts_with_no_schwab_credential_and_the_daemon_without_a_test_shells_settings(tmp_path):
    shell = {"PATH": "p", "SCHWAB_API_KEY": "LiveLookingKey", "SCHWAB_APP_SECRET": "LiveLookingSecret",
             "SCHWAB_APP_KEY": "LiveLookingKey", "SCHWAB_TOKEN_PATH": "t.json", "ED_CI_OFFLINE": "1"}
    no_env_file = tmp_path / ".env"
    assert launch.daemon_environment(shell, no_env_file) == {
        "PATH": "p", "SCHWAB_API_KEY": "LiveLookingKey", "SCHWAB_APP_SECRET": "LiveLookingSecret",
        "SCHWAB_APP_KEY": "LiveLookingKey", "SCHWAB_TOKEN_PATH": "t.json"}
    assert launch.console_environment(shell, no_env_file) == {"PATH": "p", "SCHWAB_TOKEN_PATH": "t.json"}


def test_both_processes_take_env_files_settings_under_the_shells_and_the_console_no_credential(tmp_path):
    """.env is read once, by the launcher: the console gets its token path and ports, never a credential;
    the shell's value wins."""
    env_file = tmp_path / ".env"
    env_file.write_text("SCHWAB_API_KEY=LiveLookingKey\nSCHWAB_APP_SECRET=LiveLookingSecret\n"
                        "SCHWAB_TOKEN_PATH=D:/tokens/schwab_token.json\nED_LIVE_UI_PORT=8801\n", encoding="utf-8")
    shell = {"PATH": "p", "ED_LIVE_UI_PORT": "8802"}
    assert launch.console_environment(shell, env_file) == {
        "PATH": "p", "SCHWAB_TOKEN_PATH": "D:/tokens/schwab_token.json", "ED_LIVE_UI_PORT": "8802"}
    assert launch.daemon_environment(shell, env_file)["SCHWAB_APP_SECRET"] == "LiveLookingSecret"


def test_a_test_shells_stand_in_credential_never_reaches_the_daemon_and_env_files_real_one_does(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SCHWAB_API_KEY=LiveLookingKey\n", encoding="utf-8")
    for shell_key in ("test", "ci-placeholder-key"):
        env = launch.daemon_environment({"PATH": "p", "SCHWAB_API_KEY": shell_key}, env_file)
        assert env == {"PATH": "p", "SCHWAB_API_KEY": "LiveLookingKey"}, shell_key
    assert launch.daemon_environment({"PATH": "p", "SCHWAB_APP_SECRET": "test"}, tmp_path / "none") == {"PATH": "p"}


def test_with_no_console_on_its_port_one_is_started():
    assert launch.console_on(_free_port(), _never_asked) == "start"


def test_a_healthy_console_is_opened_and_nothing_is_started():
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status": "ok"}'
            self.send_response(200 if self.path == "/api/health" else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        said: list = []
        assert launch.console_on(server.server_address[1], _never_asked, said.append) == "open"
        assert "healthy" in said[0]
    finally:
        server.shutdown()
        server.server_close()


def test_a_hung_console_is_stopped_only_when_the_operator_says_so():
    """A process that holds the port and never answers: asked, kept on "n"; asked, stopped on "y"."""
    port = _free_port()
    hung = subprocess.Popen([sys.executable, "-c",
                             "import socket, sys, time\n"
                             "s = socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
                             "print('listening', flush=True); time.sleep(600)", str(port)],
                            stdout=subprocess.PIPE, text=True)
    try:
        assert hung.stdout.readline().strip() == "listening"
        holder = launch.listener(port)
        asked: list = []
        said: list = []
        assert launch.console_on(port, lambda q: asked.append(q) or "n", said.append) == "leave"
        assert f"PID {holder.pid}" in asked[0] and "has not answered healthy in 10 s" in asked[0]
        assert holder.is_running() and launch.listener(port).pid == holder.pid
        assert launch.console_on(port, lambda q: asked.append(q) or "y", said.append) == "start"
        assert len(asked) == 2 and launch.listener(port) is None
        assert not holder.is_running() or holder.status() == psutil.STATUS_ZOMBIE
    finally:
        for p in [*psutil.Process(hung.pid).children(recursive=True), psutil.Process(hung.pid)] if hung.poll() is None else []:
            p.kill()
        hung.wait(10)
