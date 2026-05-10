"""CLI — V3 Deliverable 2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catch_all import scan_catch_all_lines
from .html_scanner import scan_html_file
from .js_ts_scanner import scan_js_ts_text
from .markdown_scan import scan_markdown_file
from .paths import (
    ROOT,
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
) -> dict:
    idx = SchwabCsvIndex(default_dictionary_path())
    syn = load_synonyms()
    vendor_pf = load_vendor_prefixes()
    state = ReconciliationState()

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

    for abs_p in walk_workspace_files(root, on_prune=on_prune):
        if max_files is not None and n_attempts >= max_files:
            break
        rel = abs_p.relative_to(root).as_posix()
        suffix = abs_p.suffix

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

    write_register_csv(out_csv, all_rows)
    reverse = build_reverse_coverage_rows(all_rows, idx)
    recon = state.as_report()
    recon["criterion_1_reconciliation"]["partial_scan_max_files"] = max_files
    recon["criterion_1_reconciliation"]["partial_scan_breaks_reconciliation"] = max_files is not None
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
    args = ap.parse_args()
    summary = run_scan(
        args.root.resolve(),
        args.output,
        include_dot_claude=args.include_dot_claude,
        max_files=args.max_files,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
