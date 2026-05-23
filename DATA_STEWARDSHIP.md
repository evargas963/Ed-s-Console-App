> **Classification:** Operator Runbook | **Scope:** Training, maintenance, and data stewardship procedures.

# Data stewardship — EdWebConsole

**Guiding principle:** The database is the **king**; the fields and rows that drive your decisions are the **crown jewels**; written rules, automated checks, and routine habits are the **guards**. Nothing precious sits in the vault without guards — and nothing is “true” only because it was saved.

---

## Part 1 — What each part means

| Image | Meaning here |
|--------|----------------|
| **King** | The SQLite DB (`data/ed_console.db`) as the **single system of record** for snapshots and derived analytics. |
| **Crown jewels** | The **small set of things that must be right** when you trust a row: ticker, time, spot/price context, option chain when you rely on it, flow/greeks if you act on them, outcomes if you train models on them. *You can grow this list deliberately.* |
| **Guards** | **Rules** (“this column may be NULL only when…”), **scripts** that verify or repair data, **habits** after imports (audit → backfill → normalize), and **tiers** (gold vs “do not use for decisions”). |

---

## Part 2 — When you’re unsure

1. **Does this touch crown-jewel columns?** → Be slower and stricter.  
2. **Are the guards in place?** (rule written + check run?)  
3. **If we skip a guard, what’s the worst “garbage in” case?** → If it’s bad, don’t skip.

**One-line reminder:** *King, jewels, guards — same package; not the vault alone.*

---

## Part 3 — Operational runbook (what to run and when)

Run these from the **project root** (`EdWebConsole`) unless noted.  
On Windows PowerShell: `cd` into that folder first.

### Tier A — Do regularly (data health & consistency)

| Task | Suggested cadence | Command (typical) | Notes |
|------|-------------------|-------------------|--------|
| **DB health audit** (integrity, schema, normalized rules, sample flow check) | After big imports; weekly if active | `python db_health_audit.py` | Stricter: `python db_health_audit.py --deep-flow --strict-flow` |
| **Normalize 1m training table** (rebuild `snapshots_1m_normalized`) | After backfills that touch columns used in training | `python snapshot_normalizer.py` | Validate only: `python snapshot_normalizer.py --validate` |
| **Flow + smart-money from archived chain** | When chain JSON exists but flow is empty/wrong; after replay | `python backfill_flow_imbalance.py` | Match JSON only: `python backfill_flow_imbalance.py --force` then re-run normalizer |
| **Debug one snapshot’s flow inputs** | When a row looks wrong | `python debug_flow_snapshot.py --latest SPY` or pass `snapshot_id` | |

### Tier B — On schedule or when fixing gaps

| Task | Suggested cadence | Command (typical) | Notes |
|------|-------------------|-------------------|--------|
| **Backfill VWAP / IV rank / pressure fields** | When those columns are NULL or stale historically | `python backfill_snapshot_derived.py` | Can skip normalizer pass with `--skip-normalizer` if you’ll run it separately |
| **Training-table / snapshot audits** | Before training; after data collection pushes | `python audit_training_data.py` | Raw `snapshots` |
| | | `python audit_snapshot_data.py` | Timing / spacing / intrabar checks |
| | | `python audit_model_readiness.py` | GO/NO-GO vs `snapshots_1m_normalized` |
| **Other audits** (domain-specific) | As needed | `python audit_gate_labels.py`, `python audit_expiry_data.py` | Read through each script header for scope |

### Tier C — App / auth / ML operations (not DB schema, but keeps the system up)

| Task | When | Command / action |
|------|------|-------------------|
| **Schwab auth failure** | API returns token errors | `python reauth_schwab.py` (per server messages) |
| **Model training / promotion** | Your ML workflow | `ml_scheduler.py` / project docs you use for training |

---

## Part 4 — Habits that harden the DB

1. After a **large backfill** that changes shared columns: run **`db_health_audit.py`**, then **`snapshot_normalizer.py`** if training uses the normalized table.  
2. When adding an important column: **write one sentence** on whether NULL is allowed and who fills it.  
3. For mission-critical analysis: filter to **gold-tier** rows only; don’t silently mix eras with different column coverage.

---

## Part 5 — View this guide inside the app

With the console server running, open:

- **`/guide/data-stewardship`** — this document  
- **`/guide/pipeline-quality`** — TQM-style checkpoints (ingest → audits → normalized → readiness)  
- **`/guide/training-and-maintenance`** — training + ops cadence (companion)  
- **`/ops`** — optional **click-to-run** panel (needs `ED_OPS_RUNNER=1`; see that doc)

The top bar includes **Ops & data** (this guide) and **Run tasks** (the ops panel).

---

*Last updated: maintenance runbook aligned with scripts in this repository. Extend the tables when you add new audits or backfills.*
