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

import order_flow_streaming as ofs  # noqa: E402


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
    """OFF must mean OFF: no options symbols subscribed, no writer started, no keys spent."""
    monkeypatch.delenv(ofs.ED_OPTIONS_STREAM_ENV, raising=False)
    assert ofs.options_streaming_enabled() is False

    calls: list[str] = []

    class _Sub:
        async def level_one_option_subs(self, *_a, **_k):
            calls.append("level_one_option_subs")

        async def options_book_subs(self, *_a, **_k):
            calls.append("options_book_subs")

    asyncio.run(ofs._start_options_collection(_Sub()))
    assert calls == [], f"options were subscribed while collection is disabled: {calls}"
    assert ofs._options_ingest is None, "a writer was started while collection is disabled"
    assert ofs.options_stream_status()["subscribed_contracts"] == 0


def test_registering_options_handlers_cannot_abort_stream_setup():
    """A vendor/library failure on the options handlers must not take the equity path with it.

    Registration happens BEFORE login and before the equity subscribe, so an exception escaping
    here would leave the console with no quote stream at all.
    """
    c = _Client(fail_options=True)
    # Must not raise.
    ofs._register_options_handlers(c, lambda service: (lambda msg: None))
    # And a client missing the options methods entirely (older library) must also be tolerated.

    class _Old:
        def __getattr__(self, name):
            if name.startswith("add_") and "option" in name:
                raise AttributeError(name)
            return lambda *_a, **_k: None

    ofs._register_options_handlers(_Old(), lambda service: (lambda msg: None))


def test_equity_and_book_handlers_are_still_registered_alongside_options():
    """The three services the console depends on must all still be attached."""
    import inspect

    src = inspect.getsource(ofs._run_stream_loop)
    for required in ("add_nasdaq_book_handler", "add_nyse_book_handler",
                     "add_level_one_equity_handler"):
        assert required in src, f"{required} is no longer registered — equity path regression"
    # And options registration must come from the shared helper, not a second client.
    assert "_register_options_handlers" in src
    assert "StreamClient(" in src and src.count("StreamClient(") == 1, (
        "more than one StreamClient is constructed — a second socket is a second source of truth")


def test_the_options_handler_swallows_its_own_errors():
    """The handler runs INLINE on the shared message loop. An exception escaping it would
    propagate into the loop that services equities and books."""
    import inspect

    src = inspect.getsource(ofs._run_stream_loop)
    i = src.find("def _options_frame_handler")
    assert i > 0, "the options handler is gone"
    body = src[i:i + 900]
    assert "try:" in body and "except Exception" in body, (
        "the options frame handler does not contain its own failure — a storage error would "
        "reach the shared stream loop")
    # It must hand off, not persist inline: no sqlite/commit work on the loop thread.
    for forbidden in ("sqlite3", "commit(", "persist_frame("):
        assert forbidden not in body, (
            f"the options handler does {forbidden} on the stream loop thread — that is the "
            f"stall this design exists to prevent")


def test_stopping_options_collection_is_safe_when_nothing_started():
    """Shutdown runs in the stream loop's finally; it must be harmless in every state."""
    ofs._options_ingest = None
    ofs._options_subscribed_syms = []
    ofs._stop_options_collection("test")          # must not raise
    assert ofs._options_ingest is None


def test_enabling_is_env_gated_and_not_settable_from_a_stale_module_global(monkeypatch):
    """The gate must be read at call time, so an operator turning it on or off is honoured
    without a code path caching the answer from import time."""
    monkeypatch.setenv(ofs.ED_OPTIONS_STREAM_ENV, "1")
    assert ofs.options_streaming_enabled() is True
    monkeypatch.setenv(ofs.ED_OPTIONS_STREAM_ENV, "0")
    assert ofs.options_streaming_enabled() is False
    monkeypatch.delenv(ofs.ED_OPTIONS_STREAM_ENV, raising=False)
    assert ofs.options_streaming_enabled() is False
    assert os.environ.get(ofs.ED_OPTIONS_STREAM_ENV) is None
