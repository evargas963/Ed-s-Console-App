#!/usr/bin/env python3
"""
Universal card fidelity runtime harness — read-only, ticker-agnostic, live API + browser DOM.

Default institutional proof set: SPY, QQQ, IWM (base seeds) + NVDA (guest seed).
Same validation path for every ticker; expected values derived from each ticker's live payload.

Usage:
  python tools/run_universal_card_fidelity_runtime.py
  python tools/run_universal_card_fidelity_runtime.py --tickers SPY,QQQ,IWM,NVDA \\
      --stable-reads 3 --require-browser-dom --require-live-transport
  python tools/run_universal_card_fidelity_runtime.py --tickers AAPL,MSFT

Reports (untracked): reports/ui_transport/universal_card_fidelity_<date>.json|.md
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scheduler_user_tickers import TRAINING_ANCHOR_TICKERS, is_training_anchor_ticker

# Base coverage seeds — not universality by themselves; guest required for institutional proof.
DEFAULT_BASE_TICKERS: tuple[str, ...] = TRAINING_ANCHOR_TICKERS
DEFAULT_GUEST_TICKERS: tuple[str, ...] = ("NVDA",)
DEFAULT_INSTITUTIONAL_TICKERS: tuple[str, ...] = DEFAULT_BASE_TICKERS + DEFAULT_GUEST_TICKERS

HORIZON_SLUGS: tuple[str, ...] = ("1c", "5c", "15c", "60c")

ORPHAN_FIELD_NAMES: tuple[str, ...] = (
    "pred_headline",
    "reversal_risk",
    "reversal_label",
    "call_headline",
    "call_signal",
    "call_state",
    "call_forecast_state",
    "z_score",
    "expected_move",
)

EM_BOUND_FIELDS: tuple[str, ...] = (
    "em_straddle_upper",
    "em_straddle_lower",
    "kl_em_upper",
    "kl_em_lower",
)

OPERATOR_DECISION_ORPHANS: frozenset[str] = frozenset(
    {
        "pred_headline",
        "reversal_risk",
        "reversal_label",
        "call_state",
        "call_forecast_state",
    }
)

BACKEND_ONLY_ORPHAN_FIELDS: frozenset[str] = frozenset(
    {
        "call_headline",
    }
)

DOM_CARD_IDS: dict[str, str] = {
    "1c": "tf-signal-1c",
    "5c": "tf-signal-5c",
    "15c": "tf-signal-15c",
    "60c": "tf-signal-60c",
    "ALL": "tf-signal-consolidated",
    "PLAN": "tf-signal-plan",
}


def parse_ticker_list(raw: str) -> list[str]:
    parts = re.split(r"[\s,]+", (raw or "").strip())
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        t = p.strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def split_base_guest(tickers: list[str]) -> tuple[list[str], list[str]]:
    bases = [t for t in tickers if is_training_anchor_ticker(t)]
    guests = [t for t in tickers if not is_training_anchor_ticker(t)]
    return bases, guests


def norm_dir(call: Any) -> str:
    u = str(call or "").upper()
    if u == "LONG":
        return "LONG"
    if u == "SHORT":
        return "SHORT"
    if u == "UNAVAILABLE":
        return "UNAVAILABLE"
    if u in ("WAIT", "FLAT", "NEUTRAL"):
        return "FLAT"
    return "FLAT"


def parse_confidence_pct(conf: Any) -> Optional[int]:
    if conf is None:
        return None
    try:
        n = float(conf)
    except (TypeError, ValueError):
        return None
    if 0 <= n <= 1:
        return round(n * 100)
    return round(min(100, max(0, n)))


def engine_tradeable_setup(payload: dict[str, Any]) -> bool:
    bias = str(payload.get("final_bias") or "WAIT").upper()
    return bool(payload.get("final_tradeable")) and bias in ("LONG", "SHORT")


def expected_tf_state_from_call(call: Any) -> str:
    d = norm_dir(call)
    if d == "LONG":
        return "up"
    if d == "SHORT":
        return "down"
    return "dim"


def mhap_row_by_horizon(payload: dict[str, Any], slug: str) -> Optional[dict[str, Any]]:
    for row in payload.get("mhap_rows") or []:
        if isinstance(row, dict) and str(row.get("horizon") or "").lower() == slug:
            return row
    return None


def derive_horizon_parity(payload: dict[str, Any], slug: str) -> dict[str, Any]:
    row = mhap_row_by_horizon(payload, slug)
    if not row:
        return {
            "field": f"mhap_{slug}",
            "expected_dir": "UNAVAILABLE",
            "expected_state": "dim",
            "expected_pct": None,
            "status": "MISSING_ROW",
        }
    call = row.get("call")
    conf = parse_confidence_pct(row.get("confidence"))
    state = expected_tf_state_from_call(call)
    nd = norm_dir(call)
    dom_dir = "UNAVAILABLE" if nd == "UNAVAILABLE" else ("NEUTRAL" if nd == "FLAT" else nd)
    return {
        "field": f"mhap_{slug}",
        "payload_call": call,
        "expected_dir": dom_dir,
        "expected_state": state,
        "expected_pct": conf,
        "status": "DERIVED",
    }


def derive_all_parity(payload: dict[str, Any]) -> dict[str, Any]:
    tradeable = engine_tradeable_setup(payload)
    bias = str(payload.get("final_bias") or "WAIT").upper()
    if tradeable and bias in ("LONG", "SHORT"):
        state = "up" if bias == "LONG" else "down"
        dom_dir = bias
    else:
        state = "dim"
        dom_dir = "NEUTRAL"
    return {
        "field": "ALL_final_bias",
        "payload_value": f"{bias} tradeable={tradeable}",
        "expected_state": state,
        "expected_dir": dom_dir,
        "status": "DERIVED",
    }


def derive_plan_parity(payload: dict[str, Any]) -> dict[str, Any]:
    tradeable = engine_tradeable_setup(payload)
    entry = str(payload.get("entry_state") or "no_setup").lower()
    if not tradeable:
        expected = "NO SETUP"
    elif entry == "no_setup":
        expected = "NO SETUP"
    else:
        expected = entry.replace("_", " ").upper()
    return {
        "field": "PLAN_entry_state",
        "payload_entry_state": entry,
        "expected_plan_state": expected,
        "status": "DERIVED",
    }


def derive_card_parity_expectations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for slug in HORIZON_SLUGS:
        out.append(derive_horizon_parity(payload, slug))
    out.append(derive_all_parity(payload))
    out.append(derive_plan_parity(payload))
    return out


def classify_orphan_field(
    field_name: str,
    payload: dict[str, Any],
    *,
    dom_body: str = "",
    card_dom_text: str = "",
    dom_snapshot: Optional[dict[str, Any]] = None,
) -> str:
    if field_name == "call_state":
        val = payload.get(field_name)
        if val is None or val == "":
            return "ABSENT"
        snap = dom_snapshot or {}
        expected = str(val).strip().upper()
        chip_state = str(snap.get("execution_chip_call_state") or "").upper()
        chip_text = str(snap.get("execution_chip_text") or "").upper()
        chip_trusted = str(snap.get("execution_chip_trusted") or "").lower()
        if chip_state == expected:
            if expected in ("WAIT", "WATCH") and chip_text == expected:
                return "RENDERED"
            if expected == "ACTIVE" and chip_trusted == "true" and chip_text == "ACTIVE":
                return "RENDERED"
            if expected == "ACTIVE" and chip_trusted == "false" and chip_text == "WITHHELD":
                return "RENDERED"
        return "OPERATOR_DECISION_REQUIRED"

    if field_name == "call_signal":
        val = payload.get(field_name)
        if val is None or val == "":
            return "ABSENT"
        sig = str(val).strip().lower()
        snap = dom_snapshot or {}
        promoted = payload.get("mh_promoted_directional") is True or snap.get(
            "mh_promotion_chip_visible"
        ) in ("true", True)
        chip_text = str(snap.get("mh_promotion_chip_text") or "").upper()
        if promoted and sig in ("long", "short"):
            expected = f"MH PROMOTED {sig.upper()}"
            if chip_text == expected or expected in chip_text:
                return "RENDERED"
            return "OPERATOR_DECISION_REQUIRED"
        # Supporting directional — not primary execution readiness; intentionally unrendered when not promoted.
        return "SUPPORTING_UNRENDERED"

    if field_name in BACKEND_ONLY_ORPHAN_FIELDS:
        val = payload.get(field_name)
        if val is None or val == "":
            return "ABSENT"
        return "BACKEND_ONLY"

    if field_name in EM_BOUND_FIELDS:
        present = any(payload.get(k) not in (None, "") for k in EM_BOUND_FIELDS if k.startswith("em_") or k.startswith("kl_em_"))
        if not present:
            return "ABSENT"
        # EM bounds render on key-level / exec surfaces, not horizon pills — backend-only on cards.
        return "BACKEND_ONLY"

    val = payload.get(field_name)
    if val is None or val == "":
        return "ABSENT"

    needle = str(val).strip()
    if len(needle) >= 8 and needle in dom_body:
        # Incidental body match is not a dedicated render — still orphaned for operator fields.
        if field_name in OPERATOR_DECISION_ORPHANS:
            return "OPERATOR_DECISION_REQUIRED"
        return "ORPHANED"

    if field_name in OPERATOR_DECISION_ORPHANS:
        return "OPERATOR_DECISION_REQUIRED"

    return "ORPHANED"


def build_orphan_table(payload: dict[str, Any], dom_snapshot: dict[str, Any]) -> dict[str, str]:
    body = str(dom_snapshot.get("body_text") or "")
    card_text = str(dom_snapshot.get("card_text") or "")
    combined = body + "\n" + card_text
    table: dict[str, str] = {}
    for name in ORPHAN_FIELD_NAMES:
        table[name] = classify_orphan_field(
            name,
            payload,
            dom_body=combined,
            card_dom_text=card_text,
            dom_snapshot=dom_snapshot,
        )
    em_vals = {k: payload.get(k) for k in EM_BOUND_FIELDS}
    has_em = any(v not in (None, "") for v in em_vals.values())
    table["EM_bounds"] = "BACKEND_ONLY" if has_em else "ABSENT"
    return table


def compare_dom_to_expectations(
    expectations: list[dict[str, Any]],
    dom_cards: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    slug_to_key = {"ALL": "consolidated", "PLAN": "plan"}

    for exp in expectations:
        field = exp.get("field", "")
        if field.startswith("mhap_"):
            slug = field.replace("mhap_", "")
            card = dom_cards.get(slug) or {}
            cls = str(card.get("class") or "")
            exp_state = exp.get("expected_state")
            parity = f"tf-state-{exp_state}" in cls if exp_state else False
            pct = card.get("pct")
            exp_pct = exp.get("expected_pct")
            pct_ok = exp_pct is None or pct == f"{exp_pct}%" or pct == str(exp_pct)
            status = "PARITY" if parity and pct_ok else "MISMATCH"
            rows.append(
                {
                    "field": field,
                    "payload_value": f"{exp.get('payload_call')}@{exp_pct}%",
                    "dom_value": f"{cls} dir={card.get('dir')} pct={pct}",
                    "parity_status": status,
                }
            )
        elif field == "ALL_final_bias":
            card = dom_cards.get("consolidated") or {}
            cls = str(card.get("class") or "")
            exp_state = exp.get("expected_state")
            status = "PARITY" if f"tf-state-{exp_state}" in cls else "MISMATCH"
            rows.append(
                {
                    "field": field,
                    "payload_value": exp.get("payload_value"),
                    "dom_value": f"{cls} dir={card.get('dir')}",
                    "parity_status": status,
                }
            )
        elif field == "PLAN_entry_state":
            dom_state = dom_cards.get("plan_state")
            exp_state = exp.get("expected_plan_state")
            status = "PARITY" if dom_state == exp_state else "MISMATCH"
            rows.append(
                {
                    "field": field,
                    "payload_value": exp.get("payload_entry_state"),
                    "dom_value": dom_state,
                    "parity_status": status,
                }
            )
    return rows


def evaluate_institutional_proof(
    *,
    tickers: list[str],
    ticker_results: dict[str, Any],
    require_browser_dom: bool,
    require_live_transport: bool,
    stable_reads_required: int,
) -> dict[str, Any]:
    """Institutional proof is NOT_PROVEN unless every gate passes for every required ticker."""
    bases_present, guests_present = split_base_guest(tickers)
    missing_bases = [t for t in DEFAULT_BASE_TICKERS if t not in tickers]
    reasons: list[str] = []

    if missing_bases:
        reasons.append(f"missing_base_tickers:{','.join(missing_bases)}")
    if not guests_present:
        reasons.append("missing_guest_ticker")

    for t in tickers:
        tr = ticker_results.get(t) or {}
        stab = tr.get("stability") or {}
        if stab.get("status") != "STABLE":
            reasons.append(f"{t}_stability:{stab.get('status')}")
        if stab.get("consecutive_stable_reads", 0) < stable_reads_required:
            reasons.append(f"{t}_stable_reads_insufficient")

        if require_browser_dom:
            dom = tr.get("browser_dom") or {}
            if dom.get("status") != "OK":
                reasons.append(f"{t}_browser_dom:{dom.get('status')}")
            parity_rows = dom.get("parity_rows") or []
            if any(r.get("parity_status") != "PARITY" for r in parity_rows):
                reasons.append(f"{t}_dom_parity_mismatch")
            if require_live_transport and dom.get("live_transport") != "CAPTURED":
                reasons.append(f"{t}_live_transport:{dom.get('live_transport')}")

    status = "NOT_PROVEN" if reasons else "PROVEN"
    return {
        "institutional_proof_status": status,
        "reasons": reasons,
        "base_tickers_present": bases_present,
        "guest_tickers_present": guests_present,
    }


def spy_only_institutional_pass_possible(ticker_results: dict[str, Any], stable_reads: int) -> bool:
    """True if only SPY could satisfy gates — used by regression tests to forbid SPY-only PASS."""
    if len(ticker_results) != 1 or "SPY" not in ticker_results:
        return False
    tr = ticker_results["SPY"]
    stab_ok = (tr.get("stability") or {}).get("status") == "STABLE"
    dom_ok = (tr.get("browser_dom") or {}).get("status") == "OK"
    return stab_ok and dom_ok


def base_only_institutional_pass_possible(tickers: list[str], ticker_results: dict[str, Any]) -> bool:
    _, guests = split_base_guest(tickers)
    if guests:
        return False
    return evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=ticker_results,
        require_browser_dom=True,
        require_live_transport=True,
        stable_reads_required=3,
    )["institutional_proof_status"] == "PROVEN"


class HttpClient:
    def __init__(self, base: str, timeout_sec: float = 180.0, token: Optional[str] = None) -> None:
        self.base = base
        self.timeout_sec = timeout_sec
        self.token = token

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def get_json(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(self.base + path, headers=self._headers(), method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            return json.loads(resp.read().decode())

    def post_json(self, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(self.base + path, data=data, headers=self._headers(), method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
            return json.loads(resp.read().decode())


def poll_stability(
    client: HttpClient,
    ticker: str,
    *,
    stable_reads: int = 3,
    poll_interval_sec: float = 8.0,
    max_wait_sec: float = 420.0,
) -> dict[str, Any]:
    reads: list[dict[str, Any]] = []
    streak = 0
    last_payload: dict[str, Any] = {}
    warm_status = "OK"
    warm_error: Optional[str] = None

    try:
        client.post_json(f"/api/analytics/warm?ticker={ticker}", {"source": "universal_card_fidelity_harness"})
    except Exception as exc:
        warm_status = "FAIL"
        warm_error = str(exc)

    t0 = time.time()
    while time.time() - t0 < max_wait_sec:
        try:
            payload = client.get_json(f"/api/analytics/state?ticker={ticker}&force=1")
        except Exception as exc:
            reads.append({"error": str(exc), "ts": time.time()})
            streak = 0
            time.sleep(poll_interval_sec)
            continue

        n_mhap = len(payload.get("mhap_rows") or [])
        pending = bool(payload.get("analytics_pending_shell"))
        snap = {
            "ts": time.time(),
            "mhap_rows": n_mhap,
            "final_bias": payload.get("final_bias"),
            "final_tradeable": payload.get("final_tradeable"),
            "entry_state": payload.get("entry_state"),
            "call_signal": payload.get("call_signal"),
            "call_state": payload.get("call_state"),
            "analytics_stale": payload.get("analytics_stale"),
            "analytics_pending_shell": pending,
        }
        reads.append(snap)
        last_payload = payload
        ok = n_mhap >= 4 and not pending
        streak = streak + 1 if ok else 0
        if streak >= stable_reads:
            break
        time.sleep(poll_interval_sec)

    # Refetch torture
    refetch_empty = False
    try:
        refetch = client.get_json(f"/api/analytics/state?ticker={ticker}&force=1")
        if len(last_payload.get("mhap_rows") or []) >= 4 and len(refetch.get("mhap_rows") or []) == 0:
            refetch_empty = True
    except Exception:
        refetch_empty = True

    status = "STABLE" if streak >= stable_reads and not refetch_empty else "NOT_PROVEN"
    return {
        "warm": warm_status,
        "warm_error": warm_error,
        "consecutive_stable_reads": streak,
        "stable_reads_required": stable_reads,
        "reads": reads,
        "refetch_empty_mhap": refetch_empty,
        "status": status,
        "payload": last_payload,
    }


def _node_playwright_script(base_url: str, ticker: str, timeout_ms: int) -> str:
    return textwrap.dedent(
        f"""
        const {{ chromium }} = require('playwright');
        (async () => {{
          const browser = await chromium.launch({{ headless: true }});
          const page = await browser.newPage();
          await page.addInitScript(() => {{ window.__ED_E2E__ = true; }});
          await page.goto({json.dumps(base_url + '/')}, {{ waitUntil: 'domcontentloaded', timeout: {timeout_ms} }});
          await page.waitForFunction(() => typeof window.setActiveTicker === 'function', null, {{ timeout: {timeout_ms} }});
          await page.evaluate(async (sym) => {{
            window.setActiveTicker(sym, null);
            if (typeof window.manualFullRefresh === 'function') {{
              await window.manualFullRefresh();
            }} else if (typeof window.fetchState === 'function') {{
              await window.fetchState(true);
            }}
          }}, {json.dumps(ticker)});
          await page.waitForFunction((sym) => {{
            const d = window._lastData;
            return d && String(d.ticker || '').toUpperCase() === sym.toUpperCase()
              && Array.isArray(d.mhap_rows) && d.mhap_rows.length >= 4
              && d.analytics_pending_shell !== true;
          }}, {json.dumps(ticker)}, {{ timeout: {timeout_ms} }});
          const out = await page.evaluate(() => {{
            const readCard = (id) => {{
              const el = document.getElementById(id);
              if (!el) return null;
              return {{
                class: el.className,
                dir: el.querySelector('.tf-dir')?.textContent?.trim() || null,
                pct: el.querySelector('.tf-pct')?.textContent?.trim() || null,
                dataDir: el.getAttribute('data-tf-signal-dir'),
                withhold: el.getAttribute('data-direction-withhold'),
              }};
            }};
            const cards = {{
              '1c': readCard('tf-signal-1c'),
              '5c': readCard('tf-signal-5c'),
              '15c': readCard('tf-signal-15c'),
              '60c': readCard('tf-signal-60c'),
              consolidated: readCard('tf-signal-consolidated'),
              plan: readCard('tf-signal-plan'),
            }};
            const planState = document.getElementById('tf-plan-state')?.textContent?.trim() || null;
            const tickerInput = document.getElementById('ticker-input')?.value?.trim()?.toUpperCase() || null;
            const staleLabel = document.getElementById('status-label')?.textContent || '';
            const transport = window.__edTransport || {{}};
            const src = window._lastPayloadUpdateSource || window._lastFullRenderSource || transport.lastFullRenderSource || '';
            const cardIds = ['tf-signal-1c','tf-signal-5c','tf-signal-15c','tf-signal-60c','tf-signal-consolidated','tf-signal-plan'];
            const card_text = cardIds.map(id => document.getElementById(id)?.textContent || '').join(' ');
            const execChip = document.getElementById('tf-execution-state-chip');
            const mhChip = document.getElementById('dr-mh-promotion-chip');
            const mhVisible = mhChip && mhChip.style.display !== 'none' && mhChip.textContent?.trim();
            return {{
              cards,
              plan_state: planState,
              ticker_input: tickerInput,
              active_ticker: window.activeTicker,
              last_data_ticker: window._lastData?.ticker,
              last_data: window._lastData,
              analytics_stale: window._lastData?.analytics_stale,
              analytics_pending_shell: window._lastData?.analytics_pending_shell,
              payload_update_source: src,
              transport_mode: transport.mode,
              body_text: document.body.innerText.slice(0, 120000),
              card_text,
              execution_chip_text: execChip ? execChip.textContent : null,
              execution_chip_call_state: execChip ? execChip.getAttribute('data-call-state') : null,
              execution_chip_trusted: execChip ? execChip.getAttribute('data-call-state-trusted') : null,
              mh_promotion_chip_text: mhChip ? mhChip.textContent?.trim() : null,
              mh_promotion_chip_visible: mhVisible ? 'true' : 'false',
              stale_label: staleLabel,
            }};
          }});
          console.log(JSON.stringify(out));
          await browser.close();
        }})().catch(err => {{ console.error(JSON.stringify({{ error: String(err) }})); process.exit(1); }});
        """
    ).strip()


def capture_browser_dom_live_transport(
    base_url: str,
    ticker: str,
    *,
    timeout_sec: float = 420.0,
) -> dict[str, Any]:
    node_modules = _REPO / "node_modules"
    env = os.environ.copy()
    env["NODE_PATH"] = str(node_modules)
    script = _node_playwright_script(base_url, ticker, int(timeout_sec * 1000))
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec + 30,
            cwd=str(_REPO),
            env=env,
        )
    except FileNotFoundError:
        return {"status": "SKIP", "error": "node_not_found", "live_transport": "NOT_PROVEN"}
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "error": "browser_timeout", "live_transport": "NOT_PROVEN"}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[-500:]
        return {"status": "FAIL", "error": err, "live_transport": "NOT_PROVEN"}

    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    if not lines:
        return {"status": "FAIL", "error": "no_json_from_browser", "live_transport": "NOT_PROVEN"}

    try:
        snap = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return {"status": "FAIL", "error": f"json_parse:{exc}", "live_transport": "NOT_PROVEN"}

    src = str(snap.get("payload_update_source") or "").lower()
    inject_only = "inject" in src or src in ("harness_inject", "evaluate_inject")
    has_live_payload = bool(snap.get("last_data_ticker")) and bool(snap.get("cards"))
    if inject_only:
        live_transport = "NOT_PROVEN"
    elif has_live_payload:
        live_transport = "CAPTURED"
    else:
        live_transport = "PARTIAL"

    ticker_ok = (
        str(snap.get("active_ticker") or "").upper() == ticker.upper()
        and str(snap.get("last_data_ticker") or "").upper() == ticker.upper()
    )

    return {
        "status": "OK",
        "snapshot": snap,
        "live_transport": live_transport,
        "ticker_identity_ok": ticker_ok,
        "payload_update_source": snap.get("payload_update_source"),
        "transport_mode": snap.get("transport_mode"),
    }


def collect_confirmed_defects(ticker_results: dict[str, Any]) -> list[str]:
    defects: list[str] = []
    for ticker, tr in ticker_results.items():
        ot = (tr.get("browser_dom") or {}).get("orphan_table") or tr.get("api_orphan_table") or {}
        for field, status in ot.items():
            if status in ("ORPHANED", "OPERATOR_DECISION_REQUIRED"):
                defects.append(f"{ticker}:{field}={status}")
    if defects:
        defects.append("rth_guest_switch_events_not_captured")
    return sorted(set(defects))


def evaluate_overall_card_fidelity(ticker_results: dict[str, Any]) -> str:
    """Overall card fidelity stays NOT_PROVEN while orphan operator fields remain unresolved."""
    return "NOT_PROVEN"


def run_harness(args: argparse.Namespace) -> dict[str, Any]:
    tickers = parse_ticker_list(args.tickers) if args.tickers else list(DEFAULT_INSTITUTIONAL_TICKERS)
    if not tickers:
        tickers = list(DEFAULT_INSTITUTIONAL_TICKERS)

    base_url = (args.base_url or os.environ.get("ED_DIAG_BASE") or "http://127.0.0.1:8000").rstrip("/")
    timeout = float(args.timeout_sec or os.environ.get("ED_CARD_FIDELITY_TIMEOUT") or 180)
    client = HttpClient(base=base_url, timeout_sec=timeout, token=os.environ.get("ED_DIAG_TOKEN"))

    server_reachable = False
    try:
        client.get_json("/api/build")
        server_reachable = True
    except Exception as exc:
        server_reachable = False
        server_error = str(exc)

    report: dict[str, Any] = {
        "schema_version": 1,
        "harness": "universal_card_fidelity_runtime",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "head_sha": args.head_sha,
        "base_url": base_url,
        "tickers": tickers,
        "default_institutional_tickers": list(DEFAULT_INSTITUTIONAL_TICKERS),
        "base_coverage_seeds": list(DEFAULT_BASE_TICKERS),
        "guest_seed_default": list(DEFAULT_GUEST_TICKERS),
        "stable_reads_required": args.stable_reads,
        "require_browser_dom": args.require_browser_dom,
        "require_live_transport": args.require_live_transport,
        "server_reachable": server_reachable,
        "ticker_results": {},
    }

    if not server_reachable:
        report["server_error"] = server_error
        report["harness_result"] = "NOT_RUN"
        report["institutional_proof"] = evaluate_institutional_proof(
            tickers=tickers,
            ticker_results={},
            require_browser_dom=args.require_browser_dom,
            require_live_transport=args.require_live_transport,
            stable_reads_required=args.stable_reads,
        )
        report["card_fidelity_runtime_status"] = "NOT_PROVEN"
        return report

    ticker_results: dict[str, Any] = {}
    for ticker in tickers:
        tr: dict[str, Any] = {"ticker": ticker}
        tr["stability"] = poll_stability(
            client,
            ticker,
            stable_reads=args.stable_reads,
            poll_interval_sec=args.poll_interval_sec,
            max_wait_sec=args.max_wait_sec,
        )
        payload = tr["stability"].get("payload") or {}

        browser: dict[str, Any] = {"status": "SKIP", "live_transport": "NOT_PROVEN"}
        if not args.skip_browser:
            browser = capture_browser_dom_live_transport(base_url, ticker, timeout_sec=args.max_wait_sec)
            if browser.get("status") == "OK":
                snap = browser.get("snapshot") or {}
                cards = snap.get("cards") or {}
                cards["plan_state"] = snap.get("plan_state")
                render_payload = snap.get("last_data") if isinstance(snap.get("last_data"), dict) else payload
                expectations = derive_card_parity_expectations(render_payload)
                parity_rows = compare_dom_to_expectations(expectations, cards)
                browser["parity_rows"] = parity_rows
                browser["orphan_table"] = build_orphan_table(render_payload, snap)
                browser["stale_pending"] = {
                    "analytics_stale_payload": render_payload.get("analytics_stale"),
                    "analytics_stale_dom": snap.get("analytics_stale"),
                    "pending_shell_payload": render_payload.get("analytics_pending_shell"),
                    "pending_shell_dom": snap.get("analytics_pending_shell"),
                    "loading_class_present": any(
                        "analytics-loading" in str((cards.get(k) or {}).get("class") or "")
                        for k in ("1c", "5c", "15c", "60c", "consolidated", "plan")
                    ),
                }
                call_state = render_payload.get("call_state")
                body = snap.get("body_text") or ""
                chip_state = snap.get("execution_chip_call_state")
                chip_text = str(snap.get("execution_chip_text") or "")
                chip_trusted = str(snap.get("execution_chip_trusted") or "")
                exec_visible = True
                if call_state:
                    cs = str(call_state).strip().upper()
                    if chip_state and str(chip_state).upper() == cs:
                        if cs == "ACTIVE" and chip_trusted == "false":
                            exec_visible = chip_text.upper() == "WITHHELD"
                        else:
                            exec_visible = cs in chip_text.upper() or chip_trusted == "true"
                    else:
                        exec_visible = cs in body.upper()
                browser["wait_watch_active"] = {
                    "call_state_payload": call_state,
                    "execution_chip_call_state": chip_state,
                    "execution_chip_text": chip_text,
                    "execution_chip_trusted": chip_trusted,
                    "visible_in_body": exec_visible,
                    "status": "NOT_PROVEN" if call_state and not exec_visible else "PROVEN",
                }
        tr["browser_dom"] = browser
        tr["api_orphan_table"] = build_orphan_table(payload, {})
        ticker_results[ticker] = tr

    report["ticker_results"] = ticker_results
    report["institutional_proof"] = evaluate_institutional_proof(
        tickers=tickers,
        ticker_results=ticker_results,
        require_browser_dom=args.require_browser_dom,
        require_live_transport=args.require_live_transport,
        stable_reads_required=args.stable_reads,
    )
    report["card_fidelity_runtime_status"] = report["institutional_proof"]["institutional_proof_status"]
    report["defects_confirmed"] = collect_confirmed_defects(ticker_results)
    report["card_fidelity_overall_status"] = evaluate_overall_card_fidelity(ticker_results)
    report["harness_result"] = "PASS" if server_reachable else "NOT_RUN"
    if report["institutional_proof"]["institutional_proof_status"] != "PROVEN":
        report["harness_result"] = "FAIL"

    report["rth_guest_switch_support"] = "PARTIAL"
    report["rth_note"] = (
        "RTH guest-switch proof requires operator-driven switches via "
        "tools/run_rth_guest_switch_validation.py with switch_event_count > 0."
    )
    return report


def write_reports(report: dict[str, Any], out_dir: Path, audit_date: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"universal_card_fidelity_{audit_date}.json"
    md_path = out_dir / f"universal_card_fidelity_{audit_date}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        f"# Universal card fidelity runtime — {audit_date}",
        "",
        f"- harness_result: **{report.get('harness_result')}**",
        f"- institutional_proof: **{report.get('institutional_proof', {}).get('institutional_proof_status')}**",
        f"- card_fidelity_runtime_status: **{report.get('card_fidelity_runtime_status')}**",
        "",
    ]
    for t, tr in (report.get("ticker_results") or {}).items():
        stab = tr.get("stability") or {}
        dom = tr.get("browser_dom") or {}
        lines.append(f"## {t}")
        lines.append(f"- stability: {stab.get('status')} ({stab.get('consecutive_stable_reads')} reads)")
        lines.append(f"- browser_dom: {dom.get('status')} live_transport={dom.get('live_transport')}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--tickers",
        default=",".join(DEFAULT_INSTITUTIONAL_TICKERS),
        help="Comma/space-separated tickers (default institutional set)",
    )
    p.add_argument("--base-url", default=None, help="Server base URL (default ED_DIAG_BASE or :8000)")
    p.add_argument("--stable-reads", type=int, default=3, help="Consecutive stable reads required")
    p.add_argument("--poll-interval-sec", type=float, default=8.0)
    p.add_argument("--max-wait-sec", type=float, default=420.0)
    p.add_argument("--timeout-sec", type=float, default=180.0, help="HTTP timeout per request")
    p.add_argument("--require-browser-dom", action="store_true", help="Require Playwright DOM capture")
    p.add_argument("--require-live-transport", action="store_true", help="Require live transport (not inject-only)")
    p.add_argument("--audit-date", default=datetime.date.today().isoformat())
    p.add_argument("--output-dir", type=Path, default=_REPO / "reports" / "ui_transport")
    p.add_argument("--no-write-report", action="store_true")
    p.add_argument("--head-sha", default=None)
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    if args.head_sha is None:
        try:
            import subprocess as sp

            args.head_sha = sp.check_output(["git", "rev-parse", "HEAD"], cwd=str(_REPO), text=True).strip()
        except Exception:
            args.head_sha = "unknown"

    if args.require_browser_dom:
        args.skip_browser = False
    else:
        args.skip_browser = True

    report = run_harness(args)
    if not args.no_write_report:
        jp, mp = write_reports(report, args.output_dir, args.audit_date)
        print(f"wrote {jp}")
        print(f"wrote {mp}")

    print(json.dumps({
        "harness_result": report.get("harness_result"),
        "institutional_proof_status": report.get("institutional_proof", {}).get("institutional_proof_status"),
        "card_fidelity_runtime_status": report.get("card_fidelity_runtime_status"),
        "card_fidelity_overall_status": report.get("card_fidelity_overall_status"),
        "defects_confirmed_count": len(report.get("defects_confirmed") or []),
        "reasons": report.get("institutional_proof", {}).get("reasons"),
    }, indent=2))

    inst = report.get("institutional_proof", {}).get("institutional_proof_status")
    overall = report.get("card_fidelity_overall_status")
    if inst != "PROVEN" or overall != "PROVEN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
