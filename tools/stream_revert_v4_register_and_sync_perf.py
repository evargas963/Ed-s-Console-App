"""Stream-revert specific V4 register rows and resync perf_proof register_link JSON.

The register CSV may be tens of gigabytes: one streaming pass writes a temp file,
then atomically replaces the original. A second pass computes SHA-256 and size.

Updates ``governance/artifacts/perf_proof/replacements/*.json`` register_link
lists from the post-patch CSV (grouped by ``governed_ref`` suffix).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
PERF_DIR = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements"
META_PATH = ROOT / "governance" / "artifacts" / "schwab_v4_register_build_meta.json"

CONCRETE_PROOFS = (
    "pp_v4b_server_expiration_date_only.json",
    "pp_v4b_server_quote_coalesce_trim.json",
    "pp_v4b_market_state_oe_chain_snapshot.json",
)
COMPOSITE = "pp_v4b_schwab_gate_eleven_test_bundle.json"


def _proof_suffix(governed_ref: str) -> str | None:
    g = (governed_ref or "").strip().replace("\\", "/")
    for p in CONCRETE_PROOFS:
        if g.endswith(p):
            return p
    return None


def _stream_patch_and_collect(
    register_path: Path,
    tmp_path: Path,
    revert_ids: set[str],
) -> tuple[int, int, dict[str, list[str]]]:
    """Return (n_rows, n_reverted, replaced_ids_by_proof_json_name)."""
    replaced_by_proof: dict[str, list[str]] = defaultdict(list)
    n_rows = 0
    n_reverted = 0
    with register_path.open(newline="", encoding="utf-8") as fin, tmp_path.open(
        "w", newline="", encoding="utf-8"
    ) as fout:
        reader = csv.DictReader(fin)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise SystemExit("register CSV missing header")
        writer = csv.DictWriter(fout, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            n_rows += 1
            rid = (row.get("register_id") or "").strip()
            if rid in revert_ids:
                row["disposition"] = "UNREVIEWED"
                row["canonical_field_citation"] = ""
                row["governed_ref"] = ""
                n_reverted += 1
            disp = (row.get("disposition") or "").strip()
            if disp == "REPLACED":
                proof = _proof_suffix(row.get("governed_ref") or "")
                if proof:
                    replaced_by_proof[proof].append(rid)
            writer.writerow(row)
    for k in list(replaced_by_proof.keys()):
        replaced_by_proof[k] = sorted(set(replaced_by_proof[k]))
    return n_rows, n_reverted, dict(replaced_by_proof)


def _sha256_and_size(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest(), path.stat().st_size


def _write_perf_json(by_proof: dict[str, list[str]]) -> None:
    for proof in CONCRETE_PROOFS:
        path = PERF_DIR / proof
        doc = json.loads(path.read_text(encoding="utf-8"))
        rl = doc.setdefault("register_link", {})
        rl["status"] = "bound_retroactive"
        rl["replaced_register_ids"] = list(by_proof.get(proof, []))
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    union: set[str] = set()
    for proof in CONCRETE_PROOFS:
        union |= set(by_proof.get(proof, ()))

    gate = PERF_DIR / COMPOSITE
    doc = json.loads(gate.read_text(encoding="utf-8"))
    rl = doc.setdefault("register_link", {})
    rl["status"] = "composite_bundle_retroactive"
    rl["wrapped_proof_ids"] = sorted(CONCRETE_PROOFS)
    rl["replaced_register_ids"] = sorted(union)
    gate.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _update_register_meta(sha256_hex: str, size_b: int, n_rows: int) -> None:
    prior: dict = {}
    if META_PATH.is_file():
        prior = json.loads(META_PATH.read_text(encoding="utf-8"))
    prior["register_content_sha256"] = sha256_hex
    prior["register_size_bytes"] = size_b
    prior["register_rows_written"] = n_rows
    prior["generated_at_utc"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    META_PATH.write_text(json.dumps(prior, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument(
        "--revert-ids",
        default="60ca8db4744d7ac5da79,af3f1806c0f22f08f3f5",
        help="Comma-separated register_id values to revert to UNREVIEWED.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions only; do not write register or JSON.",
    )
    args = ap.parse_args()
    reg = args.register.resolve()
    revert_ids = {x.strip() for x in args.revert_ids.split(",") if x.strip()}
    if not reg.is_file():
        print(f"missing register: {reg}", flush=True)
        return 2

    tmp = reg.with_suffix(reg.suffix + ".stream_patch_tmp")
    if args.dry_run:
        print(f"would patch {reg} revert_ids={sorted(revert_ids)} tmp={tmp}", flush=True)
        return 0

    n_rows, n_rev, by_proof = _stream_patch_and_collect(reg, tmp, revert_ids)
    if n_rev != len(revert_ids):
        tmp.unlink(missing_ok=True)
        print(
            f"expected {len(revert_ids)} reverts, found {n_rev}; abort without replacing register",
            flush=True,
        )
        return 3

    os.replace(tmp, reg)
    sha256_hex, size_b = _sha256_and_size(reg)
    _write_perf_json(by_proof)
    _update_register_meta(sha256_hex, size_b, n_rows)

    print(
        json.dumps(
            {
                "n_rows": n_rows,
                "n_reverted": n_rev,
                "register_content_sha256": sha256_hex,
                "register_size_bytes": size_b,
                "replaced_by_proof": by_proof,
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
