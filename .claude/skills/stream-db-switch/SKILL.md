---
name: stream-db-switch
description: Use for what is left of STREAM-DB-SWITCH, production's move to the 5-session stream_capture.db: checking the daily keep on the new file, then the old file's deletion, which Ed runs.
---

Work item `STREAM-DB-SWITCH` in `ACTIVE_PROGRAM.md` (the design: `docs/DATA_FLOW.md` D4). The old
file is kept in `data/old_stream_capture_2026-10-13/`.

1. Check: the writer writes to `data/stream_capture.db` (its newest rows' times), the daily keep runs
   after the last option close and leaves 5 sessions, and the kept option rows are the soonest expiry
   ±5 strikes and the Flow pick. Show each query and its result.
2. On Ed's word, Ed deletes the old file and the copy's empty `data/stream_capture_new.db-wal` and `-shm`
   (the delete-protection: the `deploy` skill). Remove the work item and this skill in the same PR.
