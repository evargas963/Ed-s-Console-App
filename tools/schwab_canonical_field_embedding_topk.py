"""V4 four-channel exhaustion — embedding top-K over canonical_field (sentence-transformers).

Reads schwab_field_inventory/schwab_field_dictionary.csv and ranks canonical_field rows
by cosine similarity to each query string. Output is JSON for memo / register linkage.

Requires: pip install sentence-transformers (see requirements-dev.txt).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

from tools.schwab_universal_coverage_scanner_v3.paths import ROOT


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv",
    )
    ap.add_argument("--queries", nargs="+", required=True, help="Surface / token strings to embed")
    ap.add_argument("-k", type=int, default=10, help="Top-K canonical_field rows per query")
    ap.add_argument(
        "--model",
        default="all-MiniLM-L6-v2",
        help="sentence-transformers model id (default: all-MiniLM-L6-v2)",
    )
    ap.add_argument("--out", type=Path, help="Write JSON to this path")
    args = ap.parse_args()

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        sys.stderr.write(
            "schwab_canonical_field_embedding_topk: sentence_transformers not installed.\n"
            "Install dev deps: pip install -r requirements-dev.txt\n"
        )
        return 2

    rows: list[dict[str, str]] = []
    with args.csv.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            cf = (r.get("canonical_field") or "").strip()
            if cf:
                rows.append(
                    {
                        "canonical_field": cf,
                        "example_raw_field": (r.get("example_raw_field") or "").strip(),
                        "category": (r.get("category") or "").strip(),
                        "likely_use": (r.get("likely_use") or "").strip(),
                    }
                )

    texts = [r["canonical_field"] for r in rows]
    model = SentenceTransformer(args.model)
    emb_fields = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    # row-normalize for cosine via dot product
    emb_fields = emb_fields / np.clip(np.linalg.norm(emb_fields, axis=1, keepdims=True), 1e-12, None)

    out_queries: list[dict] = []
    for q in args.queries:
        qv = model.encode([q], convert_to_numpy=True, show_progress_bar=False)
        qv = qv / np.clip(np.linalg.norm(qv, axis=1, keepdims=True), 1e-12, None)
        sims = (emb_fields @ qv[0]).tolist()
        ranked = sorted(
            range(len(sims)),
            key=lambda i: sims[i],
            reverse=True,
        )[: args.k]
        out_queries.append(
            {
                "query": q,
                "model": args.model,
                "top_k": [
                    {
                        "rank": idx + 1,
                        "score": round(float(sims[i]), 6),
                        **rows[i],
                    }
                    for idx, i in enumerate(ranked)
                ],
            }
        )

    payload = {
        "csv": str(args.csv.resolve()),
        "n_canonical_rows": len(rows),
        "queries": out_queries,
    }
    js = json.dumps(payload, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(js + "\n", encoding="utf-8")
    else:
        print(js)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
