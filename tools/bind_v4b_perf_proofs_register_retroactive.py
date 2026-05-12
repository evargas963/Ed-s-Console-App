"""Retroactive bind / repair: v4b perf_proof bundles ↔ register REPLACED rows.

Citation rule: pick a Schwab path from the row's csv_candidates ∪ csv_lexical_topk_note
that matches the bundle's semantic fields. Never use csv_candidates[0] or any
unsorted first-segment default. If no segment matches, the row is not bound to
that bundle (stay or revert to UNREVIEWED).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
PERF_DIR = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements"
REL_PERF = "governance/artifacts/perf_proof/replacements"

# Concrete bundles only (composite gate bundle is synced from register union).
PROOF_FILES = (
    "pp_v4b_server_expiration_date_only.json",
    "pp_v4b_server_quote_coalesce_trim.json",
    "pp_v4b_market_state_oe_chain_snapshot.json",
)

_PREF_TOTAL_VOL = (
    "quotes.quote.totalVolume",
    "chains.underlying.totalVolume",
    "chains.callExpDateMap.*.totalVolume",
    "chains.putExpDateMap.*.totalVolume",
)


def _segments(row: dict[str, str]) -> list[str]:
    c = (row.get("csv_candidates") or "") + ";" + (row.get("csv_lexical_topk_note") or "")
    return [x.strip() for x in c.split(";") if x.strip()]


def _pick_expiration_citation(row: dict[str, str]) -> str | None:
    for s in _segments(row):
        if "expirationDate" not in s:
            continue
        if s.startswith("chains.") or s.startswith("quotes."):
            return s[:220]
    return None


def _pick_quote_total_volume(row: dict[str, str]) -> str | None:
    segs = _segments(row)
    for p in _PREF_TOTAL_VOL:
        if p in segs:
            return p
    for s in segs:
        if "totalVolume" not in s:
            continue
        if any(k in s for k in ("quotes.quote", "chains.underlying", "callExpDateMap", "putExpDateMap")):
            return s[:220]
    return None


def _pick_oe_chain_citation(row: dict[str, str]) -> str | None:
    for s in _segments(row):
        if "expirationDate" in s and s.startswith("chains."):
            return s[:220]
        if "totalVolume" in s and (s.startswith("chains.") or "quotes.quote" in s):
            return s[:220]
    return None


_PICKERS: dict[str, object] = {
    "pp_v4b_server_expiration_date_only.json": _pick_expiration_citation,
    "pp_v4b_server_quote_coalesce_trim.json": _pick_quote_total_volume,
    "pp_v4b_market_state_oe_chain_snapshot.json": _pick_oe_chain_citation,
}


def _proof_for_governed_ref(gr: str) -> str | None:
    g = (gr or "").strip().replace("\\", "/")
    for fname in PROOF_FILES:
        if g.endswith(fname):
            return fname
    return None


def semantic_repair_register() -> tuple[int, int, list[str]]:
    """Return (n_replaced_ok, n_reverted_unreviewed, replaced_ids_sorted)."""
    with REGISTER.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise SystemExit("register missing header")
        rows = list(reader)

    n_ok = 0
    n_rev = 0
    for row in rows:
        proof = _proof_for_governed_ref(row.get("governed_ref") or "")
        if proof is None:
            continue
        if (row.get("disposition") or "").strip() != "REPLACED":
            continue
        picker = _PICKERS[proof]
        cit = picker(row)  # type: ignore[misc]
        if cit is None:
            row["disposition"] = "UNREVIEWED"
            row["canonical_field_citation"] = ""
            row["governed_ref"] = ""
            n_rev += 1
        else:
            row["canonical_field_citation"] = cit
            row["governed_ref"] = f"{REL_PERF}/{proof}"
            n_ok += 1

    replaced_ids: list[str] = []
    for row in rows:
        if (row.get("disposition") or "").strip() == "REPLACED" and _proof_for_governed_ref(row.get("governed_ref") or ""):
            replaced_ids.append(row["register_id"])

    out = REGISTER.with_suffix(".csv.tmp")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    out.replace(REGISTER)
    return n_ok, n_rev, sorted(set(replaced_ids))


def sync_perf_json_from_register(rows: list[dict[str, str]]) -> None:
    by_proof: dict[str, set[str]] = {p: set() for p in PROOF_FILES}
    for row in rows:
        if (row.get("disposition") or "").strip() != "REPLACED":
            continue
        proof = _proof_for_governed_ref(row.get("governed_ref") or "")
        if proof is None:
            continue
        by_proof[proof].add(row["register_id"])

    union: set[str] = set()
    for proof in PROOF_FILES:
        path = PERF_DIR / proof
        doc = json.loads(path.read_text(encoding="utf-8"))
        rl = doc.setdefault("register_link", {})
        rl["status"] = "bound_retroactive"
        ids = sorted(by_proof[proof])
        rl["replaced_register_ids"] = ids
        union |= set(ids)
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    gate = PERF_DIR / "pp_v4b_schwab_gate_eleven_test_bundle.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    rl = doc.setdefault("register_link", {})
    rl["status"] = "composite_bundle_retroactive"
    rl["wrapped_proof_ids"] = sorted(PROOF_FILES)
    rl["replaced_register_ids"] = sorted(union)
    gate.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def initial_bind_from_id_sets() -> None:
    """Original retroactive bind: only used once; kept for reproducibility."""
    id_sets: dict[str, frozenset[str]] = {
        "pp_v4b_server_expiration_date_only.json": frozenset(
            {
                "65115c2ceeeb8b6a4509",
                "f74ee40dc602a4e36d9c",
                "08f4d7635ae6d1af4de4",
                "a097ac90251efab43d75",
                "72b1cc8a7226a2fb2276",
                "0efde8c5bee579af7abe",
            }
        ),
        "pp_v4b_server_quote_coalesce_trim.json": frozenset(
            {
                "04fde1296aaf18668dee",
                "a60939e6fed009b418ca",
                "9a98b7873658db7f55c6",
                "d5d1f1fcca9b8ded2234",
                "5fad7a01642e699b7d58",
                "702d2ff0c8c45ce350d9",
                "0167eb5bbcdea3f7a051",
                "2abb5b4ccddcc4ada8ad",
            }
        ),
        "pp_v4b_market_state_oe_chain_snapshot.json": frozenset(
            {
                "e2f059cdc06cf0e31399",
                "6e85d0734ba0138f8569",
                "b254d7b971e4f3cd4c38",
                "5d65c623e91615193034",
                "d305ad2b4ba34c912a55",
            }
        ),
    }
    proof_to_ids = id_sets
    all_ids: set[str] = set()
    for s in proof_to_ids.values():
        all_ids |= set(s)

    with REGISTER.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise SystemExit("register missing header")
        rows = list(reader)

    for row in rows:
        rid = (row.get("register_id") or "").strip()
        if rid not in all_ids:
            continue
        proof_name = next((p for p, ids in proof_to_ids.items() if rid in ids), None)
        if proof_name is None:
            continue
        picker = _PICKERS[proof_name]
        cit = picker(row)  # type: ignore[misc]
        if cit is None:
            continue
        row["disposition"] = "REPLACED"
        row["canonical_field_citation"] = cit
        row["governed_ref"] = f"{REL_PERF}/{proof_name}"

    out = REGISTER.with_suffix(".csv.tmp")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    out.replace(REGISTER)
    sync_perf_json_from_register(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--initial-bind",
        action="store_true",
        help="Apply hard-coded id sets with semantic citations only (destructive; for fresh repro)",
    )
    args = ap.parse_args()
    if args.initial_bind:
        initial_bind_from_id_sets()
        with REGISTER.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        sync_perf_json_from_register(rows)
        print("initial semantic bind done")
        return

    n_ok, n_rev, ids = semantic_repair_register()
    with REGISTER.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    sync_perf_json_from_register(rows)
    print(f"semantic repair: {n_ok} REPLACED with aligned citation, {n_rev} reverted to UNREVIEWED")
    print("replaced register_ids:", ",".join(ids))


if __name__ == "__main__":
    main()
