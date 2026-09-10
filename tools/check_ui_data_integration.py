"""UI ↔ data integration gate — mechanically stop "done" claims over dead placeholders.

WHY THIS EXISTS (operator, 2026-07-25): an agent's text tools cannot see a rendered DOM,
so it can verify code + endpoints yet still ship a screen full of "—" or static mock
shapes. This gate closes that loophole in three tiers, from cheap-and-always-on to
expensive-and-live:

  TIER 1 — STATIC BINDING (always; no server): every data cell in EVERY page the router
    serves (the PAGE routes of governance/provenance_roots.py resolved to their static file
    by `served_pages` below — the router is the population, never a hand list; 2026-09-10
    replaced the two-file tuple that stood in for it, which audited 2 of 7 pages)
    that ships initialised to the "—" placeholder MUST have a JavaScript
    writer (a T('id', …) / getElementById('id') / el('id') reference in a <script>). An
    element that renders "—" forever because nothing populates it is a dead placeholder,
    and this fails the build. This is the tier wired into pre-commit — pure text parse,
    no network, no browser, so it can never false-fail on a down server.

  TIER 2 — ENDPOINT ASSERTIONS (server-gated): if a local server is reachable, the key
    endpoints must return REAL numeric data, not empty objects or empty arrays. Skipped
    (clean pass) when no server is up, so it never blocks an offline commit.

  TIER 3 — HEADLESS RENDER (server + Node Playwright, opt-in via ED_UI_GATE_LIVE=1):
    actually render the page, visit each tab, and assert the key cells show real numbers,
    not "—". This is the only tier that sees what the agent cannot — the rendered DOM.
    Off by default (it is slow) so pre-commit stays fast; CI / manual runs set the flag.

Design note: TIER 1 is fail-closed and enforced. TIERS 2–3 are deliberately skip-when-
absent rather than hard pre-commit gates, because a browser+server dependency inside every
commit would itself become a source of false failures — the exact anti-pattern this repo
already hit with the worktree gate's fail-on-unset behaviour.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The id-prefixes that mark a *data* cell (not chrome). The PAGES audited are not listed
#: here: they are every page the router serves (`served_pages`).
_DATA_ID_RE = re.compile(r'id="((?:cv2|ct|dr|kl|hd)-[\w-]+)"[^>]*>\s*(?:<[^>]+>\s*)*—')


def served_pages(repo: Path | None = None) -> list[str]:
    """The canonical page population: PAGE routes of the provenance root population
    (governance/provenance_roots.py, reconciled with server.py by tests/test_provenance_v1.py)
    resolved to the `static/*.html` literal their handler reads. The router is the authority;
    a file under static/ that no route serves is not a page. Unresolvable => raise: a gate
    that cannot name its population must not report a clean run over an invented one."""
    import ast
    root = repo or REPO
    ns: dict = {}
    exec(compile((root / "governance" / "provenance_roots.py").read_text(encoding="utf-8"), "provenance_roots", "exec"), ns)
    page_routes = {r for r, (cls, _p) in ns["ROUTES"].items() if cls == "PAGE"}
    pages: set[str] = set()
    for node in ast.parse((root / "server.py").read_text(encoding="utf-8", errors="replace")).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post")
                   and d.args and isinstance(d.args[0], ast.Constant) and d.args[0].value in page_routes
                   for d in node.decorator_list):
            continue
        for c in ast.walk(node):
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.endswith(".html"):
                rel = c.value.replace("\\", "/")
                if "static/" in rel:
                    pages.add(rel[rel.index("static/"):])
                elif "/" not in rel:
                    pages.add(f"static/{rel}")
    if not pages:
        raise LookupError("no PAGE route resolves to a static HTML file")
    return sorted(p for p in pages if (root / p).is_file())


#: Endpoints that must return real data, with a callable asserting "this JSON is real".
_ENDPOINTS = {
    "/api/terrain?ticker=SPY": lambda d: isinstance(d.get("gamma_flip"), (int, float)),
    "/api/terrain/strikes?ticker=SPY": lambda d: bool((d.get("today") or {}).get("all")),
    "/api/analytics/state?ticker=SPY": lambda d: isinstance(d, dict) and len(d) > 5,
    "/api/bars1m?ticker=SPY": lambda d: bool(d.get("bars")),
    "/api/terrain/radar?ticker=SPY": lambda d: isinstance(d.get("rows"), list),
}


def _base_url() -> str:
    return (os.environ.get("ED_DIAG_BASE") or "http://127.0.0.1:8000").rstrip("/")


def _server_up(base: str, timeout: float = 0.4) -> bool:
    try:
        urllib.request.urlopen(base + "/favicon.ico", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # any HTTP response means the server is answering
    except Exception:
        return False


def _get_json(url: str, timeout: float = 16.0) -> dict | None:
    # analytics/state is the heavy ML stack and can take several seconds — the gate
    # asserts "returns real data", not "is fast", so it must wait it out.
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# ── TIER 1 ─────────────────────────────────────────────────────────────────────────────
def _tier1_static_binding(pages: list[str] | None = None,
                          repo: Path | None = None) -> list[tuple[str, int, str]]:
    root = repo or REPO
    out: list[tuple[str, int, str]] = []
    if pages is None:
        try:
            pages = served_pages(root)
        except Exception as e:  # noqa: BLE001 — an unreadable population is a violation, not a pass
            return [("governance/provenance_roots.py", 0,
                     f"the served-page population could not be resolved from the router: {e!r}")]
    for rel in pages:
        p = root / rel
        if not p.exists():
            out.append((rel, 0, "a PAGE route serves this file and it does not exist"))
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        # every <script> body concatenated — a data cell is "wired" if its id appears here.
        scripts = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", text, re.S))
        lines = text.split("\n")
        for i, line in enumerate(lines, 1):
            for m in _DATA_ID_RE.finditer(line):
                cell = m.group(1)
                if ("'" + cell + "'") in scripts or ('"' + cell + '"') in scripts:
                    continue
                out.append((
                    rel, i,
                    f"data cell id='{cell}' ships as the '—' placeholder but no <script> "
                    f"ever writes it — a dead placeholder that can never show real data. "
                    f"Wire it to a real API value or remove the element.",
                ))
    return out


# ── TIER 2 ─────────────────────────────────────────────────────────────────────────────
def _tier2_endpoints(base: str) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for path, is_real in _ENDPOINTS.items():
        d = _get_json(base + path)
        if d is None:
            out.append(("(live endpoint)", 0, f"{path}: no/invalid JSON response"))
            continue
        try:
            ok = bool(is_real(d))
        except Exception as e:  # noqa: BLE001 - a shape error is itself a failure
            ok = False
            out.append(("(live endpoint)", 0, f"{path}: shape check raised {e!r}"))
            continue
        if not ok:
            out.append(("(live endpoint)", 0,
                        f"{path}: returned empty/non-numeric data — the UI would render "
                        f"'—'. Endpoint must serve real data before the UI can."))
    return out


# ── TIER 3 ─────────────────────────────────────────────────────────────────────────────
_RENDER_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[2];
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const bad = [];
  const val = async (sel) => { const el = await page.$(sel); return el ? (await el.innerText()).trim() : '(missing)'; };
  const real = async (sel) => { const v = await val(sel); return !!v && v !== '—'; };
  const count = async (sel) => page.$$eval(sel, els => els.length).catch(() => 0);
  // poll: wait up to `ms` for EVERY condition (text-is-real / element-count) to hold.
  // Waits out slow analytics AND the strikes fetch that builds bars/rows — so the probe
  // asserts the settled DOM, never a mid-load snapshot.
  const waitAll = async (checks, ms) => {
    const t0 = Date.now();
    for (;;) {
      let ok = true;
      for (const c of checks) { if (!(await c())) { ok = false; break; } }
      if (ok || Date.now() - t0 > ms) return;
      await page.waitForTimeout(500);
    }
  };
  try {
    await page.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 20000 });
    const cCells = ['#cv2-c-verd', '#cv2-kl-flip', '#cv2-g-gex'];
    await waitAll(cCells.map(s => () => real(s)).concat([async () => (await count('#cv2-gx .cv-bar')) >= 1]), 28000);
    for (const s of cCells) { const v = await val(s); if (!v || v === '—') bad.push('console ' + s + '=' + v); }
    if ((await count('#cv2-gx .cv-bar')) < 1) bad.push('console gamma bars rendered 0 real bars');
    const tt = await page.$('#cv2-tab-terrain'); if (tt) await tt.click();
    const tCells = ['#ct-verd', '#ct-flip', '#ct-gex'];
    await waitAll(tCells.map(s => () => real(s)).concat([async () => (await count('#ct-map .ct-row')) >= 1]), 28000);
    for (const s of tCells) { const v = await val(s); if (!v || v === '—') bad.push('terrain ' + s + '=' + v); }
    if ((await count('#ct-map .ct-row')) < 1) bad.push('terrain price map rendered 0 real rows');

    // RC-81 — ONE TICK, ONE PRICE. A single spot AUTHORITY only guarantees that readers
    // sampled at the SAME INSTANT agree; with several paint sites on several clocks the
    // operator still sees two prices. MEASURED here before the fix: over 15s ub-price walked
    // 737.65 -> 737.71 -> 737.73 while cv2-hd-px sat at 737.65 the whole time. No static check
    // can see that — cadence is only visible in the rendered DOM, which is why the assertion
    // lives in this tier and not in the faucet audit.
    await page.goto(base + '/', { waitUntil: 'domcontentloaded', timeout: 20000 });
    const SPOT_IDS = ['#sb-spot', '#ub-price', '#cv2-hd-px'];
    const priced = async () => {
      const vs = [];
      for (const s of SPOT_IDS) { const v = await val(s); if (v && v !== '—' && v !== '(missing)') vs.push(v); }
      return vs.length >= 2;
    };
    await waitAll([priced], 25000);
    for (let i = 0; i < 3; i++) {
      const seen = {};
      for (const s of SPOT_IDS) {
        const v = await val(s);
        if (v && v !== '—' && v !== '(missing)') seen[s] = v;
      }
      const distinct = [...new Set(Object.values(seen))];
      if (distinct.length > 1) {
        bad.push('console shows ' + distinct.length + ' DIFFERENT spot prices in one frame: ' +
                 JSON.stringify(seen));
        break;
      }
      await page.waitForTimeout(4000);
    }

    await page.goto(base + '/chart', { waitUntil: 'domcontentloaded', timeout: 20000 });
    const chartPriced = async () =>
      (await real('#biglegend .px')) && (await real('#metapx'));
    await waitAll([chartPriced], 25000);
    for (let i = 0; i < 3; i++) {
      const big = await val('#biglegend .px'), meta = await val('#metapx');
      if (big !== '(missing)' && meta !== '(missing)' && big !== meta) {
        bad.push('chart big legend (' + big + ') and meta bar (' + meta +
                 ') show different spot prices in one frame');
        break;
      }
      await page.waitForTimeout(4000);
    }
  } catch (e) { bad.push('render error: ' + e.message); }
  await browser.close();
  console.log(JSON.stringify(bad));
})();
"""


def _tier3_render(base: str) -> list[tuple[str, int, str]]:
    script = REPO / "tools" / "_ui_render_probe.js"
    try:
        script.write_text(_RENDER_JS, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(script), base],
            capture_output=True, text=True, timeout=90, cwd=str(REPO),
        )
    except FileNotFoundError:
        return []  # node absent — skip
    except subprocess.TimeoutExpired:
        return [("(render)", 0, "headless render timed out")]
    finally:
        try:
            script.unlink()
        except OSError:
            pass
    if proc.returncode != 0:
        # playwright not installed / launch failed → skip rather than false-fail
        if "Cannot find module 'playwright'" in (proc.stderr or ""):
            return []
        return [("(render)", 0, f"render probe failed: {(proc.stderr or '').strip()[:200]}")]
    try:
        bad = json.loads((proc.stdout or "[]").strip().splitlines()[-1])
    except Exception:
        return [("(render)", 0, f"render probe returned unparseable output: {proc.stdout[:200]}")]
    return [("(rendered DOM)", 0, f"cell shows placeholder, not real data: {b}") for b in bad]


def static_binding_violations(pages: list[str] | None = None,
                              repo: Path | None = None) -> list[tuple[str, int, str]]:
    """Tier 1 only — the fast, server-free, deterministic check wired into pre-commit.
    Every data cell that ships as the '—' placeholder must have a JavaScript writer, on
    every page the router serves (or the explicit `pages` a caller judges)."""
    return _tier1_static_binding(pages, repo)


def ui_data_integration_violations() -> list[tuple[str, int, str]]:
    """All violations. Tier 1 always; tiers 2–3 only when a server is reachable
    (tier 3 additionally requires ED_UI_GATE_LIVE=1 and Node Playwright)."""
    violations = _tier1_static_binding()
    base = _base_url()
    if _server_up(base):
        violations += _tier2_endpoints(base)
        if os.environ.get("ED_UI_GATE_LIVE") == "1":
            violations += _tier3_render(base)
    return violations


def _tier_status() -> str:
    base = _base_url()
    up = _server_up(base)
    t3 = "on" if (up and os.environ.get("ED_UI_GATE_LIVE") == "1") else "skipped"
    return (f"tier1=static(on)  tier2=endpoints({'on' if up else 'skipped(no server)'})  "
            f"tier3=render({t3})")


if __name__ == "__main__":
    print("UI DATA INTEGRATION GATE —", _tier_status())
    vs = ui_data_integration_violations()
    if not vs:
        print("PASS — no dead placeholders; live tiers clean where run.")
        raise SystemExit(0)
    for rel, line, msg in vs:
        print(f"  {rel}:{line}  {msg}")
    print(f"FAIL — {len(vs)} violation(s)")
    raise SystemExit(1)
