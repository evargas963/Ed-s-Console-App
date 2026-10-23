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
    token_path: str  # absolute (token_path())
    api_key: str
    app_secret: str
    callback_url: str


def token_path() -> str:
    """The Schwab token file, absolute: SCHWAB_TOKEN_PATH, else schwab_token.json under the
    runtime root (this checkout unless ED_RUNTIME_ROOT moves it). The console reads only this
    (the token's age); it holds no Schwab credential."""
    env_token = os.getenv("SCHWAB_TOKEN_PATH")
    if env_token:
        return os.path.abspath(env_token)
    from runtime_layout import RUNTIME_ROOT
    return os.path.abspath(os.path.join(str(RUNTIME_ROOT), "schwab_token.json"))


def build_config() -> AppConfig:
    """The Schwab client's configuration (the capture daemon, reauth): its credentials from the
    environment, empty when absent and then refused at the one gate, `schwab_live_blocked_for()`."""
    api_key = (os.getenv("SCHWAB_API_KEY") or "").strip()
    app_secret = (os.getenv("SCHWAB_APP_SECRET") or "").strip()
    callback_url = os.getenv("SCHWAB_CALLBACK_URL", SCHWAB_CALLBACK_URL).strip()

    return AppConfig(
        token_path=token_path(),
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
    )
