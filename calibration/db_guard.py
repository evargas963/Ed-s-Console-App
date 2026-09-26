"""Shared CLI guards for calibration modules: default canonical DB, explicit non-canonical opt-in."""

from __future__ import annotations

import argparse
from pathlib import Path

from db_authority import cli_require_canonical_or_ack


def register_allow_noncanonical_flag(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--allow-noncanonical-db",
        action="store_true",
        help=(
            "Opt-in to target a non-canonical database (harness/proof/backup/alternate). "
            "Without this flag, only the canonical production file is allowed."
        ),
    )


def require_canonical_db_target(
    args: argparse.Namespace,
    *,
    tool_name: str,
    write_capable: bool,
) -> None:
    cli_require_canonical_or_ack(
        Path(args.db).resolve(),
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
        tool_name=tool_name,
        write_capable=write_capable,
    )


