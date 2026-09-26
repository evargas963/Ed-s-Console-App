"""
CAPS — Comprehensive Anti-Pattern Sweep.

Enumerates silent-default-substitution shapes on Schwab-leaf-derived paths.
Output: file:line:variant_id:expression (tab-separated on CLI).

Used by tests/test_anti_pattern_family_repo_wide.py and governance register maintenance.
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
        "governance",
        "schwab_field_inventory",
    }
)

# Production scan excludes tooling and test harnesses (allowlisted via register prefix rows).
SCAN_SKIP_PREFIXES = (
    "tools/",
    "tests/",
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
        re.compile(r"""\.get\(\s*['"][^'"]+['"]\s*,\s*(?!None\b)([^)]+)\)"""),
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
        re.compile(
            r"""getattr\(\s*[^,]+,\s*['"][^'"]+['"]\s*,\s*(?!None\b)"""
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
        "next(iter, default)",
    ),
    VariantSpec(
        "EXCEPT_RETURN_DEFAULT",
        re.compile(r"""except\s*[^:]*:\s*(?:return\s+)?(?:0\.0|0|None|False|True)\b"""),
        "try/except return default",
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


def iter_py_files(*, production_only: bool) -> list[Path]:
    out: list[Path] = []
    for path in _tracked_py_files():
        if set(path.parts) & SKIP_DIR_PARTS:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if production_only and any(rel.startswith(p) for p in SCAN_SKIP_PREFIXES):
            continue
        out.append(path)
    return out


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


def scan_all(*, production_only: bool = False) -> list[tuple[int, str, str, str]]:
    all_hits: list[tuple[int, str, str, str]] = []
    for path in sorted(iter_py_files(production_only=production_only)):
        all_hits.extend(scan_file(path))
    return all_hits


def format_hit(lineno: int, rel: str, variant_id: str, expr: str) -> str:
    expr_one = expr.replace("\t", " ").replace("\n", " ")[:200]
    expr_one = expr_one.encode("ascii", "replace").decode("ascii")
    return f"{rel}:{lineno}:{variant_id}:{expr_one}"


def hit_is_allowlisted(
    rel: str,
    lineno: int,
    variant_id: str,
    *,
    prefix_rules: tuple[tuple[str, str], ...],
    line_rules: tuple[tuple[str, int | str, str, str], ...],
) -> bool:
    for prefix, _reason in prefix_rules:
        if rel == prefix or rel.startswith(prefix):
            return True
    for file, line, variant, _reason in line_rules:
        if rel != file:
            continue
        if line != "*" and int(line) != lineno:
            continue
        if variant != "*" and variant != variant_id:
            continue
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAPS anti-pattern family sweep")
    parser.add_argument(
        "--production-only",
        action="store_true",
        help="Exclude tests/ and tools/",
    )
    parser.add_argument(
        "--variant",
        action="append",
        help="Filter to variant_id (repeatable)",
    )
    parser.add_argument(
        "--emit-register-tsv",
        action="store_true",
        help="Emit CAPS allowlist TSV rows to stdout (for register maintenance)",
    )
    args = parser.parse_args(argv)

    allowed_variants = set(args.variant) if args.variant else None
    hits = scan_all(production_only=args.production_only)
    for lineno, rel, vid, expr in hits:
        if allowed_variants and vid not in allowed_variants:
            continue
        if args.emit_register_tsv:
            print(f"{rel}\t{lineno}\t{vid}\tauto-classified pending")
        else:
            print(format_hit(lineno, rel, vid, expr))
    return 0


# Prefix allowlist: path prefix → justification (all variants, all lines).
CAPS_PREFIX_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("tests/", "test fixtures and gate documentation"),
    ("tools/", "scanner/CLI tooling not production data path"),
    ("calibration/", "calibration audit SQL aggregates and phase cleanup counters"),
    ("verification/", "verification harness diagnostics"),
    ("arch_competition/", "offline arch competition harness"),
    ("planes/", "L1/runtime plane timestamps and version counters"),
    ("liquidity_value_engine.py", "internal bar _ts sort keys"),
    ("app/options/order_flow/engine.py", "Schwab print time_millis sort/cutoff"),
    ("db.py", "SQL COUNT aggregate int coercion"),
    ("server.py", "L1/SSE instrumentation timestamps and volume deltas"),
    ("live_market_plane.py", "streaming plane timestamps and carry-forward guards"),
    ("api_pressure.py", "HTTP client status_code getattr default"),
    ("micro_structure.py", "microstructure derived metrics"),
    ("movement_target_threshold.py", "movement target threshold derived metrics"),
    ("app/options/order_flow/state.py", "order-flow live state derived metrics"),
    ("app/options/order_flow/streaming.py", "order-flow streaming diagnostics"),
    ("math_volatility.py", "volatility derived metrics"),
    ("research/", "research pilot scripts"),
    ("v2_decision/", "v2 decision adapter derived defaults"),
    ("audit_", "audit script counters and diagnostics"),
    ("backfill_", "backfill script counters"),
    ("debug_", "debug utilities"),
    ("db_authority.py", "DB authority env flags"),
    ("db_safety.py", "sqlite3 constant getattr defaults"),
    ("market_context.py", "Schwab quote envelope nesting (quote/extended/regular dict shells)"),
    ("math_exposure_core.py", "explicit None branches on bucket aggregates"),
    ("math_probabilities.py", "probability derived metrics"),
    ("schwab_field_dictionary_builder.py", "field dictionary builder tooling"),
    ("math_levels.py", "structural window index default (non-price)"),
)

# Line-level exceptions (file, line or *, variant or *, justification).
CAPS_LINE_ALLOWLIST: tuple[tuple[str, int | str, str, str], ...] = (
    ("numeric_contract.py", "*", "GETATTR_DEFAULT", "duck-typing on base-model output objects (prob_up/prob_down/prob_flat, dominant_class/dominant_dir); not a silent-default fabrication"),
    # ANTI_PATTERN_CAPS_VIOLATIONS bucket — exact line+variant exemptions for reviewed
    # non-market-leaf hits (no whole-file prefix; any future hit on another line/variant
    # in these files is still caught). Reasons state the reviewed category.
    ("decision_record.py", 352, "IF_TRUTHY_ELSE", "explicit fail-closed no-payload result"),
    ("decision_record.py", 422, "IF_TRUTHY_ELSE", "explicit fail-closed no-payload result"),
    ("release_object.py", 35, "GET_WITH_DEFAULT", "env config only"),
    ("release_object.py", 106, "GET_WITH_DEFAULT", "env config only"),
    ("release_object.py", 107, "GET_WITH_DEFAULT", "env config only"),
    ("scheduler_user_tickers.py", 60, "GET_WITH_DEFAULT", "env config only"),
    ("schwab_client.py", 51, "GETATTR_DEFAULT", "constant base URL only"),
    # Instant-UI Phase 7 added write_token_file_atomically (+14 lines). The four
    # reviewed OAuth/config sites moved 294/372/373/404 -> 308/386/387/418. Each
    # site now also carries `# caps-ok:` so a later shift cannot re-red CI on
    # the same already-reviewed statements (RC-287).
    ("schwab_client.py", 308, "GET_WITH_DEFAULT", "OAuth/config timeout only"),
    ("schwab_client.py", 386, "GET_OR_DEFAULT", "parse_qs indexing idiom only"),
    ("schwab_client.py", 387, "GET_OR_DEFAULT", "parse_qs indexing idiom only"),
    ("schwab_client.py", 418, "GET_WITH_DEFAULT", "OAuth/config timeout only"),
    # 218 -> 217: RC-64 removed a dead `reasons: list[str] = []` initialisation earlier in this
    # file, shifting every following line up by one. The reviewed site is unchanged.
    # stream_spine.py's `msg.get("src", "?")` sites moved when native-fidelity/book capture
    # (2026-08-30) added lines above CaptureWriter.insert(); a line-pinned entry here would
    # silently stop matching the moment anything shifts again (exactly the failure mode this
    # allowlist shape is documented above as NOT suited to). Each site now carries its own
    # `# caps-ok:` marker instead, which travels with the code it excuses.
)


def caps_hit_allowed(rel: str, lineno: int, variant_id: str) -> bool:
    if hit_is_allowlisted(
        rel,
        lineno,
        variant_id,
        prefix_rules=CAPS_PREFIX_ALLOWLIST,
        line_rules=CAPS_LINE_ALLOWLIST,
    ):
        return True
    return False


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


def find_unallowlisted_hits(*, production_only: bool = True) -> list[str]:
    out: list[str] = []
    for lineno, rel, vid, expr in scan_all(production_only=production_only):
        if caps_hit_allowed(rel, lineno, vid):
            continue
        if line_carries_caps_marker(rel, lineno):
            continue
        out.append(format_hit(lineno, rel, vid, expr))
    return out


if __name__ == "__main__":
    sys.exit(main())
