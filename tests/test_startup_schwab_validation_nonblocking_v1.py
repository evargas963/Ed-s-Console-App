"""Startup performance finding (2026-09-11, operator-directed measurement request):
_app_lifespan used to build a SEPARATE Schwab client (build_client_from_token) instead
of the canonical cached owner (get_client()), then issue a BLOCKING live client.get_quote
call before `yield` -- so no HTTP request of any kind (including Schwab-independent ones)
could be served until that network round-trip finished. Both are structural facts,
verified directly against the source rather than asserted."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server as srv


def _startup_schwab_block_source() -> str:
    full = inspect.getsource(srv._app_lifespan.__wrapped__)
    # Isolate the Schwab-startup section from the rest of the (long) lifespan body,
    # bounded by its own markers so an unrelated later change to the function does not
    # make this test pass or fail for the wrong reason.
    start = full.index("Lightweight auth validation")
    end = full.index("initialize_release_at_startup")
    return full[start:end]


def test_startup_uses_the_canonical_cached_client_not_a_second_construction():
    block = _startup_schwab_block_source()
    assert "get_client()" in block
    # build_client_from_token must not be CALLED a second time in this block (an
    # explanatory comment naming the old pattern is fine) -- a second construction was
    # the duplicate-construction defect: a throwaway client, never cached, so the first
    # real request paid the ~400ms construction cost again.
    assert "= build_client_from_token(" not in block


def test_startup_quote_validation_is_dispatched_off_the_blocking_path():
    block = _startup_schwab_block_source()
    assert "run_in_executor" in block, (
        "the live SPY quote validation must be dispatched to a background executor, "
        "not awaited/called inline before `yield` (which would block ALL HTTP traffic, "
        "including Schwab-independent routes, on vendor response time)"
    )


def test_yield_is_not_preceded_by_an_inline_blocking_quote_call():
    """A structural guard against regressing back to a direct client.get_quote(...) call
    sitting between the auth-validation block and `yield`."""
    full = inspect.getsource(srv._app_lifespan.__wrapped__)
    start = full.index("Lightweight auth validation")
    yield_idx = full.index("\n    yield", start)
    pre_yield = full[start:yield_idx]
    # The ONLY get_quote reference before yield must be inside the executor-dispatched
    # helper (_validate_schwab_quote_sync's body), never a bare top-level call.
    assert "state.client.get_quote" not in pre_yield
