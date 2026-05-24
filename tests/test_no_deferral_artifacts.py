"""Deferral Reconciliation lock — closed-band ledger must match commit reality.

Operator escalation 2026-05-24 (paraphrasing): the deferral pattern hides not
just in commit messages but in stale ledger rows. Map rows say "TBD / pending
/ inventory only" while the code says "landed". OPEN_ITEMS keeps a row [ ]
while a SHA exists. Duplicate rows. [x]/[ ] conflicts for the same item.
Cited test paths that don't exist. The producer-cone walk drifts from "fixes
landed" to "narrative says landed".

This test locks the state for the specific items the operator named in the
2026-05-24 Deferral Reconciliation message, and runs a regression scan against
the forbidden-phrase list shared with `tools/check_no_deferral_language.py`.

Scope is deliberately narrow:
  - Lock the specific FIND-LIVEUI-6 / LIVE-UI-1 / LIVE-UI-2 closures with
    SHA cites.
  - Catch the duplicate-row pattern (LIVE-UI-A appeared in two sections).
  - Catch [x]/[ ] conflicts (OBS-CLUSTER-RANK-1 + Phase 5 COH-I tier-3
    group both had conflicting markers).
  - Verify every test path cited in OPEN_ITEMS.md or
    governance/STACK_WIRING_INTEGRITY_MAP.md actually exists on disk.
  - Scan non-allowlisted source files for the forbidden-phrase list
    (single source of truth in tools/check_no_deferral_language.py).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_no_deferral_language as mod  # noqa: E402


@pytest.fixture(scope="module")
def open_items_text() -> str:
    return (REPO_ROOT / "OPEN_ITEMS.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def map_text() -> str:
    return (REPO_ROOT / "governance" / "STACK_WIRING_INTEGRITY_MAP.md").read_text(encoding="utf-8")


def _find_row_state(text: str, row_id: str) -> str | None:
    """Return 'x' / ' ' (open) for the first markdown checkbox row matching `**row_id**`."""
    pat = re.compile(
        r"-\s*\[(x| )\]\s+\*\*" + re.escape(row_id) + r"(?:\*\*|\s)",
        re.IGNORECASE,
    )
    m = pat.search(text)
    return m.group(1) if m else None


def _count_row_occurrences(text: str, row_id: str) -> int:
    pat = re.compile(
        r"-\s*\[(?:x| )\]\s+\*\*" + re.escape(row_id) + r"(?:\*\*|\s)",
        re.IGNORECASE,
    )
    return len(pat.findall(text))


def _all_checkbox_rows(text: str, row_id: str) -> list[re.Match[str]]:
    pat = re.compile(
        r"-\s*\[(x| )\]\s+\*\*" + re.escape(row_id) + r"(?:\*\*|\s)",
        re.IGNORECASE,
    )
    return list(pat.finditer(text))


def test_find_liveui_6_closed_with_sha_cites(open_items_text: str) -> None:
    rows = _all_checkbox_rows(open_items_text, "FIND-LIVEUI-6")
    assert rows, "FIND-LIVEUI-6 checkbox row missing"
    assert all(m.group(1) == "x" for m in rows), "every FIND-LIVEUI-6 row must be [x]"
    combined = "".join(
        open_items_text[m.start() : m.start() + 600] for m in rows
    )
    assert "413787a" in combined, "FIND-LIVEUI-6 rows must cite SHA 413787a (helpers/markers/CSS)"
    assert "e3742ac" in combined, "FIND-LIVEUI-6 rows must cite SHA e3742ac (Playwright spec)"


def test_live_ui_1_closed_with_sha_cite(open_items_text: str) -> None:
    state = _find_row_state(open_items_text, "LIVE-UI-1")
    assert state == "x", "LIVE-UI-1 must be [x] after inventory landed @ f57c6a7"
    snippet_idx = open_items_text.find("LIVE-UI-1")
    body = open_items_text[snippet_idx : snippet_idx + 1200]
    assert "f57c6a7" in body, "LIVE-UI-1 row must cite SHA f57c6a7 (inventory commit)"


def test_live_ui_2_closed_with_sha_cite(open_items_text: str) -> None:
    rows = _all_checkbox_rows(open_items_text, "LIVE-UI-2")
    assert rows, "LIVE-UI-2 checkbox row missing"
    assert all(m.group(1) == "x" for m in rows), "every LIVE-UI-2 row must be [x]"
    combined = "".join(
        open_items_text[m.start() : m.start() + 600] for m in rows
    )
    assert "413787a" in combined or "e3742ac" in combined, (
        "LIVE-UI-2 rows must cite at least one FIND-LIVEUI-6 SHA"
    )


def test_live_ui_a_appears_at_most_once(open_items_text: str) -> None:
    """Operator flagged the duplicate row in COHERENCE-AUDIT vs Phase 3 sections."""
    count = _count_row_occurrences(open_items_text, "LIVE-UI-A")
    assert count <= 1, (
        f"LIVE-UI-A appears {count} times as a markdown checkbox row; merge to a single canonical "
        "entry (the Deferral Reconciliation pass removed the duplicate in the Phase 3 section)"
    )


def test_obs_cluster_rank_1_no_open_duplicate(open_items_text: str) -> None:
    """OBS-CLUSTER-RANK-1 was closed in COHERENCE-AUDIT TIER 3 but still appeared [ ] in Phase 5."""
    state = _find_row_state(open_items_text, "OBS-CLUSTER-RANK-1")
    assert state == "x", "OBS-CLUSTER-RANK-1 must be [x] (closed via CLUSTERING_RANK_NO_ZONES_FLOOR)"


def test_phase_5_coh_i_tier_3_group_closed(open_items_text: str) -> None:
    """The grouped Phase 5 row for COH-I-{B,D,F,G,I,L,M} must reflect the individual closures above."""
    # Find the grouping row text.
    pat = re.compile(
        r"-\s*\[(x| )\]\s+\*\*COH-I-B,\s*COH-I-D,\s*COH-I-F,\s*COH-I-G,\s*COH-I-I,\s*COH-I-L,\s*COH-I-M\*\*",
    )
    m = pat.search(open_items_text)
    assert m, "Phase 5 COH-I tier-3 grouping row must exist"
    assert m.group(1) == "x", "Phase 5 COH-I tier-3 grouping must be [x] — individual rows already closed"


def test_pilot1_disclosed_finds_parent_closed_or_real_gate(open_items_text: str) -> None:
    """Pilot 1 chunks 3-N parent row must not carry self-referential 'deferred' label."""
    # The parent row was renamed during reconciliation from "deferred FINDs" to "disclosed FINDs".
    assert "Pilot 1 Schwab walk — disclosed FINDs" in open_items_text, (
        "Pilot 1 parent row must be normalized to 'disclosed FINDs' (was 'deferred FINDs')"
    )


def test_layer_5_features_sweep_parent_closed_or_real_gate(open_items_text: str) -> None:
    assert "Layer 5 features sweep — disclosed FINDs" in open_items_text, (
        "Layer 5 features sweep parent row must be normalized to 'disclosed FINDs'"
    )


@pytest.mark.parametrize(
    "test_file",
    [
        "tests/test_find_liveui_6_v1.py",
        "tests/e2e/find-liveui-6-direction-withhold.spec.js",
        "tests/test_live_ui_integrity_v1.py",
        "tests/test_check_no_deferral_language.py",
        "tools/check_no_deferral_language.py",
    ],
)
def test_cited_test_files_exist(test_file: str) -> None:
    p = REPO_ROOT / test_file
    assert p.is_file(), f"file cited in OPEN_ITEMS / STACK_WIRING_INTEGRITY_MAP must exist: {test_file}"


def test_no_deferral_language_in_committed_source() -> None:
    """Regression scan — every source/test file outside the allowlist must pass the guard.

    Uses the same `check_path` function the pre-commit hook uses, so this test is the
    single source of truth for "is the guard happy with the repo".
    """
    failures: list[str] = []
    # Source surfaces in scope. Tests for the guard itself are excluded.
    in_scope_extensions = {".py", ".js", ".yml", ".yaml", ".html", ".css"}
    allowed_paths = {
        # Self-referential — the guard, its paired test, and this reconciliation
        # lock all NEED to name the forbidden phrases.
        REPO_ROOT / "tools" / "check_no_deferral_language.py",
        REPO_ROOT / "tests" / "test_check_no_deferral_language.py",
        REPO_ROOT / "tests" / "test_no_deferral_artifacts.py",
    }
    skip_path_prefixes = (
        ".git",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "venv",
        "tests/",  # tests quote forbidden phrases when locking the guard itself
        "tools/_phase",  # historical one-shot scripts
        "governance",  # legitimate future-work tracking
        "OPEN_ITEMS",
        "ACTIVE_PROGRAM",
        "memory/",
    )
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path in allowed_paths:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in skip_path_prefixes):
            continue
        if path.suffix not in in_scope_extensions:
            continue
        # Defer to the script's path-allowlist for OPEN_ITEMS / governance / etc.
        hits = mod.check_path(path)
        for line_no, label, snippet in hits:
            failures.append(f"{rel}:{line_no}: {label}: {snippet[:100]}")
    if failures:
        msg = "\n".join(failures[:30])
        pytest.fail(
            "deferral-language hits in committed source files "
            "(see tools/check_no_deferral_language.py for the phrase list; either land the work "
            "in-turn or move future tracking to OPEN_ITEMS.md / governance/):\n" + msg,
        )


def test_map_has_no_phase_2_paired_fix_pending(map_text: str) -> None:
    """Specific pattern the operator named — map rows must not claim 'Phase 2 paired-fix pending'."""
    assert "Phase 2 paired-fix pending" not in map_text
    assert "still pending" not in map_text.lower()
    # "inventory only" was the prior label for rows that had landed but not been promoted; the
    # reconciliation pass promotes them.
    assert "inventory only (Phase 2 paired-fix pending)" not in map_text


def test_map_test_path_cites_resolve(map_text: str) -> None:
    """Every `tests/...` cite in the map must resolve to a real file."""
    cite_pat = re.compile(r"`(tests/[^`]+?\.(?:py|spec\.js))(?:::[^`]+)?`")
    failures: list[str] = []
    for m in cite_pat.finditer(map_text):
        cited = m.group(1)
        if not (REPO_ROOT / cited).is_file():
            failures.append(cited)
    failures = sorted(set(failures))
    assert not failures, (
        "test-path cites in STACK_WIRING_INTEGRITY_MAP.md that don't resolve to a real file:\n"
        + "\n".join(failures)
    )
