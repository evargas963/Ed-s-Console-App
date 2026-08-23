#!/usr/bin/env python3
"""SOURCE copy of the PM-authority write helper (RC-456).

THIS FILE IS NOT THE SECURITY BOUNDARY.

The installed privileged executable (root-owned, non-AI-writable), for example
``/usr/local/sbin/ed_pm_authority_write``, is the write seam. Tests and this
repo copy prove the contract. Host install copies this source to the privileged
path. Committing this file does not create the capability split.

Contract:
  - candidate JSON on stdin only
  - NO arbitrary output path from the caller
  - writes only the canonical external authority resource
  - parse JSON; require exactly pm == \"operator\"
  - reject missing pm, pm != operator, malformed JSON
  - preserve additional mission validation (scope / remaining)
  - atomic replace; refuse symlink/path-redirection
  - nonzero on every refusal
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.pm_authority as PA  # noqa: E402


def run(stdin_text: str) -> int:
    errs = PA.write_atomic_authority(stdin_text)
    if errs:
        sys.stderr.write("".join(f"{e}\n" for e in errs))
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # Refuse path injection: any flag or positional path is a failure.
    if args:
        sys.stderr.write(
            "PM_AUTHORITY: helper accepts JSON on stdin only; "
            "no output path or extra arguments permitted\n"
        )
        return 2
    try:
        text = sys.stdin.read()
    except OSError as exc:
        sys.stderr.write(f"PM_AUTHORITY: stdin unreadable: {exc}\n")
        return 2
    return run(text)


if __name__ == "__main__":
    raise SystemExit(main())
