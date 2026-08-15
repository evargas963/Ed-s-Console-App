# Gamma-flip / key-levels audit (Claude, read-only)

> **SUPERSEDED 2026-07-19.** This audit described `compute_gamma_flip` (cumulative-sum
> zero-crossing). That method was subsequently **DISPROVED** against a real SPY reference
> chain — correlation 0.086 with the true profile, cumulative sum never crosses zero,
> divergence 2.19e9 — and the function has been deleted. The canonical method is
> `compute_gamma_profile` (dealer gamma recomputed at each hypothetical spot), served via
> `compute_gamma_flip_v2` with a mandatory confidence flag. Retained for provenance;
> do not use its recommendations.

**Date (UTC):** 2026-07-17 · **File audited:** `math_levels.py::compute_gamma_flip` (672) + inputs.
**Verdict:** the flip level is **not trustworthy as built** — two independent problems. Operator's suspicion confirmed.

## Finding 0 — RAW GAMMA IS CONTAMINATED (most critical; upstream of everything)
The stored per-contract greeks are Schwab-native (delta/gamma/theta/vega all present). Rare but catastrophic corruption:
- **|gamma|>1.0 (physically impossible per-share):** SPY 9/8000 (0.11%), QQQ 1/8000, IWM 2/8000.
- **Every corrupted contract is 0DTE deep-ITM** (|delta|≈1), where true gamma ≈ 0, but Schwab's near-expiry greek engine returns garbage: e.g. SPY 748P **gamma −91965.237, OI 21605**; SPY 738C 3.647; IWM 298P 10.033.
- **Impact:** OI-weighted, one bad contract dominates the whole snapshot. SPY 748P: −91965 × 21605 ≈ **−2e9** → flips/obliterates net_gamma, GEX, and the flip for that snapshot. Rare (~0.1%) but any affected day's levels are garbage.
- Note: GEX-R1's ER validation survived only because rank (Spearman) correlation is robust to a few corrupted days. Production levels are not.

**GOOD (verified):** the aggregation pipeline itself is FAITHFUL — independent reconstruction from the raw chain matched stored `gamma_pin` 25/25, both walls 25/25, `net_gamma` sign 24–25/25 (SPY/QQQ/IWM). The bug is the INPUT, not the aggregation.

**Fix 0 (do FIRST — cheap, high-impact):** sanitize greeks before any aggregation:
- Hard-reject `gamma < 0` (vanilla-option gamma is always ≥ 0 — catches −91965).
- Cap/drop `gamma >` a sane bound (~0.5–1.0 per share for these underlyings) → treat as 0 or exclude.
- Optional stronger rule: `|delta| ≥ 0.98` ⇒ force gamma≈0 (deep-ITM/OTM gamma is ~0).
Apply in BOTH the live level computation and the research GEX build. Add a unit test with the −91965 fixture.

## Finding 1 — primary method is non-standard
`compute_gamma_flip` tries, in order:
1. **PRIMARY:** `_find_crossing("net_gex_1pct")` / `net_gamma` — the *per-strike* (call γ − put γ) sign change across the strike ladder. This finds roughly where calls start outweighing puts, **not** the zero-gamma level.
2. **FALLBACK (only if 1 returns None):** cumulative net GEX along the chain crossing zero — closer to the canonical SqueezeMetrics definition.

The canonical **zero-gamma / flip** = the spot price at which **aggregate dealer gamma summed over all strikes = 0**, ideally recomputing each option's gamma at hypothetical spot prices. The code never recomputes gamma at hypothetical spots (uses static current-spot gamma), and it prefers the per-strike method.

**Empirical (SPY, last 12 sessions, stored 0DTE slice):** the two methods disagree by up to ~1.3% and sometimes on *sign* of the offset from spot; on 2026-07-17 the cumulative method finds no crossing while per-strike returns one. So ordering changes the reported flip.

## Finding 2 — the input is far too narrow (the bigger issue)
Historical `option_chain_json` holds a **single selected expiry (~40 ATM strikes, 0DTE)** — see FP-63 / `option_chain_morning_full`. A real flip needs the **full chain**: all strikes (incl. far-OTM put walls that pull the flip below spot) across near expiries. With only an ATM 0DTE slice, both methods put the flip within ±1% of spot every day — it structurally hugs spot and cannot locate the true zero-gamma level.

This likely explains the operator's observation that the displayed flip behaves oddly. (Note: it is *normal* for price to sit above the flip most days — markets are usually net long gamma — so "rarely crossed" is not itself a bug; Findings 1–2 are.)

## Fix directive (Cursor implements, Claude verifies)
1. **Method:** make the flip the **cumulative aggregate net-GEX zero-crossing** the canonical definition (not the per-strike sign change); ideally recompute gamma at a grid of hypothetical spot prices and find total-GEX = 0. Keep the same +call/−put dealer-sign convention (consistent with the GEX-R1 build).
2. **Input:** compute the flip from the **full chain** (all strikes, near expiries) once `option_chain_morning_full` (FP-63) is capturing forward. Until then, label any displayed flip as `LOW_CONFIDENCE_NARROW_CHAIN`.
3. **Also re-derive** `net_gamma`, `gamma_pin`, and the call/put walls from the full chain and sanity-check `net_gamma` sign vs the realized-choppiness relationship (efficiency ratio) already validated in `gex_r1_claude_independent_verify.md`.
4. **Do not rush to production tonight** — the corrected method is only meaningful once full-chain data flows (Monday+). Land method + gate, verify against full-chain data next week.

**Dependency:** blocked on FP-63 (full-chain capture) for trustworthy output; method correction can land independently and be verified on the narrow slice for equivalence first.
