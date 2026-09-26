"""I-01: fetch_market_context never raises; partial context on quote failure."""
from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


class _MockQuoteResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _quote_fn(*, fail: frozenset[str] = frozenset(), prices: dict[str, float] | None = None):
    """Minimal safe_get_quote stub: fail-closed per symbol."""

    def _quote(_client, sym: str):
        if sym in fail:
            raise RuntimeError(f"{sym} unavailable")
        if prices and sym in prices:
            return _MockQuoteResponse({sym: {"quote": {"lastPrice": prices[sym]}}})
        return _MockQuoteResponse({})

    return _quote
























# ── VOL_INPUT_CONTRACT 1.0.0 (lane V1) — per-cycle context + stamp parity ────

import ast as _ast
from pathlib import Path as _Path



_REPO = _Path(__file__).resolve().parent.parent






def test_single_tracker_tick_site_lock():
    """Exactly ONE _vix_tracker.tick site may exist in server.py — the
    per-cycle vol-context computation. Extra per-surface ticks re-tick the
    same value and force direction to flat (pre-fix defect class)."""
    server_src = (_REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert server_src.count("_vix_tracker.tick(") == 1


def test_three_surfaces_consume_the_one_context():
    """SignalInput stamp, snapshot row, and ms_dict must all read
    vol_ctx.market_iv_* — no surface recomputes vs-prev or re-reads the
    tracker independently (MSD-001 route parity by construction)."""
    server_src = (_REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    ms_src = (_REPO / "market_state.py").read_text(encoding="utf-8", errors="replace")
    assert 'ms_dict["vix"] = vol_ctx.market_iv_level' in server_src
    assert 'ms_dict["vix_direction"] = vol_ctx.market_iv_direction' in server_src
    assert 'ms_dict["vix_vs_prev"] = vol_ctx.market_iv_change' in server_src
    assert "_vix_vs_prev = vol_ctx.market_iv_change" in server_src   # snapshot row
    assert "vix_level=vol_ctx.market_iv_level" in server_src         # snapshot row
    assert "vol_ctx=vol_ctx" in server_src                           # build_market_state call
    assert "vix_vs_prev=(vol_ctx.market_iv_change if vol_ctx is not None else None)" in ms_src
    assert "vix_direction=(vol_ctx.market_iv_direction if vol_ctx is not None else None)" in ms_src
    # [REAL-GATE:VOL-CTX-SINGLE-SOURCE] closure lock: zero raw mkt_ctx.vix
    # attribute reads outside the canonical conversion site. server.py may
    # read mkt_ctx.vix exactly ONCE (the float() conversion feeding vol_ctx);
    # market_state.py exactly TWICE, both as the ratified vol_ctx=None
    # rollback fallbacks (vix_level stamp + vix_bucket source).
    def _raw_vix_reads(src: str) -> list[int]:
        tree = _ast.parse(src)
        return sorted(
            n.lineno for n in _ast.walk(tree)
            if isinstance(n, _ast.Attribute) and n.attr == "vix"
            and isinstance(n.value, _ast.Name) and n.value.id == "mkt_ctx"
        )
    server_reads = _raw_vix_reads(server_src)
    assert len(server_reads) == 1, (
        f"raw mkt_ctx.vix reads in server.py at {server_reads} — only the "
        f"canonical vol_ctx conversion site may read the raw quote"
    )
    ms_reads = _raw_vix_reads(ms_src)
    assert len(ms_reads) == 2, (
        f"raw mkt_ctx.vix reads in market_state.py at {ms_reads} — only the "
        f"two vol_ctx=None rollback fallbacks may read the raw quote"
    )
    ms_lines = ms_src.splitlines()
    for ln in ms_reads:
        assert "vol_ctx is not None else mkt_ctx.vix" in ms_lines[ln - 1], (
            f"market_state.py:{ln} raw read is not a vol_ctx=None fallback"
        )


def test_vol_context_bound_outside_any_try():
    """vol_ctx must be bound unconditionally in _fetch_state — never inside a
    try whose handler swallows and continues. Caught 2026-07-10: the binding
    lived inside the envelope/density/sector try (except Exception:
    log.debug), so any swallowed exception there left vol_ctx unbound and the
    later build_market_state(vol_ctx=vol_ctx) call died with NameError."""
    tree = _ast.parse((_REPO / "server.py").read_text(encoding="utf-8", errors="replace"))
    parents: dict[_ast.AST, _ast.AST] = {}
    for node in _ast.walk(tree):
        for child in _ast.iter_child_nodes(node):
            parents[child] = node
    bindings = [
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.Name) and n.id == "vol_ctx" and isinstance(n.ctx, _ast.Store)
    ]
    assert len(bindings) == 1, f"expected exactly one vol_ctx binding, got {len(bindings)}"
    cur: _ast.AST = bindings[0]
    enclosing: list[str] = []
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (_ast.Try, _ast.If, _ast.For, _ast.While)):
            enclosing.append(f"{type(cur).__name__}@{cur.lineno}")
    assert enclosing == [], (
        f"vol_ctx binding is conditional/swallowable (inside {enclosing}) — "
        f"it must execute on every path that reaches its consumers"
    )


def test_canonical_signal_input_construction_lock(repo_index):
    """Money-path SignalInput construction happens only in the two canonical
    builders (market_state live stamp; replay builder). Production code must
    not bypass the vol boundary with an independent SignalInput(...)."""
    # TEST_SYSTEM_REHAB_V2: was two independent globs (_REPO.glob("*.py"),
    # (_REPO/"features").glob("*.py")) + per-file read+parse -- now sources from the
    # shared `repo_index` corpus, filtered to the same two top-level scopes.
    allowed = {"market_state.py", "features/replay_signal_input_v1.py", "signal_types.py"}
    offenders: list[str] = []
    for rel, _text, tree in repo_index.items():
        in_root = len(rel.parts) == 1
        in_features = len(rel.parts) == 2 and rel.parts[0] == "features"
        if not (in_root or in_features):
            continue
        rel_s = rel.name if in_root else f"features/{rel.name}"
        if rel_s in allowed or (in_root and rel.name.startswith("test_")):
            continue
        if tree is None:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, _ast.Name) else (
                    fn.attr if isinstance(fn, _ast.Attribute) else ""
                )
                if name == "SignalInput":
                    offenders.append(f"{rel_s}:{node.lineno}")
    assert offenders == [], f"SignalInput constructed outside canonical builders: {offenders}"
