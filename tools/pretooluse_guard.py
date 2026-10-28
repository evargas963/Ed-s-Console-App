"""Whether an edit target is the production checkout's app code: `production_path`, the one place
a guard places a path, read by process_lock_guard (the production-checkout rails). A library, not
a hook."""
from __future__ import annotations

from pathlib import Path

#: Production surfaces across the whole continuum, not just backend.
PRODUCTION_SUFFIXES = (".py", ".html", ".js", ".css", ".sql", ".ts", ".jsx", ".tsx")
#: Not part of the product surface.
NOT_PRODUCT_PREFIXES = (
    "tests/", "governance/", "docs/", "reports/", ".claude/", ".cursor/",
    "scratchpad/", "calibration/",
)


def production_path(target: str, base: Path, primary: Path) -> Path | None:
    """`target` resolved (joined to `base` when relative) when it is app code inside the checkout
    `primary`; None when it is outside it or not app code. A path that cannot be resolved raises:
    the guard that asked cannot decide, and hook_chain refuses an event a guard raises on."""
    path = Path(target)
    resolved = (path if path.is_absolute() else base / path).resolve()
    try:
        rel = resolved.relative_to(primary.resolve()).as_posix()
    except ValueError:
        return None
    if rel.endswith(PRODUCTION_SUFFIXES) and not rel.startswith(NOT_PRODUCT_PREFIXES):
        return resolved
    return None


