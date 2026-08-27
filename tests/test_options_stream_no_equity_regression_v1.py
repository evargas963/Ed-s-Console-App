"""OPTIONS FLOW — wiring options must not be able to disturb the equity/book stream.

WHAT IS AT RISK. order_flow_streaming owns the console's ONE StreamClient. LEVELONE_EQUITIES,
NASDAQ_BOOK and NYSE_BOOK are what the console actually depends on: the live quote path, the
book panels, the money path. Options collection is additive and, today, off. It must therefore
be impossible for the options code to change what the equity path does - not merely intended to
be harmless.

Three distinct failure routes are checked, because they fail differently:
  1. Options handlers registering could raise and abort the setup BEFORE the equity subscribe.
  2. Options collection could subscribe symbols even when disabled, spending stream keys the
     equity path needs and changing what the account is subscribed to.
  3. The options frame handler runs INLINE on the shared message loop, so it must stay O(1) and
     must swallow its own errors rather than propagating into the loop.

Nothing here infers dealer ownership, aggressor side, or intent.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import order_flow_streaming as ofs  # noqa: E402  — the UI stream (equity/book handlers)
import options_stream_collect as osc  # noqa: E402  — the daemon-owned options Collect subsystem


class _Client:
    """Records what was registered and subscribed, and can be told to fail on options."""

    def __init__(self, fail_options: bool = False):
        self.registered: list[str] = []
        self.subscribed: list[tuple[str, tuple]] = []
        self.fail_options = fail_options

    def _reg(self, name):
        def _add(_handler):
            if self.fail_options and "option" in name:
                raise RuntimeError("vendor refused the options handler")
            self.registered.append(name)
        return _add

    def __getattr__(self, name):
        if name.startswith("add_") and name.endswith("_handler"):
            return self._reg(name)
        raise AttributeError(name)


def test_options_are_not_subscribed_while_collection_is_disabled(monkeypatch):
    """OFF must mean OFF: no options symbols subscribed, no keys spent."""
    monkeypatch.delenv(osc.ED_OPTIONS_STREAM_ENV, raising=False)
    assert osc.options_streaming_enabled() is False

    calls: list[str] = []

    class _Sub:
        async def level_one_option_subs(self, *_a, **_k):
            calls.append("level_one_option_subs")

        async def options_book_subs(self, *_a, **_k):
            calls.append("options_book_subs")

    asyncio.run(osc.start_options_collection(
        _Sub(), bus=object(), equity_symbols=3, equity_key_services=2))
    assert calls == [], f"options were subscribed while collection is disabled: {calls}"
    assert osc.options_stream_status()["subscribed_contracts"] == 0


def test_registering_options_handlers_cannot_abort_stream_setup():
    """A vendor/library failure on the options handlers must not take the equity path with it.

    Registration happens BEFORE login and before the equity subscribe, so an exception escaping
    here would leave the console with no quote stream at all.
    """
    c = _Client(fail_options=True)
    # Must not raise.
    osc.register_options_handlers(c, lambda service: (lambda msg: None))
    # And a client missing the options methods entirely (older library) must also be tolerated.

    class _Old:
        def __getattr__(self, name):
            if name.startswith("add_") and "option" in name:
                raise AttributeError(name)
            return lambda *_a, **_k: None

    osc.register_options_handlers(_Old(), lambda service: (lambda msg: None))


def test_the_ui_stream_registers_equity_handlers_and_does_not_touch_options():
    """The UI stream is observational: three equity services, ONE client, NO options Collect.

    Options collection moved to the capture daemon (the single stream owner), so the UI loop must
    register the equity/book handlers the console depends on and touch nothing options.
    """
    import inspect

    src = inspect.getsource(ofs._run_stream_loop)
    for required in ("add_nasdaq_book_handler", "add_nyse_book_handler",
                     "add_level_one_equity_handler"):
        assert required in src, f"{required} is no longer registered — equity path regression"
    assert "StreamClient(" in src and src.count("StreamClient(") == 1, (
        "more than one StreamClient is constructed — a second socket is a second source of truth")
    for banned in ("register_options_handlers", "start_options_collection",
                   "stop_options_collection", "_options_frame_handler"):
        assert banned not in src, (
            f"the UI stream loop still references {banned!r} — options Collect must live only in "
            f"the capture daemon, not on the UI socket")


def test_the_options_handler_publishes_and_swallows_its_own_errors(monkeypatch):
    """The handler runs INLINE on the shared message loop. An exception escaping it would
    propagate into the loop that services equities and books.

    DRIVEN, not read. The handler now PUBLISHES to the daemon bus (no SQLite on the loop — the one
    CaptureWriter persists on its own task), so the containment is exercised with a bus.publish
    that actually raises, and the hand-off is proven by a recording bus. RC-308: if the property is
    behaviour, assert the behaviour.
    """
    class _ExplodingBus:
        def __init__(self):
            self.calls = 0

        def publish(self, *_a, **_k):
            self.calls += 1
            raise RuntimeError("bus exploded")

    boom = _ExplodingBus()
    monkeypatch.setattr(osc, "_options_bus", boom, raising=False)
    handler = osc._options_frame_handler("LEVELONE_OPTIONS")
    handler({"content": [{"key": "SPY   260828C00600000"}]})   # must not raise
    assert boom.calls == 1, "the handler never reached the bus, so nothing was contained"

    # ...and with no bus attached at all it must still be inert, not raise.
    monkeypatch.setattr(osc, "_options_bus", None, raising=False)
    osc._options_frame_handler("OPTIONS_BOOK")({"content": [{"key": "SPY"}]})

    # It must HAND OFF exactly once, to the right topic KIND, with the vendor frame + service +
    # receive clock in the payload — and no SQLite touched on this thread.
    class _RecordingBus:
        def __init__(self):
            self.pub: list[tuple] = []

        def publish(self, topic, msg):
            self.pub.append((topic, msg))

    rec = _RecordingBus()
    monkeypatch.setattr(osc, "_options_bus", rec, raising=False)
    monkeypatch.setattr(osc, "_options_offered", 0, raising=False)
    osc._options_frame_handler("LEVELONE_OPTIONS")({"content": [{"key": "SPY   260828C00600000"}]})
    assert len(rec.pub) == 1, "the handler did not hand the frame off exactly once"
    topic, msg = rec.pub[0]
    assert topic.startswith("optionchain."), f"LEVELONE_OPTIONS routed to wrong topic kind: {topic}"
    assert msg["service"] == "LEVELONE_OPTIONS" and "frame" in msg and "received_ts_ms" in msg
    assert osc._options_offered == 1, "the offered counter did not advance (drop accounting broken)"

    # OPTIONS_BOOK rides the other kind.
    rec2 = _RecordingBus()
    monkeypatch.setattr(osc, "_options_bus", rec2, raising=False)
    osc._options_frame_handler("OPTIONS_BOOK")({"content": [{"key": "SPY"}]})
    assert rec2.pub and rec2.pub[0][0].startswith("optionbook.")


def test_stopping_options_collection_is_safe_when_nothing_started():
    """Shutdown runs in the daemon's finally; it must be harmless in every state.

    Teardown is async now (it awaits the cancelled rotation task), so it is actually driven here —
    the previous version called it synchronously and left the coroutine un-awaited, a false pass.
    """
    osc._vendor_held = {s: set() for s in osc.OPTIONS_SERVICES}
    osc._coverage_open = {s: set() for s in osc.OPTIONS_SERVICES}
    osc._options_rotation_task = None
    osc._options_offered = 0
    osc._options_written = 0
    asyncio.run(osc.stop_options_collection("test"))     # must not raise
    assert osc._active_stream is None and osc._options_bus is None


def test_enabling_is_env_gated_and_not_settable_from_a_stale_module_global(monkeypatch):
    """The gate must be read at call time, so an operator turning it on or off is honoured
    without a code path caching the answer from import time."""
    monkeypatch.setenv(osc.ED_OPTIONS_STREAM_ENV, "1")
    assert osc.options_streaming_enabled() is True
    monkeypatch.setenv(osc.ED_OPTIONS_STREAM_ENV, "0")
    assert osc.options_streaming_enabled() is False
    monkeypatch.delenv(osc.ED_OPTIONS_STREAM_ENV, raising=False)
    assert osc.options_streaming_enabled() is False
    assert os.environ.get(osc.ED_OPTIONS_STREAM_ENV) is None
