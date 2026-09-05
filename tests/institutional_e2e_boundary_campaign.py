"""RC-516 — EXECUTABLE-BOUNDARY CAMPAIGN for the institutional end-to-end law checks.

Not collected by pytest (no `test_` prefix): each case costs several minutes because it
walks the ACTUAL merge-enforcement path required Hardening uses —

    attack staged in a real worktree of THIS repository
      -> tools/check_delta_adds_no_debt.py --index --base <base sha>
        -> tools/check_institutional_correctness.py --enforced-only (subprocess, both sides)
          -> the registered enforced check
            -> the wrapper's process exit status

and asserts the exit status: non-zero for every attack, zero for every legitimate control.
Nothing is stubbed. The wrapper, the gate and the checks are the committed files of the
worktree under test.

Run (from the repository root, on the branch to be proven):

    .venv/Scripts/python.exe tests/institutional_e2e_boundary_campaign.py --out reports/e2e_boundary_campaign_latest.json

Each case: (1) a private worktree of HEAD is materialised; (2) when the case needs a BASE
that carries a duplicate or a superseded path, those files are committed with git plumbing
(write-tree / commit-tree — no hooks, no branch) and the worktree is moved onto that commit;
(3) the attack is written and STAGED; (4) the wrapper runs with `--index --base <base>`;
(5) the exit status and the wrapper's verdict lines are recorded. The worktree is removed
afterwards. Bases are shared across cases so the wrapper's base-side cache is reused.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

GEX = (
    "def compute_gex(rows, px):\n"
    "    total = 0.0\n    calls = 0.0\n    puts = 0.0\n"
    "    for r in rows:\n"
    "        w = r[\"gamma\"] * r[\"oi\"] * px * px * 0.01\n"
    "        if r[\"kind\"] == \"call\":\n            calls += w\n        else:\n            puts += w\n"
    "    total = calls - puts\n"
    "    return {\"total\": total, \"calls\": calls, \"puts\": puts}\n"
)
GEX_CHANGED = GEX.replace("    total = 0.0\n", "    if px <= 0:\n        raise ValueError(px)\n    total = 0.0\n")
OLD = (
    "def old_compute(rows, px):\n    acc = 0.0\n    n = 0\n    for r in rows:\n"
    "        acc += r[\"volume\"]\n        n += 1\n    if n == 0:\n        return 0.0\n    return acc / n\n"
)


def norm_body(name: str, variant: int) -> str:
    if variant == 0:
        return f"def {name}(x):\n    a = x + 1\n    b = a * 2\n    c = b - 3\n    d = c / 4\n    e = d + 5\n    return e\n"
    return f"def {name}(x):\n    a = x * 10\n    b = a - 1\n    c = b * 3\n    d = c + 4\n    e = d - 5\n    return e\n"


#: BASE SETUPS — files committed (by plumbing) on top of HEAD before the attack is staged.
#: The campaign packages live under `planes/` — an existing production package — so the base
#: itself is a legal tree for every law check.
BASE_DUP = {
    "planes/e2e_campaign/__init__.py": "",
    "planes/e2e_campaign/gex.py": GEX,
    "planes/e2e_campaign/api.py": "from planes.e2e_campaign.gex import compute_gex\n\n\ndef serve(rows, px):\n    return compute_gex(rows, px)\n",
    "planes/e2e_campaign/replay.py": GEX.replace("def compute_gex(", "def compute_gex_replay("),
}
BASE_SUPERSEDED = {
    "planes/e2e_campaign/__init__.py": "",
    "planes/e2e_campaign/gex.py": GEX,
    "planes/e2e_campaign/old_gex.py": OLD,
    "planes/e2e_campaign/legacy_api.py": "from planes.e2e_campaign.old_gex import old_compute\n\n\ndef serve_old(rows, px):\n    return old_compute(rows, px)\n",
}
BASE_COLLISION = {
    "planes/e2e_campaign/__init__.py": "",
    "planes/e2e_campaign/gex.py": GEX,
    "planes/e2e_campaign/norm_a.py": norm_body("normalize", 0),
    "planes/e2e_campaign/norm_b.py": norm_body("normalize", 1),
    "planes/e2e_campaign/call_a.py": "from planes.e2e_campaign.norm_a import normalize\n\n\ndef via_a(x):\n    return normalize(x)\n",
    "planes/e2e_campaign/call_b.py": "import planes.e2e_campaign.norm_b as m\n\n\ndef via_b(x):\n    return m.normalize(x)\n",
}

CASES: list[dict] = [
    {"id": "A1_changed_canonical_duplicate_left_behind", "expect": "FAIL", "base": "dup",
     "check": "changed_computation_leaves_no_twin",
     "stage": {"planes/e2e_campaign/gex.py": GEX_CHANGED}},
    {"id": "A2_superseded_path_left_callable", "expect": "FAIL", "base": "superseded",
     "check": "no_superseded_path_survives",
     "stage": {"planes/e2e_campaign/legacy_api.py":
               "from planes.e2e_campaign.gex import compute_gex\n\n\ndef serve_old(rows, px):\n    return compute_gex(rows, px)\n"}},
    {"id": "A3_parent_closed_over_not_proven", "expect": "FAIL", "base": "head",
     "check": "institutional_closure_ledger", "ledger_mutation": "close_over_not_proven"},
    {"id": "A4_deleted_enforcement_claimed_proven", "expect": "FAIL", "base": "head",
     "check": "institutional_closure_ledger", "ledger_mutation": "cite_deleted_mechanism"},
    {"id": "A5_new_root_production_module", "expect": "FAIL", "base": "head",
     "check": "no_new_root_production_module",
     "stage": {"e2e_campaign_root_helper.py": "def helper():\n    return 1\n"}},
    {"id": "A6_same_name_collision_replaced_while_survivor_used", "expect": "FAIL", "base": "collision",
     "check": "no_superseded_path_survives",
     "stage": {"planes/e2e_campaign/call_a.py":
               "from planes.e2e_campaign.gex import compute_gex\n\n\ndef via_a(x):\n    return compute_gex([], x)\n"}},
    {"id": "C1_legitimate_consumer", "expect": "PASS", "base": "dup",
     "stage": {"planes/e2e_campaign/report.py":
               "from planes.e2e_campaign.gex import compute_gex\n\n\ndef report(rows, px):\n"
               "    g = compute_gex(rows, px)\n    lines = []\n    lines.append(str(g['total']))\n"
               "    lines.append(str(g['calls']))\n    lines.append(str(g['puts']))\n    return '\\n'.join(lines)\n"}},
    {"id": "C2_root_fix_duplicate_removed_consumers_rewired", "expect": "PASS", "base": "dup",
     "stage": {"planes/e2e_campaign/gex.py": GEX_CHANGED,
               "planes/e2e_campaign/replay.py":
               "from planes.e2e_campaign.gex import compute_gex\n\n\ndef replay(rows, px):\n    return compute_gex(rows, px)\n"}},
    {"id": "C3_collision_survivor_not_condemned_when_other_removed_properly", "expect": "PASS", "base": "collision",
     "stage": {"planes/e2e_campaign/call_a.py":
               "from planes.e2e_campaign.gex import compute_gex\n\n\ndef via_a(x):\n    return compute_gex([], x)\n",
               "planes/e2e_campaign/norm_a.py": None}},
]


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="e2e-campaign", GIT_AUTHOR_EMAIL="e2e@local",
               GIT_COMMITTER_NAME="e2e-campaign", GIT_COMMITTER_EMAIL="e2e@local")
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {p.stderr[-400:]}")
    return p.stdout


def _write(root: Path, rel: str, text: str | None) -> None:
    p = root / rel
    if text is None:
        _git(root, "rm", "-q", "-f", rel)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    _git(root, "add", rel)


def _plumbing_commit(wt: Path, parent: str, message: str) -> str:
    """A commit from the current INDEX with no hooks and no branch (write-tree/commit-tree)."""
    tree = _git(wt, "write-tree").strip()
    return _git(wt, "commit-tree", tree, "-p", parent, "-m", message).strip()


def _mutate_ledger(wt: Path, how: str) -> None:
    path = wt / "governance" / "INSTITUTIONAL_CLOSURE_SCHEMA.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    lane = next(r for r in doc["lanes"] if r["lane"] == "ECON-01")
    if how == "close_over_not_proven":
        lane["status"] = "CLOSED_WITH_EVIDENCE"          # over END_TO_END_CORRECTNESS=NOT_PROVEN
    elif how == "cite_deleted_mechanism":
        lane["evidence"] = {"engine": "tools/check_universal_fix_impact_gate.py"}   # deleted in 41360574
        lane["dimensions"]["MECHANICAL_ENFORCEMENT"] = "PROVEN"
    else:
        raise ValueError(how)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    _git(wt, "add", "governance/INSTITUTIONAL_CLOSURE_SCHEMA.json")


_SIDE_RE = re.compile(r"^(base \S+|staged INDEX) \((?P<sha>[0-9a-f]+)\): (?P<rest>.*)$")


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_case(wt: Path, head: str, bases: dict[str, str], case: dict) -> dict:
    """One case through the real boundary. Every field the record needs is captured here so a
    later crash cannot destroy completed proof (the caller flushes it immediately)."""
    base_key = case["base"]
    base_sha = bases[base_key]
    _git(wt, "checkout", "-q", "-f", base_sha)
    _git(wt, "clean", "-qfd", "--", "planes/e2e_campaign", ".")
    for rel, text in (case.get("stage") or {}).items():
        _write(wt, rel, text)
    if case.get("ledger_mutation"):
        _mutate_ledger(wt, case["ledger_mutation"])
    started = _utc()
    t0 = time.time()
    proc = subprocess.run([sys.executable, "tools/check_delta_adds_no_debt.py", "--index", "--base", base_sha],
                          cwd=str(wt), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    lines = out.splitlines()
    base_line = next((ln for ln in lines if ln.startswith("base ") and "(" in ln), "")
    cand_line = next((ln for ln in lines if ln.startswith("staged INDEX")), "")
    base_cached = any(ln.startswith("base side: cache hit") for ln in lines)
    m = _SIDE_RE.match(cand_line)
    candidate_sha = m.group("sha") if m else ""
    verdict_lines = [ln for ln in lines if ln.startswith(("[PASS]", "[FAIL]")) or ln.strip().startswith(case.get("check", "\x00"))]
    got = "PASS" if proc.returncode == 0 else "FAIL"
    delta_lines = [ln.strip() for ln in lines if re.match(r"^\s+[a-z_0-9]+: \d+ -> \d+", ln)]
    named = case.get("check") is None or any(ln.startswith(case["check"] + ":") for ln in delta_lines)
    return {
        "id": case["id"], "expect": case["expect"], "expected_violation": case.get("check"),
        "base_sha": base_sha, "candidate_sha": candidate_sha,
        "started_utc": started, "ended_utc": _utc(), "seconds": round(time.time() - t0, 1),
        "base_gate_result": base_line, "base_side_cached": base_cached,
        "candidate_gate_result": cand_line, "delta_lines": delta_lines,
        "exit_code": proc.returncode, "got": got,
        "failed_for_the_correct_reason": (got == "FAIL" and named) if case["expect"] == "FAIL" else None,
        "ok": got == case["expect"] and (named or case["expect"] == "PASS"),
        "verdict": verdict_lines[-6:],
    }


def preflight(out_path: Path | None) -> list[str]:
    """Environment proof BEFORE the expensive part: nothing here changes what is measured.
    Returns the problems found; an empty list means go."""
    problems: list[str] = []
    for mod in ("tools.check_institutional_correctness", "tools.check_one_producer",
                "tools.check_institutional_closure_gate"):
        try:
            __import__(mod)
        except Exception as exc:  # noqa: BLE001 - the point is to name the import failure
            problems.append(f"{mod} does not import: {type(exc).__name__}: {exc}")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # the gate prints em dashes
    except (AttributeError, ValueError) as exc:
        problems.append(f"stdout cannot be made utf-8 safe: {exc}")
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            probe = out_path.parent / (out_path.name + ".probe")
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            problems.append(f"result path not writable: {exc}")
    probe_wt = Path(tempfile.mkdtemp(prefix="e2e-preflight-")) / "wt"
    try:
        _git(REPO, "worktree", "add", "--detach", "-q", str(probe_wt), "HEAD")
        _git(REPO, "worktree", "remove", "--force", str(probe_wt))
    except RuntimeError as exc:
        problems.append(f"cannot materialise a worktree: {exc}")
    finally:
        shutil.rmtree(probe_wt.parent, ignore_errors=True)
    if os.name == "nt":
        listing = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace").stdout.lower()
        busy = [name for name in ("node.exe", "playwright") if name in listing]
        if busy:
            problems.append(f"competing workload running (the campaign owns the machine): {busy}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None, help="JSON results path (scratch or reports/)")
    ap.add_argument("--only", action="append", default=[], help="case id prefix filter")
    ap.add_argument("--base-group", action="append", default=[],
                    help="run only cases on these base keys (head/dup/superseded/collision); "
                         "the groups are independent, so four processes with one group each "
                         "finish in the time of the longest group")
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args(argv)
    out_path = Path(args.out) if args.out else None
    if not args.skip_preflight:
        problems = preflight(out_path)
        if problems:
            for p in problems:
                print("PREFLIGHT: " + p, flush=True)
            print("campaign NOT STARTED: fix the environment first (nothing was measured)", flush=True)
            return 2
    head = _git(REPO, "rev-parse", "HEAD").strip()
    jsonl = out_path.with_suffix(".jsonl") if out_path else None   # flushed per case
    tmp = Path(tempfile.mkdtemp(prefix="e2e-campaign-"))
    wt = tmp / "wt"
    _git(REPO, "worktree", "add", "--detach", "-q", str(wt), head)
    results: list[dict] = []
    wall0 = time.time()
    try:
        wanted = [c for c in CASES
                  if (not args.only or any(c["id"].startswith(p) for p in args.only))
                  and (not args.base_group or c["base"] in args.base_group)]
        bases = {"head": head}
        for key, files in (("dup", BASE_DUP), ("superseded", BASE_SUPERSEDED), ("collision", BASE_COLLISION)):
            if not any(c["base"] == key for c in wanted):
                continue
            _git(wt, "checkout", "-q", "-f", head)
            _git(wt, "clean", "-qfd")
            for rel, text in files.items():
                _write(wt, rel, text)
            bases[key] = _plumbing_commit(wt, head, f"e2e campaign base: {key}")
        for case in wanted:
            r = run_case(wt, head, bases, case)
            results.append(r)
            if jsonl is not None:   # completed proof survives any later crash
                with jsonl.open("a", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps({"head": head, **r}) + "\n")
            print(f"{'ok ' if r['ok'] else 'BAD'} {r['id']}: expect {r['expect']} got {r['got']} "
                  f"(exit {r['exit_code']}, {r['seconds']}s, base "
                  f"{'cached' if r['base_side_cached'] else 'measured'})", flush=True)
            for ln in r["verdict"]:
                print("      " + ln[:160], flush=True)
    finally:
        _git(REPO, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    candidates = len(results)
    bases_measured = sum(1 for r in results if not r["base_side_cached"])
    perf = {
        "real_gate_executions": candidates + bases_measured,
        "candidate_executions": candidates,
        "base_executions_measured": bases_measured,
        "base_executions_avoided_by_cache": candidates - bases_measured,
        "max_concurrency_in_this_process": 1,
        "per_case_seconds": {r["id"]: r["seconds"] for r in results},
        "proof_work_seconds": round(sum(r["seconds"] for r in results), 1),
        "wall_clock_seconds": round(time.time() - wall0, 1),
    }
    payload = {"head": head, "cases": results, "all_ok": all(r["ok"] for r in results), "performance": perf}
    if out_path is not None:
        out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"campaign {'PASS' if payload['all_ok'] else 'FAIL'}: {sum(r['ok'] for r in results)}/{len(results)} "
          f"cases as expected at {head[:12]}; {perf['real_gate_executions']} real gate executions "
          f"({perf['base_executions_avoided_by_cache']} base runs avoided by cache), "
          f"wall {perf['wall_clock_seconds']}s", flush=True)
    return 0 if payload["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
