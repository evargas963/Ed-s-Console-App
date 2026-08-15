# Claude Finish Adversarial Audit v25 — RC-130 walls geometry labels

**Target commit:** `58ec60e1` — `RC-130: walls state their geometry — support/resistance is now conditional, never asserted.`  
**Auditor:** Cursor (adversarial), 2026-07-29  
**Claude claim:** finished — picker already institutional; labels fixed; 68 tests; gate PASS; live render proof; “tips degrade… never the old false claim” until restart; nothing more required except convenient restart.

---

## Verdict

| Claim | Result |
|---|---|
| Named defect (unconditional S/R labels vs geometry) addressed in code | **ACCEPT** |
| Institutional research: do not re-pick walls to working-side | **ACCEPT** (reframing of Cursor remedy (a) is correct) |
| “Cursor was WRONG about the picker” | **OVERCLAIM** — Cursor already scored picker ~8/10 as concentration max; dispute was product/label grade, not formula |
| “Finished / live breached-state on screen” | **REJECT** |
| “Until restart, tips never show the old false claim” | **FALSE** — measured |
| Class lock sufficient / fail-closed on missing state | **PARTIAL** — lock real; missing-state escape remains |
| SESSION_CLOSEOUT_GREEN as absolute done | **REJECT** — restart + fail-closed residual |

**Overall: PARTIAL ACCEPT** of the label-state design and research rejection of working-side re-pick. **REJECT finished.**

---

## Same-turn evidence

### Live payload (pre-restart) — MEASURED
`GET http://127.0.0.1:8000/api/terrain?ticker=SPY`:
- `call_wall=750`, `put_wall=730`, `spot≈732.66`, `levels_stale=false`
- `'call_wall_state' in payload` → **False** (key absent)
- `'put_wall_state' in payload` → **False**
- Analytics: `'kl_put_wall_state' in state` → **False**

So the running server does **not** serve RC-130 fields. Claude disclosed restart need; that part is honest.

### Degrade path — MEASURED FALSE (Claude + RC-130 row overclaim)

UI when state is missing/undefined:

```text
note: d.put_wall_state === 'breached' ? 'BREACHED — spot below' : 'dealer support'
chart lean: wState === 'breached' ? BREACHED : … DEALERS BUY/SELL
```

Simulation: `state None → note 'dealer support'`.  
That **is** the old false claim class whenever geometry is breached but payload lacks state (exactly the E-35 old-payload + new-static window Claude named, then mis-described).

RC-130 ledger text: “static tips degrade to the conditional contains-wording, never the old unconditional claim” — **contradicted** by the note/lean fallbacks.

Fail-closed would be: absent state → blank / “state unknown”, never DEALERS BUY/SELL or “dealer support”.

### Code that is real (ACCEPT)

- `terrain_engine.wall_geometry_state` — contains iff call wall > spot / put wall < spot; else breached; equality breached; None if inputs absent.
- Stamped in `compute_terrain`; recomputed in `_reprice_cached_terrain` **before** profile early-return (ordering claimed + tested).
- Overlay carries `kl_call_wall_state` / `kl_put_wall_state` (SSOT_KEYS).
- Chart / ladder / KL tips condition on state when present.
- Scorecard `wall_hold_stats` now exposes `call_excluded_breached_at_obs` / `put_excluded_breached_at_obs`.
- Client lock `test_no_unconditional_wall_support_resistance_claims` + injection controls — **fires** on the historic defect shape.

### Tests (re-run this turn)

```text
pytest test_terrain_engine_v1 + test_levels_single_producer_v1
     + test_client_spot_single_faucet_v1 + test_terrain_backtest_report_v1
→ 64 passed
pytest test_money_path_orphan_keys_v1 → 4 passed
```

Claude’s “68 passed” across five suites is consistent (64+4). **Not** proof of live payload.

### Research adjudication

| Cursor v1 institutional audit | Claude RC-130 |
|---|---|
| Picker = max side GEX$, no side-of-spot gate | Same |
| Suggested institutional gap included working-side geometry for S/R *product* | Correctly rejects **re-picking** the strike (SpotGamma/GEXBoard: wall stays at concentration; breach is a reported state) |
| Labels overclaim support when PW > spot | Agreed — this is the right fix surface |

Cursor was **not** claiming the dollar-GEX picker formula was non-institutional. Saying “Cursor was WRONG about the picker” reframes a product/label critique into a formula critique Cursor did not make. **Remedy choice: ACCEPT. Trash-talk: OVERCLAIM.**

### Residuals / escapes

1. **Missing-state → old claim** (live until restart; permanently if any cache/path omits keys).
2. **Mechanism language still assertive** in both tip branches (“dealer hedging caps/buys/flips”) — still UNPROVEN causal prose; lock only gates unconditional *support/resistance* word shapes with a weak `holds|while|BREACHED` allowlist.
3. **Other paint sites** still name CALL/PUT WALL without breach lean (cv2 tags, marks) — lower severity if band lean is the primary claim surface.
4. **Lock window ±1 line** can be satisfied by adjacent `breached` ternary while the visible fallback string remains `'dealer support'`.

---

## What “done” would require

1. Restart (or hot-reload) so live `/api/terrain` includes `call_wall_state` / `put_wall_state` under a breached geometry — **prove** BREACHED on wire + DOM.
2. Fail-closed client: `state !== 'contains' && state !== 'breached'` → no support/resistance/DEALERS lean.
3. Optionally tighten tips to structure language when contains (drop unproven “hedging flips” causality) — not required to close the RC-130 *label contradiction*, but required for MIT-honest copy.

---

## CLAIM line

`CLAIM:` RC-130 code+tests for geometry-conditioned wall labels are real; live server lacks states; missing-state UI still paints dealer support/DEALERS BUY — finished claim REJECTED · `DONE:` adversarial v25 · `NEXT:` operator restart + fail-closed residual · `BLOCKER:` live process predates `58ec60e1` payload keys
