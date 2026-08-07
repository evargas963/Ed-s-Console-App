# Console error inventory v1

**Captured evidence:** stale Cursor uvicorn capture `terminals/151702.txt` (ended ~2026-08-02 10:57 CT; growth=0). Live :8000 stdout is external cmd (buffer now 9999). Re-sample live after restart before claiming wipe.

| Rank | Signature | Counts (151702) | Root | Weekend fix? |
|------|-----------|-----------------|------|--------------|
| P0 | `sqlite3.DatabaseError: database disk image is malformed` via `fetch_prior_net_gamma` | Traceback×131, XGB fail×524 | `ml_data_common.fetch_prior_net_gamma` ← XGB path | Fail-closed return None shipped this turn (no fake gamma). Integrity repair still ops. |
| P1 | sklearn `InconsistentVersionWarning` 1.8→1.9 | ~155 | `ml_predict._load_meta` | Pending: pin or re-export meta.pkl |
| P1 | SnapshotRow `charm_scope`/`charm_expiry` drop | ~135 hist | `db.SnapshotRow` now has fields + ALTER (RC-184/206 path) | Verify live console quiet after :8000 reload |
| P2 | `sqlite_bg_write_slow` fill_outcomes | ~28 | `db.fill_outcomes` | Indexes/query — pending |
| — | `non_trading_day` morning skip | 3 | calendar | Expected Sunday |

Reproduce historical counts: Select-String on the stale terminal capture (not live).
