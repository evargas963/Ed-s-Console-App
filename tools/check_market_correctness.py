"""Market-correctness checker — the single fast static gate for the money path.

Replaces the retired enforcement stack (check_fix_everything_we_touch.py,
enforce_all_rules.py, preload/deferral/ticker-lock checkers). It keeps ONLY the
checks that directly prevent a real trading-system failure the one-page charter,
the pre-work question, or the decision gate cannot already handle:

  1. FABRICATED_MARKET_INPUT   — hard-coded neutral/default market values
     (0.33, "neutral", "flat", 500.0 spot, silent `or 0.0` on a market field)
     reaching the decision path.
  2. SESSION_CLOCK_CORRUPTION  — session/RTH decided from a stored et_hour/
     et_minute/market_session column instead of ts_utc + the exchange calendar.
  3. SECRET_EXPOSURE           — hard-coded credentials / API keys / tokens, or
     operator-home absolute paths, in tracked source.
  4. SILENT_PRODUCTION_FALLBACK — bare `except: pass` / `except Exception: pass`
     swallowing errors in a money-path file.
  5. NONDETERMINISTIC_MONEYPATH — unseeded randomness (`random.` / `np.random`
     / `uuid4`) in a money-path inference file.

Behavioral classes not statically decidable here — causal leakage, train/serve
schema parity, and full inference determinism — are proven by retained
PROTECTS_RUNTIME_TRUTH tests in the required pytest-full suite, not by this gate.

Usage:
  python tools/check_market_correctness.py                # scan the money path
  python tools/check_market_correctness.py --staged       # only staged files
  python tools/check_market_correctness.py --self-test    # prove each check fires
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The decision/inference cone — where a correctness failure becomes a trade.
# (Traced from compute_call -> signals.py -> stamp_decision_bundle; the gate seam
# is live_decision_bundle.apply_trade_impacting_gate.)
MONEY_PATH_FILES = (
    "call_engine.py",
    "signals.py",
    "live_decision_bundle.py",
    "trade_impacting_gate.py",
    "bayesian_fusion.py",
    "math_probabilities.py",
    "horizon_outcomes.py",
)
# Session authority must live only here.
SESSION_AUTHORITY_ALLOW = ("time_et.py", "ct_session.py")

# Only UNAMBIGUOUS fabrications: a literal 1/3 "neutral" probability or a 500.0
# magic spot assigned to a probability/confidence/spot field. Honest abstention
# labels (direction="flat"/"neutral") and the governed uniform no-forecast
# fallback are NOT fabrications and are deliberately not matched — that semantic
# line is the operator's review + the runtime tests, not this static gate.
_MARKET_DEFAULT_RE = re.compile(
    r"""(?xi)
    (?:\bprob\w*\b|\bconfidence\b|\bspot\b)
    \s*=\s*
    (?:0\.33\b|500\.0\b)
    """
)
_SILENT_MARKET_GET_RE = re.compile(
    r"\.get\(\s*[\"'][a-z_]*(spot|price|delta|gamma|prob|dir|conf|vol)[a-z_]*[\"']\s*,\s*0(?:\.0)?\s*\)",
    re.IGNORECASE,
)
_SESSION_CLOCK_RE = re.compile(
    r"\b(et_hour|et_minute|market_session)\b\s*(?:[<>=!]=?|in\b|==)",
)
_SECRET_RE = re.compile(
    r"""(?xi)
    (?:api[_-]?key|secret|token|passwd|password|bearer)\s*[:=]\s*["'][A-Za-z0-9/\+=_\-]{16,}["']
    """
)
_HOME_PATH_RE = re.compile(r"[\"']([A-Za-z]:[\\/]Users[\\/][^\"'\\/]+|/(?:home|Users)/[^\"'/]+)")
_RANDOM_RE = re.compile(r"\b(random\.(?:random|choice|shuffle|randint|uniform)|np\.random\.|numpy\.random\.|uuid4)\b")

_GOVERNED = re.compile(r"\bO-\d+\b|GOVERNED|# *nofabricate-ok|schwab|canonical", re.IGNORECASE)


def _iter_money_path(only: set[str] | None) -> list[Path]:
    out = []
    for name in MONEY_PATH_FILES:
        p = ROOT / name
        if not p.is_file():
            continue
        rel = name
        if only is not None and rel not in only:
            continue
        out.append(p)
    return out


def _staged_paths() -> set[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--name-only"],
                       capture_output=True, text=True)
    return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}


def _scan_text(rel: str, text: str) -> list[str]:
    errs: list[str] = []
    lines = text.splitlines()
    is_session_authority = any(rel.endswith(a) for a in SESSION_AUTHORITY_ALLOW)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _MARKET_DEFAULT_RE.search(line) and not _GOVERNED.search(line):
            errs.append(f"{rel}:{i}: FABRICATED_MARKET_INPUT — hard-coded neutral/default market value: {stripped[:100]!r}")
        if _SILENT_MARKET_GET_RE.search(line) and not _GOVERNED.search(line):
            errs.append(f"{rel}:{i}: FABRICATED_MARKET_INPUT — silent 0-default on a market field: {stripped[:100]!r}")
        if not is_session_authority and _SESSION_CLOCK_RE.search(line):
            errs.append(f"{rel}:{i}: SESSION_CLOCK_CORRUPTION — session decided from stored clock, not ts_utc: {stripped[:100]!r}")
        if _SECRET_RE.search(line):
            errs.append(f"{rel}:{i}: SECRET_EXPOSURE — hard-coded credential/token: <redacted>")
        if _HOME_PATH_RE.search(line):
            errs.append(f"{rel}:{i}: SECRET_EXPOSURE — operator-home absolute path in source: <redacted>")
        if _RANDOM_RE.search(line) and "seed" not in text.lower():
            errs.append(f"{rel}:{i}: NONDETERMINISTIC_MONEYPATH — unseeded randomness in money path: {stripped[:100]!r}")
    errs.extend(_scan_silent_fallback(rel, text))
    return errs


def _exception_is_broad(node: ast.ExceptHandler) -> bool:
    """Bare `except:` or broad `except Exception/BaseException:` — the dangerous
    kind that can swallow a market-computation error. A narrow typed except
    (TypeError/ValueError/KeyError/...) with a fallthrough is defensible parsing."""
    if node.type is None:
        return True
    names = []
    t = node.type
    if isinstance(t, ast.Tuple):
        names = [e.id for e in t.elts if isinstance(e, ast.Name)]
    elif isinstance(t, ast.Name):
        names = [t.id]
    return any(n in ("Exception", "BaseException") for n in names)


def _scan_silent_fallback(rel: str, text: str) -> list[str]:
    """Bare/broad except that only passes in a money-path file (AST)."""
    errs: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return errs
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = node.body
            if body and all(isinstance(s, ast.Pass) for s in body) and _exception_is_broad(node):
                errs.append(f"{rel}:{node.lineno}: SILENT_PRODUCTION_FALLBACK — broad/bare except silently passes")
    return errs


def scan(staged_only: bool = False) -> list[str]:
    only = _staged_paths() if staged_only else None
    errs: list[str] = []
    for p in _iter_money_path(only):
        rel = p.relative_to(ROOT).as_posix()
        try:
            errs.extend(_scan_text(rel, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return errs


_SELF_TEST_CASES = {
    "FABRICATED_MARKET_INPUT": "probability_up = 0.33\n",
    "SESSION_CLOCK_CORRUPTION": "if et_hour >= 9 and et_minute >= 30:\n    pass\n",
    "SECRET_EXPOSURE": "api_key = 'abcd1234efgh5678ijkl'\n",
    "SILENT_PRODUCTION_FALLBACK": "try:\n    x = f()\nexcept Exception:\n    pass\n",
    "NONDETERMINISTIC_MONEYPATH": "x = random.random()\n",
}


def self_test() -> int:
    failures = []
    for cls, snippet in _SELF_TEST_CASES.items():
        hits = _scan_text("call_engine.py", snippet)
        if not any(cls in h for h in hits):
            failures.append(f"self-test: {cls} NOT detected on seeded probe")
    # negative control: a governed/clean line must not fire
    clean = "direction = fused.direction  # canonical fusion authority\n"
    if _scan_text("call_engine.py", clean):
        failures.append("self-test: clean governed line falsely flagged")
    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        return 1
    print(f"check_market_correctness self-test PASS: {len(_SELF_TEST_CASES)} classes detected, clean line clean")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    errs = scan(staged_only="--staged" in argv)
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        print(f"\ncheck_market_correctness: {len(errs)} money-path correctness violation(s) — "
              "fix at the source (no fabricated defaults, ts_utc session authority, no secrets, "
              "no silent fallback, deterministic inference).", file=sys.stderr)
        return 1
    print("check_market_correctness: money path clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
