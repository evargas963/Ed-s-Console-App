"""Post-promote live console model registry reload (PR4 P3-10)."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from arch_competition.scheduler_auto_promote_policy import (
    console_reload_token,
    resolve_console_reload_url,
)

log = logging.getLogger(__name__)

RELOAD_SCHEMA_VERSION = "reload_models_v1"


def build_live_reload_report(
    *,
    reloads: list[dict[str, str]],
    url: str | None = None,
) -> dict[str, Any]:
    """POST batch reload to console; return training_report live_reload block."""
    effective_url = (url if url is not None else resolve_console_reload_url()).strip()
    if not effective_url:
        return {"called": False, "reason": "ED_CONSOLE_RELOAD_URL=<empty>"}
    if not reloads:
        return {"called": False, "reason": "no reload tuples accumulated", "url": effective_url}

    body = json.dumps({"reloads": reloads}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    tok = console_reload_token()
    if tok:
        headers["X-Reload-Token"] = tok

    req = urllib.request.Request(effective_url, data=body, headers=headers, method="POST")
    report: dict[str, Any] = {
        "called": True,
        "url": effective_url,
        "results": [],
    }
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            http_status = resp.getcode()
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        http_status = e.code
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        report["results"] = [
            {
                "ticker": r.get("ticker"),
                "horizon": r.get("horizon"),
                "succeeded": False,
                "http_status": http_status,
                "error": str(e),
            }
            for r in reloads
        ]
        report["live_reload_partial_failure"] = True
        return report
    except urllib.error.URLError as e:
        report["results"] = [
            {
                "ticker": r.get("ticker"),
                "horizon": r.get("horizon"),
                "succeeded": False,
                "error": str(e.reason if hasattr(e, "reason") else e),
            }
            for r in reloads
        ]
        report["live_reload_partial_failure"] = True
        return report

    results = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(results, list):
        for item in results:
            row = dict(item) if isinstance(item, dict) else {"succeeded": False, "error": "invalid result row"}
            row.setdefault("http_status", http_status)
            report["results"].append(row)
    else:
        report["results"] = [
            {
                "ticker": r.get("ticker"),
                "horizon": r.get("horizon"),
                "succeeded": http_status == 200,
                "http_status": http_status,
            }
            for r in reloads
        ]

    partial = bool(payload.get("partial_failure")) if isinstance(payload, dict) else False
    if not partial:
        partial = any(not r.get("succeeded") for r in report["results"])
    if partial:
        report["live_reload_partial_failure"] = True
    return report
