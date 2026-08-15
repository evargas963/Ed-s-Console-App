# Charm 100% surface proof — v1 (operator order "i need charm 100%", 2026-08-02)

**Scope:** RC-184/RC-185 completion — labeled charm surfaces end-to-end. NOT a Decide VOTE;
charm approval NOT REQUESTED, NOT GRANTED; admissions untouched.

## Live proof (real `server:app` on 127.0.0.1:8000, started AFTER the code landed)

Server PIDs this session: 8800 (first pass), 40188 (restart on the B_light fix); both started
and stopped by this verification — no pre-existing operator server touched.

### API JSON — every path labeled (captured live this turn)

| Path | Evidence |
|---|---|
| `/api/state?ticker=SPY` (Tier C_analytics) | `charm_net: -204756.23, charm_direction: "selling", charm_scope: "single_expiry", charm_expiry: "2026-08-03"` |
| `/api/analytics/state?ticker=MSFT` | `charm_net: -38140.63, charm_scope: "single_expiry"` (has_scope true) |
| B_light SSE → page `_lastData` | `{tier: "B_light", scope: "single_expiry", expiry: "2026-08-03", net: -204756.23}` |
| `/api/terrain?ticker=SPY` | `call_charm_wall: 750.0, put_charm_wall: 730.0, charm_book_scope: "full_chain"` |

### Rendered DOM (live browser on :8000)

| Surface | Evidence |
|---|---|
| cv2 Greek tile (`cv2-g-charm-wrap`) | title = `"Charm drift — book: selected expiry 2026-08-03 (charm_scope from the API; RC-184)"` |
| Terrain cells `ct-ccharm` / `ct-pcharm` | `"500.00 · full chain"` / `"450.00 · full chain"` — label READ from `charm_book_scope` |
| Served `/` HTML | fail-closed gate present (`const charmLabeled`), notes carry `charm wall · full chain`, Charm Drift scope span present |
| Served `/chart` HTML | `FULL-CHAIN book` declaration + dynamic `T.charm_book_scope` read |

### The fourth strip locus, found LIVE and fixed

The weekend console runs SSE-primary on the **B_light** plane. Its enumerated key list
(`planes/context_light.py`) carried `charm_net` with NO book — the page's fail-closed gate
correctly rendered `unlabeled`, which is how the strip was caught. `charm_scope`/`charm_expiry`
now travel wherever `charm_net` travels; locked by
`test_light_plane_carries_the_book_label_with_the_number`.

A second false lead is recorded for honesty: a **localStorage snapshot cache** replayed a
pre-fix payload after reload; cleared, and the live wire was then provably clean.

## Named external blocker (the ONLY remainder)

**Key Levels "Charm Drift" row + levels-list notes DOM capture**: the console's money-path
renderer runs on a `requestAnimationFrame` loop, and the verification harness keeps the browser
pane backgrounded — browsers suspend rAF for hidden pages, so `lastFullRenderSource` stays
`init` across reloads while the DATA provably arrives (`_lastData.charm_scope =
"single_expiry"`, captured live). Fronting the tab, visibility spoofs, rAF shims and the page's
own gate-reset were all tried this turn; the harness re-hides the pane between calls. An
operator-visible browser renders this loop normally — one glance Monday confirms the row, whose
markup, label logic and fail-closed gate are in the SERVED html (proven) and test-locked.

## Dual `now=` — pinned (RC-185)

Both production call sites pass `now=` from the single clock authority `time_et.now_et`:
`server._fetch_state` → `compute_net_charm(..., now=_charm_clock())`, `terrain_engine` →
`compute_charm_by_strike(..., now=_charm_clock())`, plus the `/charm` debug route. Locked by
`test_both_production_call_sites_pin_the_shared_clock`.

## Soft residuals — closed

1. **Fail-closed publish**: charm_net with no `charm_scope` renders `unlabeled` (Key Levels row
   AND cv2 tile), never a direction. Locked by `test_ui_fails_closed_when_the_book_label_is_missing`.
2. **Labels follow the data**: `ct-ccharm`/`ct-pcharm` and chart tips READ `charm_book_scope`;
   locked by `test_surfaces_read_charm_book_scope_from_the_payload`.
3. **Secondary surfaces**: cv2 tile labeled (live-proven); order-flow `charm_direction`
   consumer: OUT-OF-SCOPE — feature plumbing, not an operator display; unchanged semantics.
4. **In-process lock**: producer harvest → MarketState → `_ms_to_dict` e2e test (real chain).

## Re-attack + counts (this turn)

```
pytest charm+desk+completeness bundle ......... 96 passed
scratchpad/_charm_adversarial_v2.py ........... dirty fixture 420.21 buying used=2 parity_ok True
                                                decomp_ok True · doc flags clean
```

Reproduce:
```powershell
$env:PYTHONPATH = (Get-Location).Path   # run from the repo root
.venv\Scripts\python.exe -m pytest tests/test_charm_scope_surface_v1.py tests/test_charm_sign_finite_difference.py tests/test_charm_by_strike_v1.py tests/test_action11_5_compute_net_charm_fail_closed.py tests/test_centralization.py tests/test_desk_store_v1.py tests/test_rth_completeness_check_v1.py -q
.venv\Scripts\python.exe scratchpad\_charm_adversarial_v2.py
.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000   # then GET /api/state?ticker=SPY
```

## t13 — MONEY-PATH usable in app (board item, PROVEN 2026-08-04)

Board bar: charm must be trader-usable in the app — real numbers on decision surfaces, no
LOCKED theater — not merely CHARM_DONE at the formula. Proven against the LIVE operator
console (PID 37528, up since 08:18 CT) via headless Chrome CDP, same-moment API comparison:

| Surface (rendered DOM) | Evidence |
|---|---|
| `/chart` FORCES strip | `CHARM \| -268K \| · \| -2.3M \| banked 2026-08-03→2026-08-04` — matches `/api/forces` `charm_below -267913.79 / charm_above -2342827.64` captured in the same probe run |
| `/chart` Charm walls family | `__edChart.menu.charmw = {state:"on", values:2}` — terrain walls 758.0 / 750.0 served and drawable, default ON (RC-199) |
| `/exposure` charm pill + gates line | pill class `pill on` (honest-lamp `gate` class removed because fields serve); `gatekeepers 31 · charm -268K / -2.3M sh/day · full_chain_banked` |
| Theater scan | `/LOCKED\|APPROVAL\|PENDING VOTE/i` absent from both surfaces' `document.body.innerText`; source scan of chart/exposure/index/server charm lines found only historical RC-199 comments |

t13 required NO code change: the money path was landed by one-faucet-closeout-v1 + RC-199
(strip row, walls family ON, exposure annotation in sh/day). This section is the rendered-DOM
proof that closes the board item.

Reproduce:
```powershell
node "$env:TEMP\claude\C--Users-evarg-Documents-Trading-EdWebConsole\<session>\scratchpad\t13_charm_dom_probe.js"   # or any CDP probe of #f-grid / #ov-charm / #gates on 127.0.0.1:8000
curl "http://127.0.0.1:8000/api/forces?sym=SPY"   # charm_below/charm_above/charm_book_scope
```
