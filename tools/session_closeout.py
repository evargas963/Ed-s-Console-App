#!/usr/bin/env python3
"""Session close-out gate — the mechanical answer to "report green or fix it".

Standing operator rule (2026-07-19): a work turn may not be reported as finished while
anything it touched is red, and a known problem may not be handed back as someone else's.
Goodwill has failed at this repeatedly, so it is mechanised here.

This runs the whole close-out in one command and prints ONE verdict line. If the verdict is
not SESSION_CLOSEOUT_GREEN, the turn is not finished — regardless of how good the prose is.

    python tools/session_closeout.py

Checks, in order (the worktree-handoff step 0 was removed with the vendor worktree
policy in the 2026-08-24 Architecture A teardown):
  1. INSTITUTIONAL GATE      — tools/check_institutional_correctness.py must exit 0
  2. AFFECTED TESTS          — every changed/untracked .py must have its tests RUN, not
                               merely collected (collection proves imports, not assertions)
  3. NO OVERDUE CLAIMS       — governance/unproven_register.md has no overdue row
  4. NO ORPHANED CHANGES     — a changed production module with no test touching it is
                               surfaced, so "I'll test it later" cannot pass silently

Exit code is the arbiter. There is no --force.

Handoff implication: commit (or stash) protected source before closeout GREEN. Mid-turn
verification of dirty WIP uses pytest / the institutional gate directly — not closeout.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"


def _run(cmd: list[str], timeout: int = 1800) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def changed_python_files() -> list[str]:
    """Modified, staged, and untracked .py files in the working tree."""
    out: set[str] = set()
    for args in (["diff", "--name-only", "HEAD"],
                 ["ls-files", "--others", "--exclude-standard"]):
        rc, txt = _run(["git", *args])
        if rc != 0:
            continue
        for line in txt.splitlines():
            line = line.strip()
            if line.endswith(".py") and (REPO / line).exists():
                out.add(line)
    return sorted(out)


def tests_for(changed: list[str]) -> list[str]:
    """Test files that are themselves changed, plus tests naming a changed module."""
    picked: set[str] = set()
    stems = set()
    for c in changed:
        p = Path(c)
        if p.parts[0] == "tests" and p.name.startswith("test_"):
            picked.add(c)
        else:
            stems.add(p.stem)
    if not stems:
        return sorted(picked)

    # Select a test only if it actually IMPORTS a changed module.
    #
    # This was a plain substring scan (`if any(s in txt for s in stems)`), which matched
    # any test merely MENTIONING a stem. Stems like "server", "config", "schema" and
    # "runner" appear in almost every test file, so a normal working tree selected 301
    # files -- effectively the whole suite -- and every close-out cost ~21 minutes.
    # Import-based selection is what "affected" actually means.
    for tf in sorted(TESTS.rglob("test_*.py")):
        if "archive" in tf.relative_to(TESTS).parts:
            continue
        if _imported_modules(tf) & stems:
            picked.add(tf.relative_to(REPO).as_posix())
    return sorted(picked)


def _imported_modules(path: Path) -> set[str]:
    """Every module name a test file imports, including importlib/reload string forms."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()

    def _add_dotted(name: str) -> None:
        found.add(name.split(".")[0])
        found.add(name.split(".")[-1])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                _add_dotted(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            _add_dotted(node.module)
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if fname in ("import_module", "__import__", "reload") and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    _add_dotted(a0.value)
    return found


def _count_overdue_claims() -> int:
    """UNPROVEN/DISPROVED rows in the register whose due date has passed."""
    import datetime

    reg = REPO / "governance" / "unproven_register.md"
    if not reg.exists():
        return 0
    today = datetime.date.today()
    overdue = 0
    for line in reg.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0] not in ("UNPROVEN", "DISPROVED"):
            continue
        try:
            if datetime.date.fromisoformat(cells[2]) < today:
                overdue += 1
        except ValueError:
            continue
    return overdue


def _orphaned_production_changes(changed: list[str], targets: list[str]) -> list[str]:
    """Changed production modules that no selected test file even mentions."""
    prod = [c for c in changed if not c.startswith(("tests/", "tools/"))]
    covered: set[str] = set()
    for t in targets:
        try:
            txt = (REPO / t).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        covered.update(c for c in prod if Path(c).stem in txt)
    return [c for c in prod if c not in covered]


def _run_affected_tests(targets: list[str]) -> bool:
    """Execute the affected tests and print the verdict. True when green."""
    if not targets:
        print("[PASS] affected tests (none implicated)")
        return True
    print(f"       running {len(targets)} affected test file(s)...")
    rc, out = _run([sys.executable, "-m", "pytest", *targets, "-q", "--no-header"])
    tail = [ln for ln in out.splitlines() if ln.strip()][-1:] or [""]
    print(f"[{'PASS' if rc == 0 else 'FAIL'}] affected tests  {tail[0].strip()[:60]}")
    if rc == 0:
        return True
    for ln in out.splitlines():
        if ln.startswith(("FAILED", "ERROR")):
            print(f"         {ln.strip()[:110]}")
    return False


def main() -> int:
    failures: list[str] = []
    print("=" * 78)
    print("SESSION CLOSE-OUT")
    print("=" * 78)

    changed = changed_python_files()
    print(f"\nchanged/untracked python files: {len(changed)}")

    # 1 ── institutional gate
    rc, _ = _run([sys.executable, "tools/check_institutional_correctness.py"])
    print(f"[{'PASS' if rc == 0 else 'FAIL'}] institutional gate")
    if rc != 0:
        failures.append("institutional gate is red")

    # 2 ── affected tests actually EXECUTED
    targets = tests_for(changed)
    if not _run_affected_tests(targets):
        failures.append("affected tests are red")

    # 2b ── provably-dead code (v17 graded the report-only tool THEATER; --check is the lock).
    # Lives HERE and not in the commit gate because its full-tree reference scan runs ~2min —
    # acceptable at turn end, hostile per-commit. Exit 2 = deletable_now non-empty.
    rc, out = _run([sys.executable, "tools/verify_dead_code_orphans_v1.py", "--check"],
                   timeout=600)
    print(f"[{'PASS' if rc == 0 else 'FAIL'}] dead-code orphans (--check)")
    if rc != 0:
        for ln in (out or "").splitlines()[-6:]:
            if ln.strip():
                print(f"         {ln.strip()[:110]}")
        failures.append("provably-dead code present (verify_dead_code_orphans_v1 --check)")

    # 3 ── overdue claims (the gate covers this, reported separately for visibility)
    overdue = _count_overdue_claims()
    print(f"[{'PASS' if overdue == 0 else 'FAIL'}] unproven register ({overdue} overdue)")
    if overdue:
        failures.append(f"{overdue} overdue claim(s)")

    # 4 ── orphaned production changes (advisory, but SHOWN — never silent)
    orphans = _orphaned_production_changes(changed, targets)
    if orphans:
        print(f"[WARN] {len(orphans)} changed production file(s) with no test referencing them:")
        for o in orphans[:10]:
            print(f"         {o}")
        if len(orphans) > 10:
            print(f"         ... and {len(orphans) - 10} more")
    else:
        print("[PASS] no orphaned production changes")

    print("\n" + "=" * 78)
    if failures:
        print(f"SESSION_CLOSEOUT_RED — {'; '.join(failures)}")
        print("The turn is NOT finished. Fix, then re-run.")
        return 1
    print("SESSION_CLOSEOUT_GREEN — gate clean, affected tests executed and passing,")
    print("no overdue claims. Safe to report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
