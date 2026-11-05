"""Where an edit target lies, for both of process_lock_guard's production-checkout rails.

`live_file` places it in the production checkout (`checkout_path`), keeps every file there
(`production_path`: the checkout stays `main == origin/main`, AGENTS.md Authority) and leaves a
worktree of its own its own files. A library, not a hook.
"""

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
    """Return `checkout_path`, kept when it names a file: any file of the checkout.

    Never the checkout itself or a device Windows reserves (`NUL`), which no write lands in.
    """
    resolved = checkout_path(target, base, primary)
    if resolved is None or resolved == primary.resolve():
        return None
    # NUL, CON: Windows devices, no file (os.path.isreserved exists only where Windows runs)
    device = os.name == "nt" and "\0" not in str(resolved) and os.path.isreserved(resolved)
    return None if device else resolved


def live_file(target: str, base: Path, primary: Path, own: Path) -> Path | None:
    """Return `production_path`, but never a file under `own` when that is a worktree of its own.

    `own` is the checkout asking; a worktree nested at `<primary>/.claude/worktrees/<name>` owns
    its files. Both production-checkout rails, the Edit rail and the shell rail, place a target
    with this.
    """
    resolved = production_path(target, base, primary)
    ours = own.resolve() != primary.resolve() and resolved is not None
    return None if ours and resolved.is_relative_to(own.resolve()) else resolved
