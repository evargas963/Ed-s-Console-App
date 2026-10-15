"""Schwab's REST host, played by a local server, for tests that run the daemon's chain sweep through
the real schwab-py client (schwab_client.client_from_token_file_atomic, as the daemon builds it).

It answers the expiration chain (each ticker's captured expiry, and PASSED, which has passed), the
chain of a captured expiry in Schwab's chain shape, the quotes of the symbols asked for from the
captured quotes, and the price history of a ticker's series as Schwab answered it. Every request is
recorded once answered: (path, query, started, answered, the client's port).

Real data: SPY's 2026-11-20 chain and its quotes (fixtures/real_spy_2026_11_20_chain_and_quotes.json),
Schwab's /chains answer for TSLA's 2026-10-09 expiry as sent (fixtures/real_schwab_chain_tsla_2026_10_09.json,
captured 2026-10-08; its quotes were not captured), and SPY's and TSLA's /pricehistory answers of 2026-10-07 09:57 UTC
(fixtures/real_pricehistory_spy_tsla_2026_10_07.json: 1-minute, 15-minute and daily candles), and
Schwab's /quotes answer for each of SPY, TSLA, SPCX, META, QQQ, IWM and ZQZQZ asked alone, as the
daemon's watchlist check asks (fixtures/real_schwab_quotes_watchlist_check_2026_10_07.json; ZQZQZ is
named in errors.invalidSymbols), Schwab's /markets answer for every date it answered on
2026-10-07 (fixtures/real_schwab_markets_2026_10_07.json), each chain's isIndex from a /chains
answer Schwab sent for the ticker on 2026-10-08 (fixtures/real_schwab_chain_top_level_spy_tsla_2026_10_08.json),
and Schwab's edge 403 page (fixtures/real_schwab_akamai_403_2026_10_03.json).
STAND-INS: the expiration chains; an answer other than 200 (its body); the refreshed token
(REFRESHED); the body of Schwab's refusal of the sign-in (REFUSED); the user preferences
(`stream_url`: where schwab-py's StreamClient finds the streamer, tests/schwab_stream_standin.py);
a /markets date outside the capture, answered with Schwab's captured 400 for that side (2026-09-29:
more than 7 days back; 2027-10-08: more than a year ahead).
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

import schwab_client as sc

FX = Path(__file__).resolve().parent / "fixtures"
SPY = json.loads((FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
SPY_QUOTES = {s: e for q in SPY["quotes"] for s, e in q["reply"].items()}
_TSLA_ANSWER = json.loads((FX / "real_schwab_chain_tsla_2026_10_09.json").read_text(encoding="utf-8"))["answer"]
TSLA = {"chain": sc.flatten_chain_contracts(_TSLA_ANSWER), "spot": _TSLA_ANSWER["underlyingPrice"]}
#: ticker -> (its captured expiry, its captured contracts, Schwab's underlying price in the capture)
CHAINS = {"SPY": ("2026-11-20", SPY["chain"], SPY["spot"]), "TSLA": ("2026-10-09", TSLA["chain"], TSLA["spot"])}
PASSED = "2026-08-27"
EXPIRATIONS, CHAIN, QUOTES, PRICEHISTORY = ("/marketdata/v1/expirationchain", "/marketdata/v1/chains",
                                            "/marketdata/v1/quotes", "/marketdata/v1/pricehistory")
MARKETS = "/marketdata/v1/markets"
#: ticker -> the top level of a /chains answer Schwab sent for it (its isIndex, as sent)
TOP_LEVEL = {tk: a["top_level"] for tk, a in json.loads(
    (FX / "real_schwab_chain_top_level_spy_tsla_2026_10_08.json").read_text(encoding="utf-8"))["answers"].items()}
#: date -> Schwab's captured /markets answer (status, body as sent)
MARKETS_ANSWERS = json.loads((FX / "real_schwab_markets_2026_10_07.json").read_text(encoding="utf-8"))["answers"]
PREFERENCES = "/trader/v1/userPreference"
#: ticker -> Schwab's captured /quotes answer to it asked alone (status and body)
CHECKS = {a["ticker"]: a for a in json.loads(
    (FX / "real_schwab_quotes_watchlist_check_2026_10_07.json").read_text(encoding="utf-8"))["answers"]}
#: (symbol, frequencyType, frequency) -> Schwab's captured /pricehistory answer
HISTORY = {(a["symbol"], a["params"]["frequencyType"], a["params"]["frequency"]): a for a in json.loads(
    (FX / "real_pricehistory_spy_tsla_2026_10_07.json").read_text(encoding="utf-8"))["answers"]}
TOKEN = "/v1/oauth/token"
#: Schwab's edge 403 page, as captured
EDGE_403 = json.loads((FX / "real_schwab_akamai_403_2026_10_03.json").read_text(encoding="utf-8"))
#: a refreshed token (stand-in)
REFRESHED = {"access_token": "new-access", "refresh_token": "r", "token_type": "Bearer",
             "expires_in": 1800, "scope": "api", "id_token": "i"}
#: Schwab's answer refusing the daemon's refresh token, built from production's stream_capture log
#: (stand-in for the body, which the log does not keep): its status ("REST POST /v1/oauth/token ->
#: 400") and authlib's error and description, Schwab's own `error` and `error_description`
REFUSED = {"error": "unsupported_token_type",
           "error_description": '400 Bad Request: "{"error_description":"Refresh token is invalid, expired or '
                                'revoked","error":"invalid_grant"}"'}


def chain_payload(ticker: str) -> dict:
    """The captured chain in Schwab's chain shape."""
    expiry, contracts, spot = CHAINS[ticker]
    out = {"symbol": ticker, "isIndex": TOP_LEVEL[ticker]["isIndex"], "callExpDateMap": {}, "putExpDateMap": {}}
    if spot is not None:
        out["underlyingPrice"] = spot
    for ct in contracts:
        side = "callExpDateMap" if ct["putCall"] == "CALL" else "putExpDateMap"
        out[side].setdefault(f"{expiry}:{ct['daysToExpiration']}", {}) \
            .setdefault(str(ct["strikePrice"]), []).append(ct)
    return out


class LocalSchwab:
    """The local server, on HTTP/1.1. `quotes_status`: the quotes endpoint's answer while not 200;
    `quotes_body`: while set, the quotes endpoint answers 200 with these bytes as its body;
    `refuse_chain`: tickers whose next chain request is answered 502; `withheld`: symbols the
    quotes answer leaves out; `invalid`: SPY contracts (their /chains entries) served in SPY's
    chain answer, which the quotes answer names in Schwab's errors entry
    (`{"errors": {"invalidSymbols": [...]}}`) instead of quoting them; `stream_url`: the streamer
    the user preferences name (tests/schwab_stream_standin.LocalStreamer.url); `token`: the token
    endpoint's answer ("refreshes": REFRESHED; "refuses": REFUSED, 400; "edge": EDGE_403);
    `answering`: run while the token endpoint answers, before its answer leaves; `edge`: while
    set, every data request is answered with EDGE_403. Each request is recorded as (path, query,
    started, answered, the client's port, its Authorization)."""

    def __init__(self, stream_url: "str | None" = None):
        self.stream_url = stream_url
        self.requests: list = []
        self.token = "refreshes"
        self.answering = lambda: None
        self.edge = False
        self.quotes_status = 200
        self.quotes_body: "bytes | None" = None
        self.refuse_chain: "set[str]" = set()
        self.withheld: "set[str]" = set()
        self.invalid: "list[dict]" = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                started = time.monotonic()
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                if outer.edge:
                    return self._edge(url.path, query, started)
                status, body = outer.answer(url.path, query)
                self._send(url.path, query, started, status, "application/json",
                           body if isinstance(body, bytes) else json.dumps(body).encode())

            def do_POST(self):
                started = time.monotonic()
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.answering()
                if outer.token == "edge":
                    return self._edge(TOKEN, {}, started)
                refused = outer.token == "refuses"
                self._send(TOKEN, {}, started, 400 if refused else 200, "application/json",
                           json.dumps(REFUSED if refused else REFRESHED).encode())

            def _edge(self, path: str, query: dict, started: float):
                self._send(path, query, started, 403, "text/html", EDGE_403["body"].encode(),
                           (("Server", EDGE_403["headers"]["server"]),))

            def _send(self, path: str, query: dict, started: float, status: int, ctype: str, data: bytes,
                      headers: tuple = ()):
                # recorded before the answer leaves, so a client holding the answer finds its request
                outer.requests.append((path, query, started, time.monotonic(), self.client_address[1],
                                       self.headers.get("Authorization")))
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, path: str, query: dict) -> "tuple[int, dict | bytes]":
        if path == EXPIRATIONS:
            return 200, {"expirationList": [{"expirationDate": PASSED},
                                            {"expirationDate": CHAINS[query["symbol"]][0]}]}
        if path == CHAIN:
            if query["symbol"] in self.refuse_chain:
                self.refuse_chain.discard(query["symbol"])
                return 502, {}
            payload = chain_payload(query["symbol"])
            for ct in self.invalid if query["symbol"] == "SPY" else ():
                side = "callExpDateMap" if ct["putCall"] == "CALL" else "putExpDateMap"
                payload[side].setdefault(f"{ct['expirationDate'][:10]}:{ct['daysToExpiration']}", {}) \
                    .setdefault(str(ct["strikePrice"]), []).append(ct)
            return 200, payload
        if path == PRICEHISTORY:
            return 200, HISTORY[(query["symbol"], query["frequencyType"], query["frequency"])]["body"]
        if path == MARKETS:
            day = query["date"]
            a = MARKETS_ANSWERS[day if day in MARKETS_ANSWERS else ("2026-09-29" if day < "2026-09-29" else "2027-10-08")]
            return a["status"], a["body"].encode()
        if path == PREFERENCES:
            return 200, {"streamerInfo": [{"streamerSocketUrl": self.stream_url, "schwabClientCustomerId": "c",
                                           "schwabClientCorrelId": "r", "schwabClientChannel": "N9",
                                           "schwabClientFunctionId": "APIAPP"}]}
        if query["symbols"] in CHECKS:
            return CHECKS[query["symbols"]]["status"], CHECKS[query["symbols"]]["body"]
        if self.quotes_status != 200:
            return self.quotes_status, {}
        if self.quotes_body is not None:
            return 200, self.quotes_body
        asked = query["symbols"].split(",")
        answer = {s: SPY_QUOTES[s] for s in asked if s in SPY_QUOTES and s not in self.withheld}
        named = [s for s in asked if s in {ct["symbol"] for ct in self.invalid}]
        if named:
            answer["errors"] = {"invalidSymbols": named}
        return 200, answer

    def asked(self, path: str) -> "list[dict]":
        """The query of each request to `path`, in order."""
        return [q for p, q, *_ in self.requests if p == path]

    def client(self, tmp_path, expires_in_sec: float = 3600):
        """The daemon's client, its requests delivered here, from a token file (tmp_path /
        schwab_token.json) whose token expires in `expires_in_sec` (far from expiry by default),
        saved whole as every writer of it saves one (sc.write_token_file_atomically)."""
        tok = tmp_path / "schwab_token.json"
        sc.write_token_file_atomically(str(tok), {"creation_timestamp": int(time.time()), "token": {
            "access_token": "a", "refresh_token": "r", "token_type": "Bearer", "expires_in": 1800,
            "expires_at": int(time.time() + expires_in_sec)}})
        return sc.client_from_token_file_atomic(str(tok), "k", "s",
                                                transport=_ToLocal(self.server.server_address[1]))

    def close(self) -> None:
        self.server.shutdown()


class _ToLocal(httpx.BaseTransport):
    """Every request the client sends, delivered to the local server instead of Schwab's host."""

    def __init__(self, port: int):
        self.port, self.inner = port, httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return self.inner.handle_request(request)


def delivered(published: list, ticker: str) -> "dict[str, dict]":
    """The ticker's contracts in the chain the sweep published, by symbol."""
    return {ct["symbol"]: ct for topic, msg in published if topic == f"chain.{ticker}" and "contracts" in msg
            for ct in msg["contracts"]}
