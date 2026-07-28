# Terrain regime backtest — 2026-07-28T03:26:45+00:00

Scored **0** ticker-days across **0** tickers (242.6s). Claim: SHORT_GAMMA_TREND -> above-own-median range; LONG_GAMMA_CHOP -> below.

| slice | n | hit% |
|---|---|---|
| ALL | 0 | —% |
| TRUSTED only | 0 | —% |
| narrow-chain only (LOW_CONFIDENCE — caveated) | 0 | —% |
| sentinels (SPY/QQQ/IWM) | 0 | —% |
| single names | 0 | —% |
| long-gamma days | 0 | —% |
| short-gamma days | 0 | —% |
| PLACEBO: yesterday's class persists | 0 | —% |

Trendiness (|close-open|/range) median — short-gamma days: None, long-gamma days: None (mechanism check: short-gamma days should trend more).

## TU-04 sign-model A/B (single names; registered test due 2026-08-03)

_No A/B rows scored yet._

## TU-13 OI-vs-VOLUME regime A/B (parallel profile — never silent swap)

| universe | n both | OI hit% | VOL hit% | placebo% | rho OI | rho VOL | winner |
|---|---|---|---|---|---|---|---|
| sentinels (SPY/QQQ/IWM) | 0 | — | — | — | — | — | — |
| single names | 0 | — | — | — | — | — | — |

_Parallel-profile law (TU-04 pattern): a weighting swap goes through PDCA rules, never a silent default change. History accrues `ab_*` fields from the sentinel slice (sign-proven universe)._

## Wall hold rates (10:00 ET walls vs rest-of-session)

| slice | call n | call held% | close≤CW% | put n | put held% | close≥PW% |
|---|---|---|---|---|---|---|
| ALL rows | 1 | 100.0% | 100.0% | 2 | 100.0% | 100.0% |
| TRUSTED only | 1 | 100.0% | 100.0% | 2 | 100.0% | 100.0% |

_External benchmark (SpotGamma SPX 2019-2024, different walls/market — context, not a pass bar): call held 83.0% / close below 88.0%; put held 89.0% / close above 93.0%._

_Bar to clear: beat the placebo, not 50%. Narrow-chain rows are structurally LOW_CONFIDENCE (20-strike history) — the TRUSTED row is the honest one._

## PDCA — the loop, self-treating

- **DO (coverage)**: 37 tickers wide-captured today (healthy — at roster ceiling (17 confluence-only exclusions stand, operator 2026-07-21))
- **CHECK (window)**: 4/20 sessions accumulated; rolling TRUSTED−placebo gap: -1.6pts
- **ACT** → **YELLOW**: ACCUMULATE — 4/20 sessions in window; no ACT decision until it fills (Deming: don't tamper on common-cause noise)

_Rules: ≥+5pts promote · −5..+5 refine measurement · ≤−5 adjust inputs via register · window unfilled = accumulate. Single days never trigger ACT (special-vs-common cause)._
