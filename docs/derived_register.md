# Derived register

Schwab does not send these. Each one has one producer. The full inventory of
older derived values is still the queued register; this file starts with the
values added for the confluence matrix.

| Value | Producer | Why Schwab does not send it |
|---|---|---|
| Per-strike composite | `confluence_composite.score_magnitudes` | A rank of one expiry's book, from 0 up to that preset's ceiling. Each factor in the score is its absolute magnitude, scaled by a Hyndman-Fan type 7 percentile from the 5th to the 95th across the strikes that have it, then multiplied by its weight. A required factor that is missing blanks that strike. The top strike is not rescaled to 100. Schwab sends the contracts, not a score. |
| Per-strike volatility blend | `confluence_composite.iv_by_strike` | Schwab sends `volatility` on each contract. The column is one number for the strike, weighted by that contract's open interest plus its volume. A contract missing either count is not weighted. When the weights sum to zero, the blend is the simple mean of the contracts that have a volatility. When none do, the factor is missing. |
| Per-strike vanna | `math_exposure_core.compute_exposures_by_strike` | Schwab does not send vanna. One Black-Scholes vanna (`math_levels.bs_vanna`) per contract, from that contract's Schwab volatility, inside the one exposure book. The matrix reads the strike's `net_vanna`. |
| Per-strike charm | `math_levels.compute_charm_by_strike` | Schwab does not send charm. One call per expiry inside `terrain_engine.compute_terrain`. The full-book charm map is those expiry maps added. The matrix reads the expiry it shows. |
| Gross gamma | `confluence_composite.magnitudes` | Call leg plus put leg of the book's 1% gamma, and only when both legs are zero or positive. A negative leg leaves the cell empty. Not scored. |
| Put/call gamma, put/call volume, volume/open interest | `confluence_composite.magnitudes` | Ratios of the book's own legs. Blank when the divisor is zero or unknown. Not scored. |
| Vanna in dollars per vol point | `confluence_composite.magnitudes` | The book's per-strike `net_vanna` times the book's spot. The book stores `net_vanna` before that multiply. |
| Strike distance | `confluence_composite.build_matrix` | The strike minus the book's spot. |
| Score slope | `confluence_composite.build_matrix` | `100 × weight / (p95 − p5)` for each scored factor that varies. A diagnostic, not a second score. |
| Preset and ceiling | `confluence_composite.preset_name`, `confluence_composite.ceiling` | The weight row for that expiry's days to expiration: 0, 1–7, or 8 and beyond. The ceiling is 100 times the weights that are in the score. Flow and the change in gamma stay at zero, so they do not raise it. |
| Heat color | `confluence_composite.build_matrix` | Each column's color is that column's number divided by the largest absolute value of the same column on the expiry. The composite uses the score divided by the ceiling. Put/call columns color by which side is heavier. The page paints the served string. |
| Thin book | `confluence_composite.build_matrix` | Fewer than 10 strikes in the expiry have open interest or volume. The score is still computed. The note is served as text. |
| Flat factor | `confluence_composite.score_magnitudes` | Every strike with open interest or volume has the factor, and the 95th percentile equals the 5th, so that factor adds nothing. A factor missing on any of those strikes is not called flat. The note is served as text. |
| Level price on the rail | `server._screen_levels` | Each level is sent at its own price. The page draws that price on the rail between the strike rows. A price outside the visible strikes is a button above or below the matrix. The page does not move the price onto a strike. |
| One-day move markers | `server._confluence_markers` | The book's spot plus and minus the book's implied one-day move. Display only. Not scored. A strike between those two prices is marked `inside` by `server._inside_move`. |
| Rail and spot geometry | the confluence page | The page places each served level price and the served spot between the rendered strike-row centers. That is the design spec's display geometry. It does not produce a price. |
