"""Tests for tools/schwab_universal_coverage_scanner_v3 — V3 contract Step 2 bar + V4 M1 closure."""

from __future__ import annotations

import os

os.environ.setdefault("SCHWAB_SCANNER_EMBEDDINGS", "mock")

from pathlib import Path

import pytest

from tools.schwab_universal_coverage_scanner_v3.catch_all import scan_catch_all_lines
from tools.schwab_universal_coverage_scanner_v3.cli import run_scan
from tools.schwab_universal_coverage_scanner_v3.cross_validate import cross_validate_python_file
from tools.schwab_universal_coverage_scanner_v3.html_scanner import scan_html_file
from tools.schwab_universal_coverage_scanner_v3.js_ts_scanner import scan_js_ts_text
from tools.schwab_universal_coverage_scanner_v3.paths import (
    is_binary_sample,
    try_decode_utf8,
    walk_workspace_files,
)
from tools.schwab_universal_coverage_scanner_v3.python_scanner import scan_python_complete, scan_python_source
from tools.schwab_universal_coverage_scanner_v3.reconciliation import (
    ReconciliationState,
    inventory_mark_present,
    scan_family,
)
from tools.schwab_universal_coverage_scanner_v3.register import RegisterRow
from tools.schwab_universal_coverage_scanner_v3.reverse_coverage import build_reverse_coverage_rows
from tools.schwab_universal_coverage_scanner_v3.schwab_csv import SchwabCsvIndex
from tools.schwab_universal_coverage_scanner_v3.sql_scan import scan_sql_file
from tools.schwab_universal_coverage_scanner_v3.structured_scan import (
    scan_ini_file,
    scan_json_file,
    scan_toml_file,
    scan_yaml_file,
)
from tools.schwab_universal_coverage_scanner_v3.markdown_scan import scan_markdown_file
from tools.schwab_universal_coverage_scanner_v3.vocabulary import tokenize_for_vocabulary


@pytest.fixture
def mini_csv(tmp_path: Path) -> Path:
    p = tmp_path / "schwab_field_dictionary.csv"
    p.write_text(
        "canonical_field,description,category,likely_use\n"
        "quotes.quote.bidPrice,bid side,opt,quote\n"
        "quotes.quote.askPrice,ask side,opt,quote\n"
        "quotes.greeks.theta,theta desc,opt,greek\n"
        "quotes.meta.timeClock,clock desc,meta,time\n"
        "quotes.default.bucket,default theta bucket,opt,default\n"
        "quotes.pipeline.computeTheta,compute Theta path,opt,compute\n"
        "quotes.w.computetheta,compute theta ident,opt,compute\n"
        "quotes.session.clockDateTime,session datetime field,opt,datetime\n"
        "quotes.session.nowMarker,now session marker,opt,now\n"
        "quotes.mark.datetimeTag,tag,datetime,mark\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def idx(mini_csv: Path) -> SchwabCsvIndex:
    return SchwabCsvIndex(mini_csv)


def test_vocabulary_derivation(idx: SchwabCsvIndex) -> None:
    v = idx.vocabulary
    assert "bid" in v.tokens
    assert v.contains_word("theta")


def test_tokenize_for_vocabulary_camel() -> None:
    toks = tokenize_for_vocabulary("lastPriceDelta", min_len=3)
    assert "last" in toks or "price" in toks or "delta" in toks


def test_catch_all_unusual_extension(idx: SchwabCsvIndex) -> None:
    text = "symbol = theta\n"
    rows = scan_catch_all_lines("x.proto", text, idx, {}, language="proto")
    assert any("theta" in r.tokens for r in rows)


def test_scan_family_unknown_ext() -> None:
    assert scan_family(".proto") == "catch_all_text"


def test_binary_detection() -> None:
    assert is_binary_sample(b"a\x00b") is True
    assert is_binary_sample(b"hello") is False


def test_utf8_decode_failure() -> None:
    raw = bytes([0xFF, 0xFE, 0xFD])
    text, err = try_decode_utf8(raw)
    assert text is None and err is not None


def test_python_subscript_vocab(idx: SchwabCsvIndex) -> None:
    src = 'x = row["theta"]\n'
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "SUBSCRIPT_MARKET_KEY" for r in rows)


def test_python_getattr(idx: SchwabCsvIndex) -> None:
    src = "v = getattr(o, 'theta')\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "PYTHON_GETATTR_SETATTR" for r in rows)


def test_cross_validator_miss(idx: SchwabCsvIndex) -> None:
    src = "s = 'theta fallback'\n"
    py_rows = scan_python_source("t.py", src, idx, {})
    miss = cross_validate_python_file("t.py", src, py_rows, idx)
    assert any(r.pattern_kind == "pattern_kind_miss" for r in miss)


@pytest.mark.parametrize(
    "src,kind",
    [
        ("Reflect.get(a,b);\n", "REFLECT_API"),
        ("new Proxy(x,{});\n", "PROXY_TRAP"),
        ("eval('1');\n", "DYNAMIC_EVAL"),
        ("new Function('return 1');\n", "DYNAMIC_EVAL"),
        ("import(m);\n", "DYNAMIC_IMPORT"),
        ("obj[k];\n", "COMPUTED_PROPERTY"),
        ("const o = { theta: 1 };\n", "REGISTRY_DISPATCH"),
        (
            "const o = {};\nconst k = 'x';\nObject.defineProperty(o, k, {});\n",
            "COMPUTED_DEFINE_PROPERTY",
        ),
    ],
)
def test_js_ts_kinds(idx: SchwabCsvIndex, src: str, kind: str) -> None:
    rows, ok = scan_js_ts_text("f.ts", src, idx, {}, "typescript")
    assert ok
    assert any(r.pattern_kind == kind for r in rows)


def test_m1_js_registry_dispatch_const_h(idx: SchwabCsvIndex) -> None:
    src = "const H = {a: 1};\n"
    rows, ok = scan_js_ts_text("h.ts", src, idx, {}, "typescript")
    assert ok
    assert any(r.pattern_kind == "REGISTRY_DISPATCH" for r in rows)


def test_sql_dynamic(idx: SchwabCsvIndex) -> None:
    src = "SELECT * FROM t WHERE x = 'a' + bid;\n"
    rows = scan_sql_file("q.sql", src, idx, {})
    assert any(r.pattern_kind == "DYNAMIC_SQL_BUILD" for r in rows)


def test_m1_sql_static_market_token(idx: SchwabCsvIndex) -> None:
    src = "SELECT theta FROM t;\n"
    rows = scan_sql_file("q.sql", src, idx, {})
    assert any(r.pattern_kind == "SQL_STATIC_MARKET_TOKEN" for r in rows)


def test_json_walk(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    jf = tmp_path / "a.json"
    jf.write_text('{"theta": 1}', encoding="utf-8")
    rows, ok = scan_json_file("a.json", jf, idx, {})
    assert ok
    assert rows
    assert any(r.pattern_kind == "JSON_KEY_MARKET_TOKEN" for r in rows)


def test_m1_json_string_market_token(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    jf = tmp_path / "s.json"
    jf.write_text('{"x": "theta value"}', encoding="utf-8")
    rows, ok = scan_json_file("s.json", jf, idx, {})
    assert ok
    assert any(r.pattern_kind == "JSON_STRING_MARKET_TOKEN" for r in rows)


def test_m1_yaml_key_market_token(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    yk = tmp_path / "k.yaml"
    yk.write_text("theta: 1\n", encoding="utf-8")
    rows, ok = scan_yaml_file("k.yaml", yk, idx, {})
    assert ok
    assert any(r.pattern_kind == "YAML_KEY_MARKET_TOKEN" for r in rows)


def test_m1_yaml_string_market_token(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    ys = tmp_path / "s.yaml"
    ys.write_text('x: "theta context"\n', encoding="utf-8")
    rows, ok = scan_yaml_file("s.yaml", ys, idx, {})
    assert ok
    assert any(r.pattern_kind == "YAML_STRING_MARKET_TOKEN" for r in rows)


def test_m1_toml_key_market_token(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    tf = tmp_path / "k.toml"
    tf.write_text("theta = 1\n", encoding="utf-8")
    rows, ok = scan_toml_file("k.toml", tf, idx, {})
    assert ok
    assert any(r.pattern_kind == "TOML_KEY_MARKET_TOKEN" for r in rows)


def test_m1_toml_string_market_token(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    tf = tmp_path / "s.toml"
    tf.write_text('x = "theta context"\n', encoding="utf-8")
    rows, ok = scan_toml_file("s.toml", tf, idx, {})
    assert ok
    assert any(r.pattern_kind == "TOML_STRING_MARKET_TOKEN" for r in rows)


def test_m1_ini_key_market_token(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    inf = tmp_path / "k.ini"
    inf.write_text("[s]\ntheta = 1\n", encoding="utf-8")
    rows, ok = scan_ini_file("k.ini", inf, idx, {})
    assert ok
    assert any(r.pattern_kind == "INI_KEY_MARKET_TOKEN" for r in rows)


def test_m1_ini_string_market_token(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    inf = tmp_path / "s.ini"
    inf.write_text("[s]\nx = theta\n", encoding="utf-8")
    rows, ok = scan_ini_file("s.ini", inf, idx, {})
    assert ok
    assert any(r.pattern_kind == "INI_STRING_MARKET_TOKEN" for r in rows)


def test_m1_html_attr_market_token(idx: SchwabCsvIndex) -> None:
    html = "<!DOCTYPE html><html><body><div data-theta=\"1\"></div></body></html>\n"
    rows, ok = scan_html_file("x.html", html, idx, {})
    assert ok
    assert any(r.pattern_kind == "HTML_ATTR_MARKET_TOKEN" for r in rows)


def test_m1_html_script_reflect_set(idx: SchwabCsvIndex) -> None:
    html = (
        '<!DOCTYPE html><html><body><script>Reflect.set(a,"theta",1);</script>'
        "</body></html>\n"
    )
    rows, ok = scan_html_file("x.html", html, idx, {})
    assert ok
    assert any(
        r.pattern_kind == "REFLECT_API" and r.language == "javascript" for r in rows
    )


def test_m1_markdown_fence_theta_assign(idx: SchwabCsvIndex) -> None:
    md = "```python\ntheta = 1\n```\n"
    rows, ok = scan_markdown_file("d.md", md, idx, {})
    assert ok
    assert any(r.pattern_kind == "MAGIC_NUMERIC_DEFAULT" for r in rows)


def test_catch_all_text_line_market_token(idx: SchwabCsvIndex) -> None:
    rows = scan_catch_all_lines("n.txt", "theta = 1\n", idx, {}, language="text")
    assert any(r.pattern_kind == "TEXT_LINE_MARKET_TOKEN" for r in rows)


def test_m1_python_dynamic_dispatch(idx: SchwabCsvIndex) -> None:
    src = "class A:\n    def __getattr__(self, n):\n        return None\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "DYNAMIC_DISPATCH" for r in rows)


def test_m1_python_attribute_market(idx: SchwabCsvIndex) -> None:
    src = "class O: pass\no = O()\nx = o.theta\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "ATTRIBUTE_MARKET" for r in rows)


def test_m1_python_dict_literal_market_key(idx: SchwabCsvIndex) -> None:
    src = 'd = {"theta": 1}\n'
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "DICT_LITERAL_MARKET_KEY" for r in rows)


def test_m1_python_binop_bid_minus_ask(idx: SchwabCsvIndex) -> None:
    src = "bid = 1\nask = 2\nx = bid - ask\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "BINOP_MARKET_IDENT" for r in rows)


def test_m1_python_bool_or_default_zero_bid(idx: SchwabCsvIndex) -> None:
    src = "bid = 1\nx = bid or 0\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "BOOL_OR_DEFAULT_ZERO" for r in rows)


def test_m1_python_ifexp_bid(idx: SchwabCsvIndex) -> None:
    src = "bid = 1\nx = bid if bid else 0\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "IFEXP_ZERO_DEFAULT" for r in rows)


def test_m1_python_dict_get_market_default(idx: SchwabCsvIndex) -> None:
    src = "d = {}\nx = d.get(\"theta\", 0)\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "DICT_GET_MARKET_DEFAULT" for r in rows)


def test_m1_python_getattr_market_literal(idx: SchwabCsvIndex) -> None:
    src = "o = object()\nx = getattr(o, \"theta\", 0)\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "GETATTR_MARKET_LITERAL" for r in rows)


def test_m1_python_coerce_float_bid_or_zero(idx: SchwabCsvIndex) -> None:
    src = "bid = 1\nx = float(bid or 0)\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "COERCE_OR_ZERO" for r in rows)


def test_m1_python_time_time(idx: SchwabCsvIndex) -> None:
    src = "import time\nx = time.time()\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "TIME_TIME" for r in rows)


def test_m1_python_time_monotonic(idx: SchwabCsvIndex) -> None:
    src = "import time\nx = time.monotonic()\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "TIME_MONOTONIC" for r in rows)


def test_m1_python_datetime_now(idx: SchwabCsvIndex) -> None:
    src = "from datetime import datetime\nx = datetime.now()\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "DATETIME_NOW" for r in rows)


def test_m1_python_call_compute_theta(idx: SchwabCsvIndex) -> None:
    """Directive `compute_theta(...)` ↔ CSV token `computetheta` (V3-A path segment)."""
    src = (
        "def computetheta():\n"
        "    return 1\n"
        "computetheta()\n"
    )
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "CALL_NAMED_DERIVATION" for r in rows)


def test_m1_python_magic_default_theta(idx: SchwabCsvIndex) -> None:
    src = "default_theta = 0.5\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "MAGIC_NUMERIC_DEFAULT" for r in rows)


def test_m1_python_decorator_site(idx: SchwabCsvIndex) -> None:
    src = "@dec\ndef f():\n    pass\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "DECORATOR_SITE" for r in rows)


def test_m1_python_registry_dispatch_h(idx: SchwabCsvIndex) -> None:
    src = "def f():\n    pass\ndef g():\n    pass\nH = {\"a\": f, \"b\": g}\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "REGISTRY_DISPATCH" for r in rows)


def test_yaml_parse_failure(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    yf = tmp_path / "bad.yaml"
    yf.write_text("{ not: valid yaml [[\n", encoding="utf-8")
    rows, ok = scan_yaml_file("bad.yaml", yf, idx, {})
    assert not ok
    assert rows == []


def test_reverse_coverage_counts(idx: SchwabCsvIndex) -> None:
    rows = scan_catch_all_lines("f.py", "theta = 1\n", idx, {}, language="python")
    rev = build_reverse_coverage_rows(rows, idx)
    assert len(rev) == len(idx.all_canonical_fields())
    statuses = {r["canonical_field"]: r["status"] for r in rev}
    assert statuses["quotes.greeks.theta"] == "field_referenced"
    assert statuses["quotes.quote.bidPrice"] == "field_orphaned"


def test_reconciliation_a_eq_b_plus_c(tmp_path: Path, mini_csv: Path, monkeypatch) -> None:
    inv = tmp_path / "schwab_field_inventory"
    inv.mkdir(parents=True)
    dict_path = inv / "schwab_field_dictionary.csv"
    dict_path.write_text(mini_csv.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "tools.schwab_universal_coverage_scanner_v3.cli.default_dictionary_path",
        lambda: dict_path,
    )
    out = tmp_path / "out.csv"
    summary = run_scan(tmp_path, out, include_dot_claude=True)
    fam = summary["reconciliation"]["criterion_1_reconciliation"]["per_scan_family"]["python"]
    assert fam["(d)_reconciles_a_eq_b_plus_c"] is True
    assert fam["(b)_files_scanned"] >= 1


def test_binary_file_excluded_from_scan(tmp_path: Path, mini_csv: Path, monkeypatch) -> None:
    inv = tmp_path / "schwab_field_inventory"
    inv.mkdir(parents=True)
    dict_path = inv / "schwab_field_dictionary.csv"
    dict_path.write_text(mini_csv.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")
    monkeypatch.setattr(
        "tools.schwab_universal_coverage_scanner_v3.cli.default_dictionary_path",
        lambda: dict_path,
    )
    out = tmp_path / "o.csv"
    summary = run_scan(tmp_path, out, include_dot_claude=True)
    fam = summary["reconciliation"]["criterion_1_reconciliation"]["per_scan_family"]["catch_all_text"]
    assert fam["(c)_files_excluded"] >= 1
    ex = fam["exclusions"]
    assert any("V3-B binary file" in str(e.get("clause", "")) for e in ex)


def test_prune_records_callback(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "obj").mkdir(parents=True)
    (tmp_path / ".git" / "obj" / "x").write_text("a", encoding="utf-8")
    batches: list = []

    def cb(batch) -> None:
        batches.append(batch)

    list(walk_workspace_files(tmp_path, on_prune=cb))
    assert any(b.dir_kind == ".git" for b in batches)


def test_inventory_dot_claude_skip() -> None:
    st = ReconciliationState()
    r = inventory_mark_present(st, "a/.claude/x.py", ".py", include_dot_claude=False)
    assert r == "skip_claude"
    fam = st.family("python")
    assert fam.a_present == 1
    assert fam.c_excluded == 1


def test_register_id_stable() -> None:
    a = RegisterRow.make_id("p.py", 1, 0, "K", "python")
    b = RegisterRow.make_id("p.py", 1, 0, "K", "python")
    assert a == b
