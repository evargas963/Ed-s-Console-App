"""RC-380 — the Schwab field dictionary is a union over time, never a destructive snapshot.

WHAT WAS MEASURED (2026-08-15, live Schwab, all six market-data endpoints):

  1. The committed dictionary (built 2026-05-05) missed 8 fields Schwab returns today,
     including `breakEven` on every option contract.
  2. `schwab_field_dictionary_builder.main()` writes the CSV with `open(dict_file, "w")`
     from the newest capture alone, so refreshing during a closed session — when
     `movers` returns `{"screeners": []}` and `market_hours` omits `sessionHours` —
     DELETES the rows those endpoints contributed.
  3. Because refresh was unsafe, the dictionary aged out of sync with the vendor, which
     in turn would have made any derivation guard built on it pass the very violation it
     exists to catch (the CSV does not contain `breakEven`, so a guard reading the CSV
     cannot object to `breakEven` being derived).

The controls below drive the real merge. The first one is the property everything else
rests on: an observation may add or refresh, never remove.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.sync_schwab_field_dictionary import (  # noqa: E402
    COLUMNS,
    fields_from_capture,
    load_dictionary,
    merge,
    write_dictionary,
    write_sync_state,
)

# RC-368: declared direct owner.
TURN_AUDIT_OWNS = ["tools/sync_schwab_field_dictionary.py"]

TODAY = "2026-08-15"


def _existing(*fields: str) -> dict[str, dict[str, str]]:
    return {
        f: {
            "canonical_field": f, "source_endpoints": f.split(".")[0],
            "example_raw_field": f.split(".")[-1], "category": "greeks",
            "likely_use": "model", "priority": "high",
            "first_seen": "2026-05-05", "last_seen": "2026-05-05",
        }
        for f in fields
    }


def test_an_empty_endpoint_cannot_delete_a_catalogued_field():
    """THE PROPERTY. movers returned {"screeners": []} live; a snapshot rebuild drops
    all 11 movers rows. The union must keep every one of them."""
    existing = _existing("movers.symbol", "movers.lastPrice", "chains.delta")
    merged, added, _refreshed = merge(existing, {"movers": set(), "chains": {"chains.delta"}}, today=TODAY)
    assert set(merged) >= set(existing), (
        "a capture with an empty endpoint deleted catalogued fields — unobserved is not absent")
    assert added == []
    assert merged["movers.symbol"]["last_seen"] == "2026-05-05", (
        "an unobserved field must keep its history untouched, not be stamped as seen today")


def test_an_endpoint_that_failed_entirely_cannot_delete_anything():
    """A transport failure omits the endpoint from the capture. Same guarantee."""
    existing = _existing("market_hours.equity.sessionHours.regularMarket.*.start", "quotes.mark")
    merged, added, _ = merge(existing, {"quotes": {"quotes.mark"}}, today=TODAY)
    assert "market_hours.equity.sessionHours.regularMarket.*.start" in merged
    assert added == []


def test_new_vendor_fields_are_added_with_history():
    """The 8 fields measured live on 2026-08-15 must land, dated, and unreviewed."""
    existing = _existing("chains.delta")
    new = {"chains.callExpDateMap.*.breakEven", "chains.callExpDateMap.*.ssid",
           "chains.hasBinaryOptions", "chains.ethOptionEligible"}
    merged, added, _ = merge(existing, {"chains": new | {"chains.delta"}}, today=TODAY)
    assert set(added) == new, added
    row = merged["chains.callExpDateMap.*.breakEven"]
    assert row["first_seen"] == TODAY and row["last_seen"] == TODAY
    assert row["category"] == "unclassified" and row["priority"] == "unreviewed", (
        "a newly discovered vendor field must arrive UNREVIEWED — inventing a category "
        "would launder a guess as a classification")


def test_reobserving_a_field_refreshes_last_seen_but_not_first_seen():
    existing = _existing("chains.delta")
    merged, added, refreshed = merge(existing, {"chains": {"chains.delta"}}, today=TODAY)
    assert added == [] and "chains.delta" in refreshed
    assert merged["chains.delta"]["first_seen"] == "2026-05-05"
    assert merged["chains.delta"]["last_seen"] == TODAY


def test_a_field_seen_on_a_second_endpoint_unions_the_endpoints():
    existing = _existing("chains.delta")
    merged, _, _ = merge(existing, {"streaming": {"chains.delta"}}, today=TODAY)
    assert merged["chains.delta"]["source_endpoints"] == "chains;streaming"


def test_merge_never_shrinks_for_any_capture(tmp_path):
    """Property check across empty, partial, and disjoint captures."""
    existing = _existing("a.one", "b.two", "c.three")
    for capture in ({}, {"a": set()}, {"a": {"a.one"}}, {"z": {"z.new"}}):
        merged, _, _ = merge(existing, capture, today=TODAY)
        assert len(merged) >= len(existing), (capture, len(merged), len(existing))
        assert set(existing) <= set(merged), capture


def test_written_csv_keeps_the_original_columns_first(tmp_path):
    """Additive schema: existing DictReader consumers must not care that we grew columns."""
    out = tmp_path / "dict.csv"
    write_dictionary(_existing("chains.delta", "quotes.mark"), path=out)
    with out.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == COLUMNS
        assert reader.fieldnames[:6] == [
            "canonical_field", "source_endpoints", "example_raw_field",
            "category", "likely_use", "priority"], reader.fieldnames
        rows = list(reader)
    assert {r["canonical_field"] for r in rows} == {"chains.delta", "quotes.mark"}
    assert out.read_bytes().count(b"\r\n") == 0, "CRLF crept into a governed data file (RC-372)"


def test_round_trip_through_the_real_loader_is_lossless(tmp_path):
    out = tmp_path / "dict.csv"
    start = _existing("chains.delta", "movers.symbol")
    write_dictionary(start, path=out)
    assert set(load_dictionary(out)) == set(start)


def test_sync_state_records_a_partial_capture_as_partial(tmp_path):
    """Silence must be legible: zero observed is recorded, not omitted."""
    state_path = tmp_path / "sync_state.json"
    state = write_sync_state({"quotes": {"quotes.mark"}, "movers": set()}, ["quotes.mark"], path=state_path)
    assert state["endpoints_observed"]["movers"] == 0
    assert state["endpoints_observed"]["quotes"] == 1
    assert "chains" in state["endpoints_not_observed"], state
    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk["fields_added"] == ["quotes.mark"]
    assert "not deletions" in on_disk["note"].lower()


def test_the_committed_dictionary_still_loads_and_is_nonempty():
    """Negative control against breaking the live artifact the ML universe reads."""
    live = load_dictionary()
    assert len(live) >= 2000, f"committed dictionary looks truncated: {len(live)} rows"
    assert "chains.callExpDateMap.*.delta" in live


def test_an_empty_collection_yields_only_its_container_not_its_children():
    """The mechanism behind the whole row, stated exactly.

    Measured: `movers` returning `{"screeners": []}` flattens to the single container
    field `movers.screeners`. The 10 CHILD fields the dictionary catalogs (symbol,
    lastPrice, ...) are unobservable because there are no objects to walk. A snapshot
    rebuild therefore writes 1 movers row where the catalogue held 11 — the loss this
    module exists to prevent.
    """
    got = fields_from_capture({"movers": {"screeners": []}})["movers"]
    assert got == {"movers.screeners"}, got
    assert not any(f.startswith("movers.screeners.") for f in got), (
        "an empty array cannot yield child fields")

    existing = _existing("movers.screeners", "movers.screeners.*.symbol",
                         "movers.screeners.*.lastPrice")
    merged, added, _ = merge(existing, {"movers": got}, today=TODAY)
    assert len(merged) == 3 and added == [], (
        "the observable container must not evict the unobservable children")
