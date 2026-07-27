#!/usr/bin/env python3
"""
Fetch /api/state for training anchors (default SPY + QQQ + IWM) and print stack + Call summary.

Usage (console running with Schwab auth OK):
  set ED_LIVE_DIAG=1
  python tools/live_diag_compare.py              # all three anchors
  python tools/live_diag_compare.py SPY QQQ IWM
  python tools/live_diag_compare.py NVDA       # single guest ticker
  python tools/live_diag_compare.py --ui-maximize-probe SPY

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
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS, is_training_anchor_ticker

DEFAULT_DIAG_TICKERS: tuple[str, ...] = TRAINING_ANCHOR_TICKERS


def _get(url: str, token: Optional[str]) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _post(url: str, token: Optional[str], body: dict | None = None) -> dict[str, Any]:
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _ui_maximize_probe(base: str, ticker: str, exp: str, token: Optional[str]) -> int:
    """UI-MAXIMIZE timing probe — pending shell, partial Tier C, full fusion (_pipeline_ms)."""
    t0 = time.perf_counter()
    q_base = f"ticker={ticker}"
    if exp:
        q_base += f"&expiry={exp}"

    try:
        build = _get(f"{base}/api/build", token)
        warm = _post(f"{base}/api/analytics/warm?{q_base}", token, {"source": "ui_maximize_probe"})
        pending = _get(f"{base}/api/analytics/state?{q_base}", token)
        t_pending_ms = int((time.perf_counter() - t0) * 1000)

        t1 = time.perf_counter()
        partial = _get(f"{base}/api/analytics/state?{q_base}&force=1", token)
        t_partial_ms = int((time.perf_counter() - t1) * 1000)

        t2 = time.perf_counter()
        full = _get(f"{base}/api/analytics/state?{q_base}&force=1", token)
        t_full_ms = int((time.perf_counter() - t2) * 1000)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"URL error: {e}", file=sys.stderr)
        print("Start the console server or set ED_DIAG_BASE.", file=sys.stderr)
        return 1

    sla = build.get("ui_maximize_sla_ms") or {}
    print(f"\n=== UI-MAXIMIZE probe {ticker} ===")
    print(f"sla_ms: {json.dumps(sla)}")
    print(f"warm_post: {json.dumps(warm)}")
    print(f"pending_shell_ms={t_pending_ms} analytics_pending_shell={pending.get('analytics_pending_shell')}")
    print(
        f"partial_tier_c_ms={t_partial_ms} analytics_partial_tier_c={partial.get('analytics_partial_tier_c')} "
        f"_pipeline_ms={partial.get('_pipeline_ms')} mhap_rows={len(partial.get('mhap_rows') or [])}"
    )
    print(
        f"full_fusion_ms={t_full_ms} fusion_available={full.get('fusion_available')} "
        f"_pipeline_ms={full.get('_pipeline_ms')} mhap_rows={len(full.get('mhap_rows') or [])}"
    )
    fq_sla = int(sla.get("first_quote") or 500)
    panel_sla = int(sla.get("fusion_cards_panel_warm") or 2000)
    if is_training_anchor_ticker(ticker):
        fusion_sla = panel_sla
    else:
        fusion_sla = int(sla.get("fusion_cards_guest_cold") or 15000)
    print(
        f"verdict: pending<={fq_sla} {'PASS' if t_pending_ms <= fq_sla else 'FAIL'} | "
        f"fusion_target<={fusion_sla} {'PASS' if t_full_ms <= fusion_sla else 'SLOW'}"
    )
    return 0


def _hz_probs(d: dict, hz: str) -> dict[str, Any]:
    u, dn, f = (d.get(f"up_prob_{hz}"), d.get(f"down_prob_{hz}"), d.get(f"flat_prob_{hz}"))
    return {"up": u, "down": dn, "flat": f, "any_none": u is None or dn is None or f is None}


def _diff_keys(d: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "fusion_available": d.get("fusion_available"),
        "dominant_dir": d.get("dominant_dir"),
        "confidence": d.get("confidence"),
        "canonical_provenance": d.get("canonical_provenance"),
        "samples_used": d.get("samples_used"),
        "match_tier": d.get("match_tier"),
        "call_signal": d.get("call_signal"),
        "final_bias": d.get("final_bias"),
        "primary_horizon": d.get("primary_horizon"),
        "alignment_state_display": d.get("alignment_state_display"),
        "final_quality": d.get("final_quality"),
        "entry_state": d.get("entry_state"),
    }
    for hz in ("1c", "5c", "15c", "60c"):
        keys[f"{hz}_any_none"] = _hz_probs(d, hz)["any_none"]
    return keys


def _print_block(title: str, a: dict, b: dict, tick_a: str, tick_b: str) -> None:
    print(f"\n=== {title} ===")
    print(f"{'field':<40} {tick_a:<18} {tick_b:<18}")
    print("-" * 78)
    keys = sorted(set(a.keys()) | set(b.keys()))
    for k in keys:
        va, vb = a.get(k), b.get(k)
        sa = json.dumps(va, default=str)[:70] if va is not None else "null"
        sb = json.dumps(vb, default=str)[:70] if vb is not None else "null"
        if sa != sb or k in ("final_bias", "call_signal", "fusion_available"):
            mark = " *" if sa != sb else ""
            print(f"{k:<40} {sa:<18} {sb:<18}{mark}")


def _layer_flag(ok: bool) -> str:
    """ASCII-only for Windows consoles (avoid em-dash mojibake)."""
    return "ok" if ok else "missing"


def _summarize_full_stack_layers(d: dict[str, Any]) -> dict[str, str]:
    """All seven stack models — operator binding (governed_stack_contract.FULL_STACK_MODEL_LAYERS)."""
    mo = d.get("model_outputs") if isinstance(d.get("model_outputs"), dict) else {}
    xgb_ok = bool(mo.get("xgb", {}).get("available")) if isinstance(mo.get("xgb"), dict) else bool(d.get("xgb_available"))
    lstm_ok = bool(mo.get("lstm", {}).get("available")) if isinstance(mo.get("lstm"), dict) else bool(d.get("lstm_available"))
    tr_ok = bool(mo.get("transformer", {}).get("available")) if isinstance(mo.get("transformer"), dict) else bool(d.get("transformer_available"))
    meta_mo = mo.get("meta") if isinstance(mo.get("meta"), dict) else {}
    meta_ok = bool(meta_mo.get("available")) if meta_mo else (
        xgb_ok and lstm_ok and tr_ok and bool(d.get("fusion_available"))
    )
    mc_ok = bool(d.get("mc_available"))
    regime_ok = bool(
        d.get("regime_available")
        or d.get("vol_regime")
        or d.get("market_regime")
        or d.get("regime_label")
    )
    fusion_ok = bool(d.get("fusion_available"))
    return {
        "xgb": _layer_flag(xgb_ok),
        "lstm": _layer_flag(lstm_ok),
        "transformer": _layer_flag(tr_ok),
        "meta": _layer_flag(meta_ok),
        "monte_carlo": _layer_flag(mc_ok),
        "regime": _layer_flag(regime_ok),
        "fusion": _layer_flag(fusion_ok),
    }


def stack_layer_failures(ticker: str, d: dict[str, Any]) -> list[str]:
    """Missing layers for anchor tickers (fail-closed operator check)."""
    if not is_training_anchor_ticker(ticker):
        return []
    stack = _summarize_full_stack_layers(d)
    return [layer for layer, status in stack.items() if status != "ok"]


def _primary_mhap_row(d: dict[str, Any]) -> dict[str, Any] | None:
    for r in d.get("mhap_rows") or []:
        if isinstance(r, dict) and r.get("role") == "Primary":
            return r
    return None


def _alignment_explainer(d: dict[str, Any]) -> str:
    """One-line why alignment_state_display is what it is (operator legibility)."""
    from multi_horizon_decision import (
        ALIGNMENT_STATE_NO_PRIMARY,
        ALIGNMENT_STATE_UNUSABLE_LEGACY,
        alignment_state_operator_label,
        normalize_alignment_state,
    )

    align = normalize_alignment_state(str(d.get("alignment_state_display") or "unknown"))
    ph = d.get("primary_horizon") or "?"
    if align not in (ALIGNMENT_STATE_NO_PRIMARY, ALIGNMENT_STATE_UNUSABLE_LEGACY):
        return (
            f"alignment={align} ({alignment_state_operator_label(align)}) "
            f"primary={ph} trade_mode={d.get('trade_mode')}"
        )
    prow = _primary_mhap_row(d)
    if prow:
        return (
            f"alignment=no_primary: primary {ph} is {prow.get('call')} "
            f"(conf={prow.get('confidence')}) — no directional trade plan to align against"
        )
    return f"alignment=no_primary: primary {ph} not tradeable"


def summarize(ticker: str, d: dict[str, Any]) -> list[str]:
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
    missing = stack_layer_failures(ticker, d)
    if missing:
        print(f"  STACK_MISSING: {', '.join(missing)}")
    print(f"xgb_available={d.get('xgb_available')} lstm={d.get('lstm_available')} tr={d.get('transformer_available')}")
    print(f"fusion_available={fus} canonical/dominant_dir={can_d} confidence={can_c} prov={can_p}")
    print(f"alignment: {_alignment_explainer(d)}")
    print(f"primary_horizon={d.get('primary_horizon')} final_quality={d.get('final_quality')} entry_state={d.get('entry_state')}")
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
    return missing


def main() -> int:
    base = (os.environ.get("ED_DIAG_BASE") or "http://127.0.0.1:8000").rstrip("/")
    exp = os.environ.get("ED_DIAG_EXPIRY") or ""
    token = os.environ.get("ED_DIAG_TOKEN") or None
    argv = [a for a in sys.argv[1:] if a]
    ui_maximize_probe = "--ui-maximize-probe" in argv
    if ui_maximize_probe:
        argv = [a for a in argv if a != "--ui-maximize-probe"]

    if ui_maximize_probe:
        ta = (argv[0] if argv else DEFAULT_DIAG_TICKERS[0]).upper().strip()
        return _ui_maximize_probe(base, ta, exp, token)

    tickers = [t.upper().strip() for t in argv] if argv else list(DEFAULT_DIAG_TICKERS)

    q = "ticker={}&force=1"
    if exp:
        q += f"&expiry={exp}"

    payloads: dict[str, dict[str, Any]] = {}
    try:
        for t in tickers:
            payloads[t] = _get(f"{base}/api/state?{q.format(t)}", token)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"URL error: {e}", file=sys.stderr)
        print("Start the console server or set ED_DIAG_BASE.", file=sys.stderr)
        return 1

    if isinstance(payloads.get(tickers[0]), dict) and payloads[tickers[0]].get("error") == "token_invalid":
        print("Server returned token_invalid (Schwab).", file=sys.stderr)
        return 1

    all_missing: list[str] = []
    for t in tickers:
        all_missing.extend(summarize(t, payloads[t]))

    if len(tickers) >= 2:
        ref = tickers[0]
        ref_keys = _diff_keys(payloads[ref])
        for other in tickers[1:]:
            _print_block(f"Diff vs {ref}", ref_keys, _diff_keys(payloads[other]), ref, other)

    print("\nTip: run server with ED_LIVE_DIAG=1 and grep logs for LIVE_DIAG lines (full pipeline JSON).")
    if all_missing:
        print(
            f"\nFAIL: anchor stack incomplete — missing layers on: {', '.join(sorted(set(all_missing)))}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
