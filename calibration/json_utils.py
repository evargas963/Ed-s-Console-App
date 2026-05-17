"""Shared JSON parsing helpers for calibration tools."""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def parse_json_mapping(value: Any, *, context: str) -> dict[str, Any]:
    """Parse JSON text to dict; log warning and return {} on failure."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        log.warning("%s unparseable, treating as empty: %s", context, e)
        return {}
    return parsed if isinstance(parsed, dict) else {}
