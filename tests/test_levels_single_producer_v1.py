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


def test_the_single_producer_computes_from_the_full_chain():
    """The one producer reads the FULL chain (2026-09-25: the strike window moved or lost levels
    on a third of the board)."""
    seg = _fn("_terrain_refresh_one")
    assert "fetch_full_chain(" in seg, "the producer no longer computes from the full chain"
    assert "strike_count" not in seg, "the producer narrowed its chain to a strike window again"
    assert "priority" in seg, "the producer cannot serve an operator-facing miss with priority"


def test_levels_producers_are_enumerated_and_declared():
    """Any NEW producer must be declared here deliberately, with the reason it may exist.

    _publish_levels is THE producer of the terrain cache: the terrain loop's chain fetch
    (_terrain_refresh_one) and every tick-driven reprice of a viewed ticker publish through it,
    one at a time per ticker, from the one kept chain.

    _radar_fallback_recompute (the stored-chain radar sweep, RC-80) is no longer declared: it
    was deleted with the uncalled /api/terrain/radar route it served, so _publish_levels is now
    the only level producer in server.py.
    """
    declared = {"_publish_levels"}
    found = {fn for _, fn in _producers()}
    assert found == declared, (
        f"the set of level producers changed: {sorted(found)} != {sorted(declared)}. "
        "Every producer is a chance for two answers to disagree — add it here with its reason, "
        "or route it through _terrain_refresh_one."
    )


# ── RC-122 (W3-C1, operator P0b): ONE wall book on the screen ────────────────────────────────

def _overlay(cache_entry, monkeypatch):
    import time

    import server as S
    if cache_entry is not None:
        entry = dict(cache_entry)
        if "computed_ts_utc" not in entry:
            entry["computed_ts_utc"] = (
                time.time() - 99999.0 if entry.get("levels_stale") else time.time()
            )
    else:
        entry = None
    monkeypatch.setattr(S, "_terrain_cache",
                        {"SPY": entry} if entry is not None else {})
    md = {"kl_call_gamma_wall": 111.0, "kl_put_gamma_wall": 222.0, "kl_gamma_flip": 333.0,
          "kl_absolute_gamma_strike": 444.0, "kl_hvl": 555.0, "kl_max_pain": 666.0,
          "kl_call_gamma_str": "$9.9M/pt", "kl_put_gamma_str": "$8.8M/pt"}
    S._terrain_kl_overlay(md, "SPY")
    return md












# ── RC-128 (operator mandate: ONE Levels Faucet) ─────────────────────────────────────────────
# The invariant, enforced structurally: for every SSOT level concept there is exactly ONE
# writer of its payload key — the carriage helper. The analytics assignments were DELETED,
# not overridden; this lock fails the day any second writer returns, wherever it is placed.

SSOT_KEYS = (
    "kl_call_gamma_wall", "kl_put_gamma_wall", "kl_gamma_flip", "kl_absolute_gamma_strike",
    # RC-292: the qualified pin claim and its blockers ride the same single writer.
    "kl_pin_candidate", "kl_pin_candidate_blockers", "kl_hvl",
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
    # RC-441: computed_ts_utc=1.0 forces the RC-162 stale-path accrual-bank read
    # (server.get_terrain_strikes -> latest_accrual_rows). Without stubbing it, this "unit"
    # test calls latest_accrual_rows against the live DB, so `today` is silently overridden by
    # whatever real SPY rows exist — the test then passes on an empty DB but fails on a
    # populated one (env-dependent, non-hermetic). Stub it so the fixture stays authoritative.
    monkeypatch.setattr(srv, "latest_accrual_rows", lambda *a, **k: None)
    resp = srv.get_terrain_strikes(ticker="SPY")
    payload = json.loads(bytes(resp.body))
    ss = payload["today_side_sums"]
    assert ss["gex_below"] == 10.0 and ss["gex_above"] == -4.0
    assert ss["vol_below"] == 100 and ss["vol_above"] == 50
    assert ss["spot_basis"] == 100.0, "sums must be computed against the payload's own spot"


def test_terrain_strikes_registers_viewing_demand(monkeypatch):
    """Operator-reproduced defect (2026-09-14, "the collection schedule must not block live
    viewing"): _note_gamma_surface_demand was only ever called from get_options_gamma_surface
    (the Heatmap grid's own route). GEX-by-Strike, the Trade Desk Positioning Migration panel,
    and the Chart view all read /api/terrain/strikes instead and never registered that anyone
    was watching -- a ticker viewed only through one of those three screens could never reach
    _terrain_loop's viewed-ticker set (see test_terrain_surface_gate_v1.py's companion test),
    so it never got a live refresh attempt regardless of enrollment. Every screen that shows a
    ticker's live terrain-derived data must register the same demand signal."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "terrain_cache_get", lambda tk: {
        "_per_strike": {"all": [], "near": [], "far": []}, "spot": 100.0, "computed_ts_utc": 1.0,
    })
    monkeypatch.setattr(srv, "resolve_spot", lambda tk, **kw: (100.0, "schwab_quote_last", 1.0))
    monkeypatch.setattr(srv, "latest_accrual_rows", lambda *a, **k: None)
    tk = srv.ticker_storage_key("ZZDEMANDONLY")
    srv._gamma_surface_demand.pop(tk, None)
    try:
        assert srv._gamma_surface_wanted(tk) is False, "must start with no recorded demand"
        resp = srv.get_terrain_strikes(ticker="ZZDEMANDONLY")
        json.loads(bytes(resp.body))   # a real, well-formed response — not the point of this test
        assert srv._gamma_surface_wanted(tk) is True, (
            "GET /api/terrain/strikes must register viewing demand for its ticker, the same as "
            "/api/options/gamma-surface already does -- otherwise the terrain loop never learns "
            "anyone is watching a ticker that only this route serves")
    finally:
        srv._gamma_surface_demand.pop(tk, None)


def test_chart_level_titles_carry_session_scope_and_vendor_basis():
    """RC-305: /api/levels serves session_scope and vendor_basis on every row's provenance
    and the chart rendered the prices with neither qualifier. EXECUTED against the REAL
    `levelProvenanceTitle` extracted from chart.html (the RC-355 extract-and-run idiom):
    a served scope/basis ride the level tooltip; an absent one reads "unknown", never a
    fabricated default. The server half is already behavioural in this file
    (test_api_levels_b1_contract_single_session_prior_day asserts
    provenance.session_scope == "RTH" on a real get_levels payload, and
    test_api_levels_truncated_accumulator_falls_through_to_banked asserts the PDL
    vendor_basis)."""
    import re
    import subprocess

    m = re.search(r"function levelProvenanceTitle\(title, prov\) \{.*?\n\}", _CHART, re.S)
    assert m, "levelProvenanceTitle must exist in chart.html"
    assert "levelProvenanceTitle(title, row.provenance)" in _CHART, (
        "renderEngineLevels no longer routes the tooltip through the qualifier builder")
    assert 'title="${esc(r.title)}"' in _CHART, (
        "the manager span lost its title binding — the qualifier reaches no DOM surface")
    driver = (
        m.group(0) + "\n"
        "const full = levelProvenanceTitle('prior-day low',"
        " {session_scope: 'RTH', vendor_basis: '1m bars (bars1m); schwab pricehistory'});\n"
        "if (!full.includes('RTH session')) throw new Error('scope missing: ' + full);\n"
        "if (!full.includes('basis: 1m bars (bars1m); schwab pricehistory'))"
        " throw new Error('basis missing: ' + full);\n"
        "const bare = levelProvenanceTitle('prior-day low', null);\n"
        "if (!bare.includes('session scope unknown') || !bare.includes('vendor basis unknown'))"
        " throw new Error('absence not honest: ' + bare);\n"
        "if (bare.includes('RTH')) throw new Error('fabricated default scope: ' + bare);\n"
        "const half = levelProvenanceTitle('overnight high', {session_scope: 'extended'});\n"
        "if (!half.includes('extended session') || !half.includes('vendor basis unknown'))"
        " throw new Error('partial provenance mishandled: ' + half);\n"
        "console.log('LEVEL QUALIFIERS OK');\n"
    )
    p = subprocess.run(["node", "-e", driver], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    assert p.returncode == 0, f"level qualifier builder failed: {p.stderr[:400]}"
    assert "LEVEL QUALIFIERS OK" in p.stdout


def test_strip_states_the_server_spot_basis():
    """RC-305: today_side_sums carries spot_basis — the exact spot the SERVER bucketed the
    GEX/OV side sums against — and the strip rendered the sums with no spot ref while a
    differently-bound live pill sat between them. EXECUTED against the REAL
    `sideSumsBasisText` extracted from chart.html: a served basis renders as the row's
    spot ref; an absent one reads "unknown" with no number invented; absent sums render
    no text. The server half is test_strikes_payload_carries_server_side_sums above."""
    import re
    import subprocess

    m = re.search(r"function sideSumsBasisText\(ss\) \{.*?\n\}", _CHART, re.S)
    assert m, "sideSumsBasisText must exist in chart.html"
    assert "${basisTxt}" in _CHART and "'live session' + basisTxt" in _CHART, (
        "the GEX/OV strip rows no longer carry the server spot ref")
    driver = (
        "const fmt = (x, d = 2) => x == null ? '-' : Number(x).toFixed(d);\n"
        + m.group(0) + "\n"
        "const ref = sideSumsBasisText({gex_below: 1, spot_basis: 645.2});\n"
        "if (!ref.includes('spot ref') || !ref.includes('645.20'))"
        " throw new Error('served basis not stated: ' + ref);\n"
        "const missing = sideSumsBasisText({gex_below: 1});\n"
        "if (!missing.includes('spot ref unknown'))"
        " throw new Error('absent basis not honest: ' + missing);\n"
        "if (/[0-9]/.test(missing)) throw new Error('a number was invented: ' + missing);\n"
        "if (sideSumsBasisText(null) !== '') throw new Error('no sums must render no text');\n"
        "console.log('SPOT BASIS OK');\n"
    )
    p = subprocess.run(["node", "-e", driver], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    assert p.returncode == 0, f"spot basis builder failed: {p.stderr[:400]}"
    assert "SPOT BASIS OK" in p.stdout




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
        "server.py", '@app.get("/api/exposure/flow")\ndef f(): pass', registry_text)
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


def test_api_levels_prior_day_low_is_the_full_session_min_of_price_bars_1m(monkeypatch, tmp_path):
    """t12 (RC-227 residual): the PDL must be the min of the WHOLE prior session. Measured
    live: a truncated in-memory tape served PDL 756.84 vs the true 749.59 while PDH/PDC
    matched. price_bars_1m (written only from Schwab's streamed bars) is now the one bar
    source, so the full prior session there must set every prior-day level."""
    import json
    import sqlite3
    from datetime import datetime as _dt

    import server as srv
    from time_et import ET

    monkeypatch.setattr(srv._lpr, "forming_bar", lambda t: None)   # no forming minute
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (758.0, "schwab_quote_last", 1.0))
    import time_et as te
    monkeypatch.setattr(te, "now_et", lambda: _dt(2026, 8, 4, 10, 0, tzinfo=ET))

    # The FULL prior session (390 bars) with the true low 749.59 mid-session.
    dbf = tmp_path / "bars.db"
    con = sqlite3.connect(str(dbf))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    t0 = _dt(2026, 8, 3, 9, 30, tzinfo=ET).timestamp()
    for i in range(390):
        lo = 749.59 if i == 100 else 755.0
        con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                    ("SPY", t0 + i * 60, t0 + i * 60 + 60, 756, 758.58 if i == 200 else 757,
                     lo, 757.67 if i == 389 else 756, 100.0, "schwab_chart"))
    con.commit(); con.close()

    class _Db:
        db_path = str(dbf)
    monkeypatch.setattr(srv, "get_db", lambda: _Db())

    payload = json.loads(bytes(srv.get_levels(ticker="SPY").body))
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDL"]["price"] == 749.59, "PDL is not the full prior session's min"
    assert by_id["PDH"]["price"] == 758.58
    assert by_id["PDC"]["price"] == 757.67
    assert "price_bars_1m" in by_id["PDL"]["provenance"]["vendor_basis"], (
        "provenance must name the one bar source"
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






def test_rc124_merged_pin_tag_keeps_its_decisiveness():
    """RC-124 (2026-08-04): when the abs-gamma strike is coincident with a wall the axis tag
    MERGES, and the merge used to drop the lead % — measured live as `750.00 PWALL·PIN`
    while the payload carried a strength of 19.8%. A near-tie leader and a decisive one must
    never render identically; absent strength still renders nothing rather than a fabricated
    number. RC-292: field renamed absolute_gamma_strength_pct, tag renamed ABSΓ."""
    assert "const _pinSp = Number(T.absolute_gamma_strength_pct);" in _CHART, (
        "the merged wall/abs-gamma tag no longer reads the leader's strength from the payload"
    )
    assert "'·ABSΓ' + (Number.isFinite(_pinSp) ? ` ${_pinSp}%` : '')" in _CHART, (
        "the merged tag must append the strength when present and NOTHING when absent"
    )
    # the bare merge (decisiveness deleted) must not come back in either wall shape
    assert "`⬌WALL${pinHere ? '·ABSΓ' : ''}`" not in _CHART
    assert "(sell ? 'CWALL' : 'PWALL') + (pinHere ? '·ABSΓ' : '')" not in _CHART
    # and the pre-rename payload field must not be read anywhere on the chart
    assert "T.gamma_pin" not in _CHART, "a chart read of the retired gamma_pin field returned"
