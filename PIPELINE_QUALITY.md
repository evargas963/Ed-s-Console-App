# Pipeline quality (TQM checkpoints)

**Goal:** Catch bad or noisy data **before** it leaves the “factory” (training, dashboards, automation). Use this as a **station checklist** along the path from live ingest to model-ready tables.

Companion docs: `DATA_STEWARDSHIP.md` (principles + script runbook), `TRAINING_AND_MAINTENANCE.md` (training cadence + `/ops`).

---

## Station 1 — Live ingest (raw `snapshots`)

| Check | What “good” looks like | Levers |
|--------|------------------------|--------|
| Row rate vs. intent | At most **one new row per ticker per UTC minute** for append-only logging (matches 1m normalization bucketing). | **`ED_DB_SNAPSHOT_THROTTLE`** — default `1` (throttle on). Set to `0` / `false` / `off` to log every fetch (older behavior; can explode row counts under SSE + logger + polls). |
| Outcomes still advance | Older rows get `outcome_*` filled from newer spot, even when an insert is skipped. | Server always calls **`fill_outcomes`** after the throttle decision. |
| “Accidental” full pipeline | UI polls should not run **full `_fetch_state`** just to populate a dropdown. | **`GET /api/expiries`** on cache miss uses **chain-only** `_fetch_expiries_light` (no `MarketState`, no DB snapshot for that call). |

---

## Station 2 — Integrity and domain audits

Run from project root. High value early warnings:

| Checkpoint | Command |
|------------|---------|
| DB + schema + normalized rules | `python db_health_audit.py` |
| Training table on raw snapshots | `python audit_training_data.py` |
| Timing / spacing / intrabar | `python audit_snapshot_data.py` |
| Flow vs. archived chain | `python backfill_flow_imbalance.py` (see script header); `python debug_flow_snapshot.py` for one row |

---

## Station 3 — Normalized layer (`snapshots_1m_normalized`)

| Checkpoint | Command |
|------------|---------|
| Rebuild after backfills touching shared columns | `python snapshot_normalizer.py` |
| Validate without writing | `python snapshot_normalizer.py --validate` |

---

## Station 4 — Training readiness (GO / NO-GO)

| Checkpoint | Command |
|------------|---------|
| Model readiness vs. normalized 1m | `python audit_model_readiness.py` |
| Optional: smoke inference active tickers | `python smoke_predict_active.py` |

---

## How this ties to “king / jewels / guards”

- **King:** SQLite remains the system of record.  
- **Jewels:** Rows you train on and columns you trade on.  
- **Guards:** Throttles + light API paths **at ingest**, audits **before** training, normalizer **between** raw and ML tables.

Treat **NO-GO** from readiness audits like a **hold tag** on the factory floor: fix or exclude before shipment.
