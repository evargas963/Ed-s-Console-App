"""Schwab's REST host, played by a local server, for tests that run the daemon's chain sweep through
the real schwab-py client (schwab_client.client_from_token_file_atomic, as the daemon builds it).

It answers the expiration chain (each ticker's captured expiry, and PASSED, which has passed), the
chain of a captured expiry in Schwab's chain shape, and the quotes of the symbols asked for from the
captured quotes. Every request is recorded once answered: (path, query, started, answered, the
client's port).

Real data: SPY's 2026-11-20 chain and its quotes (fixtures/real_spy_2026_11_20_chain_and_quotes.json)
and TSLA's 2026-08-31 chain (fixtures/real_tsla_complete_chain_strike_range_all.json; its quotes
were not captured). STAND-INS: the expiration chains; an answer other than 200 (its body).
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
TSLA = json.loads((FX / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8"))
#: ticker -> (its captured expiry, its captured contracts, Schwab's underlying price in the capture)
CHAINS = {"SPY": ("2026-11-20", SPY["chain"], SPY["spot"]), "TSLA": ("2026-08-31", TSLA["chain"], None)}
PASSED = "2026-08-27"
EXPIRATIONS, CHAIN, QUOTES = ("/marketdata/v1/expirationchain", "/marketdata/v1/chains",
                              "/marketdata/v1/quotes")


def chain_payload(ticker: str) -> dict:
    """The captured chain in Schwab's chain shape."""
    expiry, contracts, spot = CHAINS[ticker]
    out = {"symbol": ticker, "callExpDateMap": {}, "putExpDateMap": {}}
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
    (`{"errors": {"invalidSymbols": [...]}}`) instead of quoting them."""

    def __init__(self):
        self.requests: list = []
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
                status, body = outer.answer(url.path, query)
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                outer.requests.append((url.path, query, started, time.monotonic(), self.client_address[1]))

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

    def client(self, tmp_path):
        """The daemon's client (a token file far from expiry), its requests delivered here."""
        tok = tmp_path / "schwab_token.json"
        tok.write_text(json.dumps({"creation_timestamp": int(time.time()), "token": {
            "access_token": "a", "refresh_token": "r", "token_type": "Bearer", "expires_in": 1800,
            "expires_at": int(time.time() + 3600)}}))
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
