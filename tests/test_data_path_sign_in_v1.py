"""The daemon's Schwab sign-in, whose one record is the token file: a sign-in saved there is taken
before the next request, without a restart; once Schwab refuses the sign-in, nothing more is sent
to Schwab until a new one is saved.

Through the real schwab-py client (schwab_client.client_from_token_file_atomic) against a local
stand-in for Schwab's host, and the daemon's real chain sweep (ChainSweep.work). Real data:
Schwab's refusal of the daemon's refresh token as production's stream_capture log recorded it
("OAuthError: unsupported_token_type: 400 Bad Request: ...", authlib's error and description,
which are Schwab's own `error` and `error_description`); Schwab's edge 403 page
(tests/fixtures/real_schwab_akamai_403_2026_10_03.json); the captured SPY 2026-11-20 chain
(tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json) for every data request. STAND-INS
(named): the token files and the refreshed token (_REFRESHED).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

import schwab_client as sc
from app.market_data.schwab.streaming.capture import CaptureWriter
from calibration import complete_chain_capture as cch
from tests.test_data_path_rules_v1 import _AKAMAI_403, _REFRESHED, _ToLocal, _spy_chain_payload, _token_file

#: Schwab's answer refusing the daemon's refresh token, as production's log recorded it
_REFUSED = {"error": "unsupported_token_type",
            "error_description": '400 Bad Request: "{"error_description":"Refresh token is invalid, expired or '
                                 'revoked","error":"invalid_grant"}"'}


class _Host:
    """Schwab's host, played locally: the token endpoint answers as `token` says ("refuses":
    Schwab's refusal; "edge": Schwab's edge 403 page; "refreshes": a refreshed token); every other
    request answers the captured chain. Every request is recorded with the token it carried."""

    def __init__(self):
        self.token = "refuses"
        self.requests: list = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, ctype: str, raw: bytes):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append(("POST", urlparse(self.path).path, None))
                if outer.token == "edge":
                    return self._send(403, "text/html", _AKAMAI_403["body"].encode())
                body = _REFUSED if outer.token == "refuses" else _REFRESHED
                self._send(400 if outer.token == "refuses" else 200, "application/json", json.dumps(body).encode())

            def do_GET(self):
                outer.requests.append(("GET", urlparse(self.path).path, self.headers.get("Authorization")))
                self._send(200, "application/json", json.dumps(_spy_chain_payload()).encode())

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
    """Each kind of request the daemon sends Schwab, as it sends it: the stream's login first
    asks for the user's preferences (schwab-py StreamClient.login)."""
    return [lambda: client.get_user_preferences(),
            lambda: client.get_option_expiration_chain("SPY"),
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


class _Turns(threading.Event):
    """The sweep's stop event, set after `n` of the sweep's idle waits; each wait returns at once
    (the sweep's second between looks, not waited out)."""

    def __init__(self, n: int):
        super().__init__()
        self.left = n

    def wait(self, timeout=None):
        self.left -= 1
        if self.left <= 0:
            self.set()
        return self.is_set()


def _sweep(tmp_path):
    sqlite3.connect(tmp_path / "ed_console.db").close()
    return cch.ChainSweep(tmp_path / "ed_console.db", ["SPY"], lambda topic, msg: None,
                          failures=CaptureWriter(tmp_path / "stream_capture.db"), streamed=lambda symbol: None)


def _work(sweep, schwab_client, turns: int) -> bool:
    """The sweep's thread, stopped after `turns` idle looks; whether it ended within 20 s."""
    worker = threading.Thread(target=sweep.work, args=(schwab_client, _Turns(turns)), daemon=True)
    worker.start()
    worker.join(20)
    return not worker.is_alive()


def test_once_schwab_refuses_the_sign_in_no_request_of_any_kind_reaches_schwab(tmp_path):
    """The token in its refresh window and Schwab refusing it: the first request's refresh is
    refused (SignInRefused), and every kind of request the daemon sends after it, the stream's
    login among them, raises the same, sending nothing: one POST in all, no GET."""
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


def test_a_new_sign_in_saved_after_the_refusal_is_taken_without_a_restart(tmp_path):
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


def test_a_new_sign_in_saved_while_signed_in_is_taken_and_never_overwritten(tmp_path):
    """A sign-in saved while the daemon still holds the old one (before it would be refused): the
    next request carries the new token, nothing is refreshed with the old one, and the token file
    still holds the new sign-in."""
    host = _Host()
    try:
        token = _token_file(tmp_path, 100)                 # the old sign-in, in its refresh window
        client = host.client(token)
        created = _new_sign_in(token, "fresh")
        resp = client.get_option_expiration_chain("SPY")
    finally:
        host.close()
    assert resp.status_code == 200 and host.requests == [("GET", "/marketdata/v1/expirationchain", "Bearer fresh")]
    saved = json.loads(token.read_text())
    assert saved["token"]["access_token"] == "fresh" and saved["creation_timestamp"] == created


def test_a_sign_in_in_progress_removes_the_token_file_and_nothing_breaks(tmp_path):
    """python reauth_schwab.py removes the token file before it saves the new sign-in: while it
    is not there the session holds no sign-in and raises nothing else; once saved, it is taken."""
    host = _Host()
    try:
        token = _token_file(tmp_path, 100)
        client = host.client(token)
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        token.unlink()
        assert not client.session.signed_in()
        with pytest.raises(sc.SignInRefused):
            client.get_option_expiration_chain("SPY")
        _new_sign_in(token, "fresh")
        assert client.session.signed_in()
    finally:
        host.close()
    assert host.sent("POST") == 1


def test_schwabs_edge_page_at_the_token_endpoint_is_not_a_refusal(tmp_path):
    """Schwab's edge answering the refresh with its 403 page: the request fails and the next one
    asks again; only Schwab's answer refusing the sign-in stops the requests."""
    host = _Host()
    host.token = "edge"
    try:
        client = host.client(_token_file(tmp_path, 100))
        for _ in range(2):
            with pytest.raises(Exception) as raised:
                client.get_option_expiration_chain("SPY")
            assert not isinstance(raised.value, sc.SignInRefused)
        assert client.session.signed_in()
    finally:
        host.close()
    assert host.sent("POST") == 2


def test_the_chain_sweep_asks_nothing_while_signed_out_and_goes_on_after_a_new_sign_in(tmp_path, caplog):
    """The daemon's chain sweep over SPY while Schwab refuses the sign-in: its first round meets
    the refusal (one POST), then it only looks, 50 times, sending nothing and logging nothing more
    (a round per look would log every request's failure); a new sign-in saved, it asks Schwab."""
    host = _Host()
    try:
        token = _token_file(tmp_path, 100)
        client = host.client(token)
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, lambda: client, 50), "the sweep never stopped to look: it kept asking"
        first_round = len(caplog.records)
        assert host.requests == [("POST", "/v1/oauth/token", None)]
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, lambda: client, 50)
        assert host.requests == [("POST", "/v1/oauth/token", None)] and not caplog.records and first_round
        _new_sign_in(token, "fresh")
        assert _work(sweep, lambda: client, 1)
    finally:
        host.close()
    assert host.sent("GET") > 0 and all(auth == "Bearer fresh" for m, _p, auth in host.requests if m == "GET")


def test_the_chain_sweep_waits_for_a_client_it_cannot_build_and_goes_on_once_built(tmp_path, caplog):
    """The daemon's client cannot be built (no usable token file: capture.one_schwab_client
    raises ConnectionError and builds again on the next ask): the sweep keeps looking, logs it
    once and asks Schwab for nothing; built, it asks."""
    host = _Host()
    host.token = "refreshes"
    built: list = []

    def schwab_client():
        if not built:
            raise ConnectionError("no Schwab client (token file missing)")
        return built[0]
    try:
        sweep = _sweep(tmp_path)
        with caplog.at_level(logging.WARNING):
            assert _work(sweep, schwab_client, 20), "the sweep ended or never looked again"
        assert [r.getMessage() for r in caplog.records] == [
            "chain sweep waits for the daemon's Schwab client: no Schwab client (token file missing)"]
        assert host.requests == []
        built.append(host.client(_token_file(tmp_path, 3600)))
        assert _work(sweep, schwab_client, 1)
    finally:
        host.close()
    assert host.sent("GET") > 0
