"""schwab_client's auth latch: after Schwab refuses a client's token refresh, that client's chain
and quote requests are withheld (SchwabAuthError) instead of sent; no other client is withheld.

Through the real schwab-py client (schwab_client.client_from_token_file_atomic) against a local
stand-in for Schwab's host. STAND-INS: the token endpoint's answers (OAuth's invalid_grant refusal,
or a refreshed token) and the token file; the chain endpoint answers the captured SPY 2026-11-20
chain (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json, envelope rebuilt from its
contracts), or HTTP 401 with a body that mentions a token.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

import schwab_client as sc
from tests.test_data_path_rules_v1 import _REFRESHED, _ToLocal, _spy_chain_payload, _token_file

_INVALID_GRANT = {"error": "invalid_grant", "error_description": "refresh token revoked"}


class _Host:
    """Schwab's host, played locally: the token endpoint answers `token` ("refused": 400
    invalid_grant; "refreshed": a new token); the chain endpoint answers `chain` ("served": the
    captured chain; "401": a 401 whose body mentions a token). Every request is recorded."""

    def __init__(self, token: str, chain: str = "served"):
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
                if token == "refused":
                    return self._send(400, _INVALID_GRANT)
                self._send(200, _REFRESHED)

            def do_GET(self):
                outer.requests.append(("GET", urlparse(self.path).path))
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
        with pytest.raises(sc.SchwabAuthError, match="latched"):
            sc.safe_get_chain(client, "SPY", strike_range="ALL")
    finally:
        host.close()
    assert len(host.requests) == sent, "a latched client's request reached Schwab"


def test_an_answer_that_mentions_a_token_is_not_an_auth_failure(tmp_path):
    host = _Host(token="refreshed", chain="401")
    try:
        client = host.client(tmp_path, "a")
        codes = [sc.safe_get_chain(client, "SPY", strike_range="ALL").status_code for _ in range(2)]
    finally:
        host.close()
    assert codes == [401, 401] and host.gets() == 2, "a 401 answer latched the client"


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
