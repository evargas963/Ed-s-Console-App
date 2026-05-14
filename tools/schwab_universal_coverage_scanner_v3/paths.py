"""Repository paths and file classification — V3-B (no extension whitelist)."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
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


def walk_workspace_files(
    root: Path,
    *,
    on_prune: Callable[[PruneBatch], None],
) -> Iterator[Path]:
    """
    Walk repo files for scanning. Pruned directories are not descended into;
    caller must record each prune via on_prune (reconciliation (c)).
    """
    root = root.resolve()

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
            if d == "node_modules":
                sub = dirpath_p / d
                n = count_files_under(sub)
                on_prune(
                    PruneBatch(
                        relative_dir=rel_sub,
                        dir_kind="node_modules",
                        file_count=n,
                        clause="V3 scope — node_modules not scanned (npm vendor tree)",
                        reason="pruned_directory",
                    )
                )
                dirnames.remove(d)
                continue

            for prefix in PRUNE_SUBTREE_PREFIXES:
                if rel_sub == prefix or rel_sub.startswith(prefix + "/"):
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
                    break

        for fn in sorted(filenames):
            yield dirpath_p / fn
