# schwab_client.py
"""
Centralized Schwab client construction and safe API wrappers.
Token path is always absolute. InvalidTokenError triggers one retry with client rebuild.
"""
import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from schwab import auth
import logging

log = logging.getLogger(__name__)


# schwab-py raises this when token expired/invalid
try:
    from schwab.auth import InvalidTokenError
except ImportError:
    InvalidTokenError = type("InvalidTokenError", (Exception,), {})

# ── OAuth scope for authorize URL (schwab-py's get_auth_context omits scope by default).
#    Schwab token responses may omit refresh_token without offline_access-style scope.
#    Override via env SCHWAB_OAUTH_SCOPE (space-separated, e.g. "openid profile offline_access").
_DEFAULT_SCHWAB_OAUTH_SCOPE = "openid profile offline_access"


def _schwab_oauth_scope() -> str:
    s = os.getenv("SCHWAB_OAUTH_SCOPE", _DEFAULT_SCHWAB_OAUTH_SCOPE).strip()
    return s if s else _DEFAULT_SCHWAB_OAUTH_SCOPE


def _get_auth_context_with_scope(api_key, callback_url, state=None, base_url=None):
    """Same as schwab.auth.get_auth_context but OAuth2Client includes explicit scope (scope= in authorize URL).

    Mirrors schwab.auth.get_auth_context across schwab-py versions: 1.5.x added the
    ``base_url`` kwarg (the authorize endpoint is derived from it). We accept and honor
    it (defaulting to the library's DEFAULT_BASE_URL when not supplied by an older
    caller) so this override stays signature-compatible — the only behavioral delta vs
    the upstream function is the explicit ``scope=`` on the OAuth2Client.
    """
    from authlib.integrations.httpx_client import OAuth2Client

    if base_url is None:
        base_url = getattr(auth, "DEFAULT_BASE_URL", "https://api.schwabapi.com")
    endpoint = (
        auth._auth_endpoint(base_url)
        if hasattr(auth, "_auth_endpoint")
        else base_url.rstrip("/") + "/v1/oauth/authorize"
    )
    scope = _schwab_oauth_scope()
    oauth = OAuth2Client(api_key, redirect_uri=callback_url, scope=scope)
    authorization_url, new_state = oauth.create_authorization_url(endpoint, state=state)
    print(f"[schwab_client DEBUG] OAuth authorization_url (scope={scope!r}):\n{authorization_url}")
    return auth.AuthContext(callback_url, authorization_url, new_state)


auth.get_auth_context = _get_auth_context_with_scope


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


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_diag(diagnostics_dir: str, prefix: str, ticker: str, payload: dict) -> str:
    ensure_dir(diagnostics_dir)
    fn = f"{prefix}_{ticker}_{_utc_ts()}.json"
    fp = os.path.join(diagnostics_dir, fn)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return fp


def _resolve_token_path(token_path: str) -> str:
    """Ensure token path is absolute. Idempotent if already absolute."""
    return os.path.abspath(os.path.expanduser(token_path))


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
    tok = data.get("token")
    if isinstance(tok, dict):
        out.has_token_object = True
        at = tok.get("access_token")
        out.has_access_token = isinstance(at, str) and len(at.strip()) > 0
        rt = tok.get("refresh_token")
        out.has_refresh_token = isinstance(rt, str) and len(rt.strip()) > 0
        out.has_expires_at = "expires_at" in tok
        sc = tok.get("scope")
        if isinstance(sc, str) and sc.strip():
            out.scope_value = sc.strip()
        elif sc is not None:
            out.scope_value = str(sc)

        now = int(time.time())
        exp = tok.get("expires_at")
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
    from config import is_schwab_ci_offline_mode

    if is_schwab_ci_offline_mode():
        return SchwabClientState(
            ok=False,
            message=(
                "Schwab CI offline mode (ED_CI_OFFLINE or ci-placeholder credentials) — "
                "live client construction blocked; no Schwab API calls."
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
        c = auth.client_from_token_file(
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
                enforce_enums=False,
                interactive=False,
                callback_timeout=float(os.environ.get("SCHWAB_OAUTH_CALLBACK_TIMEOUT_SEC", "900")),
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
    state = (qs.get("state") or [None])[0]
    if not (qs.get("code") or [None])[0]:
        return False, "Redirect URL missing OAuth code query parameter."

    resolved = _resolve_token_path(token_path)
    auth_context = _get_auth_context_with_scope(api_key, callback_url, state=state)
    token_write_func = auth.__make_update_token_func(resolved)
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
_SCHWAB_AUTH_FAILURE_LATCH_SEC = float(os.environ.get("ED_SCHWAB_AUTH_FAILURE_LATCH_SEC", "300"))


def _is_token_error(exc: BaseException) -> bool:
    """True if exception indicates token expired/invalid."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if "InvalidTokenError" in name or name == "InvalidTokenError":
        return True
    if "invalid_grant" in msg or "unsupported_token_type" in msg:
        return True
    if "refresh token" in msg and ("invalid" in msg or "revoked" in msg or "expired" in msg):
        return True
    if "token" in msg and ("invalid" in msg or "expired" in msg or "401" in msg or "revoked" in msg):
        return True
    if "401" in msg or "unauthorized" in msg:
        return True
    return False


def _raise_schwab_auth_error(exc: BaseException) -> None:
    global _schwab_auth_failure_until_mono
    _schwab_auth_failure_until_mono = time.monotonic() + _SCHWAB_AUTH_FAILURE_LATCH_SEC
    raise SchwabAuthError(str(exc)) from exc


def _schwab_auth_latched() -> bool:
    return time.monotonic() < _schwab_auth_failure_until_mono


def _block_live_schwab_in_ci_offline() -> None:
    from config import is_schwab_ci_offline_mode

    if is_schwab_ci_offline_mode():
        raise RuntimeError(
            "Schwab CI offline mode — live API call blocked (ED_CI_OFFLINE or ci-placeholder credentials)"
        )


def safe_get_quote(client, ticker: str, *, refresh_client_fn=None, attempt_hook=None):
    """
    Fetch quote. On InvalidTokenError: if refresh_client_fn provided, rebuild client
    and retry once. Returns response or raises. refresh_client_fn() returns new client.

    attempt_hook: optional callable invoked immediately before each get_quote attempt
    (primary and token-refresh retry) for timing / observability.
    """
    _block_live_schwab_in_ci_offline()
    if attempt_hook is not None:
        try:
            attempt_hook()
        except Exception as e:
            log.debug("quote attempt_hook: %s", e, exc_info=True)
    try:
        resp = client.get_quote(ticker)
        try:
            from api_pressure import record_schwab_http_response

            record_schwab_http_response(resp, f"quote:{ticker}")
        except ImportError:
            pass
        return resp
    except Exception as e:
        if refresh_client_fn is not None and _is_token_error(e):
            try:
                new_client = refresh_client_fn()
                if new_client:
                    if attempt_hook is not None:
                        try:
                            attempt_hook()
                        except Exception as e:
                            log.debug("quote attempt_hook: %s", e, exc_info=True)
                    resp = new_client.get_quote(ticker)
                    try:
                        from api_pressure import record_schwab_http_response

                        record_schwab_http_response(resp, f"quote:{ticker}")
                    except ImportError:
                        pass
                    return resp
            except Exception as retry_e:
                raise retry_e
        raise

def safe_get_price_history(client, ticker: str, *, frequency_minutes: int = 5, period_days: int = 1):
    """Fetch intraday price history from Schwab. Returns response or None."""
    _block_live_schwab_in_ci_offline()
    try:
        import schwab as _schwab
        PH = _schwab.client.Client.PriceHistory
        freq = {
            1: PH.Frequency.EVERY_MINUTE,
            5: PH.Frequency.EVERY_FIVE_MINUTES,
            10: PH.Frequency.EVERY_TEN_MINUTES,
            15: PH.Frequency.EVERY_FIFTEEN_MINUTES,
            30: PH.Frequency.EVERY_THIRTY_MINUTES,
        }.get(frequency_minutes, PH.Frequency.EVERY_FIVE_MINUTES)
        period = {
            1: PH.Period.ONE_DAY,
            2: PH.Period.TWO_DAYS,
            3: PH.Period.THREE_DAYS,
            5: PH.Period.FIVE_DAYS,
            10: PH.Period.TEN_DAYS,
        }.get(period_days, PH.Period.ONE_DAY)
        return client.get_price_history(
            ticker,
            period_type=PH.PeriodType.DAY,
            period=period,
            frequency_type=PH.FrequencyType.MINUTE,
            frequency=freq,
            need_extended_hours_data=False,
        )
    except Exception as e_enum:
        # STACK-VERIFY-CAND-SILENT-FALLBACK-SWEEP: legacy raw-kwargs fallback for
        # older schwab-py versions; emit diagnostic so silent fallback to None on
        # the second branch is visible to the operator instead of a black-box drop.
        log.debug("safe_get_price_history: enum-API path failed (%s); trying raw kwargs", e_enum)
        try:
            return client.get_price_history(
                ticker,
                periodType="day",
                period=period_days,
                frequencyType="minute",
                frequency=frequency_minutes,
                needExtendedHoursData=False,
            )
        except Exception as e_raw:
            log.warning(
                "safe_get_price_history: both enum + raw kwargs failed for ticker=%s freq=%s days=%s "
                "(enum_err=%r raw_err=%r); returning None",
                ticker, frequency_minutes, period_days, e_enum, e_raw,
            )
            return None

def safe_get_chain(client, ticker: str, *, strike_count: int = 20, from_date=None, to_date=None):
    # schwab-py supports optional args; we keep them optional to reduce breakage.
    _block_live_schwab_in_ci_offline()
    if _schwab_auth_latched():
        raise SchwabAuthError(
            "Schwab auth latched after prior token failure — option chain withheld"
        )
    kwargs = {"strike_count": strike_count, "include_underlying_quote": True}
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
    try:
        from api_pressure import record_schwab_http_response

        record_schwab_http_response(resp, f"option_chain:{ticker}")
    except ImportError:
        pass
    return resp
