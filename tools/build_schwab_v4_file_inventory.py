"""Build governance/SCHWAB_V4_FILE_INVENTORY.csv + stats (V4 file-inventory pivot, operator O-40)."""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from pathlib import Path

from tools.schwab_universal_coverage_scanner_v3.paths import (
    ROOT,
    is_binary_sample,
    is_csv_source_of_truth,
    try_decode_utf8,
)
from tools.schwab_universal_coverage_scanner_v3.reconciliation import scan_family
from tools.schwab_universal_coverage_scanner_v3.vendor_paths import load_vendor_prefixes, path_is_vendored

# G1.1 dependency manifests (extend as needed; clause cites mechanical NOT_MARKET_DATA).
DEP_MANIFEST_NAMES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "requirements.txt",
        "requirements-dev.txt",
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
        "go.sum",
        "Cargo.lock",
        "composer.lock",
        "Gemfile.lock",
    }
)

def _rel_posix(root: Path, p: Path) -> str:
    return p.resolve().relative_to(root.resolve()).as_posix()


def _extension(rel: str) -> str:
    suf = Path(rel).suffix
    return suf if suf else ""


def _language_family(rel: str) -> str:
    return scan_family(_extension(rel), rel_posix=rel)


def classify_file(
    root: Path,
    abs_path: Path,
    *,
    vendor_prefixes: list[str],
) -> tuple[str, str]:
    """Return (status, clause). status is pending|excluded."""
    rel = _rel_posix(root, abs_path)
    parts = rel.split("/")

    if ".git" in parts:
        return "excluded", "V3-B git internals"

    if "__pycache__" in parts or ".pytest_cache" in parts or ".mypy_cache" in parts:
        return "excluded", "V3 reconciliation — build cache"

    if ".claude" in parts:
        return "excluded", "G1.1 .claude worktree dedup"

    if is_csv_source_of_truth(rel):
        return "excluded", "G1.1 canonical CSV source-of-truth"

    name = Path(rel).name
    if name in DEP_MANIFEST_NAMES:
        return "excluded", "G1.1 dependency manifest"

    if path_is_vendored(rel, vendor_prefixes):
        return "excluded", "G1.1 vendored"

    try:
        data = abs_path.read_bytes()
    except OSError:
        return "pending", ""

    sample = data if len(data) <= 1_048_576 else data[:1_048_576]
    if is_binary_sample(sample):
        return "excluded", "V3-B binary file"
    _text, err = try_decode_utf8(sample)
    if err:
        return "excluded", "V3-B binary file"

    return "pending", ""


def _load_prior_inventory(out_csv: Path) -> dict[str, dict[str, str]]:
    if not out_csv.is_file():
        return {}
    with out_csv.open(encoding="utf-8", newline="") as f:
        return {r["path"]: r for r in csv.DictReader(f) if r.get("path")}


def iter_all_files(root: Path) -> list[Path]:
    root = root.resolve()
    out: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        for fn in sorted(filenames):
            out.append(dp / fn)
    return out


def build_inventory(root: Path, out_csv: Path, out_stats: Path) -> dict:
    root = root.resolve()
    vendor_pf = load_vendor_prefixes()
    prior = _load_prior_inventory(out_csv)
    rows: list[dict[str, str]] = []
    sizes: list[int] = []
    ext_hist: Counter[str] = Counter()

    for abs_p in iter_all_files(root):
        if not abs_p.is_file():
            continue
        rel = _rel_posix(root, abs_p)
        ext = _extension(rel)
        try:
            sz = abs_p.stat().st_size
        except OSError:
            sz = 0
        sizes.append(sz)
        ext_hist[ext if ext else "(no extension)"] += 1

        status, clause = classify_file(root, abs_p, vendor_prefixes=vendor_pf)
        row = {
            "path": rel,
            "extension": ext,
            "language_family": _language_family(rel),
            "status": status,
            "clause": clause,
            "memo_ref": "",
            "reviewed_at": "",
        }
        old = prior.get(rel)
        if (
            old
            and (old.get("status") or "").strip() == "reviewed"
            and (old.get("memo_ref") or "").strip()
        ):
            row["status"] = "reviewed"
            row["memo_ref"] = (old.get("memo_ref") or "").strip()
            row["reviewed_at"] = (old.get("reviewed_at") or "").strip()
            row["clause"] = (old.get("clause") or "").strip()
        rows.append(row)

    rows.sort(key=lambda r: r["path"])
    status_hist: Counter[str] = Counter(r["status"] for r in rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "path",
                "extension",
                "language_family",
                "status",
                "clause",
                "memo_ref",
                "reviewed_at",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    # Size buckets
    buckets = {"0": 0, "1-1K": 0, "1K-100K": 0, "100K-1M": 0, "1M+": 0}
    for sz in sizes:
        if sz == 0:
            buckets["0"] += 1
        elif sz < 1024:
            buckets["1-1K"] += 1
        elif sz < 100_000:
            buckets["1K-100K"] += 1
        elif sz < 1_000_000:
            buckets["100K-1M"] += 1
        else:
            buckets["1M+"] += 1

    top_ext = ext_hist.most_common(40)
    lines = [
        "# Schwab V4 file inventory — statistics",
        "",
        f"**Root:** `{root}`",
        "**Generated by:** `tools/build_schwab_v4_file_inventory.py`",
        "",
        "## Totals",
        "",
        "Re-running this builder **preserves** prior **`reviewed`** rows (same `path`) that have a non-empty **`memo_ref`**; bulk **`excluded`** clauses are recomputed from the working tree.",
        "",
        "Paths under prefixes listed in **`governance/schwab_vendor_paths.yaml`** are **`excluded`** with clause **`G1.1 vendored`** (see `tools/schwab_universal_coverage_scanner_v3/vendor_paths.py`).",
        "",
        f"- **Files listed:** {len(rows)}",
        f"- **status=pending:** {status_hist.get('pending', 0)}",
        f"- **status=excluded:** {status_hist.get('excluded', 0)}",
        f"- **status=reviewed:** {status_hist.get('reviewed', 0)}",
        f"- **Total bytes (sum of file sizes):** {sum(sizes)}",
        "",
        "## Size distribution",
        "",
        "| Bucket | Count |",
        "|--------|------:|",
    ]
    for k, v in buckets.items():
        lines.append(f"| {k} | {v} |")
    lines.extend(["", "## Extension histogram (top 40)", "", "| extension | count |", "|-----------|------:|"])
    for ext, c in top_ext:
        lines.append(f"| `{ext}` | {c} |")
    lines.extend(
        [
            "",
            "## Walk order (recommended review batches)",
            "",
            "See `governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md` sequencing / operator directive 2026-05-10: trade-decision core → decision plane → features → static → tools → tests → governance → configs → catch-all.",
            "",
        ]
    )
    out_stats.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "files": len(rows),
        "pending": status_hist.get("pending", 0),
        "excluded": status_hist.get("excluded", 0),
        "reviewed": status_hist.get("reviewed", 0),
        "csv": str(out_csv.resolve()),
        "stats": str(out_stats.resolve()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "governance" / "SCHWAB_V4_FILE_INVENTORY.csv",
    )
    ap.add_argument(
        "--stats",
        type=Path,
        default=ROOT / "governance" / "SCHWAB_V4_FILE_INVENTORY_STATS.md",
    )
    args = ap.parse_args()
    s = build_inventory(args.root, args.csv, args.stats)
    print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
