"""RC-80: the call wall, put wall and gamma flip have exactly ONE producer.

MEASURED on the live console 2026-07-27 by polling /api/terrain?ticker=SPY every 4s for 200s:

    t+ 85.2s   call=739.0  put=736.0  flip=739.80   spot=736.82
    t+ 95.3s   call=750.0  put=740.0  flip=746.59   spot=736.86
    t+162.1s   call=750.0  put=740.0  flip=746.59   spot=736.96

An 11-point swing in the walls and 6.8 in the flip while spot moved four cents. Two producers:
the terrain loop computed from a WIDE chain sized by the resolve_chain_strike_count faucet, and
/api/terrain on a cache MISS computed its own from _latest_chain_and_spot() — the most recent
NARROW stored snapshot. Wall selection depends on how much of the wing is present, so a narrower
chain walks the walls inward.

The provenance audit scored "levels: 1 faucet" throughout, and was right about the READ side.
Nothing measured how many independent producers could compute the value behind it. That is what
these tests do.
"""
from __future__ import annotations

import ast
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "server.py"
SRC = SERVER.read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def _fn(name: str) -> str:
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError(f"{name} not found in server.py")


def _producers() -> list[tuple[int, str]]:
    """(line, enclosing function) for every compute_terrain call fed REAL contracts.

    `compute_terrain(tk, None, ...)` is the UNAVAILABLE constructor — it computes no levels from
    data and is therefore not a producer."""
    out: list[tuple[int, str]] = []

    class V(ast.NodeVisitor):
        fn: str | None = None

        def visit_FunctionDef(self, n):
            prev, self.fn = self.fn, n.name
            self.generic_visit(n)
            self.fn = prev

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, n):
            nm = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            if nm == "compute_terrain":
                second = n.args[1] if len(n.args) > 1 else None
                is_unavailable = isinstance(second, ast.Constant) and second.value is None
                if not is_unavailable:
                    out.append((n.lineno, self.fn or "<module>"))
            self.generic_visit(n)

    V().visit(TREE)
    return out


def _calls_in(name: str) -> set[str]:
    """Callee names actually INVOKED inside `name`. AST, not substring: the comment recording why
    the narrow-chain read was removed must not itself trip the lock, or the next person deletes
    the explanation to get green."""
    node = next(n for n in ast.walk(TREE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", "")
            for c in ast.walk(node) if isinstance(c, ast.Call)}


def test_terrain_endpoint_is_a_reader_not_a_producer():
    """The endpoint must drive THE producer on a miss, never imitate it."""
    seg = _fn("get_terrain")
    assert "_latest_chain_and_spot" not in _calls_in("get_terrain"), (
        "RC-80 regression: /api/terrain computes levels from the narrow stored chain again — the "
        "operator's walls will alternate between two values seconds apart"
    )
    assert "_terrain_refresh_one(" in seg, (
        "the endpoint no longer drives the single producer on a cache miss"
    )


def test_absence_reads_as_absence_not_as_a_narrower_chains_answer():
    seg = _fn("get_terrain")
    assert "terrain_not_ready" in seg, (
        "a cache miss that cannot be filled must say so; anything else invents an answer"
    )


def test_the_single_producer_still_uses_the_width_faucet():
    """One producer is only worth having if it reads the one width authority (RC-59)."""
    seg = _fn("_terrain_refresh_one")
    assert "_terrain_strike_count(" in seg or "resolve_chain_strike_count(" in seg, (
        "the producer no longer sizes its chain from the width faucet"
    )
    assert "priority" in seg, "the producer cannot serve an operator-facing miss with priority"


def test_levels_producers_are_enumerated_and_declared():
    """Any NEW producer must be declared here deliberately, with the reason it may exist.

    _radar_fallback_recompute is declared: it computes levels ONLY for tickers the terrain loop
    has not cached, for the ~51-symbol radar sweep, from stored chains — because calling the
    vendor per symbol measured a 40.5s cold sweep that always timed out. It never feeds
    /api/terrain. It is a KNOWN width inconsistency across radar rows, tracked in RC-80, not an
    accident this test should silently permit.
    """
    declared = {"_terrain_refresh_one", "_radar_fallback_recompute"}
    found = {fn for _, fn in _producers()}
    assert found == declared, (
        f"the set of level producers changed: {sorted(found)} != {sorted(declared)}. "
        "Every producer is a chance for two answers to disagree — add it here with its reason, "
        "or route it through _terrain_refresh_one."
    )


# ── RC-122 (W3-C1, operator P0b): ONE wall book on the screen ────────────────────────────────

def _overlay(cache_entry, monkeypatch):
    import server as S
    monkeypatch.setattr(S, "_terrain_cache",
                        {"SPY": cache_entry} if cache_entry is not None else {})
    md = {"kl_call_gamma_wall": 111.0, "kl_put_gamma_wall": 222.0, "kl_gamma_flip": 333.0,
          "kl_gamma_pin": 444.0, "kl_hvl": 555.0, "kl_max_pain": 666.0,
          "kl_call_gamma_str": "$9.9M/pt", "kl_put_gamma_str": "$8.8M/pt"}
    S._terrain_kl_overlay(md, "SPY")
    return md


def test_fresh_terrain_overlays_every_gamma_family_level(monkeypatch):
    md = _overlay({"call_wall": 745.0, "put_wall": 740.0, "gamma_flip": 746.5,
                   "gamma_pin": 741.0, "hvl": 740.0, "max_pain": 742.0,
                   "levels_stale": False}, monkeypatch)
    assert md["kl_call_gamma_wall"] == 745.0 and md["kl_put_gamma_wall"] == 740.0
    assert md["kl_gamma_flip"] == 746.5 and md["kl_gamma_pin"] == 741.0
    assert md["kl_hvl"] == 740.0 and md["kl_max_pain"] == 742.0
    assert md["kl_levels_source"] == "terrain_wide_chain"
    # narrow-book dollar strengths beside wide-chain strikes are the dual-book lie in a
    # smaller cell — blanked, never mixed
    assert md["kl_call_gamma_str"] == "—" and md["kl_put_gamma_str"] == "—"


def test_stale_terrain_blanks_rather_than_serving_the_narrow_book(monkeypatch):
    md = _overlay({"call_wall": 745.0, "put_wall": 740.0, "levels_stale": True}, monkeypatch)
    for k in ("kl_call_gamma_wall", "kl_put_gamma_wall", "kl_gamma_flip",
              "kl_gamma_pin", "kl_hvl", "kl_max_pain"):
        assert md[k] is None, f"{k} survived a stale terrain — the second book is back"
    assert "withheld" in md["kl_levels_source"]


def test_absent_terrain_blanks_rather_than_serving_the_narrow_book(monkeypatch):
    md = _overlay(None, monkeypatch)
    assert md["kl_call_gamma_wall"] is None and md["kl_gamma_flip"] is None
    assert "withheld" in md["kl_levels_source"]
