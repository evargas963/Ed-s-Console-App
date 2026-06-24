#!/usr/bin/env python3
"""
Guard market-data edits with the Schwab CSV-first policy.

Modes:
  (default) Risky-pattern guard — added diff lines with fail-open market defaults
            require CSV-first declaration markers in the diff.
  --diff-emission-gate — V4 PR gate: new market-fact emission sites in the code diff
            must be covered by a row in the V4 register (on disk and/or added in the
            same diff). Surfaces: Python, HTML, JS/TS, SQL, templates.
"""
from __future__ import annotations

import argparse
import ast
import csv
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
REGISTER_CSV_NAME = "governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"

CSV_MARKERS = (
    "Schwab CSV authority checked",
    "CSV row(s):",
    "NO_SCHWAB_EQUIVALENT",
    "SCHWAB_CSV_CHECKED",
)

REGISTER_ID_IN_DIFF = re.compile(r"\bREGISTER_ROW:\s*([a-f0-9]{20})\b", re.IGNORECASE)
REGISTER_ID_TOKEN = re.compile(r"\b([a-f0-9]{20})\b")

MARKET_NAMES = re.compile(
    r"\b("
    r"spot|lastPrice|mark|bid|ask|bidPrice|askPrice|spread|volume|totalVolume|"
    r"openInterest|multiplier|daysToExpiration|expirationDate|theta|gamma|delta|"
    r"vega|rho|volatility|quoteTime|tradeTime|quoteTimeInLong|tradeTimeInLong|"
    r"vix|pcr|vwap|ohlc|open|high|low|close|confidence|fused|mhap"
    r")\b",
    re.IGNORECASE,
)

MARKET_SURFACE_EXTRA = re.compile(
    r"(?:^|[._])(?:kl_|fused_|mhap|pin_|iv_|vol_|last_|bid_|ask_|spot|gamma|delta|theta|vega|vwap|pcr)",
    re.IGNORECASE,
)

MARKET_DATA_PATHS = (
    "server.py",
    "live_market_plane.py",
    "market_context.py",
    "market_state.py",
    "math_",
    "features/",
    "v2_decision/",
    "calibration/",
    "static/",
    "templates/",
    "backfill_flow_imbalance.py",
    "debug_flow_snapshot.py",
    "realized_contract_eval.py",
    "market_data_adapter.py",
    "snapshot_normalizer.py",
    "signals.py",
    "mc_fusion_adjustment.py",
    "order_flow_",
    "lstm_",
    "ml_",
    "transformer_",
    "prediction_engine.py",
    "liquidity_value_engine.py",
)

EMISSION_SCAN_SUFFIXES = (
    ".py",
    ".html",
    ".htm",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".sql",
    ".jinja",
    ".j2",
)

# Homonyms / English — require quoted market-key context unless extracted as emission surface.
AMBIGUOUS_MARKET_TOKENS = frozenset({"open", "close", "high", "low", "vix"})

# Mega traceable inventories — disposition ledger rows cite Schwab leaves in metadata;
# not runtime market-fact emission (diff-emission gate targets product canopy/trunk).
TRACEABLE_INVENTORY_PATHS: frozenset[str] = frozenset(
    {
        "governance/mega1_traceable_inventory.py",
        "governance/mega2_traceable_inventory.py",
        "governance/mega3_traceable_inventory.py",
        "governance/mega4_traceable_inventory.py",
    }
)

# V4 disposition-ledger slice CSVs — cite scanner surface_form/notes; not runtime emission.
REGISTER_SLICE_LEDGER_PREFIX = "governance/register_slices/"

# Operator-trust / governance tooling — not market-fact emission paths (PR #18 stabilization cone).
EMISSION_EXCLUDE_PATH_PREFIXES: tuple[str, ...] = (
    "tools/check_operator_trust_governance.py",
    "tools/emit_operator_trust_backtrack_reports.py",
    "tools/run_rth_",
    "verification/operator_trust_",
    "reports/operator_trust_backtrack/",
    "reports/ci/",
    "reports/rth_validation/",
    "reports/ui_transport/rth_guest_switch_validation_runbook",
    "reports/db_contention/rth_db_contention_validation_runbook",
    "reports/base_capture/rth_base_capture_normalization_runbook",
    "docs/OPEN_ITEMS_OPERATOR_TRUST.md",
    "docs/ADMIN_BYPASS_REGISTER.md",
    "docs/PR_REVIEW_STANDARD.md",
    "docs/RUNTIME_EVIDENCE_ENV_CONTRACT.md",
    "docs/NO_SILENT_DEGRADATION_POLICY.md",
    "governance/OPERATOR_TRUST_STABILIZATION_GATE.json",
    "tests/test_operator_trust_governance.py",
    "tests/test_check_schwab_csv_first.py",
)

RISK_PATTERNS = (
    re.compile(r"\bor\s+0(?:\.0)?\b"),
    re.compile(r"\bor\s+1(?:\.0)?\b"),
    re.compile(r"\bor\s+100(?:\.0)?\b"),
    re.compile(r"\.get\([^\n\)]*,\s*(?:0|0\.0|1|1\.0|100|100\.0)\s*\)"),
    re.compile(r"\([^)]*(?:bid|bf)[^)]*\+[^)]*(?:ask|af)[^)]*\)\s*/\s*2(?:\.0)?", re.IGNORECASE),
    re.compile(r"(?:ask|af)\s*-\s*(?:bid|bf)", re.IGNORECASE),
    re.compile(r"time\.time\s*\("),
    re.compile(r"black[_-]?scholes|norm\.cdf|bs_", re.IGNORECASE),
)

# Patterns that introduce a named market-fact site (canopy/trunk surface).
REGISTER_COLUMNS_FALLBACK = [
    "register_id",
    "language",
    "path",
    "line",
    "col",
    "pattern_kind",
    "surface_form",
    "tokens",
    "csv_candidates",
    "csv_lexical_topk_note",
    "v2_trace",
    "disposition",
    "canonical_field_citation",
    "governed_ref",
    "notes",
]

EMISSION_EXTRACTORS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""ms_dict\[\s*['"]([A-Za-z_][\w]*)['"]\s*\]"""),
    re.compile(r"""['"]([A-Za-z_][\w]*)['"]\s*:\s*"""),  # JSON / dict literal keys
    re.compile(r"""\.get\(\s*['"]([A-Za-z_][\w]*)['"]"""),
    re.compile(r"""setdefault\(\s*['"]([A-Za-z_][\w]*)['"]"""),
    re.compile(r"""id\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE),
    re.compile(r"""domIf\(\s*['"]([^'"]+)['"]"""),
    re.compile(r"""\bd\.([A-Za-z_][\w]*(?:\[[^\]]+\])?(?:\.[A-Za-z_][\w]*)*)"""),
    re.compile(r"""['"]([A-Za-z_][\w]*)['"]\s*[,}]"""),  # JS object keys in added lines
    re.compile(r"""\{\{\s*([A-Za-z_][\w.]+)\s*\}\}"""),  # Jinja / Mustache
)


@dataclass(frozen=True)
class EmissionSite:
    path: str
    line: int
    surfaces: tuple[str, ...]
    excerpt: str


@dataclass
class RegisterIndex:
    by_path_line: dict[tuple[str, int], dict[str, str]]
    by_register_id: dict[str, dict[str, str]]
    rows: list[dict[str, str]]


def _load_canonical_fields() -> set[str]:
    if not CSV_PATH.exists():
        raise SystemExit(f"Missing Schwab CSV authority: {CSV_PATH}")
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return {row["canonical_field"] for row in csv.DictReader(f)}


def _git_diff(*, staged: bool) -> str:
    args = ["git", "diff", "--cached" if staged else "--"]
    proc = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "git diff failed")
    return proc.stdout


def _added_lines(diff_text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    current = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line.removeprefix("+++ b/")
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        content = line[1:]
        if content.strip().startswith("#"):
            continue
        out.append((current, content))
    return out


def _parse_diff_added_with_lines(diff_text: str) -> list[tuple[str, int, str]]:
    """Return (path, new_file_line_number, content) for each added line."""
    out: list[tuple[str, int, str]] = []
    current = ""
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current = raw.removeprefix("+++ b/")
            new_line = 0
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", raw)
            if m:
                new_line = int(m.group(1))
            continue
        if not current:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            content = raw[1:]
            if not content.strip().startswith("#"):
                out.append((current, new_line, content))
            new_line += 1
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            continue
        if raw.startswith(" "):
            new_line += 1
    return out


def _changed_paths(diff_text: str) -> set[str]:
    paths: set[str] = set()
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            paths.add(line.removeprefix("+++ b/"))
    return paths


def _is_market_data_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in MARKET_DATA_PATHS)


def _is_traceable_inventory_path(path: str) -> bool:
    norm = path.replace("\\", "/")
    return norm in TRACEABLE_INVENTORY_PATHS


def _is_register_slice_ledger_path(path: str) -> bool:
    norm = path.replace("\\", "/")
    return norm.startswith(REGISTER_SLICE_LEDGER_PREFIX)


def _is_emission_scannable_path(path: str) -> bool:
    if _is_traceable_inventory_path(path):
        return False
    if path == REGISTER_CSV_NAME or path.endswith(".csv") and "REGISTER" in path.upper():
        return False
    if any(part in path for part in (".git/", "node_modules/", "backups/", "__pycache__/")):
        return False
    if path.startswith("schwab_field_inventory/"):
        return False
    norm = path.replace("\\", "/")
    if any(norm == p or norm.startswith(p) for p in EMISSION_EXCLUDE_PATH_PREFIXES):
        return False
    if any(path.endswith(suf) for suf in EMISSION_SCAN_SUFFIXES):
        return True
    return path.startswith("templates/")


def _ambiguous_token_is_quoted_market_key(line: str, start: int, end: int) -> bool:
    """True when open/close/high/low/vix appear as quoted dict/JSON keys, not English or methods."""
    before = line[:start]
    after = line[end:]
    if before.endswith(("'", '"')) and after.startswith(("'", '"', ":", " ")):
        return True
    # ms_dict['open'] style already handled by extractors; skip .close() method calls
    if after.startswith("("):
        return False
    return False


def _has_marker(diff_text: str) -> bool:
    return any(marker in diff_text for marker in CSV_MARKERS)


def _is_risky(line: str) -> bool:
    if not MARKET_NAMES.search(line):
        return False
    return any(pattern.search(line) for pattern in RISK_PATTERNS)


def _risky_added_lines(diff_text: str) -> list[tuple[str, str]]:
    """Added diff lines that match risky market-data heuristics (runtime paths only)."""
    return [
        (path, line)
        for path, line in _added_lines(diff_text)
        if not _is_register_slice_ledger_path(path) and _is_risky(line)
    ]


def _is_market_surface(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if MARKET_NAMES.search(name):
        return True
    return MARKET_SURFACE_EXTRA.search(name) is not None


def _is_token_catalog_definition_line(line: str) -> bool:
    """Skip homonym catalog / frozenset definitions — not market-fact emission."""
    stripped = line.strip()
    if "AMBIGUOUS_MARKET_TOKENS" in stripped:
        return True
    if re.match(r"^\w+\s*=\s*frozenset\s*\(", stripped):
        return True
    return False


def _surfaces_from_line(line: str) -> list[str]:
    if _is_token_catalog_definition_line(line):
        return []
    found: list[str] = []
    for pat in EMISSION_EXTRACTORS:
        for m in pat.finditer(line):
            surf = m.group(1).strip()
            if _is_market_surface(surf):
                found.append(surf)
    if MARKET_NAMES.search(line):
        for m in MARKET_NAMES.finditer(line):
            token = m.group(1)
            if token.lower() in AMBIGUOUS_MARKET_TOKENS:
                if not _ambiguous_token_is_quoted_market_key(line, m.start(), m.end()):
                    continue
            found.append(token)
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for s in found:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _extract_emission_sites(diff_text: str) -> list[EmissionSite]:
    sites: list[EmissionSite] = []
    for path, line_no, content in _parse_diff_added_with_lines(diff_text):
        if not _is_emission_scannable_path(path):
            continue
        stripped = content.strip()
        if not stripped:
            continue
        surfaces = _surfaces_from_line(stripped)
        if not surfaces:
            continue
        sites.append(
            EmissionSite(
                path=path,
                line=line_no,
                surfaces=tuple(surfaces),
                excerpt=stripped[:200],
            )
        )
    return sites


def _load_register_index(register_path: Path) -> RegisterIndex:
    if not register_path.is_file():
        raise SystemExit(
            f"V4 register not found: {register_path}\n"
            "Run: python -m tools.schwab_universal_coverage_scanner_v3 "
            f"--output {REGISTER_CSV_NAME}"
        )
    by_path_line: dict[tuple[str, int], dict[str, str]] = {}
    by_register_id: dict[str, dict[str, str]] = {}
    rows: list[dict[str, str]] = []
    with register_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            rid = (row.get("register_id") or "").strip()
            p = (row.get("path") or "").strip().replace("\\", "/")
            try:
                ln = int((row.get("line") or "0").strip() or 0)
            except ValueError:
                ln = 0
            if p and ln:
                by_path_line[(p, ln)] = row
            if rid:
                by_register_id[rid] = row
    return RegisterIndex(by_path_line=by_path_line, by_register_id=by_register_id, rows=rows)


def _parse_register_rows_from_diff(diff_text: str) -> list[dict[str, str]]:
    """Parse added CSV lines for the V4 register when the register file is in the diff."""
    added: list[dict[str, str]] = []
    in_register = False
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            in_register = raw.removeprefix("+++ b/") == REGISTER_CSV_NAME
            continue
        if not in_register or not raw.startswith("+") or raw.startswith("+++"):
            continue
        body = raw[1:]
        if not body or body.startswith("register_id,"):
            continue
        try:
            row = next(csv.DictReader([body], fieldnames=REGISTER_COLUMNS_FALLBACK))
        except Exception:
            continue
        if row.get("register_id"):
            added.append(row)
    return added


def _register_ids_cited_in_diff(diff_text: str) -> set[str]:
    return {m.group(1).lower() for m in REGISTER_ID_IN_DIFF.finditer(diff_text)}


def _row_covers_site(row: dict[str, str], site: EmissionSite, *, line_slack: int = 3) -> bool:
    rp = (row.get("path") or "").strip().replace("\\", "/")
    if rp != site.path:
        return False
    try:
        rline = int((row.get("line") or "0").strip() or 0)
    except ValueError:
        rline = 0
    if rline and site.line and abs(rline - site.line) > line_slack:
        return False
    surface_form = (row.get("surface_form") or "").lower()
    tokens = (row.get("tokens") or "").lower()
    for surf in site.surfaces:
        s = surf.lower()
        if s in surface_form or s in tokens:
            return True
        if surface_form and (s in surface_form or surface_form in s):
            return True
    # path+line match without surface overlap still counts if line exact
    if rline and site.line and rline == site.line:
        return True
    return False


def _site_covered(
    site: EmissionSite,
    index: RegisterIndex,
    diff_register_rows: list[dict[str, str]],
    cited_ids: set[str],
) -> bool:
    for row in diff_register_rows:
        if _row_covers_site(row, site):
            return True
    for rid in cited_ids:
        row = index.by_register_id.get(rid)
        if row and _row_covers_site(row, site):
            return True
    for dline in range(-3, 4):
        row = index.by_path_line.get((site.path, site.line + dline))
        if row and _row_covers_site(row, site):
            return True
    return False


def check_diff_emission_gate(diff_text: str, register_path: Path) -> list[str]:
    """Return human-readable violations (empty list = pass)."""
    sites = _extract_emission_sites(diff_text)
    if not sites:
        return []
    index = _load_register_index(register_path)
    diff_rows = _parse_register_rows_from_diff(diff_text)
    cited = _register_ids_cited_in_diff(diff_text)
    violations: list[str] = []
    for site in sites:
        if _site_covered(site, index, diff_rows, cited):
            continue
        surf = ", ".join(site.surfaces)
        violations.append(
            f"{site.path}:{site.line}: market-fact emission ({surf}) has no matching "
            f"V4 register row in {register_path.name} or register diff; excerpt: {site.excerpt!r}"
        )
    return violations


def _iter_repo_lines() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    skip_parts = {".git", "__pycache__", ".venv", "venv", "node_modules", ".claude"}
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if any(part in skip_parts for part in path.parts):
            continue
        if not _is_market_data_path(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and _is_risky(stripped):
                out.append((rel, lineno, stripped))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Schwab CSV-first guard and V4 diff-emission register gate."
    )
    parser.add_argument("--staged", action="store_true", help="Check staged diff instead of working tree diff.")
    parser.add_argument("--diff-file", type=Path, help="Check an explicit git diff file, used by CI.")
    parser.add_argument(
        "--whole-repo",
        action="store_true",
        help="Scan the current repository for risky market-data patterns, independent of git diff.",
    )
    parser.add_argument(
        "--diff-emission-gate",
        action="store_true",
        help="Fail if the diff adds market-fact emission sites without a matching V4 register row.",
    )
    parser.add_argument(
        "--register",
        type=Path,
        default=DEFAULT_REGISTER,
        help="V4 register CSV for --diff-emission-gate (default: governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv).",
    )
    parser.add_argument(
        "--gatekeeper-crosscheck",
        type=Path,
        metavar="PATH.py",
        help="Print lexical CSV collisions for a Python file (full AST vs entire Schwab CSV).",
    )
    args = parser.parse_args()

    if args.gatekeeper_crosscheck is not None:
        target = args.gatekeeper_crosscheck
        if not target.is_absolute():
            target = (ROOT / target).resolve()
        raise SystemExit(_print_gatekeeper_crosscheck(target))

    canonical = _load_canonical_fields()
    if len(canonical) < 1000:
        raise SystemExit(f"Schwab CSV authority looks incomplete: {len(canonical)} fields")

    if args.whole_repo:
        risky_repo = _iter_repo_lines()
        if not risky_repo:
            print(f"Schwab CSV-first whole-repo guard passed ({len(canonical)} CSV fields loaded).")
            return 0
        print("Schwab CSV-first whole-repo guard FAILED.")
        print(f"CSV authority loaded: {CSV_PATH} ({len(canonical)} fields)")
        print("Risky market-data patterns remain in repository:")
        for path, lineno, line in risky_repo[:80]:
            print(f"- {path}:{lineno}: {line[:180]}")
        if len(risky_repo) > 80:
            print(f"... {len(risky_repo) - 80} more")
        return 1

    if args.diff_file:
        diff_text = args.diff_file.read_text(encoding="utf-8")
    else:
        diff_text = _git_diff(staged=args.staged)

    exit_code = 0

    if args.diff_emission_gate:
        violations = check_diff_emission_gate(diff_text, args.register.resolve())
        if violations:
            print("Schwab V4 diff-emission register gate FAILED.")
            print(f"Register: {args.register.resolve()}")
            print(
                "Each new market-fact site in the diff must have a matching row in the V4 register "
                f"({REGISTER_CSV_NAME}) or be added in the register diff / cited via REGISTER_ROW:<id>."
            )
            for v in violations[:60]:
                print(f"- {v}")
            if len(violations) > 60:
                print(f"... {len(violations) - 60} more")
            exit_code = 1
        else:
            n = len(_extract_emission_sites(diff_text))
            print(
                f"Schwab V4 diff-emission register gate passed "
                f"({n} emission site(s) checked, register loaded)."
            )

    risky = _risky_added_lines(diff_text)
    changed_market_paths = sorted(p for p in _changed_paths(diff_text) if _is_market_data_path(p))
    if args.diff_emission_gate and exit_code != 0:
        return exit_code
    if not risky and not changed_market_paths:
        if args.diff_emission_gate:
            return exit_code
        print(f"Schwab CSV-first guard passed: no risky market-data additions found ({len(canonical)} CSV fields loaded).")
        return exit_code
    if _has_marker(diff_text):
        print(
            "Schwab CSV-first guard passed with declaration marker: "
            f"{len(risky)} risky market-data addition(s), "
            f"{len(changed_market_paths)} market-data file(s), {len(canonical)} CSV fields loaded."
        )
        return exit_code

    print("Schwab CSV-first guard FAILED.")
    print(f"CSV authority loaded: {CSV_PATH} ({len(canonical)} fields)")
    print("Market-data changes need a CSV-first declaration in the slice/commit/governance artifact:")
    print("  Schwab CSV authority checked: yes")
    print("  CSV row(s): <canonical_field rows or NO_SCHWAB_EQUIVALENT>")
    print("  Derived-field disposition: REPLACE_WITH_SCHWAB | KEEP_DERIVED_WITH_PROVENANCE | GATE_FAIL_CLOSED | REDESIGN")
    print("  All consumers checked: yes/no + disposition list")
    for path, line in risky[:40]:
        print(f"- {path}: {line.strip()[:180]}")
    if len(risky) > 40:
        print(f"... {len(risky) - 40} more")
    if changed_market_paths:
        print("Changed market-data files:")
        for path in changed_market_paths[:40]:
            print(f"- {path}")
        if len(changed_market_paths) > 40:
            print(f"... {len(changed_market_paths) - 40} more")
    return 1


# ── V4 gatekeeper: full-file AST token cross-check vs entire Schwab CSV ────────

GATEKEEPER_SECTION_RE = re.compile(r"^## Gatekeeper CSV cross-check", re.MULTILINE | re.IGNORECASE)
COLLISION_COUNT_RE = re.compile(
    r"\*\*lexical_csv_collision_count:\*\*\s*(\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LexicalCsvCollision:
    line: int
    kind: str
    token: str
    example_canonical: str


def _csv_token_lookup() -> dict[str, str]:
    """Uppercase token -> one example canonical_field (full CSV, not a hand-picked subset)."""
    lookup: dict[str, str] = {}
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cf = row["canonical_field"]
            raw = row.get("example_raw_field") or ""
            for part in re.split(r"[.*\[\]/]+", cf):
                if part and part not in ("streaming", "quotes", "chains", "pricehistory", "movers"):
                    lookup.setdefault(part.upper(), cf)
            for part in raw.replace("content.1.", "").split("."):
                if part and part not in ("SPY", "content", "1", "0", "underlying"):
                    lookup.setdefault(part.upper(), cf)
    return lookup


def extract_py_string_tokens(py_path: Path) -> list[tuple[int, str, str]]:
    """Return (line, kind, token) for string literals and dict.get('key') keys."""
    src = py_path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(py_path))
    hits: list[tuple[int, str, str]] = []

    class Visitor(ast.NodeVisitor):
        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and len(node.value) >= 1:
                hits.append((node.lineno, "literal", node.value))

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    hits.append((node.lineno, "dict.get", node.args[0].value))
            self.generic_visit(node)

    Visitor().visit(tree)
    return hits


def lexical_csv_collisions(py_path: Path) -> list[LexicalCsvCollision]:
    """Cross-check every AST string/get token in py_path against the full Schwab CSV."""
    lookup = _csv_token_lookup()
    out: list[LexicalCsvCollision] = []
    seen: set[tuple[int, str, str]] = set()
    for line, kind, tok in extract_py_string_tokens(py_path):
        key = (line, kind, tok)
        if key in seen:
            continue
        seen.add(key)
        cf = lookup.get(tok.upper())
        if cf:
            out.append(LexicalCsvCollision(line=line, kind=kind, token=tok, example_canonical=cf))
    return out


def _memo_target_py_path(memo_path: Path, root: Path) -> Path:
    """
    Map governance/SCHWAB_V4_REVIEW_MEMOS/[subdir/]foo.py.md -> repo-relative foo.py path.
    Root-level memos (bayesian_fusion.py.md) map to root/bayesian_fusion.py;
    nested memos (features/signal_layer_v1.py.md) map to features/signal_layer_v1.py.
    """
    name = memo_path.name[:-3]  # strip .md from *.py.md
    try:
        rel = memo_path.relative_to(root)
    except ValueError:
        return root / name
    parts = rel.parts
    if (
        len(parts) >= 3
        and parts[0] == "governance"
        and parts[1] == "SCHWAB_V4_REVIEW_MEMOS"
    ):
        subdirs = parts[2:-1]
        if subdirs:
            return root.joinpath(*subdirs, name)
        return root / name
    return root / name


def check_v4_memo_gatekeeper_csv(memo_path: Path, repo_root: Path | None = None) -> list[str]:
    """
    Require ## Gatekeeper CSV cross-check with lexical_csv_collision_count matching
    tools/check_schwab_csv_first.py full-CSV AST cross-check of the memo's target .py.
    """
    root = repo_root or ROOT
    errors: list[str] = []
    if not memo_path.is_file():
        return errors
    if memo_path.suffix != ".md" or not memo_path.name.endswith(".py.md"):
        return errors
    try:
        rel = memo_path.relative_to(root).as_posix()
    except ValueError:
        rel = memo_path.as_posix()
    py_path = _memo_target_py_path(memo_path, root)
    target = py_path.relative_to(root)
    if not py_path.is_file():
        return [f"{rel}: target {target.as_posix()} not found for gatekeeper CSV cross-check"]
    try:
        text = memo_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [f"{rel}: cannot read memo ({exc})"]
    if not GATEKEEPER_SECTION_RE.search(text):
        errors.append(
            f"{rel}: missing '## Gatekeeper CSV cross-check' section — "
            "run full CSV AST cross-check before sign-off (AGENTS § Self-governance quality loop)."
        )
        return errors
    collisions = lexical_csv_collisions(py_path)
    m = COLLISION_COUNT_RE.search(text)
    if not m:
        errors.append(
            f"{rel}: Gatekeeper section must record **lexical_csv_collision_count:** N "
            f"(tool count for {target.as_posix()} is {len(collisions)})."
        )
        return errors
    declared = int(m.group(1))
    if declared != len(collisions):
        errors.append(
            f"{rel}: lexical_csv_collision_count {declared} != tool count {len(collisions)} "
            f"for {target.as_posix()} — re-run: python tools/check_schwab_csv_first.py "
            f"--gatekeeper-crosscheck {target.as_posix()}"
        )
    return errors


def _print_gatekeeper_crosscheck(py_path: Path) -> int:
    if not py_path.is_file():
        print(f"File not found: {py_path}", file=sys.stderr)
        return 1
    collisions = lexical_csv_collisions(py_path)
    lookup = _csv_token_lookup()
    print(f"Gatekeeper CSV cross-check: {py_path}")
    print(f"CSV lookup tokens loaded: {len(lookup)}")
    print(f"lexical_csv_collision_count: {len(collisions)}")
    for c in collisions:
        print(f"  L{c.line} {c.kind} {c.token!r} -> e.g. {c.example_canonical}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
