"""Where an edit target lies: `checkout_path` (inside the production checkout) is the one place a
guard places a path, and `production_path` keeps the app code among those; both read by
process_lock_guard (the production-checkout rails). A library, not a hook."""
from __future__ import annotations

from pathlib import Path

#: Production surfaces across the whole continuum, not just backend.
PRODUCTION_SUFFIXES = (".py", ".html", ".js", ".css", ".sql", ".ts", ".jsx", ".tsx")
#: Not part of the product surface.
NOT_PRODUCT_PREFIXES = (
    "tests/", "governance/", "docs/", "reports/", ".claude/", ".cursor/",
    "scratchpad/",
)


def checkout_path(target: str, base: Path, primary: Path) -> Path | None:
    """`target` resolved (joined to `base` when relative) when it is inside the checkout
    `primary`; None when it is outside it. A path that cannot be resolved raises: the guard that
    asked cannot decide, and hook_chain refuses an event a guard raises on."""
    path = Path(target)
    resolved = (path if path.is_absolute() else base / path).resolve()
    return resolved if resolved.is_relative_to(primary.resolve()) else None


def production_path(target: str, base: Path, primary: Path) -> Path | None:
    """`checkout_path`, kept only when the file is app code."""
    resolved = checkout_path(target, base, primary)
    if resolved is None:
        return None
    rel = resolved.relative_to(primary.resolve()).as_posix()
    if rel.endswith(PRODUCTION_SUFFIXES) and not rel.startswith(NOT_PRODUCT_PREFIXES):
        return resolved
    return None


