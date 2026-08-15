"""F39: missing confluence is typed absence at the /api/state + DOM consumer."""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Cross-asset weighted_push compute sites (not ML cf_* — that is RC-318).
F39_WEIGHTED_PUSH_PRODUCERS = frozenset(
    {
        "market_context.py:_build_confluence",
        "market_context.py:_build_iwm_confluence",
        "market_context.py:weighted_push_from_constituents",
        "market_context.py:blend_iwm_weighted_push",
        "market_context.py:weighted_pushes_from_snapshot_row",
        "market_context.py:iwm_blended_participation_push",
    }
)

SKIP_PARTS = frozenset(
    {".git", "__pycache__", "tests", "archive", "node_modules", ".venv"}
)


def _py_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_PARTS for part in p.parts):
            continue
        if "governance/archive" in "/".join(p.parts):
            continue
        out.append(p)
    return out


def test_f39_enumerates_every_weighted_push_producer():
    """Tree-wide: every assignment that computes weighted_push is a named producer."""
    found: set[str] = set()
    for path in _py_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for t in child.targets:
                        if isinstance(t, ast.Name) and t.id == "weighted_push":
                            found.add(f"{rel}:{node.name}")
                if isinstance(child, ast.Return) and isinstance(
                    child.value, ast.Call
                ):
                    fn = child.value.func
                    name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                    if name == "ConfluenceRead":
                        found.add(f"{rel}:{node.name}")
    compute = {s for s in found if s.startswith("market_context.py:_build_")}
    assert compute <= F39_WEIGHTED_PUSH_PRODUCERS, compute
    for req in (
        "market_context.py:_build_confluence",
        "market_context.py:_build_iwm_confluence",
        "market_context.py:weighted_push_from_constituents",
    ):
        assert req in F39_WEIGHTED_PUSH_PRODUCERS


def test_f39_no_confluence_key_literal_anywhere_in_server_ast():
    """RC-378 (Cursor gate-width residual: `ms_dict.setdefault("cf_weighted_push", 0)`
    passes BOTH regex shapes below). The typed mapper line carries no key literals, so
    the lock is a zero-count over the AST: NO confluence display key may appear as a
    string constant anywhere in server.py. setdefault, `|=`, dict(...), __setitem__ —
    every reshape that NAMES a key trips this; only the typed mapper stays possible."""
    keys = {
        "cf_weighted_push", "cf_label", "cf_color", "cf_dot_green", "cf_dot_total",
        "qqq_cf_weighted_push", "iwm_cf_push", "iwm_holdings_cf_push",
        "iwm_participation_push",
    }
    tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
    hits = [
        (n.lineno, n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in keys
    ]
    assert hits == [], (
        f"server.py names a confluence display key outside the typed mapper: {hits} — "
        "stamp_confluence_display_fields must stay the ONLY faucet (F39/RC-365)")


def test_f39_missing_confluence_is_none_not_zero_at_consumer():
    """Producer _build_confluence → stamp → #cf-push-val. Empty inputs → None / —."""
    from market_context import (
        ConstituentQuote,
        MarketContext,
        SPY_TOP_WEIGHT_SUM,
        _build_confluence,
        stamp_confluence_display_fields,
    )

    empty = _build_confluence([], SPY_TOP_WEIGHT_SUM)
    assert empty.weighted_push is None
    assert empty.weighted_push != 0

    no_chg = _build_confluence(
        [ConstituentQuote(symbol="AAPL", label="AAPL", weight=0.07, chg_pct=None)],
        SPY_TOP_WEIGHT_SUM,
    )
    assert no_chg.weighted_push is None

    mixed = _build_confluence(
        [
            ConstituentQuote(symbol="AAPL", label="AAPL", weight=0.07, chg_pct=0.0),
            ConstituentQuote(symbol="MSFT", label="MSFT", weight=0.07, chg_pct=0.0),
        ],
        SPY_TOP_WEIGHT_SUM,
    )
    assert mixed.weighted_push == 0.0

    ctx = MarketContext()
    ctx.confluence = empty
    stamped = stamp_confluence_display_fields(ctx)
    assert stamped["cf_weighted_push"] is None
    assert stamped["cf_dot_green"] is None
    assert stamped["cf_dot_total"] is None
    assert stamp_confluence_display_fields(None)["cf_weighted_push"] is None

    server = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "ms_dict.update(stamp_confluence_display_fields(mkt_ctx))" in server
    # RC-375 (Cursor audit: existence of the mapper line does not prove uniqueness):
    # the mapper must be the ONLY /api/state confluence stamp — no direct ms_dict
    # writes of any confluence display key anywhere in server.py.
    import re as _re
    for key in ("cf_weighted_push", "cf_label", "cf_color", "cf_dot_green",
                "cf_dot_total", "qqq_cf_weighted_push", "iwm_cf_push",
                "iwm_holdings_cf_push", "iwm_participation_push"):
        # RC-376 widening (Cursor gate-width note): both quote styles for the
        # subscript write, plus dict-literal update forms — a reshaped second
        # stamp must not slip a double-quote-only regex.
        direct = _re.findall(rf'ms_dict\[\s*[\'"]{key}[\'"]\s*\]\s*=', server)
        assert direct == [], (
            f"a second /api/state confluence stamp writes {key!r} directly — the "
            "typed mapper must stay the ONLY faucet (F39/RC-365)")
        dict_form = _re.findall(rf'ms_dict\.update\(\s*\{{[^)]*[\'"]{key}[\'"]', server)
        assert dict_form == [], (
            f"a dict-literal ms_dict.update writes {key!r} outside the typed mapper "
            "(F39/RC-365)")

    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="cf-push-val"' in html
    start = html.find("// Weighted push")
    assert start != -1
    block = html[start : start + 400]
    assert "d.cf_weighted_push" in block
    assert "pushEl.textContent = pushDisp" in html
    # Live consumer expressions from index.html (not a reconstructed proxy).
    lines = [ln.strip() for ln in block.splitlines()]
    raw_line = [ln for ln in lines if "const pushRaw" in ln][0]
    push_line = [ln for ln in lines if ln.startswith("const push ") or ln.startswith("const push=")][0]
    disp_line = [ln for ln in lines if "const pushDisp" in ln][0]
    render = raw_line + "\n" + push_line + "\n" + disp_line + "\n"
    script = (
        "function renderPush(d){\n"
        + render
        + "  return pushDisp;\n"
        + "}\n"
        + "if (renderPush({cf_weighted_push: null}) !== '—') { console.error('absent'); process.exit(1); }\n"
        + "if (renderPush({cf_weighted_push: 0}) !== '+0.00%') { console.error('neutral'); process.exit(1); }\n"
        + "console.log('ok');\n"
    )
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "ok" in proc.stdout
