"""CODE HEALTH PANEL — the standing static-quality scoreboard (RC-64).

WHY IT EXISTS. On 2026-07-26 the institutional gate reported ~3,000 advisory findings as a single
undifferentiated pile, and the operator reasonably read that as "3,000 problems". It is not. The
project's OWN ruff configuration flags 76 errors; the gate's wider net adds ~1,077 style rules the
project deliberately does not enable. And the SHAPE metrics must never be driven to zero — RC-19
recorded that chasing a file-length ceiling forced five circular imports to save seven lines.
Reporting those three populations as one number destroys the only decision the numbers support:
what to fix, what to watch, and what to leave alone.

THE TIERS (this is the triage, made permanent):
  BLOCKING  — the project's own ruff correctness rules (F-rules: unused vars, redefinitions,
              undefined names, duplicate dict keys). These are DEFECTS. Target: 0.
  TRACKED   — mypy types and orphan dict keys. Real debt, driven down incrementally. Rising is a
              regression; zero is the eventual goal.
  FROZEN    — complexity / function-length / file-length, plus the gate's wider ruff net. Watched
              for RUNAWAY growth only. Deliberately NOT driven to zero (RC-19). A rise here is a
              prompt to look, never an automatic failure.

Usage:
  python tools/code_health_panel.py            # print the panel
  python tools/code_health_panel.py --json     # machine-readable
  python tools/code_health_panel.py --check    # exit 1 if any BLOCKING finding exists
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: The project's own correctness selection — these are defects, not style opinions.
BLOCKING_RULES = "F"
#: Style families the project deliberately leaves off; counted for drift, never enforced.
WIDE_RULES = "F,E,W,SIM,ARG,B,PIE,RET,C4,UP"


def _py() -> str:
    """The .venv interpreter — the one the gate mandates, so counts match what it sees."""
    cand = _ROOT / ".venv" / "Scripts" / "python.exe"
    return str(cand) if cand.exists() else sys.executable


def _ruff_count(select: str) -> int | None:
    try:
        r = subprocess.run([_py(), "-m", "ruff", "check", ".", "--select", select,
                            "--output-format", "json"],
                           cwd=str(_ROOT), capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return len(json.loads(r.stdout or "[]"))
    except json.JSONDecodeError:
        return None            # absence reads as absence — never silently 0 (RC-57 class)


def _ruff_breakdown(select: str) -> dict[str, int]:
    try:
        r = subprocess.run([_py(), "-m", "ruff", "check", ".", "--select", select,
                            "--output-format", "json"],
                           cwd=str(_ROOT), capture_output=True, text=True, timeout=300)
        items = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}
    out: dict[str, int] = {}
    for it in items:
        code = it.get("code") or "?"
        out[code] = out.get(code, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _gate_metric(name: str) -> int | None:
    """Count from the institutional gate's own checker, so the panel cannot drift from it."""
    try:
        from tools import check_institutional_correctness as cic
    except ImportError:
        return None
    fn = dict((n, f) for n, f, _ in cic.CHECKS).get(name)
    if fn is None:
        return None
    try:
        return len(fn())
    except Exception:
        return None


def collect() -> dict:
    blocking = _ruff_count(BLOCKING_RULES)
    wide = _ruff_count(WIDE_RULES)
    return {
        "BLOCKING": {
            "ruff_project_correctness": blocking,
            "breakdown": _ruff_breakdown(BLOCKING_RULES),
            "target": 0,
            "meaning": "real defects by the project's OWN ruff config — fix these",
        },
        "TRACKED": {
            "mypy_types": _gate_metric("mypy_types"),
            "orphan_dict_keys": _gate_metric("orphan_dict_keys"),
            "meaning": "real debt, driven down incrementally; a RISE is a regression",
        },
        "FROZEN": {
            "ruff_wide_net": wide,
            "function_complexity": _gate_metric("function_complexity"),
            "function_length": _gate_metric("function_length"),
            "file_length": _gate_metric("file_length"),
            "meaning": "watched for runaway growth ONLY — never driven to zero (RC-19: a "
                       "file-length ceiling once forced five circular imports to save seven lines)",
        },
    }


def _provenance() -> str:
    """WHICH TREE these numbers describe (RC-140).

    mypy_types runs `mypy .` over the WORKING TREE, not HEAD — MEASURED 2026-07-29: adding a
    single untracked .py with one type error moved the count 759 -> 760. So two agents reading
    the panel minutes apart legitimately get different integers with neither being wrong, and
    three readings that evening (751 / 759 / 753) could not be reconciled because no reading
    said which tree it described. A bare integer is not a measurement; this line makes any two
    readings comparable, per RC-57 (a metric that cannot be trusted is worse than none).
    """
    def _git(*args: str) -> str:
        try:
            r = subprocess.run(["git", *args], cwd=str(_ROOT), capture_output=True,
                               text=True, timeout=20)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    head = _git("rev-parse", "--short", "HEAD") or "unknown"
    porcelain = [ln for ln in _git("status", "--porcelain").splitlines() if ln.strip()]
    dirty_py = [ln for ln in porcelain if ln.strip().endswith(".py")]
    return (f"tree: HEAD {head} · {len(dirty_py)} dirty/untracked .py "
            f"({len(porcelain)} paths total) · python {sys.version.split()[0]}")


def render(panel: dict) -> str:
    lines = ["", "=" * 72, "CODE HEALTH PANEL", _provenance(), "=" * 72]
    b = panel["BLOCKING"]
    n = b["ruff_project_correctness"]
    verdict = "UNKNOWN (ruff unavailable)" if n is None else ("CLEAN" if n == 0 else f"{n} DEFECT(S)")
    lines += [f"\nBLOCKING  (target 0)                        -> {verdict}",
              f"          {b['meaning']}"]
    for code, cnt in b["breakdown"].items():
        lines.append(f"            {code:6s} {cnt}")
    lines.append("\nTRACKED   (drive down; a rise is a regression)")
    for k, v in panel["TRACKED"].items():
        if k != "meaning":
            lines.append(f"            {k:26s} {'n/a' if v is None else v}")
    lines.append("\nFROZEN    (watch for runaway growth only — do NOT drive to zero)")
    for k, v in panel["FROZEN"].items():
        if k != "meaning":
            lines.append(f"            {k:26s} {'n/a' if v is None else v}")
    lines += ["", "=" * 72]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    panel = collect()
    if "--json" in argv:
        print(json.dumps(panel, indent=2))
    else:
        print(render(panel))
    if "--check" in argv:
        n = panel["BLOCKING"]["ruff_project_correctness"]
        if n is None:
            print("\n[FAIL] BLOCKING count unavailable — ruff missing in the mandated "
                  "interpreter. A metric that cannot be measured is NOT a pass (RC-57).")
            return 1
        if n > 0:
            print(f"\n[FAIL] {n} BLOCKING defect(s). These are the project's own correctness "
                  f"rules, not style opinions.")
            return 1
        print("\n[OK] No BLOCKING defects.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
