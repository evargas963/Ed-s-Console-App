#!/usr/bin/env python3
"""
Fetch /api/state for two tickers and print a compact SPY vs QQQ (or any pair) comparison
for model stack proxies, predictive horizons, multi-horizon / THE CALL fields.

Usage (console running with ED auth OK):
  set ED_LIVE_DIAG=1
  python tools/live_diag_compare.py SPY QQQ

Uses ``ticker=`` on ``/api/state`` (``symbol=`` is also accepted as an alias on the server).

Env:
  ED_DIAG_BASE   — default http://127.0.0.1:8000
  ED_DIAG_EXPIRY — optional YYYY-MM-DD (enables server cache path for that expiry)
  ED_DIAG_TOKEN  — optional Authorization Bearer token if your server requires it
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Optional


def _get(url: str, token: Optional[str]) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _hz_probs(d: dict, hz: str) -> dict[str, Any]:
    u, dn, f = (d.get(f"up_prob_{hz}"), d.get(f"down_prob_{hz}"), d.get(f"flat_prob_{hz}"))
    return {"up": u, "down": dn, "flat": f, "any_none": u is None or dn is None or f is None}


def _print_block(title: str, a: dict, b: dict, tick_a: str, tick_b: str) -> None:
    print(f"\n=== {title} ===")
    print(f"{'field':<40} {tick_a:<18} {tick_b:<18}")
    print("-" * 78)
    keys = sorted(set(a.keys()) | set(b.keys()))
    for k in keys:
        va, vb = a.get(k), b.get(k)
        sa = json.dumps(va, default=str)[:70] if va is not None else "—"
        sb = json.dumps(vb, default=str)[:70] if vb is not None else "—"
        if sa != sb or k in ("final_bias", "call_signal", "fusion_available"):
            mark = " *" if sa != sb else ""
            print(f"{k:<40} {sa:<18} {sb:<18}{mark}")


def _summarize_full_stack_layers(d: dict[str, Any]) -> dict[str, str]:
    """All seven stack models — operator binding (governed_stack_contract.FULL_STACK_MODEL_LAYERS)."""
    mo = d.get("model_outputs") if isinstance(d.get("model_outputs"), dict) else {}
    xgb_ok = bool(mo.get("xgb", {}).get("available")) if isinstance(mo.get("xgb"), dict) else bool(d.get("xgb_available"))
    lstm_ok = bool(mo.get("lstm", {}).get("available")) if isinstance(mo.get("lstm"), dict) else bool(d.get("lstm_available"))
    tr_ok = bool(mo.get("transformer", {}).get("available")) if isinstance(mo.get("transformer"), dict) else bool(d.get("transformer_available"))
    meta_ok = bool(d.get("stack_probs_available") or d.get("meta_available"))
    mc_ok = bool(d.get("mc_available"))
    regime_ok = bool(d.get("regime_available") or d.get("vol_regime") or d.get("market_regime"))
    fusion_ok = bool(d.get("fusion_available"))
    return {
        "xgb": "ok" if xgb_ok else "—",
        "lstm": "ok" if lstm_ok else "—",
        "transformer": "ok" if tr_ok else "—",
        "meta": "ok" if meta_ok else "—",
        "monte_carlo": "ok" if mc_ok else "—",
        "regime": "ok" if regime_ok else "—",
        "fusion": "ok" if fusion_ok else "—",
    }


def summarize(ticker: str, d: dict[str, Any]) -> None:
    mo = d.get("model_outputs")
    fus = d.get("fusion_available")
    can_d = d.get("dominant_dir")
    can_c = d.get("confidence")
    can_p = d.get("canonical_provenance")
    stack = _summarize_full_stack_layers(d)
    print(f"\n--- {ticker} ---")
    print(
        "full_stack (7):",
        " ".join(f"{k}={v}" for k, v in stack.items()),
    )
    print(f"xgb_available={d.get('xgb_available')} lstm={d.get('lstm_available')} tr={d.get('transformer_available')}")
    print(f"fusion_available={fus} canonical/dominant_dir={can_d} confidence={can_c} prov={can_p}")
    print(f"call_signal={d.get('call_signal')} final_bias={d.get('final_bias')} wait_reason-ish: {str(d.get('validation_summary',''))[:80]}")
    for hz in ("1c", "5c", "15c", "60c"):
        t = _hz_probs(d, hz)
        print(f"  {hz}: any_none={t['any_none']} up={t['up']} down={t['down']} flat={t['flat']}")
    print(f"  samples_used={d.get('samples_used')} match_tier={d.get('match_tier')}")
    rows = d.get("mhap_rows") or []
    print(f"  mhap_rows ({len(rows)}):")
    for r in rows:
        if isinstance(r, dict):
            print(
                f"    {r.get('horizon')} role={r.get('role')} call={r.get('call')} "
                f"conf={r.get('confidence')} state={r.get('row_state')}"
            )


def main() -> int:
    base = (os.environ.get("ED_DIAG_BASE") or "http://127.0.0.1:8000").rstrip("/")
    exp = os.environ.get("ED_DIAG_EXPIRY") or ""
    token = os.environ.get("ED_DIAG_TOKEN") or None
    ta = (sys.argv[1] if len(sys.argv) > 1 else "SPY").upper().strip()
    tb = (sys.argv[2] if len(sys.argv) > 2 else "QQQ").upper().strip()

    q = "ticker={}&force=1"
    if exp:
        q += f"&expiry={exp}"
    try:
        da = _get(f"{base}/api/state?{q.format(ta)}", token)
        db = _get(f"{base}/api/state?{q.format(tb)}", token)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"URL error: {e}", file=sys.stderr)
        print("Start the console server or set ED_DIAG_BASE.", file=sys.stderr)
        return 1

    if isinstance(da, dict) and da.get("error") == "token_invalid":
        print("Server returned token_invalid (Schwab).", file=sys.stderr)
        return 1

    summarize(ta, da)
    summarize(tb, db)

    keys_a = {
        "fusion_available": da.get("fusion_available"),
        "dominant_dir": da.get("dominant_dir"),
        "confidence": da.get("confidence"),
        "canonical_provenance": da.get("canonical_provenance"),
        "samples_used": da.get("samples_used"),
        "match_tier": da.get("match_tier"),
        "call_signal": da.get("call_signal"),
        "final_bias": da.get("final_bias"),
        "primary_horizon": da.get("primary_horizon"),
        "alignment_state_display": da.get("alignment_state_display"),
        "entry_state": da.get("entry_state"),
    }
    for hz in ("1c", "5c", "15c", "60c"):
        keys_a[f"{hz}_any_none"] = _hz_probs(da, hz)["any_none"]

    keys_b = {
        "fusion_available": db.get("fusion_available"),
        "dominant_dir": db.get("dominant_dir"),
        "confidence": db.get("confidence"),
        "canonical_provenance": db.get("canonical_provenance"),
        "samples_used": db.get("samples_used"),
        "match_tier": db.get("match_tier"),
        "call_signal": db.get("call_signal"),
        "final_bias": db.get("final_bias"),
        "primary_horizon": db.get("primary_horizon"),
        "alignment_state_display": db.get("alignment_state_display"),
        "entry_state": db.get("entry_state"),
    }
    for hz in ("1c", "5c", "15c", "60c"):
        keys_b[f"{hz}_any_none"] = _hz_probs(db, hz)["any_none"]

    _print_block("Diff-friendly keys", keys_a, keys_b, ta, tb)
    print("\nTip: run server with ED_LIVE_DIAG=1 and grep logs for LIVE_DIAG lines (full pipeline JSON).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
