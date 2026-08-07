# Charm closeout — loop log v1 (mission: charm-closeout-no-soft-stop, 2026-08-01)

Contract: IMPLEMENT + PROVE + SELF-ATTACK until surface PASS or honest FAIL. PARTIAL banned
for in-scope guns. Forbidden excuses honored: no "backgrounded rAF", no "markup implies paint",
no "_lastData implies Drift", no recycled numbers — every number below is from THIS mission's
command output.

## LOOP 1 — R9 fix + locks + bundle

- **Identify:** Cursor v4 residual — `#dr-of-confirm` judged CONFIRM/DIVERGENCE against a
  BOOKLESS `d.charm_direction` (the unlabeled-direction defect through a side door).
- **Fix:** `static/index.html` of-confirm gate — `if (!d.charm_scope) return 'MIXED';` BEFORE
  the direction is consulted. Terrain ct cells already read `t.charm_book_scope` with an
  explicit `book?` unknown branch.
- **Locks added:** `test_order_flow_confirm_requires_a_labeled_charm_book`,
  `test_terrain_cells_never_pretend_a_book_they_were_not_given`.
- **Audit:** bundle **98 passed**; adversarial dirty-book `scalar 420.21 buying used 2
  per 420.21 parity_ok True`. Server `server:app` PID 50756 up on :8000.

## LOOP 2 — Drift paint: the harness excuse dies, then the occlusion excuse dies

- **Attempt A (Chrome, visible):** `--remote-debugging-port=9223` + CDP
  `Page.bringToFront` + the page's own `acceptAndScheduleMoneyPathRender` → `accept:true`
  but DOM unchanged. Instrumented `window.__edMoneyPathLatency`:
  `{sched: 14, flush: 0, renders: 0, pending: true}` and a direct
  `requestAnimationFrame` probe returned **rafFired: false** — the window reported
  `visibilityState: "visible"` while Chrome had suspended its renderer (native window
  occlusion). Relaunch with `--disable-features=CalculateNativeWinOcclusion
  --disable-backgrounding-occluded-windows --disable-renderer-backgrounding` still
  `rafFired: false` (counters 14→18 proved the kill had failed and the same occluded
  window answered).
- **Attempt B (Edge, operator order "use edge instead"):** msedge on port 9224, same
  flags. `{sched: 5, flush: 3, renders: 3, skips: 0, last_src: "rest_manual",
  pending: false}`, **rafFired: true** — the render loop runs.
- **R6 PROVEN (painted DOM, visible Edge):** `.kl-name.charm` →
  `"Charm Drift exp 08-03 · 750.00 · Bearish · +5.79 · -204K Δ/day"`, scope span
  `"exp 08-03"`. `#dr-of-confirm` → `"MIXED"`.
- **R8 PROVEN:** ct cells only paint under `ed-terrain-mode` (index.html:13730 gate).
  Clicked the page's OWN `#cv2-tab-terrain` via CDP → `ct-ccharm = "750.00 · full chain"`,
  `ct-pcharm = "730.00 · full chain"` (label READ from `charm_book_scope`).

## LOOP 3 — Attacks + full re-run

- **N1 (bookless direction injection, live DOM):** fetched real `/api/state`, deleted
  `charm_scope`/`charm_expiry`, pushed through the REAL accept path. Drift row →
  `"Charm Drift 750.00 unlabeled +5.79 —"` (NO direction, NO Δ/day, no scope span);
  `#dr-of-confirm` → `"MIXED"`. Restore with the labeled payload →
  `"Charm Drift exp 08-03 750.00 Bearish +5.79 -204K Δ/day"`. FAIL-CLOSED CONFIRMED.
- **N2 (bookless walls on the wire, live DOM):** intercepted `window.fetch`, stripped
  `charm_book_scope` from `/api/terrain` responses, drove `EdCv2Terrain.refresh()`
  (interception hits=1) → `ct-ccharm = "750.00 · book?"`, `ct-pcharm = "730.00 · book?"`.
  Restored fetch → `"750.00 · full chain"`. NEVER pretends a book it wasn't given.
  (First N2 pass showed `full chain` — the `inflight` guard had swallowed the refresh;
  re-ran with a retry loop and a hit counter before claiming anything.)
- **R4 (live wire):** `/api/analytics/light?ticker=SPY` → `charm_net: -204272.62,
  charm_scope: "single_expiry", charm_expiry: "2026-08-03"`. Raw SSE frame from
  `/api/analytics/light/stream` captured: `"charm_net": -204272.62,
  "charm_direction_display": "Bearish", ..., "charm_scope": "single_expiry",
  "charm_expiry": "2026-08-03"` — the label travels ON the wire with the number.
- **R5 (four tickers, live):** SPY −204,275.89 / QQQ −192,144.38 / IWM −143,607.13 /
  MSFT −38,908.47 — all four fields (`charm_net/direction/scope/expiry`) present on every
  ticker, scope `single_expiry`, expiry `2026-08-03`.
- **R10 (strip-locus census):** repo-wide `charm_net` scan (worktree snapshot excluded);
  dispositions in the closeout report — display/API loci ALL labeled; the remaining
  bookless loci are the ML feature column (db.py/signal_types.py/feature lists) and a
  magnitude-only normalization (server.py:7001 → hedging-flow input, no book claim
  published); the signals path's charm VOTE is gated off (tests/test_charm_vote_gate.py,
  re-run green this loop).
- **Re-run:** bundle (+ vote gate) **103 passed**; adversarial
  `scalar 420.21 buying used 2 per 420.21 scope single_expiry 2026-08-03 parity_ok True`,
  `decomp_ok True`, now= pins ×3 `now_kw True`, T-floor `eq_floor True`, doc flags clean.
  The "server strip sim: forwarded_has_scope False" line is the STATIC demonstration of the
  old four-key hazard (kept deliberately); the live check `server_forwards_scope_from_raw
  True` proves the fix.

## Verdict

SURFACE **PASS** — every in-scope gun proven on painted DOM in a visible browser or on the
live wire, fail-closed under both injection attacks, locked by 103 green tests.

## Post-verdict stop-guard round (same session)

The guard caught two honest gaps in the CLOSED stamp: the RC-184 fix cell still carried the
old "PARTIAL … proof pending" opener, and no test bound the `#cv2-tab-terrain` visible
consumer. Both fixed: fix cell rewritten (CLOSED, no evidence owed);
`test_terrain_tab_is_the_bound_visible_consumer_of_the_ct_charm_cells` added — bundle
**104 passed**, `stop_guard.py` exit 0.

SURFACE PASS ≠ charm VOTE. Decide WAIT. Admissions untouched.
