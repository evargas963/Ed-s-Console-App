# institutional-synthetic-ok: these tests INJECT dual-age spot fallbacks / missing as_of
# surfaces to prove the RC-225 / census #8 spot-binding lock BLOCKS — that is their purpose.
"""RC-225: each screen binds spot from one declared payload field with as_of age visible.

test_console_kills_last_price_quote_mid_fallback was retired here (/console cutover, operator
directive 2026-09-14): it locked legacy static/index.html's own consoleSpot(d) function, which
has no equivalent in the new console (static/js/ed-core.js reads a spot field inline per call
site, not through one shared function) -- see tools/spot_binding_lock.py's
console_binding_violations docstring for the full disposition."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.spot_binding_lock as L  # noqa: E402
from tools.data_faucet_audit import audit_client  # noqa: E402

CHART = ROOT / "static" / "chart.html"
EXPOSURE = ROOT / "static" / "exposure.html"


def test_shipped_static_spot_binding_is_clean():
    bad = L.scan_tracked_static(ROOT)
    assert bad == [], f"spot dual-age / missing as_of remains: {bad}"


def test_shipped_client_faucet_audit_clean():
    assert audit_client() == [], "client spot read outside authority"


def test_chart_binds_api_spot_only():
    import re

    src = CHART.read_text(encoding="utf-8")
    assert "function currentSpot()" in src
    assert "return liveSpot;" in src
    assert "function _cycleSpot" not in src
    # Executable code must not read strikes.spot / terrain.spot (comments may name the kill).
    code = re.sub(r"/\*.*?\*/", "", re.sub(r"//.*$", "", src, flags=re.M), flags=re.S)
    assert "strikes.spot" not in code, "executable strikes.spot read remains"
    assert "terrain.spot" not in code, "executable terrain.spot read remains"
    m = re.search(r"function currentSpot\(\)\s*\{([^}]*)\}", src)
    assert m and "return liveSpot" in m.group(1)
    assert "_cycleSpot" not in m.group(1)


def test_chart_exposes_as_of_age():
    src = CHART.read_text(encoding="utf-8")
    assert "spot_as_of_ts_utc" in src
    assert "spotBindingAgeLabel" in src
    assert "getElementById('spotage')" in src or 'id="spotage"' in src
    assert "SPOT_STALE_SEC" in src
    assert "STALE" in src


def test_exposure_kills_cycle_fallback():
    src = EXPOSURE.read_text(encoding="utf-8")
    assert "function currentSpot()" in src
    assert "strikes.spot" not in src
    assert "terrain.spot" not in src
    assert "spotBindingAgeLabel" in src
    assert "spot_as_of_ts_utc" in src


def test_cycle_fallback_injection_screams():
    """Negative control: the exact census dual-age shape must BLOCK."""
    bad = L.chart_binding_violations(
        "function currentSpot() {\n"
        "  if (liveSpot != null) return liveSpot;\n"
        "  return _cycleSpot();\n"
        "}\n"
        "function _cycleSpot() {\n"
        "  return (strikes && strikes.spot != null) ? strikes.spot\n"
        "    : (terrain ? terrain.spot : null);\n"
        "}\n"
    )
    assert any("_cycleSpot" in m or "fallback" in m or "strikes.spot" in m for m in bad), bad


def test_missing_as_of_surface_screams():
    bad = L.chart_binding_violations(
        "function currentSpot() { return liveSpot; }\n"
        "async function pollSpot() { const j = await r.json(); liveSpot = j.spot; }\n"
    )
    assert any("spotage" in m or "spotBindingAgeLabel" in m or "as_of" in m for m in bad), bad


def test_console_dual_field_injection_screams():
    bad = L.console_binding_violations(
        "function consoleSpot(d) {\n"
        "  const s = parseFloat(d.spot ?? d.last_price ?? d.quote_mid);\n"
        "  return s;\n"
        "}\n"
        "const x = document.getElementById('data-price-freshness');\n"
    )
    assert any("last_price" in m or "quote_mid" in m or "dual" in m for m in bad), bad


def test_ed_js_dual_spot_fallback_injection_screams():
    """Closes the gap console_binding_violations's own docstring named as future work: the
    rebuilt console's ed-*.js files have no shared currentSpot()-shaped function, so the old
    chart/exposure scanners cannot apply structurally, but the same defect they exist to ban
    (a spot value chosen from whichever of two independently-fetched payloads happens to be
    present) can still occur -- and did, in static/js/ed-gamma-chart.js (independent git
    review, 2026-09-15). This exact line, taken from that bug before it was fixed, must
    scream."""
    bad = L.ed_js_dual_spot_fallback_violations({
        "static/js/ed-gamma-chart.js":
            "var spot = Number((terrain && terrain.spot) != null ? terrain.spot "
            ": (strikesData && strikesData.spot));",
    })
    assert any("terrain" in m and "strikesData" in m for m in bad), bad


def test_ed_js_single_spot_source_is_clean():
    """Negative control: a single source's .spot read on its own (however it is guarded or
    combined with other, non-.spot fallbacks) must never trip the dual-source lock -- it exists
    to ban TWO DIFFERENT identifiers' .spot fields feeding one fallback, not any use of the
    word at all."""
    bad = L.ed_js_dual_spot_fallback_violations({
        "static/js/ed-gamma-chart.js":
            "var spot = Number(terrain && terrain.spot);\n"
            "var x = terrain.spot != null ? terrain.spot : null;\n",
    })
    assert bad == [], bad


def test_ed_js_dual_spot_fallback_survives_multiline():
    """Independent review, 2026-09-16: 'detection that survives multiline expressions.' The
    exact original bug, reformatted across several source lines (a Number(...) call wrapping a
    multi-line ternary) -- the old per-line scanner could not see across this; the statement-
    level scanner must."""
    bad = L.ed_js_dual_spot_fallback_violations({
        "f.js":
            "var spot = Number(\n"
            "  (terrain && terrain.spot) != null\n"
            "    ? terrain.spot\n"
            "    : (strikesData && strikesData.spot)\n"
            ");\n",
    })
    assert any("terrain" in m and "strikesData" in m for m in bad), bad


def test_ed_js_dual_spot_fallback_survives_aliasing():
    """Independent review, 2026-09-16: 'detection that survives ... aliases.' Extracting .spot
    into plain-named intermediate variables BEFORE the fallback leaves no literal '.spot' text
    at the fallback site itself -- the lock must still trace each variable back to its source."""
    bad = L.ed_js_dual_spot_fallback_violations({
        "f.js":
            "var t = terrain.spot;\n"
            "var s = strikesData.spot;\n"
            "var spot = t != null ? t : s;\n",
    })
    assert any("terrain" in m and "strikesData" in m for m in bad), bad


def test_ed_js_dual_spot_fallback_survives_helper_mediated_fallback():
    """Independent review, 2026-09-16: 'detection that survives ... helper-mediated fallback.'
    No ?, :, ||, or ?? appears at the call site at all -- the fallback logic lives inside
    pickFirst() -- but handing two different sources' spot to the SAME call is the same defect
    under a different spelling."""
    bad = L.ed_js_dual_spot_fallback_violations({
        "f.js": "var spot = pickFirst(terrain.spot, strikesData.spot);\n",
    })
    assert any("terrain" in m and "strikesData" in m and "helper" in m for m in bad), bad
    # And composed with aliasing -- both escapes stacked must still be caught together.
    bad2 = L.ed_js_dual_spot_fallback_violations({
        "f.js": "var t = terrain.spot;\nvar s = strikesData.spot;\nvar spot = pickFirst(t, s);\n",
    })
    assert any("terrain" in m and "strikesData" in m for m in bad2), bad2


def test_spot_number_null_fabrication_screams():
    """Independent review, 2026-09-16: 'Number(terrain && terrain.spot) fabricates zero when
    terrain is null because Number(null) === 0.' Live in static/js/ed-gamma-chart.js,
    ed-gamma-panels.js, and ed-gamma.js before this fix -- a fabricated, finite 0 passes every
    isFinite(spot) guard as if it were a real price."""
    bad = L.spot_number_null_fabrication_violations({
        "f.js": "var spot = Number(terrain && terrain.spot);\n",
    })
    assert bad, bad
    bad2 = L.spot_number_null_fabrication_violations({
        "f.js": "var spot = Number(surface.spot);\n",
    })
    assert bad2, bad2


def test_spot_number_null_fabrication_recognizes_the_actual_fix_as_clean():
    """Negative control: the exact guarded shape this session's fixes now use
    (`expr == null ? NaN : Number(expr)`) must NOT be re-flagged -- it is the fix, not the bug."""
    bad = L.spot_number_null_fabrication_violations({
        "f.js": "var spot = terrain && terrain.spot == null ? NaN : Number(terrain && terrain.spot);\n",
    })
    assert bad == [], bad
    bad2 = L.spot_number_null_fabrication_violations({
        "f.js": "var spot = surface.spot == null ? NaN : Number(surface.spot);\n",
    })
    assert bad2 == [], bad2


def test_discover_frontend_execution_surfaces_is_dynamic_not_a_fixed_roster():
    """Independent review, 2026-09-16: 'replace the fixed eight-file roster ... with discovery
    of every shipped frontend JS/HTML execution surface.' Proves discovery actually walks the
    tree: a file that did not exist at write time is still found."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "static" / "js").mkdir(parents=True)
        (root / "static" / "js" / "ed-brand-new-panel.js").write_text("var x = 1;\n")
        (root / "static" / "chart.html").write_text("<html></html>")
        found = L.discover_frontend_execution_surfaces(root)
    assert "static/js/ed-brand-new-panel.js" in found, found
    assert "static/chart.html" in found, found


def test_shipped_ed_js_spot_binding_is_clean():
    """The actual shipped file set, not a synthetic fixture -- proves the fixed
    ed-gamma-chart.js, ed-gamma-panels.js, ed-gamma.js (and every other discovered ed-*.js) is
    clean today, on BOTH checks (dual-source fallback and Number-null-fabrication)."""
    files = {}
    for rel in L.discover_frontend_execution_surfaces(ROOT):
        if rel.endswith(".js"):
            path = ROOT / rel
            if path.is_file():
                files[rel] = path.read_text(encoding="utf-8", errors="ignore")
    assert L.ed_js_dual_spot_fallback_violations(files) == []
    assert L.spot_number_null_fabrication_violations(files) == []


def test_exposure_fallback_injection_screams():
    bad = L.exposure_binding_violations(
        "function currentSpot() { return liveSpot; }\n"
        "const spot = liveSpot != null ? liveSpot\n"
        "  : (strikes && strikes.spot != null ? Number(strikes.spot)\n"
        "    : (terrain && terrain.spot != null ? Number(terrain.spot) : null));\n"
        "function spotBindingAgeLabel() { return ''; }\n"
        "spotBindingAgeLabel();\n"
        "spot_as_of_ts_utc\n"
    )
    assert any("strikes.spot" in m or "fallback" in m for m in bad), bad
