# SHIP CONFIRMATION — static/chart.html (mission one-faucet-closeout-v1, RC-227)

**Surface:** static/chart.html (approved design surface; data-integrity kills only, zero visual
redesign — every changed element keeps its approved style).

## RENDERED-FRAME evidence

Live rendered-DOM verification against the restarted console (PID 24808→17188, post-kill code),
executed in the embedded browser at http://127.0.0.1:8000/chart on 2026-08-04 ~01:2x CT via
`javascript_exec` against the painted page (the rendered DOM, not source):

```
bars_drawn: 3001                     engine_levels: 19
computeDaily_pd_dead: true           enginePD_exists: true
pd_menu: {state: auto, values: 3}    side_sums_consumed: true
strip_rows: 25                       charm_row_text: "CHARM"
charm_locked_text_present: false     strip_src_text: "STALE 14191s · quote.last"
legend_text: "SPY 758.36 +11.54 (1.55%) vs yday close"
```

## FEATURE-BY-FEATURE against the approved surface

| feature | approved behavior | rendered proof |
|---|---|---|
| Candles + levels chart | unchanged | 3001 bars drawn, 19 engine levels rendered |
| Prior-day lines (PDH/PDL/PDC) | same style, ENGINE-only values (B3) | pd menu carries 3 engine values; `daily` has no pd keys (`computeDaily_pd_dead: true`); `enginePD` accessor live |
| Big legend change-vs-close | engine PDC basis | "SPY 758.36 +11.54 (1.55%) vs yday close" renders from `enginePD().pdc` |
| FORCES strip GEX/OV | server-aggregated `today_side_sums` (STRIP kill) | `side_sums_consumed: true`; 25 strip cells render |
| FORCES strip CHARM row | real numbers per the operator's charm vote-gate revocation | CHARM row present; the "renders after the operator charm vote" lock text is GONE from the rendered page |
| Spot pill honesty (RC-225) | age/source visible, stale says STALE | "STALE 14191s · quote.last" rendered after-hours — honest staleness on the face |
| Absent data | renders absent, never fabricated | pd values render only from `rawLevelDefs`; empty engine set shows "no data this session" |

**Locks binding this surface:** `tests/test_levels_single_producer_v1.py` — 27 passed this
session (B3 no-client-compute, strip no-re-aggregation, charm not vote-locked, `#f-src`
visible-consumer binding, side-sums server contract, 410 retirement, raw precision).

**Quiet gate:** `python -m tools.ed_server_warn_quiet_window` verdict recorded in
`reports/ed_server_warn_quiet_window_latest.json` (final run after the `quote_source_detail`
scope registration; the two prior FAILs — agent-env DB redirect, unregistered payload key —
were real findings, fixed, and are part of this landing).
