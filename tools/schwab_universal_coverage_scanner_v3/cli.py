"""CLI — V3 Deliverable 2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .catch_all import scan_catch_all_lines
from .html_scanner import scan_html_file
from .js_ts_scanner import scan_js_ts_text
from .markdown_scan import scan_markdown_file
from .paths import (
    ROOT,
    SCAN_SCOPE_EXCLUDE_PREFIXES,
    is_binary_sample,
    try_decode_utf8,
    walk_workspace_files,
)
from .python_scanner import scan_python_complete
from .reconciliation import ReconciliationState, inventory_mark_present, scan_family
from .register import RegisterRow, write_register_csv
from .reverse_coverage import build_reverse_coverage_rows
from .schwab_csv import SchwabCsvIndex, default_dictionary_path
from .sql_scan import scan_sql_file
from .structured_scan import scan_ini_file, scan_json_file, scan_toml_file, scan_yaml_file
from .synonyms import load_synonyms
from .vendor_paths import load_vendor_prefixes, path_is_vendored

SCANNER_VERSION = "3.0.0"
REGISTER_BUILD_META_REL = "governance/artifacts/schwab_v4_register_build_meta.json"
CANONICAL_REGISTER_REL = "governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
# Never ingest another register artifact as scan input (explodes row count / self-scan).
SKIP_SCAN_REL_PATHS = frozenset(
    {
        "governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.mock_build.csv",
    }
)


def _is_canonical_register(root: Path, out_csv: Path) -> bool:
    try:
        return out_csv.resolve() == (root / CANONICAL_REGISTER_REL).resolve()
    except OSError:
        return False


def _merge_key_from_csv_row(row: dict[str, str]) -> tuple[str, int, int, str, str] | None:
    try:
        ln = int(row.get("line") or 0)
        col = int(row.get("col") or 0)
    except ValueError:
        return None
    path = (row.get("path") or "").strip()
    pk = (row.get("pattern_kind") or "").strip()
    lang = (row.get("language") or "").strip()
    return (path, ln, col, pk, lang)


def _merge_surface_key_from_csv_row(row: dict[str, str]) -> tuple[str, str, str, str] | None:
    path = (row.get("path") or "").strip()
    if not path:
        return None
    surf = (row.get("surface_form") or "").strip()
    pk = (row.get("pattern_kind") or "").strip()
    lang = (row.get("language") or "").strip()
    return (path, surf, pk, lang)


def _merge_surface_key_from_register_row(row: RegisterRow) -> tuple[str, str, str, str]:
    return (row.path, (row.surface_form or "").strip(), row.pattern_kind, row.language)


def _load_disposition_merge_maps(
    register_csv: Path,
) -> tuple[
    dict[tuple[str, int, int, str, str], dict[str, str]],
    dict[str, dict[str, str]],
    dict[tuple[str, str, str, str], dict[str, str]],
]:
    """Prior dispositions keyed by scan site, register_id, and surface+pattern (line-stable rescan).

    Surface-key merge is dropped when the prior register already has that
    (path, surface_form, pattern_kind, language) on more than one line — otherwise
    a second physical site with identical surface text inherits REPLACED without
    an operator line binding.
    """
    by_site: dict[tuple[str, int, int, str, str], dict[str, str]] = {}
    by_id: dict[str, dict[str, str]] = {}
    by_surface: dict[tuple[str, str, str, str], dict[str, str]] = {}
    surface_lines: dict[tuple[str, str, str, str], set[int]] = defaultdict(set)
    cross_surface_lines: dict[tuple[str, str], set[int]] = defaultdict(set)
    if not register_csv.is_file():
        return by_site, by_id, by_surface
    if os.environ.get("SCHWAB_SKIP_DISPOSITION_MERGE", "").strip().lower() in ("1", "true", "yes"):
        return by_site, by_id, by_surface
    try:
        with register_csv.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = (row.get("disposition") or "").strip()
                if not d or d == "UNREVIEWED":
                    continue
                payload = {
                    "disposition": d,
                    "canonical_field_citation": (row.get("canonical_field_citation") or "").strip(),
                    "governed_ref": (row.get("governed_ref") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                    "surface_form": (row.get("surface_form") or "").strip(),
                }
                sk = _merge_key_from_csv_row(row)
                if sk is not None:
                    by_site[sk] = payload
                rid = (row.get("register_id") or "").strip()
                if rid:
                    by_id[rid] = payload
                ssk = _merge_surface_key_from_csv_row(row)
                if ssk is not None:
                    try:
                        ln = int(row.get("line") or 0)
                    except ValueError:
                        ln = 0
                    surface_lines[ssk].add(ln)
                    by_surface[ssk] = payload
                    cross_surface_lines[(ssk[0], ssk[1])].add(ln)
    except (OSError, UnicodeError, csv.Error):
        return {}, {}, {}
    for ssk, lines in surface_lines.items():
        if len(lines) > 1:
            by_surface.pop(ssk, None)
    for cross_key, lines in cross_surface_lines.items():
        if len(lines) > 1:
            path, surf = cross_key
            for key in list(by_surface):
                if key[0] == path and key[1] == surf:
                    by_surface.pop(key, None)
    return by_site, by_id, by_surface


def _merge_payload_applies_to_row(row: RegisterRow, payload: dict[str, str]) -> bool:
    """Do not inherit disposition when prior surface text differs (stable line, changed code)."""
    prior_surface = (payload.get("surface_form") or "").strip()
    if not prior_surface:
        return True
    return (row.surface_form or "").strip() == prior_surface


def _apply_disposition_merge(
    all_rows: list[RegisterRow],
    by_site: dict[tuple[str, int, int, str, str], dict[str, str]],
    by_id: dict[str, dict[str, str]],
    by_surface: dict[tuple[str, str, str, str], dict[str, str]],
) -> None:
    if not by_site and not by_id and not by_surface:
        return
    for row in all_rows:
        key = (row.path, int(row.line), int(row.col), row.pattern_kind, row.language)
        candidates: list[dict[str, str]] = []
        site_m = by_site.get(key)
        if site_m is not None:
            candidates.append(site_m)
        id_m = by_id.get(row.register_id)
        if id_m is not None:
            candidates.append(id_m)
        surf_m = by_surface.get(_merge_surface_key_from_register_row(row))
        if surf_m is not None:
            candidates.append(surf_m)
        m = next((c for c in candidates if _merge_payload_applies_to_row(row, c)), None)
        if not m:
            continue
        row.disposition = m["disposition"]
        row.canonical_field_citation = m["canonical_field_citation"]
        row.governed_ref = m["governed_ref"]
        row.notes = m["notes"]


def _git_head_sha(root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    s = (proc.stdout or "").strip()
    return s or None


def write_register_build_meta(
    root: Path,
    out_csv: Path,
    summary: dict,
    *,
    max_files: int | None,
    embedding_mode_cli: str | None,
    include_dot_claude: bool,
    respect_gitignore: bool,
    scope_exclude_prefixes: tuple[str, ...],
) -> Path:
    """Emit pinned scan metadata (hashes, flags, HEAD) for audit / CI reproduction.

    Canonical-register guard: only updates the global meta when ``out_csv`` resolves
    to the canonical register path. Non-canonical writes (e.g. ``--output /tmp/x.csv``
    for a dry run) are skipped to prevent SHA-pin corruption.
    """
    root = root.resolve()
    meta_path = root / REGISTER_BUILD_META_REL
    if not _is_canonical_register(root, out_csv):
        print(
            f"register_build_meta: skipped (non-canonical output {out_csv}); "
            f"pin preserved at {meta_path}",
            file=sys.stderr,
        )
        return meta_path
    body = b""
    if out_csv.is_file():
        body = out_csv.read_bytes()
    sha256_hex = hashlib.sha256(body).hexdigest() if body else ""
    size_b = len(body)
    emb = embedding_mode_cli or os.environ.get("SCHWAB_SCANNER_EMBEDDINGS") or "mock"
    scan_sha = _git_head_sha(root)
    prior: dict = {}
    if meta_path.is_file():
        try:
            prior = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prior = {}

    rel_csv: str
    if out_csv.is_file():
        try:
            rel_csv = out_csv.resolve().relative_to(root).as_posix()
        except ValueError:
            rel_csv = str(out_csv)
    else:
        rel_csv = str(out_csv)

    doc = {
        **prior,
        "scanner_version": SCANNER_VERSION,
        "partial_scan": max_files is not None,
        "max_files": max_files,
        "embedding_mode": emb,
        "files_attempted": int(summary.get("files_attempted") or 0),
        "register_rows_written": int(summary.get("register_rows") or 0),
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scanner_commit_sha": scan_sha,
        "scanner_flags": {
            "max_files": max_files,
            "embedding_mode": emb,
            "include_dot_claude": include_dot_claude,
            "respect_gitignore": respect_gitignore,
            "scope_exclude_prefixes": list(scope_exclude_prefixes),
        },
        "register_content_sha256": sha256_hex,
        "register_size_bytes": size_b,
        "register_csv_path": rel_csv,
    }
    if prior.get("operator_note"):
        doc["operator_note"] = prior["operator_note"]
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return meta_path


def _language_tag(suffix: str) -> str:
    if not suffix:
        return "text"
    return suffix.lstrip(".").lower() or "text"


def _dispatch_specialized(
    rel: str,
    suffix: str,
    abs_p: Path,
    text: str,
    idx: SchwabCsvIndex,
    syn: dict,
) -> tuple[list[RegisterRow], bool]:
    """Catch-all always runs; specialized parsers add rows. All must succeed for ok."""
    lang = _language_tag(suffix)
    rows: list[RegisterRow] = []
    rows.extend(scan_catch_all_lines(rel, text, idx, syn, language=lang))
    ok = True

    if suffix.lower() == ".py":
        extra, o = scan_python_complete(rel, text, idx, syn)
        rows.extend(extra)
        ok = ok and o
    elif suffix.lower() == ".json":
        extra, o = scan_json_file(rel, abs_p, idx, syn)
        rows.extend(extra)
        ok = ok and o
    elif suffix.lower() in {".yaml", ".yml"}:
        extra, o = scan_yaml_file(rel, abs_p, idx, syn)
        rows.extend(extra)
        ok = ok and o
    elif suffix.lower() == ".toml":
        extra, o = scan_toml_file(rel, abs_p, idx, syn)
        rows.extend(extra)
        ok = ok and o
    elif suffix.lower() == ".ini":
        extra, o = scan_ini_file(rel, abs_p, idx, syn)
        rows.extend(extra)
        ok = ok and o
    elif suffix.lower() == ".md":
        extra, o = scan_markdown_file(rel, text, idx, syn)
        rows.extend(extra)
        ok = ok and o
    elif suffix.lower() in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        jslang = "typescript" if suffix.lower() in {".ts", ".tsx"} else "javascript"
        extra, o = scan_js_ts_text(rel, text, idx, syn, jslang)
        rows.extend(extra)
        ok = ok and o
    elif suffix.lower() == ".html":
        extra, o = scan_html_file(rel, text, idx, syn)
        rows.extend(extra)
        ok = ok and o
    elif suffix.lower() == ".sql":
        rows.extend(scan_sql_file(rel, text, idx, syn))

    return rows, ok


def run_scan(
    root: Path,
    out_csv: Path,
    *,
    include_dot_claude: bool = False,
    max_files: int | None = None,
    embedding_mode: str | None = None,
    respect_gitignore: bool = True,
    scope_exclude_prefixes: tuple[str, ...] = SCAN_SCOPE_EXCLUDE_PREFIXES,
    extra_exclude_prefixes: tuple[str, ...] = (),
) -> dict:
    if embedding_mode:
        import os

        os.environ["SCHWAB_SCANNER_EMBEDDINGS"] = embedding_mode
    idx = SchwabCsvIndex(default_dictionary_path())
    syn = load_synonyms()
    vendor_pf = load_vendor_prefixes()
    state = ReconciliationState()
    combined_scope = tuple(scope_exclude_prefixes) + tuple(extra_exclude_prefixes)

    def on_prune(batch) -> None:
        state.record_pruned_batch(
            relative_dir=batch.relative_dir,
            dir_kind=batch.dir_kind,
            file_count=batch.file_count,
            clause=batch.clause,
            reason=batch.reason,
        )

    all_rows: list[RegisterRow] = []
    n_attempts = 0
    root = root.resolve()
    merge_by_site, merge_by_id, merge_by_surface = _load_disposition_merge_maps(out_csv)
    out_csv = out_csv.resolve()
    try:
        skip_output_rel = out_csv.relative_to(root).as_posix().replace("\\", "/")
    except ValueError:
        skip_output_rel = None

    for abs_p in walk_workspace_files(
        root,
        on_prune=on_prune,
        respect_gitignore=respect_gitignore,
        scope_exclude_prefixes=combined_scope,
    ):
        if max_files is not None and n_attempts >= max_files:
            break
        rel = abs_p.relative_to(root).as_posix().replace("\\", "/")
        suffix = abs_p.suffix

        if rel in SKIP_SCAN_REL_PATHS:
            continue
        if skip_output_rel is not None and rel == skip_output_rel:
            continue

        route = inventory_mark_present(state, rel, suffix, include_dot_claude=include_dot_claude)
        if route == "skip_dictionary":
            continue
        if route == "skip_claude":
            continue

        fam_name = scan_family(suffix, rel_posix=rel)
        fam = state.family(fam_name)
        n_attempts += 1

        try:
            data = abs_p.read_bytes()
        except OSError:
            fam.add_exclusion("os_read_error", "V3 — OSError reading file; not scanned")
            continue

        sample = data if len(data) <= 1_048_576 else data[:1_048_576]
        if is_binary_sample(sample):
            fam.add_exclusion("non_text_content", "V3-B binary file")
            continue

        text, dec_err = try_decode_utf8(data)
        if dec_err:
            fam.add_exclusion("utf8_decode_failed", "V3-B binary file")
            continue

        vend_note = "vendor_path_listed" if path_is_vendored(rel, vendor_pf) else ""

        def _tag(file_rows: list[RegisterRow]) -> None:
            if not vend_note:
                return
            for r in file_rows:
                r.notes = f"{r.notes};{vend_note}".strip(";") if r.notes else vend_note

        file_rows, ok = _dispatch_specialized(rel, suffix, abs_p, text, idx, syn)
        if not ok:
            fam.add_exclusion("parse_or_scan_failure", "V3 — structured parse or parser failure")
            continue

        _tag(file_rows)
        all_rows.extend(file_rows)
        fam.b_scanned += 1

    _apply_disposition_merge(all_rows, merge_by_site, merge_by_id, merge_by_surface)
    write_register_csv(out_csv, all_rows)
    reverse = build_reverse_coverage_rows(all_rows, idx)
    recon = state.as_report()
    recon["criterion_1_reconciliation"]["partial_scan_max_files"] = max_files
    recon["criterion_1_reconciliation"]["partial_scan_breaks_reconciliation"] = max_files is not None
    recon["criterion_1_reconciliation"]["scan_scope"] = {
        "respect_gitignore": respect_gitignore,
        "scope_exclude_prefixes": list(combined_scope),
    }
    return {
        "scanner_version": SCANNER_VERSION,
        "files_attempted": n_attempts,
        "register_rows": len(all_rows),
        "output": str(out_csv.resolve()),
        "contract": "SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md",
        "reconciliation": recon,
        "reverse_coverage_preview": reverse[:50],
        "reverse_coverage_total": len(reverse),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Schwab Universal Coverage Scanner V3 — see TRACEABILITY_V3.md")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument(
        "--output",
        type=Path,
        default=ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv",
    )
    ap.add_argument("--include-dot-claude", action="store_true")
    ap.add_argument("--max-files", type=int, default=None)
    ap.add_argument(
        "--embedding-mode",
        choices=("minilm", "mock"),
        default=None,
        help="Override SCHWAB_SCANNER_EMBEDDINGS: mock is fast (deterministic hash embeddings); minilm loads sentence-transformers.",
    )
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PREFIX",
        help="Additional POSIX path prefix to exclude from the walk (repeatable).",
    )
    ap.add_argument(
        "--no-respect-gitignore",
        action="store_true",
        help="Walk gitignored paths (tests / dry-run only; not for canonical register regen).",
    )
    ap.add_argument(
        "--no-scope-excludes",
        action="store_true",
        help="Disable default SCAN_SCOPE_EXCLUDE_PREFIXES (legacy full-tree walk).",
    )
    args = ap.parse_args()
    scope_excludes = () if args.no_scope_excludes else SCAN_SCOPE_EXCLUDE_PREFIXES
    extra_excludes = tuple(p.strip().replace("\\", "/").strip("/") for p in args.exclude if p.strip())
    summary = run_scan(
        args.root.resolve(),
        args.output,
        include_dot_claude=args.include_dot_claude,
        max_files=args.max_files,
        embedding_mode=args.embedding_mode,
        respect_gitignore=not args.no_respect_gitignore,
        scope_exclude_prefixes=scope_excludes,
        extra_exclude_prefixes=extra_excludes,
    )
    write_register_build_meta(
        args.root.resolve(),
        args.output,
        summary,
        max_files=args.max_files,
        embedding_mode_cli=args.embedding_mode,
        include_dot_claude=args.include_dot_claude,
        respect_gitignore=not args.no_respect_gitignore,
        scope_exclude_prefixes=scope_excludes + extra_excludes,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
