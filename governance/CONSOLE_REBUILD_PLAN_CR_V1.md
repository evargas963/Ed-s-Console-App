# Console Rebuild Plan — CR v1.2 (2026-07-21)

**Status: PLAN v1.2 — consensus round 2 objections (P1, P4, P5, P9, P10 — all stale
prose contradicting v1.1 laws) resolved with Cursor's exact conversion edits.
Round 3 = co-sign request. No code written. Implementation awaits operator GO on a
consensus-stamped version.**
Program ledger: `ACTIVE_PROGRAM.md` §CR. Research provenance: four-track deep review
2026-07-21 (free order-flow sources / intraday signal evidence / OSS console architecture /
options + cross-asset evidence), every load-bearing claim fetch-verified same day.

**v1.1 changes (all from the Cursor review):** separate `stream_capture.db` is a CR-01
acceptance requirement (RC-6 lesson — BLOCKING in v1.0); split-process hatch rewritten
(capture daemon, never a second writer on ed_console.db); CR-01 acceptance gains bounded
queue + drop/parse-latency metrics + a REST/streamer/terrain contention matrix; CR-03
rescoped (retire polling + demote ML DOM first; panels registry and volume profile
deferred behind the capture gate); capture-only ≥3 sessions is a MECHANICAL gate; ML
surfaces are demoted/hidden at CR-03 and hard-deleted only after replacements clear CR-07
plus a live week; published effect rates (e.g. the closing-reversion paper rate) may be
cited in §2 of this plan ONLY — never in UI copy or program tables — until our own
scorecard reproduces them; CR-05 arming thresholds must be pre-registered before first
arming; CR-06 trust labels wait on the CR-08 conflation study and carry window/leakage
rules; streamer key budget assumed OVER 500 for L1+dual-books+internals until measured —
sentinel-first books; single bar authority named (canonical 1m stays authoritative,
CHART_EQUITY is display-only until reconciled — RC-14 class); any tile that shapes a
TRADE goes through decision-path admission (`decision_gate.py`).

---

## 1. Verdict and scope

**Rebuild the console's decision layer; keep the data spine.**

- **Retires** (already demotion-approved by operator 2026-07-20, measured at chance):
  the 7-layer ML stack surfaces — horizon cards, fusion verdicts, decision bundle UI.
  They are **demoted/hidden at CR-03**; **hard-deleted only after their replacement
  panels clear CR-07 plus a live week (§8.3)**. No big-bang cutover on a trading day.
- **Keeps**: Schwab ingest, canonical 1m machinery, SQLite, snapshots/chains, terrain module
  (TU program continues in parallel and CR-05's late-day tile consumes its gamma sign),
  calibration logging, the operable-surface gate, world_* collectors.
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

Streamer capacity (v1.1, per Cursor review): the v1.0 arithmetic was NOT safe — if each
book service consumes its own key, 50×L1 + 50×NYSE_BOOK + 50×NASDAQ_BOOK + 450×L1
internals = 600 > 500. Until CR-01 measures the real accounting: **sentinel-first books**
(SPY/QQQ/IWM only), Alpaca's 30-name overlap carries print-level flow, internals universe
expands only after the measured key cost is recorded.

**Operator actions required**: (a) GO word; (b) open a free Alpaca account (CR-02 —
eligibility/TOS for the free IEX feed is VERIFIED AT CR-02 START, not assumed; if the free
tier requires conditions we can't meet, CR-02 re-plans before any dependent work);
(c) one Databento signup (CR-08). Nothing else.

**Streamer ownership (self-audit addendum)**: Schwab allows limited concurrent streamer
sessions per account. The capture spine becomes the ONLY streamer owner in the system;
any future component wanting streamed data subscribes to the bus, never opens a second
Schwab stream. Today's app uses REST quotes only, so there is no existing conflict — this
rule prevents one.

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
  coupling. Every queue is BOUNDED with an explicit drop policy (coalesce-to-latest for
  quotes, never for prints) and drop counters exported to the health panel.
- **Cache-then-publish**: new browser clients snapshot the cache, then ride deltas.
  Kills poll-to-hydrate.
- **Storage (v1.1 — RC-6 lesson, was BLOCKING)**: raw streams NEVER touch
  `ed_console.db`. A dedicated **`stream_capture.db`** (WAL, `synchronous=NORMAL`) holds
  `stream_quotes_raw`, `stream_prints_raw`, `stream_agg_1s`; one writer drains the bus
  (commit every N rows or 250ms); raw retained **days** (delete-by-day), 1s aggregates
  long-term. Research/console reads ATTACH it read-only. The operational DB grows by
  zero bytes from this program.
- **Bar authority (v1.1, RC-14 class)**: canonical 1m in `ed_console.db` REMAINS the
  single bar authority for every computation and study. `CHART_EQUITY` streamed bars are
  display-only until a recorded reconciliation proves them equivalent; no module may
  consume both.
- **WS contract**: `{"type":"bar_1m","sym":"SPY","data":{...}}`; client sends a
  subscription list; server coalesces quotes to 250–500ms UI frames. Existing SSE folds in;
  polling loops retire incrementally from CR-03 onward (CR-03 acceptance requires ≥1;
  zero-polling is the CR-03b/CR-06 end state, not a CR-03 claim).
- **Health first-class**: every feed publishes RUNNING/DEGRADED/STALE with
  last-message age; the UI renders feed state distinctly from market quiet. (Terrain's
  existing watchdog/fail-closed philosophy, applied to streams.)
- **Frontend (v1.2, per consensus P5)**: CR-03 ships a plain grid shell + the main chart
  module WITHOUT `panels.json` — no registry indirection before capture is proven. The
  registry (panel = ES module + endpoint/topic + grid slot) lands in **CR-03b**, matching
  §6. index.html shrinks by subtraction as panels migrate; no build tooling.

## 5. Cockpit information architecture (sparse by design)

Practitioner-literature finding: professional cockpits are sparse — pre-computed context
plus one or two live confirmation streams.

| Zone | Content | Source |
|---|---|---|
| Main chart | candles + levels ON the chart (prior H/L/C, ON H/L, terrain walls/flip/KDS/HVP/LVP), VWAP as fair-value reference line; session volume profile + POC/VA right-margin **(CR-03b, deferred per §6)** | CHART_EQUITY (display-only until reconciled) + terrain levels + canonical 1m history (sole computation authority) |
| Flow pane | CVD (Alpaca prints), snapshot-OFI + depth imbalance, live impact tile — labeled "explains, does not predict" | CR-02/CR-06 |
| Regime strip | NET GEX chip (exists), RVOL gauge (U-shape normalized), dispersion + breadth sparklines, VIX term-structure state | CR-04 + terrain + world_vol_index |
| Evidence tiles | late-day gamma-conditioned card (arms ≥15:15 ET when net gamma < 0 AND move exceeds the pre-registered bound — constant lives in the unproven register per CR-05, never post-hoc); conditional AM→PM momentum card (arms only high-RV/news days, thresholds likewise pre-registered); closing-pressure reversion card (computes 3:59-mid vs close; mechanism words only per §9) | CR-05 |
| Tape | large-prints-only filter, auto-armed near marked levels | CR-02 |
| Health | per-feed state + ages | CR-01 |
| Coach layer (operator directive 2026-07-22: "tooltips or messages on the graph along the way... until muscle memory kicks in") | hover tooltip on every drawn level/zone — what it is, why it sits there (strike mass), what dealers do there, and its proven/unproven state; a narrator strip showing the current terrain-read headline; on-chart event badges when price tests/crosses a level ("3rd test of call wall — pressure building"); a learning-mode toggle (verbose ↔ quiet). NO new prose generators: coach copy is sourced from the deterministic `terrain_read` headline/lines and the `level_crosses` feed — deterministic in, deterministic out | terrain_read (exists) + level_crosses (exists) · CR-03 |

Explicitly **not** built: book heatmap, footprint bars, TPO letters, DOM ladder —
skip-tier at minutes horizons per the architecture review.

## 6. Work items, dependencies, acceptance

Order is dependency-driven; each item is a separate commit round with real-seam tests
named in the commit prompt (seam rule), gate PASS, closeout GREEN.

| ID | Depends on | Deliverable | Acceptance (measured, not asserted) |
|---|---|---|---|
| CR-01 | — | streamer client + bus + cache + **`stream_capture.db`** writer + health | `stream_capture.db` exists and `ed_console.db` byte-growth from streaming = 0; a full RTH session captured with bounded queues — recorded max queue depth, drop count, JSON-parse p99; REST/streamer/terrain **contention matrix** recorded (REST latency + terrain-loop timing with streams on vs off); feed-drop drill shows DEGRADED→STALE in UI within 10s; **measured** key-accounting for L1 vs book services recorded; retention deletes proven to hold `stream_capture.db` at a bounded steady-state size (deletes don't shrink SQLite — the bound is measured, not assumed; RC-6 class) |
| CR-02 | CR-01 | Alpaca prints + CVD + signing cross-check | CVD captured (not yet displayed); Schwab-signed vs IEX-signed imbalance correlation measured and recorded on ≥3 sessions |
| CR-CAP | CR-01/02 | **capture gate (mechanical)** | ≥3 full RTH sessions in `stream_capture.db` with health history; UI stream-display code paths REFUSE to mount before this gate passes (fail-closed test proves it) |
| CR-03 | CR-CAP | WS hub + main chart panel + **coach layer** (§5 — tooltips/narrator/event badges); **retire polling loops + demote/hide chance-level ML DOM** | ≥1 legacy polling loop retired; ML surfaces hidden (hard-delete deferred to §8.3); layout-contract tests; coach copy sourced VERBATIM from terrain_read lines / level_crosses rows — no free-typed UI strings (contract-tested) |
| CR-04 | CR-CAP | RVOL + dispersion + breadth aggregators & strip | each metric has an unproven-register row + backfilled history from canonical bars where derivable; U-shape baseline proven against 20-day time-of-day means; RVOL copy says "range/vol conditioning," never "forecast," until CR-07 clears it |
| CR-05 | CR-04, terrain | three evidence tiles | **arming thresholds pre-registered in the unproven register BEFORE first arming** (e.g. the late-day tile's "large move" bound is a written constant with rationale, not post-hoc); each arming condition unit-tested both ways; each tile wired into the daily scorecard with its own placebo; tile copy contains NO published effect rates — mechanism words only |
| CR-06 | CR-01/02 **and CR-08 for trust labels** | flow instrumentation pane | impact coefficient computed on an explicit trailing window with written leakage rules (contemporaneous fit, clearly framed as such); "explains, does not predict" label contract-tested; trust labels rendered only after CR-08's conflation numbers exist |
| CR-07 | CR-05 | promotion gate | mechanical: a tile without N scored sessions CANNOT render a directional prompt (fail-closed test); **any tile that shapes a TRADE additionally passes decision-path admission (`decision_gate.py`)** — unadmitted influence → WAIT, same law as the old stack |
| CR-08 | CR-02 | conflation-cost study | one report: signal correlation full-tape vs 500ms-conflated on SPY; gates CR-06 trust labels |

## 7. Risks and honest limits

- **Conflation**: 500ms snapshots undercount quote events exactly in fast tape; CR-08
  measures the damage instead of assuming it.
- **IEX sample bias**: 2% of tape; ratios only; the cross-check in CR-02 quantifies
  agreement before anything downstream trusts either source alone.
- **Streamer unknowns**: book-service symbol availability and effective key budget are
  subscribe-and-measure; CR-01 records them as facts before CR-04 sizes the internals
  universe.
- **Windows host + GIL (v1.1 — elevated per Cursor review)**: the real contention surface
  is CPU, not I/O — JSON parse of ~500 conflated subs + aggregators over hundreds of
  names + FastAPI/terrain/REST in one GIL. CR-01's contention matrix (parse p99, queue
  depth, REST latency under load, terrain-loop timing) measures this before any UI
  consumes streams. The escape hatch, rewritten: a separate **capture daemon** owning the
  Schwab/Alpaca connections and `stream_capture.db`; the UI process attaches read-only or
  consumes IPC'd aggregates. NEVER a second writer on `ed_console.db` — that "hatch" was
  hand-waving and is withdrawn.
- **Evidence decay**: the three CR-05 effects are published; McLean-Pontiff decay applies.
  That is exactly why CR-07 exists — our own scorecard, not the papers, grants promotion.
- **0DTE blindness stands**: no free feed sees same-day-opened OI. The console states it
  (chip caveat) rather than pretending.

## 8. Rollout (v1.1)

1. CR-01/02 run **capture-only**; the ≥3-session requirement is the MECHANICAL CR-CAP
   gate, not a convention — display code refuses to mount before it passes.
2. New panels mount alongside legacy surfaces; a legacy surface retires only when its
   replacement has survived a week of live use without a defect ticket.
3. ML-stack surfaces are **demoted/hidden** at CR-03 (overdue — they measure at chance);
   **hard-delete only after replacement panels clear CR-07 plus the live week** — the
   plan's own retire-by-replacement law applies to the ML DOM too (v1.0 had this
   inconsistent; Cursor caught it).
4. Program reviews: after CR-03 and CR-05, a Cursor audit + Bugbot round each, same as the
   terrain bundles.

## 9. UI-copy law (v1.1)

Published effect rates and paper statistics live in §2 of this plan and in commit
messages ONLY. No tile, chip, tooltip, or program-table row may cite a paper's rate
(e.g. a reversion percentage) as if it were ours until our own scorecard reproduces it
through CR-07. Mechanism words are allowed ("closing price pressure tends to revert
overnight — measuring ours"); borrowed numbers are not.

## 10. Consensus protocol (operator directive 2026-07-21: "no confirmed daylight")

The plan reaches CONSENSUS status only through this loop:

1. Claude publishes plan version vN with a numbered **consensus position list** (below).
2. Cursor marks each position **AGREE** or **OBJECT + the specific change that would
   convert it to AGREE**. Silence or generalities do not count as agreement.
3. Claude incorporates or rebuts with evidence; version bumps; repeat.
4. Terminal state: every position AGREE in the same round → both agents co-sign the line
   **"CR PLAN vN — NO CONFIRMED DAYLIGHT — CONSENSUS"** in the commit body. Only a
   consensus-stamped version may receive the operator's GO.

**Round-2 record (v1.1 → v1.2):** Cursor marked P2/P3/P6/P7/P8 AGREE; objected P1
(§1 retire wording), P4 (§5 chart source authority), P5 (§4 frontend still led with the
registry), and raised P9 (§5 volume profile untagged vs §6 deferral) and P10
(ACTIVE_PROGRAM "500 keys" blurb). All five converted with Cursor's exact edits in v1.2.

### Consensus positions (P1–P8 as listed; P9 folded into P5/§5; P10 into P3/ledger)

P1. Rebuild-not-rehabilitate scope (§1): decision layer replaced, spine kept, retire by
    replacement.
P2. Evidence law (§2) incl. flow-explains-not-predicts and the kill list.
P3. Data stack (§3): Schwab streamer + Alpaca IEX as the free feeds; sentinel-first
    books; Alpaca eligibility verified at CR-02 start; single-streamer-owner rule.
P4. Storage (§4): dedicated `stream_capture.db`; ed_console.db zero-growth; bounded
    steady-state size measured; canonical-1m sole bar authority.
P5. Architecture (§4): in-process bus + last-value cache + one typed WS; capture-daemon
    escape hatch; bounded queues with drop counters.
P6. Sequencing (§6): CR-01 → CR-02 → CR-CAP (mechanical) → CR-03 (demote-not-delete,
    registry deferred) → CR-04..08 with stated dependencies and acceptance criteria.
P7. Governance (§§6-9): pre-registered arming thresholds; UI-copy law; CR-07 placebo
    gate + decision-path admission; CR-06 trust labels gated on CR-08.
P8. Rollout (§8): capture-first, week-live retirement rule, audit rounds after CR-03 and
    CR-05.
