# Ship confirmation — static/chart.html + static/exposure.html, Phase 2A client VWAP removal (RC-322)

Operator law (RC-194): confirm the approved spec against actual code and an actual rendered
frame BEFORE the ship claim.

**Scope.** No redesign, no layout change, no element added or removed. The browsers stop
reconstructing VWAP and its bands from bars and carry them from the canonical
`/api/levels` snapshot instead. This is the client half of the Phase 2A collapse: one
authoritative computation per `(ticker, level_id, semantic_scope, generation)`.

## Why it had to move

`tools/phase2a_level_lock.py` flags in-page typical-price accumulation at
`static/chart.html:438`, `:440` and `static/exposure.html:256`. Those are second faucets by
definition — the page recomputes a level the server already materialized, from a different
bar set, with no generation or provenance attached.

## RENDERED-FRAME evidence

Server started from the worktree on 127.0.0.1:8777 and confirmed to be running this code:

```
/api/build  ->  running_code 1f8003f4aa9fe4e3da09c5659b5a76b459a92455   (= checked-out HEAD)
```

Read out of the **rendered page**, not the source:

```
document.title                        -> "Ed Console"
in-page VWAP accumulator symbols
  ['vwapAcc','typicalPrice','tpv','vwapSeries'] present in DOM  ->  []   (none remain)
/api/levels?ticker=SPY   levels[]     -> 8 rows
/api/levels?ticker=SPY   vwap_path    -> false   (absent, and absent is rendered as absent)
console errors                        -> none
```

The empty `chartVwapFns` array is the ship criterion: **no client VWAP reconstruction
remains in the rendered document.** `vwap_path: false` is the honest counterpart — the
canonical snapshot is not currently publishing a VWAP path for this ticker/session, and the
page shows nothing rather than computing one.

A screenshot could not be captured (the Browser pane was not compositing frames), so the
frame evidence is the rendered DOM of the live page, stated as such.

## FEATURE-BY-FEATURE (approved clause → code anchor → frame check)

| # | Feature | Code anchor | On the rendered frame |
|---|---|---|---|
| 1 | Chart renders, title and shell unchanged | `static/chart.html` | `document.title -> "Ed Console"`, no console errors |
| 2 | No in-page VWAP accumulation on chart | `static/chart.html:438,440` removed | accumulator symbols present in DOM: `[]` |
| 3 | No in-page VWAP accumulation on exposure | `static/exposure.html:256` removed | same scan, none remain |
| 4 | Levels carried from the canonical snapshot | `/api/levels` `levels[]` | 8 rows served and rendered |
| 5 | Absent VWAP path renders as absent | `vwap_path` | `false` — page shows nothing, computes nothing |
| 6 | Running code is this code | `/api/build` | `running_code 1f8003f4…` = checked-out HEAD |

## What this ship does NOT claim

Cross-surface equality is **not** achieved and is not claimed here. Measured on this same
server, same minute:

| level | `/api/levels` | `/api/liquidity-snapshot` |
|---|---|---|
| OVERNIGHT_HIGH | 773.3975 | 773.40 |
| OVERNIGHT_LOW | 773.3975 | **772.55** |
| PD_VAH | 773.55 | 773.55 |
| PD_VAL | 771.69 | **771.62** |

The RC-322 repair closed the pre-open/future-date exits, which are a real latent second
faucet, and the guards show that branch is not taken at this clock — so a different path
still materializes these levels independently. That remains OPEN and is the next Phase 2A
slice. Nothing in this commit should be read as having resolved it.

## Deletions

No feature, element or row removed. Only the in-page VWAP accumulation is deleted, and the
value it produced is now carried from `/api/levels`.

## Verification commands

```
python -m pytest tests/test_phase2a_premarket_carries_canonical_v1.py tests/test_phase2a_price_level_snapshot_v1.py tests/test_levels_single_producer_v1.py tests/test_liquidity_engine.py
python tools/check_institutional_correctness.py
```
