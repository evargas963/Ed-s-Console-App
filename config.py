# config.py
import os
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


#: the host's secrets file (Schwab credentials; never committed)
ENV_FILE = _ROOT / ".env"


def load_dotenv_file(path: Path = ENV_FILE) -> None:
    """Put `path`'s variables into the environment, never over ones already set. Entry points
    call it once, first; library code reads the environment and never loads a file."""
    from dotenv import load_dotenv

    if path.is_file():
        load_dotenv(path, override=False)


# No default ticker (universality, operator 2026-09-23): every endpoint and CLI requires the
# ticker it acts on -- a missing one used to silently become SPY.

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




def schwab_live_blocked_for(
    *,
    api_key: str | None = None,
    app_secret: str | None = None,
) -> bool:
    """Block live Schwab when it cannot work: placeholder OR ABSENT credentials.

    ED_CI_OFFLINE with explicit non-placeholder credentials (unit tests) does not block.

    RC-514: absent credentials block too, and did not before. That was the hole under the
    failure-domain architecture (docs/ARCHITECTURE.md "Failure domains").
    `schwab_credentials_are_ci_placeholders` returns False for an empty value, so with NO
    credentials this returned False: `build_client_from_token` built a client, and the
    capability presented itself as live while failing one unauthenticated request at a time.
    The launcher compensated by refusing to start the WHOLE application — the wrong boundary.

    Blocking here is what lets the launcher stop doing that: the one fail-closed site,
    `schwab_client.build_client_from_token`, then builds no client and reports the capability
    unavailable instead of pretending; with no client, no Schwab call can be made.
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
    token_path: str  # Always absolute when built via build_config
    api_key: str
    app_secret: str
    callback_url: str


def build_config() -> AppConfig:
    """Build config. token_path is always absolute regardless of launch context."""
    # Env override for launch-method debugging / explicit path
    env_token = os.getenv("SCHWAB_TOKEN_PATH")
    if env_token:
        token_path = os.path.abspath(env_token)
    else:
        # RC-523: the token is RUNTIME state — under the runtime root (this checkout unless
        # ED_RUNTIME_ROOT moves it), never a source-tree fixture.
        from runtime_layout import RUNTIME_ROOT
        token_path = os.path.abspath(os.path.join(str(RUNTIME_ROOT), "schwab_token.json"))

    # RC-514: Schwab credentials are a CAPABILITY input, not an application-shell requirement.
    # These two lines used to call a `_require_env` helper that RAISED when either was absent,
    # and `server.py` calls `build_config` at module scope — so `import server`, and therefore
    # `uvicorn server:app`, failed outright with no credentials. The entire application refused
    # to exist because one vendor's secrets were missing, which is the boundary
    # docs/ARCHITECTURE.md "Failure domains" rejects: Schwab unavailable degrades the Schwab capability.
    #
    # This is not a relaxation. That raise was a SECOND place deciding "can we do Schwab",
    # duplicating `schwab_live_blocked_for()` — which now blocks on absent credentials, so an
    # empty value here cannot reach a live call: `build_client_from_token` returns ok=False and
    # builds no client. One gate decides, and it still fails closed.
    api_key = (os.getenv("SCHWAB_API_KEY") or "").strip()
    app_secret = (os.getenv("SCHWAB_APP_SECRET") or "").strip()
    callback_url = os.getenv("SCHWAB_CALLBACK_URL", SCHWAB_CALLBACK_URL).strip()

    return AppConfig(
        token_path=token_path,
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
    )
