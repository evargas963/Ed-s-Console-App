"""
eval_metrics_store.py — Persist last full-RTH evaluation metrics for dashboard (What the Data Says).
Written by ml_scheduler after parallel/cascade evaluation; read by prediction_engine / server payload.

Metrics are out-of-sample style: full RTH walk-forward using production inference (not training-set accuracy).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key

log = logging.getLogger(__name__)

def metrics_path() -> Path:
    return Path(__file__).resolve().parent / "models" / "eval_dashboard_metrics.json"


def arch_eval_proof_path() -> Path:
    """Side-by-side parallel vs cascade eval + promotion outcome (written by ml_scheduler)."""
    return Path(__file__).resolve().parent / "models" / "arch_eval_proof.json"


def load_arch_eval_proof() -> dict[str, Any]:
    p = arch_eval_proof_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("arch eval proof load failed: %s", e)
        return {}


def save_arch_eval_proof_merge(ticker: str, entry: dict[str, Any]) -> None:
    """Merge per-ticker proof rows; preserves other tickers."""
    p = arch_eval_proof_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cur = load_arch_eval_proof()
    tickers = cur.get("by_ticker")
    if not isinstance(tickers, dict):
        tickers = {}
    tickers[ticker_storage_key(ticker)] = entry  # RC-345/F25: canonical proof key (WRITE side; readers canonicalize the lookup)
    cur["by_ticker"] = tickers
    cur["updated_at"] = entry.get("updated_at")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


def load_dashboard_eval_metrics() -> dict[str, Any]:
    p = metrics_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("eval metrics load failed: %s", e)
        return {}


def save_dashboard_eval_metrics(payload: dict[str, Any]) -> None:
    p = metrics_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)
