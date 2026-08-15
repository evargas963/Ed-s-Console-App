# Claude — settle dirty tree, then rebuild (2026-08-03)

**Audience:** Claude (sole writer)  
**Author:** Cursor PM (halted — will not reset / checkout product paths)  
**Verdict feeding this prompt:** `SAFE_FOR_CLAUDE_REBUILD=no` (dirty staged `static/chart.html` + `server.py`; MM on mission/sole_writer; no UU unmerged paths)  
**HEAD:** `ead22055`  
**Mission:** `one-faucet-closeout-v1`  
**Rebuild spec:** `scratchpad/_one_faucet_closeout_rebuild_spec.md`

Cursor does **not** edit product code and will **not** `git reset` / `git checkout --` on mission scope. Claude owns settle + rebuild.

---

## PASTE TO CLAUDE (one block)

```
PIPELINE HALTED — Claude sole writer. Cursor PM halted: will NOT git reset / checkout product paths, will NOT edit chart.html/server.py, will NOT arm writer=cursor.

STATE (measured; SAFE_FOR_CLAUDE_REBUILD=no until YOU settle):
- HEAD: ead22055
- sole_writer.json → writer=claude, pm=cursor (normalize if MM/conflict-stale)
- pm_mission.json → status=active, mission_id=one-faucet-closeout-v1, writer=claude, rebuild_spec=scratchpad/_one_faucet_closeout_rebuild_spec.md
- Staged modified (dirty — unknown if YOUR partial closeout or Cursor damage): static/chart.html, server.py (~+95/-49 staged)
- MM on governance/pm_mission.json + governance/sole_writer.json (index≠WT possible)
- No UU unmerged paths; no <<<<<<< markers observed in mission/sole_writer at measure time — still VERIFY before edits
- Sibling halt cleared you to rebuild; you MUST settle the dirty chart/server tree FIRST

══════════════════════════════════════════════════════════════════
STEP 0 — Normalize SoD (before any product restore/edit)
══════════════════════════════════════════════════════════════════
1) Verify no conflict markers in governance/pm_mission.json and governance/sole_writer.json.
2) Ensure BOTH files are clean JSON with:
   - sole_writer: writer=claude, pm=cursor, auditor=cursor
   - pm_mission: status=active, mission_id=one-faucet-closeout-v1, writer=claude, pm=cursor,
     rebuild_spec=scratchpad/_one_faucet_closeout_rebuild_spec.md
3) Resolve any MM (index vs worktree) by making WT the SoD truth above, then stage those two governance files when you commit process slices. Do not leave dual versions.

══════════════════════════════════════════════════════════════════
STEP 1 — SETTLE dirty chart.html / server.py (MANDATORY before rebuild)
══════════════════════════════════════════════════════════════════
Do NOT assume the staged diffs are good. Do NOT ask Cursor to reset.

Measure staged (+ unstaged if any) diffs vs HEAD for:
  static/chart.html
  server.py

Classify EACH file as KEEP_PARTIAL or GARBAGE using the rebuild_spec kill checklist:

B3 (chart): computeDaily prior-session extraction REMOVED; enginePD() present;
  famLiveValues 'pd' engine-only (no daily.pdh/pdl/pdc fallback); draw/legend use enginePD.
STRIP (chart+server): client consumes strikes.today_side_sums (no in-browser gB+= side sum
  vs spot); get_terrain_strikes serves today_side_sums; charm row not vote-locked.
PDH_PRECISION (server): six level-family fields (vwap/pdh/pdl/pdc/orb_high/orb_low) use
  _raw_level / float_finite_or_none — NOT _fv rounding in state payload.
B6 (server): /api/price-levels returns 410 retired pointing to /api/levels.

Decision rule:
- GARBAGE (Cursor damage, unrelated churn, incomplete/wrong kill, or cannot prove it matches
  rebuild_spec): YOU restore that path from HEAD, then apply rebuild_spec cleanly.
    Example (you run; Cursor will not):
      git restore --source=HEAD --worktree --staged -- static/chart.html
      git restore --source=HEAD --worktree --staged -- server.py
    Restore only the file(s) classified GARBAGE.
- KEEP_PARTIAL (your incomplete closeout that already matches rebuild_spec direction): do NOT
  restore; finish the remaining rebuild_spec edits on top of the kept diff.
- Mixed: restore only GARBAGE files; keep KEEP_PARTIAL files and finish them.

Write a one-line settle verdict into your working notes / RC before coding, e.g.:
  SETTLE: chart=KEEP_PARTIAL|GARBAGE; server=KEEP_PARTIAL|GARBAGE; action=...

══════════════════════════════════════════════════════════════════
STEP 2 — Execute rebuild_spec END-TO-END
══════════════════════════════════════════════════════════════════
Read and execute scratchpad/_one_faucet_closeout_rebuild_spec.md completely:

1) B3 chart kills
2) STRIP chart + server today_side_sums
3) PDH_PRECISION raw state levels
4) B6 /api/price-levels → 410
5) Locks: tests/test_levels_single_producer_v1.py (seven tests in spec)
6) Ledger: re-land closeout as RC-227 (+ close-contract patches named in spec)
7) Scoreboard: reports/multi_faucet_one_faucet_closeout_latest.md + .json
   (REMAINING empty only with evidence)

Do not redo (already done / prior mission): quiet gate / fill_outcomes / RC-207 quarantine /
Tier-B session collapse; clocks TZ (RC-223); charm→bs_charm (RC-224); spot-binding (RC-225 / HEAD ead22055).

══════════════════════════════════════════════════════════════════
STEP 3 — Commit + quiet PASS
══════════════════════════════════════════════════════════════════
- pytest green for the closeout suite (spec: 24+1 / the seven locks + related)
- Commit coherent slices WITH hooks (never --no-verify); long-timeout pre-commit — do not kill mid-hook
- After server-touching land: restart via start_ed_console.bat (visible), prove LIVE process
- python -m tools.ed_server_warn_quiet_window → PASS (no demote); append verdict to RC-227
- Do not claim LIVE_ENFORCED / COMPLETE while DISK_ONLY or while OPEN RCs name this mission_id without FIXED/NEXT-DEPTH/OUT-OF-SCOPE

CURSOR STATUS: halted. Will not reset. You own settle + rebuild + commit + quiet PASS.
```

---

## Operator note

Paste the fenced block above into Claude as the single instruction set. Cursor remains PM/auditor only.
