"""Paired test for tools/check_no_deferral_language.py + Deferral Reconciliation lock.

Single file covers (a) the script's regex behavior, (b) the allowlist semantics,
(c) the closed-band ledger state the operator named in the 2026-05-24 Deferral
Reconciliation pass, and (d) a regression scan via the script's own check_path
across committed source. Consolidated 2026-05-24 — the operator's
"don't sprawl rules across files" directive.
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


@pytest.mark.parametrize(
    "phrase",
    [
        "Behavioral Playwright spec deferred — operator does not run Playwright via CI",
        "Implementation deferred until next slice.",
        "TBD: wire-in for the second horizon.",
        "TBD — see follow-up commit.",
        "Pending Playwright behavioral spec.",
        "Pending CI integration of the paired test.",
        "Pending operator sign-off on the wire path.",
        "Will revisit in a follow-up commit.",
        "next slice will cover the per-horizon variant",
        "next commit will land the e2e harness",
        "Land in a future commit when Playwright is wired.",
        "Will land later in a follow-up.",
        "Phase 2 paired-fix pending.",
        "Implementation pending — operator must enable CI first.",
        "Consumer pending — Phase 3 wires the strip.",
        "wire-in pending behavioral coverage",
        "Spec deferred for the e2e harness.",
        "I'll commit it next.",
        "I will add that later.",
        "I'll wire it in a follow-up.",
        # Patterns I personally used in the FIND-LIVEUI-6 commit that the
        # operator caught as deferral — added explicitly so the rule can't
        # regress.
        "Helpers are window-exposed so the spec can land later.",
        "Land it later when CI is wired.",
        "Behavioral e2e still pending.",
        "Behavioral spec coverage still pending.",
        "behavioral spec pending",
        "Can land later without refactoring.",
        "Will wire it later in a follow-up commit.",
    ],
)
def test_each_forbidden_phrase_is_caught(tmp_path: Path, phrase: str) -> None:
    p = tmp_path / "commit_msg.txt"
    p.write_text(f"Slice subject.\n\n{phrase}\n", encoding="utf-8")
    rc = mod.main([str(p)])
    assert rc == 1, f"expected the guard to fire on {phrase!r}"


@pytest.mark.parametrize(
    "clean",
    [
        # In-turn paired-fix language (no deferral).
        "Helpers ship in the same commit as the lock test.",
        "Operator preflip + live_reload verification on host runs separately.",
        # Legitimate FIND-LIVEUI-6 phrasing without deferral.
        "Behavioral spec lands in tests/e2e/find-liveui-6-direction-withhold.spec.js.",
        # The word `pending` on its own (no defer phrasing) — common in `pending_shell` reason codes.
        "reason = 'pending_shell' when analytics_pending_shell=true.",
        # `next` as a noun in code paths.
        "Next cache row to evict per LRU policy.",
        # A `future` mention that isn't about deferring this slice.
        "Future-proof the schema by versioning the manifest.",
    ],
)
def test_clean_text_passes(tmp_path: Path, clean: str) -> None:
    p = tmp_path / "commit_msg.txt"
    p.write_text(f"Slice subject.\n\n{clean}\n", encoding="utf-8")
    rc = mod.main([str(p)])
    assert rc == 0, f"clean text should pass, got rc=1 on {clean!r}"


def test_allowlisted_open_items_md_does_not_trip(tmp_path: Path) -> None:
    """OPEN_ITEMS.md is the legitimate place for `pending` / `TBD` rows."""
    p = tmp_path / "OPEN_ITEMS.md"
    p.write_text(
        "- [ ] LIVE-UI-3 — pending operator sign-off.\n"
        "- [ ] TBD: wire L1 SSE diag counters.\n"
        "- Spec deferred until pytest-to-ci lands.\n",
        encoding="utf-8",
    )
    rc = mod.main([str(p)])
    assert rc == 0


def test_allowlisted_governance_md_does_not_trip(tmp_path: Path) -> None:
    p = tmp_path / "governance"
    p.mkdir()
    g = p / "PROGRAM_PLAN.md"
    g.write_text(
        "Phase 2 paired-fix pending — see row in STACK_WIRING_INTEGRITY_MAP.md.\n"
        "Follow-up commit lands the e2e spec.\n",
        encoding="utf-8",
    )
    rc = mod.main([str(g)])
    assert rc == 0


def test_allowlisted_agents_md_does_not_trip() -> None:
    """AGENTS.md lists banned deferral phrases as documentation — must not self-trip."""
    rc = mod.main([str(REPO_ROOT / "AGENTS.md")])
    assert rc == 0


def test_allowlisted_memory_file_does_not_trip(tmp_path: Path) -> None:
    """The memory file documenting the rule must list the banned phrases without firing."""
    p = tmp_path / "memory"
    p.mkdir()
    m = p / "feedback_no_audit_deferral_across_walks.md"
    m.write_text("Forbidden: 'deferred', 'TBD:', 'pending Playwright'.\n", encoding="utf-8")
    rc = mod.main([str(m)])
    assert rc == 0


def test_script_itself_allowlisted() -> None:
    """The check script can name its own banned phrases without self-failing."""
    rc = mod.main([str(REPO_ROOT / "tools" / "check_no_deferral_language.py")])
    assert rc == 0


def test_no_args_returns_zero() -> None:
    assert mod.main([]) == 0


def test_missing_path_does_not_crash(tmp_path: Path) -> None:
    rc = mod.main([str(tmp_path / "does_not_exist.txt")])
    assert rc == 0


def test_reports_file_line_phrase(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    p = tmp_path / "msg.txt"
    p.write_text("ok line\nactually spec deferred\n", encoding="utf-8")
    rc = mod.main([str(p)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "msg.txt:2" in out
    assert "deferred" in out.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Deferral Reconciliation locks (closed-band ledger state)
# ─────────────────────────────────────────────────────────────────────────────
# Operator escalation 2026-05-24: the deferral pattern hides not just in
# commit messages but in stale ledger rows. Map rows say "TBD / pending /
# inventory only" while the code says "landed". OPEN_ITEMS keeps a row [ ]
# while a SHA exists. Duplicate rows. [x]/[ ] conflicts for the same item.
# Cited test paths that don't exist.
#
# These assertions are consolidated into the same file as the regex-behavior
# tests above per operator directive "i don't want rules in various places".


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
    combined = "".join(open_items_text[m.start() : m.start() + 600] for m in rows)
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
    combined = "".join(open_items_text[m.start() : m.start() + 600] for m in rows)
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
    pat = re.compile(
        r"-\s*\[(x| )\]\s+\*\*COH-I-B,\s*COH-I-D,\s*COH-I-F,\s*COH-I-G,\s*COH-I-I,\s*COH-I-L,\s*COH-I-M\*\*",
    )
    m = pat.search(open_items_text)
    assert m, "Phase 5 COH-I tier-3 grouping row must exist"
    assert m.group(1) == "x", "Phase 5 COH-I tier-3 grouping must be [x] — individual rows already closed"


def test_pilot1_disclosed_finds_parent_closed_or_real_gate(open_items_text: str) -> None:
    """Pilot 1 chunks 3-N parent row must not carry self-referential 'deferred' label."""
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
    """Regression scan — every source file outside the allowlist must pass the guard.

    Uses the same `check_path` function the pre-commit hook uses, so this test is the
    single source of truth for "is the guard happy with the repo".
    """
    failures: list[str] = []
    in_scope_extensions = {".py", ".js", ".yml", ".yaml", ".html", ".css"}
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
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in skip_path_prefixes):
            continue
        if path.suffix not in in_scope_extensions:
            continue
        hits = mod.check_path(path)
        for line_no, label, snippet in hits:
            failures.append(f"{rel}:{line_no}: {label}: {snippet[:100]}")
    if failures:
        msg = "\n".join(failures[:30])
        pytest.fail(
            "deferral-language hits in committed source files "
            "(see tools/check_no_deferral_language.py for the phrase list; either land the "
            "work in-turn or move future tracking to OPEN_ITEMS.md / governance/):\n" + msg,
        )


def test_map_has_no_phase_2_paired_fix_pending(map_text: str) -> None:
    """Specific pattern the operator named — map rows must not claim 'Phase 2 paired-fix pending'."""
    assert "Phase 2 paired-fix pending" not in map_text
    assert "still pending" not in map_text.lower()
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
