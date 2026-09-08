"""
Controlled repair: fill bar-based outcomes for historical pin_neutral snapshots
left unfilled by the live 14-day rolling fill_outcomes window.

Does NOT change Issue 19 SQL or tier logic. Transaction-safe optional path via EdDB.

CLI:
  python pin_neutral_outcome_repair_v1.py --db data/ed_console.db
  python pin_neutral_outcome_repair_v1.py --dry-run --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from calibration.db_guard import (
    register_allow_noncanonical_flag,
    require_canonical_db_target,
)
from calibration.paths import DEFAULT_DB
from db_authority import is_canonical_db_path
from db_safety import backup_permanent_database

log = logging.getLogger(__name__)

FLAG_KEY = "pin_neutral_outcome_repair_v1"
FLAG_COMPLETE = "backfill_complete"


def run_repair(
    db_path: Path,
    *,
    dry_run: bool = False,
    allow_noncanonical: bool = False,
) -> dict:
    from db import EdDB

    db_path = db_path.resolve()
    audit: dict = {
        "schema": "pin_neutral_outcome_repair_v1",
        "db_path": str(db_path),
        "dry_run": dry_run,
    }
    if not dry_run and is_canonical_db_path(db_path):
        backup_path, manifest_path, _ = backup_permanent_database(
            db_path, reason="pre_pin_neutral_outcome_repair_v1"
        )
        audit["backup_path"] = str(backup_path)
        audit["backup_manifest_path"] = str(manifest_path)

    db = EdDB(db_path, allow_noncanonical=allow_noncanonical)
    res = db.fill_outcomes_pin_neutral_backfill_v1(dry_run=dry_run)
    audit.update(res)

    if not dry_run:
        db.set_schema_flag(FLAG_KEY, FLAG_COMPLETE)
        audit["flag_after"] = FLAG_COMPLETE

        out_path = db_path.parent / "pin_neutral_outcome_repair_v1_last_audit.json"
        out_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        audit["audit_json"] = str(out_path)

    return audit


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    if not args.db.is_file():
        raise SystemExit(f"DB not found: {args.db}")
    require_canonical_db_target(args, tool_name="pin_neutral_outcome_repair_v1", write_capable=True)
    r = run_repair(
        args.db,
        dry_run=args.dry_run,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
