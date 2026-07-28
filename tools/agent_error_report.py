"""AGENT ERROR REPORT — what I got wrong, and which lock did or did not catch it (RC-92).

OPERATOR MANDATE 2026-07-27: a report of agent errors — coding errors, false claims, failures to
obey the mechanical locks — delivered at end of day or ad hoc, "to then figure out what mechanical
locks you need in order to produce a pristine, error free, patch free, dead code free repo."

THE POINT IS THE THIRD COLUMN. Listing mistakes is confession, which changes nothing. What changes
something is `caught_by`: an error caught by a LOCK is a solved class; an error caught by the
OPERATOR is an unsolved class with a human standing in for a machine. This report ranks by that,
because the operator-caught rows ARE the backlog of locks to build.

  python tools/agent_error_report.py             # full report
  python tools/agent_error_report.py --today     # rows from today only
  python tools/agent_error_report.py --locks     # just the enforcement inventory
  python tools/agent_error_report.py --json

Reads governance/agent_error_log.md. A row with `caught_by=NOTHING` or `OPERATOR` and an empty
`lock_that_should_exist` is itself a finding: the error was not converted into a control.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LOG = REPO / "governance" / "agent_error_log.md"


def read_errors() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not re.match(r"\|\s*E-\d+\s*\|", line):
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) < 7:
            continue
        out.append({"id": c[0], "date": c[1], "class": c[2], "what": c[3],
                    "caught_by": c[4], "lock_needed": c[5], "status": c[6]})
    return out


def enforcement_inventory() -> dict:
    """Every lock actually wired, read from the files that wire it — never from memory."""
    inv: dict = {}

    # 1. Claude Code hooks — the only locks that fire BEFORE/AROUND an action.
    hooks = []
    try:
        cfg = json.loads((REPO / ".claude" / "settings.json").read_text(encoding="utf-8"))
        for event, groups in (cfg.get("hooks") or {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    hooks.append(f"{event}({g.get('matcher', '*')}): {h.get('command', '')}")
    except Exception as e:
        hooks.append(f"UNMEASURABLE: {type(e).__name__}: {e}")
    inv["claude_hooks"] = hooks

    # 2. pre-commit stages — fire at commit, after the work is written.
    pc = []
    try:
        y = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        pc = [f"{m.group(1)} — {m.group(2).strip()}"
              for m in re.finditer(r"- id: (\S+)\n\s+name: ([^\n]+)", y)]
    except Exception as e:
        pc.append(f"UNMEASURABLE: {type(e).__name__}: {e}")
    inv["pre_commit"] = pc

    # 3. Institutional checks, with live counts. A check that CRASHES is a finding.
    try:
        import tools.check_institutional_correctness as C
        enforced, advisory, crashed = {}, {}, {}
        for name, fn, is_enf in C.CHECKS:
            try:
                n = len(fn())
            except Exception as e:
                crashed[name] = f"{type(e).__name__}: {e}"
                continue
            (enforced if is_enf else advisory)[name] = n
        inv["institutional_enforced"] = enforced
        inv["institutional_advisory"] = advisory
        inv["institutional_crashed"] = crashed
    except Exception as e:
        inv["institutional_enforced"] = {"UNMEASURABLE": f"{type(e).__name__}: {e}"}

    # 4. Standalone checkers not wired into the gate — present but not enforcing.
    wired = " ".join(pc)
    standalone = [p.name for p in sorted((REPO / "tools").glob("check_*.py"))
                  if p.stem.replace("check_", "").replace("_", "-") not in wired
                  and p.name not in ("check_institutional_correctness.py",)]
    inv["standalone_checkers_not_in_precommit"] = standalone
    return inv


def render(errors: list[dict], inv: dict, brief: bool = False) -> str:
    L = ["", "=" * 78, "AGENT ERROR REPORT", "=" * 78, ""]
    if not errors:
        L += ["No rows in governance/agent_error_log.md.",
              "An empty error log after a working session is itself suspicious.", ""]
    else:
        # Normalise the catcher to its CATEGORY. "SELF (negative control)" and "SELF (DOM probe)"
        # are the same fact — I caught it — and splitting them into separate buckets shrinks the
        # only comparison that matters, machine-caught versus human-caught. The specific
        # instrument stays visible in the per-row listing below.
        def _catcher(v: str) -> str:
            v = v.strip().upper()
            for key in ("OPERATOR", "NOTHING", "LOCK", "SELF"):
                if v.startswith(key):
                    return key
            return v.split(":")[0].split("(")[0].strip() or "UNKNOWN"

        by_catcher = Counter(_catcher(e["caught_by"]) for e in errors)
        by_class = Counter(e["class"] for e in errors)
        total = len(errors)
        op = by_catcher.get("OPERATOR", 0)
        L += [f"TOTAL ERRORS LOGGED: {total}", ""]
        L += ["WHO CAUGHT IT  (the only column that matters)", "-" * 78]
        for k, v in by_catcher.most_common():
            note = ""
            if k == "OPERATOR":
                note = "  <-- a human doing a machine's job. THIS is the lock backlog."
            elif k == "NOTHING":
                note = "  <-- shipped undetected"
            elif k == "LOCK":
                note = "  <-- a solved class"
            L.append(f"   {k:10} {v:3}  ({v / total * 100:4.0f}%){note}")
        L += ["", f"   OPERATOR-CAUGHT RATE: {op / total * 100:.0f}% — the number to drive to zero.",
              ""]
        L += ["BY CLASS", "-" * 78]
        for k, v in by_class.most_common():
            L.append(f"   {k:22} {v}")
        L += ["", "ERRORS WITH NO LOCK YET  (the backlog)", "-" * 78]
        unlocked = [e for e in errors
                    if e["status"].upper().startswith("OPEN") or not e["lock_needed"]]
        if not unlocked:
            L.append("   (none — every logged error has a lock or a named control)")
        for e in unlocked:
            L += [f"   {e['id']} [{e['class']}] caught_by={e['caught_by']}",
                  f"        {e['what'][:100]}",
                  f"        NEEDS: {e['lock_needed'] or '(undetermined)'}"]
        if not brief:
            L += ["", "ALL ROWS", "-" * 78]
            for e in errors:
                L += [f"   {e['id']} {e['date']} [{e['class']}] caught_by={e['caught_by']} "
                      f"status={e['status']}", f"        {e['what'][:104]}"]
    L += ["", "=" * 78, "ENFORCEMENT INVENTORY — what is actually wired", "=" * 78, ""]
    L += ["CLAUDE HOOKS (fire BEFORE/AROUND an action — the only pre-damage locks)", "-" * 78]
    for h in inv.get("claude_hooks", []):
        L.append(f"   {h}")
    L += ["", "PRE-COMMIT STAGES (fire at commit — after the work is written)", "-" * 78]
    for h in inv.get("pre_commit", []):
        L.append(f"   {h}")
    enf = inv.get("institutional_enforced", {})
    adv = inv.get("institutional_advisory", {})
    crashed = inv.get("institutional_crashed", {})
    L += ["", f"INSTITUTIONAL CHECKS — {len(enf)} ENFORCED, {len(adv)} ADVISORY", "-" * 78]
    failing = {k: v for k, v in enf.items() if v}
    L.append(f"   ENFORCED failing now: {len(failing)}  {failing if failing else '(all clean)'}")
    L.append("   ADVISORY counts: " + ", ".join(f"{k}={v}" for k, v in adv.items()))
    if crashed:
        L.append(f"   CHECKS THAT CRASHED: {len(crashed)}  <-- a check that cannot run is a FINDING")
        for k, v in crashed.items():
            L.append(f"      {k}: {v}")
    sa = inv.get("standalone_checkers_not_in_precommit", [])
    L += ["", f"CHECKERS PRESENT BUT NOT IN PRE-COMMIT: {len(sa)}", "-" * 78]
    L.append("   " + ", ".join(sa) if sa else "   (none)")
    L += ["", "=" * 78,
          "An error caught by the OPERATOR is an unsolved class. An error caught by a",
          "LOCK is a solved one. The middle column is the whole point of this report.",
          "=" * 78]
    return "\n".join(L)


def main(argv: list[str]) -> int:
    errors = read_errors()
    if "--today" in argv:
        today = datetime.date.today().isoformat()
        errors = [e for e in errors if e["date"] == today]
    inv = enforcement_inventory()
    if "--locks" in argv:
        errors = []
    if "--json" in argv:
        print(json.dumps({"errors": errors, "inventory": inv}, indent=2, default=str))
    else:
        print(render(errors, inv, brief="--brief" in argv))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
