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
    "static/index.html",
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
    return out
