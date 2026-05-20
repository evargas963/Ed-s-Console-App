"""Shared JSON parsing and serialization helpers for calibration tools."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from types import SimpleNamespace
from typing import Any

log = logging.getLogger(__name__)


def json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    if is_dataclass(obj):
        try:
            return json_safe(asdict(obj))
        except Exception as e:
            log.debug("calibration json_utils: %s", e, exc_info=True)
    if isinstance(obj, SimpleNamespace):
        return json_safe(vars(obj))
    if hasattr(obj, "__dict__"):
        try:
            return json_safe(vars(obj))
        except Exception as e:
            log.debug("calibration json_utils: %s", e, exc_info=True)
    return str(obj)


def dumps_compact(obj: Any) -> str:
    return json.dumps(json_safe(obj), separators=(",", ":"), ensure_ascii=False)


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
