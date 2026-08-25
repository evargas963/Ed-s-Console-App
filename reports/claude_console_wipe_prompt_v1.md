# Claude prompt — console wipe pack — HISTORICAL (stamped 2026-08-25; a dated session prompt, not a standing work order)

CONTEXT: Inventory in `reports/console_error_inventory_v1.md`. Stale capture counts from `151702.txt`. Live :8000 is external cmd — do not claim wiped without tee/sample after restart.

RANKED (prefer offline / no RTH):

1. **P0** — SQLite malformed → `ml_data_common.fetch_prior_net_gamma` (fail-closed None already shipped; run `PRAGMA integrity_check` on `data/ed_console.db`; repair/restore with operator OK; never fabricate gamma).
2. **P1** — sklearn 1.8.0 meta.pkl vs runtime 1.9.0 via `ml_predict._load_meta` (~155 warnings). Pin or re-export under 1.9; log-once after gate.
3. **P1** — Confirm SnapshotRow `charm_scope`/`charm_expiry` persist (fields exist in `db.py`); if live still drops, find remaining kwargs path.
4. **P2** — `db.fill_outcomes` `sqlite_bg_write_slow` (~28): indexes/query tighten.
5. Expected Sunday: `non_trading_day` — not a defect.

CONSTRAINTS: UNIVERSAL tickers; no kill Claude :8777 without operator OK; show before/after console sample counts; tests for fail-closed path; write `reports/console_wipe_proof_v1.md`.
