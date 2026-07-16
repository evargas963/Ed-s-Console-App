"""Register row schema + CSV writer — V3 (column names unchanged from V2)."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# D17 stable semantic key prototype — scope model (tool/test; not persisted in register CSV).
SITE_SCOPE = "SITE_SCOPE"
LINE_SCOPE = "LINE_SCOPE"
FILE_SCOPE = "FILE_SCOPE"
DOC_SCOPE = "DOC_SCOPE"
GENERATED_ARTIFACT_SCOPE = "GENERATED_ARTIFACT_SCOPE"
UNKNOWN_SCOPE = "UNKNOWN_SCOPE"

DISPOSITION_SCOPES = frozenset(
    {
        SITE_SCOPE,
        LINE_SCOPE,
        FILE_SCOPE,
        DOC_SCOPE,
        GENERATED_ARTIFACT_SCOPE,
        UNKNOWN_SCOPE,
    }
)

LINE_SCOPE_ALLOWED_DISPOSITIONS = frozenset({"NOT_MARKET_DATA"})

FORMAL_PATTERN_KIND_PREFIX = "FORMAL_"


REGISTER_COLUMNS = [
    "register_id",
    "language",
    "path",
    "line",
    "col",
    "pattern_kind",
    "surface_form",
    "tokens",
    "csv_candidates",
    "csv_lexical_topk_note",
    "v2_trace",
    "disposition",
    "canonical_field_citation",
    "governed_ref",
    "notes",
]


@dataclass
class RegisterRow:
    register_id: str
    language: str
    path: str
    line: int
    col: int
    pattern_kind: str
    surface_form: str
    tokens: str
    csv_candidates: str
    csv_lexical_topk_note: str
    v2_trace: str
    disposition: str = "UNREVIEWED"
    canonical_field_citation: str = ""
    governed_ref: str = ""
    notes: str = ""

    @staticmethod
    def make_id(path: str, line: int, col: int, pattern_kind: str, language: str) -> str:
        h = hashlib.sha256(
            f"{language}|{path}|{line}|{col}|{pattern_kind}".encode()
        ).hexdigest()[:20]
        return h

    def as_csv_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: d[k] for k in REGISTER_COLUMNS}


def canonicalize_register_rows(rows: list[RegisterRow]) -> list[dict[str, Any]]:
    """Return the serialized rows in a stable total order.

    File-traversal order (os.walk directory order) is filesystem/checkout
    dependent, so an unsorted register emits the same logical row set in
    different byte order across CI checkouts, producing a different SHA-256 for
    identical content. Sorting the SERIALIZED register-schema fields immediately
    before writing makes the byte content — and its pin — independent of
    traversal order. Row discovery, inclusion, schema, and values are unchanged;
    only the emission order is canonicalized.
    """
    serialized = [r.as_csv_dict() for r in rows]
    serialized.sort(
        key=lambda d: tuple("" if d[c] is None else str(d[c]) for c in REGISTER_COLUMNS)
    )
    return serialized


def write_register_csv(path: Path, rows: list[RegisterRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        for d in canonicalize_register_rows(rows):
            w.writerow(d)


def normalize_register_path(path: str) -> str:
    return (path or "").strip().replace("\\", "/")


def normalize_tokens(tokens: str) -> str:
    raw = (tokens or "").strip().lower()
    if not raw:
        return ""
    parts = re.split(r"\s+", raw)
    return " ".join(sorted(parts))


def surface_fingerprint(surface_form: str) -> str:
    text = (surface_form or "").strip().lower()[:400]
    if not text:
        return ""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _hash_key(parts: tuple[str, ...]) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def read_source_line_text(repo_root: Path, path: str, line: int) -> str | None:
    rel = normalize_register_path(path)
    candidate = repo_root / rel
    if not candidate.is_file():
        return None
    try:
        lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if line < 1 or line > len(lines):
        return None
    return lines[line - 1]


def compute_line_text_hash(line_text: str | None) -> str:
    if line_text is None:
        return "MISSING"
    normalized = line_text.strip()
    if not normalized:
        return "EMPTY"
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def line_classification_for_row(row: dict[str, Any]) -> str:
    pk = (row.get("pattern_kind") or "").strip()
    if pk.startswith(FORMAL_PATTERN_KIND_PREFIX):
        return pk
    disp = (row.get("disposition") or "").strip()
    if disp == "NOT_MARKET_DATA":
        return "LINE_NMD"
    return pk or "UNKNOWN"


def file_classification_from_slice_basename(slice_basename: str) -> str:
    name = (slice_basename or "").lower()
    if "scanner_baseline" in name or "baseline" in name:
        return "scanner_baseline"
    if name.startswith("phase2_tests"):
        return "phase2_tests"
    if name.startswith("phase2_mega"):
        return "phase2_mega_inventories"
    if name.startswith("phase2_docs"):
        return "phase2_docs_md"
    if name.startswith("phase2_governance"):
        return "phase2_governance_md"
    if name.startswith("phase_oxx"):
        return "phase_oxx_perf_proof"
    return "module_slice"


def classify_disposition_scope(
    row: dict[str, Any],
    *,
    slice_basename: str = "",
) -> str:
    """Classify row disposition scope for stable semantic key prototype."""
    pk = (row.get("pattern_kind") or "").strip()
    path = normalize_register_path(str(row.get("path") or ""))
    slice_name = (slice_basename or "").lower()

    if "scanner_baseline" in slice_name:
        return GENERATED_ARTIFACT_SCOPE
    if slice_name.startswith("phase2_docs") or slice_name.startswith("phase2_governance"):
        return DOC_SCOPE
    if slice_name.startswith("phase2_tests") or slice_name.startswith("phase2_mega"):
        return FILE_SCOPE
    if path.endswith(".md"):
        return DOC_SCOPE
    if pk.startswith(FORMAL_PATTERN_KIND_PREFIX):
        return LINE_SCOPE
    if pk and not pk.startswith(FORMAL_PATTERN_KIND_PREFIX):
        tokens = (row.get("tokens") or "").strip()
        surface = (row.get("surface_form") or "").strip()
        if tokens or surface:
            return SITE_SCOPE
    notes = (row.get("notes") or "").strip()
    trace = (row.get("v2_trace") or "").strip()
    if notes or trace:
        return SITE_SCOPE
    return UNKNOWN_SCOPE


def compute_stable_semantic_key(
    row: dict[str, Any],
    scope: str,
    *,
    line_text_hash: str = "",
    file_classification: str = "",
) -> str:
    """Hybrid Design B stable semantic key (prototype-only; does not replace register_id)."""
    path = normalize_register_path(str(row.get("path") or ""))
    line = int(row.get("line") or 0)
    col = int(row.get("col") or 0)
    language = (row.get("language") or "python").strip().lower() or "python"
    tokens = normalize_tokens(str(row.get("tokens") or ""))
    surf_fp = surface_fingerprint(str(row.get("surface_form") or ""))

    if scope == SITE_SCOPE:
        return _hash_key(("SITE", path, str(line), str(col), language, tokens, surf_fp))
    if scope == LINE_SCOPE:
        lc = line_classification_for_row(row)
        return _hash_key(("LINE", path, str(line), line_text_hash or "MISSING", lc, LINE_SCOPE))
    if scope == FILE_SCOPE:
        fc = file_classification or file_classification_from_slice_basename("")
        return _hash_key(("FILE", path, fc))
    if scope == DOC_SCOPE:
        lth = line_text_hash or "MISSING"
        return _hash_key(("DOC", path, str(line), lth))
    if scope == GENERATED_ARTIFACT_SCOPE:
        fc = file_classification or file_classification_from_slice_basename("")
        return _hash_key(("GEN", path, fc, str(line), str(col)))
    return ""


def line_scope_disposition_admissible(disposition: str) -> bool:
    disp = (disposition or "").strip()
    if disp.startswith("GOVERNED_EXCEPTION"):
        return False
    return disp in LINE_SCOPE_ALLOWED_DISPOSITIONS


def site_scope_disposition_admissible(disposition: str) -> bool:
    disp = (disposition or "").strip()
    if not disp or disp == "UNREVIEWED":
        return False
    return True
