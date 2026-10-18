# Derived register

Schwab does not send these. Each one has one producer. The full inventory of
older derived values is still the queued register; this file starts with the
values added for the confluence matrix.

| Value | Producer | Why Schwab does not send it |
|---|---|---|
| Per-strike composite | `confluence_composite.score_magnitudes` | A rank of the book. Schwab sends the contracts, not a score. |
| Per-strike volatility blend | `confluence_composite.iv_by_strike` | Schwab sends `volatility` on each contract. The column is one number for the strike, weighted by that contract's open interest plus its volume. |
