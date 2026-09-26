"""
Append rows to calibration_decision_log (Phase 2).

Enable with environment variable ED_CALIBRATION_LOG=1 (or true/yes).
Uses a short-lived SQLite connection to the console DB (same file as db.DB_PATH).
"""

from __future__ import annotations

import os



















def calibration_logging_enabled() -> bool:
    """Env-gated kill switch for the calibration_decision_log writer.

    Returns True only when ``ED_CALIBRATION_LOG`` env var is one of
    {"1", "true", "yes", "on"} (case-insensitive). When False, every call to
    ``append_live_v2_calibration_decision`` silently returns None — the
    calibration_decision_log table gets zero new rows with no log warning.

    **Default is OFF.** Operators must set ``ED_CALIBRATION_LOG=1`` in the
    server environment (typically ``.env``) to enable persistence. Forgetting
    to set this is the root cause of the 2026-04-12 → 2026-05-05 calibration
    gap (24 days of silent zero-row writes); ``server.py`` now logs a WARNING
    at boot when this returns False, so the operator can't restart into a
    silent-skip state without seeing it.
    """
    return os.environ.get("ED_CALIBRATION_LOG", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )




# ───────────────────────── Pass 3 — calibration rate health ─────────────────────────
#
# Forward-only consumer for calibration_decision_log: counts rows added in the
# last 24h vs prior 24h vs expected, surfaced via /api/ops/calibration_rowcount
# (server.py) and the Calibration health card in static/ops.html.
#
# Constants below are NAMED (per Cursor Pass 3 review) so tests pass deterministic
# values and the operator can tune one place without grepping the codebase.









