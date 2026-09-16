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
    if "spot_as_of_ts_utc" not in text:
        out.append("static/chart.html: poll must read spot_as_of_ts_utc from /api/spot")
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
    if "spot_as_of_ts_utc" not in text:
        out.append("static/exposure.html: poll must read spot_as_of_ts_utc")
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


def ed_js_dual_spot_fallback_violations(files: dict[str, str]) -> list[str]:
    """Generalized RC-225 dual-age-fallback check for the rebuilt console's per-file spot
    reads (static/js/ed-*.js). console_binding_violations's own docstring already named this
    as a real gap ("a real equivalent structural lock for that pattern is future work, not
    reproduced here") after fixing ed-trade-desk.js's own instance of it by hand -- this closes
    that gap. No shared currentSpot()-shaped function exists in this architecture (each file
    reads its own already-resolve_spot()-backed endpoint response inline, per call site), so
    the chart/exposure-shaped scanners above cannot apply structurally, but the underlying
    defect (a spot value chosen from whichever of two independently-fetched payloads happens
    to be present -- which can reflect two different observation instants even when both trace
    back to resolve_spot on the backend) can still occur, and did: static/js/ed-gamma-chart.js
    read `(terrain && terrain.spot) != null ? terrain.spot : (strikesData && strikesData.spot)`
    (independent git review, 2026-09-15) -- /api/terrain and /api/terrain/strikes are two
    SEPARATE fetches, each independently resolved server-side. Fixed to read spot from exactly
    one endpoint (terrain), letting the existing isFinite(spot) guards handle absence honestly
    instead of silently substituting a different endpoint's number.

    Flags any single line combining two DIFFERENT identifiers' `.spot` reads with a fallback
    operator (?, :, ||, ??) -- a per-line heuristic, matching this codebase's own one-statement-
    per-line style (confirmed against the actual bug above). Names both identifiers so a
    genuine multi-source computation (rare, and should be reviewed either way, not silently
    passed) is visible in the failure message rather than silently allowed."""
    out: list[str] = []
    for rel, text in files.items():
        code = _strip_comments(text)
        for i, line in enumerate(code.split("\n"), 1):
            idents = {m.group(1) for m in _JS_SPOT_ACCESS_RE.finditer(line)}
            if len(idents) < 2:
                continue
            if re.search(r"\?|\|\||\?\?|:", line):
                out.append(
                    f"{rel}:{i}: dual-source spot fallback on one line -- reads .spot from "
                    f"{sorted(idents)}, combined with a fallback operator (RC-225)"
                )
    return out


#: static/js/*.js files that read a `.spot` field from a server response at all (found by
#: grepping the shipped tree, 2026-09-15) -- the actual set ed_js_dual_spot_fallback_violations
#: scans. A NEW file that reads .spot must be added here for this lock to see it; that is a
#: known, accepted limitation of this being a fixed list rather than a directory walk (a
#: directory walk would also pick up test fixtures/vendored JS if any land under static/js/
#: later -- an explicit list stays a deliberate, reviewable set).
_ED_JS_SPOT_FILES = (
    "static/js/ed-core.js",
    "static/js/ed-gamma.js",
    "static/js/ed-gamma-chart.js",
    "static/js/ed-gamma-levels.js",
    "static/js/ed-gamma-panels.js",
    "static/js/ed-gamma-chain.js",
    "static/js/ed-trade-desk.js",
    "static/js/ed-liquidity-map.js",
)


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
    ed_js_files: dict[str, str] = {}
    for rel in _ED_JS_SPOT_FILES:
        path = root / rel
        if path.is_file():
            ed_js_files[rel] = path.read_text(encoding="utf-8", errors="ignore")
    out.extend(ed_js_dual_spot_fallback_violations(ed_js_files))
    return out
