"""Reconcile reports/whole_ui_live_inventory_v1.json to every rendered binding instance."""

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
INSTANCE_KEYS = {
    "id", "page", "view", "target", "semantic", "canonical_producer",
    "source_observation", "timestamp", "generation", "freshness",
    "update_trigger", "status", "designed_capability", "runtime_status",
    "instance_kind",
}
RUNTIME_VOCAB = {"LIVE", "HISTORICAL_REFERENCE", "UNAVAILABLE", "FAIL", "NOT_PROVEN"}
FRAGMENT_APIS = {
    "/api/desk",
    "/api/diagnostics",
    "/api/order-flow",
    "/api/terrain",
    "/api/release/current",
    "/api/spot.spot",
}
REQUIRED_INDEX_MARKET_IDS = {
    "hPx", "hChg", "hBidAsk", "hFeed", "hAge", "hSession",
    "heatBody", "klSpot", "klFlip", "klCall", "klPut", "klAbs", "klPeak",
    "klNet", "klPcr", "klRegime", "sdBody", "gbsBody", "ofBody", "chainBody",
    "flowBody", "vnBody", "chmBody", "stBody", "tdBody", "obBody", "ofhBody",
    "liqmBody", "lvlBody", "chartBody", "levelsBody", "alertsList", "aiCtxFresh",
    "deskRadarBody",
}
def _inventory_last_price_ids(inv: dict) -> set[str]:
    return {r["id"] for r in inv["instances"] if r["semantic"] == "LAST_PRICE"}


def _core_last_price_ids() -> set[str]:
    core = (STATIC / "js" / "ed-core.js").read_text(encoding="utf-8")
    block = re.search(r"var LAST_PRICE_CONSUMERS = \[(.*?)\];", core, re.S)
    assert block, "LAST_PRICE_CONSUMERS missing from ed-core.js"
    ids = set(re.findall(r"id: '([^']+)'", block.group(1)))
    ids.add("sse.live_quote")
    return ids
REQUIRED_CLOSED_PATHS = {
    "index.html#deskRadarBody_spot",
    "index.html.contract_admission",
    "index.html#tdBody_spot",
    "index.html#ofhBody.latest",
    "index.html#liqmBody.zones",
    "index.html#alertsList",
    "chart.html#forces",
    "exposure.html#flow",
    "options.html#m-spot",
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


def test_instance_denominator_reconciles() -> None:
    inv = _load()
    instances = inv["instances"]
    assert instances, "inventory has no binding instances"
    for row in instances:
        missing = INSTANCE_KEYS - set(row)
        assert not missing, f"{row.get('id')}: missing {sorted(missing)}"
        assert row["status"] in STATUS_VOCAB
        assert row["designed_capability"] == row["status"]
        assert row["runtime_status"] in RUNTIME_VOCAB
        if row.get("runtime_failure"):
            assert row["runtime_status"] != "LIVE", (
                f"{row['id']}: runtime_failure cannot be counted runtime LIVE"
            )
        if row["runtime_status"] == "LIVE":
            assert row.get("runtime_evidence"), (
                f"{row['id']}: runtime LIVE requires runtime_evidence"
            )
    keys = [(r["page"], r["target"], r["semantic"]) for r in instances]
    dups = [k for k, n in Counter(keys).items() if n > 1]
    assert dups == [], f"duplicate binding instances (not unique semantics): {dups}"
    last_price = [r for r in instances if r["semantic"] == "LAST_PRICE"]
    assert len(last_price) >= 8, (
        "LAST_PRICE painted in multiple locations must be multiple instance rows, "
        f"got {len(last_price)}"
    )
    ids = {r["id"] for r in instances}
    missing_lp = sorted(_inventory_last_price_ids({"instances": instances}) - ids)
    assert missing_lp == [], f"required LAST_PRICE instances missing: {missing_lp}"
    counts = Counter(r["status"] for r in instances)
    summary = {
        "total": len(instances),
        "LIVE": counts.get("LIVE", 0),
        "HISTORICAL_REFERENCE": counts.get("HISTORICAL_REFERENCE", 0),
        "UNAVAILABLE": counts.get("UNAVAILABLE", 0),
        "FAIL": counts.get("FAIL", 0),
        "NOT_PROVEN": counts.get("NOT_PROVEN", 0),
        "binding_instances": len(instances),
        "generated_templates": sum(1 for r in instances if r["instance_kind"] == "generated"),
        "static_instances": sum(1 for r in instances if r["instance_kind"] == "static"),
    }
    written = _load()
    assert written["summary"] == summary
    assert summary["FAIL"] == 0
    # summary counts designed_capability, not runtime proof.
    assert summary["NOT_PROVEN"] == 0
    assert summary["total"] == summary["binding_instances"]
    assert summary["total"] == summary["static_instances"] + summary["generated_templates"]
    runtime = written["runtime_summary"]
    rt_counts = Counter(r["runtime_status"] for r in instances)
    assert runtime == {
        "LIVE": rt_counts.get("LIVE", 0),
        "HISTORICAL_REFERENCE": rt_counts.get("HISTORICAL_REFERENCE", 0),
        "UNAVAILABLE": rt_counts.get("UNAVAILABLE", 0),
        "FAIL": rt_counts.get("FAIL", 0),
        "NOT_PROVEN": rt_counts.get("NOT_PROVEN", 0),
    }
    assert runtime["FAIL"] == 0
    assert runtime["LIVE"] == 0 or all(
        r.get("runtime_evidence") for r in instances if r["runtime_status"] == "LIVE"
    )
    leftover_ids = {"chart.html#scorecard", "index.html#vol-observability"}
    assert leftover_ids <= {r["id"] for r in instances}


def test_required_paths_are_not_not_proven() -> None:
    inv = _load()
    by_id = {r["id"]: r for r in inv["instances"]}
    for iid in REQUIRED_CLOSED_PATHS:
        assert iid in by_id, f"required path missing from instance inventory: {iid}"
        assert by_id[iid]["status"] != "NOT_PROVEN", iid
        assert by_id[iid]["status"] != "FAIL", iid
    fields = {f["id"]: f for f in inv["fields"]}
    assert fields["desk_workspace_radar_placeholder"]["status"] == "LIVE"
    assert fields["contract_admission_pending"]["status"] == "LIVE"
    assert fields["tdBody"]["status"] == "LIVE"
    assert fields["ofhBody"]["status"] == "LIVE"
    assert fields["liqmBody"]["status"] == "LIVE"
    assert fields["alertsList"]["status"] == "LIVE"
    assert fields["chart_html_forces"]["status"] == "HISTORICAL_REFERENCE"
    assert fields["exposure_html_flow"]["status"] == "HISTORICAL_REFERENCE"
    assert fields["options_html_spot"]["status"] == "LIVE"
    assert "/api/spot" in fields["options_html_spot"]["source"]


def test_every_static_api_binding_is_inventoried() -> None:
    inv = _load()
    surfaces = set(inv["api_surfaces"])
    found = _static_api_paths()
    missing = sorted(found - surfaces)
    assert missing == [], f"unrepresented UI API bindings: {missing}"
    assert "/api/watchlist-quotes" in surfaces
    assert "/api/spot" in surfaces
    assert "/api/state" in surfaces
    assert "/api/terrain/radar" in surfaces


def test_every_index_market_id_is_inventoried() -> None:
    inv = _load()
    ids = {f["id"] for f in inv["fields"]}
    inst_text = " ".join(r["target"] + " " + r["id"] for r in inv["instances"])
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    present = set(re.findall(r'id="([^"]+)"', html))
    missing = sorted(REQUIRED_INDEX_MARKET_IDS - present)
    assert missing == [], f"required market ids missing from index.html: {missing}"
    unmapped = sorted(REQUIRED_INDEX_MARKET_IDS - ids)
    unmapped = [u for u in unmapped if u != "heatBody" and u != "deskRadarBody"]
    assert unmapped == [], f"index market ids missing from inventory: {unmapped}"
    assert "deskRadarBody" in inst_text
    assert "wl-px" in ids and "wl-chg" in ids


def test_spot_identity_harness_enumerates_every_last_price_target() -> None:
    inv = _load()
    expected = _inventory_last_price_ids(inv)
    assert expected
    assert _core_last_price_ids() == expected, (
        "LAST_PRICE harness must be derived from the inventory, not a second list: "
        f"inventory={sorted(expected)} harness={sorted(_core_last_price_ids())}"
    )
    core = (STATIC / "js" / "ed-core.js").read_text(encoding="utf-8")
    assert "function exactSpotIdentityEqual" in core
    assert "function stampSpotIdentity" in core
    assert "tickerStorageKey" not in core
    fn = re.search(
        r"function lastPriceObservationFromPayload\([\s\S]*?\n  \}",
        core,
    )
    assert fn, "lastPriceObservationFromPayload missing"
    body = fn.group(0)
    assert "p.spot_source" not in body
    assert "quote_ingestion" not in body
    assert "_quote_authority" not in body
    assert "current_spot_source ||" not in core


def test_gamma_stamp_has_no_manual_identity_fallback() -> None:
    src = (STATIC / "js" / "ed-gamma.js").read_text(encoding="utf-8")
    fn = re.search(r"function stampHeatScopeSpotIdentity\([\s\S]*?\n  \}", src)
    assert fn, "stampHeatScopeSpotIdentity missing"
    body = fn.group(0)
    assert "setAttribute" not in body
    assert "EdSpotIdentity" in body
    assert "if (!stamp) return" in body


def test_gamma_identity_rejects_producer_disagreement() -> None:
    import pytest

    import server

    with pytest.raises(ValueError, match="disagrees"):
        server._stamp_gamma_ticker_identity({"ticker": "QQQ"}, "SPY", "SPY")
    with pytest.raises(ValueError, match="requested ticker is missing"):
        server._stamp_gamma_ticker_identity({"ticker": "SPY"}, "", "SPY")
    with pytest.raises(ValueError, match="requested ticker is missing"):
        server._stamp_gamma_ticker_identity({"ticker": "SPY"}, None, "SPY")
    out = server._stamp_gamma_ticker_identity(
        {"ticker": "SPY", "available": True}, "SPY", "SPY"
    )
    assert out["ticker"] == "SPY"
    assert out["canonical_ticker"] == "SPY"
    assert out["requested_ticker"] == "SPY"


def test_cannot_be_live_adjudications_are_source_contracts() -> None:
    inv = _load()
    by_id = {f["id"]: f for f in inv["fields"]}
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
    assert pending["status"] == "LIVE"
    aggressor = by_id["book_aggressor"]
    assert aggressor["status"] == "UNAVAILABLE"
    assert "no native aggressor" in aggressor["source_contract"]
    forces = by_id["chart_html_forces"]
    assert forces["status"] == "HISTORICAL_REFERENCE"
    assert "current_spot" in forces["source_contract"]


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
        assert out["snapshot_spot"] == 680.0
        assert out["snapshot_spot_source"] == "snapshot"
        assert out["spot"] == 701.25
        assert out["current_spot"] == 701.25
        assert out["spot_source"] == server.SPOT_SOURCE_PLANE
        assert out["current_spot_source"] == server.SPOT_SOURCE_PLANE
        assert out["spot_state"] == "live"
        assert out["last_price_generation"] == 9
        hist = server._radar_apply_plane_spot({"ticker": "RADNONE", "spot": 680.0, "spot_source": "snapshot"})
        assert hist["snapshot_spot"] == 680.0
        assert hist["snapshot_spot_source"] == "snapshot"
        assert hist["spot"] is None
        assert hist["current_spot"] is None
        assert hist["current_spot_source"] is None
        assert hist["spot_state"] == "unavailable"
    finally:
        L._by_ticker.pop(tk, None)
