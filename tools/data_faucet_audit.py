"""DATA FAUCET AUDIT — mechanical proof of provenance for every rendered field (RC-73).

WHY. Single-source-of-truth is a governing law here, and it was enforced per-PRODUCER
(single_spot_authority, chain_width_single_faucet, vendor_field_coercion) while nothing could
answer the operator's actual question: *is this field on my screen live, and how many faucets feed
it?* Every answer was agent prose. That is how a 2.1-hour-frozen volume panel, a three-faucet spot
bind, a 110-hour-old scorecard file and a 19.1-minute bar lag all survived inside a system that
had already declared the law. A law with no instrument is enforced only by whoever happens to look.

WHAT THIS DOES. Statically traces every UI endpoint in server.py to the sources it reads, measures
each source's real AGE against the live DB, and counts how many distinct faucets feed each logical
data concept. It replaces narrative with a number.

  python tools/data_faucet_audit.py            # the report
  python tools/data_faucet_audit.py --check    # exit 1 if any concept has >1 faucet
  python tools/data_faucet_audit.py --json
  python tools/data_faucet_audit.py --watch 220   # LIVE: do the levels hold still, does volume move?

LIVE WATCH (RC-79/RC-80). A source can be single, declared and fresh and still be wrong, and the
static half cannot see it. /api/terrain once alternated between call=750/put=740 and
call=739/put=736 within ten seconds because two producers disagreed, and /api/terrain/strikes once
served today_source=terrain_live_cache with an age of 7.4s and ZERO rows. Both were found by
watching the running console, not by reading code — so that measurement is a mode of this tool
rather than a script someone has to remember to write again.

CLIENT SIDE (RC-75). The server half alone left the browser as the one surface no lock reached,
and that is where the damage appeared: SIX sites in chart.html each inlined their own spot
precedence, three skipping the 1.5s live poll, so the big legend rendered the live price while the
meta bar directly above the chart rendered the 15s cycle price — two prices, one screen. The
operator found the sixth by looking at it, after the first fix was reported complete. `audit_client`
therefore flags any READ of a source outside its declared authority function, not merely a line
that visibly combines two of them.

HONEST LIMIT, stated not hidden, and NOT a licence to leave it (RC-76). Detection is STATIC on
both halves. The SERVER half is enumerative — it matches DECLARED source signatures, so a source
reached through an alias it does not list is invisible and must be added to SOURCE_SIGNATURES. The
CLIENT half is structural and has no such gap: it flags ANY read of a spot-bearing name outside the
declared authority, whatever that name is, because the enumerative version of it passed a file that
was rendering two different prices on one screen.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: (regex over endpoint source, faucet id, liveness class, human note)
SOURCE_SIGNATURES: tuple[tuple[str, str, str, str], ...] = (
    (r"resolve_spot\(",              "resolve_spot",        "LIVE",        "live vendor quote (cached ~1.25s)"),
    (r"safe_get_chain\(",            "vendor_chain",        "LIVE",        "live vendor chain fetch"),
    (r"_terrain_cache|terrain_cache_get", "terrain_cache",  "LOOP",        "in-process cache, terrain loop cadence"),
    (r"FROM\s+option_chain_morning_full", "morning_archive", "ARCHIVE",    "once-daily morning capture (frozen)"),
    (r"FROM\s+price_bars_1m",        "price_bars_1m",       "DB_TABLE",    "bar collection service writes this"),
    (r"FROM\s+snapshots\b",          "snapshots",           "DB_TABLE",    "per-minute snapshot capture"),
    (r"FROM\s+level_crosses",        "level_crosses",       "DB_TABLE",    "event log"),
    (r"terrain_backtest_latest\.json", "scorecard_file",    "REPORT_FILE", "batch study artifact"),
)

#: `resolve_spot` is the ONE spot authority (RC-14). Every endpoint calling it is COMPLIANCE, not
#: duplication, so it is excluded from the per-concept data-source count — otherwise the correct
#: behaviour would score as a violation and the report would cry wolf on its own law.
UNIVERSAL_AUTHORITIES = frozenset({"resolve_spot"})

#: Logical concept -> endpoints that render it. >1 distinct DATA faucet for one concept is a
#: violation (the spot authority above is excluded from the count).
CONCEPTS: dict[str, tuple[str, ...]] = {
    "spot":          ("/api/spot",),
    "price_bars":    ("/api/bars1m",),
    "levels":        ("/api/terrain",),
    "per_strike":    ("/api/terrain/strikes",),
    "coach_stats":   ("/api/terrain/scorecard",),
    "level_events":  ("/api/level_crosses",),
}

#: DECLARED legitimate faucets per concept. A source outside this set is a violation; a source
#: inside it is a deliberate, reviewed second field — not a fallback. This is the difference the
#: report must capture: /api/terrain/strikes reads the live cache for TODAY and the archive for
#: the PRIOR-DAY GHOST. Those are two fields, not two sources for one field. Declaring it here
#: keeps that legitimate, while any NEW source silently appearing still fails.
DECLARED_FAUCETS: dict[str, frozenset[str]] = {
    "spot":         frozenset(),                 # resolve_spot only (universal authority)
    "price_bars":   frozenset({"price_bars_1m"}),
    "levels":       frozenset({"terrain_cache"}),
    # today -> terrain_cache (live). prior-day ghost -> morning_archive (yesterday cannot change).
    "per_strike":   frozenset({"terrain_cache", "morning_archive"}),
    "coach_stats":  frozenset({"scorecard_file"}),
    "level_events": frozenset({"level_crosses"}),
}

FRESH_LIMITS = {"LIVE": 60, "LOOP": 180, "DB_TABLE": 300, "ARCHIVE": 86400, "REPORT_FILE": 86400}

#: CLIENT concepts (RC-75/RC-76). `reader` matches ANY read of the concept in the browser;
#: `authorities` are the only functions allowed to decide between sources. A read anywhere else is
#: a private precedence — that line picks its own faucet, and two such lines is two prices.
CLIENT_CONCEPTS: dict[str, dict] = {
    "spot": {
        "files": ("static/chart.html",),
        # ALIAS-PROOF BY CONSTRUCTION. An earlier version listed the source variable names
        # (`strikes.spot`, `terrain.spot`) and scored this file clean while the meta bar rendered
        # `(s && s.spot) ?? t.spot` — the same two sources reached through the local aliases of a
        # Promise.all destructure. The operator was looking at two different prices on one screen
        # while the audit reported one faucet. The rule is therefore structural: ANY read of a
        # spot-bearing name, whatever it happens to be called, is a violation outside the authority.
        # RC-225: _cycleSpot DELETED — authorities are the /api/spot binding + as_of helpers only.
        "reader": r"\bliveSpot\b|\b[A-Za-z_$][\w$]*\.spot\b",
        "authorities": (
            "currentSpot",
            "spotBindingAgeSec",
            "spotBindingStale",
            "spotBindingAgeLabel",
        ),
        # The only functions allowed to ingest the raw /api/spot payload and feed the authority.
        "writers": ("pollSpot", "_dropLiveSpot"),
        # A bare state reset (`liveSpot = null`) chooses no faucet and renders nothing.
        "assign_only": r"\bliveSpot\s*=",
    },
    # RC-225: exposure had the same silent strikes/terrain age fork; same structural rule.
    "exposure_spot": {
        "files": ("static/exposure.html",),
        "reader": r"\bliveSpot\b|\b[A-Za-z_$][\w$]*\.spot\b",
        "authorities": (
            "currentSpot",
            "spotBindingAgeSec",
            "spotBindingStale",
            "spotBindingAgeLabel",
        ),
        "writers": ("pollSpot",),
        "assign_only": r"\bliveSpot\w*\s*=",
    },
    # RC-77. The console page carries the same defect class on a much larger surface, so its
    # reader is NARROW BY NECESSITY rather than by preference: `r.spot` on a ladder row is a
    # boolean "this is the spot row" flag, not a price, and a check that flags it would be a
    # false positive — and this repo does not enforce a check that produces those. So the reader
    # matches only what RENDERS OR CHOOSES a price: a numeric coercion of a `.spot` field, a
    # `??`/`||` precedence between two of them, or a raw read of the SSE fast lane.
    "console_spot": {
        "files": ("static/index.html",),
        "reader": (r"parseFloat\(\s*[\w$]+\.spot\b|Number\(\s*[\w$]+\.spot\b"
                   r"|fnum\([^)]*\.spot\b|[\w$]+\.spot\s*(?:\?\?|\|\|)"
                   r"|(?:\?\?|\|\|)\s*[\w$]+\.spot\b|\bwindow\._fastLaneSpot\b"
                   r"|\bedLiveSpot\s*\("),
        "authorities": ("consoleSpot", "effectiveDisplaySpot"),
        # Lane management and fast-repaint paths: they FEED the authority or repaint from the
        # lane itself. edLiveSpot is the raw lane accessor — legitimate to read the lane,
        # never to choose between faucets.
        "writers": ("_livePlaneApplyCore", "_quoteLaneShouldApply", "_syncQuoteLaneFromMergedState",
                    "setActiveTicker", "edLiveSpot", "edPaintSpot", "edLoadRadar",
                    "computeSpreadGate"),
        # `window._fastLaneSpot = …` (write), `!== window._fastLaneSpot` (change detection),
        # `_fastLaneSpot: window._fastLaneSpot` (injection into the pure computeSpreadGate, which
        # needs a REFERENCE price to convert a fractional spread to a dollar width and never
        # renders one), and `x.spot == null` guards all choose nothing and display nothing.
        "assign_only": (r"window\._fastLaneSpot\w*\s*=|[!=]==?\s*window\._fastLaneSpot"
                        r"|_fastLaneSpot\s*:\s*window\._fastLaneSpot|\.spot\s*[!=]=\s*null"),
    },
}

_JS_FUNC = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")


def _strip_comments(text: str) -> list[str]:
    """Blank out // and /* */ comments, preserving line count so numbers stay true.

    Block comments matter: the RC-77 comment explaining the fix quoted the defective expression
    it replaced, and a line-comment-only stripper reported the explanation as two violations."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return [re.sub(r"//.*$", "", ln) for ln in text.splitlines()]


def _js_function_at(lines: list[str]) -> list[str | None]:
    """Enclosing top-level function name for each line, by brace depth. Good enough for these
    files, which declare plain `function name(...)` at depth 0 — and a wrong answer here can only
    make the audit STRICTER (a line attributed to no function is still checked)."""
    out: list[str | None] = []
    cur: str | None = None
    fn_depth = depth = 0
    for line in lines:
        code = re.sub(r"//.*$", "", line)
        if cur is None:
            m = _JS_FUNC.search(code)
            if m:
                cur, fn_depth = m.group(1), depth
        out.append(cur)                     # the `function foo() {` line belongs to foo
        depth += code.count("{") - code.count("}")
        if cur is not None and depth <= fn_depth:
            cur = None                      # body closed
    return out


def audit_client() -> list[dict]:
    """Lines that read a concept's source outside its declared authority.

    A read anywhere else is a PRIVATE PRECEDENCE: that line decides for itself which faucet wins,
    and two such lines on one screen is two prices. Writes are exempt — the poller must be able to
    feed the authority, and a reset to null renders nothing."""
    bad: list[dict] = []
    for concept, spec in CLIENT_CONCEPTS.items():
        reader = re.compile(spec["reader"])
        assign_only = re.compile(spec["assign_only"])
        for rel in spec["files"]:
            path = _ROOT / rel
            if not path.exists():
                bad.append({"concept": concept, "undeclared": [f"missing client file {rel}"]})
                continue
            code_lines = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"))
            owners = _js_function_at(code_lines)
            for i, (code, owner) in enumerate(zip(code_lines, owners), 1):
                if not reader.search(code):
                    continue
                if owner in spec["authorities"] or owner in spec["writers"]:
                    continue
                # Remove the exempt constructs (lane writes, change detection, null guards,
                # injection) and re-test: a line is only clean if NOTHING that reads a price
                # survives. Matching the exemption anywhere on the line is not enough — that
                # would let `liveSpot = strikes.spot` pass on the strength of its left side.
                if not reader.search(assign_only.sub(" ", code)):
                    continue
                bad.append({"concept": f"{concept} (client)",
                            "undeclared": [f"{rel}:{i} reads a {concept} source outside "
                                           f"{'/'.join(spec['authorities'])}(): "
                                           f"{code.strip()[:64]}"]})
    return bad


def endpoint_sources(server_src: str) -> dict[str, list[dict]]:
    """endpoint path -> [{faucet, liveness, note}] traced statically from its handler body."""
    tree = ast.parse(server_src)
    out: dict[str, list[dict]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        paths = [
            d.args[0].value
            for d in node.decorator_list
            if isinstance(d, ast.Call) and d.args
            and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)
            and d.args[0].value.startswith("/api/")
        ]
        if not paths:
            continue
        seg = ast.get_source_segment(server_src, node) or ""
        hits = [
            {"faucet": fid, "liveness": live, "note": note}
            for pat, fid, live, note in SOURCE_SIGNATURES
            if re.search(pat, seg, re.I)
        ]
        for p in paths:
            out.setdefault(p, [])
            for h in hits:
                if h not in out[p]:
                    out[p].append(h)
    return out


def measure_ages(db_path: str) -> dict[str, float | None]:
    """Real age in seconds of each measurable faucet. None = unmeasurable/not applicable."""
    now = time.time()
    ages: dict[str, float | None] = {k: None for _, k, _, _ in SOURCE_SIGNATURES}
    # RC-407: a read-age MEASUREMENT must never create-on-connect. sqlite3.connect(path)
    # defaults to read-write-create and planted an empty data/ed_console.db when the file
    # was absent — that 0-byte DB then failed db-health and blocked a commit. Absent file =
    # unmeasurable; the connection is read-only so it can neither create nor mutate.
    if not os.path.exists(db_path):
        return ages
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    except sqlite3.Error:
        return ages
    try:
        for faucet, sql in (
            ("price_bars_1m", "SELECT MAX(bar_start_ts_utc) FROM price_bars_1m"),
            ("snapshots", "SELECT MAX(ts_utc) FROM snapshots"),
            ("level_crosses", "SELECT MAX(ts_utc) FROM level_crosses"),
            ("morning_archive", "SELECT MAX(ts_utc) FROM option_chain_morning_full"),
        ):
            try:
                v = con.execute(sql).fetchone()[0]
                if v:
                    t = float(v)
                    ages[faucet] = now - (t / 1000.0 if t > 1e12 else t)
            except sqlite3.Error:
                pass
    finally:
        con.close()
    p = _ROOT / "reports" / "terrain_backtest_latest.json"
    if p.exists():
        ages["scorecard_file"] = now - p.stat().st_mtime
    return ages


def _fmt(a: float | None) -> str:
    if a is None:
        return "n/a"
    return f"{a/3600:.1f}h" if a >= 3600 else f"{a/60:.0f}m"


def run(db_path: str) -> dict:
    src = (_ROOT / "server.py").read_text(encoding="utf-8", errors="ignore")
    eps = endpoint_sources(src)
    ages = measure_ages(db_path)
    violations = []
    concepts = {}
    for concept, paths in CONCEPTS.items():
        faucets: list[str] = []
        for p in paths:
            for h in eps.get(p, []):
                if h["faucet"] in UNIVERSAL_AUTHORITIES:
                    continue        # the single spot authority — using it everywhere is the law
                if h["faucet"] not in faucets:
                    faucets.append(h["faucet"])
        concepts[concept] = faucets
        declared = DECLARED_FAUCETS.get(concept, frozenset())
        undeclared = [f for f in faucets if f not in declared]
        if undeclared:
            violations.append({"concept": concept, "undeclared": undeclared,
                               "declared": sorted(declared)})
    stale = [
        {"faucet": f, "age_sec": round(a), "limit_sec": FRESH_LIMITS.get(live, 300)}
        for _, f, live, _ in SOURCE_SIGNATURES
        for a in [ages.get(f)]
        if a is not None and a > FRESH_LIMITS.get(live, 300)
    ]
    client_bad = audit_client()
    violations.extend(client_bad)
    return {"endpoints": eps, "ages_sec": {k: (round(v) if v is not None else None)
                                           for k, v in ages.items()},
            "concepts": concepts, "faucet_violations": violations,
            "client_violations": client_bad, "stale_sources": stale}


def render(rep: dict) -> str:
    L = ["", "=" * 78, "DATA FAUCET AUDIT — provenance of every rendered field", "=" * 78,
         "", "ENDPOINT -> SOURCES (static trace) + measured age", "-" * 78]
    for ep in sorted(rep["endpoints"]):
        hits = rep["endpoints"][ep]
        if not hits:
            L.append(f"  {ep:26s} (no recognised source signature)")
            continue
        for h in hits:
            a = rep["ages_sec"].get(h["faucet"])
            L.append(f"  {ep:26s} {h['liveness']:<11s} {h['faucet']:<17s} age={_fmt(a):>6s}  {h['note']}")
    L += ["", "ONE FAUCET PER CONCEPT", "-" * 78]
    bad = {v["concept"] for v in rep["faucet_violations"]}
    for c, f in rep["concepts"].items():
        mark = "FAIL" if c in bad else "OK  "
        L.append(f"  [{mark}] {c:14s} {len(f)} faucet(s): {', '.join(f) or '(none traced)'}")
    if rep["stale_sources"]:
        L += ["", "SOURCES PAST THEIR FRESHNESS BUDGET", "-" * 78]
        for s in rep["stale_sources"]:
            L.append(f"  {s['faucet']:<18s} age={_fmt(s['age_sec'])} > limit {_fmt(s['limit_sec'])}")
    L += ["", "CLIENT-SIDE BINDS (RC-75)", "-" * 78]
    cv = rep.get("client_violations", [])
    if not cv:
        for c, spec in CLIENT_CONCEPTS.items():
            L.append(f"  [OK  ] {c:14s} bound only inside {', '.join(spec['authorities'])}"
                     f"  ({', '.join(spec['files'])})")
    for v in cv:
        L.append(f"  [FAIL] {v['concept']:14s} {v['undeclared'][0]}")
    L += ["", f"FAUCET VIOLATIONS: {len(rep['faucet_violations'])}"
          f"  (server {len(rep['faucet_violations']) - len(cv)}, client {len(cv)})",
          "NOTE: static. SERVER half traces declared source signatures (a source reached by an",
          "      unlisted alias is not visible there). CLIENT half is structural: ANY spot read",
          "      outside the authority is caught regardless of what it is named.",
          "=" * 78]
    return "\n".join(L)


def watch_live(seconds: int = 220, base: str = "http://127.0.0.1:8000") -> dict:
    """Poll the RUNNING console and measure what no static check can see: whether the levels hold
    still and whether the volume panel actually moves.

    RC-80 was found this way and by nothing else — /api/terrain alternated between two sets of
    walls seconds apart because two producers disagreed, while every static check reported one
    faucet and was right about the read side. RC-79 the same: today_source=terrain_live_cache with
    an age of 7.4s and ZERO rows. A source can be single, declared and fresh and still be wrong,
    so the instrument has to watch the values themselves over time.
    """
    import urllib.request

    def _get(path: str):
        try:
            with urllib.request.urlopen(base + path, timeout=40) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            return {"__err__": f"{type(e).__name__}: {e}"}

    levels: list[tuple] = []
    volumes: list[int] = []
    ages: list[float] = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        t = _get("/api/terrain?ticker=SPY")
        s = _get("/api/terrain/strikes?ticker=SPY")
        key = (t.get("call_wall"), t.get("put_wall"), t.get("gamma_flip"))
        if key[0] is not None and (not levels or key != levels[-1]):
            levels.append(key)
        rows = (s.get("today") or {}).get("all") or []
        v = sum(r[2] for r in rows if len(r) > 2)
        if not volumes or v != volumes[-1]:
            volumes.append(v)
        if s.get("today_age_sec") is not None:
            ages.append(float(s["today_age_sec"]))
        time.sleep(10)

    walls = sorted({k[0] for k in levels if k[0] is not None})
    puts = sorted({k[1] for k in levels if k[1] is not None})
    flips = [k[2] for k in levels if k[2] is not None]
    return {
        "seconds": seconds,
        "call_wall_values": walls,
        "put_wall_values": puts,
        "flip_span": round(max(flips) - min(flips), 4) if flips else None,
        "levels_stable": len(walls) <= 1 and len(puts) <= 1,
        "volume_first": volumes[0] if volumes else None,
        "volume_last": volumes[-1] if volumes else None,
        "volume_delta": (volumes[-1] - volumes[0]) if len(volumes) > 1 else 0,
        "volume_live": len(volumes) > 1 and volumes[-1] > volumes[0],
        "panel_age_max_sec": round(max(ages), 1) if ages else None,
    }


def render_watch(w: dict) -> str:
    ok = lambda b: "OK  " if b else "FAIL"          # noqa: E731
    return "\n".join([
        "", "=" * 78, f"LIVE WATCH — {w['seconds']}s against the running console", "=" * 78,
        f"  [{ok(w['levels_stable'])}] levels stable    call_wall={w['call_wall_values']} "
        f"put_wall={w['put_wall_values']} flip_span={w['flip_span']}",
        f"  [{ok(w['volume_live'])}] volume live      {w['volume_first']:,} -> {w['volume_last']:,} "
        f"(delta {w['volume_delta']:+,})" if w["volume_first"] is not None else
        "  [FAIL] volume live      no rows served",
        f"         panel age max    {w['panel_age_max_sec']}s",
        "=" * 78,
    ])


def freshness_violations(base: str = "http://127.0.0.1:8000") -> list[dict]:
    """A rendered field whose SOURCE is correct but whose DATA has stopped moving (RC-91).

    PROVENANCE IS NOT FRESHNESS, and conflating them is how this audit reported a clean bill while
    the gamma panel served levels 90 MINUTES old: one declared source, no fallback, every faucet
    check green — and the terrain loop had stopped at the background-logging window (16:30 ET).
    Naming the right tap proves only that it was opened, never that anything is still coming out.

    Returns [] when no console is reachable, and says so via the `unreachable` marker rather than
    implying freshness nobody measured.
    """
    import urllib.request

    def get(path: str):
        try:
            with urllib.request.urlopen(base + path, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            return {"__err__": f"{type(e).__name__}: {e}"}

    probe = get("/api/spot?ticker=SPY")
    if "__err__" in probe:
        return [{"concept": "(console unreachable)", "detail": probe["__err__"][:70],
                 "unreachable": True}]
    out: list[dict] = []
    d = get("/api/terrain/strikes?ticker=SPY")
    if "__err__" not in d and d.get("levels_stale"):
        out.append({"concept": "per_strike/levels",
                    "detail": d.get("levels_stale_reason") or "levels are stale",
                    "age_sec": d.get("levels_age_sec"),
                    # RC-120: the payload says whether the producer SHOULD be running. False
                    # after 16:30 ET is the designed, labeled, budgeted state (RC-91/RC-78) —
                    # consumers that gate on staleness need this to tell broken from closed.
                    "refresh_active": d.get("levels_refresh_active")})
    return out


def main(argv: list[str]) -> int:
    if "--watch" in argv:
        i = argv.index("--watch")
        secs = int(argv[i + 1]) if len(argv) > i + 1 and argv[i + 1].isdigit() else 220
        w = watch_live(secs)
        print(json.dumps(w, indent=2) if "--json" in argv else render_watch(w))
        return 0 if (w["levels_stable"] and w["volume_live"]) else 1
    db = next((a for a in argv if not a.startswith("--")), os.path.join("data", "ed_console.db"))
    rep = run(db)
    print(json.dumps(rep, indent=2) if "--json" in argv else render(rep))
    if "--check" in argv and rep["faucet_violations"]:
        print(f"\n[FAIL] {len(rep['faucet_violations'])} concept(s) fed by more than one faucet.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
