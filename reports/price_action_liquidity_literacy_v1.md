# Price-action liquidity literacy v1

**Status:** DISCUSSION / RESEARCH — literacy + methodological critique  
**Date:** 2026-07-30  
**Mission class:** Find & Prove research (no Decide admission; no app UI; no push)  
**Edge claim:** NONE. This file does not assert predictive edge on Ed data.  
**Cross-link:** If/when `reports/liquidity_experiment_input_audit*` lands (OI / yellow-bars / input census), treat it as the **input-fidelity** companion; this file is the **price-action event-definition** companion. That audit file was **not present** at write time — do not duplicate OI/DOM census here.

**Reproduce / authority for claims in this file:**
- Same-turn web research (market-microstructure / auction / Wyckoff / Market Profile / practitioner PA frameworks) — cited inline; predictive transfer to SPY/QQQ/IWM is `[UNVERIFIED]` unless a same-turn Ed harness is cited.
- Repo experiment reports (skimmed + tool event defs):  
  `reports/lp01_touch_study_v1.md`,  
  `reports/liquidity_synthesis_research_v1.md`,  
  `reports/liquidity_synthesis_experiments_v1.md`,  
  `reports/liquidity_gamma_levels_experiment_v1.md`,  
  `reports/liquidity_gamma_hold_horizon_experiments_v1.md`,  
  and touch scanners in `tools/liquidity_synthesis_experiments_v1.py` / gamma experiment tools.

---

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — research / methodological literacy |
| GAP | Operator critique: we treat “unfilled orders / resting interest” as LOB/OI stories while ignoring what is visible in candles; backtests may be pattern-blind |
| SMALLEST_COMPLETE_CHANGE | This report only (design specs for PA-aware events; no UI; no Decide; optional prototype deferred) |
| MINIMUM_SUFFICIENT_EVIDENCE | Cited literature taxonomy + PROVEN citations to prior FAIL packs’ event defs; no new edge numbers invented |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator bound: unfilled orders can be *seen* in price action; prior packs mostly tested “tag a static level” |
| TASK_ADMISSION | Admitted as research/discussion only |

---

## 1. Plain English for the operator (read this first)

**Your critique is right in spirit, and our packs largely confirm the methodological worry.**

We have been asking: *“When price’s high/low range overlaps a static level (PDH, ORB, call wall, order-block zone, FVG, …), does the next 30 minutes bounce / hold better than a random same-width level?”*  
That is a **location** test. It is not a **how price behaved at the location** test.

Practitioners who talk about “unfilled orders,” “resting interest,” “absorption,” or “unfinished auction” almost never mean “the print merely tagged the line.” They mean a **story told by the bar(s)**:

- Price **probed** a place where leftover interest might sit (gap edge, prior extreme, equal highs, consolidation edge).
- The tape / volume / wick **showed a fight** (rejection, absorption, failed break, reclaim).
- Only then do they lean that the leftover interest **defended** or **got filled and released**.

So FAIL vs placebo on bare touch does **not** prove “levels are useless.” It more honestly proves:

> **Mere geometric intersection of a bar range with a level is not, by itself, an informational event** — at least not on the samples and objectives we registered.

Your own synthesis research already said the A+ definition needs **“Trigger ≠ mere touch”** (`reports/liquidity_synthesis_research_v1.md` §2.4). The follow-up packs then largely **ran the touch-only spine** again (family count, width, OB/FVG geometry, gamma walls) and left the trigger layer as “next.” This literacy note closes that gap in language so the next experiments are not pattern-blind.

**What “unfilled / resting interest” can look like on candles (intuition, not edge):**

| You see on the chart… | Honest read |
|---|---|
| Gap open away from prior close; price later walks back into the gap | Overnight auction left a **price void**; filling it is common language, not a guarantee |
| Long wick into a known pool, close back inside | **Rejection / possible stop-run + reclaim** — interest (stops or limits) may have been engaged |
| High volume, tiny range at a level | **Effort without result** (Wyckoff) — *possible* absorption; OHLC cannot prove *who* absorbed |
| Break of high/low that snaps back inside 1–3 bars | **Failed breakout / sweep** — visible on OHLC; intent is `[UNVERIFIED]` |
| Flat dual-period high/low (poor high/low) | **Unfinished auction** (Market Profile convention) — magnet folklore is `[UNVERIFIED]` as edge |
| Last opposing candle before a displacement | **Order-block geometry** (PA operationalization) — we already tested touch of that zone: FAIL |
| 3-candle gap (FVG) | **Imbalance / skipped prices** — geometric; we already tested touch: FAIL |

None of those rows is a Decide admission. They are **event-definition vocabulary** so backtests stop treating every tag as the same thing.

---

## 2. Structured definitions: candle signatures of resting / unfinished interest

**Legend for every row**

- **VISIBLE (OHLC±vol):** can be coded from our `price_bars_1m` (O/H/L/C/volume) without book/footprint.
- **REQUIRES book/footprint/delta:** needs bid/ask volume at price, DOM refill, or aggressor flags.
- **Support status:**  
  - **Supported (concept):** appears in peer-reviewed microstructure, classic Wyckoff/auction pedagogy, or well-specified Market Profile craft as a *description of market process* — **not** as proven Ed-ETF edge.  
  - **`[UNVERIFIED]` folklore:** discretionary / ICT / vendor lore, or edge claims without fair measurement.  
  - **Ed-tested (structure only):** we ran a related geometric test; cite verdict — still not Decide.

### 2.1 Gaps (open vs prior close) + fill / partial fill

| Item | Definition (operational) | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Gap | Session open ≠ prior RTH close by more than a threshold (e.g. ≥ k×ATR or ≥ tick cluster) | Yes — open vs prior close | No for existence | Common TA fact of discontinuous auction; open-auction imbalance literature (e.g. Hasbrouck open-auction notes) explains *why* gaps form |
| Gap fill | Price later trades through the entire open→prior-close interval | Yes | No | “Gaps often fill” is practitioner / Investopedia-class lore; **timing and rate on our tickers** = `[UNVERIFIED]` until measured |
| Partial fill | Price enters the gap but does not reach prior close | Yes | No | Descriptive geometry only |
| Leftover interest framing | Gap = overnight / after-hours orders cleared at a new open; unfilled resting interest may remain near prior close / gap edge | Partial — path of fill is visible | True inventory of unfilled limits **not** visible on OHLC | Causal story is `[UNVERIFIED]` without book; **useful as PA hypothesis**, not as proof |

**Backtest implication:** event ≠ “tag prior close.” Event candidates: *gap-up open + first RTH attempt to enter gap*, or *first touch of prior close from inside the gap*, with wick/volume qualifiers.

### 2.2 Rejection wicks / pin bars

| Item | Definition | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Rejection wick | Upper (lower) wick ≥ k×ATR or ≥ f× bar range; close in opposite half of bar; preferably at a pre-defined pool | Yes | No | Classic PA; mechanical defs vary |
| Pin bar | Small body near one extreme + long opposing wick | Yes | No | Nison / retail PA family — geometry clear; edge `[UNVERIFIED]` |
| Resting-interest story | Wick = aggressive side hit resting size and failed to hold the extreme | Plausible PA | Confirmation needs absorption / delta | Microstructure-compatible *story*; not proven by wick alone |

### 2.3 Absorption (high volume, small range)

| Item | Definition | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Effort-vs-result (bar) | Volume high vs recent median **and** range (high−low) narrow vs recent median | Yes (OHLC+vol) | No for *proxy* | Wyckoff Law of Effort vs Result — **Supported as pedagogy** (Wyckoff Analytics / VSA tradition). Predictive edge on Ed = `[UNVERIFIED]` |
| True absorption (order-flow) | Aggressive hits absorbed by passive refill; delta one-sided; price stalls | Partial (small range + high vol is necessary but not sufficient) | **Yes** — footprint / Numbers Bars / DOM | Sierra Chart / NexusFi / Cont-style OFI framing: contradiction between aggression and travel |
| Mid-range “absorption” | Same proxy away from structure | Visible | Still needs book to validate | Widely warned as noise — treat as low-information without a level |

**Honest split:** Our bars can code a **VSA-style absorption proxy**. They cannot prove a large passive participant without book/footprint.

### 2.4 Failed breakouts (spring / upthrust family)

| Item | Definition | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Failed breakout | Close beyond level, then reclaim inside within N bars (or wick beyond + close inside) | Yes | Volume helps quality | Wyckoff spring / upthrust — **Supported as named PA process**; edge `[UNVERIFIED]` |
| Breakout acceptance | Multiple closes beyond + hold / retest from far side | Yes | Optional | Opposite of failed break — must be the control arm in any sweep study |

### 2.5 Poor highs / poor lows (unfinished auction)

| Item | Definition | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Poor high/low (TPO) | Session extreme formed by ≥2 adjacent TPO periods at the same price; **lacks excess / single-print tail** | Needs TPO / half-hour profile construction (doable from 1m bars → 30m TPO) | Footprint “0×N at extreme” is a *different* unfinished-auction object | Market Profile / Dalton craft — **Supported as convention**; revisit-rate folklore (e.g. vendor “70–80%”) = `[UNVERIFIED]` without fair Ed test |
| Excess / strong extreme | Single thin tail at high/low (“emotional” end of auction) | Profile or long wick cluster | Optional | Same tradition |

**Note:** Footprint “unfinished auction” (zero volume on one side at the extreme) is **not** the same object as a TPO poor high. Do not merge them in code without renaming.

### 2.6 Order block (last opposing candle before displacement) — as PA, not mysticism

| Item | Definition (Ed operationalization already used) | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Bullish OB | Last bearish candle before close displacement ≥ 1.5× causal ATR within 5 bars; zone = [L,H] of that candle | Yes | No | ICT/SMC branding = `[UNVERIFIED]`; **geometry is just “origin of impulse”** |
| Ed result | Touch of OB zone vs random same-width zones, triple-barrier bounce | — | — | **FAIL** — real 53.3% vs placebo 55.9% (`liquidity_synthesis_experiments_v1.md` Exp D). Costs ABSENT |

### 2.7 FVG as imbalance

| Item | Definition (Ed) | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Bull FVG | low[i] > high[i−2]; zone = [high[i−2], low[i]]; min gap 0.15×ATR | Yes | No | 3-candle imbalance = geometric fact; “must fill” = `[UNVERIFIED]` folklore |
| Ed result | Touch vs placebo | — | — | **FAIL** — 42.9% vs 45.7% (Exp E) |

### 2.8 Consolidation then expand

| Item | Definition | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Balance → imbalance | N bars with range ≤ r×ATR (or BB squeeze), then bar range ≥ e×ATR breaking the box | Yes | Volume on expand helps | Auction theory + opening-range / IB craft; edge `[UNVERIFIED]` |
| Link to liquidity | Expansion often leaves LVN / single prints (fast trade); later revisit is a **separate** hypothesis | Profile helps | Book optional | Do not equate “expand” with “resting orders filled” |

### 2.9 Stop-run through then reclaim (liquidity sweep)

| Item | Definition | VISIBLE | REQUIRES book | Support |
|---|---|---|---|---|
| Sweep / stop-run PA | Price trades beyond an obvious pool (equal high, PDH, OR high, …) by ≥ ε, then closes back inside within 1–3 bars on the level’s timeframe | Yes | Stops themselves invisible | Osler: stop-loss clustering *beyond* rounds / levels can accelerate; FX evidence **Supported** in papers — **transfer to SPY ETF 1m** = `[UNVERIFIED]`. ICT “liquidity sweep” naming = folklore wrapper around failed-break PA |
| Genuine break control | Close beyond and stay / retest holds outside | Yes | Optional | Required null behavior |

---

## 3. What is folklore vs what is process language

| Claim | Tag |
|---|---|
| Limit-order / stop clustering can create local S/R and cascades | **Supported** (Kavajecz & Odders-White LOB↔S/R; Osler SL/TP clustering) — see `liquidity_synthesis_research_v1.md` §3 |
| High volume + narrow range can mean absorption of initiative | **Supported as Wyckoff process language**; bar proxy ≠ book proof |
| Poor highs/lows mark unfinished auctions that “must” revisit | **Convention + folklore rates** — structure measurable; rates `[UNVERIFIED]` |
| ICT OB / FVG / “smart money” narratives | **`[UNVERIFIED]`** as causal labels; geometry OK as candidates |
| “Unfilled institutional orders after gaps always defend” | **`[UNVERIFIED]`** — gap path is visible; inventory is not |
| Our touch experiments found edge | **False** — packs FAIL / BLOCKED; see §4 |

---

## 4. Critique of OUR experiments (pattern blindness)

### 4.1 What we actually tested (PROVEN from reports/tools)

| Pack | Event definition (essence) | PA context in features? | Verdict |
|---|---|---|---|
| LP-01 Step 5 | Bar range **contains** structure level → forward \|return\| vs TOD baseline + displaced-level placebo | **No** — touch only | **FAIL** (`lp01_touch_study_v1.md`) |
| Synthesis A | Zone touch; compare family-count ≥2 vs 1 / shuffled families | **No** | **FAIL** |
| Synthesis B | Zone touch across widths; E(w) vs random centers | **No** (width only) | **FAIL** (Tsinaslanidis trap True) |
| Synthesis C | Gamma regime split of structure zones | N/A | **BLOCKED** (thin morning_full) |
| Synthesis D | Touch of OB geometry zones | OB geometry in **zone birth**; event still **first touch** | **FAIL** |
| Synthesis E | Touch of FVG zones | Gap geometry in zone birth; event still **first touch** | **FAIL** |
| Gamma levels | Touch / approach of CALL_WALL, PUT_WALL, PIN (FLIP: 0 touches) | **No** wick/vol/reclaim | **FAIL** |
| Gamma hold/horizon | Approach/touch → hold vs break; multi-horizon bounce | Hold is an *outcome*, not a PA entry qualifier | **FAIL** / E4 **BLOCKED** |

Code-level fingerprint (synthesis scanner): event fires when  
`bar.low <= zone.hi and bar.high >= zone.lo`  
then labels from touch-bar **close** via triple-barrier  
(`tools/liquidity_synthesis_experiments_v1.py` `_scan_zone_touches`).  
No wick ratio, no volume z-score, no reclaim, no gap-state, no consolidation-break state.

### 4.2 Did we test “tag a level” while ignoring PA context?

**Yes — systematically.**

Even when zones were *born* from PA-ish geometry (OB displacement, FVG imbalance), the **scored event** was still “price later tagged the zone,” not “price tagged *and* rejected / absorbed / reclaimed.”

Gamma packs asked “does the wall magnet / bounce?” still keyed off approach/touch distance in ATR — again location, not candle story.

### 4.3 Patterns NOT in the feature set (explicit)

Missing from event features / filters across these packs:

1. Rejection wick / pin metrics (wick ÷ ATR, close location in bar)  
2. Absorption proxy (volume high × range low)  
3. Gap state (open gap, % filled, first fill attempt)  
4. Break-and-reclaim / sweep confirmation (beyond → close inside within N bars)  
5. Failed vs accepted breakout control split  
6. Poor high/low / excess (TPO) at the level  
7. Consolidation→expand context at arrival  
8. Effort-vs-result sequence (multiple bars), not single touch  
9. Time-in-zone / number of probes before event (bounce-count as context — noted as `[UNVERIFIED]` feature in synthesis research)  
10. Book/footprint confirmation (Collect has live book memory; historical depth peaks not used in these offline packs — see synthesis research §5)

Synthesis research Rank 4 already named a trigger layer; it was **not** the primary arm of the executed packs.

### 4.4 Why FAIL vs placebo may mean “wrong event definition”

Fair reading of the FAIL stack:

1. **Touch selects wide bars** — LP-01 itself documented that range-containing-level sampling inflates volatility; placebo captures the method.  
2. **Mixture of opposite behaviors** — absorb vs sweep at the same geometric level cancel in a pooled bounce rate (regime split mostly BLOCKED/thin).  
3. **Trigger missing** — operator A+ already required a trigger; we measured the weaker hypothesis.  
4. **Geometry ≠ interest** — OB/FVG/wall *locations* without interaction quality are closer to chart stickers than to “unfilled orders.”  
5. **Costs ABSENT** — even a future PA-qualified PASS would still be pre-cost.

What FAIL does **not** license: “liquidity / levels / gamma are dead.” It licenses: **do not promote bare-touch bounce as edge**, and **redesign the event**.

---

## 5. PA-aware experiment menu (design first; no edge claims)

**Shared discipline (non-negotiable):**

- Same tickers/sessions policy as prior packs unless pre-registered otherwise.  
- Labels: triple-barrier and/or hold-vs-break — **pre-register** which is primary.  
- **Placebo:** same PA qualifier rate on random same-width levels / time-shuffled levels (not “no placebo”).  
- Costs: state ABSENT or apply; never silent.  
- Half-sample OOS agreement.  
- No Decide admission from a single PASS.

**Event schema (generic):**

```
EVENT = LOCATION_TOUCH ∧ PA_QUALIFIER ∧ CAUSAL_CONTEXT
LOCATION = pre-registered level/zone (structure and/or gamma), no lookahead
PA_QUALIFIER ∈ {rejection_wick, absorb_proxy, gap_fill_attempt, break_reclaim, ...}
ENTRY_TIME = close of confirming bar (not mid-wick fantasy)
```

### Ranked next tests (3–5)

#### Rank 1 — Rejection-wick at causal structure (cheap, highest literacy fix)

- **Question:** Does *first touch* of causal families (PRIOR_DAY / OVERNIGHT / ORB) **plus** wick ≥ k×ATR toward the zone and close back on the approach side beat (i) touch-without-wick and (ii) placebo levels with the same wick filter?  
- **VISIBLE:** OHLC only.  
- **Why:** Directly answers “unfilled/resting interest *seen* in candles.”  
- **Null:** shuffled level centers; keep wick filter so we don’t credit volatility selection alone.  
- **Kill criteria:** edge vs placebo & vs touch-only both fail pre-registered pp / halves.

#### Rank 2 — Break-and-reclaim (sweep) vs accepted break

- **Question:** At PDH/PDL/ORB extremes (and separately gamma walls when sample allows), does *beyond-by-ε then close back inside within N bars* predict barrier wins better than placebo extremes with the same reclaim rule?  
- **VISIBLE:** OHLC.  
- **Control arm:** accepted breaks (close beyond and stay N bars) — report separately; do not mix.  
- **Why:** Matches stop-run / failed-break vocabulary; still PA-only.  
- **Anchor literature:** Osler cascade *direction* (beyond-level acceleration vs reflect) — transfer `[UNVERIFIED]` until measured.

#### Rank 3 — Gap-fill attempt (overnight leftover path)

- **Question:** On gap days (|open−prior close| ≥ g×ATR), does the first RTH entry into the gap (or first tag of prior close) with optional rejection/absorb qualifier differ from non-gap days’ random level tags under the same barrier?  
- **VISIBLE:** OHLC.  
- **Why:** Operator’s “liquidity as leftover interest after gaps” — test the *path*, not a static overnight high alone.  
- **Fair method:** stratify by gap size buckets of equal width; report per-unit move, not only raw fill counts.

#### Rank 4 — Absorption proxy nested on confluence zones

- **Question:** Among family≥2 (or gamma wall) touches, does high-volume / low-range at the touch bar raise hold or bounce rates vs (i) low-volume touches at same zones and (ii) placebo zones with matched volume filter?  
- **VISIBLE:** OHLC+volume proxy.  
- **LIMIT:** proxy ≠ book absorption; state that in the report header.  
- **Why:** Synthesis research Rank 4; executed packs skipped it.

#### Rank 5 — Consolidation→expand through LVN / away from HVN (medium)

- **Question:** After a balance box, does expansion that leaves a thin region (LVN / single-print proxy) predict *continuation*, while first revisit with rejection predicts *mean reversion* — each vs placebo boxes?  
- **VISIBLE:** OHLC + session VP from bars.  
- **Why:** Separates “air pocket” from “acceptance” — two different liquidity stories often collapsed into one “level touch.”

### Optional tiny prototype

**Prefer design specs first.** A cheap prototype (only if a follow-up turn wants code) would be Rank 1 only: reuse `_scan_zone_touches`, add  
`wick_toward = (high-max(open,close))` or `(min(open,close)-low)` ≥ `k * causal_atr` and close on approach side; emit the same JSON/MD skeleton as synthesis v1. No UI. No Decide.

---

## 6. Parent-agent summary bullets

1. **Acknowledge critique:** Unfilled / resting interest is not only an LOB/OI narrative; candles can show *interaction quality* (wicks, failed breaks, effort-vs-result, gap paths). Our packs mostly scored **location tags**.  
2. **What it looks like in candles:** rejection into a pool; high-vol narrow bar; break-then-reclaim; gap fill/partial fill; poor extremes; consolidation then expand — with clear OHLC vs book splits (§2).  
3. **What we missed:** PA qualifiers were named in research (“trigger ≠ touch”) but not primary-tested; OB/FVG were zone generators still scored as bare touch — and **FAIL**ed placebos.  
4. **What to test next:** Rank 1 rejection-wick + structure; Rank 2 break-reclaim; Rank 3 gap-fill path; Rank 4 absorb proxy on confluence; Rank 5 balance→expand / revisit — same barrier + placebo discipline.  
5. **No edge, no Decide, no UI** from this note.

---

## 7. Disposition

- Artifact: `reports/price_action_liquidity_literacy_v1.md`  
- Decide: WAIT  
- Prototype: not shipped this turn (design-first per brief)  
- Companion input audit: cross-link when present; not duplicated here
