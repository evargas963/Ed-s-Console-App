"""Phase 3 scheduler auto-promote environment policy (PR4)."""
from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_truthy(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in _TRUTHY


def _env_falsy_default_true(name: str, default: str = "1") -> bool:
    raw = os.environ.get(name, default).strip().lower()
    return raw not in ("0", "false", "no", "off")


def scheduler_auto_promote_panic_disabled() -> bool:
    return _env_truthy("ED_DISABLE_AUTO_PROMOTE")


def scheduler_auto_promote_to_active_enabled() -> bool:
    """Train-success-live: default ON — successful scheduler train writes models/active/."""
    if scheduler_auto_promote_panic_disabled():
        return False
    return _env_falsy_default_true("ED_SCHEDULER_AUTO_PROMOTE", "1")


def scheduler_auto_promote_core_only() -> bool:
    return _env_truthy("ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY")


def scheduler_auto_promote_require_verify() -> bool:
    return _env_falsy_default_true("ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY", "1")


def scheduler_auto_promote_strict_core_freshness() -> bool:
    return _env_truthy("ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS")


def scheduler_nightly_all_horizons_enabled() -> bool:
    """Phase 2 stack honesty: nightly background + default train path covers all four primaries."""
    return _env_falsy_default_true("ED_ML_SCHEDULER_ALL_HORIZONS", "1")


def resolve_console_reload_url() -> str:
    explicit = os.environ.get("ED_CONSOLE_RELOAD_URL")
    if explicit is not None:
        return explicit.strip()
    port = os.environ.get("ED_CONSOLE_PORT", "8000").strip() or "8000"
    return f"http://127.0.0.1:{port}/api/internal/reload_models"


def console_reload_token() -> str | None:
    tok = os.environ.get("ED_CONSOLE_RELOAD_TOKEN", "").strip()
    return tok or None


def ticker_eligible_for_auto_promote(ticker: str) -> bool:
    from scheduler_user_tickers import is_training_anchor_ticker

    if scheduler_auto_promote_core_only():
        return is_training_anchor_ticker(ticker)
    return True
