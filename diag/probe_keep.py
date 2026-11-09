"""Probe: the test's scenario, timed per phase and per keep part.

usage: probe_keep.py <worktree> <poll: 0|1> [slow_ms]
poll=1 polls _old_rows every 20 ms as the test does; poll=0 polls nothing until the keep ends.
"""

import asyncio
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT))
POLL = sys.argv[2] == "1"

import stream_spine  # noqa: E402
import time_et  # noqa: E402
from tests import test_data_path_stream_kept_v1 as t  # noqa: E402

parts: list[tuple[float, float, int]] = []


class Timed(stream_spine.CaptureWriter):
    def _prune_part(self, conn):
        a = time_et.elapsed()
        before = sum(self._pruned.values())
        super()._prune_part(conn)
        wal = Path(str(self.db_path) + "-wal")
        size = wal.stat().st_size if wal.exists() else 0
        parts.append((a, time_et.elapsed() - a, sum(self._pruned.values()) - before, size))


def old_file(d: Path) -> Path:
    db = d / "old.db"
    w = stream_spine.CaptureWriter(db)
    conn = sqlite3.connect(db)
    for copy in range(t._COPIES):
        for m in t._MIX["messages"]:
            if m["service"] == "LEVELONE_OPTIONS":
                key = m["item"]["key"].upper()
                kind, msg = t.capture._message(m["service"], key, m["item"], m["schwab_ts"])
                msg["ts_recv"] = m["ts_recv"] - 7 * 86_400 - 60.0 * copy
                w.insert(f"{kind}.{key}", msg, conn=conn)
    conn.commit()
    conn.close()
    return db


def main():
    d = Path(tempfile.mkdtemp(dir=sys.argv[4] if len(sys.argv) > 4 else None))
    src = d.parent / "old_cached.db"
    if not src.exists():
        a = time_et.elapsed()
        shutil.move(old_file(d), src)
        print(f"old file built {time_et.elapsed() - a:.1f}s", flush=True)
    db = d / "stream_capture.db"
    shutil.copy(src, db)
    with sqlite3.connect(db) as c:
        print("journal_mode", c.execute("PRAGMA journal_mode").fetchone()[0])
    writer = Timed(db, batch_rows=1, batch_sec=0.01)
    bus = stream_spine.MessageBus()
    polls = [0]
    poll_max = [0.0]

    def old_rows():
        polls[0] += 1
        a = time_et.elapsed()
        n = t._old_rows(db)
        poll_max[0] = max(poll_max[0], time_et.elapsed() - a)
        return n

    import threading

    hold = threading.Event()

    def overlapping_reader(offset: float):
        # INDUCED: two readers, each a COUNT then a held snapshot, offset so one is always open
        time.sleep(offset)
        while not hold.is_set():
            c = sqlite3.connect(db)
            c.execute("BEGIN")
            c.execute(
                "SELECT COUNT(*) FROM stream_options_quotes_raw WHERE ts_recv < ?",
                (t._et(t._FIVE_SESSIONS),),
            ).fetchone()
            time.sleep(0.2)
            c.close()

    if sys.argv[2] == "2":
        for off in (0.0, 0.1):
            threading.Thread(target=overlapping_reader, args=(off,), daemon=True).start()

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(
            writer.run(bus.subscribe("", policy=stream_spine.LOG), stop=stop)
        )
        await asyncio.sleep(0)
        t0 = time_et.elapsed()
        writer.prune(t._et(t._FIVE_SESSIONS))
        sent = t._publish_mix(bus, {m["service"] for m in t._MIX["messages"]})
        t1 = time_et.elapsed()
        while writer.status()["rows_written"] < sent:
            await asyncio.sleep(0.02)
        t2 = time_et.elapsed()
        left = old_rows()
        if POLL:
            while old_rows() != 0:
                await asyncio.sleep(0.02)
        else:
            while writer._prune:
                await asyncio.sleep(0.02)
        t3 = time_et.elapsed()
        stop.set()
        hold.set()
        await task
        print(
            f"sent {sent} publish {t1 - t0:.1f}s written {t2 - t1:.1f}s old_left {left} "
            f"keep_after {t3 - t2:.1f}s total {t3 - t0:.1f}s polls {polls[0]} "
            f"poll_max {poll_max[0]:.2f}s parts_sum {sum(p[1] for p in parts):.1f}s"
        )
        for i, (at, dur, n, wal) in enumerate(parts):
            print(
                f"  part {i:2d} at {at - t0:6.2f}s took {dur:5.2f}s removed {n} wal {wal >> 20}MB"
            )

    asyncio.run(go())
    shutil.rmtree(d, ignore_errors=True)


main()
