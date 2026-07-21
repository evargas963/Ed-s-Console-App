# Console Rebuild Plan — CR v1 (2026-07-21)

**Status: PLAN — awaiting operator GO and Cursor review. No code in this document's scope has been written.**
Program ledger: `ACTIVE_PROGRAM.md` §CR. Research provenance: four-track deep review
2026-07-21 (free order-flow sources / intraday signal evidence / OSS console architecture /
options + cross-asset evidence), every load-bearing claim fetch-verified same day.

---

## 1. Verdict and scope

**Rebuild the console's decision layer; keep the data spine.**

- **Retires** (already demotion-approved by operator 2026-07-20, measured at chance):
  the 7-layer ML stack surfaces — horizon cards, fusion verdicts, decision bundle UI.
  Retirement is *by replacement*: each old surface stays until its replacement panel is live
  and validated; no big-bang cutover on a trading day.
- **Keeps**: Schwab ingest, canonical 1m machinery, SQLite, snapshots/chains, terrain module
  (TU program continues in parallel and CR-05a consumes its gamma sign), calibration
  logging, the operable-surface gate, world_* collectors.
- **Adds**: a streaming spine (bus + cache + writer), free order-flow feeds, an
  evidence-gated cockpit UI.

## 2. Evidence law (what this rebuild is allowed to claim)

1. **Flow explains; it does not predict.** Best-level OFI: contemporaneous OOS R² 65–84%
   on 1-min returns; forward 1-min R² **negative** (Cont-Cucuringu-Zhang, Quant. Finance
   2023, arXiv:2112.13213). All flow surfaces carry the literal label
   "explains, does not predict."
2. **Surviving intraday effects are mechanical and tail-concentrated**: dealer-gamma-
   conditioned late-day continuation (Baltussen et al. JFE 2021 — only when net gamma < 0);
   conditional first→last half-hour momentum (Gao et al. JFE 2018; survives only
   high-vol/high-volume/news regimes per post-publication replications);
   closing price-pressure overnight reversion (~85% of close-vs-3:59-mid deviation reverts
   by open; Bogousslavsky-Muravyev JFM 2023).
3. **Killed as predictors** (do not build; full list in ACTIVE_PROGRAM §CR):
   VPIN (Andersen-Bondarenko: zero incremental power vs volume+RV), TICK-extreme rules,
   VWAP-magnet, DIX thresholds, gap-fill percentages, 0DTE net-flow direction,
   minutes-scale cross-asset lead-lag, naive FINRA short-ratio reads.
4. **Every self-computed construct enters through the unproven register + PDCA gate**
   (CR-07). No tile renders a directional prompt before beating its placebo on our data.

## 3. Data acquisition (all $0 recurring; verified live 2026-07-21)

| Feed | Gives | Constraints | CR item |
|---|---|---|---|
| Schwab Streamer `LEVELONE_EQUITIES` (QOS 0 Express) | bid/ask/last + sizes, ~500ms conflated | no trade prints (TIMESALE dropped from new API); no condition codes | CR-01 |
| Schwab `CHART_EQUITY` | streaming 1m OHLCV | — | CR-01 |
| Schwab `NYSE_BOOK` / `NASDAQ_BOOK` | aggregated depth levels | conflated; per-symbol availability is subscribe-and-see | CR-01 (capture), CR-06 (use) |
| Alpaca free tier websocket | true IEX trade prints + quotes | 30 symbols; IEX ≈ 2% of tape — imbalance *ratios* usable, absolute volumes not | CR-02 |
| Existing: chains, world_* (DIX, vol indices, OCC, FINRA, CFTC) | regime context | daily cadence | already landed (TU-01) |
| Databento $125 signup credits | historical full-tape ticks, one-off | credits expire ~6 months | CR-08 |

Streamer capacity: 500 keys/connection ⇒ ~50 active names on L1+books **plus** ~450
additional constituent L1 subscriptions for internals (CR-04) fit one connection; if book
subscriptions consume keys faster than expected, internals move to a second app-level
stream or a reduced (~100-name) universe — decided by measurement in CR-01, not assumption.

**Operator actions required**: (a) GO word; (b) open a free Alpaca account (CR-02);
(c) one Databento signup (CR-08). Nothing else.

## 4. Target architecture

Patterns proven by NautilusTrader (bus/cache), freqtrade (typed-WS push), OpenBB
(widget manifest), OrderFlowMap (lightweight-charts + custom primitives). No new runtime
dependencies except `lightweight-charts` (Apache-2.0 + attribution notice) and the Alpaca
websocket client (or a ~100-line raw websocket implementation — decided in CR-02 review).

```
Schwab streamer ─┐                       ┌─ last-value cache (dict, write-before-publish)
Alpaca IEX ──────┼→ in-process topic bus ┼─ SQLite writer task (single, batched)
chain poller ────┘   (asyncio pub/sub,   ├─ aggregators (RVOL, dispersion, CVD, OFI)
                      topic strings)     └─ WS hub → browser (typed JSON, coalesce-to-latest,
                                             per-client bounded queue, dead-client reaping)
```

- **Bus**: ~100 lines asyncio; topics like `quote.SPY`, `print.SPY`, `bar1m.QQQ`,
  `internal.dispersion`, `system.health.schwab_stream`. Additive consumers; no implicit
  coupling.
- **Cache-then-publish**: new browser clients snapshot the cache, then ride deltas.
  Kills poll-to-hydrate.
- **SQLite**: WAL, `synchronous=NORMAL`, one writer draining the bus (commit every N rows
  or 250ms); raw prints/quotes retained **days** (delete-by-day), derived 1s/1m aggregates
  retained long-term. New tables: `stream_quotes_raw`, `stream_prints_raw`,
  `stream_agg_1s`, each with an explicit retention row in the ops doc.
- **WS contract**: `{"type":"bar_1m","sym":"SPY","data":{...}}`; client sends a
  subscription list; server coalesces quotes to 250–500ms UI frames. Existing SSE folds in;
  polling loops go to zero over CR-03.
- **Health first-class**: every feed publishes RUNNING/DEGRADED/STALE with
  last-message age; the UI renders feed state distinctly from market quiet. (Terrain's
  existing watchdog/fail-closed philosophy, applied to streams.)
- **Frontend**: grid shell + `panels.json` registry (panel = ES module + endpoint/topic +
  grid slot). index.html shrinks by subtraction as panels migrate; no build tooling.

## 5. Cockpit information architecture (sparse by design)

Practitioner-literature finding: professional cockpits are sparse — pre-computed context
plus one or two live confirmation streams.

| Zone | Content | Source |
|---|---|---|
| Main chart | candles + levels ON the chart (prior H/L/C, ON H/L, terrain walls/flip/KDS/HVP/LVP), VWAP as fair-value reference line, session volume profile + POC/VA right-margin | CHART_EQUITY + terrain + 1m history |
| Flow pane | CVD (Alpaca prints), snapshot-OFI + depth imbalance, live impact tile — labeled "explains, does not predict" | CR-02/CR-06 |
| Regime strip | NET GEX chip (exists), RVOL gauge (U-shape normalized), dispersion + breadth sparklines, VIX term-structure state | CR-04 + terrain + world_vol_index |
| Evidence tiles | late-day gamma-conditioned card (arms ≥15:15 ET when net gamma < 0 AND |move| large); conditional AM→PM momentum card (arms only high-RV/news days); closing-pressure reversion card (computes 3:59-mid vs close, states overnight expectation) | CR-05 |
| Tape | large-prints-only filter, auto-armed near marked levels | CR-02 |
| Health | per-feed state + ages | CR-01 |

Explicitly **not** built: book heatmap, footprint bars, TPO letters, DOM ladder —
skip-tier at minutes horizons per the architecture review.

## 6. Work items, dependencies, acceptance

Order is dependency-driven; each item is a separate commit round with real-seam tests
named in the commit prompt (seam rule), gate PASS, closeout GREEN.

| ID | Depends on | Deliverable | Acceptance (measured, not asserted) |
|---|---|---|---|
| CR-01 | — | streamer client + bus + cache + writer + health | a full RTH session captured with zero writer-queue overflow; feed-drop drill shows DEGRADED→STALE in UI within 10s; key-capacity measurement recorded |
| CR-02 | CR-01 | Alpaca prints + CVD + signing cross-check | CVD renders live; Schwab-signed vs IEX-signed imbalance correlation measured and recorded on ≥3 sessions |
| CR-03 | CR-01 | WS hub + panels.json shell + main chart panel | one legacy polling loop retired; chart panel byte-budget < 1/10 of equivalent legacy code; layout-contract tests |
| CR-04 | CR-01 | RVOL + dispersion + breadth aggregators & strip | each metric has an unproven-register row + a backfilled history from canonical bars where derivable; U-shape baseline proven against 20-day time-of-day means |
| CR-05 | CR-04, terrain | three evidence tiles | each tile's arming condition unit-tested both ways; each wired into the daily scorecard with its own placebo |
| CR-06 | CR-01/02 | flow instrumentation pane | impact coefficient recomputed live; "explains, does not predict" label contract-tested |
| CR-07 | CR-05 | promotion gate | mechanical: a tile without N sessions of scored history CANNOT render a directional prompt (fail-closed test proves it) |
| CR-08 | CR-02 | conflation-cost study | one report: signal correlation full-tape vs 500ms-conflated on SPY; informs CR-06 trust labels |

## 7. Risks and honest limits

- **Conflation**: 500ms snapshots undercount quote events exactly in fast tape; CR-08
  measures the damage instead of assuming it.
- **IEX sample bias**: 2% of tape; ratios only; the cross-check in CR-02 quantifies
  agreement before anything downstream trusts either source alone.
- **Streamer unknowns**: book-service symbol availability and effective key budget are
  subscribe-and-measure; CR-01 records them as facts before CR-04 sizes the internals
  universe.
- **Windows host + one process**: the bus is in-process by design; if ingest CPU ever
  contends with the UI (measured, not feared), the spine splits into a second process
  writing to the same WAL DB — the architecture permits it without redesign.
- **Evidence decay**: the three CR-05 effects are published; McLean-Pontiff decay applies.
  That is exactly why CR-07 exists — our own scorecard, not the papers, grants promotion.
- **0DTE blindness stands**: no free feed sees same-day-opened OI. The console states it
  (chip caveat) rather than pretending.

## 8. Rollout

1. CR-01/02 run **capture-only** for ≥3 sessions before any UI consumes them (data first,
   surfaces second — same discipline as the terrain scorecard).
2. New panels mount alongside legacy surfaces; a legacy surface retires only when its
   replacement has survived a week of live use without a defect ticket.
3. ML-stack surfaces retire at CR-03 (shell) since their replacement is context panels,
   not predictions — per the standing demotion decision.
4. Program reviews: after CR-03 and CR-05, a Cursor audit + Bugbot round each, same as the
   terrain bundles.
