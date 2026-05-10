"""Coverage reconciliation — V3 completion criterion 1 (a)(b)(c)(d)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import DOT_CLAUDE, is_csv_source_of_truth


def scan_family(suffix: str, *, rel_posix: str = "") -> str:
    """Route files to a reconciliation family (V3-B: no extension whitelist — unknown → catch_all)."""
    if suffix == "":
        return "catch_all_text"
    s = suffix.lower()
    if s == ".py":
        return "python"
    if s in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        return "javascript_typescript"
    if s == ".html":
        return "html"
    if s == ".json":
        return "json"
    if s in {".yaml", ".yml"}:
        return "yaml"
    if s == ".toml":
        return "toml"
    if s == ".ini":
        return "ini"
    if s == ".md":
        return "markdown"
    if s == ".sql":
        return "sql"
    return "catch_all_text"


@dataclass
class FamilyReconciliation:
    a_present: int = 0
    b_scanned: int = 0
    c_excluded: int = 0
    exclusion_breakdown: list[dict[str, Any]] = field(default_factory=list)

    def add_exclusion(self, reason: str, clause: str) -> None:
        self.c_excluded += 1
        for row in self.exclusion_breakdown:
            if row["reason"] == reason and row["clause"] == clause:
                row["count"] += 1
                return
        self.exclusion_breakdown.append({"count": 1, "reason": reason, "clause": clause})

    def reconciles(self) -> bool:
        return self.a_present == self.b_scanned + self.c_excluded

    def as_dict(self) -> dict[str, Any]:
        return {
            "(a)_files_present_in_repo": self.a_present,
            "(b)_files_scanned": self.b_scanned,
            "(c)_files_excluded": self.c_excluded,
            "exclusions": self.exclusion_breakdown,
            "(d)_reconciles_a_eq_b_plus_c": self.reconciles(),
        }


@dataclass
class ReconciliationState:
    families: dict[str, FamilyReconciliation] = field(default_factory=dict)
    g1_1_dictionary_csv_excluded: int = 0
    pruned_directory_exclusions: list[dict[str, Any]] = field(default_factory=list)

    def family(self, name: str) -> FamilyReconciliation:
        if name not in self.families:
            self.families[name] = FamilyReconciliation()
        return self.families[name]

    def record_pruned_batch(
        self,
        *,
        relative_dir: str,
        dir_kind: str,
        file_count: int,
        clause: str,
        reason: str,
    ) -> None:
        self.pruned_directory_exclusions.append(
            {
                "relative_dir": relative_dir,
                "dir_kind": dir_kind,
                "file_count": file_count,
                "clause": clause,
                "reason": reason,
            }
        )

    def as_report(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "criterion_1_reconciliation": {
                "per_scan_family": {k: v.as_dict() for k, v in sorted(self.families.items())},
                "pruned_directory_exclusions": self.pruned_directory_exclusions,
                "g1_1_canonical_dictionary_csv_excluded_from_code_register": self.g1_1_dictionary_csv_excluded,
            }
        }
        all_ok = all(f.reconciles() for f in self.families.values())
        report["criterion_1_reconciliation"]["all_families_reconcile"] = all_ok
        return report


def inventory_mark_present(
    state: ReconciliationState,
    rel_posix: str,
    suffix: str,
    *,
    include_dot_claude: bool,
) -> str:
    """
    Count file toward (a) and return routing hint: 'scan' | 'skip_dictionary' | 'skip_claude'.
    """
    if is_csv_source_of_truth(rel_posix):
        state.g1_1_dictionary_csv_excluded += 1
        return "skip_dictionary"

    parts = set(Path(rel_posix).parts)
    fam_name = scan_family(suffix, rel_posix=rel_posix)
    fam = state.family(fam_name)
    fam.a_present += 1

    if not include_dot_claude and DOT_CLAUDE in parts:
        fam.add_exclusion(".claude worktree dedup", "G1.1 — .claude/worktrees; scan once policy")
        return "skip_claude"

    return "scan"
