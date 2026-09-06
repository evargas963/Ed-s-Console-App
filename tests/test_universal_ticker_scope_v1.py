# institutional-synthetic-ok: these tests INJECT SPY-only violations to prove the RC-160 lock
# BLOCKS — that is their entire purpose.
"""RC-160: UNIVERSAL ticker-scope lock — fire on SPY-only, quiet on enrolled/UNIVERSAL."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_institutional_correctness as C  # noqa: E402
import tools.universal_scope_lock as U  # noqa: E402


def test_universal_ticker_scope_is_enforced():
    assert ("universal_ticker_scope", True) in [(n, e) for n, _f, e in C.CHECKS]


def test_spy_only_ticker_default_blocks_and_universal_allows(tmp_path):
    bad = tmp_path / "liquidity_zz_spy_only_v1.py"
    bad.write_text(
        "import argparse\n"
        "ap = argparse.ArgumentParser()\n"
        'ap.add_argument("--tickers", default="SPY")\n',
        encoding="utf-8",
    )
    hits = U.spy_only_ticker_default_violations(bad, bad.read_text(encoding="utf-8"))
    assert hits, "SPY-only --tickers default was not flagged — lock inert"

    good = tmp_path / "liquidity_zz_enrolled_v1.py"
    good.write_text(
        "import argparse\n"
        "ap = argparse.ArgumentParser()\n"
        'ap.add_argument("--tickers", default="SPY,QQQ,IWM")\n',
        encoding="utf-8",
    )
    assert U.spy_only_ticker_default_violations(good, good.read_text(encoding="utf-8")) == []

    waived = tmp_path / "liquidity_zz_waived_v1.py"
    waived.write_text(
        "import argparse\n"
        "ap = argparse.ArgumentParser()\n"
        "# universal-scope-ok: OUT-OF-SCOPE: operator waiver — SPY smoke only\n"
        'ap.add_argument("--tickers", default="SPY")\n',
        encoding="utf-8",
    )
    assert U.spy_only_ticker_default_violations(
        waived, waived.read_text(encoding="utf-8")
    ) == [], "documented OUT-OF-SCOPE waiver was wrongly blocked"


def test_chart_spy_only_feature_gate_blocks_and_parameterized_allows():
    bad = (
        "function paint() {\n"
        "  if (tk === 'SPY') {\n"
        "    drawStormHighlight();\n"
        "  }\n"
        "}\n"
    )
    hits = U.chart_spy_only_feature_violations(bad)
    assert hits, "SPY-only storm/highlight branch was not flagged"

    good = (
        "function load() {\n"
        "  const tk = currentChartTicker();\n"
        "  j(`/api/bars1m?ticker=${tk}&limit=3000`);\n"
        "  j(`/api/terrain?ticker=${tk}`);\n"
        "  j(`/api/terrain/strikes?ticker=${tk}`);\n"
        "  drawStormHighlight(tk);\n"
        "}\n"
    )
    assert U.chart_spy_only_feature_violations(good) == []
    assert U.chart_ticker_path_violations(good) == []

    missing = "function load() { j('/api/bars1m?limit=3000'); }\n"
    assert U.chart_ticker_path_violations(missing), (
        "Chart path missing parameterized ticker fetches was not flagged"
    )


def test_check_universal_ticker_scope_screams_on_injected_tool(tmp_path, monkeypatch):
    """Full check path: a SPY-only liquidity tool under a fake repo must produce >=1 violation."""
    tools = tmp_path / "tools"
    tools.mkdir()
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "chart.html").write_text(
        "j(`/api/bars1m?ticker=${tk}`);\n"
        "j(`/api/terrain?ticker=${tk}`);\n"
        "j(`/api/terrain/strikes?ticker=${tk}`);\n",
        encoding="utf-8",
    )
    (tools / "liquidity_zz_block_me_v1.py").write_text(
        "import argparse\n"
        "ap = argparse.ArgumentParser()\n"
        'ap.add_argument("--tickers", default="SPY")\n'
        "TICKERS = ['SPY']\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(C, "REPO", tmp_path)
    # Outside a commit context staged scan returns [] — tool AST scan must still fire.
    bad = C.check_universal_ticker_scope()
    assert any("SPY-only" in str(v) or "SPY alone" in str(v) or "SPY-only" in v.msg
               or "SPY" in v.msg for v in bad), (
        f"injected SPY-only liquidity tool was not blocked: {bad}"
    )

    (tools / "liquidity_zz_block_me_v1.py").write_text(
        "import argparse\n"
        "ap = argparse.ArgumentParser()\n"
        'ap.add_argument("--tickers", default="SPY,QQQ,IWM")\n',
        encoding="utf-8",
    )
    assert C.check_universal_ticker_scope() == [], (
        "enrolled-universe default was wrongly blocked"
    )


def test_live_tree_liquidity_defaults_are_not_spy_only():
    """Sanity: committed liquidity_* tools must not currently violate (no grandfathering)."""
    for path in U.experiment_tool_paths(ROOT):
        hits = U.spy_only_ticker_default_violations(
            path, path.read_text(encoding="utf-8", errors="ignore")
        )
        assert hits == [], f"{path.name} has SPY-only ticker default: {hits}"
