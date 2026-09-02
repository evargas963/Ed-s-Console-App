"""REPO REHABILITATION — CURRENT / TARGET / DELTA, generated from facts, plus the ratchet.

WHY ONE FILE. The mission asks for a status generator AND a no-regression ratchet. They are the
same computation asked twice: the ratchet is "measure CURRENT at two refs and refuse the ones
that got worse". Splitting them would create two producers of "what does this repo look like",
which is the duplicate-authority defect the rehabilitation exists to remove. There is no new
registry, no new governance surface, and no nightly report archive: the daily job prints to the
job summary and writes nothing to the repo.

WHAT IS MEASURED. Structural facts only, read from a git tree — module placement, tracked
runtime artifacts, directory ownership, import direction. Institutional debt is NOT recomputed
here: `tools/check_delta_adds_no_debt.py` already owns that question and already runs in
Hardening, so this tool defers to it rather than growing a second opinion.

USAGE
    python tools/repo_rehab_status.py                      # CURRENT / TARGET / TODAY'S DELTA
    python tools/repo_rehab_status.py --ratchet --base origin/main   # no-regression gate
    python tools/repo_rehab_status.py --host               # host-separation check only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── THE TARGET — FIXED AND HASH-PINNED ────────────────────────────────────────────────────
#: Pinned so the score cannot be improved by redefining what "done" means. `TARGET_SHA256`
#: is asserted by tests/test_repo_rehab_ratchet_v1.py; editing any value below changes the
#: digest and fails the suite, which is the point — the target is the operator's, not the
#: agent's, and a rehabilitation that may move its own goalposts measures nothing.
TARGET: dict = {
    "app_packages": [
        "api", "domain", "market_data", "options", "signals", "models", "decision",
        "infrastructure",
    ],
    "source_top_level": [
        "app", "research", "tests", "tools", "static", "config", "governance",
    ],
    "root_production_modules": 0,
    "tracked_runtime_artifacts": 0,
    "host_dirs_outside_source": ["runtime", "recovery", "artifacts", "worktrees"],
    "dependency_direction": {
        "domain": [],
        "market_data": ["domain"],
        "options": ["domain", "market_data"],
        "signals": ["domain", "market_data", "options"],
        "models": ["domain", "market_data", "options", "signals"],
        "decision": ["domain", "market_data", "options", "signals", "models"],
        "api": ["domain", "market_data", "options", "signals", "models", "decision",
                "infrastructure"],
        "infrastructure": ["domain"],
    },
}
TARGET_SHA256 = hashlib.sha256(
    json.dumps(TARGET, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

#: Directories that exist today and the TARGET does not name. They are not "allowed" — every
#: file in them must end up inside a TARGET directory or leave source. Listed so the report can
#: show the number shrinking; the ratchet refuses any INCREASE.
UNMAPPED_TOP_LEVEL = (
    "reports", "models", "docs", "calibration", "features", "arch_competition",
    "v2_decision", "verification", "planes", "schwab_field_inventory", "snapshot_sql",
    "scripts", "backups", "data",
)

#: Extensions that are runtime/generated state, never source.
RUNTIME_EXT = frozenset({".db", ".sqlite", ".sqlite3", ".log", ".pkl", ".joblib", ".h5",
                         ".pt", ".onnx", ".parquet", ".bin", ".ckpt"})

#: Recorded once so the daily report can surface them until the operator rules. Implementing
#: the TARGET verbatim while a known collision stands would be dishonest; changing it here
#: would be worse, because the target is not the agent's to move.
TARGET_OPEN_QUESTIONS = (
    "app/models collides with the existing top-level models/ (438 tracked files, 224 .pt/.pkl "
    "trained artifacts). Two meanings of 'models' — ML code vs trained state — in one tree is "
    "the duplicate-authority shape this rehabilitation removes. RECOMMEND app/ml, with trained "
    "artifacts leaving source for artifacts/. Not applied: the TARGET is the operator's.",
    "14 top-level directories holding 1,286 tracked files (44% of the repo) are named by "
    "neither the TARGET nor its exclusions. RECOMMEND stating that each maps into app/*, "
    "research/, tools/, or leaves source; otherwise 'unexplained difference = NONE' is "
    "unreachable by construction.",
)


# ── facts ─────────────────────────────────────────────────────────────────────────────────
def _git(args: list[str], repo: Path = REPO) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def tracked_files(ref: str, repo: Path = REPO) -> list[str]:
    out = _git(["ls-tree", "-r", "--name-only", ref], repo)
    return out.splitlines() if out else []


def _blob_lines(ref: str, path: str, repo: Path = REPO) -> int:
    out = _git(["show", f"{ref}:{path}"], repo)
    return len(out.splitlines()) if out else 0


def current(ref: str = "HEAD", repo: Path = REPO, with_loc: bool = True) -> dict:
    """CURRENT, generated from the tree at `ref`. No hand-entered status anywhere."""
    files = tracked_files(ref, repo)
    root_py = sorted(f for f in files if "/" not in f and f.endswith(".py"))
    app_py = sorted(f for f in files if f.startswith("app/") and f.endswith(".py"))
    runtime = sorted(f for f in files if os.path.splitext(f)[1].lower() in RUNTIME_EXT)
    unmapped = sorted(f for f in files
                      if f.split("/")[0] in UNMAPPED_TOP_LEVEL and "/" in f)
    tops = {f.split("/")[0] for f in files if "/" in f and not f.startswith(".")}
    gov = sorted(f for f in files if f.startswith("governance/"))
    return {
        "ref": (_git(["rev-parse", "--short", ref], repo) or ref).strip(),
        "tracked_files": len(files),
        "root_production_modules": len(root_py),
        "root_production_loc": sum(_blob_lines(ref, f, repo) for f in root_py) if with_loc else -1,
        "server_py_loc": _blob_lines(ref, "server.py", repo) if with_loc else -1,
        "app_modules": len(app_py),
        "app_loc": sum(_blob_lines(ref, f, repo) for f in app_py) if with_loc else -1,
        "app_packages_present": sorted(
            {f.split("/")[1] for f in app_py if f.count("/") >= 2}),
        "tools_py": len([f for f in files if f.startswith("tools/") and f.endswith(".py")]),
        "governance_files": len(gov),
        "governance_loc": (sum(_blob_lines(ref, f, repo) for f in gov)
                           if with_loc and len(gov) <= 400 else -1),
        "tracked_runtime_artifacts": len(runtime),
        "unmapped_top_level_dirs": sorted(tops & set(UNMAPPED_TOP_LEVEL)),
        "unmapped_tracked_files": len(unmapped),
        "_root_py_names": root_py,
        "_app_py_names": app_py,
        "_runtime_names": runtime,
    }


def host_separation(root: Path | None = None, baseline: str | None = None,
                    ref: str = "HEAD") -> dict:
    """Is runtime/recovery/artifacts/worktrees state OUTSIDE the source checkout?

    THREE states, not two, and the distinction is the whole value. Reporting an un-migrated
    layout as VIOLATED on day one makes the signal useless exactly when the work starts —
    MEASURED on the first run, which returned VIOLATED for 224 INHERITED trained-model blobs
    and would have done so every day until the last one moved.

      SEPARATED         host dirs exist and no runtime state is tracked in source
      NOT_YET_SEPARATED inherited runtime state still in source, not growing — the baseline
      VIOLATED          runtime state is being RE-CREATED inside source (count above baseline)

    VIOLATED is reserved for the thing that must never happen again, so it means something when
    it appears.
    """
    src = (root or REPO).resolve()
    host = src.parent
    present = {d: (host / d).is_dir() for d in TARGET["host_dirs_outside_source"]}
    contaminating = sorted(
        f for f in tracked_files(ref, src)
        if os.path.splitext(f)[1].lower() in RUNTIME_EXT)
    base_n = None
    if baseline:
        base_n = len([f for f in tracked_files(baseline, src)
                      if os.path.splitext(f)[1].lower() in RUNTIME_EXT])
    if base_n is not None and len(contaminating) > base_n:
        state = "VIOLATED"
    elif not contaminating and all(present.values()):
        state = "SEPARATED"
    else:
        state = "NOT_YET_SEPARATED"
    return {"state": state, "host_root": str(host), "host_dirs_present": present,
            "tracked_runtime_in_source": len(contaminating),
            "baseline_runtime_in_source": base_n, "sample": contaminating[:5]}


# ── the ratchet ───────────────────────────────────────────────────────────────────────────
def ratchet(base: str = "origin/main", head: str = "HEAD", repo: Path = REPO) -> list[str]:
    """Refuse NEW divergence from the TARGET. Inherited debt may stay; it may not grow.

    Deliberately NOT a debt checker: `check_delta_adds_no_debt` already owns institutional
    violations and duplicate-producer counts and already runs in Hardening. This adds only the
    architecture predicates that nothing else measures.
    """
    b, h = current(base, repo, with_loc=False), current(head, repo, with_loc=False)
    out: list[str] = []

    new_root = sorted(set(h["_root_py_names"]) - set(b["_root_py_names"]))
    if new_root:
        out.append(
            f"NEW ROOT PRODUCTION MODULE(S): {', '.join(new_root)}. The TARGET has none; new "
            f"code belongs in app/<package>/. Inherited root modules may stay — this refuses "
            f"ADDING to them.")

    new_rt = sorted(set(h["_runtime_names"]) - set(b["_runtime_names"]))
    if new_rt:
        out.append(
            f"NEW TRACKED RUNTIME/GENERATED STATE: {', '.join(new_rt[:6])}"
            f"{' ...' if len(new_rt) > 6 else ''}. Runtime, DB, backup, log and trained-model "
            f"state lives outside source (artifacts/, runtime/, recovery/).")

    if h["unmapped_tracked_files"] > b["unmapped_tracked_files"]:
        out.append(
            f"UNMAPPED-DIRECTORY GROWTH: {b['unmapped_tracked_files']} -> "
            f"{h['unmapped_tracked_files']} tracked files in top-level directories the TARGET "
            f"does not name. Those directories may only shrink.")

    # A package already migrated must not be re-owned by the root.
    base_app_mods = {Path(f).stem for f in b["_app_py_names"]}
    regressed = sorted(base_app_mods & {Path(f).stem for f in h["_root_py_names"]})
    if regressed:
        out.append(
            f"MIGRATED CODE MOVED BACK TOWARD ROOT: {', '.join(regressed)} exists under app/ at "
            f"the base and at the repo root at HEAD. Migration is one-way.")

    out.extend(_dependency_direction_violations(head, repo))
    out.extend(_self_protection_violations(base, head, repo))
    return out


def _dependency_direction_violations(ref: str, repo: Path = REPO) -> list[str]:
    """Once app/<pkg> exists, it may only import the packages the TARGET allows it to."""
    import ast

    allowed = TARGET["dependency_direction"]
    out: list[str] = []
    for f in tracked_files(ref, repo):
        if not (f.startswith("app/") and f.endswith(".py") and f.count("/") >= 2):
            continue
        pkg = f.split("/")[1]
        if pkg not in allowed:
            continue
        src = _git(["show", f"{ref}:{f}"], repo) or ""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                parts = m.split(".")
                if len(parts) >= 2 and parts[0] == "app" and parts[1] != pkg:
                    if parts[1] not in allowed[pkg]:
                        out.append(
                            f"FORBIDDEN DEPENDENCY DIRECTION: {f} (app/{pkg}) imports "
                            f"app.{parts[1]}, which app/{pkg} may not depend on.")
    return sorted(set(out))


def _self_protection_violations(base: str, head: str, repo: Path = REPO) -> list[str]:
    """Deleting, disabling or unwiring this ratchet is itself a regression.

    Same contract `check_delta_adds_no_debt` applies to enforced checks: if the BASE ref had the
    protection and HEAD does not, refuse. Read from the base so a change cannot authorise the
    removal of its own gate in the same delta.
    """
    wf = ".github/workflows/hardening.yml"
    tool = "tools/repo_rehab_status.py"
    base_wf = _git(["show", f"{base}:{wf}"], repo) or ""
    head_wf = _git(["show", f"{head}:{wf}"], repo) or ""
    head_files = set(tracked_files(head, repo))
    out: list[str] = []
    if "repo_rehab_status.py" in base_wf and "repo_rehab_status.py" not in head_wf:
        out.append(
            f"REHAB RATCHET REMOVED FROM REQUIRED CI: {wf} invoked it at the base and does not "
            f"at HEAD. The gate is not optional; restore the step.")
    if "repo_rehab_status.py" in base_wf and tool not in head_files:
        out.append(f"REHAB RATCHET DELETED: {tool} is gone at HEAD while CI still requires it.")
    if "repo_rehab_status.py" in head_wf and "--ratchet" not in head_wf:
        out.append(
            f"REHAB RATCHET DEMOTED: {wf} runs {tool} without --ratchet, so it reports without "
            f"blocking. A gate that cannot fail is not a gate.")
    if "repo_rehab_status.py" in head_wf and "|| true" in _ratchet_step(head_wf):
        out.append(
            f"REHAB RATCHET DEMOTED: its step in {wf} swallows failure with `|| true`.")
    return out


def _ratchet_step(workflow_text: str) -> str:
    """The lines of the hardening workflow that mention this tool, for demotion checks."""
    return "\n".join(ln for ln in workflow_text.splitlines()
                     if "repo_rehab_status" in ln)


# ── report ────────────────────────────────────────────────────────────────────────────────
def _schematic(title: str, packages: list[str], extra: list[str]) -> str:
    lines = [f"{title}", "EdWebConsole/"]
    if packages:
        lines.append("  app/")
        lines += [f"    {p}/" for p in packages]
    lines += [f"  {e}" for e in extra]
    return "\n".join(lines)


def report(start_sha: str, base: str = "origin/main") -> str:
    cur = current(base)
    start = current(start_sha, with_loc=True)
    host = host_separation(baseline=start_sha, ref=base)

    metrics = [
        ("root production modules", "root_production_modules", 0),
        ("root production LOC", "root_production_loc", 0),
        ("server.py LOC", "server_py_loc", 0),
        ("app modules", "app_modules", None),
        ("app LOC", "app_loc", None),
        ("tools .py files", "tools_py", None),
        ("governance files", "governance_files", None),
        ("tracked runtime artifacts", "tracked_runtime_artifacts", 0),
        ("unmapped tracked files", "unmapped_tracked_files", 0),
    ]
    rows, better, worse = [], 0, 0
    for label, key, target in metrics:
        s, c = start[key], cur[key]
        d = c - s
        # app modules/LOC growing is progress; everything else shrinking is progress.
        good = d > 0 if key.startswith("app_") else d < 0
        if d:
            better, worse = better + (1 if good else 0), worse + (0 if good else 1)
        rows.append(f"  {label:<28} {s:>8} -> {c:<8} {d:+8d}   target "
                    f"{'—' if target is None else target}")
    verdict = "REGRESSED" if worse else ("IMPROVED" if better else "FLAT")

    out = ["=" * 78, "A. CURRENT SCHEMATIC (generated from the tree)", "=" * 78,
           _schematic("", cur["app_packages_present"],
                      [f"{d}/" for d in sorted(cur['unmapped_top_level_dirs'])]
                      + ["research/", "tests/", "tools/", "static/", "governance/",
                         f"<{cur['root_production_modules']} root .py modules, "
                         f"{cur['root_production_loc']} LOC>"]),
           "", "=" * 78,
           f"B. FIXED TARGET SCHEMATIC   sha256={TARGET_SHA256[:16]}", "=" * 78,
           _schematic("", TARGET["app_packages"],
                      [f"{d}/" for d in TARGET["source_top_level"] if d != "app"]),
           "  (host, outside source: " + ", ".join(TARGET["host_dirs_outside_source"]) + ")",
           "", "=" * 78,
           f"C. TODAY'S DELTA — merged main only ({start['ref']} -> {cur['ref']})", "=" * 78,
           *rows, "",
           f"  HOST SEPARATION: {host['state']}  "
           f"(dirs present: {sum(host['host_dirs_present'].values())}"
           f"/{len(host['host_dirs_present'])}, "
           f"tracked runtime in source: {host['tracked_runtime_in_source']})",
           "", f"  VERDICT: {verdict}", ""]
    if TARGET_OPEN_QUESTIONS:
        out += ["  TARGET QUESTIONS AWAITING THE OPERATOR (target unchanged):"]
        out += [f"    - {q}" for q in TARGET_OPEN_QUESTIONS]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratchet", action="store_true")
    ap.add_argument("--host", action="store_true")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--start-sha", default="334c5dafafa99316589bf74b39bb4ab540bbb1a5")
    a = ap.parse_args()

    if a.host:
        print(json.dumps(host_separation(), indent=2))
        return 0
    if a.ratchet:
        bad = ratchet(a.base, a.head)
        if bad:
            sys.stderr.write(
                "[FAIL] repo rehabilitation ratchet — this delta moves AWAY from the TARGET:\n\n"
                + "".join(f"  * {b}\n" for b in bad)
                + "\nInherited debt is allowed to remain. It is not allowed to grow.\n")
            return 1
        print("[PASS] repo rehabilitation ratchet: no new divergence from the TARGET.")
        return 0
    print(report(a.start_sha, a.base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
