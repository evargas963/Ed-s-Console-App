"""RC-243: one bar writer contends for the tier-1 write seam."""
from __future__ import annotations

from pathlib import Path


def test_rc243_one_bar_writer_contends_for_the_write_seam():
    """RC-243: bar writers all serialize on ONE process-wide tier-1 write lock, so writers past
    the first queue rather than parallelise — and each extra contender lengthens the queue
    against a 27 GB file. MEASURED live: ed_bars_0/1/2 took 426/407/405 lock waits (1,238 on
    upsert_1m_bars), lifetime max 180,340 ms, busy_retry_count 0 (the Python mutex, not
    SQLite's busy handler). The REST-poll bar pool (BARS_WORKERS / ed_bars) is gone: streamed
    bars are written by exactly ONE thread, so there is one contender for the seam, attributable
    by its own thread name."""
    import ast as _ast

    import server as srv

    src = Path(srv.__file__).read_text(encoding="utf-8")
    assert 'thread_name_prefix="ed_bars"' not in src and "BARS_WORKERS" not in src, (
        "a bar worker pool reappeared — it re-creates the fan-in this row measured")
    tree = _ast.parse(src)
    starter = next(n for n in _ast.walk(tree)
                   if isinstance(n, _ast.FunctionDef) and n.name == "start_bar_writer")
    threads = [c for c in _ast.walk(starter) if isinstance(c, _ast.Call)
               and isinstance(c.func, _ast.Attribute) and c.func.attr == "Thread"]
    assert len(threads) == 1, "the bar writer must be ONE thread"
    kw = {k.arg: k.value for k in threads[0].keywords}
    assert isinstance(kw["target"], _ast.Name) and kw["target"].id == "_bar_writer"
    assert _ast.literal_eval(kw["name"]) == "bar-writer"
    # and it is started from exactly one call site
    starts = [c for c in _ast.walk(tree) if isinstance(c, _ast.Call)
              and isinstance(c.func, _ast.Name) and c.func.id == "start_bar_writer"]
    assert len(starts) == 1, f"start_bar_writer is called {len(starts)} times"
