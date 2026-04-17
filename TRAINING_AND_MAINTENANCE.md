# Training & maintenance — EdWebConsole

This doc is the **training + ops** companion to `DATA_STEWARDSHIP.md` (principles and DB-focused runbook).

---

## Why links can’t “just run Python” in the browser

Web pages **cannot** start programs on your PC by themselves (that would be a major security hole).  
This project’s **Run tasks** page (`/ops`) asks **your Ed Console server** — which already runs on your machine — to start **whitelisted** scripts. That only works if you **opt in** with an environment variable (see below).

---

## Click-to-run panel (`/ops`)

1. Stop the server if it is running.  
2. Set **`ED_OPS_RUNNER=1`** for the process that starts `uvicorn` / the console (same as you use today). Examples:  
   - PowerShell (session): `$env:ED_OPS_RUNNER = "1"` then start the server.  
   - Windows: add a user or system environment variable and restart the terminal.  
3. Start the server, open **`/ops`** (or top bar **Run tasks**).  
4. **Localhost only:** by default, only requests from this machine can trigger runs. To allow other PCs on the LAN (risky), set **`ED_OPS_ALLOW_REMOTE=1`** as well — only on networks you trust.

Long jobs (e.g. `ml_scheduler.py --run-now`) may run **many minutes or hours**; output is truncated in the browser. For full logs, still use a terminal when you need every line.

**Nightly wait-until-16:15 behavior** (`ml_scheduler.py --wait`) is **not** offered on `/ops` — it would tie up the server worker; use **Task Scheduler** or run `python ml_scheduler.py --wait` in a dedicated terminal.

---

## Document map

| In browser | File (project root) |
|------------|---------------------|
| `/guide/data-stewardship` | `DATA_STEWARDSHIP.md` |
| `/guide/pipeline-quality` | `PIPELINE_QUALITY.md` |
| `/guide/training-and-maintenance` | this file |
| `/ops` | `static/ops.html` + whitelist in `ops_runner.py` |

When you add a script to the click-to-run panel, **update `ops_runner.py`** (and optionally this doc). The panel builds its button list from that file.

---

## Live ingest controls (DB row rate)

| Variable | Default | Effect |
|----------|---------|--------|
| **`ED_DB_SNAPSHOT_THROTTLE`** | `1` (on) | At most **one `snapshots` INSERT per ticker per UTC minute** during full `_fetch_state` logging. Outcome backfill still runs every time. Set to `0` / `false` / `off` to disable (legacy high-frequency logging). |

See **`PIPELINE_QUALITY.md`** and **`/guide/pipeline-quality`** for the full TQM checkpoint list.

---

## Cadence cheat sheet (training & models)

| What | Suggested when | Command (terminal) |
|------|----------------|-------------------|
| Model readiness (GO/NO-GO on normalized 1m data) | Before any serious training | `python audit_model_readiness.py` |
| Raw training data audit | Before training; after big ingest | `python audit_training_data.py` |
| Full scheduler pipeline (parallel + cascade + promote) | After readiness passes; manual “train day” | `python ml_scheduler.py --run-now` |
| Nightly scheduler (wait for 16:15 ET weekdays) | Automation host only, dedicated process | `python ml_scheduler.py --wait` |
| Ad hoc full parallel train (alternative entry) | When you want `train_all` only | `python train_all.py` |
| Compare parallel vs cascade (SPY default in script) | Research / parity checks | `python train_compare.py` |

Optional flags (see each script’s `--help` if present): `ml_scheduler.py --force-retrain`, `--bypass-cache`.

---

## Cadence cheat sheet (DB / derived fields — overlaps with stewardship doc)

| What | Suggested when | Command |
|------|----------------|---------|
| DB health audit | After imports; weekly | `python db_health_audit.py` |
| Rematerialize `snapshots_1m_normalized` | After backfills touching shared training columns | `python snapshot_normalizer.py` |
| Flow from `option_chain_json` | After replay / empty flow | `python backfill_flow_imbalance.py` |
| Force flow from JSON | JSON is source of truth | `python backfill_flow_imbalance.py --force` then normalizer |
| VWAP / IV rank / pressure backfill | Sparse historical columns | `python backfill_snapshot_derived.py` |

---

## Predefined **sequences** on `/ops`

These run **in order** and **stop on first failure**:

| Sequence ID | Purpose |
|-------------|---------|
| `after_flow_backfill` | Conservative flow backfill → normalizer |
| `after_flow_force` | Force flow from JSON → normalizer |
| `pre_train_gate` | `db_health_audit` → `audit_model_readiness` |

---

## Schwab / auth (when the app “won’t connect”)

If the API reports token failure, reauth as documented in server messages, e.g. **`python reauth_schwab.py`**.

---

*Extend this file as your training and ops workflow grows.*
