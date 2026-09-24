"""live_push.FieldHistory keeps, per topic, the latest message carrying each field -- at a
cost proportional to the message, not to everything ever seen.

MEASURED 2026-09-24 08:46 CT: py-spy caught the capture daemon's event loop inside
FieldHistory.record rebuilding a set of every field of every topic on every message, while
the whole live feed went silent for seconds (all services DEGRADED, push handshakes timing
out). The replacement keeps a reference count per stored message."""
from __future__ import annotations

import random
import time

from app.market_data.schwab.streaming.live_push import FieldHistory


class _Reference:
    """The old, obviously-correct semantics (latest message per (topic, field))."""

    def __init__(self):
        self.by_topic = {}
        self.msgs = {}
        self.seq = 0

    def record(self, topic, msg):
        body = FieldHistory.payload(topic, msg)
        ts = msg.get("ts_recv")
        if body is None or not isinstance(ts, (int, float)):
            return
        self.seq += 1
        self.msgs[self.seq] = (topic, msg)
        f = self.by_topic.setdefault(topic, {})
        for k in body:
            f[k] = (float(ts), self.seq)

    def replay(self):
        ids = sorted({(ts, sid) for f in self.by_topic.values() for ts, sid in f.values()})
        return [self.msgs[sid] for _ts, sid in ids]


def _msg(rng, t, topic):
    fields = rng.sample(["LAST_PRICE", "BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE",
                         "TOTAL_VOLUME", "NET_CHANGE_PERCENT", "MARK"], rng.randint(0, 4))
    key = "native" if topic.startswith("quote.") else "content"
    return {"ts_recv": t, key: {f: rng.random() for f in fields}}


def test_replay_matches_latest_message_per_field_semantics():
    rng = random.Random(7)
    new, ref = FieldHistory(), _Reference()
    topics = [f"quote.S{i}" for i in range(30)] + [f"optquote.O{i}" for i in range(30)]
    for i in range(20_000):
        topic = rng.choice(topics)
        m = _msg(rng, 1_000.0 + i * 0.01, topic)
        new.record(topic, m)
        ref.record(topic, m)
        if i % 997 == 0:
            assert new.replay() == ref.replay()
    assert new.replay() == ref.replay()
    # nothing is kept that no field points at
    live = {sid for f in new._by_topic.values() for _t, sid in f.values()}
    assert set(new._msgs) == live == set(new._refs)


def test_record_cost_does_not_grow_with_the_number_of_topics():
    rng = random.Random(3)
    h = FieldHistory()
    fields = [f"F{i}" for i in range(40)]
    for i in range(2_000):                                   # 2,000 topics x 40 fields seen
        h.record(f"optquote.O{i}", {"ts_recv": float(i), "content": {f: 1.0 for f in fields}})
    t0 = time.perf_counter()
    for i in range(20_000):
        h.record(f"optquote.O{rng.randrange(2_000)}",
                 {"ts_recv": 5_000.0 + i, "content": {"F1": 2.0, "F2": 3.0}})
    per_msg_us = (time.perf_counter() - t0) / 20_000 * 1e6
    # the old rescan walked all 80,000 (topic, field) entries per message (~ms each)
    assert per_msg_us < 100, per_msg_us
