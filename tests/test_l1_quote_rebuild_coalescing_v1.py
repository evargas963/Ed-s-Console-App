"""planes/l1_events rebuilds a ticker's header projection AT ONCE on a quote, coalescing
bursts to one running + one trailing rebuild (audit 2026-09-24: a 120 ms timer restarted on
every message delayed every tick and spawned a thread per message)."""
from __future__ import annotations

import threading
import time

import planes.l1_events as ev


def test_first_quote_rebuilds_immediately_and_a_burst_coalesces_to_one_trailing(monkeypatch):
    calls: list[float] = []
    gate = threading.Event()

    def rebuild(t):
        calls.append(time.monotonic())
        if len(calls) == 1:
            gate.wait(2)            # hold the first rebuild while a burst arrives

    monkeypatch.setattr(ev, "_rebuild_quote_fn", rebuild)
    monkeypatch.setattr(ev, "_inflight", {})
    t0 = time.monotonic()
    ev.notify_quote_updated("ZZCOAL")
    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.001)
    assert calls and calls[0] - t0 < 0.1, "the first quote must rebuild at once, not after a timer"
    for _ in range(50):
        ev.notify_quote_updated("ZZCOAL")   # burst while the first rebuild runs
    gate.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and (len(calls) < 2 or ev._inflight["ZZCOAL"]["running"]):
        time.sleep(0.005)
    assert len(calls) == 2, "a burst coalesces to exactly one trailing rebuild of the newest row"
    assert ev._inflight["ZZCOAL"] == {"running": False, "dirty": False}


def test_no_timer_thread_per_message():
    src = open(ev.__file__, encoding="utf-8").read()
    assert "threading.Timer(" not in src
