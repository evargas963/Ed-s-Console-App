"""JSON-serialize arbitrary model objects for calibration storage."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from types import SimpleNamespace
from typing import Any


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
        except Exception:
            pass
    if isinstance(obj, SimpleNamespace):
        return json_safe(vars(obj))
    if hasattr(obj, "__dict__"):
        try:
            return json_safe(vars(obj))
        except Exception:
            pass
    return str(obj)


def dumps_compact(obj: Any) -> str:
    return json.dumps(json_safe(obj), separators=(",", ":"), ensure_ascii=False)
