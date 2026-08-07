# Single-faucet levels service — measured case and design (v1)

**Mission:** Monday 2026-08-03 08:30 CT operator order, step 2 (named priority).
**Status:** RESEARCH + DESIGN COMPLETE. **No production code changed this turn** — the
step-1 precondition (co-tenant git freeze, RC-210) could not be confirmed with the operator,
who was not present for this scheduled run. Every artifact here is a NEW untracked file, which
is the only wipe-safe state on this shared worktree (`git stash` / `checkout` / `reset --hard`
do not remove untracked files — that is why `static/exposure.html` survived both wipes).

**Scope note.** The live two-endpoint divergence probe is run on **SPY**; the universe-wide
census (§2.1) covers **all 59 enrolled tickers** and was completed this turn, so no claim here
rests on a sentinel alone (RC-160).

---

## 1. What is wrong, in one screen's worth of plain language

The console has **more than one place that computes "yesterday's low"** — and this morning they
gave **two different answers, $3.09 apart, on SPY**.

| what the operator would read | value served 2026-08-03 ~09:41 ET |
|---|---|
| prior-day low, per the Chart's raw-levels engine | **737.68** |
| prior-day low, per `/api/price-levels` | **734.59** |

Both are labelled "previous day low". One of them is wrong. It is not a rounding difference and
it is not a display bug — the two producers are **measuring different windows of time**, and only
one of them was ever fixed.

---

## 2. Root cause — proven, not inferred

**PROVEN.** `/api/price-levels` labels a **TWO-session** range as "previous day".

`market_context.fetch_price_levels()` (market_context.py L1073-1074) asks Schwab for a
`period=TWO_DAYS` minute history and then appends **every** bar whose ET date is earlier than
today into one `prev_bars` list:

```python
elif dt_et.date() < today_date:
    prev_bars.append((dt_et, c))
```

There is no selection of *which* prior session. On a Monday that window holds Thursday **and**
Friday, so PDH/PDL/PDC/PD_POC/PD_VAH/PD_VAL are computed across both.

`liquidity_value_engine.get_previous_day_levels()` does **not** have this defect. It calls
`prior_trading_session_date()` and keeps the single most recent RTH session — the fix recorded
in that function's own comment block as UI-04 P1D / RC-153, which describes precisely this bug:

> "its fallback swept EVERY prior bar in the buffer (multi-day, extended-hours included) into
> PDH/PDL/PDC — wrong levels displayed as prior-day truth."

**The RC-153 fix was applied to one faucet and never to the other.** That is the whole thesis of
the single-faucet mission, demonstrated on a live production endpoint.

### The prediction test (this is what makes it proof, not a story)

If the cause is "two sessions merged", then the two served values must equal two specific
computable numbers. They do, to the cent:

```
SPY RTH sessions in price_bars_1m          RTH low
  2026-07-30                                734.590
  2026-07-31 (most recent prior session)    737.680

single most-recent prior session   low = 737.680  ==  /api/liquidity-snapshot PDL  737.68  ✓
union of the last TWO prior sessions low = 734.590  ==  /api/price-levels        PDL  734.59  ✓
both sessions' max high            = 748.895 == PDH from BOTH faucets  748.895            ✓
```

PDH agrees only by coincidence: Friday's high happened to be the higher of the two days, so
merging them changed nothing. The moment an earlier session prints the extreme, PDH diverges too.

**Reproduce:**
`python scratchpad/_pdl_root_cause_test.py` (RTH-scoped, read-only against our own
`price_bars_1m`; copy in this run's scratchpad — see §9)

### Full divergence table (same probe window, SPY)

| level name | `/api/price-levels` | `/api/liquidity-snapshot` | verdict |
|---|---|---|---|
| PDH | 748.895 | 748.895 | agree |
| PDL | 734.59 | 737.68 | **disagree by 3.09** |
| PDC | 747.03 | 746.82 | **disagree by 0.21** |
| PD_POC | 741.59 | 746.17 | **disagree by 4.58** |
| PD_VAH | 743.64 | 748.81 | **disagree by 5.17** |
| PD_VAL | 735.29 | 742.28 | **disagree by 6.99** |
| VWAP, VWAP±1, ORB H/L, overnight H/L, today POC/VAH/VAL | `null` (10 fields) | real values | price-levels blank |

`agree=1  DISAGREE=5  only-liquidity=10`.
**Reproduce:** `python scratchpad/_faucet_divergence_probe.py`

### 2.1 Universe census — this is not a SPY problem

**PROVEN.** `python scratchpad/_levels_universe_census.py` — for every enrolled ticker with 1m
bars, compare the single-most-recent-prior-RTH-session range (what the correct faucet computes)
against the union of the last two prior sessions (what the defective faucet computes):

> **56 of 59 enrolled tickers diverge today — 94.9%.**

Worst offenders as a share of price:

| ticker | prior-day range error | % of price |
|---|---|---|
| AMZN | 30.95 pts | **11.81%** |
| CIFR | 2.27 pts | 10.41% |
| BE | 20.55 pts | 10.00% |
| AAPL | 24.06 pts | 8.02% |
| STRL | 43.82 pts | 7.48% |
| NBIS | 13.42 pts | 7.35% |

The three tickers that "agree" today are **not** safe — they agree only because the newer
session happened to hold both extremes. The defect is in the code path, not in the ticker; a
ticker moves in and out of agreement as the tape changes.

This closes LEV-01 (§8): the divergence is **universal**, not SPY-specific, as the
ticker-independent code paths predicted.

PDC diverges for a *second, independent* reason: `fetch_price_levels` takes PDC from the Schwab
quote's `closePrice` field (Tier 1, L1007) while the liquidity engine takes the last RTH 1m bar
close. Two defensible definitions of "yesterday's close", never reconciled, 21 cents apart.

`/api/price-levels` also returned `bars_today: 0` with `error: ''` — HTTP 200, no today-session
data, and nothing in the payload says the session side is empty. Silent partial success.

---

## 3. How far the wrong number reaches

**PROVEN** by AST referrer trace (`scratchpad/_price_levels_referrer_scan.py`, 35 referrer sites)
plus a static-surface census (`scratchpad/_pdl_screen_reach.py`):

`fetch_price_levels` is **not** confined to its own endpoint. It is called at
**server.py L6752, inside `_fetch_state`** — the `/api/state` pipeline — and its output is
published into the state payload at **server.py L8741-8746**:

```python
ms_dict["pdh"] = ...; ms_dict["pdl"] = ...; ms_dict["pdc"] = ...
ms_dict["vwap"] = ...; ms_dict["orb_high"] = ...; ms_dict["orb_low"] = ...
```

and **index.html L13424 renders `s.pdc`** as the header's change-vs-yesterday's-close.

So the two-session PDC is **on the operator's screen today**, in the console header, while the
Chart's raw-levels strip beside it shows the single-session prior-day family from the other
producer. This is the RC-14 pattern exactly — two sources, one concept, two numbers visible at
once — reopened in a different domain.

The `/api/price-levels` **route** itself has **zero client consumers** (census below), so the
endpoint's own divergence is latent. The `_fetch_state` path is not latent.

### A third producer: the Chart computes its own prior-day levels in JavaScript

`static/chart.html` L391-410 `computeDaily()` derives `pdh/pdl/pdc` client-side from
`/api/bars1m`, grouping by `new Date(t*1000).toLocaleDateString()` — the **browser's local
timezone**, not ET — and taking `days[days.length-2]`, the previous *group in the buffer*, not
the previous *trading session*, with no RTH filter.

This one is **declared, not silent**: L572-576 prefers the engine's values and falls back to the
client copy only when the engine is absent, carrying the comment
`# ui-mockup-ok: engine values are the authority; client copies only when engine absent`.
It is still a fourth window rule for one level name, and it is what paints when the engine is down.

**Count for PDH/PDL/PDC alone: 3 independent producers (2 Python, 1 JavaScript), 3 different
definitions of "the prior session".**

---

## 4. The producer census — what actually exists

Seven levels-domain endpoints ship today; `governance/level_faucets.json` registers **seven but
names a different seven** — it omits `/api/price-levels` and `/api/level_crosses` (and lists
`/api/terrain/radar` and `/api/terrain/scorecard` nowhere).

**Measured latency, RTH 2026-08-03 08:43 CT, calibrated against `/favicon.ico` = 0.275 s:**

| endpoint | time | reads |
|---|---|---|
| `/api/price-levels` | **26.93 s** | synchronous Schwab price-history call |
| `/api/liquidity-snapshot?snapshot=live` | **21.61 s** | synchronous Schwab bar fetch |
| `/api/exposure/history` | 2.76 s | banked chains, all sessions |
| `/api/forces` | 1.56 s | banked chains, newest two |
| `/api/terrain/strikes` | 1.44 s | live terrain cache |
| `/api/terrain` | 0.98 s | live terrain cache |
| `/api/exposure/book` | 0.73 s | banked chain, newest |

**Reproduce:** the timing loop in §9.

This is a hard design constraint: **a single `/api/levels` that fans out synchronously to all
seven would cost ~27 s**, because two producers block on the vendor. The contract in §5 is
designed around it — see §5.4.

### Which surface reads which producer

`python scratchpad/_levels_consumer_census.py`:

| surface | levels endpoints it fetches |
|---|---|
| `index.html` | terrain (×3), terrain/strikes (×2), terrain/radar (×2), liquidity-snapshot, level_crosses |
| `chart.html` | terrain, terrain/strikes, terrain/scorecard, liquidity-snapshot, forces, level_crosses |
| `exposure.html` | terrain, terrain/strikes, liquidity-snapshot, forces, exposure/flow |

**Every tab re-assembles the level set itself, from a different subset of producers.** No two
tabs read the same combination — which is the structural reason a fix in one place does not
reach the others.

`/api/exposure/book`, `/api/exposure/history` and `/api/price-levels` have **no client consumer
at all** (0 references in `static/`). The first two are the step-6 orphan-wiring targets.

---

## 5. The `/api/levels` contract

### 5.1 Shape

```jsonc
GET /api/levels?ticker=SPY[&families=prior_day,value_area,gamma,...]
{
  "ticker": "SPY",
  "schema_version": 1,
  "served_ts_utc": 1785764812.4,
  "spot": 751.68,
  "spot_source": "schwab_quote_last",      // resolve_spot() ONLY — RC-14 single authority
  "spot_as_of_ts_utc": 1785764811.9,

  "levels": [
    {
      "id": "PDL",                          // stable machine id, UNIQUE within the payload
      "price": 737.68,
      "family": "prior_day",
      "label": "PDL",
      "side": null,                         // CALL | PUT | NET | null
      "strength": null,                     // {"value": 4.1e9, "unit": "GEX$/1%"} or null
      "evidence_tier": "price_fact",
      "provenance": {
        "producer": "liquidity_value_engine.get_previous_day_levels",
        "session_scope": "RTH",
        "window": "2026-07-31 09:30-16:00 ET (most recent prior RTH session)",
        "vendor_basis": "schwab pricehistory.candles[].low"
      },
      "staleness": {
        "as_of_ts_utc": 1785764700.0,
        "age_sec": 112.4,
        "stale_after_sec": 900,
        "stale": false,
        "reason": null
      }
    }
  ],

  "families_absent": [
    {"family": "opening_range", "reason": "ORB window incomplete (09:45 ET cutoff not reached)"}
  ],
  "degraded": [
    {"family": "vwap", "reason": "vendor bar fetch timed out after 20s", "last_good_ts_utc": ...}
  ]
}
```

### 5.2 Field laws (each maps to an existing root cause)

| field | law it enforces | origin |
|---|---|---|
| `id` unique per payload | a level is one row; coincident concepts merge into one entry with `also_ids`, they do not duplicate | RC-88 (one crossing wrote 8 rows), and `chart.html` already tests unique raw-level ids |
| `spot` / `spot_source` | `resolve_spot()` is the only spot faucet; no producer may carry its own | RC-14 / `single_spot_authority` |
| `family` | closed vocabulary; a new family requires a registry entry, not a new key | this document, §6 |
| `evidence_tier` | `price_fact` \| `derived_certified` \| `derived_uncertified` \| `unproven` — the operator can see at a glance which lines are facts and which are claims | Find & Prove charter; `governance/unproven_register.md` |
| `provenance.session_scope` | every derived level states RTH vs full-session **in the payload**, because the PDL divergence is exactly a session-scope disagreement | `rth_only_market_measurement` |
| `provenance.window` | the literal window used, so two producers can never silently mean different days | RC-153 |
| `staleness` **per level** | provenance is not freshness — a correctly-named tap can still have stopped flowing | RC-91 |
| `families_absent` | absence reads as absence, never as a substitute value | RC-68 |
| `degraded` | a partial answer says which part is partial; no silent `bars_today: 0` with `error: ''` | measured §2 |

### 5.3 Family vocabulary (v1)

`prior_day` · `value_area` · `vwap` · `opening_range` · `overnight` · `gamma` · `delta` · `oi` ·
`charm` · `vanna` · `expected_move` · `synthetic` · `spot`

The Chart already carries this vocabulary as `RL_FAM` / `rawLevelDefs` ids
(`PDH`, `PDL`, `PDC`, `PD_POC`, `PD_VAH`, `PD_VAL`, `VWAP_P2`, `TODAY_POC`, …) — chart.html
L485-531. **The contract adopts the Chart's existing ids verbatim** rather than inventing a
parallel naming scheme, which is why chart.html is the cheapest first consumer to migrate (§7).

### 5.4 Latency architecture — the part the 27 s measurement dictates

`/api/levels` **must not** be a synchronous fan-out. Design:

- **Tier A — banked / cached, served inline (< 3 s measured):** terrain walls, per-strike,
  forces, exposure book/history. Served on the request.
- **Tier B — vendor-blocking (21-27 s measured):** the price/volume families that need a Schwab
  bar fetch. These are served **from the producer's existing cache** with their real
  `staleness` block, and refreshed by the existing background loops — never fetched on the
  request path.
- A family whose Tier-B cache is cold appears in `families_absent` with
  `reason: "awaiting first background refresh"`. It never blocks the payload and it is never
  substituted from a different producer.

This is what makes one endpoint feasible at all. It also removes a real hazard the census
exposed: `chart.html` and `exposure.html` each call the 21 s `/api/liquidity-snapshot` on the
request path today.

### 5.5 Explicitly out of contract

- **The Gamma panel's data is untouched.** `/api/terrain/strikes` keeps its exact payload, its
  `today`/`prior` scopes and its bar heights. `/api/levels` carries *lines*, never the histogram
  series. This is the operator's stated constraint and it is a contract boundary, not a
  courtesy.
- `/api/level_crosses` stays as-is: it is a **history of level events**, not a level producer.
  It becomes a *consumer* of `/api/levels` ids in a later phase so a cross can name a stable id.

---

## 6. The missing lock (mandate-to-mechanism)

The honest answer to "why four producers?" recorded on 2026-08-02 was: each was born in a
different mission era, and **no law forced a system-level design pass before adding another
producer — the mockup law reviews UI, nothing reviews DATA architecture.**

Proposed enforcement, to ship *with* the build (an `.md` is never the lock):

1. **`check_levels_domain_single_producer`** (enforced, `tools/check_institutional_correctness.py`)
   — any staged route decorator or function that emits a name in the level vocabulary must be
   registered in `governance/level_faucets.json`. Registering a *new* producer requires an
   `operator_quote` in the same staged change. This registry rule already exists in the file's
   charter; today **nothing enforces it**, which is how `/api/price-levels` and
   `/api/level_crosses` stayed unregistered.
2. **`check_levels_divergence`** (enforced, runtime-backed) — a contract test that drives two
   or more producers of the same level `id` and **fails** when they disagree beyond tolerance.
   This is the check that would have caught the $3.09 PDL split the day it appeared. It is the
   single highest-value item in this document.
3. **PreToolUse clause** (`tools/pretooluse_guard.py`) — creating a NEW `@app.get("/api/...")`
   in the levels domain blocks at the moment of writing unless the registry entry is co-staged.
   Front end and back end, per the mandate-to-mechanism law: a commit-time check alone means the
   wrong producer is already written.

---

## 7. Build plan — ordered, each step independently shippable

**B0. Universe census — DONE this turn (§2.1).** 56 of 59 enrolled tickers diverge, worst
11.81% of price. No freeze was needed; it is read-only.

**B1. `/api/levels` as a pure read-adapter.** New endpoint; assembles the contract from the
*existing* producers. **No math moves, no producer changes, zero behavior change.** Ships with
contract tests and the §6.2 divergence test — which will **fail red on PDL/PDC/PD_POC/PD_VAH/PD_VAL
on day one**, correctly, and that red is the artifact that justifies B2.

**B2. Collapse the prior-day family to one implementation.** Route
`market_context.fetch_price_levels` prior-day block through
`liquidity_value_engine.prior_trading_session_date` (the RC-153-correct helper). Reconcile the
PDC definition explicitly — one of the two is chosen, in the open, and the other is deleted.
Divergence test goes green. **This is the step that fixes the number on the operator's screen.**

**B3. Migrate `chart.html`** — it already speaks the contract's id vocabulary, so this is the
cheapest consumer. Additive, `display:none` over delete (never-delete-working-screens law).

**B4. Migrate `index.html`** header PDC + terrain cells. **B5.** Migrate `exposure.html`.

**B6. Retire `/api/price-levels`** — 0 client consumers, and after B2 it duplicates nothing.

**B7. Ship the §6 locks** and register the orphan sweep as a standing check (step 6 of the
operator order).

Steps B1-B7 all require the **freeze** (§8). B0 does not.

---

## 8. Blocker

**RC-210 freeze is unconfirmed.** Two wipes on 2026-08-02 destroyed all uncommitted tracked work
in this shared tree, the second landing mid-recovery. The scheduled order makes the freeze a
**precondition**: "Do NOT build on an unfrozen tree." The operator was not present for this run
to confirm it, so no tracked file was modified. Racing the co-tenant is measured-futile.

`governance/root_cause_log.md` is currently modified in the working tree by the co-tenant.
Appending the RC row for this defect would risk their uncommitted work, so the row is **drafted
ready-to-append** at `scratchpad/_rc_levels_faucet_row_draft.md` rather than written into the
tracked ledger — an honest deferral with a named artifact, not a skipped obligation.

---

## 9. Reproduce everything here

```bash
# divergence between the two prior-day faucets (live, needs console on :8000)
python scratchpad/_faucet_divergence_probe.py

# root cause: single prior session vs union of two, against our own bars
python scratchpad/_pdl_root_cause_test.py

# referrer trace: where fetch_price_levels reaches (AST, 35 sites)
python scratchpad/_price_levels_referrer_scan.py

# screen reach: which static surface paints pd* fields
python scratchpad/_pdl_screen_reach.py

# which tab reads which levels endpoint
python scratchpad/_levels_consumer_census.py

# universe-wide blast radius: 56 of 59 enrolled tickers
python scratchpad/_levels_universe_census.py

# endpoint latency, calibrated against the no-op
for ep in "/favicon.ico" "/api/terrain?ticker=SPY" "/api/forces?ticker=SPY" \
          "/api/exposure/book?ticker=SPY" "/api/exposure/history?ticker=SPY" \
          "/api/price-levels?ticker=SPY" "/api/terrain/strikes?ticker=SPY" \
          "/api/liquidity-snapshot?ticker=SPY&snapshot=live"; do
  printf "%-46s " "$ep"
  curl -s -m 90 -o /dev/null -w "http=%{http_code} t=%{time_total}s\n" "http://127.0.0.1:8000$ep"
done
```

The five probe scripts live in this run's scratchpad
(`%LOCALAPPDATA%\Temp\claude\C--Users-evarg-Documents-Trading-EdWebConsole\
fa39512f-dc24-48c9-a097-68c8aebb1ed2\scratchpad\`) and are copied into `scratchpad/` in the repo
by the same-named files; both locations are untracked and therefore wipe-safe.
