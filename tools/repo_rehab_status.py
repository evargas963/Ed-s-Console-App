"""REPO REHABILITATION — CURRENT / TARGET / DELTA, generated from facts, plus the ratchet.

WHY ONE FILE. The mission asks for a status generator AND a no-regression ratchet. They are the
same computation asked twice: the ratchet is "measure CURRENT at two refs and refuse the ones
that got worse". Splitting them would create two producers of "what does this repo look like",
which is the duplicate-authority defect the rehabilitation exists to remove. No new registry, no
new governance surface, no report archive: the daily job prints to the job summary.

WHAT IS MEASURED. Structural facts only, read from a git tree — module placement, tracked
runtime artifacts, directory ownership, import direction. Institutional debt is NOT recomputed
here: `tools/check_delta_adds_no_debt.py` already owns that question and already runs in
Hardening, so this defers to it rather than growing a second opinion.

USAGE
    python tools/repo_rehab_status.py                      # CURRENT / TARGET / DELTA
    python tools/repo_rehab_status.py --ratchet --base origin/main   # no-regression gate
    python tools/repo_rehab_status.py --host               # host separation (local only)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: The rehabilitation's fixed origin. Re-anchored to the merge of PR #218 when this work was
#: rebased onto it, so cumulative progress is measured from the tree the plan actually starts on.
START_SHA = "e3a7071419dff0ce08b3cc235925eeb7a0c13278"

# ── THE TARGET — FIXED AND HASH-PINNED ────────────────────────────────────────────────────
#: Pinned so the score cannot be improved by redefining what "done" means. Two protections, and
#: the second exists because the first is not enough: `tests/test_repo_rehab_ratchet_v1.py`
#: asserts the digest, AND the ratchet re-derives the BASE ref's TARGET and refuses any change —
#: a delta that edited the target, the pin and the test together would satisfy every test it
#: shipped with and still be moving its own goalposts.
#:
#: OPERATOR RULING 2026-09-02: `app/models` is KEPT (the earlier recommendation to rename it
#: `app/ml` is rejected); `docs/` is added to source. Every other legacy top-level directory is
#: dispositioned below — none is left unexplained, because "unexplained difference = NONE" is
#: the goal and a directory with no stated destination can never reach it.
TARGET: dict = {
    "app_packages": [
        "api", "domain", "market_data", "options", "signals", "models", "decision",
        "infrastructure",
    ],
    "source_top_level": [
        "app", "research", "tests", "tools", "static", "config", "governance", "docs",
    ],
    "root_production_modules": 0,
    "tracked_runtime_artifacts": 0,
    #: Where each legacy top-level directory GOES. "<host>" means it leaves source entirely.
    "legacy_disposition": {
        "reports": "<host>/artifacts",
        "models": "<host>/artifacts",
        "backups": "<host>/recovery",
        "data": "<host>/runtime",
        "calibration": "app/models",
        "features": "app/signals",
        "arch_competition": "research",
        "v2_decision": "app/decision",
        "verification": "tools",
        "planes": "app/domain",
        "schwab_field_inventory": "app/market_data",
        "snapshot_sql": "app/infrastructure",
        "scripts": "tools",
    },
    #: Ed Console-specific host paths, relative to the directory ABOVE the source checkout.
    "host_paths": [
        "runtime/EdWebConsole", "recovery/EdWebConsole", "artifacts/EdWebConsole", "worktrees",
    ],
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


def _digest(target: dict) -> str:
    return hashlib.sha256(
        json.dumps(target, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


TARGET_SHA256 = _digest(TARGET)

#: Extensions that are runtime/generated state, never source.
RUNTIME_EXT = frozenset({".db", ".sqlite", ".sqlite3", ".log", ".pkl", ".joblib", ".h5",
                         ".pt", ".onnx", ".parquet", ".bin", ".ckpt"})


def _legacy_dirs() -> frozenset[str]:
    return frozenset(TARGET["legacy_disposition"])


def _allowed_top_level() -> frozenset[str]:
    """Directories a tree may contain: TARGET source, plus legacy ones still being drained."""
    return frozenset(TARGET["source_top_level"]) | _legacy_dirs()


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


def top_level_dirs(files: list[str]) -> set[str]:
    return {f.split("/")[0] for f in files if "/" in f and not f.startswith(".")}


def current(ref: str = "HEAD", repo: Path = REPO, with_loc: bool = True) -> dict:
    """CURRENT, generated from the tree at `ref`. No hand-entered status anywhere."""
    files = tracked_files(ref, repo)
    root_py = sorted(f for f in files if "/" not in f and f.endswith(".py"))
    app_py = sorted(f for f in files if f.startswith("app/") and f.endswith(".py"))
    runtime = sorted(f for f in files if os.path.splitext(f)[1].lower() in RUNTIME_EXT)
    tops = top_level_dirs(files)
    legacy_present = sorted(tops & _legacy_dirs())
    legacy_files = sorted(f for f in files if f.split("/")[0] in _legacy_dirs() and "/" in f)
    unknown = sorted(tops - _allowed_top_level())
    gov = sorted(f for f in files if f.startswith("governance/"))
    return {
        "ref": (_git(["rev-parse", "--short", ref], repo) or ref).strip(),
        "tracked_files": len(files),
        "root_production_modules": len(root_py),
        "root_production_loc": sum(_blob_lines(ref, f, repo) for f in root_py) if with_loc else -1,
        "server_py_loc": _blob_lines(ref, "server.py", repo) if with_loc else -1,
        "app_modules": len(app_py),
        "app_loc": sum(_blob_lines(ref, f, repo) for f in app_py) if with_loc else -1,
        "app_packages_present": sorted({f.split("/")[1] for f in app_py if f.count("/") >= 2}),
        "tools_py": len([f for f in files if f.startswith("tools/") and f.endswith(".py")]),
        "governance_files": len(gov),
        "tracked_runtime_artifacts": len(runtime),
        "legacy_dirs_present": legacy_present,
        "legacy_tracked_files": len(legacy_files),
        "unknown_top_level_dirs": unknown,
        "_root_py_names": root_py,
        "_app_py_names": app_py,
        "_runtime_names": runtime,
        "_top_level": sorted(tops),
    }


# ── host separation ───────────────────────────────────────────────────────────────────────
def _in_ci() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


def host_separation(root: Path | None = None, baseline: str | None = None,
                    ref: str = "HEAD", force_local: bool = False) -> dict:
    """Is Ed Console's runtime/recovery/artifacts/worktree state OUTSIDE the source checkout?

    NOT_PROVEN_FROM_CI is the honest answer in CI. A CI runner clones the repository into an
    ephemeral path with no host layout around it, so any SEPARATED/VIOLATED verdict there would
    describe the runner, not the operator's machine — a measurement of the wrong subject read as
    a measurement of the right one.

    Locally the check is Ed Console-SPECIFIC: it looks for this console's own external paths
    (`runtime/EdWebConsole`, `recovery/EdWebConsole`, `artifacts/EdWebConsole`, `worktrees`)
    beside the checkout, not for generic directory names that some other project might own.

      NOT_PROVEN_FROM_CI  running in CI; the host is not observable from here
      SEPARATED           all four host paths exist and no runtime state is tracked in source
      NOT_YET_SEPARATED   inherited runtime state still in source, not growing — the baseline
      VIOLATED            runtime state is being RE-CREATED inside source (above baseline)
    """
    src = (root or REPO).resolve()
    if _in_ci() and not force_local:
        return {"state": "NOT_PROVEN_FROM_CI", "host_root": None, "host_paths_present": {},
                "tracked_runtime_in_source": None, "baseline_runtime_in_source": None,
                "why": "a CI runner has no host layout; the operator's machine is the subject"}
    host = src.parent
    present = {p: (host / p).is_dir() for p in TARGET["host_paths"]}
    contaminating = sorted(f for f in tracked_files(ref, src)
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
    return {"state": state, "host_root": str(host), "host_paths_present": present,
            "tracked_runtime_in_source": len(contaminating),
            "baseline_runtime_in_source": base_n, "sample": contaminating[:5]}


# ── the ratchet ───────────────────────────────────────────────────────────────────────────
def _target_at(ref: str, repo: Path = REPO) -> dict | None:
    """The TARGET literal as it exists at `ref`, parsed without executing that revision."""
    src = _git(["show", f"{ref}:tools/repo_rehab_status.py"], repo)
    if not src:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "TARGET" and node.value is not None:
            try:
                return ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                return None
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "TARGET" for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                return None
    return None


def ratchet(base: str = "origin/main", head: str = "HEAD", repo: Path = REPO) -> list[str]:
    """Refuse NEW divergence from the TARGET. Inherited debt may stay; it may not grow.

    Deliberately NOT a debt checker: `check_delta_adds_no_debt` already owns institutional
    violations. This adds only the architecture predicates nothing else measures.
    """
    b, h = current(base, repo, with_loc=False), current(head, repo, with_loc=False)
    out: list[str] = []

    out.extend(_target_drift_violations(base, head, repo))

    new_root = sorted(set(h["_root_py_names"]) - set(b["_root_py_names"]))
    if new_root:
        out.append(
            f"NEW ROOT PRODUCTION MODULE(S): {', '.join(new_root)}. The TARGET has none; new "
            f"code belongs in app/<package>/. Inherited root modules may stay — this refuses "
            f"ADDING to them.")

    # Reintroduced root ownership: the same module owned in BOTH places at HEAD.
    app_stems = {Path(f).stem for f in h["_app_py_names"]}
    dupes = sorted(app_stems & {Path(f).stem for f in h["_root_py_names"]})
    if dupes:
        out.append(
            f"ROOT OWNERSHIP REINTRODUCED: {', '.join(dupes)} exists under app/ AND at the repo "
            f"root at HEAD. One module, two owners, is the duplicate authority this "
            f"rehabilitation removes — delete the root copy or finish the move.")

    base_app_stems = {Path(f).stem for f in b["_app_py_names"]}
    regressed = sorted(base_app_stems & {Path(f).stem for f in h["_root_py_names"]} - app_stems)
    if regressed:
        out.append(
            f"MIGRATED CODE MOVED BACK TOWARD ROOT: {', '.join(regressed)} was under app/ at the "
            f"base and is at the repo root at HEAD. Migration is one-way.")

    new_rt = sorted(set(h["_runtime_names"]) - set(b["_runtime_names"]))
    if new_rt:
        out.append(
            f"NEW TRACKED RUNTIME/GENERATED STATE: {', '.join(new_rt[:6])}"
            f"{' ...' if len(new_rt) > 6 else ''}. Runtime, DB, backup, log and trained-model "
            f"state lives outside source — see the TARGET host paths.")

    # DYNAMIC: any top-level directory the TARGET neither names nor dispositions.
    new_unknown = sorted(set(h["unknown_top_level_dirs"]) - set(b["unknown_top_level_dirs"]))
    if new_unknown:
        out.append(
            f"NEW NON-TARGET TOP-LEVEL DIRECTORY: {', '.join(new_unknown)}. Every top-level "
            f"directory is either TARGET source ({', '.join(TARGET['source_top_level'])}) or a "
            f"legacy directory with a stated disposition. A new one is a new unexplained "
            f"difference, which is what this rehabilitation is closing.")

    if h["legacy_tracked_files"] > b["legacy_tracked_files"]:
        out.append(
            f"LEGACY-DIRECTORY GROWTH: {b['legacy_tracked_files']} -> "
            f"{h['legacy_tracked_files']} tracked files in directories awaiting disposition. "
            f"They may only shrink.")

    out.extend(_dependency_direction_violations(head, repo))
    out.extend(_self_protection_violations(base, head, repo))
    return out


def _target_drift_violations(base: str, head: str, repo: Path = REPO) -> list[str]:
    """The TARGET may not move to flatter the score — checked BASE against HEAD.

    The digest pin in the test suite is necessary and NOT sufficient: a single delta can edit
    the target, update the pin and update the test together, and every test it ships with will
    pass. Only a comparison against the base ref can see that, and reading the base is what
    makes it impossible for a change to authorise its own goalpost move.
    """
    base_target = _target_at(base, repo)
    if base_target is None:
        return []                      # the tool does not exist at the base: first landing
    head_target = _target_at(head, repo)
    if head_target is None:
        return ["TARGET UNREADABLE AT HEAD: tools/repo_rehab_status.py no longer defines a "
                "literal TARGET, so drift cannot be measured. Unmeasurable is not compliant."]
    if _digest(base_target) == _digest(head_target):
        return []
    changed = sorted(
        k for k in set(base_target) | set(head_target)
        if base_target.get(k) != head_target.get(k))
    return [
        f"TARGET DRIFT: the fixed target changed in this delta (fields: {', '.join(changed)}). "
        f"base sha256={_digest(base_target)[:16]} head sha256={_digest(head_target)[:16]}. The "
        f"target is the operator's, and a rehabilitation that can redefine 'done' measures "
        f"nothing. Land the target change as its own reviewed decision."]


def _dependency_direction_violations(ref: str, repo: Path = REPO) -> list[str]:
    """Once app/<pkg> exists, it may only import the packages the TARGET allows it to."""
    allowed = TARGET["dependency_direction"]
    out: list[str] = []
    for f in tracked_files(ref, repo):
        if not (f.startswith("app/") and f.endswith(".py") and f.count("/") >= 2):
            continue
        pkg = f.split("/")[1]
        if pkg not in allowed:
            continue
        try:
            tree = ast.parse(_git(["show", f"{ref}:{f}"], repo) or "")
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
                if len(parts) >= 2 and parts[0] == "app" and parts[1] != pkg \
                        and parts[1] not in allowed[pkg]:
                    out.append(
                        f"FORBIDDEN DEPENDENCY DIRECTION: {f} (app/{pkg}) imports "
                        f"app.{parts[1]}, which app/{pkg} may not depend on.")
    return sorted(set(out))


def _self_protection_violations(base: str, head: str, repo: Path = REPO) -> list[str]:
    """Deleting, disabling or unwiring this ratchet is itself a regression.

    Same contract `check_delta_adds_no_debt` applies to enforced checks: if the BASE ref had the
    protection and HEAD does not, refuse — read from the base so a change cannot authorise the
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
    step = "\n".join(ln for ln in head_wf.splitlines() if "repo_rehab_status" in ln)
    if "repo_rehab_status.py" in head_wf and "--ratchet" not in step:
        out.append(
            f"REHAB RATCHET DEMOTED: {wf} runs {tool} without --ratchet, so it reports without "
            f"blocking. A gate that cannot fail is not a gate.")
    if "repo_rehab_status.py" in head_wf and "|| true" in step:
        out.append(f"REHAB RATCHET DEMOTED: its step in {wf} swallows failure with `|| true`.")
    return out


# ── report ────────────────────────────────────────────────────────────────────────────────
def prior_daily_point(ref: str = "origin/main", hours: int = 24, repo: Path = REPO) -> str:
    """The merged point this report's DAILY delta is measured FROM.

    A git fact, not stored state: the last commit on the trunk older than `hours`. No report
    archive is needed to know where yesterday was, and none is written.
    """
    out = _git(["rev-list", "-1", f"--before={hours}.hours.ago", ref], repo)
    return (out or "").strip() or ref


_METRICS = [
    ("root production modules", "root_production_modules", 0),
    ("root production LOC", "root_production_loc", 0),
    ("server.py LOC", "server_py_loc", 0),
    ("app modules", "app_modules", None),
    ("app LOC", "app_loc", None),
    ("tools .py files", "tools_py", None),
    ("governance files", "governance_files", None),
    ("tracked runtime artifacts", "tracked_runtime_artifacts", 0),
    ("legacy tracked files", "legacy_tracked_files", 0),
]


def _delta_block(title: str, a: dict, b: dict) -> tuple[list[str], str]:
    rows, better, worse = [], 0, 0
    for label, key, target in _METRICS:
        s, c = a[key], b[key]
        d = c - s
        good = d > 0 if key.startswith("app_") else d < 0
        if d:
            better, worse = better + (1 if good else 0), worse + (0 if good else 1)
        rows.append(f"  {label:<28} {s:>8} -> {c:<8} {d:+8d}   target "
                    f"{'—' if target is None else target}")
    verdict = "REGRESSED" if worse else ("IMPROVED" if better else "FLAT")
    return ([title, *rows, f"  VERDICT: {verdict}"], verdict)


def report(start_sha: str = START_SHA, base: str = "origin/main") -> str:
    cur = current(base)
    start = current(start_sha)
    prior = prior_daily_point(base)
    yday = current(prior)
    host = host_separation(baseline=start_sha, ref=base)

    daily, _ = _delta_block(
        f"C. TODAY'S DELTA — prior merged point {yday['ref']} -> {cur['ref']}", yday, cur)
    cumulative, _ = _delta_block(
        f"D. CUMULATIVE — START_SHA {start['ref']} -> {cur['ref']}", start, cur)

    out = ["=" * 78, "A. CURRENT SCHEMATIC (generated from the tree)", "=" * 78, "EdWebConsole/"]
    if cur["app_packages_present"]:
        out += ["  app/"] + [f"    {p}/" for p in cur["app_packages_present"]]
    out += [f"  {d}/" for d in sorted(set(cur["_top_level"]))]
    out += [f"  <{cur['root_production_modules']} root .py modules, "
            f"{cur['root_production_loc']} LOC>"]
    if cur["unknown_top_level_dirs"]:
        out += [f"  !! UNDISPOSITIONED: {', '.join(cur['unknown_top_level_dirs'])}"]

    out += ["", "=" * 78, f"B. FIXED TARGET SCHEMATIC   sha256={TARGET_SHA256[:16]}", "=" * 78,
            "EdWebConsole/", "  app/"]
    out += [f"    {p}/" for p in TARGET["app_packages"]]
    out += [f"  {d}/" for d in TARGET["source_top_level"] if d != "app"]
    out += ["  (host, outside source: " + ", ".join(TARGET["host_paths"]) + ")",
            "  legacy dispositions:"]
    out += [f"    {k:<24} -> {v}" for k, v in sorted(TARGET["legacy_disposition"].items())]

    out += ["", "=" * 78] + daily + ["", "=" * 78] + cumulative
    out += ["", f"  HOST SEPARATION: {host['state']}"]
    if host["state"] == "NOT_PROVEN_FROM_CI":
        out += [f"    ({host['why']}; run locally for a verdict)"]
    else:
        out += [f"    host paths present "
                f"{sum(host['host_paths_present'].values())}/{len(host['host_paths_present'])}, "
                f"tracked runtime in source {host['tracked_runtime_in_source']} "
                f"(baseline {host['baseline_runtime_in_source']})"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratchet", action="store_true")
    ap.add_argument("--host", action="store_true")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--start-sha", default=START_SHA)
    a = ap.parse_args()

    if a.host:
        print(json.dumps(host_separation(baseline=a.start_sha), indent=2))
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
