# config.py
import os
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def _load_dotenv_if_present() -> None:
    """Load repo-root ``.env`` when present (host secrets; never committed)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = _ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _ensure_dotenv_loaded() -> None:
    _load_dotenv_if_present()


# =========================================================
# TICKER DEFAULT — used by API/CLI when no ticker specified
# Change here to update all endpoints (state, stream, expiries, price-levels, etc.)
# =========================================================
DEFAULT_TICKER = "SPY"

# Schwab Dev Portal requires HTTPS callback URL (non-secret default).
SCHWAB_CALLBACK_URL = "https://127.0.0.1:8182"


_CI_SCHWAB_PLACEHOLDER_PREFIXES: tuple[str, ...] = (
    "ci-not-live-placeholder",
    "ci-placeholder-",
)


def schwab_credentials_are_ci_placeholders(api_key: str | None = None, app_secret: str | None = None) -> bool:
    """True when Schwab env vars are non-production CI placeholders (not live credentials)."""
    key = (api_key if api_key is not None else os.getenv("SCHWAB_API_KEY") or "").strip()
    secret = (app_secret if app_secret is not None else os.getenv("SCHWAB_APP_SECRET") or "").strip()
    if not key or not secret:
        return False
    return any(key.startswith(p) for p in _CI_SCHWAB_PLACEHOLDER_PREFIXES) and any(
        secret.startswith(p) for p in _CI_SCHWAB_PLACEHOLDER_PREFIXES
    )


def is_schwab_ci_offline_mode() -> bool:
    """Explicit CI/test offline — blocks live Schwab client construction and API calls."""
    return schwab_live_blocked_for()


def schwab_live_blocked_for(
    *,
    api_key: str | None = None,
    app_secret: str | None = None,
) -> bool:
    """Block live Schwab when it cannot work: placeholder OR ABSENT credentials.

    ED_CI_OFFLINE with explicit non-placeholder credentials (unit tests) does not block.

    RC-514: absent credentials block too, and did not before. That was the hole under the
    failure-domain architecture (docs/ARCHITECTURE.md §4).
    `schwab_credentials_are_ci_placeholders` returns False for an empty value, so with NO
    credentials this returned False: `build_client_from_token` built a client and
    `_block_live_schwab_in_ci_offline` waved calls through, and the capability presented itself
    as live while failing one unauthenticated request at a time. The launcher compensated by
    refusing to start the WHOLE application — the wrong boundary, and the reason a credential
    fault took the desk down on 2026-09-03.

    Blocking here is what lets the launcher stop doing that: the two existing fail-closed sites
    in `schwab_client` then report the capability unavailable instead of pretending. No new
    mechanism — the same gate, asked the question it should always have answered.
    """
    if schwab_credentials_are_ci_placeholders(api_key, app_secret):
        return True
    key = (api_key if api_key is not None else os.getenv("SCHWAB_API_KEY") or "").strip()
    secret = (app_secret if app_secret is not None else os.getenv("SCHWAB_APP_SECRET") or "").strip()
    if not key or not secret:
        return True
    offline = os.getenv("ED_CI_OFFLINE", "").strip().lower() in ("1", "true", "yes")
    if not offline:
        return False
    return api_key is None and app_secret is None


@dataclass(frozen=True)
class AppConfig:
    app_dir: str
    token_path: str  # Always absolute when built via build_config
    diagnostics_dir: str
    api_key: str
    app_secret: str
    callback_url: str

    # Barchart data directories (relative to app_dir)
    barchart_dir: str
    barchart_raw_dir: str
    barchart_processed_dir: str
    barchart_output_dir: str
    barchart_archive_dir: str


def build_config(app_dir: str) -> AppConfig:
    """Build config. token_path is always absolute regardless of launch context."""
    _ensure_dotenv_loaded()
    # Env override for launch-method debugging / explicit path
    env_token = os.getenv("SCHWAB_TOKEN_PATH")
    if env_token:
        token_path = os.path.abspath(env_token)
    else:
        token_path = os.path.abspath(os.path.join(app_dir, "schwab_token.json"))
    diagnostics_dir = os.path.join(app_dir, "diagnostics")

    # Barchart directories (canonical)
    barchart_dir = os.path.join(app_dir, "data", "barchart")
    barchart_raw_dir = os.path.join(barchart_dir, "raw")
    barchart_processed_dir = os.path.join(barchart_dir, "processed")
    barchart_output_dir = os.path.join(barchart_dir, "output")
    barchart_archive_dir = os.path.join(barchart_dir, "archive")

    # RC-514: Schwab credentials are a CAPABILITY input, not an application-shell requirement.
    # These two lines used to call a `_require_env` helper that RAISED when either was absent,
    # and `server.py` calls `build_config` at module scope — so `import server`, and therefore
    # `uvicorn server:app`, failed outright with no credentials. The entire application refused
    # to exist because one vendor's secrets were missing, which is the boundary
    # docs/ARCHITECTURE.md §4 rejects: Schwab unavailable degrades the Schwab capability.
    #
    # This is not a relaxation. That raise was a SECOND place deciding "can we do Schwab",
    # duplicating `schwab_live_blocked_for()` — which now blocks on absent credentials, so an
    # empty value here cannot reach a live call: `build_client_from_token` returns ok=False and
    # `_block_live_schwab_in_ci_offline` raises. One gate decides, and it still fails closed.
    api_key = (os.getenv("SCHWAB_API_KEY") or "").strip()
    app_secret = (os.getenv("SCHWAB_APP_SECRET") or "").strip()
    callback_url = os.getenv("SCHWAB_CALLBACK_URL", SCHWAB_CALLBACK_URL).strip()

    return AppConfig(
        app_dir=app_dir,
        token_path=token_path,
        diagnostics_dir=diagnostics_dir,
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
        barchart_dir=barchart_dir,
        barchart_raw_dir=barchart_raw_dir,
        barchart_processed_dir=barchart_processed_dir,
        barchart_output_dir=barchart_output_dir,
        barchart_archive_dir=barchart_archive_dir,
    )
