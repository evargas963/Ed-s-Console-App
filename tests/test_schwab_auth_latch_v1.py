"""schwab_client's auth latch: after Schwab refuses a client's login (its token refresh, or an
HTTP 401 answer), that client's chain, expiration list and quote requests are not sent
(SchwabAuthError, naming the refusal); no other client is withheld.

Through the real schwab-py client (schwab_client.client_from_token_file_atomic) against a local
stand-in for Schwab's host. STAND-INS: the token endpoint's answers (OAuth's invalid_grant refusal,
or a refreshed token, one with 100 s left) and the token file; the chain endpoint answers the
captured SPY 2026-11-20 chain (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json, envelope
rebuilt from its contracts), HTTP 401 with a body that mentions a token, or HTTP 502 (induced).
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

import schwab_client as sc
from tests.test_data_path_rules_v1 import _REFRESHED, _ToLocal, _spy_chain_payload, _token_file

_INVALID_GRANT = {"error": "invalid_grant", "error_description": "refresh token revoked"}


class _Host:
    """Schwab's host, played locally: the token endpoint answers `token` ("refused": 400
    invalid_grant; "refreshed": a new token; "short": a new token inside the client's refresh
    window, so its next request refreshes again); the chain endpoint answers `chain` ("served":
    the captured chain; "401": a 401 whose body mentions a token; "502": too big, as measured for
    SPY 2026-09-25), once `held` is set. Every request is recorded."""

    def __init__(self, token: str, chain: str = "served", held: "threading.Event | None" = None):
        self.token = token
        self.requests: list = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, body: dict):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append(("POST", urlparse(self.path).path))
                if outer.token == "refused":
                    return self._send(400, _INVALID_GRANT)
                if outer.token == "short":
                    return self._send(200, {**_REFRESHED, "expires_in": 100})
                self._send(200, _REFRESHED)

            def do_GET(self):
                outer.requests.append(("GET", urlparse(self.path).path))
                if held is not None:
                    held.wait(30)
                if chain == "502":
                    return self._send(502, {})
                if chain == "401":
                    return self._send(401, {"message": "token 401 invalid"})
                self._send(200, _spy_chain_payload())

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def client(self, tmp_path, name: str):
        token = tmp_path / name
        token.mkdir()
        return sc.client_from_token_file_atomic(str(_token_file(token, 100)), "k", "s",
                                                transport=_ToLocal(self.server.server_address[1]))

    def gets(self) -> int:
        return sum(1 for method, _p in self.requests if method == "GET")

    def close(self):
        self.server.shutdown()


def test_a_refused_refresh_withholds_that_clients_next_chain_request(tmp_path):
    host = _Host(token="refused")
    try:
        client = host.client(tmp_path, "a")
        with pytest.raises(sc.SchwabAuthError):
            sc.safe_get_chain(client, "SPY", strike_range="ALL")
        sent = len(host.requests)
        with pytest.raises(sc.SchwabAuthError, match="SPY's chain not sent: Schwab refused our login"):
            sc.safe_get_chain(client, "SPY", strike_range="ALL")
    finally:
        host.close()
    assert len(host.requests) == sent, "a latched client's request reached Schwab"


def test_a_401_answer_latches_the_client_and_says_why(tmp_path):
    """Operator 2026-10-06: an HTTP 401 stops everything, like a refused token, and shows why.
    The chain endpoint answers 401 (induced, with a body that mentions a token): the client is
    latched, its next chain, expiration list and quotes requests are not sent, and each failure
    names the 401 that stopped them."""
    host = _Host(token="refreshed", chain="401")
    try:
        client = host.client(tmp_path, "a")
        with pytest.raises(sc.SchwabAuthError) as first:
            sc.safe_get_chain(client, "SPY", strike_range="ALL")
        sent = host.gets()
        with pytest.raises(sc.SchwabAuthError) as chain:
            sc.safe_get_chain(client, "QQQ", strike_range="ALL")
        with pytest.raises(sc.SchwabAuthError) as quotes:
            sc.safe_get_quotes(client, ["SPY   261120C00700000"])
    finally:
        host.close()
    stopped = "Schwab refused our login (HTTP 401 on SPY's chain); all requests stopped"
    assert str(first.value) == stopped
    assert str(chain.value) == f"QQQ's chain not sent: {stopped}"
    assert str(quotes.value) == f"SPY's quotes not sent: {stopped}"
    assert sent == 1 and host.gets() == 1, "a latched client's request reached Schwab"


def test_one_clients_refused_refresh_never_withholds_another_clients_requests(tmp_path):
    refused, served = _Host(token="refused"), _Host(token="refreshed")
    try:
        with pytest.raises(sc.SchwabAuthError):
            sc.safe_get_chain(refused.client(tmp_path, "a"), "SPY", strike_range="ALL")
        resp = sc.safe_get_chain(served.client(tmp_path, "b"), "SPY", strike_range="ALL")
    finally:
        refused.close()
        served.close()
    assert resp.status_code == 200 and served.gets() == 1


def test_a_client_latched_while_its_chain_was_out_sends_no_expiration_list_request(tmp_path):
    """One client, two sweep workers. BBB's whole chain goes out (its token refreshed, 100 s
    left) and is held at the host; meanwhile AAA's refresh is refused, latching the client. BBB's
    chain is then answered 502 (too big), which asks for the expiration list: the latched client
    sends nothing more, and BBB fails with SchwabAuthError."""
    held = threading.Event()
    host = _Host(token="short", chain="502", held=held)
    try:
        client = host.client(tmp_path, "a")
        with ThreadPoolExecutor(max_workers=1) as other_worker:
            bbb = other_worker.submit(sc.fetch_full_chain, client, "BBB")
            deadline = time.monotonic() + 10
            while host.gets() == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert host.gets() == 1, "BBB's chain request never reached the host"
            host.token = "refused"
            with pytest.raises(sc.SchwabAuthError):
                sc.safe_get_chain(client, "AAA", strike_range="ALL")
            sent = len(host.requests)
            held.set()
            with pytest.raises(sc.SchwabAuthError, match="BBB's expiration list not sent"):
                bbb.result(timeout=30)
    finally:
        held.set()
        host.close()
    assert host.requests[sent:] == [], "a latched client's expiration list request reached Schwab"
