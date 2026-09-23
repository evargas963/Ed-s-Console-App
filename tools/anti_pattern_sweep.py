"""
CAPS — Comprehensive Anti-Pattern Sweep.

Enumerates silent-default-substitution shapes across EVERY git-tracked .py file in the repo
(production, tools/, tests/, governance/). Output: file:line:variant_id:expression.

The ONLY escape is a line-specific `# caps-ok: <reason>` marker on the hit line itself.

RC-REHAB-1 (2026-09-23, operator: "fix the CAPS exemptions too, review them all"): this gate
used to carry CAPS_PREFIX_ALLOWLIST (106 whole-file / whole-folder exemptions: tests/, tools/,
calibration/, server.py, market_state.py, call_engine.py, ...) and CAPS_LINE_ALLOWLIST
(line-number pins), and its pass/fail scan skipped tools/ and tests/ and governance/ outright.
Together they hid 1,967 hits across 393 files that nobody had reviewed line by line. Every one
was reviewed: real masked defects were fixed at the source, and every legitimate default carries
its own reason on its own line. Both allowlists and the scope exclusions are deleted; a new
blanket exemption has nowhere to live.

    .venv/Scripts/python.exe tools/anti_pattern_sweep.py              # every unmarked hit
    .venv/Scripts/python.exe tools/anti_pattern_sweep.py a.py b.py    # just these files

Used by tests/test_anti_pattern_family_repo_wide.py and tests/test_caps_marker_is_line_scoped_v1.py.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIR_PARTS = frozenset(
    {
        ".git",
        ".claude",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".pytest_cache",
        "backups",
    }
)

DEFAULT_VALUE_RE = re.compile(
    r"""
    \b0\.0\b|\b0\b|\b1\.0\b|\b1\b|\b100\.0\b|\b100\b|\b6\.5\b|
    ["']above["']|["']unknown["']|["']neutral["']|["']flat["']|
    \bFalse\b|\bTrue\b
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class VariantSpec:
    variant_id: str
    regex: re.Pattern[str]
    description: str


VARIANTS: tuple[VariantSpec, ...] = (
    VariantSpec(
        "GET_WITH_DEFAULT",
        # CAPS audit fix (2026-09-20): the lookahead used to be `\s*(?!None\b)` -- since
        # `\s*` is greedy but backtracks, a genuine `.get(key, None)` (real, honest
        # missingness) could still match: the engine backtracks `\s*` to zero-width,
        # checks the lookahead at a position where a SPACE (not "N") comes next, the
        # lookahead trivially succeeds, and the true `None` default is silently
        # misclassified as a fabricated one. The lookahead itself now tolerates the
        # same leading whitespace so it always sees what the value actually is,
        # regardless of how far `\s*` backtracks.
        re.compile(r"""\.get\(\s*['"][^'"]+['"]\s*,\s*(?!\s*None\b)([^)]+)\)"""),
        "dict.get(key, default) where default is not None",
    ),
    VariantSpec(
        "GET_OR_DEFAULT",
        re.compile(r"""\.get\(\s*['"][^'"]+['"]\s*\)\s+or\s+"""),
        "dict.get(key) or default (default must be in silent-default value family)",
    ),
    VariantSpec(
        "GET_NONE_OR_DEFAULT",
        re.compile(r"""\.get\(\s*['"][^'"]+['"]\s*,\s*None\s*\)\s+or\s+"""),
        "dict.get(key, None) or default",
    ),
    VariantSpec(
        "CAST_OR_DEFAULT",
        re.compile(r"""(?:int|float)\(.+?\s+or\s+0(?:\.0)?\)"""),
        "int(x or default) / float(x or default)",
    ),
    VariantSpec(
        "IF_NOT_NONE_ELSE",
        re.compile(r"""\bif\s+[^\n:]+?\s+is\s+not\s+None\s+else\s+"""),
        "x if x is not None else default",
    ),
    VariantSpec(
        "IF_TRUTHY_ELSE",
        re.compile(
            r"""(?<!['"])\bif\s+([a-zA-Z_][\w.]*)\s+else\s+(?!None\b)"""
        ),
        "x if x else default (truthy branch)",
    ),
    VariantSpec(
        "GETATTR_DEFAULT",
        # CAPS audit fix (2026-09-20): same backtracking bug as GET_WITH_DEFAULT above --
        # `getattr(obj, "field", None)`, a genuine "absence has a type" default, was
        # silently misclassified as a fabricated default because `\s*` could backtrack
        # to zero-width before the `(?!None\b)` lookahead ran, letting a stray space
        # hide the real `None` from the check. Widened the lookahead to tolerate that
        # same leading whitespace so it always sees the true value.
        re.compile(
            r"""getattr\(\s*[^,]+,\s*['"][^'"]+['"]\s*,\s*(?!\s*None\b)"""
        ),
        "getattr(obj, field, default) where default is not None",
    ),
    VariantSpec(
        "SETDEFAULT",
        re.compile(r"""\.setdefault\(\s*['"][^'"]+['"]\s*,"""),
        "dict.setdefault(key, default)",
    ),
    VariantSpec(
        "NEXT_DEFAULT",
        re.compile(r"""next\(\s*[^,]+,\s*"""),
        "next(iter, default)",  # caps-ok: scanner false positive: this is the variant's own description string, not a call
    ),
    VariantSpec(
        "EXCEPT_RETURN_DEFAULT",
        re.compile(r"""except\s*[^:]*:\s*(?:return\s+)?(?:0\.0|0|None|False|True)\b"""),
        "try/except return default",
    ),
    VariantSpec(
        # RC-REHAB-1 (2026-09-23): found during the allowlist-retirement review --
        # `float_nonnegative_or_none(ct.get("openInterest")) or 0.0` escaped every variant
        # above because the closing paren sits BEFORE the `or`. Any call result defaulted to
        # a silent-default literal. 22 hits on introduction, each individually dispositioned.
        "CALL_OR_DEFAULT",
        re.compile(
            r"""\)\s+or\s+(?:0\.0|0|1\.0|1|100\.0|100|False|True|["'](?:unknown|neutral|flat|above)["'])\b"""
        ),
        "f(...) or default (a call's missing result replaced by a silent-default literal)",
    ),
)


def _line_is_explicit_none_branch(line: str, variant_id: str) -> bool:
    """`x if x is not None else 0.0` is explicit missingness, not silent .get default."""
    if variant_id == "IF_NOT_NONE_ELSE" and "is not None else" in line:
        return bool(re.search(r"else\s+0(?:\.0)?\b", line))
    return False


def _line_is_doc_or_comment(line: str) -> bool:
    s = line.strip()
    if s.startswith("#"):
        return True
    if '"""' in line or "'''" in line:
        if any(
            tok in line
            for tok in (
                "silent default",
                "pattern family",
                "without ``",
                "CAPS",
                "anti-pattern",
            )
        ):
            return True
    return False


def _tracked_py_files() -> list[Path]:
    """RC-286: 'repo-wide' means what git tracks, the same definition RC-274 gave the
    silent-zero gate.

    This walked the filesystem and subtracted a hand-maintained `SKIP_DIR_PARTS`, which is
    correct exactly once — on the day it is written. `scratchpad/` was never added, so this
    gate has been failing on throwaway audit scripts that `.gitignore:202` excludes and that
    git does not track at all. The index already answers "is this repository code", answers
    it for directories nobody has invented yet, and counts a staged file the moment it is
    staged. SKIP_DIR_PARTS survives for the tracked-but-not-product trees it legitimately
    names, where it is a scope choice rather than a stand-in for the index.
    """
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "git ls-files failed, so the scan scope is unknown: " + proc.stderr.strip())
    return [ROOT / p for p in proc.stdout.split("\0") if p]


def iter_py_files() -> list[Path]:
    """Every git-tracked .py file outside the not-code trees in SKIP_DIR_PARTS."""
    return [p for p in _tracked_py_files() if not (set(p.parts) & SKIP_DIR_PARTS)]


def scan_file(path: Path) -> list[tuple[int, str, str, str]]:
    rel = path.relative_to(ROOT).as_posix()
    hits: list[tuple[int, str, str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        if _line_is_doc_or_comment(line):
            continue
        for spec in VARIANTS:
            m = spec.regex.search(line)
            if not m:
                continue
            if spec.variant_id == "GET_OR_DEFAULT":
                tail = line[m.start() :]
                if not DEFAULT_VALUE_RE.search(tail):
                    continue
            if _line_is_explicit_none_branch(line, spec.variant_id):
                continue
            if spec.variant_id in ("IF_TRUTHY_ELSE", "IF_NOT_NONE_ELSE"):
                if not DEFAULT_VALUE_RE.search(line):
                    continue
            hits.append((lineno, rel, spec.variant_id, line.strip()))
            break
    return hits


def scan_all() -> list[tuple[int, str, str, str]]:
    all_hits: list[tuple[int, str, str, str]] = []
    for path in sorted(iter_py_files()):
        all_hits.extend(scan_file(path))
    return all_hits


def format_hit(lineno: int, rel: str, variant_id: str, expr: str) -> str:
    expr_one = expr.replace("\t", " ").replace("\n", " ")[:200]
    expr_one = expr_one.encode("ascii", "replace").decode("ascii")
    return f"{rel}:{lineno}:{variant_id}:{expr_one}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAPS anti-pattern family sweep")
    parser.add_argument("paths", nargs="*", help="limit to these repo-relative files")
    parser.add_argument("--variant", action="append", help="Filter to variant_id (repeatable)")
    parser.add_argument("--all", action="store_true",
                        help="also print hits that carry a caps-ok marker")
    args = parser.parse_args(argv)
    allowed_variants = set(args.variant) if args.variant else None
    files = [ROOT / p for p in args.paths] if args.paths else iter_py_files()
    n = 0
    for path in sorted(files):
        for lineno, rel, vid, expr in scan_file(path):
            if allowed_variants and vid not in allowed_variants:
                continue
            if not args.all and line_carries_caps_marker(rel, lineno):
                continue
            n += 1
            print(format_hit(lineno, rel, vid, expr))
    print(f"{n} hit(s)", file=sys.stderr)
    return 1 if n else 0  # caps-ok: process exit code (1 = hits found), n is a real count, not a data default


#: RC-287: the per-line escape, the same shape RC-276 gave the silent-zero gate as
#: `# silent-zero-ok:`. It exists because the gate's only other escapes address a hit by
#: LOCATION: CAPS_PREFIX_ALLOWLIST is file-scoped and would exempt 400+ lines of
#: terrain_engine.py to excuse two of them (RC-276's exact defect), while
#: CAPS_LINE_ALLOWLIST pins a LINE NUMBER and hands its exemption to a different statement
#: the moment anything above it shifts. A marker in the source travels with the code it
#: excuses. The reason is mandatory — a marker you can type without saying anything is the
#: file allowlist again, per line. Presence is machine-checked here; TRUTH is not
#: checkable, and RC-281 records what happens when I write reasons that are false, so
#: these are review surface, not proof.
_CAPS_OK_RE = re.compile(r"#\s*caps-ok:\s*(\S.*)$")


def line_carries_caps_marker(rel: str, lineno: int) -> bool:
    """True when the source line itself states why this hit is not a defect."""
    try:
        lines = (ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    if not (1 <= lineno <= len(lines)):
        return False
    return bool(_CAPS_OK_RE.search(lines[lineno - 1]))


def find_unmarked_hits() -> list[str]:
    """Every hit in the repo whose own line does not state why it is not a silent default."""
    out: list[str] = []
    for lineno, rel, vid, expr in scan_all():
        if line_carries_caps_marker(rel, lineno):
            continue
        out.append(format_hit(lineno, rel, vid, expr))
    return out

if __name__ == "__main__":
    sys.exit(main())
