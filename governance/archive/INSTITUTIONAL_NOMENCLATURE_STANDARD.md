# INSTITUTIONAL NOMENCLATURE STANDARD (RC-350 / operator law 2026-08-14)

> **Law:** every displayed term on the terminal uses the verified institutional industry
> standard. Terminology decisions are made by deep research with cited sources (SpotGamma,
> MenthorQ, SqueezeMetrics, CQG/Bookmap/Jigsaw, Sweeney, CFA-level derivatives references) —
> never by grep, habit, or internal consistency. House terms are allowed only where research
> verifies NO industry standard exists, and must be honest and self-describing.

Research basis: dedicated deep-dive agent, 2026-08-14 (sources cited per row; SpotGamma
support-article definitions, MenthorQ guides, SqueezeMetrics DIX/GEX papers, CQG/Bookmap
volume-profile references, order-flow glossaries, Sweeney MFE/MAE).

## A. Rulings — display names (Console / Chart / Exposure / Desk)

| Current | Ruling | Display name (canonical) | Note |
|---|---|---|---|
| Gamma Pin | RENAME | **Absolute Gamma** (index) / Key Gamma Strike (equity) | max TOTAL gamma strike; "pin/pinning" names the behavior, not the level (SpotGamma) |
| Net Γ peak | polish | **Net GEX Peak** | max abs net GEX$ strike; no vendor-reserved name; spell out GEX |
| Gamma Wall Call / Put | RENAME | **Call Wall / Put Wall** | the exact industry pair (SpotGamma/MenthorQ); word order matters |
| Gamma Flip | KEEP | **Gamma Flip** (= Zero Gamma) | most vendor-neutral; NEVER "HVL" (MenthorQ branding) and NEVER "Volatility Trigger" (SpotGamma trademark for a DIFFERENT level) |
| Gamma Inflection / Delta Inflection | RENAME | **Max Γ Slope / Max Δ Slope** (or SpotGamma "Hedge Wall" ONLY if computation = max |dγ/dK|) | "inflection" collides with vendors' synonym for the zero-gamma flip — actively misleading |
| Delta Wall Call / Put | polish | **Key Delta Strike (Call/Put)** or DEX Wall | no settled industry pair; SpotGamma publishes Key Delta Strike |
| OI Wall Call / Put | KEEP (order) | **Call OI Wall / Put OI Wall** | genuine usage; keeping the OI qualifier is MORE precise than vendors — keep both bases explicit |
| OI Center | KEEP (spell out) | **OI-Weighted Center** | house, honest; must never be confused with Max Pain |
| Max Pain | KEEP | **Max Pain** | universal (OI payout minimum) |
| Vanna Wall Call/Put | RENAME | **Largest Vanna Strike (Call/Put)** + proxy tooltip | "Wall" overstates; computation is a vega/(S·IV) proxy — disclose |
| Gamma Void | KEEP | **Gamma Void** (alt: Low-Gamma Zone) | verified: no industry standard; honest house term |
| Charm Drift | RENAME | **Charm Flow** | term of art is "charm flows" (Traderade/MenthorQ) |
| Synthetic Fwd | KEEP | **Synthetic Forward** | textbook standard (put-call parity) |
| Net GEX · Agg | RENAME | **Total Net GEX (per 1%)**; profile-at-spot counterpart = **Net GEX @ Spot (profile)** | SqueezeMetrics aggregate vs SpotGamma Gamma Profile — two objects, two names, unit is part of the meaning |
| EM Upper / Lower | KEEP + tooltip | **Expected Move +/−** | disclose method (straddle×0.85 vs S·σ√t) in tooltip |
| "vol trigger" (any use) | FORBIDDEN | use **Gamma Flip** or a distinct house name | Volatility Trigger™ is a SpotGamma trademark for a level explicitly NOT zero-gamma |
| POC / VAH / VAL | KEEP | POC / VAH / VAL (70% value area) | Steidlmayer/CBOT standard, confirmed |
| PDH / PDL / PDC | KEEP | PDH / PDL / PDC | standard session levels |
| ORB high/low | KEEP + minutes | **OR High/Low (n-min)** | no standard n exists (5/15/30 all conventional) — the window MUST be displayed |
| VWAP (+ bands) | KEEP | **VWAP; VWAP ±1σ/±2σ** | institutional benchmark; anchored → say "Anchored VWAP (from X)" |
| King node | RENAME | **POC** (profile max) or **HVN** | community slang, zero reference-source presence |
| (adopt) | ADOPT | **HVN / LVN** | canonical high/low volume-node vocabulary |
| BUYING/SELLING PRESSURE | KEEP | (or "Net Aggressor: BUY/SELL") | honest generic verdict language |
| cum delta | RENAME | **Cumulative Delta (CVD)** | standard name across order-flow platforms |
| book imbalance | KEEP | **Book Imbalance (OBI)** | canonical microstructure metric (resting depth — tooltip must say so) |
| tape pressure | KEEP (or Trade Imbalance) | house-honest | precise term if aggressor-volume: "trade imbalance" |
| absorption | KEEP | **Absorption** | canonical order-flow term |
| sweep | DISAMBIGUATE | **Liquidity Sweep** vs **Options Sweep** | two industry meanings — label the one computed |
| DPI (latent key) | FORBIDDEN as-is | rename to actual computation | collides with SqueezeMetrics Dark Pool Indicator |
| smart money (latent) | RENAME | **Institutional Flow** (or name the proxy) | retail vernacular; name block/dark-pool/sweep proxy explicitly |
| EFE / EAE | RENAME | **Exp. MFE / Exp. MAE** | anchor to Sweeney's standard MFE/MAE; expectation variant disclosed |
| Containment / Expansion | KEEP + tooltip | house-honest | state band + horizon |
| Regime enums (LONG_GAMMA_CHOP…) | KEEP framing | display e.g. "Positive Gamma — Mean-Reverting" | framing IS industry consensus; enum is internal |

## B. Prioritized rename queue (would mislead a professional as-is)
1. any "vol trigger" usage → Gamma Flip (trademark + wrong level)
2. DPI → actual computation name (SqueezeMetrics collision)
3. Gamma/Delta Inflection → Max Γ/Δ Slope (collides with flip synonym)
4. Gamma Pin → Absolute Gamma
5. Gamma Wall Call/Put → Call Wall / Put Wall
6. King node → POC / HVN
7. Charm Drift → Charm Flow
8. cum delta → Cumulative Delta (CVD)
9. Net GEX · Agg → Total Net GEX (per 1%)
10. Vanna Wall → Largest Vanna Strike (+ proxy tooltip)
11. EFE/EAE → Exp. MFE / Exp. MAE
12. smart money → Institutional Flow

## C. Application rules
- Display layer first (labels/tooltips in static/*.html and any payload `*_label`/`*_tip`).
- Internal payload keys (`kl_gamma_pin`, …) migrate deliberately, never silently — they are a
  consumer API; a key rename requires a coordinated producer+consumer change with tests.
- Where vendors genuinely disagree (zero-gamma naming, wall basis, EM method, ORB window,
  GEX sign conventions) the terminal DISCLOSES method in the tooltip instead of picking a
  fake winner.
- Every future new displayed term gets a research-verified row in this table BEFORE it ships.
