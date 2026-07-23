# Terrain regime backtest — 2026-07-23T01:50:41+00:00

Scored **1057** ticker-days across **38** tickers (146.6s). Claim: SHORT_GAMMA_TREND -> above-own-median range; LONG_GAMMA_CHOP -> below.

| slice | n | hit% |
|---|---|---|
| ALL | 1057 | 52.1% |
| TRUSTED only | 1057 | 52.1% |
| narrow-chain only (LOW_CONFIDENCE — caveated) | 0 | —% |
| sentinels (SPY/QQQ/IWM) | 0 | —% |
| single names | 1057 | 52.1% |
| long-gamma days | 762 | 51.8% |
| short-gamma days | 295 | 52.9% |
| PLACEBO: yesterday's class persists | 1019 | 53.6% |

Trendiness (|close-open|/range) median — short-gamma days: 0.544, long-gamma days: 0.492 (mechanism check: short-gamma days should trend more).

## TU-04 sign-model A/B (single names; registered test due 2026-08-03)

naive 52.1% vs empirical-prior 50.5% on n=1057 shared rows (prior classified LONG on 100.0% of rows — it is constant-LONG by construction, C+P>0, so this measures whether naive's short-gamma call beats 'always dampen'; GPO prior, Garleanu-Pedersen-Poteshman Table 1).

## Wall hold rates (10:00 ET walls vs rest-of-session)

| slice | call n | call held% | close≤CW% | put n | put held% | close≥PW% |
|---|---|---|---|---|---|---|
| ALL rows | 807 | 70.6% | 83.1% | 781 | 72.1% | 85.5% |
| TRUSTED only | 807 | 70.6% | 83.1% | 781 | 72.1% | 85.5% |

_External benchmark (SpotGamma SPX 2019-2024, different walls/market — context, not a pass bar): call held 83.0% / close below 88.0%; put held 89.0% / close above 93.0%._

_Bar to clear: beat the placebo, not 50%. Narrow-chain rows are structurally LOW_CONFIDENCE (20-strike history) — the TRUSTED row is the honest one._

## PDCA — the loop, self-treating

- **DO (coverage)**: 35 tickers wide-captured today (healthy — at roster ceiling (17 confluence-only exclusions stand, operator 2026-07-21))
- **CHECK (window)**: 3/20 sessions accumulated; rolling TRUSTED−placebo gap: -1.6pts
- **ACT** → **YELLOW**: ACCUMULATE — 3/20 sessions in window; no ACT decision until it fills (Deming: don't tamper on common-cause noise)

_Rules: ≥+5pts promote · −5..+5 refine measurement · ≤−5 adjust inputs via register · window unfilled = accumulate. Single days never trigger ACT (special-vs-common cause)._
