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
    # RC-124: kl_gamma_pin carries the STANDARD pin (+ strength passthrough); kl_hvl carries
    # the net-GEX peak under its historical key — the row label says what it is.
    md = _overlay({"call_wall": 745.0, "put_wall": 740.0, "gamma_flip": 746.5,
                   "gamma_pin": 741.0, "gamma_pin_strength_pct": 32.5,
                   "net_gex_peak": 735.0, "max_pain": 742.0,
                   "levels_stale": False}, monkeypatch)
    assert md["kl_call_gamma_wall"] == 745.0 and md["kl_put_gamma_wall"] == 740.0
    assert md["kl_gamma_flip"] == 746.5 and md["kl_gamma_pin"] == 741.0
    assert md["kl_gamma_pin_strength_pct"] == 32.5, "the pin's decisiveness must travel"
    assert md["kl_hvl"] == 735.0, "kl_hvl now carries net_gex_peak (RC-124 remap)"
    assert md["kl_max_pain"] == 742.0
    assert md["kl_levels_source"] == "terrain_wide_chain"
    # narrow-book dollar strengths beside wide-chain strikes are the dual-book lie in a
    # smaller cell — blanked, never mixed
    assert md["kl_call_gamma_str"] == "—" and md["kl_put_gamma_str"] == "—"


def test_stale_terrain_blanks_rather_than_serving_the_narrow_book(monkeypatch):
    md = _overlay({"call_wall": 745.0, "put_wall": 740.0, "confidence": "TRUSTED",
                   "levels_stale": True}, monkeypatch)
    for k in ("kl_call_gamma_wall", "kl_put_gamma_wall", "kl_gamma_flip",
              "kl_gamma_pin", "kl_hvl", "kl_max_pain", "kl_gamma_flip_confidence"):
        assert md[k] is None, f"{k} survived a stale terrain — the second book is back"
    assert "withheld" in md["kl_levels_source"]


def test_absent_terrain_blanks_rather_than_serving_the_narrow_book(monkeypatch):
    md = _overlay(None, monkeypatch)
    assert md["kl_call_gamma_wall"] is None and md["kl_gamma_flip"] is None
    assert "withheld" in md["kl_levels_source"]


# ── RC-128 (operator mandate: ONE Levels Faucet) ─────────────────────────────────────────────
# The invariant, enforced structurally: for every SSOT level concept there is exactly ONE
# writer of its payload key — the carriage helper. The analytics assignments were DELETED,
# not overridden; this lock fails the day any second writer returns, wherever it is placed.

SSOT_KEYS = (
    "kl_call_gamma_wall", "kl_put_gamma_wall", "kl_gamma_flip", "kl_gamma_pin", "kl_hvl",
    "kl_max_pain", "kl_call_delta_wall", "kl_put_delta_wall", "kl_call_oi_wall",
    "kl_put_oi_wall", "kl_call_vanna_wall", "kl_put_vanna_wall", "kl_em_upper",
    "kl_em_lower", "kl_gamma_inflection", "kl_delta_inflection", "kl_oi_center",
    # v23: the flip's confidence rides the same book as the flip's strike — it was the last
    # analytics-written kl_ key. And the terrain generation stamp travels with the values so
    # cross-surface drift (KL table vs terrain cards) is visible as generation skew, never a
    # silent disagreement.
    "kl_gamma_flip_confidence", "kl_levels_from_computed_ts",
)

# v23: terrain-NATIVE level concepts painted by the chart/console ticker views. They have no
# kl_ twin; their one producer is terrain_engine.compute_terrain via snap.to_dict(). server.py
# may CARRY them (t.get(...) into radar rows) but must never ASSIGN them — an assignment is a
# second producer for a painted key level.
TERRAIN_NATIVE_KEYS = ("hvp", "lvp", "call_charm_wall", "put_charm_wall", "key_delta_strike")


def _ssot_writes_outside_overlay(src: str) -> list[tuple[int, str]]:
    """(line, key) for every SSOT-key write outside _terrain_kl_overlay — AST-adjacent scan:
    dict-literal entries AND subscript assignments both count; comments do not."""
    import re as _re
    lines = src.splitlines()
    try:
        i0 = next(n for n, l in enumerate(lines, 1) if "def _terrain_kl_overlay" in l)
        i1 = next(n for n, l in enumerate(lines[i0:], i0 + 1)
                  if l.startswith("def ") or l.startswith("async def "))
    except StopIteration:
        i0, i1 = -1, -1
    out = []
    for n, l in enumerate(lines, 1):
        t = l.split("#")[0]
        for k in SSOT_KEYS:
            if _re.search(rf"[\"']{k}[\"']\s*[:\]]", t) and ("=" in t or ": " in t) \
                    and not (i0 <= n < i1):
                out.append((n, k))
    return out


def test_the_overlay_is_the_only_ssot_writer():
    src = SERVER.read_text(encoding="utf-8")
    offenders = _ssot_writes_outside_overlay(src)
    assert offenders == [], (
        f"SSOT level keys written outside _terrain_kl_overlay — a second book can reach the "
        f"screen again (RC-128): {offenders}"
    )


def test_second_writer_injection_is_caught():
    """Negative control: the lock must FIRE on an injected second writer, wherever placed."""
    src = SERVER.read_text(encoding="utf-8") + '\nmd["kl_call_gamma_wall"] = 123.0\n'
    assert _ssot_writes_outside_overlay(src), (
        "an injected second writer went undetected — the single-writer lock is inert"
    )


def _terrain_native_writes(src: str) -> list[tuple[int, str]]:
    """(line, key) for every server-side ASSIGNMENT of a terrain-native level key.

    An assignment is `["hvp"] =` or a dict-literal `"hvp": <value>` whose value is NOT read
    from the terrain payload (`t.get(...)` / `payload.get(...)` / `_snap.get(...)` is carriage
    of the one book, not a second producer)."""
    import re as _re
    out = []
    for n, l in enumerate(src.splitlines(), 1):
        t = l.split("#")[0]
        for k in TERRAIN_NATIVE_KEYS:
            m = _re.search(rf"[\"']{k}[\"']\s*([:\]])", t)
            if not m:
                continue
            rest = t[m.end():]
            if m.group(1) == "]" and "=" not in rest:
                continue  # a read, not a write
            if _re.search(r"\b(t|payload|_snap|snap|entry)\s*(\.get\(|\[)", rest):
                continue  # carriage from the terrain book itself
            out.append((n, k))
    return out


def test_server_never_produces_terrain_native_levels():
    """v23: HVP/LVP/charm walls/key-delta join the single-producer lock. Their producer is
    terrain_engine.compute_terrain — server.py assigning any of them is a second book."""
    src = SERVER.read_text(encoding="utf-8")
    offenders = _terrain_native_writes(src)
    assert offenders == [], (
        f"terrain-native level keys assigned in server.py — a second producer for a painted "
        f"key level (v23): {offenders}"
    )


def test_terrain_native_injection_is_caught():
    """Negative control: an injected server-side hvp producer must fire the lock; carriage
    from the terrain payload must stay quiet."""
    src = SERVER.read_text(encoding="utf-8")
    assert _terrain_native_writes(src + '\nrow["hvp"] = compute_hvp(chain)\n'), (
        "an injected terrain-native producer went undetected — the lock is inert"
    )
    assert not _terrain_native_writes('row["hvp"] = t.get("hvp")\n'), (
        "carriage of the terrain book tripped the lock — it would force deleting the radar rows"
    )


def test_overlay_owns_the_full_concept_set(monkeypatch):
    """Fresh terrain: delta walls carried, EM from the sigma band; unowned concepts BLANK."""
    md = _overlay({"call_wall": 745.0, "put_wall": 740.0, "gamma_flip": 746.5,
                   "gamma_pin": 741.0, "gamma_pin_strength_pct": 32.5,
                   "net_gex_peak": 735.0, "max_pain": 742.0,
                   "call_delta_wall": 747.0, "put_delta_wall": 738.0,
                   "implied_1d_move": {"points": 8.5}, "spot": 741.0,
                   "confidence": "TRUSTED", "computed_ts_utc": 1722.5,
                   "levels_stale": False}, monkeypatch)
    assert md["kl_call_delta_wall"] == 747.0 and md["kl_put_delta_wall"] == 738.0
    assert md["kl_gamma_flip_confidence"] == "TRUSTED", (
        "v23: the flip confidence must ride the SAME terrain book as the flip strike"
    )
    assert md["kl_levels_from_computed_ts"] == 1722.5, (
        "v23 Lock-3: the terrain generation stamp must travel with the values so cross-surface "
        "drift reads as generation skew, never a silent disagreement"
    )
    assert md["kl_em_upper"] == 749.5 and md["kl_em_lower"] == 732.5, (
        "EM must come from the terrain sigma band centered on the payload spot (E-34)"
    )
    for k in ("kl_call_oi_wall", "kl_put_oi_wall", "kl_call_vanna_wall",
              "kl_put_vanna_wall", "kl_gamma_inflection", "kl_delta_inflection",
              "kl_oi_center"):
        assert md[k] is None, f"{k}: terrain does not compute this — it must be BLANK, " \
                              f"never an analytics book"
    for k in ("kl_call_delta_str", "kl_put_oi_str", "kl_hvl_str", "kl_max_pain_str"):
        assert md[k] == "—", f"{k}: a strength from another book must be blanked"
