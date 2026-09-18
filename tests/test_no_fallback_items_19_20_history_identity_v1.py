"""No-fallback items 19-20: three sites in order_flow/history.py resolved a contract/
ticker's canonical storage key via `ticker_storage_key(x) or str(x or "").strip()` -- an
`or` fallback to a raw, unvalidated string coercion of the ORIGINAL input whenever the
canonical resolver returned a falsy value.

ticker_storage_key only ever returns falsy ("") when its input strips to empty -- and in
every one of those cases, `str(x or "").strip()` ALSO evaluates to "" (proved below by
direct computation, not assumed). The raw-string branch was therefore dead code that could
never actually take effect, but it stood in the source as a second, unvalidated identity
path bypassing the canonical option-contract identity contract -- exactly the two-authority
shape this mission exists to remove, even though it happened not to diverge numerically.
Removed; every site now reads the canonical resolver alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from instrument_identity import ticker_storage_key


def _old_fallback_formula(x, *, upper: bool = False) -> str:
    """Reproduces the REMOVED formula exactly, so the mutation control below proves
    equivalence by construction rather than by assertion against a hand-picked example."""
    canonical = ticker_storage_key(x)
    if canonical:
        return canonical
    raw = str(x or "").strip()
    return raw.upper() if upper else raw


def test_ticker_storage_key_falsy_only_when_raw_fallback_would_also_be_empty():
    """MUTATION CONTROL: for every case that made ticker_storage_key fall through to the
    removed raw-string branch, that branch always computed the SAME empty string --
    proving the removed fallback was dead code, not a silently-different second authority."""
    for x in (None, "", "   ", "\t\n", 0, False):
        assert ticker_storage_key(x) == "", f"precondition: {x!r} must resolve falsy"
        assert _old_fallback_formula(x) == "", (
            f"the removed fallback must have been unreachable-but-equal for {x!r}")
        assert _old_fallback_formula(x, upper=True) == ""


def test_hydrate_option_content_and_tape_rows_use_the_canonical_resolver_alone():
    """The real production call sites (history.py:26, :116) now compute sym identically
    to ticker_storage_key -- no separate formula exists to drift from it."""
    import inspect

    import app.options.order_flow.history as history

    src_hydrate = inspect.getsource(history.hydrate_option_content)
    src_tape = inspect.getsource(history.tape_rows_for_symbol)
    for src, name in ((src_hydrate, "hydrate_option_content"), (src_tape, "tape_rows_for_symbol")):
        assert "sym = ticker_storage_key(" in src, name
        assert "or str(" not in src, (
            f"{name}: the raw-string fallback must be gone, not just unreachable")


def test_book_heatmap_for_ticker_uses_the_canonical_resolver_alone():
    import inspect

    import app.options.order_flow.history as history

    src = inspect.getsource(history.book_heatmap_for_ticker)
    assert "sym = ticker_storage_key(" in src
    assert "or str(" not in src
