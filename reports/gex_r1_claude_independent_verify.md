# GEX-R1 — Claude independent verification (reverses the NULL verdict)

**Date (UTC):** 2026-07-17 · **Method:** read-only rebuild on `data/ed_console.db`, independent of Cursor's runner.
**Bottom line:** Cursor's `NULL_OR_WEAK` is **not supported**. The core mechanism is present and robust; what is unproven is *harvesting* it after costs. Reclassify to **SIGNAL_PRESENT / HARVEST_UNPROVEN → pursue.**

## What I did (independent of Cursor's rules)
- Rebuilt the 0DTE GEX myself from stored `option_chain_json`: `Σ_calls(gamma·OI·100·S²·0.01) − Σ_puts(...)`, stored gamma, +call/−put.
- Tested it against a rule-agnostic regime metric — the intraday **efficiency ratio** ER = |close−open| ÷ Σ|Δclose| over RTH `price_bars_1m` (low ER = choppy/mean-reverting, high ER = trending). ER does not depend on any toy trading rule, so it isolates the *mechanism* from the *harness*.

## Result — mechanism CONFIRMED, correct direction, all three names
| Ticker | n days | Pearson(GEX_level, ER) | Spearman | ER \| GEX>0 | ER \| GEX<0 | Bottom-GEX-quintile ER | Top-GEX-quintile ER |
|---|---|---|---|---|---|---|---|
| SPY | 69 | −0.33 | −0.22 | 0.092 | 0.358 | 0.270 | **0.055** |
| QQQ | 66 | −0.31 | −0.26 | 0.123 | 0.308 | 0.215 | **0.049** |
| IWM | 66 | −0.36 | −0.22 | 0.152 | 0.148 | 0.139 | **0.045** |

Long-gamma (GEX>0 / high) days are markedly choppier; short-gamma days trend. Modest correlation (~−0.22 to −0.36 on ~67 days) but **consistent across all three tickers and concentrated in the GEX tails** (top vs bottom quintile ER differ 3–5×).

## Two discrepancies with Cursor's screen (must reconcile)
1. **SPY sign.** Cursor flagged SPY as `inverted/null`. My independent build shows SPY with the **strongest correctly-signed** relationship (Pearson −0.33, GEX>0 on 50/69 days). One of the two SPY GEX builds has a bug — reconcile on identical days before any verdict.
2. **Signal lives in LEVEL, not just sign.** For IWM the sign split is flat (0.152 vs 0.148) but the level/quintile relationship is strong (Pearson −0.36). Sign-only conditioning (what the screen used) discards most of the signal. Use continuous GEX / distance-to-flip.

## Why the screen still "failed" its economic gate — and why that's not a null
- ER median overall ≈ 0.05: **most days are already choppy**, so "always-reversion" is a strong baseline that's hard to beat by *switching rules every day on GEX sign* (the weakest possible use).
- The likely economic value is **defensive/selective**, not switch-every-day: fade by default, but **stand aside or flip on the short-gamma (bottom-GEX) tail**, where fading gets run over (ER 0.14–0.27). A mean-$/day comparison on a choppy-dominated sample barely reflects avoided losses on the rare trend days — that's where GEX earns its keep. This ties directly to the app's WAIT/abstention strength.
- "Shuffle fail" = reversion pays regardless of GEX, i.e. the harness profit wasn't *from* GEX. True — but that tests the harness, not the mechanism. The mechanism test above is clean.

## What is NOT shown (do not overclaim)
- No proof of **money after costs.** ER separation ≠ P&L. The §8.6 economic gate is still unmet.
- ~67 days, **one ~4-month vol regime.** Thin and regime-narrow. Descriptive finding, not an edge.

## Next (redesign the harvest, don't shelve)
1. **Reconcile the SPY GEX sign** (Cursor build vs this one) on identical days.
2. **Redesign the harvest as tail-selective + defensive:** trade only high-conviction GEX extremes; fade on strong long-gamma, stand aside / momentum on strong short-gamma; size by continuous GEX / distance-to-flip; abstain in the middle.
3. **Re-run the §8.6 economic gate on that selective strategy** (block-bootstrap by day, 2× cost, GEX-shuffle) — including the avoided-loss / abstention accounting, not just mean $/day vs always-reversion.
4. **Keep forward full-chain capture running** — multi-expiry + full strikes should sharpen the sign (may resolve IWM sign + the SPY discrepancy) and add fresh out-of-sample days.

**Verdict:** the flashlight found something. Not edge yet — but a real, correctly-signed, tail-concentrated regime signal that independent rebuild confirms in all three names. Pursue the harvest; do not call it null.
