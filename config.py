# config.py
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

_ROOT = Path(__file__).resolve().parent


#: the host's secrets file (Schwab credentials; never committed)
ENV_FILE = _ROOT / ".env"


def env_file_settings(path: Path = ENV_FILE) -> "dict[str, str]":
    """`path`'s settings, the one reading of .env (none when it does not exist)."""
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def load_dotenv_file(path: Path = ENV_FILE) -> None:
    """Put `path`'s settings into the environment, never over ones already set. Entry points
    call it once, first; library code reads the environment and never loads a file."""
    for k, v in env_file_settings(path).items():
        os.environ.setdefault(k, v)


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
    key = (api_key if api_key is not None else os.getenv("SCHWAB_API_KEY") or "").strip()
    secret = (app_secret if app_secret is not None else os.getenv("SCHWAB_APP_SECRET") or "").strip()
    if not key or not secret or schwab_credential_is_stand_in(key) or schwab_credential_is_stand_in(secret):
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
    # imported here, not at the top: runtime_layout fixes the root when first imported, and an
    # entry point that loads .env (reauth_schwab) must have done so first
    from runtime_layout import RUNTIME_ROOT
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
