"""Census #8 / RC-225 — per-screen spot binds ONE payload field with as_of visible.

Compute authority remains resolve_spot (RC-14). This lock kills BINDING-level dual ages:
chart/exposure must not borrow strikes.spot / terrain.spot when /api/spot is absent, and
must surface spot_as_of age so a stale binding cannot paint as current.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_SCAN = (
    "static/chart.html",
    "static/exposure.html",
)

# Silent dual-age shapes the mission kills.
_CYCLE_FALLBACK_RE = re.compile(
    r"_cycleSpot\s*\(|strikes\s*&&\s*strikes\.spot|terrain\s*\?\s*terrain\.spot"
    r"|strikes\.spot\s*\?\?"
    r"|liveSpot\s*!=\s*null[^\n]{0,120}strikes\.spot",
    re.M,
)
_CONSOLE_DUAL_FIELD_RE = re.compile(
    r"d\.spot\s*\?\?\s*d\.last_price\s*\?\?\s*d\.quote_mid"
    r"|parseFloat\(\s*d\.spot\s*\?\?\s*d\.last_price"
)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*$", "", text, flags=re.M)


def chart_binding_violations(text: str) -> list[str]:
    """Chart must bind spot from /api/spot only and expose as_of age."""
    out: list[str] = []
    code = _strip_comments(text)
    if "function currentSpot()" not in text:
        out.append("static/chart.html: missing currentSpot() authority")
    # Authority must NOT fall through to cycle payloads.
    m = re.search(r"function currentSpot\(\)\s*\{([^}]*)\}", code, re.S)
    if not m:
        out.append("static/chart.html: currentSpot() body not parseable")
    else:
        body = m.group(1)
        if "_cycleSpot" in body or "strikes" in body or "terrain" in body:
            out.append(
                "static/chart.html: currentSpot() still falls through to cycle payloads "
                "(RC-225 — /api/spot only)"
            )
        if "return liveSpot" not in body and "return liveSpot;" not in body.replace(" ", ""):
            # Allow `return liveSpot;` with whitespace variants.
            if not re.search(r"return\s+liveSpot\s*;", body):
                out.append(
                    "static/chart.html: currentSpot() must return liveSpot "
                    "(declared /api/spot binding)"
                )
    if "function _cycleSpot" in text:
        out.append(
            "static/chart.html: _cycleSpot remains — dual-age fallback faucet (RC-225 kill)"
        )
    if _CYCLE_FALLBACK_RE.search(code):
        out.append(
            "static/chart.html: strikes.spot / terrain.spot fallback shape remains (RC-225)"
        )
    if "function spotBindingAgeLabel" not in text:
        out.append("static/chart.html: missing spotBindingAgeLabel() as_of surface")
    if 'id="spotage"' not in text and "getElementById('spotage')" not in text:
        out.append("static/chart.html: missing #spotage as_of DOM binding")
    if "spotBindingAgeLabel()" not in code:
        out.append("static/chart.html: spotBindingAgeLabel() never called — as_of not visible")
    if "SPOT_STALE_SEC" not in text:
        out.append("static/chart.html: missing SPOT_STALE_SEC stale threshold")
    # The binding is the capture daemon's price socket (live_ui.py; audit of #280 moved it off
    # the /api/spot poll, Stage 1 of the live-UI architecture moved it off the console): every
    # row it pushes goes through the one writer. Its as_of is the server's trade_age_sec --
    # still required to be read and shown.
    if ("new WebSocket(url)" not in code or "spotSocketUrl()" not in code
            or "msg.rows.forEach((q) => ingestQuoteTick(q" not in code):
        out.append("static/chart.html: spot must bind the daemon price socket (live_ui)")
    if "addEventListener('quote_tick'" in code:
        out.append("static/chart.html: the console serves no price -- no quote_tick listener")
    if "trade_age_sec" not in text:
        out.append("static/chart.html: binding must read the server's trade_age_sec as_of")
    return out


def exposure_binding_violations(text: str) -> list[str]:
    out: list[str] = []
    code = _strip_comments(text)
    if "function currentSpot()" not in text:
        out.append("static/exposure.html: missing currentSpot() authority")
    if _CYCLE_FALLBACK_RE.search(code):
        out.append(
            "static/exposure.html: strikes.spot / terrain.spot fallback shape remains (RC-225)"
        )
    if "function spotBindingAgeLabel" not in text:
        out.append("static/exposure.html: missing spotBindingAgeLabel() as_of surface")
    if "spotBindingAgeLabel()" not in code:
        out.append("static/exposure.html: spotBindingAgeLabel() never called")
    # the daemon price socket (live_ui) is the binding; its as_of is the row's Schwab trade_ts
    if ("new WebSocket(url)" not in code or "msg.rows.forEach(ingestSpotRow)" not in code):
        out.append("static/exposure.html: spot must bind the daemon price socket (live_ui)")
    if "q.trade_ts" not in code:
        out.append("static/exposure.html: binding must read the row's trade_ts as_of")
    if "/api/spot" in code:
        out.append("static/exposure.html: no /api/spot poll -- prices come from the daemon socket")
    return out


def console_binding_violations(text: str) -> list[str]:
    """Legacy static/index.html's OWN spot-binding shape (a single consoleSpot(d) function
    reading one declared field, plus a #data-price-freshness age surface). Retained only for
    the negative-control test that exercises this function directly against a synthetic
    fixture (tests/test_spot_binding_single_payload_v1.py's
    test_console_dual_field_injection_screams) -- NOT wired into scan_tracked_static() below
    since the /console cutover (operator directive 2026-09-14). The new console has no single
    named spot-authority function to check the same way (static/js/ed-core.js's paintQuote()
    and every ed-*.js panel each read a spot field from their own already resolve_spot()-backed
    endpoint response inline, per call site, not through one shared consoleSpot()-shaped
    function) -- a real equivalent structural lock for that pattern is future work, not
    reproduced here. Independent-review finding: fix
    static/js/ed-trade-desk.js's own dual-response spot fallback (levelsD.spot : terrain.spot)
    directly instead, since both of ITS sources are already resolve_spot()-backed server-side
    and the fallback shape itself is what this lock exists to ban."""
    out: list[str] = []
    code = _strip_comments(text)
    if _CONSOLE_DUAL_FIELD_RE.search(code):
        out.append(
            "static/index.html: consoleSpot still falls through spot→last_price→quote_mid "
            "(RC-225 — one declared field)"
        )
    if "function consoleSpot" not in text:
        out.append("static/index.html: missing consoleSpot() authority")
    # Active-ticker binding must prefer the live-plane spot field.
    m = re.search(r"function consoleSpot\(d\)\s*\{(.*?)\n\}", code, re.S)
    if m:
        body = m.group(1)
        if "_fastLaneSpot" not in body:
            out.append(
                "static/index.html: consoleSpot no longer reads the live-plane spot field"
            )
        if "last_price" in body or "quote_mid" in body:
            out.append(
                "static/index.html: consoleSpot still reads last_price/quote_mid "
                "(silent dual field)"
            )
    # Freshness / age must remain visible for the price strip.
    if "data-price-freshness" not in text:
        out.append("static/index.html: missing #data-price-freshness as_of surface")
    return out


_JS_SPOT_ACCESS_RE = re.compile(r"([A-Za-z_$][\w$]*)\.spot\b")
_FALLBACK_OPERATOR_RE = re.compile(r"\?|\|\||\?\?|:")
_SIMPLE_ASSIGN_RE = re.compile(
    r"(?:^|[;{}]|\bvar\b|\blet\b|\bconst\b)\s*([A-Za-z_$][\w$]*)\s*=\s*([^=][^;]*)$"
)


def discover_frontend_execution_surfaces(root: Path | None = None) -> list[str]:
    """Every shipped static/**/*.js and static/*.html file, discovered by walking the tree --
    not a fixed roster (independent review, 2026-09-16: "replace the fixed eight-file roster
    ... with discovery of every shipped frontend JS/HTML execution surface"). A NEW file added
    to either location is covered automatically, the whole point of a durable lock. Sorted for
    deterministic output. node_modules / .git and anything under a leading dot are excluded on
    principle even though this repo does not currently vendor JS under static/."""
    r = root if root is not None else REPO
    out: list[str] = []
    for p in sorted((r / "static").rglob("*.js")):
        rel = p.relative_to(r).as_posix()
        if any(part.startswith(".") or part == "node_modules" for part in p.parts):
            continue
        out.append(rel)
    for p in sorted((r / "static").glob("*.html")):
        out.append(p.relative_to(r).as_posix())
    return out


def _mask_strings(code: str) -> str:
    """Replace the CONTENT of string/template literals with 'x' (same length, quotes kept) so
    a `.spot`, `;`, `(`, or `)` that only appears inside a string/comment-like text can never be
    mistaken for real code by the statement splitter or the taint scan below. Comments must
    already be stripped by the caller (_strip_comments) before this runs."""
    out = []
    i, n = 0, len(code)
    in_str: str | None = None
    while i < n:
        c = code[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                out.append("xx")
                i += 2
                continue
            if c == in_str:
                out.append(c)
                in_str = None
                i += 1
                continue
            out.append("x")
            i += 1
            continue
        if c in "\"'`":
            in_str = c
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _split_top_level_statements(code: str) -> list[str]:
    """Split masked (string-safe) code into top-level statements ended by ';' at ()/[] depth 0
    -- NOT split by physical line. A multi-line ternary/call wrapped in an outer '(' stays ONE
    statement here regardless of how many source lines it spans (independent review, 2026-09-16:
    "detection that survives multiline expressions"). '{'/'}' deliberately do NOT add depth --
    each ';'-terminated statement inside a block is still its own unit, keeping the taint/
    fallback check below reasonably local instead of treating a whole function body as one
    blob. Known limitation: a C-style `for (a; b; c)` header's internal ';'s would each end a
    "statement" early -- not a shape this codebase's spot-handling code uses (confirmed by
    reading it), accepted rather than adding a special case for a pattern that does not occur."""
    stmts: list[str] = []
    depth = 0
    buf: list[str] = []
    for c in code:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        buf.append(c)
        if c == ";" and depth == 0:
            stmts.append("".join(buf))
            buf = []
    if buf:
        stmts.append("".join(buf))
    return stmts


def _spot_roots_in(stmt: str, alias_roots: dict[str, str]) -> set[str]:
    """Every ORIGINAL source identifier (e.g. 'terrain', 'strikesData') reachable from this one
    statement's text, whether via a direct `ident.spot` read or via a variable already known
    (from an earlier statement in this file) to alias one -- closes the aliasing escape
    (independent review, 2026-09-16: "survives ... aliases"): `var s = strikesData.spot; ...
    (a != null ? a : s)` still names strikesData as a root even though the fallback site itself
    has no literal `.spot` text."""
    roots: set[str] = {m.group(1) for m in _JS_SPOT_ACCESS_RE.finditer(stmt)}
    for name, root in alias_roots.items():
        if re.search(r"\b" + re.escape(name) + r"\b", stmt):
            roots.add(root)
    return roots


def _update_alias_roots(stmt: str, alias_roots: dict[str, str]) -> None:
    """Extend alias_roots with any new `name = <expr>` assignment in this statement whose RHS
    traces to a `.spot` read (directly, or transitively through an already-tracked alias) --
    one pass per statement is enough since statements are processed in file order, so a chain
    `a = x.spot; b = a; c = b;` resolves one hop further with each subsequent statement."""
    m = _SIMPLE_ASSIGN_RE.search(stmt.rstrip(";").rstrip())
    if not m:
        return
    name, rhs = m.group(1), m.group(2)
    direct = _JS_SPOT_ACCESS_RE.search(rhs)
    if direct:
        alias_roots[name] = direct.group(1)
        return
    for alias_name, root in alias_roots.items():
        if re.search(r"\b" + re.escape(alias_name) + r"\b", rhs):
            alias_roots[name] = root
            return


def _comma_separated_top_level_groups(stmt: str) -> list[str]:
    """Every argument list of a function call in this statement, as raw comma-joined text --
    used to catch a HELPER-mediated fallback (independent review, 2026-09-16: "helper-mediated
    fallback"), e.g. `pickFirst(a.spot, b.spot)`: no `?`/`:`/`||`/`??` appears at the call site
    at all, but two different spot roots handed to the SAME call is the same defect the direct
    operator check exists to ban -- the fallback logic just lives inside the callee instead of
    inline. A plain identifier immediately before '(' is required (excludes control keywords
    `if`/`for`/`while`/`switch`/`catch` parenthesized conditions, which are not calls)."""
    out: list[str] = []
    for m in re.finditer(r"([A-Za-z_$][\w$]*)\s*\(", stmt):
        name = m.group(1)
        if name in ("if", "for", "while", "switch", "catch", "function"):
            continue
        depth = 1
        i = m.end()
        start = i
        while i < len(stmt) and depth > 0:
            if stmt[i] == "(":
                depth += 1
            elif stmt[i] == ")":
                depth -= 1
            i += 1
        out.append(stmt[start:i - 1])
    return out


def ed_js_dual_spot_fallback_violations(files: dict[str, str]) -> list[str]:
    """Generalized RC-225 dual-age-fallback check for the rebuilt console's per-file spot
    reads. console_binding_violations's own docstring already named this as a real gap ("a real
    equivalent structural lock for that pattern is future work, not reproduced here") after
    fixing ed-trade-desk.js's own instance of it by hand -- this closes that gap, then closes it
    further (independent git review, 2026-09-16, after the first version of this only matched a
    single same-line literal shape): no shared currentSpot()-shaped function exists in this
    architecture (each file reads its own already-resolve_spot()-backed endpoint response
    inline, per call site), so the chart/exposure-shaped scanners above cannot apply
    structurally, but the underlying defect (a spot value chosen from whichever of two
    independently-fetched payloads happens to be present -- which can reflect two different
    observation instants even when both trace back to resolve_spot on the backend) can still
    occur, and did: static/js/ed-gamma-chart.js read `(terrain && terrain.spot) != null ?
    terrain.spot : (strikesData && strikesData.spot)` (2026-09-15) -- /api/terrain and
    /api/terrain/strikes are two SEPARATE fetches, each independently resolved server-side.

    Operates on multiline-tolerant STATEMENTS (see _split_top_level_statements), not physical
    lines, and tracks single-hop variable ALIASING (see _spot_roots_in/_update_alias_roots) so
    extracting `.spot` into an intermediate variable before the fallback does not evade
    detection. Flags a statement combining TWO OR MORE DISTINCT root identifiers' spot origin
    via a fallback operator (?, :, ||, ??) OR by passing them as separate arguments to the SAME
    function call (a helper-mediated fallback -- the operator's own name for this escape
    shape). Names every root so a genuine multi-source computation (rare, and should be
    reviewed either way, not silently passed) is visible in the failure message."""
    out: list[str] = []
    for rel, text in files.items():
        code = _mask_strings(_strip_comments(text))
        alias_roots: dict[str, str] = {}
        for stmt in _split_top_level_statements(code):
            roots = _spot_roots_in(stmt, alias_roots)
            if len(roots) >= 2:
                if _FALLBACK_OPERATOR_RE.search(stmt):
                    out.append(
                        f"{rel}: dual-source spot fallback -- reads .spot from "
                        f"{sorted(roots)} combined with a fallback operator (RC-225): "
                        f"{stmt.strip()[:160]!r}"
                    )
                else:
                    for group in _comma_separated_top_level_groups(stmt):
                        group_roots = _spot_roots_in(group, alias_roots)
                        if len(group_roots) >= 2:
                            out.append(
                                f"{rel}: helper-mediated dual-source spot fallback -- "
                                f"{sorted(group_roots)} passed together as arguments to one "
                                f"call (RC-225): {stmt.strip()[:160]!r}"
                            )
            _update_alias_roots(stmt, alias_roots)
    return out


_NUMBER_SPOT_CALL_RE = re.compile(
    r"Number\(\s*([A-Za-z_$][\w$]*(?:\s*&&\s*[A-Za-z_$][\w$]*)?\.spot)\s*\)"
)


def _null_guarded_before(stmt: str, expr: str, call_start: int) -> bool:
    """True when `stmt`, BEFORE `call_start`, already tests the exact same base expression
    (the `x.spot` tail of `expr`, ignoring any leading `x &&` guard) against null/undefined --
    the `cond == null ? safe : Number(cond)` shape this file's own fixes now use is legitimate,
    not the defect being banned. Only recognizes a null-check on the IDENTICAL expression text;
    a differently-spelled equivalent guard is not credited (a stricter default is the safe
    default for a lock)."""
    base = expr.split("&&")[-1].strip()
    guard_re = re.compile(
        r"\b" + re.escape(base) + r"\s*(?:==|!=|===|!==)\s*null\b"
    )
    return bool(guard_re.search(stmt[:call_start]))


def spot_number_null_fabrication_violations(files: dict[str, str]) -> list[str]:
    """Number(null) === 0 and Number(undefined) === NaN -- only the second is honest absence.
    `Number(x && x.spot)` / `Number(x.spot)` silently fabricates a real, finite 0 whenever x is
    null/undefined or x.spot is itself explicitly null, which then passes every isFinite(spot)
    guard downstream as if it were a genuine price (independent git review, 2026-09-16: found
    live in static/js/ed-gamma-chart.js, ed-gamma-panels.js and ed-gamma.js, all fixed by
    extracting the raw value and checking `== null` BEFORE calling Number() on it). Flags any
    `Number(<ident>.spot)` / `Number(<ident> && <ident>.spot)` call NOT already preceded, in the
    same statement, by an explicit null-check on that identical expression -- see
    _null_guarded_before for exactly what counts as already-guarded (the shape this file's own
    fixes use, `expr == null ? NaN : Number(expr)`, is recognized and not re-flagged)."""
    out: list[str] = []
    for rel, text in files.items():
        code = _mask_strings(_strip_comments(text))
        for stmt in _split_top_level_statements(code):
            for m in _NUMBER_SPOT_CALL_RE.finditer(stmt):
                if _null_guarded_before(stmt, m.group(1), m.start()):
                    continue
                out.append(
                    f"{rel}: Number({m.group(1)}) fabricates a finite 0 on null/undefined -- "
                    f"check `== null` before converting (RC-225): {stmt.strip()[:160]!r}"
                )
    return out


def scan_tracked_static(repo: Path | None = None) -> list[str]:
    root = repo if repo is not None else REPO
    out: list[str] = []
    scanners = {
        "static/chart.html": chart_binding_violations,
        "static/exposure.html": exposure_binding_violations,
        "static/index.html": console_binding_violations,
    }
    for rel in _SCAN:
        path = root / rel
        if not path.is_file():
            out.append(f"{rel}: missing")
            continue
        out.extend(scanners[rel](path.read_text(encoding="utf-8", errors="ignore")))
    js_files: dict[str, str] = {}
    for rel in discover_frontend_execution_surfaces(root):
        if rel.endswith(".js"):
            js_files[rel] = (root / rel).read_text(encoding="utf-8", errors="ignore")
    out.extend(ed_js_dual_spot_fallback_violations(js_files))
    out.extend(spot_number_null_fabrication_violations(js_files))
    return out
