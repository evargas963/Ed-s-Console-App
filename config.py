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


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if val is None or not str(val).strip():
        raise RuntimeError(
            f"Missing required environment variable {name!r} — "
            "set SCHWAB_API_KEY and SCHWAB_APP_SECRET before starting the server."
        )
    return str(val).strip()


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

    api_key = _require_env("SCHWAB_API_KEY")
    app_secret = _require_env("SCHWAB_APP_SECRET")
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
