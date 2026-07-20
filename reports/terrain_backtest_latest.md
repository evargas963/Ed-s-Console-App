# Terrain regime backtest — 2026-07-20T20:37:03+00:00

Scored **1054** ticker-days across **38** tickers (124.5s). Claim: SHORT_GAMMA_TREND -> above-own-median range; LONG_GAMMA_CHOP -> below.

| slice | n | hit% |
|---|---|---|
| ALL | 1054 | 52.1% |
| TRUSTED only | 1054 | 52.1% |
| narrow-chain only (LOW_CONFIDENCE — caveated) | 0 | —% |
| sentinels (SPY/QQQ/IWM) | 0 | —% |
| single names | 1054 | 52.1% |
| long-gamma days | 760 | 51.8% |
| short-gamma days | 294 | 52.7% |
| PLACEBO: yesterday's class persists | 1016 | 53.8% |

Trendiness (|close-open|/range) median — short-gamma days: 0.544, long-gamma days: 0.491 (mechanism check: short-gamma days should trend more).

_Bar to clear: beat the placebo, not 50%. Narrow-chain rows are structurally LOW_CONFIDENCE (20-strike history) — the TRUSTED row is the honest one._
