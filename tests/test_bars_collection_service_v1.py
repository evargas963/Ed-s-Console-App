"""RC-69: bar collection is a SERVICE, and price_bars_1m has exactly ONE writer.

Bars used to be persisted only inside `_fetch_state` — the render path — so a ticker's chart
decayed to whenever it was last looked at. MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar lag
3.1 min vs QQQ 19.1 and IWM 19.1 (off screen), while all three had ~1.0 min SNAPSHOT lag. The
quotes were current; the bars were not. 39.8% of snapshots (122,795/308,796) carry unfilled
outcomes because fill_outcomes reads price_bars_1m for the forward price and it was never written.

These lock the architecture, not the symptom: collection independent of the viewport, and a
single faucet for the bars table.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = ROOT / "server.py"
SERVER_SRC = SERVER_PATH.read_text(encoding="utf-8")
#: RC-REHAB-1 (forty-fifth slice): the collection service lives in bars_loop.py.
BARS_PATH = ROOT / "bars_loop.py"
BARS_SRC = BARS_PATH.read_text(encoding="utf-8")


def _fn_src(name: str) -> str:
    for src in (SERVER_SRC, BARS_SRC):
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"{name} not found in server.py or bars_loop.py")


def _console_runtime_modules() -> dict[str, Path]:
    """Every repo-local module the console process can import: the static import closure of
    server.py, following imports anywhere in a file (lazy in-function imports included)."""
    seen: dict[str, Path] = {}
    todo = ["server"]
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        path = ROOT / (mod.replace(".", "/") + ".py")
        if not path.is_file():
            pkg = ROOT / mod.replace(".", "/") / "__init__.py"
            if not pkg.is_file():
                continue
            path = pkg
        seen[mod] = path
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                todo += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                todo.append(node.module)
                todo += [f"{node.module}.{a.name}" for a in node.names]
    return seen


def _bar_writes(path: Path) -> list[str]:
    """`<x>.upsert_1m_bars(...)` calls, excluding a module's own `__main__` smoke block."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    main_blocks = [n for n in tree.body if isinstance(n, ast.If)
                   and "__main__" in ast.unparse(n.test)]
    skip = {id(x) for b in main_blocks for x in ast.walk(b)}
    out = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for x in ast.walk(fn):
                if (isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                        and x.func.attr == "upsert_1m_bars" and id(x) not in skip):
                    out.append(f"{path.relative_to(ROOT).as_posix()}:{fn.name}")
    for x in ast.walk(tree):
        if (isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                and x.func.attr == "upsert_1m_bars" and id(x) not in skip
                and not any(id(x) in {id(y) for y in ast.walk(f)} for f in ast.walk(tree)
                            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)))):
            out.append(f"{path.relative_to(ROOT).as_posix()}:<module>")
    return out


def test_price_bars_has_exactly_one_writer():
    """THE single-faucet contract, over the WHOLE console process -- server.py and every module
    it can import -- not one file. A second writer is how collection drifted into the render
    path in the first place. Offline repair/backfill tools are not part of the console."""
    writes = [w for p in _console_runtime_modules().values() for w in _bar_writes(p)]
    assert writes == ["bars_loop.py:_persist_1m_bars"], (
        f"price_bars_1m writers in the console runtime: {writes}; RC-69 requires exactly ONE "
        f"(the bar collection service's _persist_1m_bars). A render path must never persist bars."
    )


def test_the_one_writer_is_the_single_faucet_and_both_producers_route_through_it():
    """RC-69 single faucet, extended for RC-484: the ONE ``upsert_1m_bars(`` call lives in
    the dedicated writer ``_persist_1m_bars``, and BOTH bar producers persist through it —
    the live collection service (``_bars_collect_one``) and the day-1 enrollment history
    seed (``_enrollment_history_seed``). Before the seed existed there was one producer and
    the write lived inline in the collector; now there are two legitimate producers, so the
    faucet is extracted rather than duplicated. The render path stays barred
    (test_render_path_does_not_persist_bars)."""
    assert "upsert_1m_bars(" in _fn_src("_persist_1m_bars"), \
        "the single bar writer must be _persist_1m_bars"
    assert "_persist_1m_bars(" in _fn_src("_bars_collect_one"), \
        "the collection service must persist through the single faucet"
    assert "_persist_1m_bars(" in _fn_src("_enrollment_history_seed"), \
        "the enrollment seed must persist through the single faucet, not a second writer"


def test_render_path_does_not_persist_bars():
    """_fetch_state may tick the accumulator for its own forming candle, but must not WRITE."""
    seg = _fn_src("_fetch_state")
    assert "upsert_1m_bars(" not in seg, (
        "RC-69 regression: the render path persists bars again, so collection is once more a "
        "side-effect of what the operator happens to be looking at"
    )


def test_collection_covers_the_whole_enrolled_universe_not_a_fixed_list():
    """The loop must read the live enrolled set. A hardcoded tuple is how bars ended up covering
    3 of 57 tickers."""
    seg = _fn_src("_bars_loop")
    assert "_logger_tickers" in seg, "bar collection must iterate the enrolled universe"
    assert "BASE_MONEY_PATH_TICKERS" not in seg, "bar collection must not be sentinel-scoped"


def test_collection_is_session_gated_and_never_ticks_a_closed_market():
    """RC-48: a market-closed tick would persist a frozen bar and bias every study built on it."""
    seg = _fn_src("_bars_loop")
    assert "_is_loggable_session()" in seg


def test_collect_one_treats_a_missing_price_as_absence():
    """Absence must read as absence — never a fabricated tick into the bar series."""
    seg = _fn_src("_bars_collect_one")
    assert "skip:no_price" in seg
    assert "never raises" in seg.lower() or "except Exception" in seg


def test_loop_refuses_to_start_under_pytest():
    """A production collection thread inside the test process mutates shared state no test
    controls — the RC-5 failure class."""
    seg = _fn_src("start_bars_loop")
    assert "PYTEST_CURRENT_TEST" in seg


def test_loop_is_wired_into_the_app_lifespan():
    lifespan = _fn_src("_app_lifespan")
    assert "start_bars_loop()" in lifespan, "collection service is never started"
    assert "stop_bars_loop()" in lifespan, "collection service is never stopped on shutdown"
