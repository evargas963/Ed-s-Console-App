"""Schwab's REST host, played by a local server.

For tests that run the daemon's chain sweep through the real schwab-py client
(schwab_client.client_from_token_file_atomic, as the daemon builds it).

It answers the expiration chain (each ticker's captured expiry, and PASSED, which has passed), the
chain of a captured expiry in Schwab's chain shape, the quotes of the symbols asked for from the
captured quotes, and the price history of a ticker's series as Schwab answered it. Every request is
recorded once answered: (path, query, started, answered, the client's port).

Real data: SPY's 2026-11-20 chain and its quotes
(fixtures/real_spy_2026_11_20_chain_and_quotes.json), Schwab's /chains answer for TSLA's 2026-10-09
expiry as sent (fixtures/real_schwab_chain_tsla_2026_10_09.json, captured 2026-10-08; its quotes
were not captured), and SPY's and TSLA's /pricehistory answers of 2026-10-07 09:57 UTC
(fixtures/real_pricehistory_spy_tsla_2026_10_07.json: 1-minute, 15-minute and daily candles;
fixtures/real_pricehistory_5m_30m_spy_tsla_2026_10_07.json: 5- and 30-minute candles), and
Schwab's /quotes answer for each of SPY, TSLA, SPCX, META, QQQ, IWM and ZQZQZ asked alone, as the
daemon's watchlist check asks (fixtures/real_schwab_quotes_watchlist_check_2026_10_07.json; ZQZQZ is
named in errors.invalidSymbols), Schwab's /markets answer for every date it answered on
2026-10-07 (fixtures/real_schwab_markets_2026_10_07.json), each chain's isIndex from a /chains
answer Schwab sent for the ticker on 2026-10-08
(fixtures/real_schwab_chain_top_level_spy_tsla_2026_10_08.json), and Schwab's edge 403 page
(fixtures/real_schwab_akamai_403_2026_10_03.json).
STAND-INS: the expiration chains; an answer other than 200 (its body); the refreshed token
(REFRESHED); the body of Schwab's refusal of the sign-in (REFUSED); the user preferences
(`stream_url`: where schwab-py's StreamClient finds the streamer, tests/schwab_stream_standin.py);
a /markets date outside the capture, answered with Schwab's captured 400 for that side (2026-09-29:
more than 7 days back; 2027-10-08: more than a year ahead).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import schwab_client as sc
import time_et

FX = Path(__file__).resolve().parent / "fixtures"
SPY = json.loads((FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
SPY_QUOTES = {s: e for q in SPY["quotes"] for s, e in q["reply"].items()}
#: the SPY contracts whose captured quote (asked 2026-10-01 04:52 ET) holds another open interest
#: than the captured chain (2026-09-30 15:31 ET): 159 of the 442, each sent as 0 the next morning
SPY_OPEN_INTEREST_MOVED = frozenset(
    c["symbol"]
    for c in SPY["chain"]
    if c["symbol"] in SPY_QUOTES
    and SPY_QUOTES[c["symbol"]]["quote"]["openInterest"] != c["openInterest"]
)
_TSLA_ANSWER = json.loads(
    (FX / "real_schwab_chain_tsla_2026_10_09.json").read_text(encoding="utf-8")
)["answer"]
TSLA = {"chain": sc.flatten_chain_contracts(_TSLA_ANSWER), "spot": _TSLA_ANSWER["underlyingPrice"]}
#: ticker -> (its captured expiry, its captured contracts, Schwab's underlying price in the capture)
CHAINS = {
    "SPY": ("2026-11-20", SPY["chain"], SPY["spot"]),
    "TSLA": ("2026-10-09", TSLA["chain"], TSLA["spot"]),
}
PASSED = "2026-08-27"
EXPIRATIONS, CHAIN, QUOTES, PRICEHISTORY = (
    "/marketdata/v1/expirationchain",
    "/marketdata/v1/chains",
    "/marketdata/v1/quotes",
    "/marketdata/v1/pricehistory",
)
MARKETS = "/marketdata/v1/markets"
#: ticker -> the top level of a /chains answer Schwab sent for it (its isIndex, as sent)
TOP_LEVEL = {
    tk: a["top_level"]
    for tk, a in json.loads(
        (FX / "real_schwab_chain_top_level_spy_tsla_2026_10_08.json").read_text(encoding="utf-8")
    )["answers"].items()
}
#: date -> Schwab's captured /markets answer (status, body as sent)
MARKETS_ANSWERS = json.loads(
    (FX / "real_schwab_markets_2026_10_07.json").read_text(encoding="utf-8")
)["answers"]
PREFERENCES = "/trader/v1/userPreference"
#: ticker -> Schwab's captured /quotes answer to it asked alone (status and body)
CHECKS = {
    a["ticker"]: a
    for a in json.loads(
        (FX / "real_schwab_quotes_watchlist_check_2026_10_07.json").read_text(encoding="utf-8")
    )["answers"]
}
#: (symbol, frequencyType, frequency) -> Schwab's captured /pricehistory answer
HISTORY = {
    (a["symbol"], a["params"]["frequencyType"], a["params"]["frequency"]): a
    for name in (
        "real_pricehistory_spy_tsla_2026_10_07.json",
        "real_pricehistory_5m_30m_spy_tsla_2026_10_07.json",
    )
    for a in json.loads((FX / name).read_text(encoding="utf-8"))["answers"]
}
TOKEN = "/v1/oauth/token"
#: Schwab's edge 403 page, as captured
EDGE_403 = json.loads((FX / "real_schwab_akamai_403_2026_10_03.json").read_text(encoding="utf-8"))
#: a refreshed token (stand-in)
REFRESHED = {
    "access_token": "new-access",
    "refresh_token": "r",
    "token_type": "Bearer",
    "expires_in": 1800,
    "scope": "api",
    "id_token": "i",
}
#: Schwab's answer refusing the daemon's refresh token, built from production's stream_capture log
#: (stand-in for the body, which the log does not keep): its status
#: ("REQUEST POST /v1/oauth/token -> 400") and authlib's error and description, Schwab's own
#: `error` and `error_description`
REFUSED = {
    "error": "unsupported_token_type",
    "error_description": '400 Bad Request: "{"error_description":'
    '"Refresh token is invalid, expired or '
    'revoked","error":"invalid_grant"}"',
}


#: Schwab's challenge on a data request whose access token expired, as production's stream_capture
#: log of 2026-11-05 07:09 CT records it (a 401 with an empty body)
INVALID_TOKEN = (
    'Bearer realm="null",error="invalid_token",'
    'error_description="keymanagement.service.access_token_expired: Access Token expired"'
)


def chain_payload(ticker: str) -> dict:
    """Return the captured chain in Schwab's chain shape."""
    expiry, contracts, spot = CHAINS[ticker]
    out = {
        "symbol": ticker,
        "isIndex": TOP_LEVEL[ticker]["isIndex"],
        "callExpDateMap": {},
        "putExpDateMap": {},
    }
    if spot is not None:
        out["underlyingPrice"] = spot
    for ct in contracts:
        side = "callExpDateMap" if ct["putCall"] == "CALL" else "putExpDateMap"
        out[side].setdefault(f"{expiry}:{ct['daysToExpiration']}", {}).setdefault(
            str(ct["strikePrice"]), []
        ).append(ct)
    return out


class LocalSchwab:
    """The local server, on HTTP/1.1.

    `quotes_status`: the quotes endpoint's answer while not 200; `quotes_body`: while set, the
    quotes endpoint answers 200 with these bytes as its body;
    `refuse_chain`: tickers whose next chain request is answered 502; `throttle_chain`: tickers
    whose next chain request is answered 429; `withheld`: symbols the
    quotes answer leaves out; `invalid`: SPY contracts (their /chains entries) served in SPY's
    chain answer, which the quotes answer names in Schwab's errors entry
    (`{"errors": {"invalidSymbols": [...]}}`) instead of quoting them; `stream_url`: the streamer
    the user preferences name (tests/schwab_stream_standin.LocalStreamer.url); `token`: the token
    endpoint's answer ("refreshes": REFRESHED; "refuses": REFUSED, 400; "edge": EDGE_403);
    `expired`: access tokens a data request carrying one is answered 401 for, with Schwab's
    INVALID_TOKEN challenge; `edge`:
    while set, every data request is answered with EDGE_403. Each request is recorded as (path,
    query, started, answered, the client's port, its Authorization).
    """

    def __init__(self, stream_url: str | None = None):
        self.stream_url = stream_url
        self.requests: list = []
        self.token = "refreshes"
        self.expired: set[str] = set()
        self.edge = False
        self.quotes_status = 200
        self.quotes_body: bytes | None = None
        self.refuse_chain: set[str] = set()
        self.throttle_chain: set[str] = set()
        self.withheld: set[str] = set()
        self.invalid: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                started = time_et.elapsed()
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                if outer.edge:
                    self._edge(url.path, query, started)
                    return
                if self.headers.get("Authorization") in {f"Bearer {a}" for a in outer.expired}:
                    self._send(
                        url.path,
                        query,
                        started,
                        401,
                        "application/json",
                        b"",
                        (("WWW-Authenticate", INVALID_TOKEN),),
                    )
                    return
                status, body = outer.answer(url.path, query)
                self._send(
                    url.path,
                    query,
                    started,
                    status,
                    "application/json",
                    body if isinstance(body, bytes) else json.dumps(body).encode(),
                )

            def do_POST(self):
                started = time_et.elapsed()
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if outer.token == "edge":
                    self._edge(TOKEN, {}, started)
                    return
                refused = outer.token == "refuses"
                self._send(
                    TOKEN,
                    {},
                    started,
                    400 if refused else 200,
                    "application/json",
                    json.dumps(REFUSED if refused else REFRESHED).encode(),
                )

            def _edge(self, path: str, query: dict, started: float):
                self._send(
                    path,
                    query,
                    started,
                    403,
                    "text/html",
                    EDGE_403["body"].encode(),
                    (("Server", EDGE_403["headers"]["server"]),),
                )

            def _send(
                self,
                path: str,
                query: dict,
                started: float,
                status: int,
                ctype: str,
                data: bytes,
                headers: tuple = (),
            ):
                # recorded before the answer leaves, so a client holding the answer finds its
                # request
                outer.requests.append(
                    (
                        path,
                        query,
                        started,
                        time_et.elapsed(),
                        self.client_address[1],
                        self.headers.get("Authorization"),
                    )
                )
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

    def answer(self, path: str, query: dict) -> tuple[int, dict | bytes]:
        """Schwab's answer to a request for `path` with `query` (/quotes: any other path)."""
        by_path = {
            EXPIRATIONS: self._expirations,
            CHAIN: self._chain,
            PRICEHISTORY: self._pricehistory,
            MARKETS: self._markets,
            PREFERENCES: self._preferences,
        }
        return by_path.get(path, self._quotes)(query)

    @staticmethod
    def _expirations(query: dict) -> tuple[int, dict]:
        return 200, {
            "expirationList": [
                {"expirationDate": PASSED},
                {"expirationDate": CHAINS[query["symbol"]][0]},
            ]
        }

    def _chain(self, query: dict) -> tuple[int, dict]:
        if query["symbol"] in self.refuse_chain:
            self.refuse_chain.discard(query["symbol"])
            return 502, {}
        if query["symbol"] in self.throttle_chain:
            self.throttle_chain.discard(query["symbol"])
            return 429, {}
        payload = chain_payload(query["symbol"])
        for ct in self.invalid if query["symbol"] == "SPY" else ():
            side = "callExpDateMap" if ct["putCall"] == "CALL" else "putExpDateMap"
            payload[side].setdefault(
                f"{ct['expirationDate'][:10]}:{ct['daysToExpiration']}", {}
            ).setdefault(str(ct["strikePrice"]), []).append(ct)
        return 200, payload

    @staticmethod
    def _pricehistory(query: dict) -> tuple[int, dict]:
        return 200, HISTORY[(query["symbol"], query["frequencyType"], query["frequency"])]["body"]

    @staticmethod
    def _markets(query: dict) -> tuple[int, bytes]:
        day = query["date"]
        a = MARKETS_ANSWERS[
            day
            if day in MARKETS_ANSWERS
            else ("2026-09-29" if day < "2026-09-29" else "2027-10-08")
        ]
        return a["status"], a["body"].encode()

    def _preferences(self, _query: dict) -> tuple[int, dict]:
        return 200, {
            "streamerInfo": [
                {
                    "streamerSocketUrl": self.stream_url,
                    "schwabClientCustomerId": "c",
                    "schwabClientCorrelId": "r",
                    "schwabClientChannel": "N9",
                    "schwabClientFunctionId": "APIAPP",
                }
            ]
        }

    def _quotes(self, query: dict) -> tuple[int, dict]:
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

    def asked(self, path: str) -> list[dict]:
        """Return the query of each request to `path`, in order."""
        return [q for p, q, *_ in self.requests if p == path]

    def client(self, tmp_path, expires_in_sec: float = 3600):
        """Return the daemon's client, its requests delivered here, from token_file's file."""
        return self.delivering_here(
            sc.client_from_token_file_atomic(self.token_file(tmp_path, expires_in_sec), "k", "s")
        )

    def delivering_here(self, client):
        """`client`, every request it sends delivered here instead of Schwab's host.

        The token refresh included (schwab-py and the token endpoint name that host themselves).
        """
        port = self.server.server_address[1]

        def deliver(request) -> None:
            request.url = request.url.copy_with(scheme="http", host="127.0.0.1", port=port)

        client.session.event_hooks["request"].append(deliver)
        return client

    def token_file(self, tmp_path, expires_in_sec: float = 3600) -> str:
        """Write a token file (tmp_path / schwab_token.json) expiring in `expires_in_sec`.

        Its token is far from expiry by default; it is saved whole as every writer of it saves
        one (sc.write_token_file_atomically).
        """
        tok = tmp_path / "schwab_token.json"
        sc.write_token_file_atomically(
            str(tok),
            {
                "creation_timestamp": int(time_et.now()),
                "token": {
                    "access_token": "a",
                    "refresh_token": "r",
                    "token_type": "Bearer",
                    "expires_in": 1800,
                    "expires_at": int(time_et.now() + expires_in_sec),
                },
            },
        )
        return str(tok)

    def close(self) -> None:
        self.server.shutdown()


def delivered(published: list, ticker: str) -> dict[str, dict]:
    """Return the ticker's contracts in the chain the sweep published (read), by symbol."""
    return {
        ct.symbol: ct
        for topic, msg in published
        if topic == f"chain.{ticker}" and "contracts" in msg
        for ct in msg["contracts"]
    }
