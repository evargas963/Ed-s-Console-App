#!/usr/bin/env python3
"""RC-301 — a function that can fail must be able to SAY so in its return type.

THE CLASS, measured rather than asserted. `absence-coerced-to-a-value` has now been found
SEVEN times in three days: RC-274 (NULL close summed as 0 dollars), RC-277 (my own
regression), RC-282 (undated bundle published age 0.0 and read FRESH), RC-284 (a run that
timed out reported as "tests failed"), RC-285 (a model nobody scored published edge 0),
RC-289 (a stale artefact rendered as the current state) and now this. Each of the six
predecessors was found by an auditor pointing at one line, and each repair fixed the value
and left the SHAPE producible. That is why the count reached six.

WHY THE EXISTING GATES CANNOT SEE IT. `no_fake_defaults` and the silent-zero family match
EXPRESSIONS — `x or 0.0`, `.get(k, 0)`. This defect lives in the RETURN TYPE. A function
annotated `-> float` has already declared that absence cannot be expressed, so by the time
`return 0.0` appears in the `except` handler the type has foreclosed the honest option and
the literal reads as the only way to satisfy the signature.

WHAT THIS FLAGS. A function annotated `-> float` that returns a numeric literal from an
`except` handler. Deliberately narrow: predicates returning False are giving a real answer,
and `main() -> int` returning an exit code is not a measurement. The first prototype over
all scalar returns found 78 and was almost entirely those two shapes; restricting to float
measurements left TWO, both real.

    .venv/Scripts/python.exe tools/check_absence_has_a_type.py
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Not the money path: harnesses, tooling and offline evaluation.
SKIP_PREFIXES = ("tests/", "tools/", "research/", "governance/", "arch_competition/",
                 "scratchpad/", "calibration/")

#: RC-276/RC-287 per-line escape, with a MANDATORY reason. A marker you can type without
#: saying anything is a file allowlist at line granularity, and RC-281 records what happens
#: when the reason itself is never checked: presence is machine-checked here, TRUTH is
#: review surface.
_ABSENCE_OK_RE = re.compile(r"#\s*absence-ok:\s*(\S.*)$")


def _tracked_py() -> list[Path]:
    """RC-274/RC-286: scope is the git index, never a filesystem walk."""
    proc = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed, so the scan scope is unknown: "
                           + proc.stderr.strip())
    return [REPO / p for p in proc.stdout.split("\0") if p]


def fabricated_absence_returns(path: Path) -> list[tuple[int, str, str]]:
    """(lineno, function, literal) for each numeric literal returned from an except."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return []
    lines = text.splitlines()
    out: list[tuple[int, str, str]] = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        ret = fn.returns
        # Only NON-Optional float: the type has foreclosed absence. `float | None`,
        # `Optional[float]` and bare/absent annotations are outside the rule.
        if not (isinstance(ret, ast.Name) and ret.id == "float"):
            continue
        if fn.name == "main":
            continue
        for handler in [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]:
            for r in [n for n in ast.walk(handler) if isinstance(n, ast.Return)]:
                v = r.value
                if not (isinstance(v, ast.Constant) and isinstance(v.value, (int, float))
                        and not isinstance(v.value, bool)):
                    continue
                src_line = lines[r.lineno - 1] if r.lineno <= len(lines) else ""
                if _ABSENCE_OK_RE.search(src_line):
                    continue
                out.append((r.lineno, fn.name, repr(v.value)))
    return out


def violations() -> list[str]:
    out: list[str] = []
    for path in _tracked_py():
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(SKIP_PREFIXES):
            continue
        for lineno, fname, lit in fabricated_absence_returns(path):
            out.append(
                f"{rel}:{lineno}: {fname}() is annotated `-> float` and returns {lit} from "
                f"an except handler. That literal is a MEASUREMENT the caller cannot "
                f"distinguish from a real one — absence has no representation in the type, "
                f"so it was coerced into the value domain (RC-301; seventh occurrence of "
                f"this class). Return `float | None` and let callers say what absence "
                f"means, or add `# absence-ok: <reason>` on the return line stating why the "
                f"literal is a genuine answer here.")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    v = violations()
    if v:
        print("check_absence_has_a_type: FAIL — absence fabricated as a measurement:")
        for line in v:
            print("  " + line)
        return 1
    if not args.quiet:
        print("check_absence_has_a_type: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
