# institutional-synthetic-ok: these tests INJECT dual-age spot fallbacks / missing as_of
# surfaces to prove the RC-225 / census #8 spot-binding lock BLOCKS — that is their purpose.
"""RC-225: each screen binds spot from one declared payload field with as_of age visible."""
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
INDEX = ROOT / "static" / "index.html"


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


def test_console_kills_last_price_quote_mid_fallback():
    src = INDEX.read_text(encoding="utf-8")
    assert "d.spot ?? d.last_price ?? d.quote_mid" not in src
    import re
    m = re.search(r"function consoleSpot\(d\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "consoleSpot missing"
    body = re.sub(r"//.*$", "", m.group(1), flags=re.M)
    assert "last_price" not in body and "quote_mid" not in body
    assert "parseFloat(d.spot)" in body
    assert "data-price-freshness" in src


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
