"""Per-turn self adversarial audit — the machine-detectable ARTIFACT of the audit loop (RC-190).

WHY THIS EXISTS. Operator (non-negotiable, 2026-08-02): the 5-whys AND the self adversarial
audit run EACH TIME, not when the author judges the work big enough. The 5-why half was already
machine-forced at edit time (RC-66). The audit half had no per-turn artifact, so no hook could
demand it — v53's misses and Cursor's three guns all shipped through turns whose audit never
ran. This tool IS the artifact: it re-derives the turn's blast radius and runs the adversarial
checks against it, and `operator_law_guard` refuses to end a production-editing turn whose
ledger never ran it.

WHAT IT RUNS (fail-closed — anything unrunnable is a FAIL, not a skip):
  1. Blast radius: `git diff HEAD --name-only` filtered to production suffixes.
  2. ruff correctness (F401, F821, E9) on every changed .py.
  3. The negative-control suites: every tests/test_*.py whose TEXT names a changed module's
     stem — the attack tests are where a lock proves it can still fail. No matching suite for
     a changed module is itself a finding (exit 1) unless `--tests` names the lock explicitly.
  4. Appends a JSONL record (reports/turn_self_audit_log.jsonl) of the radius, the commands,
     and the outcome, so audits leave evidence instead of memories.

HONEST LIMIT (same clause as RC-49's check): this forces the audit ARTIFACT — the attack
suites re-run against the changed surface every turn. The cognitive depth of a fresh
adversarial pass remains the drift-audit protocol and the independent Cursor re-audit; this
lock makes SKIPPING the loop fail the turn, it does not make a shallow loop deep.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_REL = "reports/turn_self_audit_log.jsonl"
PROD_SUFFIXES = (".py", ".html", ".js", ".css", ".ts", ".sql")
#: Paths whose changes are governance/evidence, not production behaviour.
NON_PROD_PREFIXES = ("tests/", "governance/", "docs/", "reports/", ".claude/", "scratchpad/")


#: RC-284: what actually happened to a subprocess, kept separate from its exit code.
#: A timeout and a test failure both arrived as exit 1, so the ledger recorded
#: `fails: ['attack suites failed']` for 15 runs that never measured anything. An
#: instrument that cannot say "I did not measure" is the one place this repo's
#: absence-becomes-a-value defect must not live, because it is what judges every other fix.
OUTCOME_OK = "ok"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_LAUNCH_FAILURE = "launch_failure"


def _run(args: list[str], timeout: int = 600) -> tuple[int, str, str]:
    """Return (exit_code, combined_output, outcome).

    `outcome` is the channel the exit code does not have. A process that never finished has
    no exit code of its own — inheriting 1 makes "did not run" indistinguishable from "ran
    and failed", which is exactly what happened on 2026-08-07: 181 suites blew the 1800s
    ceiling and the audit reported that my tests had failed. They had not.
    """
    try:
        r = subprocess.run(args, cwd=str(REPO), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        partial = ""
        for stream in (getattr(e, "stdout", None), getattr(e, "stderr", None)):
            if stream:
                partial += stream if isinstance(stream, str) else stream.decode(
                    "utf-8", "replace")
        return 1, f"TIMED OUT after {timeout}s (nothing was measured)\n{partial}", \
            OUTCOME_TIMEOUT
    except (OSError, subprocess.SubprocessError) as e:
        return 1, f"RUN FAILED: {e}", OUTCOME_LAUNCH_FAILURE
    return (r.returncode, (r.stdout or "") + (r.stderr or ""), OUTCOME_OK)


def changed_production_files() -> list[str]:
    code, out, _outcome = _run(["git", "diff", "HEAD", "--name-only"])
    if code != 0:
        return []
    files = []
    for ln in out.splitlines():
        rel = ln.strip().replace("\\", "/")
        if not rel or rel.startswith(NON_PROD_PREFIXES):
            continue
        if rel.endswith(PROD_SUFFIXES):
            files.append(rel)
    return sorted(set(files))


def matching_attack_suites(changed: list[str]) -> tuple[list[str], list[str]]:
    """Test files whose text names a changed module's stem; and the changed stems no suite
    names (each of those is a finding, not a silent skip)."""
    stems = {Path(c).stem for c in changed if c.endswith(".py")}
    tests_dir = REPO / "tests"
    hits: set[str] = set()
    covered: set[str] = set()
    if tests_dir.exists():
        for tp in sorted(tests_dir.glob("test_*.py")):
            try:
                text = tp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for stem in stems:
                if stem in text:
                    hits.add(f"tests/{tp.name}")
                    covered.add(stem)
    return sorted(hits), sorted(stems - covered)


def research_violation(research: str, changed: list[str]) -> str | None:
    """RC-203/RC-205: production change must NAME a resolvable reference consulted first.

    Concrete markers alone are not enough (RC-205): a stale-generic string with '.py' in it
    used to pass. The reference must resolve to an existing repo path or an http(s) URL
    (tools.plus_player_locks.research_path_resolves)."""
    if not changed:
        return None
    r = (research or "").strip()
    concrete = ("/" in r) or ("§" in r) or ("http" in r) or (".md" in r) or (".py" in r) \
        or (".html" in r) or (".js" in r)
    if len(r) < 20 or not concrete:
        return ("no research record (RC-203/RC-205): name the reference consulted before acting "
                "via --research '<path/§section/URL + what it settled>' — a concrete artifact, "
                "not a vibe")
    try:
        from tools.plus_player_locks import research_path_resolves
    except ImportError:
        from plus_player_locks import research_path_resolves  # type: ignore
    if not research_path_resolves(r):
        return ("research does not resolve (RC-205): cite an existing repo path "
                "(e.g. static/chart.html) or an http(s) URL — unresolved references are theater")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="per-turn self adversarial audit (RC-190)")
    ap.add_argument("--tests", default="",
                    help="comma-separated test paths that lock changed non-.py surfaces or "
                         "modules the stem scan cannot match")
    ap.add_argument("--files", default="",
                    help="comma-separated production files to audit — REQUIRED narrowing in a "
                         "shared worktree where `git diff HEAD` carries another mission's "
                         "in-flight files; the choice is written into the audit record, so a "
                         "dishonest narrowing is visible, never silent")
    ap.add_argument("--research", default="",
                    help="RC-203 (operator law 2026-08-02: research THEN act, institutional "
                         "level, universal): NAME the reference consulted before the change — "
                         "a spec section, a reference implementation path, a direction doc, a "
                         "vendor source. Required whenever production files changed; must "
                         "contain at least one concrete artifact (a path, a §section, or a "
                         "URL), because 'I thought about it' is not research")
    args = ap.parse_args()

    changed = changed_production_files()
    if args.files:
        named = [f.strip().replace("\\", "/") for f in args.files.split(",") if f.strip()]
        changed = [c for c in changed if c in named] or named
    record: dict = {"ts_utc": time.time(), "changed": changed, "steps": [], "verdict": None,
                    "research": args.research.strip()}
    fails: list[str] = []

    rv = research_violation(args.research, changed)
    if rv:
        fails.append(rv)

    py_changed = [c for c in changed if c.endswith(".py")]
    if py_changed:
        code, out, outcome = _run([sys.executable, "-m", "ruff", "check", *py_changed,
                                   "--select", "F401,F821,E9"])
        record["steps"].append({"step": "ruff", "files": py_changed, "exit": code,
                                "outcome": outcome})
        print(out.strip() or f"ruff exit {code}")
        if outcome != OUTCOME_OK:
            fails.append(f"ruff did not run ({outcome}) — no correctness result was obtained")
        elif code != 0:
            fails.append("ruff correctness failed on changed files")

    suites, uncovered = matching_attack_suites(changed)
    extra = [t.strip() for t in args.tests.split(",") if t.strip()]
    suites = sorted(set(suites) | set(extra))
    if uncovered and not extra:
        fails.append(f"changed modules with NO attack suite naming them: {uncovered} — "
                     f"write the lock test or name it via --tests (a lock nobody attacks "
                     f"is green-and-inert)")
    if suites:
        code, out, outcome = _run([sys.executable, "-m", "pytest", *suites, "-q"],
                                  timeout=1800)
        tail = "\n".join(out.strip().splitlines()[-3:])
        record["steps"].append({"step": "pytest", "suites": suites, "exit": code,
                                "outcome": outcome, "tail": tail})
        print(tail)
        # RC-284: a timeout still FAILS the turn — an unmeasured turn is not a clean one —
        # but the record must not assert a test result it never obtained.
        if outcome == OUTCOME_TIMEOUT:
            fails.append(f"attack suites TIMED OUT after 1800s ({len(suites)} suites; "
                         f"NOTHING was measured — this is not a test failure)")
        elif outcome == OUTCOME_LAUNCH_FAILURE:
            fails.append(f"attack suites could not be LAUNCHED ({len(suites)} suites; "
                         f"no test result exists)")
        elif code != 0:
            fails.append("attack suites failed")
    elif changed and not fails:
        fails.append("production changed but zero suites ran — name the lock via --tests")

    record["verdict"] = "fail" if fails else ("clean" if changed else "no_production_change")
    record["fails"] = fails
    try:
        with (REPO / LOG_REL).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as e:
        print(f"AUDIT LOG UNWRITABLE ({e}) — an audit that leaves no evidence did not happen")
        return 2
    if fails:
        print("TURN SELF-AUDIT: FAIL")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(f"TURN SELF-AUDIT: {record['verdict'].upper()} "
          f"({len(changed)} changed production file(s), {len(suites)} suite(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
