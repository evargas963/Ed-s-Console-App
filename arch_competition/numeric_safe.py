"""Defensive numeric coercion for arch_competition manifests and gates."""

from __future__ import annotations

import math
from typing import Any


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out
