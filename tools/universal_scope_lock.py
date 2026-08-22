"""UNIVERSAL ticker-scope lock helpers (RC-160).

Operator mandate 2026-07-30: work is UNIVERSAL across the enrolled universe — SPY-only /
sentinel-only framing without explicit OUT-OF-SCOPE + operator waiver is a breach.

Shared by:
  * tools/check_institutional_correctness.py  (pre-commit BLOCK)
  * tools/pretooluse_guard.py                 (Edit/Write BLOCK for prompts / agent instructions)

Keep this module lean — PreToolUse imports it on every edit.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# Phrases that frame work as SPY-complete (or sentinel-complete) without admitting the carve-out.
_SPY_ONLY_PHRASE = re.compile(
    r"\b(?:"
    r"SPY[\s-]?only|only\s+SPY|at\s+least\s+SPY|just\s+SPY|SPY\s+alone|"
    r"SPY[\s-]?first\s+only|run\s+(?:this\s+)?(?:on|for)\s+SPY\s+only|"
    r"sentinel[\s-]?only\s+(?:is\s+)?(?:complete|enough|done|verified|clean)|"
    r"complete\s+for\s+SPY(?:\s+only)?"
    r")\b",
    re.I,
)
# Escape / compliance language that makes a narrow scope honest.
_UNIVERSAL_OK = re.compile(
    r"\b(?:"
    r"UNIVERSAL|enrolled\s+universe|all\s+enrolled|OUT-OF-SCOPE|"
    r"operator\s+waiver|universal-scope-ok|spy-sample-ok"
    r")\b",
    re.I,
)

_CHART_SPY_CMP = re.compile(
    r"(?:tk|ticker|symbol|chartTicker)\s*===?\s*['\"]SPY['\"]|"
    r"['\"]SPY['\"]\s*===?\s*(?:tk|ticker|symbol|chartTicker)",
    re.I,
)
# Substring match on purpose: Chart helpers are camelCase (drawStormHighlight), so \\bstorm\\b
# would miss the exact shapes this lock must catch.
_CHART_FEATURE = re.compile(r"storm|highlight|combo|accrual", re.I)
_CHART_HARDCODED_API = re.compile(
    r"/api/(?:terrain|terrain/strikes|bars1m|liquidity-snapshot|spot)"
    r"\?ticker=SPY\b",
    re.I,
)
_CHART_PARAM_FETCHES = (
    re.compile(r"/api/bars1m\?ticker=\$\{"),
    re.compile(r"/api/terrain\?ticker=\$\{"),
    re.compile(r"/api/terrain/strikes\?ticker=\$\{"),
)

_PROMPT_PATH_HINT = re.compile(
    r"(?:prompt|agent.?instruction|claude.?finish|cursor.?prompt)",
    re.I,
)


_TICKER_FIX_SCOPE = re.compile(
    r"(?:"
    r"ticker-specific\s+(?:repair|fix|implementation)|"
    r"SPY-only\s+implementation|"
    r"(?:base-three|sentinel)\s+implementation\s+scope|"
    r"fix\s+SPY(?:\s+timestamp|\s+only)|"
    r"if\s+ticker\s*==\s*['\"]SPY['\"]\s*:\s*(?:special_fix|repair)"
    r")",
    re.I,
)


def ticker_specific_implementation_scope_violation(
    text: str,
    *,
    rel: str = "",
) -> str | None:
    """Implementation scoped to a ticker symbol FAILs. Representative tests may use tickers."""
    r = (rel or "").replace("\\", "/").lstrip("./")
    if r.startswith("tests/"):
        return None
    if not text:
        return None
    m = _TICKER_FIX_SCOPE.search(text)
    if not m:
        return None
    sent_start = text.rfind(".", 0, m.start()) + 1
    sentence = text[sent_start:m.end() + 40]
    if re.search(
        r"^\s*(?:[-*•]|\d+\.)?\s*(?:\*\*)?(?:No|Not|Never|Do not|Forbidden)\b",
        sentence,
        re.I,
    ):
        return None
    return (
        f"ticker-specific implementation scope ({m.group(0)!r}) for a universal "
        f"defect — derive behavior from input semantics/contracts, not symbol names"
    )


def is_prompt_or_agent_instruction_path(rel: str) -> bool:
    """Paths whose Write/Edit content is gated for SPY-only framing."""
    r = rel.replace("\\", "/").lstrip("./")
    if r in ("AGENTS.md", "CLAUDE.md", "ACTIVE_PROGRAM.md", "MEMORY.md"):
        return True
    if r.startswith(".cursor/rules/"):
        return True
    if r.startswith(".claude/") and r.endswith((".md", ".mdc", ".txt")):
        return True
    if r.startswith("reports/") and _PROMPT_PATH_HINT.search(Path(r).name):
        return True
    if "prompt" in Path(r).name.lower() and r.endswith((".md", ".mdc", ".txt")):
        return True
    return False


def spy_only_content_violation(text: str) -> str | None:
    """Return a reason when text frames SPY/sentinel as complete without UNIVERSAL escape."""
    if not text or not _SPY_ONLY_PHRASE.search(text):
        return None
    if _UNIVERSAL_OK.search(text):
        return None
    m = _SPY_ONLY_PHRASE.search(text)
    snippet = (m.group(0) if m else "SPY-only").strip()
    return (
        f"SPY-only / sentinel-complete framing ({snippet!r}) without UNIVERSAL, "
        f"enrolled-universe, or OUT-OF-SCOPE + operator waiver language (RC-160)"
    )


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _ticker_list_from_ast(node: ast.AST) -> list[str] | None:
    """Return ticker symbols if `node` is a literal list/tuple/str of tickers; else None."""
    s = _const_str(node)
    if s is not None:
        parts = [p.strip().upper() for p in s.replace(";", ",").split(",") if p.strip()]
        return parts or None
    if isinstance(node, (ast.List, ast.Tuple)):
        out: list[str] = []
        for elt in node.elts:
            v = _const_str(elt)
            if v is None:
                return None
            out.append(v.strip().upper())
        return out
    return None


def _is_spy_only_tickers(tickers: list[str]) -> bool:
    return len(tickers) == 1 and tickers[0] == "SPY"


def _has_scope_escape(src: str, lineno: int) -> bool:
    """True when the line or the contiguous comment block above it carries an escape marker."""
    lines = src.splitlines()
    i = max(0, lineno - 1)
    window = lines[max(0, i - 6): i + 1]
    blob = "\n".join(window)
    return bool(
        re.search(r"universal-scope-ok|spy-sample-ok|OUT-OF-SCOPE|operator\s+waiver", blob, re.I)
    )


def spy_only_ticker_default_violations(path: Path, src: str) -> list[tuple[int, str]]:
    """AST: argparse --tickers default or module TICKERS/DEFAULT_TICKERS that is SPY alone."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # add_argument("--tickers", default="SPY") / default=["SPY"]
        if isinstance(node, ast.Call):
            args_are_tickers = any(
                isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value in (
                    "--tickers", "tickers",
                )
                for a in node.args
            )
            if not args_are_tickers:
                continue
            for kw in node.keywords:
                if kw.arg != "default":
                    continue
                tickers = _ticker_list_from_ast(kw.value)
                if tickers is None or not _is_spy_only_tickers(tickers):
                    continue
                if _has_scope_escape(src, node.lineno):
                    continue
                hits.append((
                    node.lineno,
                    f"--tickers default is SPY-only ({tickers!r}); use enrolled universe "
                    f"or mark # universal-scope-ok: OUT-OF-SCOPE: <reason> (RC-160)",
                ))
        # Module-level TICKERS = ["SPY"] / DEFAULT_TICKERS = ("SPY",)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if not isinstance(t, ast.Name):
                    continue
                if t.id not in ("TICKERS", "DEFAULT_TICKERS", "TICKER_UNIVERSE"):
                    continue
                tickers = _ticker_list_from_ast(node.value)
                if tickers is None or not _is_spy_only_tickers(tickers):
                    continue
                if _has_scope_escape(src, node.lineno):
                    continue
                hits.append((
                    node.lineno,
                    f"{t.id} is SPY-only ({tickers!r}); use enrolled universe or mark "
                    f"# universal-scope-ok: OUT-OF-SCOPE: <reason> (RC-160)",
                ))
    return hits


def chart_spy_only_feature_violations(src: str) -> list[tuple[int, str]]:
    """Flag Chart storm/highlight/combo/accrual branches keyed only to SPY."""
    if "universal-scope-ok" in src.lower():
        # File-level escape for a deliberate, documented carve-out.
        if re.search(r"universal-scope-ok\s*:", src, re.I):
            return []
    hits: list[tuple[int, str]] = []
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if _CHART_HARDCODED_API.search(line) and not re.search(
            r"universal-scope-ok|OUT-OF-SCOPE", line, re.I
        ):
            hits.append((
                i + 1,
                "Chart API URL hardcodes ticker=SPY; Chart paths must stay "
                "ticker-parameterized (RC-160)",
            ))
            continue
        if not _CHART_SPY_CMP.search(line):
            continue
        lo = max(0, i - 8)
        hi = min(len(lines), i + 9)
        ctx = "\n".join(lines[lo:hi])
        if not _CHART_FEATURE.search(ctx):
            continue
        if re.search(r"universal-scope-ok|OUT-OF-SCOPE|operator\s+waiver", ctx, re.I):
            continue
        hits.append((
            i + 1,
            "Chart storm/highlight/combo/accrual path branches on SPY only; features must "
            "be ticker-parameterized or declare OUT-OF-SCOPE (RC-160)",
        ))
    return hits


def chart_ticker_path_violations(src: str) -> list[tuple[int, str]]:
    """Chart load path must keep parameterized ticker fetches (enrolled rotation surface)."""
    missing = [p.pattern for p in _CHART_PARAM_FETCHES if not p.search(src)]
    if not missing:
        return []
    return [(
        1,
        "Chart ticker path lost parameterized fetch(es): "
        + ", ".join(missing)
        + " — enrolled Chart rotation must stay ticker-parameterized (RC-160)",
    )]


def experiment_tool_paths(repo: Path) -> list[Path]:
    """Experiment / liquidity study tools whose ticker defaults are policed."""
    tools = repo / "tools"
    if not tools.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(tools.glob("liquidity_*.py")):
        out.append(p)
    for p in sorted(tools.glob("*_experiment*.py")):
        if p not in out:
            out.append(p)
    for p in sorted(tools.glob("lp01_*.py")):
        if p not in out:
            out.append(p)
    return out
