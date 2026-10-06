# config.py
import os
from dataclasses import dataclass
from pathlib import Path

from runtime_layout import RUNTIME_ROOT

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
#: values a test shell gives the Schwab credentials in place of the real ones
_TEST_SHELL_SCHWAB_VALUES = frozenset({"test", "dummy", "fake", "changeme", "placeholder", "ci", "x", "none", "null"})


def schwab_credential_is_stand_in(value: str) -> bool:
    """Whether one Schwab credential is a CI or test shell's stand-in, not a live one: a CI
    placeholder prefix, or a test shell's value."""
    v = value.strip()
    return v.lower() in _TEST_SHELL_SCHWAB_VALUES or any(v.startswith(p) for p in _CI_SCHWAB_PLACEHOLDER_PREFIXES)


def schwab_credentials_are_ci_placeholders(api_key: str | None = None, app_secret: str | None = None) -> bool:
    """True when both Schwab credentials are set and either is a stand-in
    (schwab_credential_is_stand_in)."""
    key = (api_key if api_key is not None else os.getenv("SCHWAB_API_KEY") or "").strip()
    secret = (app_secret if app_secret is not None else os.getenv("SCHWAB_APP_SECRET") or "").strip()
    if not key or not secret:
        return False
    return schwab_credential_is_stand_in(key) or schwab_credential_is_stand_in(secret)


def schwab_live_blocked_for(
    *,
    api_key: str | None = None,
    app_secret: str | None = None,
) -> bool:
    """Block live Schwab when it cannot work: stand-in or absent credentials, or ED_CI_OFFLINE
    with credentials from the environment (explicit non-stand-in arguments, as unit tests pass,
    are not blocked by it). The one fail-closed site, `schwab_client.build_client_from_token`,
    then builds no client: no Schwab call can be made, and the application itself still runs
    (docs/ARCHITECTURE.md "Failure domains")."""
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
    return os.path.abspath(os.path.join(str(RUNTIME_ROOT), "schwab_token.json"))


def build_config() -> AppConfig:
    """The Schwab client's configuration (the capture daemon, reauth). Absent credentials are
    empty here and refused at the one gate, `schwab_live_blocked_for()`: `build_client_from_token`
    builds no client."""
    api_key = (os.getenv("SCHWAB_API_KEY") or "").strip()
    app_secret = (os.getenv("SCHWAB_APP_SECRET") or "").strip()
    callback_url = os.getenv("SCHWAB_CALLBACK_URL", SCHWAB_CALLBACK_URL).strip()

    return AppConfig(
        token_path=token_path(),
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
    )
