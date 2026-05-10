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

        for fn in sorted(filenames):
            yield dirpath_p / fn
