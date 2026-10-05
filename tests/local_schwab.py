"""Test helper: Schwab's host and streamer, played by local servers, for the daemon's one Schwab
client (schwab-py) and its StreamClient.

Real data: the captured SPY 2026-11-20 chain and Schwab's quotes for it, and Schwab's edge's 403
page (Akamai) as it answered on 2026-10-03. Stand-ins, named: the local servers playing Schwab's
host and streamer, and the token endpoint's answer to a refresh (no real one is kept: it holds
the tokens) in the shape Schwab documents. A result that rests on a stand-in answer is an induced
test condition, not observed Schwab behavior."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve as serve_sync

FX = Path(__file__).resolve().parent / "fixtures"

_SPY_1120 = json.loads((FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_SPY_1120_QUOTES = {s: e for q in _SPY_1120["quotes"] for s, e in q["reply"].items()}
_AKAMAI_403 = json.loads((FX / "real_schwab_akamai_403_2026_10_03.json").read_text(encoding="utf-8"))
_REFRESHED = {"access_token": "new-access", "refresh_token": "r", "token_type": "Bearer",
              "expires_in": 1800, "scope": "api", "id_token": "i"}


def _spy_chain_payload() -> dict:
    payload = {"symbol": "SPY", "underlyingPrice": _SPY_1120["spot"], "callExpDateMap": {},
               "putExpDateMap": {}}
    for ct in _SPY_1120["chain"]:
        side = "callExpDateMap" if ct["putCall"] == "CALL" else "putExpDateMap"
        payload[side].setdefault(f"{ct['expirationDate'][:10]}:{ct['daysToExpiration']}", {}) \
            .setdefault(str(ct["strikePrice"]), []).append(ct)
    return payload


class _ToLocal(httpx.BaseTransport):
    """Every request the client sends, delivered to the local server instead of Schwab's host."""

    def __init__(self, port: int):
        self.port, self.inner = port, httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return self.inner.handle_request(request)


class _LocalSchwab:
    """Schwab's host, played by a local server. The token endpoint answers `token_answer`
    ("refreshed": _REFRESHED; "akamai": the captured 403 page); chains and quotes answer the
    captured SPY chain (or `chains[symbol]`, Schwab's payload as captured) and its quotes, or the
    captured 403 page while `refuse`. Every request is recorded: (time, method, path,
    Authorization). The instrument lookup answers `instruments[symbol]` (a body, HTTP 200, or
    (status, body)), or `unlisted` for any other symbol -- by default `{}`, the text Schwab
    answered for NOTREAL on 2026-10-05 (tests/fixtures/real_schwab_instruments_symbol_search_
    2026_10_05.json), served for a symbol whose reply was never captured (each symbol asked is
    recorded in `instruments_asked`). The user preferences name its streamer, a local WebSocket
    that answers every request code 0, except a SUBS or ADD of a service in `stream_refusal`:
    (code, msg); before answering a request of a service in `stream_before` it sends that
    service's frames (text) first; a request of a service in `stream_silent` is never answered;
    a request for a service in `stream_drop` closes the socket unanswered, and so does drop().
    The chain requests' symbols are recorded (`chains_asked`). The streamer records every
    request (`stream_requests`: service, command, keys), every login and the most sessions
    logged in at once."""

    def __init__(self, token_answer: str = "refreshed", refuse: bool = False, instruments=None,
                 unlisted: str = "{}", stream_refusal=None, chains=None, stream_drop=(), stream_before=None,
                 stream_silent=()):
        self.token_answer, self.refuse = token_answer, refuse
        self.stream_silent = set(stream_silent)
        self.chains = dict(chains or {})
        self.chains_asked: list = []
        self.stream_before = dict(stream_before or {})
        self.instruments, self.unlisted = dict(instruments or {}), unlisted
        self.stream_refusal, self.stream_drop = dict(stream_refusal or {}), set(stream_drop)
        self.requests: list = []
        self.instruments_asked: list = []
        self.stream_requests: list = []
        self.logins = self.live = self.most_live = 0
        self.sockets: list = []
        lock = threading.Lock()
        outer = self

        def streamer(ws):
            outer.sockets.append(ws)
            logged_in = False
            try:
                for frame in ws:
                    for req in json.loads(frame)["requests"]:
                        svc, cmd = req["service"], req["command"]
                        outer.stream_requests.append((svc, cmd, req["parameters"].get("keys")))
                        if svc in outer.stream_drop:
                            ws.close()
                            return
                        if svc in outer.stream_silent:
                            continue                       # never answered
                        with lock:
                            if (svc, cmd) == ("ADMIN", "LOGIN"):
                                outer.logins, outer.live, logged_in = outer.logins + 1, outer.live + 1, True
                                outer.most_live = max(outer.most_live, outer.live)
                            elif (svc, cmd) == ("ADMIN", "LOGOUT") and logged_in:
                                outer.live, logged_in = outer.live - 1, False
                        for text in outer.stream_before.get(svc, ()):
                            ws.send(text)                  # sent ahead of this request's answer
                        code, msg = (outer.stream_refusal.get(svc, (0, "stand-in: accepted"))
                                     if cmd in ("SUBS", "ADD") else (0, "stand-in: accepted"))
                        ws.send(json.dumps({"response": [{
                            "service": svc, "requestid": req["requestid"], "command": cmd,
                            "SchwabClientCorrelId": req["SchwabClientCorrelId"], "timestamp": int(time.time() * 1000),
                            "content": {"code": code, "msg": msg}}]}))
            except ConnectionClosed:
                pass
            finally:
                with lock:
                    if logged_in:
                        outer.live -= 1
        self.streamer = serve_sync(streamer, "127.0.0.1", 0)
        threading.Thread(target=self.streamer.serve_forever, daemon=True).start()
        stream_url = f"ws://127.0.0.1:{self.streamer.socket.getsockname()[1]}"

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, content_type, body: bytes):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                if status == 403:
                    self.send_header("Server", _AKAMAI_403["headers"]["server"])
                self.end_headers()
                self.wfile.write(body)

            def _akamai(self):
                self._send(403, "text/html", _AKAMAI_403["body"].encode())

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append((time.monotonic(), "POST", urlparse(self.path).path, None))
                if outer.token_answer == "akamai":
                    return self._akamai()
                self._send(200, "application/json", json.dumps(_REFRESHED).encode())

            def do_GET(self):
                url = urlparse(self.path)
                outer.requests.append((time.monotonic(), "GET", url.path, self.headers.get("Authorization")))
                if outer.refuse:
                    return self._akamai()
                if url.path == "/marketdata/v1/chains":
                    symbol = parse_qs(url.query)["symbol"][0]
                    outer.chains_asked.append(symbol)
                    payload = outer.chains[symbol] if symbol in outer.chains else _spy_chain_payload()
                    return self._send(200, "application/json", json.dumps(payload).encode())
                if url.path == "/marketdata/v1/instruments":
                    symbol = parse_qs(url.query)["symbol"][0]
                    outer.instruments_asked.append(symbol)
                    answer = outer.instruments.get(symbol, outer.unlisted)
                    status, body = answer if isinstance(answer, tuple) else (200, answer)
                    return self._send(status, "application/json", body.encode())
                if url.path == "/trader/v1/userPreference":
                    return self._send(200, "application/json", json.dumps({"streamerInfo": [{
                        "streamerSocketUrl": stream_url, "schwabClientCustomerId": "stand-in",
                        "schwabClientCorrelId": "stand-in", "schwabClientChannel": "N9",
                        "schwabClientFunctionId": "APIAPP"}], "offers": []}).encode())
                symbols = parse_qs(url.query).get("symbols", [""])[0].split(",")
                reply = {s: _SPY_1120_QUOTES[s] for s in symbols if s in _SPY_1120_QUOTES}
                self._send(200, "application/json", json.dumps(reply).encode())

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.transport = _ToLocal(self.server.server_address[1])

    def posts(self) -> "list[float]":
        return [t for t, method, path, _a in self.requests if method == "POST" and path == "/v1/oauth/token"]

    def drop(self) -> None:
        """Schwab drops the streamer connection."""
        self.sockets[-1].close()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()                 # nothing listens: a request is refused
        self.streamer.shutdown()


def _token_file(tmp_path, expires_in_sec: float) -> Path:
    """A token file in schwab-py's shape (stand-in for schwab_token.json)."""
    tok = tmp_path / "schwab_token.json"
    tok.write_text(json.dumps({"creation_timestamp": int(time.time()), "token": {
        "access_token": "old-access", "refresh_token": "r", "token_type": "Bearer",
        "expires_in": 1800, "expires_at": int(time.time() + expires_in_sec)}}))
    return tok
