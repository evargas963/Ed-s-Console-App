# schwab_client.py
"""
Centralized Schwab client construction and safe API wrappers.
Token path is always absolute.
"""
import json
import os
import re
import socket
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import urlparse

import httpx
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.httpx_client import OAuth2Client
from schwab import auth
from schwab.client import Client
from schwab.debug import register_redactions

from time_et import now_et
import logging

log = logging.getLogger(__name__)



@dataclass
class SchwabClientState:
    ok: bool
    message: str
    client: object | None


@dataclass
class TokenInspectionResult:
    """Structured result from inspect_token_file (no secret values)."""
    file_exists: bool = False
    json_valid: bool = False
    has_creation_timestamp: bool = False
    has_token_object: bool = False
    has_access_token: bool = False
    has_refresh_token: bool = False
    has_expires_at: bool = False
    scope_value: Optional[str] = None
    seconds_to_expiry: Optional[int] = None
    is_expired: bool = False
    is_expiring_soon: bool = False
    message: str = ""


def _resolve_token_path(token_path: str) -> str:
    """Ensure token path is absolute. Idempotent if already absolute."""
    return os.path.abspath(os.path.expanduser(token_path))


#: os.replace on Windows fails with a sharing violation while another process (the console or
#: the capture daemon) has the token file open for its brief read; the SAME write is retried.
TOKEN_REPLACE_ATTEMPTS = 5


def write_token_file_atomically(token_path: str, payload: dict) -> None:
    """Write schwab_token.json via temp + fsync + os.replace -- never a partial file.

    THE token writer: every Schwab client this repo builds refreshes through it
    (client_from_token_file_atomic / the OAuth exchange). schwab-py's own writer is
    open(path, 'w') + json.dump -- a reader in the other process (console / daemon both
    refresh the same file) could load a torn token and fail the session (audit of #280)."""
    import tempfile
    from pathlib import Path

    path = Path(_resolve_token_path(token_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, TOKEN_REPLACE_ATTEMPTS + 1):
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline=chr(10)) as fh:
                json.dump(payload, fh, indent=2, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            return
        except PermissionError as e:
            Path(tmp).unlink(missing_ok=True)
            if attempt == TOKEN_REPLACE_ATTEMPTS:
                raise
            log.warning("token replace blocked by another reader (attempt %s/%s): %s",
                           attempt, TOKEN_REPLACE_ATTEMPTS, e)
            time.sleep(0.05 * attempt)


def _token_update_func(resolved: str):
    """schwab-py token_write_func: every refresh goes through write_token_file_atomically."""
    def update_token(t, *args, **kwargs):
        write_token_file_atomically(resolved, t)
        log.info("schwab token refreshed and written; Schwab's expires_in: %s s",
                 t["token"].get("expires_in"))
    return update_token


def _token_read_func(resolved: str):
    def load_token():
        with open(resolved, "rb") as f:
            return json.load(f)
    return load_token


#: response headers never written to a log
UNLOGGED_HEADERS = frozenset({"set-cookie", "cookie", "authorization", "proxy-authorization"})
#: the longest error body logged, in characters
ERROR_BODY_LOGGED = 2000
#: (status, method, path) -> [minute last logged, answers since]
_errors_logged: "dict[tuple, list]" = {}
_errors_lock = threading.Lock()


def log_schwab_error(response: httpx.Response) -> None:
    """Every Schwab answer that is not a success, as Schwab sent it: the request (method, path;
    the query on market-data paths), the status, the error body and the response headers, with
    the time of the log line and Schwab's own Date header. The token endpoint's body carries
    tokens and is never logged; request headers (the bearer token) never are. The same status
    on the same path is logged once a minute, with how many answers came since the last line."""
    if response.status_code < 400:
        return
    req = response.request
    path = re.sub(r"(/accounts/)[^/]+", r"\1(account)", req.url.path)
    response.read()
    body = "(token endpoint: not logged)" if path.endswith("/oauth/token") else response.text[:ERROR_BODY_LOGGED]
    query = req.url.query.decode() if path.startswith("/marketdata/") else ""
    headers = {k: v for k, v in response.headers.items() if k.lower() not in UNLOGGED_HEADERS}
    key = (response.status_code, req.method, path)
    minute = int(time.time() // 60)
    with _errors_lock:
        seen = _errors_logged.setdefault(key, [None, 0])
        if seen[0] == minute:
            seen[1] += 1
            return
        since, seen[0], seen[1] = seen[1], minute, 0
    log.warning("schwab answered %s %s%s -> %s (%d more since the last line) | body: %s | headers: %s",
                req.method, path, f"?{query}" if query else "", response.status_code, since, body, headers)


class OneRefreshSession(OAuth2Client):
    """authlib's OAuth2Client, refreshing the token one request at a time: authlib's own (sync)
    client lets every request that finds the token near expiry refresh it, all at once. The
    first refreshes; each one after it finds the new token and sends its request with it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._refresh_lock = threading.Lock()

    def ensure_active_token(self, token=None):
        with self._refresh_lock:
            return super().ensure_active_token(self.token)


def client_from_token_file_atomic(token_path: str, api_key: str, app_secret: str, *,
                                  enforce_enums: bool = False,
                                  transport: "httpx.BaseTransport | None" = None):
    """schwab-py's client from the token file, built as auth.client_from_access_functions builds
    it, with four differences: every token refresh is written atomically (schwab-py's writer
    rewrites the file in place), the token is refreshed by one request at a time
    (OneRefreshSession), the session holds as many connections at once as there are requests
    (httpx's default is 100, and schwab-py passes it nothing), and every answer that is not a
    success is logged as Schwab sent it (log_schwab_error). `transport` carries every request,
    the token refresh included: the network when None, a local stand-in for Schwab in a test
    (schwab-py and the token endpoint name Schwab's host themselves)."""
    resolved = _resolve_token_path(token_path)
    metadata = auth.TokenMetadata.from_loaded_token(_token_read_func(resolved)(),
                                                     _token_update_func(resolved))
    register_redactions(metadata.token)
    session = OneRefreshSession(api_key, client_secret=app_secret, token=metadata.token,
                                token_endpoint=auth.TOKEN_ENDPOINT,
                                update_token=metadata.wrapped_token_write_func(), leeway=300,
                                limits=httpx.Limits(max_connections=None, max_keepalive_connections=None),
                                event_hooks={"response": [log_schwab_error]}, transport=transport)
    return Client(api_key, session, token_metadata=metadata, enforce_enums=enforce_enums)


def inspect_token_file(token_path: str) -> TokenInspectionResult:
    """Inspect schwab-py token JSON at token_path (normalized to absolute). Does not log secrets."""
    out = TokenInspectionResult()
    resolved = _resolve_token_path(token_path)
    if not os.path.isfile(resolved):
        out.message = f"Token file not found at {resolved!r}"
        return out
    out.file_exists = True
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw)
        out.json_valid = True
    except json.JSONDecodeError as e:
        out.message = f"Invalid JSON in token file: {e}"
        return out
    except OSError as e:
        out.message = f"Cannot read token file: {e}"
        return out

    if not isinstance(data, dict):
        out.message = "Token file root must be a JSON object"
        return out

    out.has_creation_timestamp = "creation_timestamp" in data
    tok = data.get("token")   # external-key-ok: schwab-py token file
    if isinstance(tok, dict):
        out.has_token_object = True
        at = tok.get("access_token")   # external-key-ok: Schwab OAuth token payload
        out.has_access_token = isinstance(at, str) and len(at.strip()) > 0
        rt = tok.get("refresh_token")   # external-key-ok: Schwab OAuth token payload
        out.has_refresh_token = isinstance(rt, str) and len(rt.strip()) > 0
        out.has_expires_at = "expires_at" in tok
        sc = tok.get("scope")
        if isinstance(sc, str) and sc.strip():
            out.scope_value = sc.strip()
        elif sc is not None:
            out.scope_value = str(sc)

        now = int(time.time())
        exp = tok.get("expires_at")   # external-key-ok: Schwab OAuth token payload
        if exp is not None:
            try:
                exp_i = int(float(exp))
            except (TypeError, ValueError):
                exp_i = None
            if exp_i is not None:
                seconds_left = exp_i - now
                out.seconds_to_expiry = seconds_left
                out.is_expired = seconds_left <= 0
                out.is_expiring_soon = 0 < seconds_left < 300

    issues: list[str] = []
    if not out.has_creation_timestamp:
        issues.append("missing creation_timestamp")
    if not out.has_token_object:
        issues.append("missing or invalid token object")
    if not out.has_access_token:
        issues.append("missing or empty access_token")
    if not out.has_refresh_token:
        issues.append("missing or empty refresh_token (not refreshable)")
    if not out.has_expires_at:
        issues.append("missing expires_at")
    if issues:
        out.message = "Token structure issues: " + "; ".join(issues)
    else:
        out.message = "Token file structure OK; refreshable."
    return out


def auth_is_refreshable(inspection: TokenInspectionResult) -> bool:
    """True only if refresh_token is present and non-empty (inspection only; no I/O)."""
    return inspection.has_refresh_token


def build_client_from_token(token_path: str, api_key: str, app_secret: str) -> SchwabClientState:
    """Build Schwab client from token file. token_path is normalized to absolute."""
    from config import schwab_live_blocked_for

    if schwab_live_blocked_for(api_key=api_key, app_secret=app_secret):
        return SchwabClientState(
            ok=False,
            message=(
                "Schwab capability UNAVAILABLE (missing credentials, ci-placeholder "
                "credentials, or ED_CI_OFFLINE) — live client construction blocked; "
                "no Schwab API calls."
            ),
            client=None,
        )
    resolved = _resolve_token_path(token_path)
    inv = inspect_token_file(resolved)
    if not inv.file_exists:
        return SchwabClientState(
            ok=False,
            message=f"Token file not found: {resolved}. {inv.message}",
            client=None,
        )
    if not inv.json_valid:
        return SchwabClientState(
            ok=False,
            message=f"Schwab token file is not valid JSON at {resolved!r}. {inv.message}",
            client=None,
        )
    if not inv.has_creation_timestamp or not inv.has_token_object:
        return SchwabClientState(
            ok=False,
            message=(
                f"Schwab token file malformed (expected schwab-py layout with creation_timestamp and token) "
                f"at {resolved!r}. {inv.message}"
            ),
            client=None,
        )
    if not inv.has_access_token:
        return SchwabClientState(
            ok=False,
            message=f"Schwab token file missing access_token at {resolved!r}. {inv.message}",
            client=None,
        )
    if not inv.has_expires_at:
        return SchwabClientState(
            ok=False,
            message=f"Schwab token file missing expires_at at {resolved!r}. {inv.message}",
            client=None,
        )
    if not auth_is_refreshable(inv):
        return SchwabClientState(
            ok=False,
            message=(
                f"Schwab token is NOT refreshable (refresh_token missing or empty) at {resolved!r}. "
                "Remediation: python reauth_schwab.py --manual"
            ),
            client=None,
        )
    try:
        c = client_from_token_file_atomic(
            resolved,
            api_key,
            app_secret,
            enforce_enums=False,  # critical with your current schwab-py install
        )
        return SchwabClientState(ok=True, message="Client loaded from token file.", client=c)
    except Exception as e:
        return SchwabClientState(ok=False, message=f"Unable to create Schwab client: {e}", client=None)

def _parse_callback_port(callback_url: str) -> tuple[str, int]:
    """Parse host and port from callback URL (e.g. https://127.0.0.1:8182)."""
    parsed = urlparse(callback_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8182
    return host, port


def _wait_for_callback_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Poll until the callback port is accepting connections. Returns True if ready."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                pass
            return True
        except (socket.error, OSError):
            time.sleep(0.1)
    return False


def run_login_flow(api_key: str, app_secret: str, callback_url: str, token_path: str) -> tuple[bool, str]:
    """
    Browser-assisted login flow (blocking). Creates token file at token_path on success.
    Waits for callback port to be ready before proceeding; verifies token exists after flow.
    """
    exc_holder: list[BaseException] = []

    def _run():
        try:
            auth.client_from_login_flow(
                api_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
                token_path=token_path,
                token_write_func=_token_update_func(_resolve_token_path(token_path)),  # atomic
                enforce_enums=False,
                interactive=False,
                callback_timeout=float(os.environ.get("SCHWAB_OAUTH_CALLBACK_TIMEOUT_SEC", "900")),  # caps-ok: OAuth/config timeout only
            )
        except BaseException as e:
            exc_holder.append(e)

    try:
        host, port = _parse_callback_port(callback_url)
        t = threading.Thread(target=_run, daemon=False)
        t.start()

        if not _wait_for_callback_port(host, port, timeout=5.0):
            return False, (
                f"Callback server on {host}:{port} did not become ready within 5 seconds. "
                "The browser may have opened before the local listener was ready."
            )

        t.join()

        if exc_holder:
            return False, f"OAuth flow failed: {exc_holder[0]}"

        if not os.path.exists(token_path):
            raise RuntimeError(
                f"OAuth flow completed but token file was not written: {token_path}. "
                "The browser may have redirected before the callback was received, "
                "or there was a silent write failure. Try: python reauth_schwab.py --manual"
            )

        return True, f"Token created: {token_path}"
    except RuntimeError:
        raise
    except Exception as e:
        return False, f"OAuth flow failed: {e}"


def run_manual_flow(api_key: str, app_secret: str, callback_url: str, token_path: str) -> tuple[bool, str]:
    """
    Manual copy-paste login flow. No local server — you paste the redirect URL back.
    Use when the browser callback fails (e.g. cert warning blocks the request).
    """
    try:
        auth.client_from_manual_flow(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=token_path,
            token_write_func=_token_update_func(_resolve_token_path(token_path)),  # atomic
            enforce_enums=False,
        )
        if not os.path.exists(token_path):
            raise RuntimeError(
                f"Manual flow completed but token file was not written: {token_path}"
            )
        return True, f"Token created: {token_path}"
    except RuntimeError:
        raise
    except Exception as e:
        return False, f"OAuth flow failed: {e}"


def complete_oauth_from_redirect_url(
    redirect_url: str,
    *,
    api_key: str,
    app_secret: str,
    callback_url: str,
    token_path: str,
) -> tuple[bool, str]:
    """
    Finish OAuth when the browser already redirected but the local callback server
    did not persist the token (common: self-signed cert warning on 127.0.0.1:8182).
    """
    from urllib.parse import parse_qs, urlparse

    url = (redirect_url or "").strip()
    if not url:
        return False, "Redirect URL is empty."
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    state = (qs.get("state") or [None])[0]  # caps-ok: parse_qs indexing idiom only
    if not (qs.get("code") or [None])[0]:  # caps-ok: parse_qs indexing idiom only
        return False, "Redirect URL missing OAuth code query parameter."

    resolved = _resolve_token_path(token_path)
    auth_context = auth.get_auth_context(api_key, callback_url, state=state)
    token_write_func = _token_update_func(resolved)       # atomic, never in place
    try:
        auth.client_from_received_url(
            api_key,
            app_secret,
            auth_context,
            url,
            token_write_func,
            asyncio=False,
            enforce_enums=False,
        )
    except Exception as e:
        return False, f"OAuth token exchange failed: {e}"
    if not os.path.isfile(resolved):
        return False, f"Token exchange succeeded but file missing: {resolved}"
    return True, f"Token created: {resolved}"

class SchwabAuthError(Exception):
    """Schwab OAuth / refresh token failure — fail fast; do not retry chain/quote for minutes."""

    def __init__(self, message: str, *, remediation: str = "python reauth_schwab.py --manual"):
        super().__init__(message)
        self.remediation = remediation


#: each client's auth latch: after an OAuth failure on a client, its chain, expiration list and quote requests are
#: withheld until this monotonic time. The latch belongs to the client whose token failed (the
#: daemon holds one for its life, capture.one_schwab_client); another client is not withheld.
_auth_failure_until: "weakref.WeakKeyDictionary[object, float]" = weakref.WeakKeyDictionary()
_auth_failure_lock = threading.Lock()
_SCHWAB_AUTH_FAILURE_LATCH_SEC = float(os.environ.get("ED_SCHWAB_AUTH_FAILURE_LATCH_SEC", "300"))  # caps-ok: OAuth/config timeout only


def _is_token_error(exc: BaseException) -> bool:
    """True for an OAuth failure: every error authlib raises (expired / missing / revoked token,
    refresh rejected with invalid_grant) derives from AuthlibBaseError."""
    return isinstance(exc, AuthlibBaseError)


def _latched_auth_error(client, exc: BaseException) -> SchwabAuthError:
    """Latch `client` after the OAuth failure `exc`; the SchwabAuthError its caller raises."""
    with _auth_failure_lock:
        _auth_failure_until[client] = time.monotonic() + _SCHWAB_AUTH_FAILURE_LATCH_SEC
    return SchwabAuthError(str(exc))


def _schwab_auth_latched(client) -> bool:
    with _auth_failure_lock:
        until = _auth_failure_until.get(client)
    return until is not None and time.monotonic() < until


def safe_get_chain(client, ticker: str, *, strike_count: int | None = 20,
                   strike_range: str | None = None, from_date=None, to_date=None):
    # schwab-py supports optional args; we keep them optional to reduce breakage.
    # `strike_range` (schwab-py's Options.StrikeRange, e.g. "ALL") is a DIFFERENT vendor
    # selection dimension than strike_count (N strikes above/below ATM) — MEASURED live
    # 2026-08-30: strike_count=250 alone silently truncated a real SPY single-expiry chain
    # by 69 strikes (missed range 420.0-644.0) that strike_range="ALL" correctly returned,
    # confirmed converged against an independent strike_count=500 saturation check on the
    # SAME request. When strike_range is given, strike_count is OMITTED entirely rather
    # than sent alongside it — exactly the combination proven live, never an untested
    # combination of both params on one request.
    if _schwab_auth_latched(client):
        raise SchwabAuthError(
            "Schwab auth latched after prior token failure — option chain withheld"
        )
    kwargs = {"include_underlying_quote": True}
    if strike_range is not None:
        kwargs["strike_range"] = strike_range
    elif strike_count is not None:
        kwargs["strike_count"] = strike_count
    if from_date is not None:
        kwargs["from_date"] = from_date
    if to_date is not None:
        kwargs["to_date"] = to_date
    try:
        resp = client.get_option_chain(ticker, **kwargs)
    except Exception as e:
        if _is_token_error(e):
            raise _latched_auth_error(client, e) from e
        raise
    return resp


class FullChainResponse:
    """The whole chain as one response: `status_code` 200 and `.json()` the merged Schwab
    payload, or the failing part's status with no payload."""

    def __init__(self, status_code: "int | None", payload: "dict | None" = None,
                 parts: int = 0, reason: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.parts = parts
        self.reason = reason

    def json(self) -> dict:
        return self._payload if self._payload is not None else {}


#: Vendor answers that mean "this request covers too much", not "this symbol is refused".
#: MEASURED 2026-09-25: SPY (13,290 contracts), QQQ (11,710), MU (11,204) and $SPX (29,858)
#: answered a one-shot strike_range=ALL request with HTTP 502; META (7,988) and AMD (6,628)
#: did not. No Schwab document states the limit, so none is assumed here: a refused range is
#: split and retried.
_CHAIN_TOO_BIG_CODES = (502, 413, 500, 504)
#: ticker -> how many date-range parts its whole chain last needed (learned, never guessed).
_full_chain_parts: dict[str, int] = {}
_full_chain_parts_lock = threading.Lock()


def _option_expiries(client, ticker: str) -> "tuple[int, list[date]]":
    """Schwab's status for `ticker`'s expiration list, and every listed expiry that has not passed
    (ET date), ascending (none unless the status is 200). MEASURED 2026-09-26 (Saturday): the
    expiration chain still lists Friday's expired 2026-09-25, and a chain request whose fromDate
    is in the past is refused with HTTP 400 ("Check Param Values") -- the same range from today
    answers 200. Withheld, like the chain and quotes, while `client`'s auth latch holds."""
    if _schwab_auth_latched(client):
        raise SchwabAuthError("Schwab auth latched after prior token failure — expiration list withheld")
    try:
        resp = client.get_option_expiration_chain(ticker)
    except AuthlibBaseError as e:       # an OAuth failure (_is_token_error)
        raise _latched_auth_error(client, e) from e
    if resp.status_code != 200:
        return resp.status_code, []
    today = now_et().date()
    return 200, sorted({d for d in (date.fromisoformat(str(e["expirationDate"])[:10])
                               for e in (resp.json().get("expirationList") or []) if e.get("expirationDate"))  # external-key-ok: Schwab expiration chain response
                   if d >= today})


def safe_get_quotes(client, symbols: "list[str]"):
    """One request to Schwab's quotes endpoint (/marketdata/v1/quotes) for `symbols`, the quote
    fields only; Schwab's response."""
    if _schwab_auth_latched(client):
        raise SchwabAuthError("Schwab auth latched after prior token failure — quotes withheld")
    try:
        return client.get_quotes(symbols, fields=["quote"])
    except Exception as e:
        if _is_token_error(e):
            raise _latched_auth_error(client, e) from e
        raise


#: The most option symbols one quotes request carries: 300 answered in 0.3 s, 400 was refused
#: with HTTP 400 (the request's URL length).
QUOTES_BATCH_MAX = 300
#: The contract fields Schwab's chain sends rounded to 3 decimals and its quotes send as computed
#: (SPY 261120C00875000: chain gamma 0.0, delta 0.005; quote gamma 0.00037225, delta 0.00518524).
GREEK_FIELDS = ("gamma", "delta", "theta", "vega", "rho", "volatility")


def _send_each(send, items: list, alone: bool, refused) -> list:
    """`send(item)` for every item, every request at once; `alone`: one at a time, ending at the
    first answer that is `refused`, so Schwab sees at most one refused request."""
    if not alone:
        with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
            return list(pool.map(send, items))
    answers = []
    for item in items:
        answers.append(send(item))
        if refused(answers[-1]):
            break
    return answers


def fetch_full_chain(client, ticker: str, *, alone: bool = False) -> FullChainResponse:
    """EVERY strike of every listed expiry -- the chain all level math is computed from -- with
    each contract's Greeks as Schwab's quotes send them: strike_range=ALL chain requests
    (safe_get_chain) and quotes requests (safe_get_quotes) on `client`. `alone` (the sweep's
    probe after Schwab refused it): every request one at a time, stopping at the first refused.

    MEASURED 2026-09-25 across the 42 board tickers: levels computed from the old strike
    window disagreed with the same code run on the full chain -- gamma flip missing for 10
    tickers, max pain different for 16, put wall for 4, $SPX walls 3-4% apart. Operator
    decision 2026-09-25: the full chain for all calculations.

    The chain's GREEK_FIELDS are replaced by the contract's quote's, as sent, asked for in
    batches of QUOTES_BATCH_MAX, every batch at once; a contract whose quote does not come back
    has none of them (None), never the chain's rounded value. A batch Schwab refuses fails the
    whole chain (its status and reason), like a missing chain part: a book missing a batch of
    Greeks is not the book. Each fetch logs its contracts, requests and their times."""
    t0 = time.perf_counter()
    resp = _whole_chain(client, ticker, alone)
    if resp.status_code != 200:
        return resp
    t_chain = time.perf_counter() - t0
    contracts = [ct for side in ("callExpDateMap", "putExpDateMap")
                 for by_strike in (resp.json().get(side) or {}).values() if isinstance(by_strike, dict)
                 for listed in by_strike.values() if isinstance(listed, list)
                 for ct in listed if isinstance(ct, dict)]
    symbols = list(dict.fromkeys(ct["symbol"] for ct in contracts if ct.get("symbol")))
    batches = [symbols[i:i + QUOTES_BATCH_MAX] for i in range(0, len(symbols), QUOTES_BATCH_MAX)]
    t1 = time.perf_counter()
    replies = _send_each(lambda batch: safe_get_quotes(client, batch), batches, alone,
                         lambda reply: reply.status_code != 200)
    quoted: dict = {}
    for batch, reply in zip(batches, replies):
        if reply.status_code != 200:
            return FullChainResponse(reply.status_code, reason=(
                f"quotes for {len(batch)} of {len(symbols)} contracts "
                f"returned HTTP {reply.status_code}"))
        quoted.update({s: e["quote"] for s, e in reply.json().items()
                       if isinstance(e, dict) and isinstance(e.get("quote"), dict)})
    log.info("chain %s: %d contracts; chain %d part(s) %.2f s; quotes %d request(s) %.2f s; total %.2f s",
             ticker, len(contracts), resp.parts, t_chain, len(batches), time.perf_counter() - t1,
             time.perf_counter() - t0)
    for ct in contracts:
        q = quoted.get(ct.get("symbol")) or {}
        ct.update({f: q.get(f) for f in GREEK_FIELDS})
    missing = sum(1 for ct in contracts if ct.get("symbol") not in quoted)
    if missing:
        log.warning("quotes for %s: no quote came back for %d of %d contracts; their Greeks are absent",
                    ticker, missing, len(contracts))
    return resp


def _whole_chain(client, ticker: str, alone: bool) -> FullChainResponse:
    """The chain of `fetch_full_chain`. One request when Schwab answers it. When the vendor
    answers that the request covers too much, the listed expiries are split into contiguous
    date ranges, all requested at once (one at a time when `alone`), halving any range that is itself refused; the part count
    that worked is remembered per ticker. Every part must land: a missing part is a failed
    response (the reason names it), never a partial chain."""

    def _get(**dates):
        resp = safe_get_chain(client, ticker, strike_range="ALL", **dates)
        return resp, resp.status_code

    with _full_chain_parts_lock:
        known_parts = _full_chain_parts.get(ticker, 1)
    if known_parts <= 1:
        resp, code = _get()
        if code == 200:
            return FullChainResponse(200, resp.json(), parts=1)
        if code not in _CHAIN_TOO_BIG_CODES:
            return FullChainResponse(code, reason=f"full chain returned HTTP {code}")
        known_parts = 2

    code, expiries = _option_expiries(client, ticker)
    if code != 200:
        return FullChainResponse(code, reason=f"expiration list returned HTTP {code}")
    if not expiries:
        return FullChainResponse(None, reason="expiration list has no expiry from today")
    size = -(-len(expiries) // min(known_parts, len(expiries)))
    pending = [expiries[i:i + size] for i in range(0, len(expiries), size)]
    merged: "dict | None" = None
    done = 0
    while pending:
        answers = _send_each(lambda p: _get(from_date=p[0], to_date=p[-1]), pending, alone,
                             lambda answer: answer[1] not in (200, *_CHAIN_TOO_BIG_CODES))
        refused = []
        for part, (resp, code) in zip(pending, answers):
            if code == 200:
                payload = resp.json()
                if merged is None:
                    merged = payload
                    merged["callExpDateMap"] = dict(payload.get("callExpDateMap") or {})
                    merged["putExpDateMap"] = dict(payload.get("putExpDateMap") or {})
                else:
                    merged["callExpDateMap"].update(payload.get("callExpDateMap") or {})
                    merged["putExpDateMap"].update(payload.get("putExpDateMap") or {})
                done += 1
            elif code in _CHAIN_TOO_BIG_CODES and len(part) > 1:
                half = len(part) // 2
                refused += [part[:half], part[half:]]
            else:
                return FullChainResponse(code, reason=(f"chain for {part[0]}..{part[-1]} returned HTTP "
                                                       f"{code}; the full chain is incomplete"))
        pending = refused
    with _full_chain_parts_lock:
        _full_chain_parts[ticker] = done
    return FullChainResponse(200, merged, parts=done)


def flatten_chain_contracts(c_json: dict) -> list[dict]:
    """Flatten a Schwab chain response into a flat contract list.

    Single source: this was inline inside _fetch_state and is now shared with the
    terrain loop, so both consume the chain identically. Schwab CSV authority: reads
    chains.callExpDateMap.* / chains.putExpDateMap.* only; no derivation.
    """
    out: list[dict] = []
    if not isinstance(c_json, dict):
        return out
    # the chain sends its interest rate and dividend yield once, at the top; each contract
    # carries them as sent, so a stored contract can be priced on its own
    chain_fields = {k: c_json[k] for k in ("interestRate", "dividendYield") if k in c_json}
    for side_key in ("callExpDateMap", "putExpDateMap"):
        side_map = c_json.get(side_key) or {}
        if not isinstance(side_map, dict):
            continue
        for exp_map in side_map.values():
            if not isinstance(exp_map, dict):
                continue
            for strike_list in exp_map.values():
                if not isinstance(strike_list, list):
                    continue
                for ct in strike_list:
                    if isinstance(ct, dict):
                        out.append({**chain_fields, **ct})
    return out
