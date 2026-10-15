"""The daemon's Schwab sign-in: once Schwab refuses the refresh token, nothing more is sent to
Schwab until a new sign-in is saved to the token file, which is then taken without a restart.

Through the real schwab-py client (schwab_client.client_from_token_file_atomic) against a local
stand-in for Schwab's host, and the daemon's real chain sweep (ChainSweep.work). Real data:
Schwab's refusal as it answered the daemon's refreshes from 2026-10-14 12:40 CT (production's
stream_capture log: HTTP 400, its body below), and the captured SPY 2026-11-20 chain
(tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json) for every data request. STAND-INS
(named): the token files, the refreshed token (_REFRESHED) and a 503 from the token endpoint.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import httpx
import pytest

import schwab_client as sc
from app.market_data.schwab.streaming.capture import CaptureWriter
from calibration import complete_chain_capture as cch
from tests.test_data_path_rules_v1 import _REFRESHED, _ToLocal, _spy_chain_payload, _token_file

#: Schwab's answer to the daemon's refresh, 2026-10-14 12:40 CT on, as it sent it
_REFUSED = {"error_description": "Refresh token is invalid, expired or revoked", "error": "invalid_grant"}


class _Host:
    """Schwab's host, played locally: the token endpoint answers as `token` says ("refuses":
    Schwab's 400; "fails": a 503; "refreshes": a refreshed token); every other request answers the
    captured chain. Every request is recorded with the token it carried."""

    def __init__(self):
        self.token = "refuses"
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
                outer.requests.append(("POST", urlparse(self.path).path, None))
                answers = {"refuses": (400, _REFUSED), "fails": (503, {"message": "unavailable"}),
                           "refreshes": (200, _REFRESHED)}
                self._send(*answers[outer.token])

            def do_GET(self):
                outer.requests.append(("GET", urlparse(self.path).path, self.headers.get("Authorization")))
                self._send(200, _spy_chain_payload())

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def client(self, token_path):
        return sc.client_from_token_file_atomic(str(token_path), "k", "s",
                                                transport=_ToLocal(self.server.server_address[1]))

    def sent(self, method: str) -> int:
        return sum(1 for m, _p, _a in self.requests if m == method)

    def close(self):
        self.server.shutdown()


def _every_request(client) -> list:
    """Each kind of request the daemon sends Schwab, through the client as the daemon sends it."""
    return [lambda: client.get_option_expiration_chain("SPY"),
            lambda: sc.safe_get_chain(client, "SPY", strike_range="ALL"),
            lambda: sc.safe_get_quotes(client, ["SPY"]),
            lambda: client.get_price_history_every_minute("SPY"),
            lambda: client.get_market_hours([client.MarketHours.Market.EQUITY])]


def _new_sign_in(token_path, access: str) -> int:
    """A new sign-in saved to the token file, as reauth_schwab.py saves one: its creation time."""
    created = int(time.time()) + 1
    token_path.write_text(json.dumps({"creation_timestamp": created, "token": {
        "access_token": access, "refresh_token": "r2", "token_type": "Bearer", "expires_in": 1800,
        "expires_at": int(time.time() + 3600)}}))
    return created


def test_once_schwab_refuses_the_sign_in_no_request_of_any_kind_reaches_schwab(tmp_path):
    """The token in its refresh window and Schwab refusing it: the first request's refresh is
    refused (SignInRefused), and every kind of request the daemon sends after it raises the same,
    sending nothing: one POST in all, no GET."""
    host = _Host()
    try:
        client = host.client(_token_file(tmp_path, 100))
        for request in _every_request(client) * 3:
            with pytest.raises(sc.SignInRefused, match="Refresh token is invalid"):
                request()
        assert not client.session.signed_in()
    finally:
        host.close()
    assert (host.sent("POST"), host.sent("GET")) == (1, 0)


def test_a_new_sign_in_saved_to_the_token_file_is_taken_without_a_restart(tmp_path):
    """After the refusal, a new sign-in saved to the token file: the next request carries its
    token, and the client's token and creation time (the streamer's login reads them) are its."""
    host = _Host()
    try:
        token = _token_file(tmp_path, 100)
        client = host.client(token)
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        created = _new_sign_in(token, "fresh")
        resp = client.get_option_expiration_chain("SPY")
    finally:
        host.close()
    assert resp.status_code == 200 and host.requests[-1] == ("GET", "/marketdata/v1/expirationchain", "Bearer fresh")
    assert client.token_metadata.token["access_token"] == "fresh"
    assert client.token_metadata.creation_timestamp == created


def test_a_token_endpoint_that_fails_is_not_a_refusal(tmp_path):
    """Schwab's token endpoint answering 503 (STAND-IN): the request fails, and the next one asks
    again (a failure is no refusal: only Schwab's answer refusing the token stops the requests)."""
    host = _Host()
    host.token = "fails"
    try:
        client = host.client(_token_file(tmp_path, 100))
        for _ in range(2):
            with pytest.raises(httpx.HTTPStatusError):
                client.get_option_expiration_chain("SPY")
        assert client.session.signed_in()
    finally:
        host.close()
    assert host.sent("POST") == 2


def _until(cond, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def test_the_chain_sweep_asks_schwab_for_nothing_until_a_new_sign_in_then_goes_on(tmp_path):
    """The daemon's chain sweep over SPY while Schwab refuses the sign-in: after the refused
    refresh it sends nothing for 3 s, not one request per ticker; a new sign-in saved, it asks
    Schwab again."""
    host = _Host()
    stop = threading.Event()
    try:
        token = _token_file(tmp_path, 100)
        client = host.client(token)
        sqlite3.connect(tmp_path / "ed_console.db").close()
        sweep = cch.ChainSweep(tmp_path / "ed_console.db", ["SPY"], lambda topic, msg: None,
                               failures=CaptureWriter(tmp_path / "stream_capture.db"),
                               streamed=lambda symbol: None)
        worker = threading.Thread(target=sweep.work, args=(lambda: client, stop), daemon=True)
        worker.start()
        assert _until(lambda: host.sent("POST") == 1)
        time.sleep(3.0)
        assert len(host.requests) == 1, "the sweep asked Schwab again while it refused the sign-in"
        _new_sign_in(token, "fresh")
        assert _until(lambda: host.sent("GET") > 0), "the sweep did not ask again after a new sign-in"
    finally:
        stop.set()
        host.close()
    assert all(auth == "Bearer fresh" for m, _p, auth in host.requests if m == "GET")
