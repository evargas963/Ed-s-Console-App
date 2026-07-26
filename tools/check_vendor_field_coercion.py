"""Mechanical lock: single-source coercion of Schwab vendor fields (RC-FAUCET).

A trading UI where "data IS the product" cannot afford the SAME raw vendor field
parsed a dozen different ways. Raw ``float(ct.get("strikePrice"))`` inside a
``try/except (TypeError, ValueError)`` looks safe but SILENTLY ADMITS NaN/±inf
(``float('nan')`` does not raise): a NaN strike has become a dict key, slipped into
sorted strike sets (corrupting ATM/spacing), and passed ``abs(nan-target) >= 0.01``
as a FALSE contract match. Every such field must be read through the canonical
``numeric_contract`` readers so absence/corruption is rejected identically everywhere.

This check flags raw ``float(...)`` / ``int(float(...))`` coercion of a vendor field,
in BOTH forms the adversarial audit found bugs in:

  (a) DIRECT:        ``float(ct.get("strikePrice"))`` / ``float(c["strikePrice"])``
  (b) INTERMEDIATE:  ``sp = ct.get("strikePrice")`` ... later ``float(sp)``
      (the form a field-name grep MISSES — where 2 real bugs hid on 2026-07-25)

A site is CLEAN when the coercion goes through a canonical reader
(``float_finite_or_none`` / ``float_nonnegative_or_none`` / ``float_positive_or_none``
or a module-local delegate: ``_f`` / ``_f_ms`` / ``_safe_float`` / ``_nonnegative_float``
/ ``_num`` / ``_sf`` / ``_fin``), OR when the line carries an explicit, reasoned
suppression marker::

    # vendor-coercion-ok: <reason it is provably safe here>

Suppressions are for sites that are safe BY CONSTRUCTION (e.g. a diagnostic counter
that gates every use on ``isfinite``), never to silence a real one. Each must state why.

Run standalone:   python tools/check_vendor_field_coercion.py [--verbose]
Exit code 0 = clean, 1 = unmarked vendor coercion found.

Schwab CSV authority checked: yes — this governs HOW Schwab leaves are parsed; it reads
no market field itself. SCHWAB_CSV_CHECKED / NO_SCHWAB_EQUIVALENT (tooling gate).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Schwab option-chain / quote leaf fields whose coercion must be single-sourced.
VENDOR_FIELDS = frozenset({
    "strikePrice", "totalVolume", "openInterest", "gamma", "delta", "theta", "vega",
    "volatility", "bid", "ask", "mark", "last", "lastSize", "bidSize", "askSize",
    "multiplier", "daysToExpiration", "highPrice", "lowPrice", "openPrice",
    "closePrice", "netChange", "lastPrice", "mid",
    # numeric leaves added 2026-07-25 (iteration-4 finding: float(underlyingPrice) admitted
    # NaN and the `<= 0` spot guard did not catch it):
    "underlyingPrice", "rho", "theoreticalOptionValue", "theoreticalVolatility",
    "timeValue", "intrinsicValue", "markChange", "markPercentChange", "netPercentChange",
})

#: Canonical readers (and their in-scope module-local delegates) that make a coercion safe.
CANONICAL_READERS = frozenset({
    "float_finite_or_none", "float_nonnegative_or_none", "float_positive_or_none",
    "float_or_none", "_f", "_f_ms", "_safe_float", "_nonnegative_float", "_num",
    "_sf", "_fin", "_fin2",
})

SUPPRESS_MARKER = "vendor-coercion-ok"

#: Source objects that are ALREADY-parsed payloads / internal outputs, NOT a raw Schwab
#: chain contract or quote leaf. A field read off these is not a vendor coercion — the
#: canonicalization already happened upstream (e.g. pq["bid"] = _safe_float_quote(...)).
SOURCE_DENYLIST = frozenset({
    "pq", "mc_output", "ms_dict", "snapshot", "snap", "parsed", "payload",
})

#: Directories whose Python is out of the live money-path (offline/vendored/generated).
EXCLUDE_DIRS = (
    ".claude", ".venv", "node_modules", "governance/archive", "research",
    "schwab-py-main", "__pycache__",
)


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(REPO).as_posix()
    if rel.startswith("tools/") or rel.startswith("tests/") or "/tests/" in rel:
        return True
    if rel.startswith("calibration/"):
        return True  # offline morning calibration; not the live serving path
    for d in EXCLUDE_DIRS:
        if rel == d or rel.startswith(d + "/"):
            return True
    if path.name.startswith("test_") or path.name.endswith("_test.py"):
        return True
    return False


# float(EXPR) or int(float(EXPR)) — capture the inner expression EXPR, allowing ONE
# level of nested parens so ``float(ct.get("strikePrice"))`` (the DIRECT form) is matched,
# not just ``float(sp)`` (the intermediate form). Missing the nested case was a detector
# blind spot: it silently reduced the lock to intermediate-only.
_FLOAT_CALL = re.compile(r"(?:int\(\s*)?(?<![A-Za-z0-9_])float\(\s*([^()]*(?:\([^()]*\))?[^()]*?)\s*\)")
# EXPR is a direct vendor get: x.get("field") or x["field"]
_DIRECT_GET = re.compile(r"""\.get\(\s*['"](?P<f>[A-Za-z0-9_]+)['"]""")
_DIRECT_SUB = re.compile(r"""\[\s*['"](?P<f>[A-Za-z0-9_]+)['"]\s*\]""")
# Assignment of a bare name from a vendor get:  var = x.get("field")  /  var = x["field"]
_ASSIGN_GET = re.compile(
    r"""^\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<rhs>.+?\.get\(\s*['"](?P<f>[A-Za-z0-9_]+)['"].*|.+?\[\s*['"](?P<f2>[A-Za-z0-9_]+)['"]\s*\].*)$"""
)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+\w+")
_BARE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _rhs_uses_canonical(expr: str) -> bool:
    return any(r + "(" in expr for r in CANONICAL_READERS)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, kind, code) for each unmarked vendor coercion in the file."""
    findings: list[tuple[int, str, str]] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    vendor_vars: dict[str, str] = {}  # varname -> field, reset per def
    for i, line in enumerate(lines, start=1):
        if _DEF_RE.match(line):
            vendor_vars = {}
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        marked = SUPPRESS_MARKER in line

        # Record vendor-var assignments (intermediate form), unless RHS is already canonical.
        m = _ASSIGN_GET.match(line)
        if m:
            fld = m.group("f") or m.group("f2")
            var = m.group("var")
            rhs = m.group("rhs")
            src_m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\.get\(|\[)", rhs)
            src = src_m.group(1) if src_m else ""
            if fld in VENDOR_FIELDS and src in SOURCE_DENYLIST:
                vendor_vars.pop(var, None)  # already-parsed payload / internal output -> safe
            elif fld in VENDOR_FIELDS and not _rhs_uses_canonical(rhs):
                vendor_vars[var] = fld
            elif fld in VENDOR_FIELDS:
                vendor_vars.pop(var, None)  # reassigned through a canonical reader -> safe

        # Inspect every float()/int(float()) call on this line.
        for fm in _FLOAT_CALL.finditer(line):
            inner = fm.group(1).strip()
            # (a) DIRECT vendor get inside the float()
            dg = _DIRECT_GET.search(inner) or _DIRECT_SUB.search(inner)
            if dg and dg.group("f") in VENDOR_FIELDS:
                if not marked:
                    findings.append((i, "direct", stripped))
                continue
            # (b) INTERMEDIATE: float() on a bare name previously bound to a vendor field
            if _BARE_NAME.match(inner) and inner in vendor_vars:
                if not marked:
                    findings.append((i, f"intermediate({vendor_vars[inner]})", stripped))
    return findings


def violations() -> list[tuple[str, int, str]]:
    """(rel_path, line, message) for each unmarked vendor coercion — for the gate wrapper."""
    out: list[tuple[str, int, str]] = []
    for path in sorted(REPO.rglob("*.py")):
        if _is_excluded(path):
            continue
        rel = path.relative_to(REPO).as_posix()
        for (ln, kind, code) in scan_file(path):
            out.append((rel, ln,
                        f"raw float()/int(float()) coercion of a Schwab vendor field [{kind}] — "
                        f"read it through numeric_contract (float_finite_or_none / "
                        f"float_nonnegative_or_none), or add '# vendor-coercion-ok: <reason>' "
                        f"if provably safe by construction: {code}"))
    return out


def main(argv: list[str]) -> int:
    verbose = "--verbose" in argv
    total: list[tuple[Path, int, str, str]] = []
    for path in sorted(REPO.rglob("*.py")):
        if _is_excluded(path):
            continue
        for (ln, kind, code) in scan_file(path):
            total.append((path, ln, kind, code))

    if not total:
        print("vendor-field coercion: CLEAN — every Schwab vendor field is read through "
              "a canonical numeric_contract reader (or an explicit vendor-coercion-ok marker).")
        return 0

    print(f"vendor-field coercion: {len(total)} unmarked raw coercion(s) of a Schwab vendor field:")
    for (path, ln, kind, code) in total:
        rel = path.relative_to(REPO).as_posix()
        print(f"  {rel}:{ln}  [{kind}]  {code}")
    print("\nFix: read the field through numeric_contract (float_finite_or_none / "
          "float_nonnegative_or_none), or, if provably safe by construction, add "
          "'# vendor-coercion-ok: <reason>' on the line.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
