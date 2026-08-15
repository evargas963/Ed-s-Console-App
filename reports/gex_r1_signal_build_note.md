# GEX-R1 signal build note — §8.0 data availability (GO/NO-GO)

**Generated:** 2026-07-17 (read-only probe of `data/ed_console.db`)  
**Authority:** `reports/fp_levelset_directive_for_cursor.md` §8.0  
**No model code run.**

## Verdict: **FORWARD-ONLY for §8.1–8.3 as written**

The DB does **not** store the full option chain historically (all strikes × near expiries). Historical `option_chain_json` is a **selected-expiry slice** only.

## Evidence

| Question | Answer |
|---|---|
| Full chain all strikes/expiries historically? | **No.** Writer is `serialize_option_chain_for_eval` — keeps contracts matching **one** `selected_exp` only (`realized_contract_eval.py:202-219`). |
| Sample SPY latest with chain | **40** contracts, **1** expiry (`2026-07-17`), ~52 KB JSON |
| Separate options/chain table? | **None** (no optionish tables beyond `snapshots` columns) |
| Per-contract `gamma`? | **Yes** — field `gamma` present on stored contracts |
| Per-contract `open_interest`? | **Yes** — field `openInterest` (camelCase) |
| Per-contract IV? | **Yes** — field `volatility` (not `implied_volatility` / `iv`) |
| Strike / type / DTE? | **Yes** — `strikePrice`, `putCall`, `daysToExpiration`, `expirationDate`, `multiplier` |
| Aggregate gamma columns on snapshot? | **Yes** — `net_gamma`, `call_gamma_wall`, `put_gamma_wall`, `gamma_pin`, `gamma_gradient`, etc. These are **pre-rolled summaries**, not rebuildable full-chain GEX across expiries. |
| Chain JSON coverage (SPY/QQQ/IWM) | **54,120 / 124,040** snapshots (~44%) have non-empty `option_chain_json` |

## Implication for GEX-R1

- **Cannot** honestly backtest §8.3 `Σ over full near-term chain` from history — history lacks multi-expiry OI×gamma.
- **Can** start **forward collection** at ~09:35 ET of the full chain (or widen persist beyond `selected_exp`) and accumulate n over weeks.
- **Do not** treat snapshot `net_gamma` as a drop-in for §8.3 without a separate prereg that defines and sign-validates that proxy (Claude must agree; different experiment than GEX-R1 as written).

## §9 update (2026-07-17)

- **GEX-R1-SCREEN ran** on history → all tickers **NULL_OR_WEAK** (see `reports/gex_r1_screen_eval_latest.json`). Conditioned means were positive but **did not beat always-reversion**; shuffle null failed; not edge.
- **Forward full-chain capture** wired: `calibration/option_chain_morning_full.py` + server hook → table `option_chain_morning_full` once/day 09:30–10:00 ET for SPY/QQQ/IWM (near-term DTE≤~37d).
- **Monday gate (blocking):** do not count accrual until `reports/gex_r1_monday_collector_gate.md` is cleared and `reports/gex_r1_monday_collector_gate_result.json` says PASS (live process + new code + SQL rows). Queue FP-63.
