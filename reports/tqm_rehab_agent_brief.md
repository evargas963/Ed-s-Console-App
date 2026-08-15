# TQM rehab agent brief — the daily ACT + RE-MEASURE pass

`# log-law-ok: this is an executable BRIEF, not a work queue — the queue is
reports/tqm_queue_latest.json and the ledger is governance/root_cause_log.md.`

**Paste this to the writer agent (or run it yourself) after the daily rehab scan.**
It is the ACT and RE-MEASURE half of the loop RC-246 → RC-250 → RC-251 built:
MEASURE and TRIAGE are already automated by `tools/rehab_daily_scan.py`.

---

## Why this exists (read once, it changes how you work the list)

P1 (RC-246) moved seven ADVISORY checks off the blocking pre-commit path, buying **145 s per
commit**. The PM approved that on one condition: the debt stays **visible daily**. RC-250 wired
the caller that was promised and never written. RC-251 added the part that makes visibility
useful — location, trend, and a bounded list.

The backlog is ~3,360 findings. **That number is not a work order.** A repo-wide autofix of
1,256 ruff and 793 mypy findings would touch the money path with no behavioural test per
change, which is exactly how a "cleanup" becomes an incident. The loop exists so debt falls in
increments that can each be proven safe.

---

## Inputs (read all three; do not re-run the world)

| File | What it gives you |
|---|---|
| `reports/rehab_latest.md` | Human view: findings, advisory totals, hotspots, the queue |
| `reports/tqm_queue_latest.json` | The machine queue — **the only work list** |
| `reports/advisory_debt_latest.json` | Per-check tally + per-file hotspots |

---

## The pass

**1. TRIAGE — accept or kill each item, out loud.**

Work **only** `top_items` (max 5). Every item ships with `kill_criteria`. Killing an item is a
legitimate, expected outcome — say why in one line. An item nobody can refuse is not triage.

**2. ACT — smallest safe change, one item at a time.**

- **Preferred:** `ruff --fix` scoped to the **single file**, then run that file's own test module.
- **Types:** annotate the one function the error names. Do not restructure call sites.
- **Length / complexity:** extract *one* cohesive block, with a behavioural test pinning
  before == after on real inputs. RC-19 is the warning: a split to save seven lines added five
  circular imports. SHAPE metrics track but never block — they are never worth a correctness risk.
- **Orphan keys:** delete at the producer **and** prove no consumer reads it end-to-end.
  A static orphan can be a live field via dynamic access.

**Never:** drive-by refactors, opportunistic renames, or touching anything the item did not name.

**Never touch:** `data/ed_console.db` (+ `-wal`/`-shm`), `data/ed_console_claude.db`.
Not for cleanup, not for space, not for speed.

**3. RE-MEASURE — same harness, same turn.**

```bash
python tools/rehab_daily_scan.py
```

Then read `reports/tqm_queue_latest.json` and record **before → after** for
`advisory_total` and `delta` in your report and in the RC row. A win claimed in chat is not a
win. If the number did not move, say that; if it rose, find out what you did.

**4. LEDGER — open the row before the fix, close it with evidence.**

Front-loaded five-why applies (RC-66): the RC row opens the instant you find the issue, not
after. Close only with the measured delta and the reproduce command. If the host clock is still
missing, the schedule half stays **PARTIAL** — do not close it because the code half landed.

---

## Boundaries this brief will not cross

- Advisory checks **never** return to the blocking commit path (RC-246 stands; a control asserts it).
- No mass rewrites. Five items, each with a test.
- No database deletion or "disk cleanup" as part of quality work.
- RC-166 / RC-227 / RC-243 close **only** on a live mid-RTH `sqlite-contention` reading.
- No product rename unless the operator says so separately.

---

## If the queue is empty or stale

An empty queue with a non-zero total means hotspots were dropped between the gate and the scan —
that exact bug shipped once and produced a healthy-looking report with zero actionable items.
Check `hotspots` is non-empty in `advisory_debt_latest.json`, then in the queue JSON.

A **stale** report (>48 h) means the clock stopped: `reports/rehab_latest.md` will carry a P1
`rehab.advisory_report_stale` finding. Fix the schedule before working the list — a queue built
from an old measurement is worse than no queue.
