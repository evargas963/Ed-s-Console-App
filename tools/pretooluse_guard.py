"""Where an edit target lies: `checkout_path` (inside the production checkout) is the one place a
guard places a path, and `production_path` keeps the files among those, every one of them (the
production checkout stays `main == origin/main`, AGENTS.md Authority); both read by
process_lock_guard (the production-checkout rails). A library, not a hook."""

from __future__ import annotations

import os
from pathlib import Path


def checkout_path(target: str, base: Path, primary: Path) -> Path | None:
    """`target` resolved (joined to `base` when relative) when it is inside the checkout
    `primary`; None when it is outside it. A path that cannot be resolved raises: the guard that
    asked cannot decide, and hook_chain refuses an event a guard raises on."""
    path = Path(target)
    resolved = (path if path.is_absolute() else base / path).resolve()
    return resolved if resolved.is_relative_to(primary.resolve()) else None


def production_path(target: str, base: Path, primary: Path) -> Path | None:
    """`checkout_path`, kept when it names a file: any file of the checkout, never the checkout
    itself or a device Windows reserves (`NUL`), which no write lands in."""
    resolved = checkout_path(target, base, primary)
    if resolved is None or resolved == primary.resolve():
        return None
    # NUL, CON: Windows devices, no file (os.path.isreserved exists only where Windows runs)
    device = os.name == "nt" and "\0" not in str(resolved) and os.path.isreserved(resolved)
    return None if device else resolved
