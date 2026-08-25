# mc_sigma_value mixed-unit blast area — measured 2026-08-25 (RC-478)

Independent-audit finding: historical `mc_sigma_value` contains mixed units even though
current production semantics are fixed. This report is the measured blast area. All DB
numbers were re-derived 2026-08-25 against the live database opened READ-ONLY
(`file:...ed_console.db?mode=ro`); each table carries its reproduce command. No data was
modified. The remediation decision is the operator's (RC-478).

## Semantics: current vs historical

- **Current contract** (main @ `2a8a9712`): annualized decimal volatility, post regime
  multiplier, path-independent. Producer contract `monte_carlo.py:253-277`; canonical key
  `assumptions["sigma_annualized"]` (`monte_carlo.py:425`); consumer read order
  `sigma_annualized -> scaled_sigma -> blended_sigma` (`bayesian_fusion.py:764`).
- **Fixing commit:** `4c528113` ("TEARDOWN: one sigma semantic per Monte Carlo field",
  2026-08-24, merged via PR #191/#192). Reproduce:
  `git log -S mc_sigma_value --oneline -- monte_carlo.py bayesian_fusion.py market_state.py server.py db.py`
- **Old behavior:** the read was `scaled_sigma or blended_sigma`
  (`git show "4c528113^:bayesian_fusion.py"`, line 762): GARCH path stored a per-bar
  average (per-5-minute-bar until `5869081f` 2026-07-08, per-1-minute-bar after); blend
  path stored annualized. One column, three-plus scales.
- **Deployment status:** the production checkout does NOT have the fix —
  `git merge-base --is-ancestor 4c528113 HEAD` fails there (HEAD `82f59282`). Zero
  annualized-unit rows exist in the DB yet.
- Pre-`a645a894` (2026-06-19 squash) history is not in git, so the code that produced the
  March–May scale is unrecoverable.

## Storage and measured era split

Stored in `snapshots.mc_sigma_value` (`db.py:1294`, migration `db.py:2783`) and the
materialized `snapshots_1m_normalized.mc_sigma_value` (cull-ledger verdict KEEP_LIVE,
`governance/artifacts/snapshot_column_cull_ledger.json`).

`snapshots`: 365,797 rows, 188,399 non-null. `snapshots_1m_normalized`: 248,954 rows,
156,406 non-null. Reproduce (this and the era table):

```
.venv/Scripts/python.exe -c "import sqlite3; con=sqlite3.connect(r'file:data/ed_console.db?mode=ro',uri=True); c=con.cursor(); print(c.execute('SELECT COUNT(*), COUNT(mc_sigma_value) FROM snapshots').fetchone()); [print(r) for r in c.execute(\"SELECT CASE WHEN mc_vol_source='blend' THEN 'blend' WHEN ts_utc<1783651965 THEN 'garch_pre' ELSE 'garch_post' END era, COUNT(*), MIN(mc_sigma_value), MAX(mc_sigma_value), AVG(mc_sigma_value), AVG(mc_sigma_value<0.01) FROM snapshots WHERE mc_sigma_value IS NOT NULL GROUP BY era\")]"
```

| era class (cut = epoch 1783651965, the `5869081f` instant) | rows | min | max | avg | % < 0.01 | unit |
|---|---|---|---|---|---|---|
| blend (any date) | 2,315 | 0.0301 | 4.4007 | 0.4963 | 0.0% | annualized (matches current contract) |
| garch pre-2026-07-08 | 133,528 | 0.0002 | 2.1836 | 0.0489 | 21.1% | mixed per-bar scales, cadence unverifiable |
| garch post-2026-07-08 | 52,556 | 0.0002 | 0.0223 | 0.0016 | 99.4% | per-1-minute-bar |

~30x average gap between the two garch eras, ~310x between garch-post and blend — in one
column. **No clean per-row boundary exists before 2026-07-08**: SPY garch-only daily bands
interleave intraday (2026-04-08 spans 0.0095–0.1882 in one day; 2026-04-09 spans
0.0003–0.0975 — reproduce with the same connection,
`SELECT date(ts_utc,'unixepoch'), MIN(mc_sigma_value), MAX(mc_sigma_value) FROM snapshots WHERE ticker='SPY' AND mc_vol_source!='blend' AND mc_sigma_value IS NOT NULL GROUP BY 1`).
Neither date nor `mc_vol_source` decides the unit per-row in that era.

The one crisp boundary: last legacy write at rowid 341304, ts_utc 1786047287.027
(2026-08-06T20:14:47Z); all `mc_sigma_value` after it is NULL. Reproduce:
`SELECT MAX(rowid) FROM snapshots WHERE mc_sigma_value IS NOT NULL`.

## Consumer inventory (current main)

Repo-wide search of `mc_sigma` (both checkouts, identical result set):

| consumer | reads history? | contaminated? |
|---|---|---|
| `monte_carlo.py` → `bayesian_fusion.py:764` → `market_state.py:1806` → `server.py:8397` → `db.py` | no — live write chain | n/a (they created the mix) |
| `verify_snapshot_pipeline.py` | latest row only | clean |
| `inspect_trading_data.py` | yes, prints values to a human | display-only, low |
| ML training (`ml_train.py:352` `SELECT * FROM snapshots_1m_normalized`) | yes, BUT feature lists (`ml_train.py:194-270`) exclude all `mc_` columns | clean |
| `features/canonical_contract.py` (v1_1m_mvp) | not in contract | clean |
| MC→fusion features (`monte_carlo.py:115` → `mc_fusion_adjustment.py`) | live only; sigma field not carried | clean |
| study runners (`tools/study_pin_*`, `tools/research/d2_*`, terrain, liquidity) | never read the column | clean |
| current UI (`static/`) | no reference | clean |

**Measured conclusion: the column is write-only plus diagnostics on current main. No
model, study, backtest, or UI reads the mixed history — the liability is latent, not
active.** Any future study that adopts the column inherits a ~310x unit mix silently;
nothing in the data marks it.

## Contaminated studies

`reports/` search for `mc_sigma` finds only `reports/ui_transport/universal_card_fidelity_2026-07-06..10.json`
(transport-fidelity checks, not statistical studies; they do show mixed scales reached the
UI payload on 2026-07-10: SPY 0.0369 vs QQQ 0.2384). **The contaminated Find & Prove
study list is empty.**

## Remediation options (operator decision — RC-478; no change made here)

1. **Backfill-convert (partial only).** Blend rows: identity. Garch post-2026-07-08:
   ×sqrt(98,280) ≈ ×313.5 (`ANNUALIZED_HOURS=252*6.5`, `BAR_MINUTES=1` —
   `monte_carlo.py:30,56,245`). The 133,528 garch pre-2026-07-08 rows are NOT convertible
   per-row (cadence changed mid-era; producing code predates repo history). A full-column
   convert is impossible; a partial convert still needs option 2's flag for the pre-July era.
2. **Quarantine via unit flag.** Add `mc_sigma_unit` (`annualized` / `per_bar_1m` /
   `legacy_unverified`) stamped by the era rules above on both tables; readers filter.
   Migration on the live DB + writer change; preserves data; makes the mix machine-visible.
3. **Leave-and-gate.** No data change; register the column as MIXED_UNIT and gate
   study/training reads of `mc_sigma_value`. Cheapest; consistent with the measured
   zero-consumer state.

Whichever is chosen: production must first pull main so the `4c528113` serve-time fix is
actually running.

## Side-finding (own tracker: RC-479)

All `mc_*` snapshot columns stopped being written at 2026-08-06T20:14:47Z while `fusion_*`
columns continue: 34,240 snapshots since that instant carry `COUNT(mc_paths)=0,
COUNT(mc_vol_source)=0` but `COUNT(fusion_dominant)=26,004`. Reproduce:
`SELECT COUNT(*), COUNT(mc_paths), COUNT(mc_vol_source), COUNT(fusion_dominant) FROM snapshots WHERE ts_utc > 1786047287.027`.
Monte Carlo has been silently unavailable in production for ~18 days. Suspected trigger
`[UNVERIFIED]`: `resolve_monte_carlo_stack_inputs` raising `MonteCarloStackInputError`
(`signals.py:884-889`) under the RC-435 withheld-inputs/abstain lineage; confirmation
needs the live process after the production pull.
