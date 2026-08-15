# Liquidity × gamma “perfect storm” — discussion v1

**Status:** DISCUSSION only (Find & Prove). No Decide admission. No UI.  
**Date:** 2026-07-30  
**Companion results:** `reports/liquidity_gamma_hold_horizon_experiments_v1.md` (experiments #3 / #4 / #7)  
**Prior:** `reports/liquidity_synthesis_research_v1.md`, `reports/liquidity_gamma_levels_experiment_v1.md`  
**Edge claim:** NONE. Direction remains hard; nothing here authorizes TRADE.

Reproduce for measured Ed claims in the companion report:

```
python tools/liquidity_gamma_hold_horizon_experiments_v1.py
```

---

## AGENTS.md admission

| Field | Answer |
|---|---|
| MISSION_CLASS | Find & Prove — research discussion + offline experiments |
| GAP | Operator asked for storm intuition + hold/magnet / flip-regime / multi-horizon tests beyond touch→bounce FAIL |
| SMALLEST_COMPLETE_CHANGE | This note + `tools/liquidity_gamma_hold_horizon_experiments_v1.py` + companion report |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness for Ed numbers; literature tagged `[UNVERIFIED]` until Ed-measured |
| DECISION_PATH_EFFECT | None — WAIT |
| WHY_NOW | Operator two-part ask |
| TASK_ADMISSION | Discussion + research only |

---

## 1) What is the “perfect storm”? (plain English)

In desk jargon, a “perfect storm” around **gamma + options volume by strike** is the rare alignment of several independent forces at one price band — not a single magic strike.

**Candidate ingredients (all `[UNVERIFIED]` as a profitable combo on Ed until measured):**

1. **Structure / volume mass at a strike** — high open interest and/or session options volume concentrates hedging and pin risk at a level (vendor “call wall / put wall / pin” idiom; Ed terrain reconstructs walls/pin from the chain).
2. **Dealer gamma regime that matches the trade idea** — **positive / long gamma** → hedging tends to **absorb** (buy dips / sell rips → magnet / pin risk). **Negative / short gamma** → hedging tends to **accelerate** (sell weakness / buy strength → trend / cascade risk). Academic direction: Baltussen, Da, Lammers, Martens (JFE 2021) on hedging demand and intraday momentum — transfer to Ed walls is `[UNVERIFIED]`.
3. **Liquidity confluence at the same band** — prior-day VP / overnight / ORB / HVN families overlapping the gamma landmark (operator synthesis packet §2.3–2.4). Family-count ≥3 as edge is `[UNVERIFIED]` on Ed; prior synthesis bounce pack did not admit Decide.
4. **A trigger that is not mere touch** — absorption / rejection / OFI lean at interaction. Cont, Kukanov & Stoikov (JFEC 2014): OFI explains short-interval mid changes **contemporaneously** — confirmation, not tomorrow’s direction forecast.
5. **Asymmetric geometry** — air on the profit side, structure on the stop side (operator A+). `[UNVERIFIED]` until cost-aware barrier EV wins vs placebo.

**Honest compression:** the “perfect combination” people mean is roughly:

> **heavy strike volume/OI + correct gamma regime + multi-family liquidity at the same narrow band + a non-touch trigger.**

That is a **research hypothesis**, not a proven setup. Ed’s same-turn hold/horizon pack (**companion report**) did **not** find walls/pin beating same-distance or random placebos on hold or multi-horizon bounce labels. Prior gamma touch→bounce pack also **FAIL** (`liquidity_gamma_levels_experiment_v1.md`).

---

## 2) What drives spot toward a strike?

Distinguish mechanisms (do not collapse them into one story):

| Mechanism | Intuition | Status |
|---|---|---|
| **Dealer delta-hedging (gamma)** | As spot moves, dealers rebalance underlying; concentrated gamma can **pull** (long-γ magnet / pin) or **push through** (short-γ acceleration) | Literature-supported **directionally** (Baltussen et al.; dealer-hedging reviews). SpotGamma-style wall/pin narratives are **vendor idiom** → treat predictive claims as `[UNVERIFIED]` until Ed-measured |
| **Pin / max-pain near expiry** | High-OI strikes + exploding gamma near expiry → mechanical compression toward the strike | Well-known desk lore; strength/timing on Ed ETFs `[UNVERIFIED]` |
| **Resting liquidity / stops & take-profits** | Clusters of contingent orders at round numbers / prior highs → approach can reverse (TP-like) or cascade (SL-like) | Osler (JF 2003; JIMF 2005): TP vs SL clustering in **FX dealing banks** — transfer to US equity ETFs `[UNVERIFIED]` |
| **Volume-profile magnets** | HVN = acceptance / revisit; LVN = fast travel | Auction craft; edge `[UNVERIFIED]` |
| **Informed / institutional flow** | Large interest seeking a price → spot walks toward unfinished business | Plausible microstructure story; not identified as Ed edge |

**Magnet / pin vs acceleration through (do not confuse):**

- **Positive gamma / absorb:** hedging **leans against** the move → higher chance of **stall, mean-reversion, pin** near heavy gamma. Walls can *look* like support/resistance.
- **Negative gamma / accelerate:** hedging **leans with** the move → **break-and-go**, wider ranges, “levels fail fast.” Same wall can be a launchpad, not a shelf.

Ed sample caveat (**PROVEN** companion run): reconstructed regime days in the scored sentinel window were **SHORT_GAMMA only** (LONG=0). So we **cannot** yet claim Ed shows absorb-vs-accelerate split — the sample is one-sided.

---

## 3) How can I tell which direction spot will go? Signs?

**Short answer: you usually cannot with high confidence from gamma geometry alone.** Direction is the hard problem; abstain is the honest default (Decide WAIT).

**What is closer to “signs” than “forecasts”:**

| Sign class | What it might mean | Limit |
|---|---|---|
| **Regime badge (net GEX sign / flip side)** | Absorb day vs accelerate day — changes *how* levels behave, not a free arrow | Ed: LONG days missing in current morning_full TRUSTED sample (**PROVEN** companion) |
| **Location vs walls / flip** | Below put wall in short-γ → cascade risk `[UNVERIFIED]`; into call wall in long-γ → stall risk `[UNVERIFIED]` | Vendor narratives; Ed hold/bounce tests **FAIL** vs placebo so far |
| **Volume / OI by strike shifting intraday** | New interest relocates the “magnet” | Needs causal chain history; do not invent |
| **Touch + flow confirmation (OFI / absorption)** | Cont: confirms *current* pressure, not a standalone directional oracle | Confirmation ≠ foresight |
| **Osler-style response after cross** | Rejection vs continuation after level breach | FX evidence; ETF transfer `[UNVERIFIED]` |

**What Ed measured so far (PROVEN companion + prior gamma pack):** morning gamma walls/pin as bounce or hold targets do **not** beat placebos under pre-registered gates; lengthening the barrier to 15m / 60m / EOD does **not** flip FAIL→PASS. That is evidence against “levels alone point the way,” not evidence that markets are random — only that **this geometry+labeling stack** has not shown edge.

---

## 4) Are liquidity levels “large institutional orders that didn’t get filled”?

**Partly a useful mental model; partly overfit storytelling.**

- **Supported framing (microstructure):** visible S/R often coincides with **where liquidity sits** in the book — Kavajecz & Odders-White (RFS 2004): technical levels co-move with high cumulative depth (NYSE specialist era). So “unfinished business / resting interest” is closer to truth than “magic Fib.”
- **Gap up/down leftover interest:** after a gap, prior-day high/low and unfilled auction prices can act as magnets or reclaim levels — common auction language. Predictive edge on Ed `[UNVERIFIED]`.
- **Not the same as gamma walls:** call/put walls are **options-structure / dealer-hedging landmarks**, not necessarily resting stock limit orders. Conflating “GEX wall” with “institution’s unfilled buy” is a category error unless book/tape evidence joins them.
- **Stops beyond the level:** Osler’s SL clusters *beyond* rounds can **accelerate** through a level — the opposite of “resting bid holds.” So liquidity levels can be **fuel**, not cushions.

**Practical split for Ed:**

| Object | Better read as | Not automatically |
|---|---|---|
| PDH / PDL / ON / ORB / VP HVN | Prior auction & resting-interest candidates | Proven bounce edge |
| Gamma call/put wall / pin | Hedging / pin geometry | Unfilled stock order |
| Live L2 depth peak | Actual resting size (when captured) | Historical LOB validation (persist gap — synthesis research §5) |

---

## 5) Tie-in to same-turn experiments (pointer)

| # | Question | Companion verdict |
|---|---|---|
| 3 | Wall-hold / magnet (session respect + touch-and-hold) vs same-distance placebo | **FAIL** / **FAIL** |
| 4 | morning_full flip touches + LONG/SHORT regime | **BLOCKED** (flip touches=0; LONG days=0; morning_full n=9/ticker) |
| 7 | Same zones @ 15m / 60m / EOD vs placebo | **FAIL** all horizons; horizon does not rescue |

Costs **ABSENT**. Decide **WAIT**.

---

## 6) Bottom line for the operator

1. The “perfect storm” is a **confluence story** (strike mass + regime + multi-family liquidity + trigger) — keep it as a hypothesis, not a trading rule.  
2. Spot is driven toward strikes by **hedging flow, pin mechanics, resting liquidity, and contingent orders** — different engines, different failure modes.  
3. **Direction from gamma alone is not proven here**; signs are mostly **regime and interaction context**, not arrows.  
4. Liquidity levels *can* represent unfinished / resting interest — **especially auction & book objects** — but **gamma walls are not the same thing**.  
5. Same-turn Ed tests of hold/magnet and multi-horizon bounce still **FAIL or BLOCK**; accrue TRUSTED `morning_full` (ops, not invented data) before re-asking regime/flip questions.
