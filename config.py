# config.py
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from runtime_layout import RUNTIME_ROOT

_ROOT = Path(__file__).resolve().parent


#: the host's secrets file (Schwab credentials; never committed)
ENV_FILE = _ROOT / ".env"


def load_dotenv_file(path: Path = ENV_FILE) -> None:
    """Put `path`'s variables into the environment, never over ones already set. Entry points
    call it once, first; library code reads the environment and never loads a file.
    """
    if path.is_file():
        load_dotenv(path, override=False)


# No default ticker: every endpoint and CLI requires the ticker it acts on.

# Schwab Dev Portal requires HTTPS callback URL (non-secret default).
SCHWAB_CALLBACK_URL = "https://127.0.0.1:8182"


_CI_SCHWAB_PLACEHOLDER_PREFIXES: tuple[str, ...] = (
    "ci-not-live-placeholder",
    "ci-placeholder-",
)


def schwab_live_blocked_for(api_key: str | None, app_secret: str | None) -> bool:
    """True when live Schwab cannot work: a credential missing, empty, or a CI placeholder.

    The one gate (docs/ARCHITECTURE.md "Failure domains"): `schwab_client.build_client_from_token`
    builds no client on it, so no Schwab call is made and the rest of the application starts.
    """
    if not api_key or not app_secret:
        return True
    return any(api_key.startswith(p) for p in _CI_SCHWAB_PLACEHOLDER_PREFIXES) and any(
        app_secret.startswith(p) for p in _CI_SCHWAB_PLACEHOLDER_PREFIXES
    )


@dataclass(frozen=True)
class AppConfig:
    token_path: str  # absolute (token_path())
    api_key: str | None  # None when not set, or in offline mode
    app_secret: str | None
    callback_url: str


def token_path() -> str:
    """The Schwab token file, absolute: SCHWAB_TOKEN_PATH, else schwab_token.json under the
    runtime root (this checkout, or the primary checkout for a linked worktree, unless
    ED_RUNTIME_ROOT moves it). The console reads only this
    (the token's age); it holds no Schwab credential.
    """
    env_token = os.getenv("SCHWAB_TOKEN_PATH")
    if env_token:
        return os.path.abspath(env_token)
    return os.path.abspath(os.path.join(str(RUNTIME_ROOT), "schwab_token.json"))


def build_config() -> AppConfig:
    """The Schwab client's configuration (the capture daemon, reauth), the one reader of its
    credentials: each as the environment holds it, None when not set. Offline (ED_CI_OFFLINE,
    tests and CI) takes none, so the one gate, `schwab_live_blocked_for`, refuses live Schwab.
    """
    offline = os.environ.get("ED_CI_OFFLINE") in ("1", "true", "yes")
    return AppConfig(
        token_path=token_path(),
        api_key=None if offline else os.environ.get("SCHWAB_API_KEY"),
        app_secret=None if offline else os.environ.get("SCHWAB_APP_SECRET"),
        callback_url=os.getenv("SCHWAB_CALLBACK_URL", SCHWAB_CALLBACK_URL).strip(),
    )
