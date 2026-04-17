# config.py
import os
from dataclasses import dataclass

# =========================================================
# TICKER DEFAULT — used by API/CLI when no ticker specified
# Change here to update all endpoints (state, stream, expiries, price-levels, etc.)
# =========================================================
DEFAULT_TICKER = "SPY"

# =========================================================
# 🔐 SCHWAB API CREDENTIALS (KEEP IN SCRIPT AS REQUESTED)
# =========================================================
SCHWAB_API_KEY = "A8y3Yf4jkAbJfavtb76VNbYimkSEk082"
SCHWAB_APP_SECRET = "KdGkl1VGTOw9quy5"

# Schwab Dev Portal requires HTTPS callback URL
SCHWAB_CALLBACK_URL = "https://127.0.0.1:8182"


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

    # Env vars (optional override), but we still default to hardcoded values above
    api_key = os.getenv("SCHWAB_API_KEY", SCHWAB_API_KEY)
    app_secret = os.getenv("SCHWAB_APP_SECRET", SCHWAB_APP_SECRET)
    callback_url = os.getenv("SCHWAB_CALLBACK_URL", SCHWAB_CALLBACK_URL)

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
