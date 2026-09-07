"""Canonical app-side ticker readiness lookup helpers."""
from __future__ import annotations

import json
from pathlib import Path

from runtime_layout import data_dir as _runtime_data_dir  # RC-523: runtime data root

READINESS_LOOKUP_PATH = _runtime_data_dir() / "ticker_readiness_lookup_v1.json"


def load_ticker_readiness_lookup(path: Path | None = None) -> dict:
    p = path or READINESS_LOOKUP_PATH
    if not p.is_file():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload.get("lookup", {}) if isinstance(payload, dict) else {}


def get_ticker_readiness(ticker: str, path: Path | None = None) -> dict | None:
    t = str(ticker or "").upper().strip()
    if not t:
        return None
    return load_ticker_readiness_lookup(path).get(t)
