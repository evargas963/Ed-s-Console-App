# Derived register

Schwab does not send these. Each one has one producer. The full inventory of
older derived values is still the queued register; this file starts with the
values added for the confluence matrix.

| Value | Producer | Why Schwab does not send it |
|---|---|---|
| Per-strike composite | `confluence_composite.score_magnitudes` | A rank of the book. Schwab sends the contracts, not a score. |
| Per-strike volatility blend | `confluence_composite.iv_by_strike` | Schwab sends `volatility` on each contract. The column is one number for the strike, weighted by that contract's open interest plus its volume. A contract missing either count is not weighted. When the weights sum to zero, the blend is the simple mean of the contracts that have a volatility. When none do, the factor is missing. |
| Gross gamma | `confluence_composite.magnitudes` | Call leg plus put leg of the book's 1% gamma, and only when both legs are zero or positive. A negative leg leaves the cell empty. Not scored. |
| Put/call gamma, put/call volume, volume/open interest | `confluence_composite.magnitudes` | Ratios of the book's own legs. Blank when the divisor is zero or unknown. Not scored. |
| Vanna in dollars per vol point | `confluence_composite.magnitudes` | The book's per-strike `net_vanna` times the book's spot. The book stores `net_vanna` before that multiply. |
| Strike distance | `confluence_composite.build_matrix` | The strike minus the book's spot. |
| Score slope | `confluence_composite.build_matrix` | `100 × weight / (p95 − p5)` for each scored factor that varies. A diagnostic, not a second score. |
| Preset | `confluence_composite.preset_name` | The name of the weight row for that expiry's days to expiration: 0, 1–7, or 8 and beyond. |
