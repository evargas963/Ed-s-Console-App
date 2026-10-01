# schwab_client.py
"""
Centralized Schwab client construction and safe API wrappers.
Token path is always absolute.
"""
import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import urlparse

from authlib.common.errors import AuthlibBaseError
from schwab import auth

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
    return update_token


def _token_read_func(resolved: str):
    def load_token():
        with open(resolved, "rb") as f:
            return json.load(f)
    return load_token


def client_from_token_file_atomic(token_path: str, api_key: str, app_secret: str, *,
                                  enforce_enums: bool = False):
    """schwab-py client from the token file, with ATOMIC token refresh writes. Use this, never
    auth.client_from_token_file (its writer rewrites the file in place)."""
    resolved = _resolve_token_path(token_path)
    return auth.client_from_access_functions(
        api_key, app_secret, _token_read_func(resolved), _token_update_func(resolved),
        enforce_enums=enforce_enums)


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


_schwab_auth_failure_until_mono: float = 0.0
_SCHWAB_AUTH_FAILURE_LATCH_SEC = float(os.environ.get("ED_SCHWAB_AUTH_FAILURE_LATCH_SEC", "300"))  # caps-ok: OAuth/config timeout only


def _is_token_error(exc: BaseException) -> bool:
    """True for an OAuth failure: every error authlib raises (expired / missing / revoked token,
    refresh rejected with invalid_grant) derives from AuthlibBaseError."""
    return isinstance(exc, AuthlibBaseError)


def _raise_schwab_auth_error(exc: BaseException) -> None:
    global _schwab_auth_failure_until_mono
    _schwab_auth_failure_until_mono = time.monotonic() + _SCHWAB_AUTH_FAILURE_LATCH_SEC
    raise SchwabAuthError(str(exc)) from exc


def _schwab_auth_latched() -> bool:
    return time.monotonic() < _schwab_auth_failure_until_mono


def _block_live_schwab_in_ci_offline() -> None:
    from config import schwab_live_blocked_for

    if schwab_live_blocked_for():
        raise RuntimeError(
            "Schwab capability UNAVAILABLE — live API call blocked (missing credentials, "
            "ci-placeholder credentials, or ED_CI_OFFLINE). No fabricated or stale substitute."
        )


def safe_get_chain(client, ticker: str, *, strike_range: str | None = None, from_date=None,
                   to_date=None):
    # `strike_range` is schwab-py's Options.StrikeRange ("ALL": every strike). A strike count
    # (N strikes around the money) is never requested: it truncates the chain.
    _block_live_schwab_in_ci_offline()
    if _schwab_auth_latched():
        raise SchwabAuthError(
            "Schwab auth latched after prior token failure — option chain withheld"
        )
    kwargs = {"include_underlying_quote": True}
    if strike_range is not None:
        kwargs["strike_range"] = strike_range
    if from_date is not None:
        kwargs["from_date"] = from_date
    if to_date is not None:
        kwargs["to_date"] = to_date
    try:
        resp = client.get_option_chain(ticker, **kwargs)
    except Exception as e:
        if _is_token_error(e):
            _raise_schwab_auth_error(e)
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


def _option_expiries(client, ticker: str) -> "list[date] | None":
    """Every listed expiry for `ticker` that has not passed (ET date), ascending; None when the
    vendor does not answer 200. MEASURED 2026-09-26 (Saturday): the expiration chain still lists
    Friday's expired 2026-09-25, and a chain request whose fromDate is in the past is refused
    with HTTP 400 ("Check Param Values") -- the same range from today answers 200."""
    resp = client.get_option_expiration_chain(ticker)
    if resp is None or resp.status_code != 200:
        return None
    today = now_et().date()
    return sorted({d for d in (date.fromisoformat(str(e["expirationDate"])[:10])
                               for e in (resp.json().get("expirationList") or []) if e.get("expirationDate"))  # external-key-ok: Schwab expiration chain response
                   if d >= today})


def fetch_full_chain(client, ticker: str, get, *,
                     expiry: "date | None" = None) -> FullChainResponse:
    """EVERY strike of every listed expiry (or of the one `expiry`) -- the chain all level
    math is computed from. `get(**dates)` makes one strike_range=ALL request for `ticker`
    and returns Schwab's response (the console passes its gated request, the daemon a plain
    one).

    MEASURED 2026-09-25 across the 42 board tickers: levels computed from the old strike
    window disagreed with the same code run on the full chain -- gamma flip missing for 10
    tickers, max pain different for 16, put wall for 4, $SPX walls 3-4% apart. Operator
    decision 2026-09-25: the full chain for all calculations.

    One request when Schwab answers it. When the vendor answers that the request covers too
    much, the listed expiries are split into contiguous date ranges, halving any range that
    is itself refused; the part count that worked is remembered per ticker. Every part must
    land: a missing part is a failed response (the reason names it), never a partial chain."""

    def _get(**dates):
        resp = get(**dates)
        return resp, resp.status_code

    if expiry is not None:
        resp, code = _get(from_date=expiry, to_date=expiry)
        if code != 200:
            return FullChainResponse(code, reason=f"chain for {expiry} returned HTTP {code}")
        return FullChainResponse(200, resp.json(), parts=1)

    with _full_chain_parts_lock:
        known_parts = _full_chain_parts.get(ticker, 1)
    if known_parts <= 1:
        resp, code = _get()
        if code == 200:
            return FullChainResponse(200, resp.json(), parts=1)
        if code not in _CHAIN_TOO_BIG_CODES:
            return FullChainResponse(code, reason=f"full chain returned HTTP {code}")
        known_parts = 2

    expiries = _option_expiries(client, ticker)
    if not expiries:
        return FullChainResponse(None, reason="expiration list unavailable")
    size = -(-len(expiries) // min(known_parts, len(expiries)))
    pending = [expiries[i:i + size] for i in range(0, len(expiries), size)]
    merged: "dict | None" = None
    done = 0
    while pending:
        part = pending.pop(0)
        resp, code = _get(from_date=part[0], to_date=part[-1])
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
            continue
        if code in _CHAIN_TOO_BIG_CODES and len(part) > 1:
            half = len(part) // 2
            pending[:0] = [part[:half], part[half:]]
            continue
        return FullChainResponse(code, reason=(f"chain for {part[0]}..{part[-1]} returned HTTP "
                                               f"{code}; the full chain is incomplete"))
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
