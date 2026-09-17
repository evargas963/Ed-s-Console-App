"""Reconcile reports/whole_ui_live_inventory_v1.json to every UI market binding."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INV_PATH = ROOT / "reports" / "whole_ui_live_inventory_v1.json"
STATIC = ROOT / "static"
SKIP_PAGES = {"ops.html", "governance.html"}
STATUS_VOCAB = {"LIVE", "HISTORICAL_REFERENCE", "UNAVAILABLE", "FAIL", "NOT_PROVEN"}
FRAGMENT_APIS = {
    "/api/desk",
    "/api/diagnostics",
    "/api/order-flow",
    "/api/terrain",
    "/api/release/current",
    "/api/spot.spot",
}
REQUIRED_INDEX_MARKET_IDS = {
    "hPx",
    "hChg",
    "hBidAsk",
    "hFeed",
    "hAge",
    "hSession",
    "heatBody",
    "klSpot",
    "klFlip",
    "klCall",
    "klPut",
    "klAbs",
    "klPeak",
    "klNet",
    "klPcr",
    "klRegime",
    "sdBody",
    "gbsBody",
    "ofBody",
    "chainBody",
    "flowBody",
    "vnBody",
    "chmBody",
    "stBody",
    "tdBody",
    "obBody",
    "ofhBody",
    "liqmBody",
    "lvlBody",
    "chartBody",
    "levelsBody",
    "alertsList",
    "aiCtxFresh",
}


def _load() -> dict:
    return json.loads(INV_PATH.read_text(encoding="utf-8"))


def _static_api_paths() -> set[str]:
    found: set[str] = set()
    pages = list(STATIC.glob("*.html")) + list((STATIC / "js").glob("*.js"))
    for path in pages:
        if path.name in SKIP_PAGES:
            continue
        text = path.read_text(encoding="utf-8")
        for raw in re.findall(r"/api/[a-zA-Z0-9_./-]+", text):
            api = raw.rstrip(".")
            if api.endswith("/") and api.rstrip("/") in FRAGMENT_APIS:
                continue
            if api in FRAGMENT_APIS:
                continue
            found.add(api)
    return found


def test_inventory_status_vocab_and_counts() -> None:
    inv = _load()
    fields = inv["fields"]
    assert fields, "inventory has no fields"
    counts = Counter(f["status"] for f in fields)
    assert set(counts) <= STATUS_VOCAB
    assert counts.get("FAIL", 0) == 0
    summary = {
        "total": len(fields),
        "LIVE": counts.get("LIVE", 0),
        "HISTORICAL_REFERENCE": counts.get("HISTORICAL_REFERENCE", 0),
        "UNAVAILABLE": counts.get("UNAVAILABLE", 0),
        "FAIL": counts.get("FAIL", 0),
        "NOT_PROVEN": counts.get("NOT_PROVEN", 0),
    }
    inv["summary"] = summary
    # Keep the file honest: if summary is present it must match the computed counts.
    written = json.loads(INV_PATH.read_text(encoding="utf-8"))
    if "summary" in written:
        assert written["summary"] == summary
    assert summary["total"] == sum(summary[k] for k in STATUS_VOCAB)
    assert summary["NOT_PROVEN"] > 0  # required RTH / unmatched paths remain


def test_every_static_api_binding_is_inventoried() -> None:
    inv = _load()
    surfaces = set(inv["api_surfaces"])
    found = _static_api_paths()
    missing = sorted(found - surfaces)
    assert missing == [], f"unrepresented UI API bindings: {missing}"
    assert "/api/watchlist-quotes" in surfaces
    assert "/api/spot" in surfaces
    assert "/api/state" in surfaces


def test_every_index_market_id_is_inventoried() -> None:
    inv = _load()
    ids = {f["id"] for f in inv["fields"]}
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    present = set(re.findall(r'id="([^"]+)"', html))
    missing = sorted(REQUIRED_INDEX_MARKET_IDS - present)
    assert missing == [], f"required market ids missing from index.html: {missing}"
    unmapped = sorted(REQUIRED_INDEX_MARKET_IDS - ids)
    # heatBody is covered by heat_* fields; allow that alias.
    unmapped = [u for u in unmapped if u != "heatBody"]
    assert unmapped == [], f"index market ids missing from inventory: {unmapped}"
    assert "wl-px" in ids and "wl-chg" in ids


def test_cannot_be_live_adjudications_are_source_contracts() -> None:
    inv = _load()
    by_id = {f["id"]: f for f in inv["fields"]}
    radar = by_id["desk_workspace_radar_placeholder"]
    assert radar["status"] == "NOT_PROVEN"
    assert "timeout" in (radar.get("limit") or "").lower()
    oi = by_id["heat_cells_oi"]
    assert oi["status"] == "LIVE"
    assert "OPEN_INTEREST" in oi["source_contract"]
    morning = by_id["morning_gamma_reference"]
    assert morning["status"] == "HISTORICAL_REFERENCE"
    assert "never populate current" in morning["limit"]
    bar = by_id["desk_html_structure_bar_close"]
    assert bar["status"] == "HISTORICAL_REFERENCE"
    assert "never populate current" in bar["limit"]
    pending = by_id["contract_admission_pending"]
    assert pending["status"] == "NOT_PROVEN"
    aggressor = by_id["book_aggressor"]
    assert aggressor["status"] == "UNAVAILABLE"
    assert "no native aggressor" in aggressor["source_contract"]


def test_radar_plane_last_price_reprices_snapshot_spot() -> None:
    import time

    import live_market_plane as L
    import server

    tk = "RADLIVE"
    L._by_ticker.pop(tk, None)
    L._by_ticker[tk] = {
        "spot": 701.25,
        "last_price_native_ts": time.time(),
        "last_price_received_ts": time.time(),
        "last_price_generation": 9,
        "server_received_ts": time.time(),
        "quote_source_detail": {"spot": "LAST_PRICE"},
    }
    try:
        out = server._radar_apply_plane_spot({"ticker": tk, "spot": 680.0, "spot_source": "snapshot"})
        assert out["spot"] == 701.25
        assert out["spot_source"] == server.SPOT_SOURCE_PLANE
        assert out["spot_state"] == "live"
        assert out["last_price_generation"] == 9
        hist = server._radar_apply_plane_spot({"ticker": "RADNONE", "spot": 680.0, "spot_source": "snapshot"})
        assert hist["spot"] == 680.0
        assert hist["spot_source"] == "snapshot"
    finally:
        L._by_ticker.pop(tk, None)
