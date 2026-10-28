# EdWebConsole: the Schwab field dictionary

The rules for a change are in `AGENTS.md`; this file holds the First gate's Schwab field list.

## H. The Schwab field dictionary (the First gate's "Schwab field list", made complete)

- `docs/schwab_fields.csv` lists 4,512 field paths (768 distinct field names) and their types that our own tool and probes observed. It holds **no definitions**: `schwab_doc` says only where Schwab's docs define a field, or "not in Schwab's doc", and `sample` holds values Schwab sent.
- Schwab's definitions exist in two places:
  - **The Streamer guide** (`docs/schwab/schwab_streamer_api.pdf`) has a definition table for every stream field, including whether it updates in regular and AM/PM hours and when it resets. Examples for LEVELONE_OPTIONS: "Volatility is reset to 0 at 3:30am ET"; "Total Volume ... set to zero at 3:30am ET"; open interest, bid, ask and volatility "Update AM/PM Hours: No"; field 14 "Digits: Number of decimal places".
  - **The developer portal's REST schemas** (OptionContract, QuoteOption and others). In our saved copy every description is collapsed to `[...]`, so these must be expanded and pasted from the portal, or requested from Schwab.
- One dictionary line per field: endpoint or service; Schwab's name; Schwab's definition; update and reset timing; observed precision; observed quirks with evidence; our one reader.
- Observed quirks so far (10/07):
  - /chains rounds Greeks to 3 decimals; /quotes and the stream carry about 8.
  - /chains volatility is shared by the call and put at a strike (exact for SPY; not always for QQQ and AMD).
  - After hours, open interest answers 0.
  - Call deltas above 1 occur on both /chains and /quotes.
  - Field names in real /chains answers (bid, ask, mark) differ from Schwab's documented names (bidPrice, askPrice, markPrice).
