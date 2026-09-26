"""Fit/apply A1 advisory probability calibration for v2 Pilot 1B.

Scope is intentionally training-time only: post-fusion ``P_entry_success``,
JSON-serializable isotonic artifacts, separate models per horizon, and no
runtime adapter wiring.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any


log = logging.getLogger(__name__)

try:
    from db import configure_sqlite_connection
except ImportError as e:
    log.warning(
        "db.configure_sqlite_connection not available — using no-op stub: %s",
        e,
    )

    def configure_sqlite_connection(conn: sqlite3.Connection, **kwargs: Any) -> None:
        return None


A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES = 500  # O-24
A1_CALIBRATION_PER_REGIME_MIN_SAMPLES = 50  # O-25
# Distinct from volatility_regime classifier vocabulary ("unknown" is a real class).
A1_REGIME_AXIS_MISSING = "__missing__"




















def axis_reliability_bucket_value(raw: Any) -> str:
    if raw is None:
        return A1_REGIME_AXIS_MISSING
    text = str(raw).strip()
    return text if text else A1_REGIME_AXIS_MISSING
























