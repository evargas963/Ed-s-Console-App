---
name: stream-db-switch
description: Use for STREAM-DB-SWITCH, the one-time move of production to the 5-session stream_capture.db. Lists each step with its check; Ed runs the renames and the delete.
---

Work item `STREAM-DB-SWITCH` in `ACTIVE_PROGRAM.md` (the design: `docs/DATA_FLOW.md` D4). Step 2 needs
the one-time copy tool: if it is not on `main`, build it as its own pull request first. It is deleted
after the switch (step 6).

1. After hours, stop both processes (the `deploy` skill, steps 1–3); show that neither port answers.
2. Run the copy tool against the production `stream_capture.db`: a new file with the writer's schema
   and receipt-time indexes, the last 5 trading sessions, every equity message and each session's 0DTE
   option contracts (the nearest expiration for a ticker with none that day):
   `python tools/stream_db_switch_copy.py data/stream_capture.db data/stream_capture_new.db` (it refuses
   an existing new file and spill files beside the old one). Show its counts per table and per session.
   If it stops with an error, the old file is untouched (read-only) and the new file is partial: report
   the error to Ed, start both again on the old file (step 4), and Ed deletes the partial file before a
   second run.
3. Show `dir data` with no `stream_capture_new.db-wal` left. Ed renames the old file aside and the new
   one into place (never the agent: nothing under `data/` is moved or deleted by an agent). Show `dir`
   of the folder after.
4. Start both (the `deploy` skill, steps 4–5).
5. Check: the writer writes to the new file (its newest rows' times), the daily keep runs after the
   last option close and leaves 5 sessions, and the kept option rows are the soonest expiry ±5 strikes
   and the Flow pick. Show each query and its result.
6. On Ed's word, Ed deletes the old file. Remove the copy tool, the work item and this skill in the same
   PR.
