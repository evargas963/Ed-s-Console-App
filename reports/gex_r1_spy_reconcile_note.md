# SPY GEX reconcile — Cursor vs Claude (2026-07-17)

**Verdict:** No SPY GEX *build* bug. Cursor’s `gex_0dte` matches Claude’s ER relationship. The screen’s SPY `inverted/null` flag was a **sign-validation metric bug**.

## Evidence (same Cursor `gex_0dte` vs efficiency ratio)

| Ticker | n | ER\|GEX>0 | ER\|GEX<0 | Pearson(GEX,ER) | Spearman | vs ER |
|---|---|---|---|---|---|---|
| SPY | 69 | 0.091 | 0.358 | −0.33 | −0.23 | **as_assumed** |
| QQQ | 65 | 0.123 | 0.278 | −0.33 | −0.23 | **as_assumed** |
| IWM | 66 | 0.151 | 0.147 | −0.36 | −0.21 | flat sign / level OK |

Matches Claude’s independent table within rounding (`reports/gex_r1_claude_independent_verify.md`).

## Root cause of false SPY “inverted”

Screen `_sign_validation` used `regime_score = reversion_pnl − breakout_pnl` and required mean(score|+GEX) > mean(score|−GEX). That is a **harness** check, not a mechanism check. On SPY the toy-rule score disagreed with ER while GEX↔ER was correctly signed (long gamma → choppy).

## Reclassify

- Mechanism: **SIGNAL_PRESENT** (Claude verify + this reconcile)
- Economic harvest: still **UNPROVEN** (NULL_OR_WEAK was about the switch-every-day harness, not the mechanism)
- Next: tail-selective + defensive harvest redesign; §8.6 re-run; Monday collector gate FP-63

JSON: `reports/gex_r1_spy_reconcile_latest.json`
