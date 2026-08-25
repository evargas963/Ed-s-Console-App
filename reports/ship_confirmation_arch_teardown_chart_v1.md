# Ship confirmation — static/chart.html (PR #192: absolute-gamma rename + RC-305 qualifiers)

**Law:** RC-194 — confirm the approved spec against actual code and an actual rendered frame BEFORE the ship claim.
**Surface:** static/chart.html (approved design surface). Related surfaces exercised the same session: static/exposure.html, static/index.html (bindings locked by tests below).
**Changes shipped:** commit e25e64e1 (RC-292/RC-303 absolute-gamma rename, PIN CAND row, ·ABSΓ wall tag) and commit 189ec3e5 (RC-305 qualifier delivery: levelProvenanceTitle tooltips, sideSumsBasisText spot-ref).

## RENDERED-FRAME

Rendered live on 2026-08-24 against a worktree server (`uvicorn server:app` on 127.0.0.1:8010, `ED_CI_OFFLINE=1`, no Schwab token — the charter's fail-closed offline state). Observed in the browser, not inferred:

- The page loads and paints: header `SPY · UNAVAILABLE`, banner `Terrain unavailable — stand aside.`, status line `spot — waiting for /api/spot · regime UNAVAILABLE · 0×1m bars` — every absence states itself; no fabricated numbers anywhere in the frame.
- **Zero JavaScript console errors** on chart.html — the renamed bindings and the two new renderers execute clean in the real page.
- Network: /api/forces, /api/spot, /api/bars1m, /api/terrain, /api/terrain/strikes, /api/levels all 200 with fail-closed absence payloads (`today_side_sums: null`, `levels_stale: true`, 0 level rows on the empty worktree DB). The one 500 (/api/liquidity-snapshot) is the documented missing-token offline condition and returns a loud error payload, not silent data.
- DOM assertions on the rendered document: `gamma_pin` appears NOWHERE in the chart DOM and nowhere in the exposure DOM; the literal `GAMMA PIN` label is gone; `ABS GAMMA` and `PIN CAND` are present in the page source (ladder/levels rows).

## FEATURE-BY-FEATURE

| Feature | Rendered evidence (executed in the live page) | Locking test |
|---|---|---|
| Ladder/levels rename `GAMMA PIN` → `ABS GAMMA` | `ABS GAMMA` present in rendered source; `GAMMA PIN` absent; `gamma_pin` absent from the whole DOM | test_semantic_faucet_definition_scope_v1 (UI end-to-end: zero gamma_pin in static/) |
| New `PIN CAND` qualified-claim row | `PIN CAND` present in rendered source; payload leaf `kl_pin_candidate` served (null offline = withheld, blockers named) | test_semantic_faucet_definition_scope_v1 (qualification gates + overlay wiring) |
| Spot-basis on FORCES strip (RC-305) | Live call `sideSumsBasisText({spot_basis: 645.2})` → `" · spot ref 645.20"`; `sideSumsBasisText({})` → `" · spot ref unknown"`; `sideSumsBasisText(null)` → `""` — value, honest-absence, and no-sums cases all correct in the page | test_levels_single_producer_v1::test_strip_states_the_server_spot_basis (node-executes the real function) |
| Level tooltip provenance (RC-305) | Live call `levelProvenanceTitle("prior-day low", {session_scope:"RTH", vendor_basis:"1m bars (bars1m); schwab pricehistory/stream basis"})` → `"prior-day low · RTH session · basis: 1m bars (bars1m); schwab pricehistory/stream basis"`; bare provenance → `"prior-day low · session scope unknown · vendor basis unknown"` — fail-closed, no defaults | test_levels_single_producer_v1::test_chart_level_titles_carry_session_scope_and_vendor_basis |
| Exposure charm error line (RC-305, companion surface) | `charm failed` idiom present in rendered exposure source; charm section renders; zero gamma_pin in exposure DOM | test_exposure_tab_v1::test_charm_error_is_stated_on_the_charm_line |
| Refuted sticky-pin tooltips replaced | rendered source carries no magnet-claim tooltip text (gamma_pin family absent wholesale) | test_semantic_faucet_definition_scope_v1 |

**Honest limit:** the offline worktree has no bars/chain data, so populated-ladder pixels (an actual ABS GAMMA row with values, a tooltip on a real level) could not be rendered this session — those value paths are exercised by the node-executed binding tests above, which run the real extracted page functions on served-shape fixtures. What the frame proves directly: the page executes the shipped code without a single console error, every changed renderer produces the specified strings in the live page, and every absence renders as stated absence.

Suites at ship: chart/levels battery 184 passed — reproduce with `python -m pytest tests/test_levels_single_producer_v1.py tests/test_terrain_engine_v1.py tests/test_institutional_key_levels.py tests/test_client_spot_single_faucet_v1.py tests/test_pinning_score_needs_a_pin_v1.py tests/test_semantic_faucet_definition_scope_v1.py tests/test_single_producer_batch_f02_f13_v1.py -q`; RC-305 locking suites 49 passed — `python -m pytest tests/test_levels_single_producer_v1.py tests/test_exposure_tab_v1.py tests/test_forces_provenance_v1.py -q`; full suite 6,048 passed — `python -m pytest tests/ -q --ignore=tests/archive`.
