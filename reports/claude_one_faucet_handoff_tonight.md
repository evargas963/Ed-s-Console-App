# Claude — one-faucet-closeout-v1 — HISTORICAL (do not paste or execute)

> **HISTORICAL RECORD (stamped 2026-08-25, audit round 2).** A dated session prompt from the
> retired sole-writer/PM role model; its coordination files were deleted in the 2026-08-24
> teardown. The operator directs each session in chat.

**(original text follows) YOU = sole writer. Cursor = PM/auditor only. No reset. No kill-path edits by Cursor.**

## Roles / files
- `governance/sole_writer.json`: writer=claude · pm=cursor · auditor=cursor
- `governance/pm_mission.json`: mission_id=`one-faucet-closeout-v1` · status=`active`
- rebuild_spec (wipe-safe): `scratchpad/_one_faucet_closeout_rebuild_spec.md`

## Product state (DO NOT rebuild from zero)
Four kills + RC-199 charm already in WT/index (`static/chart.html`, `server.py`, `tests/test_levels_single_producer_v1.py`) — 42 tests green. **LAND to HEAD.** Rebuild from spec ONLY if wiped.

## Remaining (land)
**B3 · STRIP · PDH_PRECISION · B6**

## GATE_UNLOCK (PM decision — Option A)
Forward-only grandfather: patch institutional checks so NEW retroactive RC laws apply only to RC rows opened on/after **2026-07-28** (close-contract date) **OR** only to **RC-227+**.
- Do NOT remediate all history tonight
- Do NOT `--no-verify`
- Do NOT full checker rollback

## LEDGER
Do **not** edit `root_cause_log` until Cursor writers confirmed dead. Then patch **RC-227 + RC-214/215/223/225** trackers in SAME commit as product OR immediately after land if stash hazard. No ledger stuffing.

## SEQUENCE (exact)
0. Confirm no phantom Cursor writer (`sole_writer` + `pm_mission` both writer=claude)
1. Gate grandfather patch + tests (Option A)
2. Stage product + tests + RC
3. Commit with hooks (never `--no-verify`)
4. Restart via `start_ed_console.bat` (visible)
5. `python -m tools.ed_server_warn_quiet_window` — 300s PASS
6. Notify Cursor for audit (do not self-COMPLETE)

## Done criteria
Kills on HEAD · quiet PASS · scoreboard REMAINING=0 honest vs HEAD · Cursor audit

## Halt
`STOP` / `PAUSE` / `HANG IT UP` / `DO NOT CONTINUE`
