#!/usr/bin/env python3
"""
SQLite contention impact audit (read-only).

Proves or rejects operator-trust impact from DB lock waits — not a justification exercise.

Usage:
  python tools/check_db_sqlite_contention_impact_audit.py \\
      --output reports/db_contention/db_sqlite_contention_impact_2026-06-18.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from verification.db_sqlite_contention_impact_audit import (
    build_contention_impact_report,
    format_contention_markdown,
)

DEFAULT_JSON = _REPO / "reports/db_contention/db_sqlite_contention_impact_2026-06-18.json"


def _scrape_log_files() -> tuple[str, list[str]]:
    texts: list[str] = []
    paths: list[str] = []
    candidates = [
        _REPO / "logs",
        _REPO / "enforce_all_out.txt",
    ]
    for base in candidates:
        if base.is_file():
            try:
                texts.append(base.read_text(encoding="utf-8", errors="replace"))
                paths.append(str(base))
            except OSError:
                pass
        elif base.is_dir():
            for p in sorted(base.glob("*.log"))[:30]:
                try:
                    texts.append(p.read_text(encoding="utf-8", errors="replace"))
                    paths.append(str(p))
                except OSError:
                    pass
            for p in sorted(base.glob("*.err"))[:15]:
                try:
                    texts.append(p.read_text(encoding="utf-8", errors="replace"))
                    paths.append(str(p))
                except OSError:
                    pass
    return "\n".join(texts), paths


def _load_switch_diag_events() -> list[dict[str, Any]]:
    try:
        from ticker_switch_diagnostics import get_recent_events

        return get_recent_events(limit=100)
    except Exception:
        return []


def _runtime_metrics() -> dict[str, Any] | None:
    try:
        from db import sqlite_contention_metrics_snapshot

        snap = sqlite_contention_metrics_snapshot()
        return snap if isinstance(snap, dict) else None
    except Exception:
        return None


def _resolve_db_path() -> Path | None:
    try:
        from db import DB_PATH

        return Path(DB_PATH)
    except Exception:
        return _REPO / "data" / "ed_console.db"


def run_db_contention_audit(
    *,
    audit_date: datetime.date,
    output_json: Path,
) -> dict[str, Any]:
    log_text, log_paths = _scrape_log_files()
    report = build_contention_impact_report(
        audit_date=audit_date.isoformat(),
        log_text=log_text,
        log_paths=log_paths,
        db_path=_resolve_db_path(),
        runtime_metrics=_runtime_metrics(),
        switch_events=_load_switch_diag_events(),
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = output_json.with_suffix(".md")
    md_path.write_text(format_contention_markdown(report), encoding="utf-8")
    report["_markdown_path"] = str(md_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite contention impact audit")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_JSON,
        help="JSON report path (markdown written alongside)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default="2026-06-18",
        help="Audit date label (YYYY-MM-DD)",
    )
    args = parser.parse_args()
    audit_date = datetime.date.fromisoformat(args.date)
    report = run_db_contention_audit(audit_date=audit_date, output_json=args.output)
    cls = report.get("classifications") or []
    print(f"Wrote {args.output}")
    print(f"Wrote {args.output.with_suffix('.md')}")
    print(f"classifications: {', '.join(cls)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
