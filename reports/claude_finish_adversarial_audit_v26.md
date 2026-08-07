# Claude Finish Adversarial Audit v26 — RC-131/132 goal closeout

**Target commits:**  
- `33d5c2c5` — RC-131 fail-closed wall claims  
- `33268c50` — RC-132 pin tip + HVL paint deletion  

**Claude claim:** DONE A1+A2+A3; locks; live wire+DOM; code-health CLEAN; BLOCKER none.  
**Auditor:** Cursor, 2026-07-29 (same-turn re-probe).

---

## Verdict: **ACCEPT** (goal conditions met)

| Item | Result |
|---|---|
| A1 fail-closed (RC-131) | **ACCEPT** |
| A2 pin tip = TOTAL gamma (RC-132) | **ACCEPT** |
| A3 HVL dual-paint removed + locked | **ACCEPT** (UI); payload still computes unused `hvl` twin — residual, not a painted lie |
| Mechanical locks E-A..E-D | **ACCEPT** (fire + quiet controls present) |
| Live wall_state wire | **ACCEPT** (re-proven this turn) |
| Code-health BLOCKING 0 | **ACCEPT** (re-run `--check` PASS) |
| DOM “no dealer support on page” | **NOT re-proven by Cursor browser this turn** — static source + wire sufficient for ACCEPT; Claude’s Playwright claim not independently repeated |

---

## Same-turn evidence

### Live wire (`:8000`)
| Ticker | spot | call_wall | put_wall | call_state | put_state | match `wall_geometry_state` |
|---|---:|---:|---:|---|---|---|
| SPY | 735.655 | 750 | 740 | contains | **breached** | True |
| AAPL | 343.13 | 345 | 325 | contains | contains | True |

Keys present (post-restart). Note: Claude’s AAPL call-wall-340 breached snapshot was time-bound; current AAPL call wall is 345 (contains). SPY put breached still proves the state path.

### Static (index.html)
- GAMMA PIN tip: TOTAL gamma / Absolute Gamma; stale “net gamma” pin tip **absent**
- Ladder `t: 'HVL'` **absent**; `*.hvl` paint binds **[]**
- `kl_hvl` remains Net Γ peak (net book) — correct exemption
- Fail-closed: containment only behind `=== 'contains'`; else `γ concentration` / unavailable tip

### Chart
- Lean: breached → BREACHED; contains → DEALERS…; else `''` (no fall-through)

### Tests (this turn)
```text
pytest test_client_spot_single_faucet_v1 + test_levels_single_producer_v1 + test_terrain_engine_v1
→ 57 passed
code_health_panel.py --check → BLOCKING CLEAN, exit 0
TRACKED mypy 759 / orphans 164 (unchanged class — no rise claimed as regression)
```

Locks verified in suite: RC-131 contains-gate + fall-through negative control; RC-132 pin-net tip + `.hvl` bind ban + injections.

---

## Residuals (do not reopen ACCEPT)

1. **Dead producer twin:** `terrain_engine` still sets `hvl=pick_hvl_strike(...)` which equals `gamma_pin` on the wire (`hvl_eq_pin: True`). Not painted; lock bans re-bind. Optional cleanup: stop computing/shipping `hvl` or alias it explicitly as deprecated.
2. **Causal tip prose** (A4 optional): contains/breached tips still say “dealer hedging caps/buys/flips” — structure-honest enough for this goal; not locked.
3. **DOM:** Claude’s headless probe not re-run here; wire+static+locks carry the ACCEPT.

---

## Research / framing
RC-131 correctly treats v25’s degrade finding as the defect class. RC-132 correctly fixes pin tip + duplicate HVL *paint*. No working-side wall re-pick. Good.

`CLAIM:` A1–A3 + locks + live wall_state ACCEPT · `DONE:` audit v26 · `NEXT:` Decide burn / LP-01 per operator · `BLOCKER:` none
