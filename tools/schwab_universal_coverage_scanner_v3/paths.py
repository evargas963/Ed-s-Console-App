"""Repository paths and file classification — V3-B (no extension whitelist)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

CSV_SOURCE_OF_TRUTH_SUFFIX = "schwab_field_inventory/schwab_field_dictionary.csv"
DOT_CLAUDE = ".claude"

# Directory names we do not descend into; contents are aggregated into reconciliation (c).
PRUNE_DIR_NAMES = frozenset({".git", "__pycache__", ".pytest_cache", ".mypy_cache"})

# Whole subtrees excluded from the universal coverage walk (POSIX path prefixes).
# Rationale: raw Schwab inventory dumps and npm trees are not operator closure targets;
# scanning them dominated register row count (~25M) vs ~9k files attempted.
PRUNE_SUBTREE_PREFIXES: tuple[str, ...] = (
    "schwab_field_inventory/pricehistory",
    "schwab_field_inventory/chains",
    "schwab_field_inventory/instruments",
    "schwab_field_inventory/streaming",
    "schwab_field_inventory/market_hours",
    "backups",
)

# Tracked-but-non-product subtrees — not market-field disposition surfaces (2026-05-24 scope diet).
# Combined with .gitignore-aware walk to drop generated/untracked bloat from register cardinality.
SCAN_SCOPE_EXCLUDE_PREFIXES: tuple[str, ...] = (
    "governance/archive",
    "models/active",
    "models/active_5c",
    "models/active_15c",
    "models/active_60c",
    "models/validation_runs",
    "tools",
    "calibration",
)

# Generated / vendor directory basenames — never scanned (closure targets source + governance text).
PRUNE_GENERATED_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        "htmlcov",
        ".tox",
        ".eggs",
        "__pypackages__",
    }
)


def is_csv_source_of_truth(rel_posix: str) -> bool:
    return rel_posix.replace("\\", "/").endswith(CSV_SOURCE_OF_TRUTH_SUFFIX)


def count_files_under(dir_path: Path) -> int:
    if not dir_path.is_dir():
        return 0
    return sum(1 for p in dir_path.rglob("*") if p.is_file())


def is_binary_sample(data: bytes) -> bool:
    """Null-byte heuristic (V3-B)."""
    return b"\x00" in data


def try_decode_utf8(data: bytes) -> tuple[str | None, str | None]:
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "utf8_decode_failed"


@dataclass(frozen=True)
class PruneBatch:
    relative_dir: str
    dir_kind: str
    file_count: int
    clause: str
    reason: str


def rel_matches_prefix(rel_posix: str, prefix: str) -> bool:
    rl = rel_posix.replace("\\", "/")
    pre = prefix.replace("\\", "/").strip("/")
    return rl == pre or rl.startswith(pre + "/")


def rel_matches_any_prefix(rel_posix: str, prefixes: Sequence[str]) -> bool:
    return any(rel_matches_prefix(rel_posix, p) for p in prefixes)


def git_work_tree(root: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(root.resolve()), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and (proc.stdout or "").strip() == "true"


class GitPathScope:
    """Git check-ignore wrapper — skips gitignored paths when walking the workspace."""

    def __init__(self, root: Path, *, enabled: bool) -> None:
        self._root = root.resolve()
        self.enabled = enabled and git_work_tree(self._root)
        self._cache: dict[str, bool] = {}

    def is_ignored(self, rel_posix: str) -> bool:
        if not self.enabled:
            return False
        rel = rel_posix.replace("\\", "/").lstrip("./")
        if rel in self._cache:
            return self._cache[rel]
        proc = subprocess.run(
            ["git", "-C", str(self._root), "check-ignore", "-q", "--", rel],
            capture_output=True,
            check=False,
        )
        ignored = proc.returncode == 0
        self._cache[rel] = ignored
        return ignored


def walk_workspace_files(
    root: Path,
    *,
    on_prune: Callable[[PruneBatch], None],
    respect_gitignore: bool = True,
    scope_exclude_prefixes: Sequence[str] = SCAN_SCOPE_EXCLUDE_PREFIXES,
) -> Iterator[Path]:
    """
    Walk repo files for scanning. Pruned directories are not descended into;
    caller must record each prune via on_prune (reconciliation (c)).
    """
    root = root.resolve()
    git_scope = GitPathScope(root, enabled=respect_gitignore)
    scope_prefixes = tuple(scope_exclude_prefixes)

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        dirpath_p = Path(dirpath)
        rel_parent = dirpath_p.relative_to(root) if dirpath_p != root else Path(".")

        for d in list(dirnames):
            if d in PRUNE_DIR_NAMES:
                sub = dirpath_p / d
                n = count_files_under(sub)
                clause = {
                    ".git": "V3 hygiene — repository metadata (.git) not scanned",
                    "__pycache__": "V3 reconciliation — Python bytecode cache not scanned",
                    ".pytest_cache": "V3 reconciliation — pytest cache not scanned",
                    ".mypy_cache": "V3 reconciliation — mypy cache not scanned",
                }[d]
                on_prune(
                    PruneBatch(
                        relative_dir=(rel_parent / d).as_posix(),
                        dir_kind=d,
                        file_count=n,
                        clause=clause,
                        reason="pruned_directory",
                    )
                )
                dirnames.remove(d)
                continue

            rel_sub = (rel_parent / d).as_posix().replace("\\", "/")
            if d in PRUNE_GENERATED_DIR_NAMES:
                sub = dirpath_p / d
                n = count_files_under(sub)
                on_prune(
                    PruneBatch(
                        relative_dir=rel_sub,
                        dir_kind=d,
                        file_count=n,
                        clause=f"V3 scope — generated/vendor directory not scanned ({d}/)",
                        reason="pruned_directory",
                    )
                )
                dirnames.remove(d)
                continue

            pruned = False
            for prefix in PRUNE_SUBTREE_PREFIXES:
                if rel_matches_prefix(rel_sub, prefix):
                    sub = dirpath_p / d
                    n = count_files_under(sub)
                    on_prune(
                        PruneBatch(
                            relative_dir=rel_sub,
                            dir_kind="inventory_or_backup_dump",
                            file_count=n,
                            clause=f"V3 scope — subtree not scanned ({prefix}/*)",
                            reason="pruned_directory",
                        )
                    )
                    dirnames.remove(d)
                    pruned = True
                    break
            if pruned:
                continue

            for prefix in scope_prefixes:
                if rel_matches_prefix(rel_sub, prefix):
                    sub = dirpath_p / d
                    n = count_files_under(sub)
                    on_prune(
                        PruneBatch(
                            relative_dir=rel_sub,
                            dir_kind="scan_scope_exclude",
                            file_count=n,
                            clause=f"V4 scan scope — non-product subtree not scanned ({prefix}/*)",
                            reason="pruned_directory",
                        )
                    )
                    dirnames.remove(d)
                    pruned = True
                    break
            if pruned:
                continue

            if git_scope.is_ignored(rel_sub):
                sub = dirpath_p / d
                n = count_files_under(sub)
                on_prune(
                    PruneBatch(
                        relative_dir=rel_sub,
                        dir_kind="gitignore",
                        file_count=n,
                        clause="V4 scan scope — path ignored per .gitignore",
                        reason="pruned_directory",
                    )
                )
                dirnames.remove(d)

        for fn in sorted(filenames):
            rel_file = (rel_parent / fn).as_posix().replace("\\", "/")
            if git_scope.is_ignored(rel_file):
                continue
            yield dirpath_p / fn
