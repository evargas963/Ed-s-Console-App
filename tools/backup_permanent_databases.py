"""Refresh the two canonical permanent SQLite backups.

This is the sole routine/pre-destructive backup entry point. Source paths are not
arguments: database identity belongs to db_authority, not to a caller.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_safety import backup_all_permanent_databases  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", default="scheduled_refresh")
    args = parser.parse_args(argv)
    try:
        results = backup_all_permanent_databases(reason=args.reason)
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error_type": type(exc).__name__, "error": str(exc)},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "backups": [
                    {"database": str(db), "manifest": str(manifest), **receipt}
                    for db, manifest, receipt in results
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
