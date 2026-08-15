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
    # RC-130: geometry states ride with the walls they qualify — same single writer.
    "kl_call_wall_state", "kl_put_wall_state",
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


def test_reprice_recomputes_wall_states_before_the_profile_early_return():
    """RC-130: wall states are a function of SPOT and must be refreshed by the reprice path
    with the PRODUCER's definition — and before the no-profile early return, or tickers
    without a cached profile would serve loop-time geometry beside a live spot."""
    seg = _fn("_reprice_cached_terrain")
    calls = seg.count("wall_geometry_state(")
    assert calls == 2, f"expected exactly 2 wall_geometry_state calls in reprice, found {calls}"
    assert seg.index("wall_geometry_state(") < seg.index("_terrain_profile_cache"), (
        "the state recompute sits after the profile early-return — no-profile tickers would "
        "keep stale geometry beside a fresh spot"
    )


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
                   # RC-130 carriage check: states are CARRIED verbatim from the producer,
                   # never recomputed in the overlay (put deliberately 'breached' here even
                   # though 740<741 — proving no second computation exists at this seam).
                   "call_wall_state": "contains", "put_wall_state": "breached",
                   "levels_stale": False}, monkeypatch)
    assert md["kl_call_delta_wall"] == 747.0 and md["kl_put_delta_wall"] == 738.0
    assert md["kl_gamma_flip_confidence"] == "TRUSTED", (
        "v23: the flip confidence must ride the SAME terrain book as the flip strike"
    )
    assert md["kl_levels_from_computed_ts"] == 1722.5, (
        "v23 Lock-3: the terrain generation stamp must travel with the values so cross-surface "
        "drift reads as generation skew, never a silent disagreement"
    )
    assert md["kl_call_wall_state"] == "contains" and md["kl_put_wall_state"] == "breached", (
        "RC-130: the geometry state must travel WITH the wall value it qualifies"
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


# ── RC-213 B1: /api/levels read-adapter contract (mission levels-faucet-v1) ──────────


def test_api_levels_b1_contract_single_session_prior_day(monkeypatch):
    """The B1 read-adapter serves the prior_day family from the RC-153 single-session
    authority, with per-level provenance naming the window, unique ids, honest
    families_absent — and never the multi-session union values (the RC-213 defect)."""
    import json
    from datetime import datetime as _dt

    import server as srv
    from time_et import ET

    def _bar(y, mo, d, h, mi, o, hi, lo, c):
        return {"timestamp": int(_dt(y, mo, d, h, mi, tzinfo=ET).timestamp() * 1000),
                "open": o, "high": hi, "low": lo, "close": c, "volume": 1000.0}

    tape = [
        _bar(2026, 7, 30, 10, 0, 100, 110, 90, 100),   # older prior session: both extremes
        _bar(2026, 7, 30, 14, 0, 100, 101, 99, 100),
        _bar(2026, 7, 31, 10, 0, 96, 105, 95, 97),     # most recent prior session
        _bar(2026, 7, 31, 15, 59, 101, 103, 100, 102),
        _bar(2026, 8, 3, 9, 35, 103, 104, 102, 103),   # today inside ORB window
        _bar(2026, 8, 3, 9, 45, 103, 104, 102, 103),   # today post-ORB
    ]
    monkeypatch.setattr(srv, "_liquidity_live_1m_overlay_bars", lambda t: tape)
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (103.5, "schwab_quote_last", 1.0))
    # This fixture tests WINDOW SELECTION with tiny sessions; the t12 coverage floor is
    # exercised by its own dedicated test below.
    monkeypatch.setattr(srv, "LEVELS_PRIOR_SESSION_MIN_BARS", 2)
    import time_et as te
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 8, 3, 10, 0, tzinfo=ET))

    resp = srv.get_levels(ticker="SPY")
    payload = json.loads(bytes(resp.body))

    assert payload["schema_version"] == 1
    assert payload["spot"] == 103.5 and payload["spot_source"] == "schwab_quote_last"

    ids = [lv["id"] for lv in payload["levels"]]
    assert len(ids) == len(set(ids)), "level ids must be UNIQUE per payload (RC-88)"
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDH"]["price"] == 105 and by_id["PDL"]["price"] == 95, (
        "prior_day must be the SINGLE most recent prior RTH session"
    )
    assert by_id["PDC"]["price"] == 102
    for lv in payload["levels"]:
        assert lv["price"] not in (110, 90), "multi-session union value served — RC-213 reopened"
        assert "as_of_ts_utc" in lv["staleness"] and "age_sec" in lv["staleness"]
        if lv["family"] == "prior_day":
            assert lv["provenance"]["session_scope"] == "RTH"
            assert "2026-07-31" in lv["provenance"]["window"], (
                "provenance.window must name the literal session used (RC-153)"
            )

    fams = {f["family"] for f in payload["families_absent"]}
    assert "gamma" in fams, (
        "gamma remains OUT-OF-SCOPE for Tier-B and must be DECLARED absent (RC-68)"
    )
    # Tier-B (levels-tierb-session-collapse-v1): session families are served from the engine
    # when today bars exist — not left as soft B1-absent placeholders.
    by_fam = {}
    for lv in payload["levels"]:
        by_fam.setdefault(lv["family"], []).append(lv["id"])
    assert "VWAP" in by_id and by_id["VWAP"]["family"] == "vwap"
    assert "ORB_HIGH" in by_id and by_id["ORB_HIGH"]["family"] == "opening_range"
    assert "TODAY_POC" in by_id and by_id["TODAY_POC"]["family"] == "value_area"
    assert all(f.get("reason") for f in payload["families_absent"])
    assert "vwap" not in fams, "vwap must be served by Tier-B, not declared absent when bars exist"


def test_multi_faucet_census_tool_emits_and_finds_known_duals(tmp_path, monkeypatch):
    """T1 (mission multi-faucet-census-v1): the census tool runs, emits both artifacts,
    every producer site cites a CURRENT line (no stale evidence), and the known duals
    (vwap triple-producer, clocks, charm grandfather) are present with severities."""
    import json

    import tools.multi_faucet_census_v1 as census

    monkeypatch.setattr(census, "MD_OUT", tmp_path / "census.md")
    monkeypatch.setattr(census, "JSON_OUT", tmp_path / "census.json")
    assert census.main() == 0
    payload = json.loads((tmp_path / "census.json").read_text(encoding="utf-8"))
    concepts = {f["concept"]: f for f in payload["findings"]}

    vwap = next(f for c, f in concepts.items() if c.startswith("vwap"))
    assert "TIERB_DONE" in vwap.get("status", "")
    assert len(vwap["producers"]) >= 2
    clocks = next(f for c, f in concepts.items() if c.startswith("clocks"))
    assert len(clocks["producers"]) >= 2
    charm = next(f for c, f in concepts.items() if c.startswith("charm"))
    assert "bs_" in str(charm["producers"]) and "compute_net_charm" in str(charm["producers"])
    prior = next(f for c, f in concepts.items() if c.startswith("prior_day"))
    assert "PHASE1_DONE" in prior.get("status", "")

    md = (tmp_path / "census.md").read_text(encoding="utf-8")
    assert "pattern gone" not in md, "census cites a producer line that no longer exists"
    for f in payload["findings"]:
        assert f["severity"] in ("P0", "P1", "P2")
        assert f["reproduce"] and f["proposed_kill"]


# ── RC-227: one-faucet closeout locks (mission one-faucet-closeout-v1) ────────────────

_CHART = (Path(__file__).resolve().parent.parent / "static" / "chart.html").read_text(
    encoding="utf-8", errors="replace")
_SERVER_SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(
    encoding="utf-8", errors="replace")


def test_b3_chart_never_computes_prior_day():
    """B3: the client prior-day fallback faucet is DEAD — chart.html must not derive
    pdh/pdl/pdc from bars, and every consumer reads the engine-only accessor."""
    assert "days[days.length - 2]" not in _CHART, "computeDaily prior-session grouping is back"
    for pat in ("daily.pdh", "daily.pdl", "daily.pdc", "d.pdh"):
        assert pat not in _CHART, f"client prior-day read '{pat}' — the B3 fallback faucet reopened"
    assert "function enginePD()" in _CHART, "the engine-only prior_day accessor is gone"


def test_strip_never_reaggregates_side_sums_client_side():
    """STRIP: the browser must not re-sum per-side GEX/OV; it consumes today_side_sums."""
    assert "today_side_sums" in _CHART, "strip no longer consumes the server aggregation"
    import re as _re
    assert not _re.search(r"if \(r\[0\] < spot\) \{ gB \+=", _CHART), (
        "in-browser per-side re-aggregation is back — a second aggregator on a second spot"
    )


def test_strip_charm_row_not_vote_locked():
    """RC-199: the operator revoked the charm vote-gate; the strip renders real charm."""
    assert "renders after the operator charm vote" not in _CHART
    assert "charm_below" in _CHART and "charm_above" in _CHART


def test_strip_visible_consumer_f_src_bound():
    """RC-225 close contract: the VISIBLE consumer #f-src (strip age/source text) is
    asserted as a rendered element wired to the spot-binding age label — not a substring
    coincidence (RC-102)."""
    assert 'id="f-src"' in _CHART, "the strip's visible age/source element is gone"
    assert "src.textContent = spotBindingAgeLabel()" in _CHART, (
        "#f-src is no longer wired to the spot-binding age label"
    )


def test_strikes_payload_carries_server_side_sums(monkeypatch):
    """STRIP server half: /api/terrain/strikes serves today_side_sums computed against the
    payload's own spot — the one aggregator."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "terrain_cache_get", lambda tk: {
        "_per_strike": {"all": [[95.0, 10.0, 100], [105.0, -4.0, 50]],
                        "near": [], "far": []},
        "spot": 100.0, "computed_ts_utc": 1.0,
    })
    monkeypatch.setattr(srv, "resolve_spot", lambda tk, **kw: (100.0, "schwab_quote_last", 1.0))
    resp = srv.get_terrain_strikes(ticker="SPY")
    payload = json.loads(bytes(resp.body))
    ss = payload["today_side_sums"]
    assert ss["gex_below"] == 10.0 and ss["gex_above"] == -4.0
    assert ss["vol_below"] == 100 and ss["vol_above"] == 50
    assert ss["spot_basis"] == 100.0, "sums must be computed against the payload's own spot"


def test_price_levels_route_retired_410():
    """B6: the second HTTP surface hard-fails with a pointer — never a silent alias."""
    import json

    import server as srv

    resp = srv.get_price_levels(ticker="SPY")
    assert resp.status_code == 410
    payload = json.loads(bytes(resp.body))
    assert payload["error"] == "retired" and "/api/levels" in payload["replacement"]


def test_state_level_family_serves_raw_not_rounded():
    """PDH_PRECISION: the state payload's level family uses the raw finite reader, never
    the 2dp _fv — /api/levels and state must serve the same digits."""
    import re as _re
    for field in ("pdh", "pdl", "pdc", "vwap", "orb_high", "orb_low"):
        m = _re.search(rf'ms_dict\["{field}"\]\s*=\s*(\w+)\(', _SERVER_SRC)
        assert m, f"state no longer serves {field}"
        assert m.group(1) == "_raw_level", (
            f"state serves {field} through {m.group(1)} — the 2dp precision faucet is back"
        )


def test_domain_faucet_registry_negative_control():
    """Negative control naming check_domain_faucet_registry (RC-95 pattern): inject an
    UNREGISTERED level-domain producer and the callee must scream; a registered one stays
    silent. Proves the ENFORCED check fires rather than sitting green-and-inert."""
    from pathlib import Path

    from tools.check_institutional_correctness import domain_faucet_violations

    registry_text = (Path(__file__).resolve().parent.parent / "governance" /
                     "level_faucets.json").read_text(encoding="utf-8")
    # Route literal is assembled at runtime so the RC-212 STAGED-TEXT scan never reads this
    # injection as a real new producer (the scan is static; the callee test is dynamic).
    injected = '@app.' + 'get("' + '/api/levels-extra' + '")\ndef f(): pass'
    bad = domain_faucet_violations("server.py", injected, registry_text)
    assert bad and any("levels-extra" in b for b in bad), (
        "check_domain_faucet_registry callee stayed silent on an unregistered producer"
    )
    ok = domain_faucet_violations(
        "server.py", '@app.get("/api/exposure/book")\ndef f(): pass', registry_text)
    assert not ok, "a REGISTERED producer must not scream"


def test_forward_only_grandfather_old_rows_exempt_new_rows_enforced():
    """Operator PM gate decision (2026-08-04): retroactive row-quality enforcement applies
    only to RC-227+; scratchpad probe debris exempt from file-hygiene classes; everything
    else passes through untouched."""
    from pathlib import Path

    from tools.check_institutional_correctness import (
        RC_GRANDFATHER_CUTOFF,
        Violation,
        _apply_forward_only_grandfather,
    )

    assert RC_GRANDFATHER_CUTOFF == 227
    old = Violation(Path("governance/root_cause_log.md"), 1, "RC-14 is CLOSED without evidence")
    new = Violation(Path("governance/root_cause_log.md"), 2, "RC-228 is CLOSED without evidence")
    kept = _apply_forward_only_grandfather("closed_rows_ship_their_code", [old, new])
    assert kept == [new], "old row must be exempt; new row must stay enforced"

    pad = Violation(Path("scratchpad/_probe.py"), 3, "silent-swallow")
    tool = Violation(Path("tools/x.py"), 4, "silent-swallow")
    kept2 = _apply_forward_only_grandfather("no_silent_swallow", [pad, tool])
    assert kept2 == [tool], "scratchpad exempt; tools/ fully enforced"

    other = Violation(Path("server.py"), 5, "RC-14 mentioned but this check is not grandfathered")
    assert _apply_forward_only_grandfather("single_spot_authority", [other]) == [other]


def test_api_levels_truncated_accumulator_falls_through_to_banked(monkeypatch, tmp_path):
    """t12 (RC-227 residual): a TRUNCATED prior session in the accumulator must not serve
    a wrong PDL — coverage below the full-session floor falls through to banked bars.
    Measured live: PDL 756.84 (truncated min) vs true 749.59 while PDH/PDC matched."""
    import json
    import sqlite3
    from datetime import datetime as _dt

    import server as srv
    from time_et import ET

    def _bar_ms(y, mo, d, h, mi, o, hi, lo, c):
        return {"timestamp": int(_dt(y, mo, d, h, mi, tzinfo=ET).timestamp() * 1000),
                "open": o, "high": hi, "low": lo, "close": c, "volume": 100.0}

    # Accumulator: prior session PRESENT but only 3 bars — truncated tail, wrong low 756.
    truncated = [
        _bar_ms(2026, 8, 3, 15, 30, 757, 758, 756.84, 757),
        _bar_ms(2026, 8, 3, 15, 59, 757, 758.58, 757, 757.67),
        _bar_ms(2026, 8, 4, 9, 45, 758, 759, 757, 758),
    ]
    monkeypatch.setattr(srv, "_liquidity_live_1m_overlay_bars", lambda t: truncated)
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (758.0, "schwab_quote_last", 1.0))
    import time_et as te
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 8, 4, 10, 0, tzinfo=ET))

    # Banked DB: the FULL prior session (390 bars) with the true low 749.59.
    dbf = tmp_path / "bank.db"
    con = sqlite3.connect(str(dbf))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    t0 = _dt(2026, 8, 3, 9, 30, tzinfo=ET).timestamp()
    for i in range(390):
        lo = 749.59 if i == 100 else 755.0
        con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                    ("SPY", t0 + i * 60, t0 + i * 60 + 60, 756, 758.58 if i == 200 else 757,
                     lo, 757.67 if i == 389 else 756, 100.0, "bank"))
    con.commit(); con.close()

    class _Db:
        db_path = str(dbf)
    monkeypatch.setattr(srv, "get_db", lambda: _Db())

    payload = json.loads(bytes(srv.get_levels(ticker="SPY").body))
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDL"]["price"] == 749.59, (
        "truncated accumulator served its partial min — the t12 fallthrough is dead"
    )
    assert "banked" in by_id["PDL"]["provenance"]["vendor_basis"], (
        "provenance must name the banked source after the fallthrough"
    )


def test_api_levels_registered_in_faucet_registry():
    """RC-212 registry law: /api/levels must be a registered producer with the operator
    quote present in governance/level_faucets.json."""
    import json
    from pathlib import Path

    reg = json.loads((Path(__file__).resolve().parent.parent / "governance" /
                      "level_faucets.json").read_text(encoding="utf-8"))
    assert "/api/levels" in reg["level_domain_producers"]
    assert "levels-tierb-session-collapse-v1" in reg.get("operator_quote", ""), (
        "adding a producer requires the operator_quote in the registry (RC-212)"
    )


def test_market_context_session_families_carry_the_canonical_snapshot():
    """Tier-B kill lock, tightened by Phase 2A.

    The original form of this test demanded that `fetch_price_levels` DELEGATE to the
    engine helpers instead of running its own inline `cum_tpv` / ORB loops. Delegation
    killed the duplicate formulas but not the duplicate MATERIALIZATION: calling the
    same helper over a privately fetched bar window still produced a second answer, and
    that is exactly how /api/liquidity-snapshot came to serve overnight 773.40/772.55
    against /api/levels' 773.3975/773.3975 for one ticker at one instant.

    So the requirement is now strictly stronger — not "call the helper" but "call
    nothing": carry the canonical PriceLevelSnapshot. Every inline-dual assertion from
    the delegation era is kept below, because carriage must not reintroduce them.
    """
    import inspect

    from market_context import fetch_price_levels

    src = inspect.getsource(fetch_price_levels)
    for name in (
        "compute_session_vwap",
        "compute_vwap_bands",
        "compute_opening_range",
        "get_overnight_levels",
        "compute_volume_profile_levels",
    ):
        assert f"{name}(" not in src, (
            f"fetch_price_levels INVOKES {name} — a second materialization of a Phase 2A "
            f"level. It must carry the canonical snapshot's value instead."
        )
    assert "carry_snapshot_levels" in src, (
        "fetch_price_levels no longer carries the canonical PriceLevelSnapshot"
    )
    assert "get_price_history" not in src, (
        "the private vendor bar fetch is back — that is the alternate bar input that made "
        "the two endpoints disagree, not a fallback"
    )
    assert "cum_tpv =" not in src, "inline VWAP dual still present"
    assert "orb_bars_seen" not in src, "inline ORB dual still present"
    assert "overnight_bars =" not in src and "overnight_bars.append" not in src, (
        "today-premarket overnight dual still present"
    )


def test_backfill_typical_price_vwap_substitution_hard_fails():
    """Census #2: typical-price must not fabricate a vwap when the column is absent."""
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent.joinpath(
        "backfill_snapshot_derived.py"
    ).read_text(encoding="utf-8")
    assert "eff_vwap = _typical_price(r)" not in src, (
        "typical-price vwap SUBSTITUTION must hard-fail to absent (census #2)"
    )
    assert "SUBSTITUTION is forbidden" in src


def test_rc124_merged_pin_tag_keeps_its_decisiveness():
    """RC-124 (2026-08-04): when the pin is coincident with a wall the axis tag MERGES, and
    the merge used to drop the lead % — measured live as `750.00 PWALL·PIN` while the payload
    carried gamma_pin_strength_pct 19.8. A near-tie pin and a decisive one must never render
    identically; absent strength still renders nothing rather than a fabricated number."""
    assert "const _pinSp = Number(T.gamma_pin_strength_pct);" in _CHART, (
        "the merged wall/pin tag no longer reads the pin's strength from the payload"
    )
    assert "'·PIN' + (Number.isFinite(_pinSp) ? ` ${_pinSp}%` : '')" in _CHART, (
        "the merged tag must append the strength when present and NOTHING when absent"
    )
    # the bare merge (decisiveness deleted) must not come back in either wall shape
    assert "`⬌WALL${pinHere ? '·PIN' : ''}`" not in _CHART
    assert "(sell ? 'CWALL' : 'PWALL') + (pinHere ? '·PIN' : '')" not in _CHART
