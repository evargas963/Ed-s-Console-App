> **Classification:** Historical evidence | **Scope:** Vendor fields discovered by polling. **Not a work queue.** INGEST residuals live on `ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md` PA-5.

# Vendor Field Discovery Register (RC-388)

**Why this file exists.** On 2026-08-15 a live poll of all six Schwab market-data endpoints
found 8 fields the vendor returns that our catalogue lacked. They were merged into
`schwab_field_inventory/schwab_field_dictionary.csv` and the JSON registry — and then
nothing consumed them and the session moved on.

That is not carelessness, it is structural: this repo makes **defects** expensive and
**discoveries** free. A defect gets an RC row, a due date and an enforced check that turns
red. A discovery gets a sentence in a commit message and evaporates. Nothing held it open.

So a discovery now gets the same standing as a defect: **registered on arrival,
dispositioned deliberately, and never silently dropped.** A field may be DECLINED — that is
a legitimate outcome — but it may not be *forgotten*, and the reason is recorded so the
decision can be revisited when conditions change.

Dispositions: `SEE_MASTER` (obligation lives only on the sole master) · `DECLINED` (reasoned no) · `DONE`. `INGEST` is historical wording and is not independent work state.

## Discovered 2026-08-15 — live poll, all six endpoints

| field | endpoint | disposition | priority | rationale |
|---|---|---|---|---|
| `bidSize` / `askSize` / `bidAskSize` | chains | SEE_MASTER OD-1225 | 1 | Top-of-book depth behind the price (e.g. `51X43`). A mid of 2.10 renders identically whether 51 contracts are resting or 1 — the single highest-value addition for anyone executing. Operator: matters "more than you know". MUST ship with `quoteTimeInLong`: size without a freshness stamp is worse than no size, because it is wrong in exactly the moments it matters. |
| `quoteTimeInLong` / `tradeTimeInLong` | chains | SEE_MASTER OD-1225 | 1 | Per-CONTRACT freshness. The repo already treats staleness as first-class but only per snapshot; this makes it per contract, and it is the guard that makes displayed size trustworthy. |
| `breakEven` | chains (call + put maps) | SEE_MASTER OD-1225 | 2 | Vendor-computed breakeven per contract. `v2_decision/a2_option_expression.py:745` derives its own, tagged `v1_approximation`, and the derived-field register closed OP-006/OP-007 citing "no native BE" — a false premise. NOT a correctness bug: measured 2026-08-15, ours and Schwab's agree to $0.01. This is a Schwab-first provenance swap that retires a derivation, pending a semantics check. |
| `ethOptionEligible` | chains + quotes.reference | SEE_MASTER OD-1225 | 3 | Which contracts may trade in extended hours. Low value today; **load-bearing on 2026-12-06**, when NYSE Arca's 23-hour session and its 9:00pm–4:00am overnight window begin (originally 2026-08-11, slipped). Ingesting early is cheap; discovering it late is not. |
| `ssid` | chains (call + put maps) | SEE_MASTER OD-1225 | 4 | Stable per-contract streaming identity. Better than parsing the OSI symbol, which is string surgery on a money path. |
| `intrinsicValue` / `extrinsicValue` / `timeValue` | chains | SEE_MASTER OD-1225 | 4 | Decomposes premium into what is real and what is decay. On a 0DTE console that is the difference between "premium" and "pure theta". Present in the catalogue already but unconsumed — registered here so it is not lost with the rest. |
| `theoreticalOptionValue` vs `mark` | chains | SEE_MASTER OD-1225 | 4 | Rich/cheap read straight from the vendor (1.934 vs 2.11 on the sampled contract), with no model of our own to defend. |
| `hasBinaryOptions` | chains | DECLINED | — | Boolean flag with no consumer on the decision path and no operator request. Revisit if binaries ever enter scope. |
| `pricehistory.symbol` | pricehistory | DECLINED | — | Echo of the requested ticker. Cheap correctness guard against a wrong-symbol series, but the request path already pins the symbol. Revisit if a series-mismatch defect is ever observed. |

## Standing rules

1. **A poll that finds a field ends here, not in a commit message.** Any run of
   `tools/sync_schwab_field_dictionary.py` that reports NEW fields adds a row with a
   disposition in the same turn.
2. **DECLINED requires a reason**, and the reason is revisitable — conditions change
   (`ethOptionEligible` is the worked example: near-worthless until December, then required).
3. **Priority is set by desk value, not by ease.** Top-of-book size before plumbing.
4. **A field pair with a safety dependency ships together.** Size ships with its freshness
   stamp or it does not ship.

## Lock (RC-388 NEXT-DEPTH, not yet built)

A check that fails when a field in `schwab_field_dictionary.csv` carries a `first_seen`
date but has no entry here. Until it exists, this register is conduct, not a lock — and by
the named-force law that means it is only as good as the next person's memory.
