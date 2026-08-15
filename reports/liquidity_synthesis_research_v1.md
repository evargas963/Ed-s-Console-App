# Liquidity synthesis research v1

**Status:** DISCUSSION / RESEARCH PACKET only  
**Date:** 2026-07-30  
**Mission class:** Find & Prove research (no Decide admission; no UI chrome; no LP-01 Step reopen)  
**Reproduce / authority for measured claims in this file:** same-turn web fetches of primary/working papers + repo greps of `liquidity_value_engine.py`, `order_flow_live_state.py`, `server.py`, `tools/lp01_touch_study_v1.py`, `reports/lp01_touch_study_v1.md`.  
**Edge claim:** NONE. This packet does not assert predictive edge on Ed data.

---

## 1. Executive plain-English (operator)

LP-01 Step 5 asked a narrow question: when price *touches* a structure level, is the next 5/15/30 minutes larger than the same clock-minute usually produces? Pre-registered result: **FAIL** (`reports/lp01_touch_study_v1.md`). That failure does **not** mean “levels are useless.” It means **mere touch → magnitude** is too thin — the “darts on a chart” feeling is real for that hypothesis.

What you want next is richer: many independent liquidity *sources* compressed into **one or few narrow zones**, scored by **expected value of zone width**, with **regime context** (gamma absorb vs accelerate), and a **trigger** (not touch alone). Academic microstructure supports the *liquidity-location* view of S/R more than the “magic Fib line” view. Practitioner ICT / order-block / FVG literature is mostly discretionary — keep it as **candidate geometry**, not authority.

**Bottom line for the roadmap:** stop counting raw level hits; count **independent source families**; choose width by maximizing \(E(w)=P(\text{win}|w)\times R(w)\); validate zones against **book / volume evidence** when available; keep gamma as **regime + landmarks**, not another TradingView line with equal weight.

---

## 2. Ingested operator model (faithful summary)

All of the following are **operator design hypotheses** until measured on Ed data → tagged `[UNVERIFIED]` for predictive claims.

### 2.1 Levels ribbon idiom
- Every level spoken as: **level · distance · percent**.
- Put **gamma landmarks** in the same idiom (not a separate cryptic book).

### 2.2 Gamma entries (proposed)
- On ribbon: **GAMMA FLIP** (prominence near VWAP), **CALL WALL**, **PUT WALL**.
- **Net GEX** as a separate badge: regime + percentile — **not** on the ribbon as another price.

### 2.3 Confluence = independent source families (not raw level count)
Proposed families:
1. Today’s volume profile  
2. Prior-day volume profile  
3. VWAP family (VWAP + σ bands = **one** family)  
4. ORB  
5. Overnight  
6. Gamma  

Within prior-day: PD POC / PDC / PDL / PD VAL at the same price = **one family**, not four.

`[UNVERIFIED]` that family-count ≥3 predicts better outcomes than raw tag-count on Ed data.

### 2.4 A+ definition (all required — operator)
1. ≥3 families inside a bandwidth  
2. Regime alignment (GEX sign)  
3. Asymmetric geometry (air-pocket profit side; structure stop side)  
4. Trigger ≠ mere touch  

`[UNVERIFIED]` as a complete profitable definition until triple-barrier / cost-aware tests.

### 2.5 Empirical discipline (operator — endorsed)
Must empirical-test families **per regime** before trusting weights. Null: naive zones ≈ random.

### 2.6 Proposed build order (operator)
1. Two-surface KDE + family weights / half-lives  
2. Touch-event dataset with triple-barrier labels  
3. Calibrated \(P\) → rank by \(E\)  
4. Validate vs book depth  
5. Then ribbon  

---

## 3. Literature verified / corrected

| Claim (operator) | Verdict | Source & notes |
|---|---|---|
| Kavajecz & Odders-White (RFS 2004): S/R coincide with LOB depth peaks; TA as liquidity-location device | **Supported** (abstract / working paper text) | Kavajecz & Odders-White, “Technical Analysis and Liquidity Provision,” *Review of Financial Studies* 17(4), 2004. Working paper PDF (Rodney L. White / public mirrors): S/R cointegrated with limit prices of high cumulative depth; MA rules speak to book skew. **Scope:** NYSE specialist era LOB — not ETF L2 today. |
| “Kavajecz earlier — depth peaks / non-smooth book” | **Partially mis-attributed** | Kavajecz, “A Specialist’s Quoted Depth and the Limit Order Book,” *Journal of Finance* 54(2), 1999: specialist vs book depth, adverse selection, inventory. **Not** the S/R↔depth-peaks result (that is 2004). Depth is strategic / event-sensitive; “non-smooth book” as S/R theory should cite **2004**, not 1999. |
| Osler: TP vs SL clustering at/beyond rounds; different half-lives ~30m vs ~2h | **Clustering supported; half-life wording needs correction** | Osler, “Currency Orders…,” *Journal of Finance* 2003 (NY Fed SR 125); “Stop-Loss Orders and Price Cascades…,” *J. Int. Money & Finance* 2005 (NY Fed SR 150). **Proven in paper text:** TP clusters at rounds (reflect); SL clusters just beyond (accelerate). **Duration:** TP *reversal tendency* loses statistical significance in **&lt;30 minutes**; SL *continuation after crossing* remains significant **≥2 hours**. These are **price-response horizons**, not order-inventory half-lives. **Market:** FX dealing-bank conditional orders — transfer to US equity ETFs is `[UNVERIFIED]`. |
| Tsinaslanidis et al.: algorithmic zones; width↑ hit rate but not profitable; Fib ≈ non-Fib | **Supported** (open PDF + abstract) | Tsinaslanidis, Guijarro, Voukelatos, “Automatic identification and evaluation of Fibonacci retracements…,” *Expert Systems with Applications* 2021 (RIUNET open PDF). Wider zones → higher bounce *detection* probability; Fib zones **do not** beat random non-Fib; trading rules fail vs random-level benchmark. Direct warning against “widen until it looks good.” |
| Bounce count / age as features | **Plausible, not verified here as edge** | Practitioner / TA literature discusses touch counts and level age. No same-turn primary paper establishing OOS equity edge. Treat as `[UNVERIFIED]` features for supervised models. |
| Cont, Kukanov & Stoikov: OFI vs price | **Supported — contemporaneous, not forecast** | Cont, Kukanov, Stoikov, “The Price Impact of Order Book Events,” *Journal of Financial Econometrics* 2014 (arXiv:1011.6402). Linear OFI↔mid-price change over **short intervals**; avg \(R^2\) ≈ 65% in their sample; impact ∝ 1/depth. Correct use: **confirmation / adverse-selection read at the touch**. Incorrect use: “OFI forecasts that this S/R will hold tomorrow.” |
| ML S/R mostly unsupervised clustering — wrong for A+ | **Directionally right as a research stance** | Practitioner KDE/DBSCAN S/R tools are abundant (density of pivots → peaks). That optimizes **reconstruction of chart clutter**, not **decision EV**. Operator prescription (triple-barrier + purged CV + calibrated \(P\) → \(E(w)\)) matches López de Prado labeling discipline (*Advances in Financial Machine Learning*), not vendor KDE indicators. **No claim** that Ed has run that stack yet. |

### 3.1 Additional academic anchor (gamma regime)

- Baltussen, Da, Lammers, Martens, “Hedging demand and market intraday momentum,” *Journal of Financial Economics* 142(1), 2021: short-gamma hedging demand linked to **intraday momentum** (esp. last-30m continuation); effect stronger on negative net-gamma days. Supports operator intuition that **regime splits absorb vs accelerate** — but their object is close-of-day momentum, not LP-01 touch events. Transfer to Ed walls/flip is `[UNVERIFIED]` until measured.

### 3.2 SpotGamma-style walls vs academic GEX

| Layer | What it is | Status |
|---|---|---|
| Academic | Dealer/hedger gamma → pro-cyclical vs mean-reverting hedging (Baltussen et al.; related dealer-hedging literature) | Peer-reviewed regime evidence |
| Vendor / desk idiom | “GEX,” Call Wall, Put Wall, Flip as named products (SpotGamma coined GEX branding) | Useful vocabulary; **methodology assumptions differ by vendor** (OI ownership, 0DTE mix, sign conventions) |
| Ed Console | Terrain / math exposure: flip, call/put walls, net GEX (repo has production path) | Structure / regime inputs — **not** Decide-admitted edge |

Do not launder SpotGamma marketing claims as peer-reviewed results. Use academic hedging papers for regime hypotheses; use Ed’s own terrain backtests for Ed-specific claims.

---

## 4. Additional methods found (synthesis toolkit)

Honest taxonomy: **A = measurable microstructure**, **B = auction / profile convention**, **C = discretionary (ICT etc.)**, **D = ML labeling / scoring**.

### A. Microstructure / book
1. **LOB depth peaks** (Kavajecz & Odders-White) — ground truth for “liquidity location” when deep book history exists.  
2. **OFI / Cont** — contemporaneous confirmation at interaction, not zone discovery.  
3. **Microprice** (Stoikov, “The Micro-Price…,” SSRN 2970694) — fair value from top-of-book imbalance; short-horizon mid predictor. Useful as **trigger / lean**, not as a daily S/R map.  
4. **VPIN** (Easley, López de Prado, O’Hara, “Flow Toxicity…,” *RFS* 2012) — volume-clock toxicity. Regime / risk-off filter for providing liquidity at a zone; **not** a level synthesizer. Parameter sensitivity and replication debate exist — treat predictive Flash-Crash lore carefully.  
5. **Stop-run / cascade detection** (Osler cascades) — operationalize as: approach round/structure → acceleration vs rejection; separate TP-like absorb from SL-like sweep.

### B. Auction / volume profile
6. **HVN / LVN / POC / VAH / VAL** — HVN = acceptance / magnet; LVN = air pocket / speed. Aligns with operator “asymmetric geometry.” Mostly market-profile craft + empirical folklore → `[UNVERIFIED]` edge until tested.  
7. **Initial Balance, poor highs/lows** — Market Profile conventions for unfinished auctions. Same caveat: convention ≠ proven edge.

### C. Discretionary geometry (flag)
8. **Order blocks, FVG / imbalances, ICT / SMC** — large YouTube/course literature; little peer-reviewed causal identification. Encode only as **candidate zone generators** with the same supervised touch+barrier tests as Fib. Expect Tsinaslanidis-style null unless data says otherwise.

### D. ML / scoring (recommended spine)
9. **Unsupervised KDE / DBSCAN on pivots** — good for *proposing* candidates; **fails alone** because bandwidth↑ merges everything and hit-rate↑ without EV (Tsinaslanidis lesson).  
10. **Supervised touch events + triple barrier** (López de Prado) — label hold / fail / time-out; purged/embargoed CV; calibrate probabilities.  
11. **Optimal width via \(E(w)=P(w)\times R(w)\)** — as \(w\) increases, \(P(\text{bounce detection})\) rises but \(R\) (reward/risk, target remaining) falls; pick \(w^*\) maximizing EV, not hit rate.  
12. **Family-weighted confluence** — score independent families with half-lives / regime-conditional weights; never raw tag count.  
13. **Book-depth validation layer** — after zone proposal, check contemporaneous depth / VP mass / absorption proxies.

---

## 5. Repo capability gap (PROVEN same-turn greps)

### Present (Collect / structure surface)

| Capability | Evidence |
|---|---|
| Liquidity & value snapshot API | `GET /api/liquidity-snapshot` → `get_liquidity_snapshot` in `server.py`; builds via `liquidity_value_engine.generate_liquidity_value_snapshot` / `build_live_snapshot` |
| VP / PD / ON / ORB / VWAP bands | `liquidity_value_engine.py` (`compute_volume_profile_levels`, `compute_opening_range`, `compute_vwap_bands`, …); Chart `static/chart.html` level keys PDH/PDL/PDC/PD_POC/VAH/VAL, ON, ORB, VWAP±σ |
| Zone clustering + width cap | `cluster_price_levels_into_zones` — percent/fixed/ATR modes; `max_zone_width` (live API uses `PlaybookConfig(..., max_zone_width=2.0)`) |
| “Confluence score” today | **`confluence_score=len(tags)`** — raw tag count, **not** independent family count (`liquidity_value_engine.py`) |
| Tradeability score | `liquidity_zone_tradeable_score` (LM-1) — tags + options tags + inside + distance; not calibrated \(P\) or \(E(w)\) |
| Gamma / terrain walls & flip | Production terrain path + Chart gamma landmarks (call/put wall, flip); Net GEX elsewhere on console |
| LP-01 Step 5 harness | `tools/lp01_touch_study_v1.py`; **verdict FAIL** in `reports/lp01_touch_study_v1.md` (placebo beat real levels on Cohen’s d) |
| Schwab book / L1 stream (live memory) | `order_flow_streaming.py` / `order_flow_live_state.push_book` — nasdaq_book/nyse_book + LEVEL_ONE; feeds `OrderFlowEngine` (imbalance, absorption proxies, tape) |

### Missing or weak for the proposed synthesis program

| Gap | Notes |
|---|---|
| **Independent-family confluence** | Not implemented; current score = tag cardinality |
| **Half-lives / family weights by regime** | Not present |
| **Two-surface KDE synthesizer** | Not present (clustering is greedy merge of discrete levels) |
| **Triple-barrier touch dataset + calibrated \(P\) + \(E(w)\)** | Not present; LP-01 used TOD magnitude + placebo, not barrier EV |
| **Persistent LOB depth history for Kavajecz-style validation** | Book snapshots live in **in-memory deques** (`order_flow_live_state.py`); no same-turn evidence of a durable deep-book depth-peak table for historical S/R validation. Do **not** claim multi-day LOB depth peaks are queryable from SQL without a dedicated persist design. |
| **VPIN / Stoikov microprice / Cont OFI as named research features** | Order-flow engine has related *proxies* (book imbalance, absorption, cum delta); not the academic estimators as first-class Find & Prove objects |
| **Order blocks / FVG detectors** | Absent (appropriately) |
| **Decide admission for any of the above** | Registry empty by charter; structure-only |

**PROVEN LP-01 disposition (from report file):** FAIL; structure-only; Decide unchanged. A FAIL kills **that touch→magnitude hypothesis**, not the broader liquidity-pool search.

---

## 6. Proposed next experiments (ordered by information value / cost)

Discussion only — **not** implementation this turn.

### Rank 1 — Family-count vs tag-count (cheap, high info)
**Question:** Does ≥3 *independent families* inside a fixed narrow band predict better barrier outcomes than `len(tags)`?  
**Design:** Reuse LP-01 level constructors; define family map as operator §2.3; labels = triple-barrier (or hold/fail within horizon); purged CV by session; **split by gamma regime**.  
**Null:** family-count ≈ shuffled family labels.  
**Why it beats darts:** tests the operator’s core confluence definition before UI.

### Rank 2 — Optimal width \(E(w)\) curve (cheap–medium)
**Question:** For a given family-confluence core, which bandwidth maximizes \(E(w)=P(\text{win}|w)\times R(w)\) net of costs?  
**Design:** Sweep \(w\) in ATR% or $; plot hit-rate vs EV; enforce Tsinaslanidis discipline (never optimize hit-rate alone).  
**Null:** random centers with same \(w\) distribution.  
**Why it beats darts:** keeps zones **narrow where EV peaks**, not wide where bounce detection is easy.

### Rank 3 — Regime-split absorb vs accelerate (medium)
**Question:** Conditional on long-gamma vs short-gamma (Ed terrain sign at touch), do the same zones show bounce vs sweep?  
**Design:** Stratify Rank 1/2 by regime; secondary: distance to flip/walls. Anchor: Baltussen et al. direction (short gamma → momentum).  
**Null:** regime labels shuffled.  
**Why now:** explains why “level + touch” felt random — mixture of two behaviors.

### Rank 4 — Trigger layer (medium)
**Question:** Does requiring a trigger (absorption proxy, microprice lean, OFI confirmation, rejection wick) raise calibrated \(P\) enough to lift \(E\) after costs?  
**Design:** Same events as Rank 1; nested models with/without trigger; Cont lesson = confirmation, not foresight.  
**Null:** random trigger at same rate.

### Rank 5 — Book / VP validation layer (costly if persist needed)
**Question:** Do high-\(E\) zones coincide with (a) VP HVN mass, (b) live book depth peaks when stream is up?  
**Design:**  
- (a) available now from bars/VP faucet.  
- (b) only if streaming book is captured for the event window — may require **new Collect persist** before historical Kavajecz replication.  
**Do not claim LOB peak validation until persist exists.**

### Rank 6 — Candidate geometry bake-off (later)
Order blocks / FVG / IB poor highs as **extra family candidates** in the same harness. Expect many kills. ICT remains discretionary until it wins the bake-off.

### Explicitly lower priority (for this program)
- Ribbon / Chart chrome redesign  
- Decide admission  
- Reopening LP-01 Step 5 as a UI program  
- Unsupervised KDE-only “pretty zones” without EV nulls  

---

## 7. Why unsupervised KDE alone fails (discussion)

1. **Objective mismatch:** KDE maximizes density of past pivots/prices — chart reconstruction — not forward EV.  
2. **Bandwidth pathology:** larger bandwidth → fewer, wider zones → higher hit rate, lower target value (Tsinaslanidis).  
3. **Source dependence:** without family independence, KDE double-counts PD POC+VAH+VAL as “strong density.”  
4. **Regime mixture:** one density mixes absorb and accelerate days → mush.  
5. **No trigger:** density marks *where* liquidity may sit; Cont/Osler say *what happens on interaction* needs flow / contingent-order structure.

KDE remains useful as a **proposal surface** inside Rank 1–2, not as the scoring authority.

---

## 8. How gamma regime splits absorb vs accelerate (discussion)

**Supported by literature direction (not Ed measurement):**
- Long gamma / positive dealer gamma → hedging **leans against** moves (absorb / pin risk).  
- Short gamma → hedging **with** moves (accelerate / cascade risk) — Baltussen et al.  
- Osler: TP-like clusters → reverse; SL-like clusters beyond levels → continue.

**Operator implication for A+:**
- Same price can be A+ fade in absorb regime and “do not stand in front” in accelerate regime.  
- Net GEX badge (regime+percentile) belongs **off** the price ribbon; walls/flip stay as landmarks with distance/%.

`[UNVERIFIED]` on Ed until Rank 3 runs.

---

## 9. Explicit non-goals (this packet)

1. **No product UI redo** — no Chart/Console chrome, badges, cards, layout polish.  
2. **No Decide admission** — nothing here authorizes TRADE.  
3. **LP-01 Step 5 FAIL** kills only the **touch→magnitude vs TOD** hypothesis; it does **not** kill structure display, VP faucet Collect work, or the richer synthesis research program.  
4. **No server restarts**; no harness implementation required this turn.  
5. **No claim of edge**; no claim of persistent LOB depth history without a Persist design.

---

## 10. Admission block (charter)

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — research discussion |
| GAP | Touch-only LP-01 feels like darts; need multi-source → few narrow EV-optimal liquidity zones |
| SMALLEST_COMPLETE_CHANGE | This report (`reports/liquidity_synthesis_research_v1.md`) |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn literature verification + repo surface map; no Ed edge claimed |
| DECISION_PATH_EFFECT | None |
| WHY_NOW | Operator rejected thin LP-01 framing; asked for mathematical/ML synthesis path before richer UI |
| TASK_ADMISSION | Admitted as discussion/research only |

---

## 11. Source list (primary / reputable)

1. Kavajecz & Odders-White (2004), RFS — https://doi.org/10.1093/rfs/hhg057 ; SSRN 315660; working PDF mirrors.  
2. Kavajecz (1999), JF — https://doi.org/10.1111/0022-1082.00124  
3. Osler (2003), JF / NY Fed SR 125 — https://www.newyorkfed.org/research/staff_reports/sr125.html  
4. Osler (2005), JIMF / NY Fed SR 150 — https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf  
5. Tsinaslanidis et al. (2021), ESWA — RIUNET open PDF https://riunet.upv.es/…  
6. Cont, Kukanov, Stoikov (2014), JFEC — https://arxiv.org/abs/1011.6402  
7. Baltussen, Da, Lammers, Martens (2021), JFE — https://doi.org/10.1016/j.jfineco.2021.04.029 ; ND PDF  
8. Easley, López de Prado, O’Hara (2012), RFS — VPIN / flow toxicity (SSRN 1695596)  
9. Stoikov — Micro-Price (SSRN 2970694)  
10. López de Prado — triple-barrier labeling (*AFML*; method standard, not an Ed result)

**Paywall limits:** Full proprietary SpotGamma methodology and some closed journal HTML pages were not used as primary text; claims above rely on abstracts, Fed open PDFs, arXiv/SSRN, and university open PDFs. Where only abstract was available for a paywalled HTML view, wording stays conservative and is not extended beyond abstract-supported statements.
