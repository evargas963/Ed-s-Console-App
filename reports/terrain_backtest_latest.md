# Terrain regime backtest — 2026-08-14T21:52:53+00:00

Scored **21** ticker-days across **4** tickers (472.6s). Claim: SHORT_GAMMA_TREND -> above-own-median range; LONG_GAMMA_CHOP -> below.

| slice | n | hit% |
|---|---|---|
| ALL | 21 | 57.1% |
| TRUSTED only | 21 | 57.1% |
| narrow-chain only (LOW_CONFIDENCE — caveated) | 0 | —% |
| sentinels (SPY/QQQ/IWM) | 0 | —% |
| single names | 21 | 57.1% |
| long-gamma days | 18 | 55.6% |
| short-gamma days | 3 | 66.7% |
| PLACEBO: yesterday's class persists | 17 | 52.9% |

Trendiness (|close-open|/range) median — short-gamma days: 0.393, long-gamma days: 0.307 (mechanism check: short-gamma days should trend more).

## TU-04 sign-model A/B (single names; registered test due 2026-08-03)

naive 57.1% vs empirical-prior 52.4% on n=21 shared rows (prior classified LONG on 100.0% of rows — it is constant-LONG by construction, C+P>0, so this measures whether naive's short-gamma call beats 'always dampen'; GPO prior, Garleanu-Pedersen-Poteshman Table 1).

## TU-13 OI-vs-VOLUME regime A/B (parallel profile — never silent swap)

| universe | n both | OI hit% | VOL hit% | placebo% | rho OI | rho VOL | winner |
|---|---|---|---|---|---|---|---|
| sentinels (SPY/QQQ/IWM) | 0 | — | — | — | — | — | — |
| single names | 18 | 55.6% | 44.4% | 50.0% | -0.6636 | -0.195 | OI |

_Parallel-profile law (TU-04 pattern): a weighting swap goes through PDCA rules, never a silent default change. History accrues `ab_*` fields from the sentinel slice (sign-proven universe)._

## Wall hold rates (10:00 ET walls vs rest-of-session)

| slice | call n | call held% | close≤CW% | put n | put held% | close≥PW% |
|---|---|---|---|---|---|---|
| ALL rows | 11 | 72.7% | 81.8% | 13 | 84.6% | 92.3% |
| TRUSTED only | 11 | 72.7% | 81.8% | 13 | 84.6% | 92.3% |

_External benchmark (SpotGamma SPX 2019-2024, different walls/market — context, not a pass bar): call held 83.0% / close below 88.0%; put held 89.0% / close above 93.0%._

_Excluded as breached at observation (wall on the wrong side of spot at 10:00 ET; hold undefined): ALL rows — call 10, put 8; TRUSTED — call 10, put 8._

_Bar to clear: beat the placebo, not 50%. Narrow-chain rows are structurally LOW_CONFIDENCE (20-strike history) — the TRUSTED row is the honest one._

## PDCA — the loop, self-treating

- **DO (coverage)**: 42 tickers wide-captured today (healthy — at roster ceiling (17 confluence-only exclusions stand, operator 2026-07-21))
- **CHECK (window)**: 6/20 sessions accumulated; rolling TRUSTED−placebo gap: -1.5pts
- **ACT** → **YELLOW**: ACCUMULATE — 6/20 sessions in window; no ACT decision until it fills (Deming: don't tamper on common-cause noise)

_Rules: ≥+5pts promote · −5..+5 refine measurement · ≤−5 adjust inputs via register · window unfilled = accumulate. Single days never trigger ACT (special-vs-common cause)._
