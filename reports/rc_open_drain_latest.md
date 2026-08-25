# RC open-class drain — LIVE POINTER (not a queue)

`# this file is a POINTER to the live ledger and deliberately holds no work rows.`

**LOG LAW (operator 2026-08-04; the `tools/log_law.py` mechanism was retired 2026-08-24 —
`governance/retired_checks.md` — the principle survives as this pointer):** closable work has
exactly two homes. This file previously carried 21 `| RC-… | OPEN |` rows — a third work queue
that went stale the moment it was written, so whichever list a reader opened looked
authoritative while the other rotted. It is now a pointer. Overdue-OPEN rows are blocked
mechanically by `check_root_cause_log` + `check_open_item_cap`.

| Kind of work | Sole home | Vocabulary |
|---|---|---|
| Defects | `governance/root_cause_log.md` | OPEN → FIXED → CLOSED |
| Epistemic claims | `governance/unproven_register.md` | UNPROVEN → PROVEN / DISPROVED / REMEDIATED |
| Telemetry (`sod_drift_events.jsonl`, quarantine, flip logs) | the `.jsonl` itself | events — **never** a to-do list |
| Triage notes (`reports/*.md`) | wherever written | dated snapshots, never current state |

## Live counts

Do not read a number out of this file — run the measurement:

```bash
python tools/log_law.py
```

It prints the live open-class count from the defect ledger and fails on any third queue or any
overdue epistemic row.

## Drain of 2026-08-04 (PM law: ZERO REPO DEBT TODAY)

Open-class (OPEN+PARTIAL) went **19 → 3** in one session, every close carrying measured
end-to-end evidence rather than a status flip. Closed this drain: RC-58, RC-102, RC-107, RC-110,
RC-115, RC-117, RC-124, RC-165, RC-168, RC-177, RC-178, RC-210, RC-218, RC-219, RC-220, RC-222 —
plus RC-229, RC-232, RC-233, RC-234, RC-235 earlier the same day.

Three of those closes were **defect discoveries made by the drain itself**, not paperwork:

- **RC-168** root finally reached — the tick accumulator differenced a *cumulative* vendor
  counter with no staleness bound, so a ticker left unpolled for minutes dumped its whole
  multi-minute volume delta into one bar. Isolated by measurement: 601 non-auction 10× spikes in
  24,284 accumulator bars (2.5%) against 8 in 13,017 vendor bars (0.06%) for the same name over
  the same period — a 40× rate from the same market. The largest apparent outlier was
  *exonerated* as the real 16:01 closing auction.
- **RC-124** — the owed rendered proof caught the pin's decisiveness being deleted by the
  coincident-wall merge (axis read `750.00 PWALL·PIN` while the payload carried 19.8%).
- **RC-210** — the "still lost" desk work was never lost; four fixtures were missing the
  completeness question and had only ever passed outside market hours.

### Still open — all three operator-gated on physical resources, named rather than hidden

| Row | Blocker (measured today) | Unblocks with |
|---|---|---|
| RC-166 | live tier-1 write-lock contention: `lock_wait_max_ms` 81,789 lifetime / 53,428 recent, and a 23,455 ms wait during the quiet window | operator-timed mid-RTH actions: WAL truncate (181 MB), accrual connection config, BARS_WORKERS reduction |
| RC-207 | mirror `snapshots_1m_normalized` still malformed (`SELECT` raises, `COUNT` answers 210,921); clone needs ~27 GB, drive C has 24 GB free | operator frees ≥3 GB, writers stopped, then `python tools/rebuild_snapshots_1m_normalized_v1.py --execute-clone` |
| RC-227 | quiet-window PASS, which RC-166's contention blocks — **no quiet PASS is claimed** | closes with RC-166 |

The quiet gate's honesty is itself proven here: today's severity calibration (RC-236) moved
routine absorbed lock waits to INFO and killed the ATR warmup warning, yet the 23.5 s distress
wait still WARNs and still fails the gate. The gate now measures a real defect instead of noise —
it was not tuned into passing.

### Epistemic backlog — why it is not zero, and why that is correct

Six `UNPROVEN` rows remain, **none overdue** (dues 2026-08-14 → 08-28). They are pre-registered
hypotheses whose protocols require data that has not accrued yet (wide-chain captures began
2026-07-21; 12 dates exist today) or a clean post-repair era that RC-207 gates. Forcing them to a
verdict today would mean citing contaminated or underpowered data — the one outcome that turns a
research ledger into a liability, and the "no MEASURED n=1 PROVEN theater" clause of this same PM
law. The enforceable bar is therefore **zero OVERDUE** epistemic rows, which `tools/log_law.py`
checks on every run, and which is green.
