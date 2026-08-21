# Schwab Streamer Guide — BOOK field citation (provenance for RC-443 / ledger M8)

**Purpose.** The five Schwab BOOK fields (`BOOK_TIME`, `NUM_BIDS`/`NUM_ASKS`, nested `EXCHANGE`,
nested `Size`, nested `SEQUENCE`) are adjudicated PROVEN at the vendor-contract / raw-field
mapping level in `reports/schwab_field_semantic_normalization_ledger_20260820.md` (M8). This
file preserves the provenance so the adjudication is reproducible from the repo.

**First-party source (authoritative).** Schwab Trader API — **Streamer Guide**, developer portal
`https://developer.schwab.com` (Trader API → Streaming/Streamer documentation). The Guide is
login-gated; the operator holds a saved copy of the portal HTML. Schwab's copyrighted document
is NOT reproduced here — only the factual field-number → field-name mapping (positions and names
are data, not creative expression) and the reproducible corroboration.

**Documented BOOK field mapping (NYSE_BOOK / NASDAQ_BOOK / OPTIONS_BOOK — shared `BookFields`):**

| level | field # | Schwab documented name |
|---|---|---|
| book (top) | 1 | Market Snapshot Time |
| price level | 2 | Market Maker Count |
| price level | 3 | Array of Market Makers |
| nested (per market maker) | 0 | Market Maker ID |
| nested | 1 | Size |
| nested | 2 | Quote Time |

(Top-level 0 = Symbol; price-level 0 = Price, 1 = Total Volume — not in scope here.)

**Independent corroboration of the mapping (not of the copyrighted text):**
1. **Position structure** independently reproduced by three community decoders — schwab-py
   `BookFields`/`PerExchangeBid/AskFields`, allensarkisyan/schwab-td-ameritrade-streamer
   `ORDER_BOOK_EXCHANGE_FIELDS`, slimandslam/schwab-client-js.
2. **Exact position match** to our captured raw RTH frames (both capture runs).
3. **The distinctive `Quote Time` label (nested field 2)** is independently confirmed on our
   frames — the value is ms-since-ET-midnight tracking the book snapshot clock — and it
   *contradicts* every public decoder, which mislabels this field "sequence." A table that
   names nested-2 correctly cannot derive from the public decoders; it is first-party sourced.

**Reproduce the position/value identities (read-only over the carried capture):**
`python -c "import json,glob,datetime as D; et=D.timezone(D.timedelta(hours=-4)); ems=lambda e:(lambda dt:(dt-dt.replace(hour=0,minute=0,second=0,microsecond=0)).total_seconds()*1000)(D.datetime.fromtimestamp(e/1000,et)); rows=[(c['1'],nx['2'],str(nx['0']).upper()) for fn in glob.glob('reports/of_capability_probe/*/frames/*BOOK_*_raw.json') for c in json.load(open(fn))['content'] if c.get('1') for lvl in c.get('2',[]) for nx in lvl.get('3',[])]; vals=[v for _,v,_ in rows]; off=sorted(abs(v-ems(b)) for b,v,_ in rows); print('n=%d in_range=%d/%d freshest25=%.0fms codes=%d'%(len(rows),sum(0<=v<86400000 for v in vals),len(vals),off[len(off)//4],len({c for _,_,c in rows})))"`
→ `n=1329 in_range=1329/1329 freshest25=77ms codes=43`.

**Semantic axes (kept distinct per operator ruling):**
- **Vendor contract meaning = PROVEN** (the documented names above, position-matched).
- **Observed value domain = separately recorded** — e.g. nested `Market Maker ID` carries 43
  codes spanning market-maker MPIDs (JPMS/GSCO/VIRT/MLCO) AND exchange MICs (ARCX/NYSE/IEXG);
  breadth does not refute the documented name.
- **Higher-level trading interpretation = NOT automatically proven** — any downstream
  microstructure meaning must be proven on its own before entering the decision path.
