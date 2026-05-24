"""Paired test for tools/check_no_deferral_language.py.

Locks every forbidden phrase the operator named in the 2026-05-24 deferral
escalation, plus the allowlist semantics so that legitimate future-work
tracking surfaces (OPEN_ITEMS.md, governance/*, the script + memory file)
don't trip the guard.
"""

from __future__ import annotations

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
    p.write_text("ok line\nactually deferred this\n", encoding="utf-8")
    rc = mod.main([str(p)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "msg.txt:2" in out
    assert "deferred" in out.lower()
