"""Tests for tools/schwab_market_derivation_catalog_v1.py (AST catalog scaffold)."""

from __future__ import annotations

import csv
from pathlib import Path

from tools.schwab_market_derivation_catalog_v1 import (
    ROOT,
    csv_candidates_for_tokens,
    iter_py_files,
    load_schwab_index,
    scan_file,
)


def test_load_schwab_index_maps_tokens(tmp_path: Path) -> None:
    p = tmp_path / "s.csv"
    p.write_text(
        "canonical_field,source_endpoints\n"
        "quotes.quote.bidPrice,quotes\n"
        "chains.callExpDateMap,chains\n",
        encoding="utf-8",
    )
    idx = load_schwab_index(p)
    # TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (weak-assertion item 3): the first
    # assertion was `"bidprice" in idx or "quote" in idx` -- STRICTLY SUBSUMED by the
    # line below it (a non-empty idx["bidprice"] entails "bidprice" in idx), so it
    # added zero detection power, and its `or "quote" in idx` disjunct actively
    # weakened it: an index that never produced the full compound token still passed
    # on the bare "quote" segment alone. Replaced with the exact token->field mapping,
    # which pins what this loader actually owes its one consumer (the
    # csv_candidate_fields column of the coverage register).
    assert idx["bidprice"] == ["quotes.quote.bidPrice"], (
        f"token must map to the FULL canonical field, not a segment; got {idx.get('bidprice')!r}")
    assert sorted(idx) == ["bidprice", "callexpdatemap", "chains", "quote", "quotes"], (
        f"tokenizer emitted an unexpected key set: {sorted(idx)}")


def test_csv_candidates_for_tokens_caps() -> None:
    idx = {
        "bid": ["quotes.quote.bidPrice", "chains.x.bid"],
        "ask": ["quotes.quote.askPrice"],
    }
    s = csv_candidates_for_tokens(idx, ["bid", "ask"])
    assert "quotes.quote.bidPrice" in s


def test_visitor_mid_div_and_dict_get(tmp_path: Path) -> None:
    src = '''
bid = 1.0
ask = 2.0
mid = (bid + ask) / 2
q = {}
v = q.get("volume", 0)
'''
    f = tmp_path / "x.py"
    f.write_text(src, encoding="utf-8")
    findings: list = []
    scan_file(f, tmp_path, findings)
    kinds = {f.pattern_kind for f in findings}
    assert "BINOP_DIV_MARKET_IDENT" in kinds
    assert "DICT_GET_MARKET_DEFAULT" in kinds


def test_iter_py_files_skips_dot_claude_by_default(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "worktrees" / "x").mkdir(parents=True)
    (tmp_path / ".claude" / "worktrees" / "x" / "dup.py").write_text(
        "bid=1\nask=2\ny=(bid+ask)/2\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "a.py").parent.mkdir(parents=True)
    (tmp_path / "pkg" / "a.py").write_text("x=1\n", encoding="utf-8")
    n_default = len(list(iter_py_files(tmp_path, include_tests=True)))
    n_with_claude = len(
        list(
            iter_py_files(
                tmp_path,
                include_tests=True,
                include_claude_worktrees=True,
            )
        )
    )
    assert n_with_claude == n_default + 1


def test_cli_smoke_writes_csv(tmp_path: Path, monkeypatch) -> None:
    import subprocess
    import sys

    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "market_dummy.py").write_text(
        "def f(bid, ask):\n    return (bid + ask) / 2\n",
        encoding="utf-8",
    )
    schwab = tmp_path / "dict.csv"
    schwab.write_text(
        "canonical_field,source_endpoints\nquotes.quote.bidPrice,q\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "schwab_market_derivation_catalog_v1.py"),
            "--root",
            str(tmp_path),
            "--schwab-csv",
            str(schwab),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert out.is_file()
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert any(rw.get("pattern_kind") == "BINOP_DIV_MARKET_IDENT" for rw in rows)
