---
name: stream-db-switch
description: Use for STREAM-DB-SWITCH, the one-time move of production to the 5-session stream_capture.db. Lists each step with its check; Ed runs the renames and the delete.
---

Work item `STREAM-DB-SWITCH` in `ACTIVE_PROGRAM.md` (the design: `docs/DATA_FLOW.md` D4). The one-time
copy tool is not built yet; build it as its own pull request first and delete it after the switch.

1. After hours, stop both processes (the `deploy` skill, steps 1–3); show that neither port answers.
2. Run the copy tool against the production `stream_capture.db`: a new file with the writer's schema
   and receipt-time indexes, the last 5 trading sessions, every equity message and every contract of
   each ticker's soonest unexpired expiry. Show its counts per table and per session.
3. Ed renames the old file aside and the new one into place (never the agent: nothing under `data/` is
   moved or deleted by an agent). Show `dir` of the folder after.
4. Start both (the `deploy` skill, steps 4–5).
5. Check: the writer writes to the new file (its newest rows' times), the daily keep runs after the
   last option close and leaves 5 sessions, and the kept option rows are the soonest expiry ±5 strikes
   and the Flow pick. Show each query and its result.
6. On Ed's word, Ed deletes the old file. Remove the copy tool and the work item in the same PR.
