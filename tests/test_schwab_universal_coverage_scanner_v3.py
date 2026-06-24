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
    is_verification_audit_json,
    rel_is_scope_excluded_file,
    try_decode_utf8,
    walk_workspace_files,
    PruneBatch,
    rel_matches_prefix,
)
from tools.schwab_universal_coverage_scanner_v3.python_scanner import scan_python_source
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


def test_m1_python_dict_get_market_nullable_single_arg(idx: SchwabCsvIndex) -> None:
    """#8 Phase A: single-arg .get('wireKey') emits a distinct nullable-semantic row."""
    src = "d = {}\nx = d.get(\"theta\")\n"
    rows = scan_python_source("t.py", src, idx, {})
    nullable = [r for r in rows if r.pattern_kind == "DICT_GET_MARKET_NULLABLE"]
    assert nullable, f"expected DICT_GET_MARKET_NULLABLE; got {[(r.pattern_kind, r.surface_form) for r in rows]!r}"
    assert nullable[0].surface_form == ".get('theta')"
    # Two-arg kind must NOT fire on single-arg call (pattern_kind separation).
    assert not any(r.pattern_kind == "DICT_GET_MARKET_DEFAULT" for r in rows)


def test_m1_python_dict_get_two_arg_still_emits_default_kind(idx: SchwabCsvIndex) -> None:
    """Regression: existing DICT_GET_MARKET_DEFAULT branch unchanged by the if/else split."""
    src = "d = {}\nx = d.get(\"theta\", 0)\n"
    rows = scan_python_source("t.py", src, idx, {})
    assert any(r.pattern_kind == "DICT_GET_MARKET_DEFAULT" for r in rows)
    assert not any(r.pattern_kind == "DICT_GET_MARKET_NULLABLE" for r in rows)


def test_m1_python_dict_get_camel_key_hits_vocab_via_csv_split(idx: SchwabCsvIndex) -> None:
    """server.py L2334-style fixture: _q.get('quoteTime') must emit NULLABLE kind.

    Vocab match comes from _string_key_hits_vocab → tokenize_for_vocabulary
    (CSV-side camel-split) — independent of words_in_line catch-all asymmetry.
    Mini-CSV fixture above seeds 'quotes.quote.bidPrice', so token 'quote' is in vocab.
    """
    src = 'q = {}\nx = q.get("quoteTime")\n'
    rows = scan_python_source("t.py", src, idx, {})
    nullable = [r for r in rows if r.pattern_kind == "DICT_GET_MARKET_NULLABLE"]
    assert nullable, (
        f"expected NULLABLE emission for single-arg .get('quoteTime'); "
        f"got {[(r.pattern_kind, r.surface_form) for r in rows]!r}"
    )
    assert nullable[0].surface_form == ".get('quoteTime')"


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


def test_prune_node_modules_and_inventory_dumps(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "junk.js").write_text("export const bid = 1\n", encoding="utf-8")
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "site.py").write_text("rho = 1\n", encoding="utf-8")
    inv = tmp_path / "schwab_field_inventory" / "pricehistory" / "raw"
    inv.mkdir(parents=True)
    (inv / "big.json").write_text('{"last": 1}\n', encoding="utf-8")
    batches: list[PruneBatch] = []

    def cb(b: PruneBatch) -> None:
        batches.append(b)

    files = {
        p.relative_to(tmp_path).as_posix()
        for p in walk_workspace_files(
            tmp_path,
            on_prune=cb,
            respect_gitignore=False,
            scope_exclude_prefixes=(),
        )
    }
    assert "keep.py" in files
    assert "node_modules/pkg/junk.js" not in files
    assert ".venv/lib/site.py" not in files
    assert "schwab_field_inventory/pricehistory/raw/big.json" not in files
    assert any(b.dir_kind == "node_modules" for b in batches)
    assert any(b.dir_kind == ".venv" for b in batches)
    assert any(b.dir_kind == "inventory_or_backup_dump" for b in batches)


def test_scope_exclude_tools_prefix(tmp_path: Path) -> None:
    (tmp_path / "root.py").write_text("x = 1\n", encoding="utf-8")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "audit.py").write_text("bid = 1\n", encoding="utf-8")
    batches: list[PruneBatch] = []

    files = {
        p.relative_to(tmp_path).as_posix()
        for p in walk_workspace_files(
            tmp_path,
            on_prune=batches.append,
            respect_gitignore=False,
            scope_exclude_prefixes=("tools",),
        )
    }
    assert files == {"root.py"}
    assert any(b.dir_kind == "scan_scope_exclude" for b in batches)


def test_d17_scope_excludes_generated_surfaces_but_keeps_money_path(tmp_path: Path) -> None:
    from tools.schwab_universal_coverage_scanner_v3.paths import SCAN_SCOPE_EXCLUDE_PREFIXES

    (tmp_path / "server.py").write_text("bid = 1\n", encoding="utf-8")
    (tmp_path / "market_state.py").write_text("ask = 1\n", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "audit.json").write_text('{"bid": 1}\n', encoding="utf-8")
    artifacts = tmp_path / "governance" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "REPO_HYGIENE_INVENTORY.json").write_text('{"bid": 1}\n', encoding="utf-8")
    slices = tmp_path / "governance" / "register_slices"
    slices.mkdir(parents=True)
    (slices / "server_py.csv").write_text("register_id\nx\n", encoding="utf-8")
    (tmp_path / "governance" / "SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv").write_text(
        "canonical_field\nquotes.quote.bidPrice\n",
        encoding="utf-8",
    )
    (tmp_path / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md").write_text(
        "# program law\n",
        encoding="utf-8",
    )

    files = {
        p.relative_to(tmp_path).as_posix()
        for p in walk_workspace_files(
            tmp_path,
            on_prune=lambda _b: None,
            respect_gitignore=False,
            scope_exclude_prefixes=SCAN_SCOPE_EXCLUDE_PREFIXES,
        )
    }
    assert "server.py" in files
    assert "market_state.py" in files
    assert "governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md" in files
    assert "reports/audit.json" not in files
    assert "governance/artifacts/REPO_HYGIENE_INVENTORY.json" not in files
    assert "governance/register_slices/server_py.csv" not in files
    assert "governance/SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv" not in files


def test_d17_scope_excludes_verification_audit_json_keeps_verification_py(tmp_path: Path) -> None:
    from tools.schwab_universal_coverage_scanner_v3.paths import SCAN_SCOPE_EXCLUDE_PREFIXES

    ver = tmp_path / "verification"
    ver.mkdir()
    (ver / "adaptive_shadow_v2_calibration.json").write_text('{"bid": 1}\n', encoding="utf-8")
    (ver / "daily_health.py").write_text("bid = 1\n", encoding="utf-8")
    (tmp_path / "server.py").write_text("ask = 1\n", encoding="utf-8")

    files = {
        p.relative_to(tmp_path).as_posix()
        for p in walk_workspace_files(
            tmp_path,
            on_prune=lambda _b: None,
            respect_gitignore=False,
            scope_exclude_prefixes=SCAN_SCOPE_EXCLUDE_PREFIXES,
        )
    }
    assert "verification/daily_health.py" in files
    assert "verification/adaptive_shadow_v2_calibration.json" not in files
    assert "server.py" in files
    assert is_verification_audit_json("verification/adaptive_shadow_v2_calibration.json")
    assert not is_verification_audit_json("verification/daily_health.py")
    assert rel_is_scope_excluded_file(
        "verification/adaptive_shadow_v2_calibration.json",
        SCAN_SCOPE_EXCLUDE_PREFIXES,
    )
    assert not rel_is_scope_excluded_file("verification/daily_health.py", SCAN_SCOPE_EXCLUDE_PREFIXES)


def test_gitignore_excludes_ignored_subtree(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("secret/\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "hid.py").write_text("bid = 1\n", encoding="utf-8")
    batches: list[PruneBatch] = []

    files = {
        p.relative_to(tmp_path).as_posix()
        for p in walk_workspace_files(
            tmp_path,
            on_prune=batches.append,
            respect_gitignore=True,
            scope_exclude_prefixes=(),
        )
    }
    assert files == {"keep.py", ".gitignore"}
    assert any(b.dir_kind == "gitignore" for b in batches)


def test_rel_matches_prefix() -> None:
    assert rel_matches_prefix("tools/check.py", "tools")
    assert rel_matches_prefix("tools", "tools")
    assert not rel_matches_prefix("mytools/x.py", "tools")


def test_prune_records_callback(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "obj").mkdir(parents=True)
    (tmp_path / ".git" / "obj" / "x").write_text("a", encoding="utf-8")
    batches: list = []

    def cb(batch) -> None:
        batches.append(batch)

    list(
        walk_workspace_files(
            tmp_path,
            on_prune=cb,
            respect_gitignore=False,
            scope_exclude_prefixes=(),
        )
    )
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


def test_disposition_merge_surface_omitted_when_duplicate_lines(tmp_path: Path) -> None:
    """Same surface key on two lines → do not surface-merge (avoids cross-site REPLACED spill)."""
    from tools.schwab_universal_coverage_scanner_v3.cli import _load_disposition_merge_maps
    from tools.schwab_universal_coverage_scanner_v3.register import write_register_csv

    surf = "        return {}"

    def make_row(rid: str, line: int) -> RegisterRow:
        return RegisterRow(
            register_id=rid,
            language="py",
            path="server.py",
            line=line,
            col=0,
            pattern_kind="TEXT_LINE_MARKET_TOKEN",
            surface_form=surf,
            tokens="t",
            csv_candidates="chains.x",
            csv_lexical_topk_note="",
            v2_trace="",
            disposition="REPLACED",
            canonical_field_citation="chains.callExpDateMap.*.expirationDate",
            governed_ref="governance/artifacts/perf_proof/replacements/pp_x.json",
            notes="",
        )

    reg = tmp_path / "prior.csv"
    write_register_csv(reg, [make_row("aaaaaaaaaaaaaaaaaaaa", 2050), make_row("bbbbbbbbbbbbbbbbbbbb", 4478)])
    _by_site, _by_id, by_surface = _load_disposition_merge_maps(reg)
    key = ("server.py", surf.strip(), "TEXT_LINE_MARKET_TOKEN", "py")
    assert key not in by_surface


def test_disposition_merge_surface_kept_when_single_line(tmp_path: Path) -> None:
    from tools.schwab_universal_coverage_scanner_v3.cli import _load_disposition_merge_maps
    from tools.schwab_universal_coverage_scanner_v3.register import write_register_csv

    surf = "        return {}"
    rows = [
        RegisterRow(
            register_id="aaaaaaaaaaaaaaaaaaaa",
            language="py",
            path="server.py",
            line=2050,
            col=0,
            pattern_kind="TEXT_LINE_MARKET_TOKEN",
            surface_form=surf,
            tokens="t",
            csv_candidates="chains.x",
            csv_lexical_topk_note="",
            v2_trace="",
            disposition="REPLACED",
            canonical_field_citation="chains.callExpDateMap.*.expirationDate",
            governed_ref="governance/artifacts/perf_proof/replacements/pp_x.json",
            notes="",
        ),
    ]
    reg = tmp_path / "prior2.csv"
    write_register_csv(reg, rows)
    _by_site, _by_id, by_surface = _load_disposition_merge_maps(reg)
    key = ("server.py", surf.strip(), "TEXT_LINE_MARKET_TOKEN", "py")
    assert key in by_surface
    assert by_surface[key]["disposition"] == "REPLACED"


def test_disposition_merge_surface_omitted_cross_pattern_kind(tmp_path: Path) -> None:
    """Same surface on two lines with different pattern_kind → no surface merge (947bbc7+)."""
    from tools.schwab_universal_coverage_scanner_v3.cli import _load_disposition_merge_maps
    from tools.schwab_universal_coverage_scanner_v3.register import write_register_csv

    surf = "        return {}"
    rows = [
        RegisterRow(
            register_id="aaaaaaaaaaaaaaaaaaaa",
            language="py",
            path="server.py",
            line=2050,
            col=0,
            pattern_kind="TEXT_LINE_MARKET_TOKEN",
            surface_form=surf,
            tokens="t",
            csv_candidates="chains.x",
            csv_lexical_topk_note="",
            v2_trace="",
            disposition="REPLACED",
            canonical_field_citation="chains.callExpDateMap.*.expirationDate",
            governed_ref="governance/artifacts/perf_proof/replacements/pp_x.json",
            notes="",
        ),
        RegisterRow(
            register_id="bbbbbbbbbbbbbbbbbbbb",
            language="cross_validator",
            path="server.py",
            line=4478,
            col=0,
            pattern_kind="pattern_kind_miss",
            surface_form=surf,
            tokens="t",
            csv_candidates="chains.x",
            csv_lexical_topk_note="",
            v2_trace="",
            disposition="REPLACED",
            canonical_field_citation="chains.callExpDateMap.*.expirationDate",
            governed_ref="governance/artifacts/perf_proof/replacements/pp_x.json",
            notes="independent path vs python AST",
        ),
    ]
    reg = tmp_path / "cross_kind.csv"
    write_register_csv(reg, rows)
    _by_site, _by_id, by_surface = _load_disposition_merge_maps(reg)
    assert not by_surface


def test_apply_disposition_merge_skips_by_id_when_surface_differs(tmp_path: Path) -> None:
    from tools.schwab_universal_coverage_scanner_v3.cli import (
        _apply_disposition_merge,
        _load_disposition_merge_maps,
    )
    from tools.schwab_universal_coverage_scanner_v3.register import write_register_csv

    prior_surf = "        return {}"
    new_surf = "    transformer_available=getattr(ms, 'transformer_available', None)"
    rid = RegisterRow.make_id("server.py", 4478, 0, "pattern_kind_miss", "cross_validator")
    write_register_csv(
        tmp_path / "prior.csv",
        [
            RegisterRow(
                register_id=rid,
                language="cross_validator",
                path="server.py",
                line=4478,
                col=0,
                pattern_kind="pattern_kind_miss",
                surface_form=prior_surf,
                tokens="t",
                csv_candidates="",
                csv_lexical_topk_note="",
                v2_trace="",
                disposition="REPLACED",
                canonical_field_citation="chains.x",
                governed_ref="governance/artifacts/perf_proof/replacements/pp_x.json",
                notes="",
            ),
        ],
    )
    _by_site, by_id, _by_surface = _load_disposition_merge_maps(tmp_path / "prior.csv")
    row = RegisterRow(
        register_id=rid,
        language="cross_validator",
        path="server.py",
        line=4478,
        col=0,
        pattern_kind="pattern_kind_miss",
        surface_form=new_surf,
        tokens="t",
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace="",
        disposition="UNREVIEWED",
        canonical_field_citation="",
        governed_ref="",
        notes="independent path vs python AST",
    )
    _apply_disposition_merge([row], {}, by_id, {})
    assert row.disposition == "UNREVIEWED"
    assert row.canonical_field_citation == ""


def test_cross_validator_skips_line_covered_by_catch_all(tmp_path: Path, idx: SchwabCsvIndex) -> None:
    """Catch-all (language=py) coverage prevents spurious pattern_kind_miss on same line."""
    from tools.schwab_universal_coverage_scanner_v3.catch_all import scan_catch_all_lines
    from tools.schwab_universal_coverage_scanner_v3.cross_validate import cross_validate_python_file

    src = "v = getattr(o, 'theta')\n"
    py_rows = scan_catch_all_lines("t.py", src, idx, {}, language="py")
    assert py_rows
    miss = cross_validate_python_file("t.py", src, py_rows, idx)
    assert not any(r.line == py_rows[0].line for r in miss)


def test_mechanical_pass_non_product_prefix() -> None:
    from tools.track_a_module_docstring_nmd_pass import _apply_pass

    row = {
        "path": "governance/OPEN_ITEMS.md",
        "line": "1",
        "disposition": "UNREVIEWED",
        "pattern_kind": "TEXT_LINE_MARKET_TOKEN",
    }
    disp, note = _apply_pass(row, {})
    assert disp == "NOT_MARKET_DATA"
    assert "non-product" in note


def test_mechanical_pass_skips_reviewed() -> None:
    from tools.track_a_module_docstring_nmd_pass import _apply_pass

    row = {
        "path": "server.py",
        "line": "1",
        "disposition": "REPLACED",
        "pattern_kind": "TEXT_LINE_MARKET_TOKEN",
    }
    assert _apply_pass(row, {}) is None


def test_mechanical_pass_streaming_zero_unreviewed(tmp_path: Path) -> None:
    from tools.track_a_module_docstring_nmd_pass import run

    reg = tmp_path / "reg.csv"
    reg.write_text(
        "register_id,language,path,line,col,pattern_kind,surface_form,tokens,"
        "csv_candidates,csv_lexical_topk_note,v2_trace,disposition,"
        "canonical_field_citation,governed_ref,notes\n"
        "abc,md,governance/x.md,1,0,TEXT_LINE_MARKET_TOKEN,bid,,,,,UNREVIEWED,,,\n",
        encoding="utf-8",
    )
    rep = run(register=reg, dry_run=False, skip_tail=False)
    assert rep["rows_updated"] == 1
    text = reg.read_text(encoding="utf-8")
    assert "UNREVIEWED" not in text
    assert "NOT_MARKET_DATA" in text


def test_write_register_build_meta_skips_non_canonical_output(tmp_path: Path) -> None:
    """Canonical-register guard: non-canonical --output must not corrupt the global meta pin."""
    from tools.schwab_universal_coverage_scanner_v3.cli import (
        CANONICAL_REGISTER_REL,
        REGISTER_BUILD_META_REL,
        write_register_build_meta,
    )

    root = tmp_path
    (root / "governance" / "artifacts").mkdir(parents=True)
    meta_path = root / REGISTER_BUILD_META_REL
    pinned = {
        "register_content_sha256": "deadbeef" * 8,
        "register_rows_written": 174459,
        "register_csv_path": CANONICAL_REGISTER_REL,
    }
    import json as _json

    meta_path.write_text(_json.dumps(pinned), encoding="utf-8")

    non_canonical = tmp_path / "tmp_dry_run.csv"
    non_canonical.write_text("register_id,disposition\nabc,UNREVIEWED\n", encoding="utf-8")

    write_register_build_meta(
        root,
        non_canonical,
        {"files_attempted": 1, "register_rows": 1},
        max_files=None,
        embedding_mode_cli="mock",
        include_dot_claude=False,
        respect_gitignore=True,
        scope_exclude_prefixes=(),
    )
    after = _json.loads(meta_path.read_text(encoding="utf-8"))
    assert after == pinned  # untouched


def test_write_register_build_meta_writes_canonical_output(tmp_path: Path) -> None:
    """Canonical-register guard: canonical --output continues to update meta."""
    from tools.schwab_universal_coverage_scanner_v3.cli import (
        CANONICAL_REGISTER_REL,
        REGISTER_BUILD_META_REL,
        write_register_build_meta,
    )

    root = tmp_path
    canonical = root / CANONICAL_REGISTER_REL
    canonical.parent.mkdir(parents=True)
    canonical.write_text("register_id,disposition\nxyz,UNREVIEWED\n", encoding="utf-8")
    (root / "governance" / "artifacts").mkdir(parents=True, exist_ok=True)

    write_register_build_meta(
        root,
        canonical,
        {"files_attempted": 1, "register_rows": 1},
        max_files=None,
        embedding_mode_cli="mock",
        include_dot_claude=False,
        respect_gitignore=True,
        scope_exclude_prefixes=("governance/archive",),
    )
    import json as _json

    meta = _json.loads((root / REGISTER_BUILD_META_REL).read_text(encoding="utf-8"))
    assert meta["register_rows_written"] == 1
    assert meta["register_csv_path"] == CANONICAL_REGISTER_REL
    assert meta["scanner_flags"]["scope_exclude_prefixes"] == ["governance/archive"]


def test_phase2_contract_test_denylist_count() -> None:
    from governance.phase2_d17_contract_test_denylist import PHASE2_CONTRACT_TEST_DENYLIST

    assert len(PHASE2_CONTRACT_TEST_DENYLIST) == 107


def test_phase2_slice_files_scope_and_dispositions() -> None:
    import csv
    from pathlib import Path

    from governance.phase2_d17_contract_test_denylist import (
        MEGA_INVENTORY_PATHS,
        MONEY_PATH_PATHS,
        PHASE2_CONTRACT_TEST_DENYLIST,
        ROOT_PROGRAM_LAW_PATHS,
    )

    root = Path(__file__).resolve().parents[1]
    slice_dir = root / "governance" / "register_slices"
    expected = {
        "phase2_governance_md_not_market_data.csv": 4170,
        "phase2_docs_md_not_market_data.csv": 4040,
        "phase2_mega_inventories_not_market_data.csv": 3038,
        "phase2_tests_non_contract_not_market_data.csv": 14772,
    }
    forbidden_runtime = {
        "server.py",
        "db.py",
        "market_state.py",
        "schwab_client.py",
        "live_market_plane.py",
    } | set(MONEY_PATH_PATHS)
    for name, want in expected.items():
        path = slice_dir / name
        assert path.is_file(), name
        rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
        assert len(rows) == want, name
        for row in rows:
            assert (row.get("disposition") or "").strip() == "NOT_MARKET_DATA", name
            rel = (row.get("path") or "").replace("\\", "/")
            assert rel not in ROOT_PROGRAM_LAW_PATHS, rel
            assert rel not in forbidden_runtime, rel
            assert not rel.startswith("features/"), rel
            assert not rel.startswith("static/"), rel
            if name == "phase2_tests_non_contract_not_market_data.csv":
                assert rel.startswith("tests/"), rel
                assert rel not in PHASE2_CONTRACT_TEST_DENYLIST, rel
            if name == "phase2_governance_md_not_market_data.csv":
                assert rel.startswith("governance/") and rel.endswith(".md"), rel
            if name == "phase2_mega_inventories_not_market_data.csv":
                assert rel in MEGA_INVENTORY_PATHS, rel


def test_phase2_slice_merge_leaves_contract_tests_unreviewed(tmp_path: Path) -> None:
    import csv
    import shutil

    from governance.phase2_d17_contract_test_denylist import (
        MONEY_PATH_PATHS,
        PHASE2_CONTRACT_TEST_DENYLIST,
    )
    from tools.stream_revert_v4_register_and_sync_perf import merge_register_slices

    repo = Path(__file__).resolve().parents[1]
    src_reg = repo / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
    if not src_reg.is_file():
        pytest.skip("canonical register not generated locally")

    reg = tmp_path / "register.csv"
    shutil.copy2(src_reg, reg)
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    for name in (
        "phase2_governance_md_not_market_data.csv",
        "phase2_docs_md_not_market_data.csv",
        "phase2_mega_inventories_not_market_data.csv",
        "phase2_tests_non_contract_not_market_data.csv",
    ):
        shutil.copy2(repo / "governance" / "register_slices" / name, slice_dir / name)

    def _count(pred) -> int:
        n = 0
        with reg.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("disposition") or "").strip() != "UNREVIEWED":
                    continue
                p = (row.get("path") or "").replace("\\", "/")
                if pred(p):
                    n += 1
        return n

    money_before = _count(lambda p: p in MONEY_PATH_PATHS)
    deny_before = _count(lambda p: p in PHASE2_CONTRACT_TEST_DENYLIST)
    assert deny_before > 0

    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 26020

    assert _count(lambda p: p in MONEY_PATH_PATHS) == money_before
    assert _count(lambda p: p in PHASE2_CONTRACT_TEST_DENYLIST) == deny_before
    assert _count(lambda p: p.startswith("governance/") and p.endswith(".md")) == 0
    assert _count(lambda p: p.startswith("tests/") and p not in PHASE2_CONTRACT_TEST_DENYLIST) == 0


def test_phase3_adapter_wire_denylist_count() -> None:
    from governance.phase3_d17_adapter_boundary import (
        PHASE3_ADAPTER_WIRE_DENYLIST,
        PHASE3_WIRE_DISPOSITIONS,
        WIRE_PATTERN_KINDS,
    )

    assert len(PHASE3_ADAPTER_WIRE_DENYLIST) == 65
    assert PHASE3_ADAPTER_WIRE_DENYLIST == set(PHASE3_WIRE_DISPOSITIONS)
    for rid, spec in PHASE3_WIRE_DISPOSITIONS.items():
        assert spec.disposition in {
            "REPLACED",
            "KEEP_DERIVED",
            "NOT_MARKET_DATA",
            "GOVERNED_EXCEPTION",
        }, rid
        if spec.disposition == "REPLACED":
            assert spec.canonical_field_citation, rid
            assert spec.governed_ref.endswith(".json"), rid
    assert WIRE_PATTERN_KINDS  # imported contract surface frozen in boundary module


def test_phase3_slice_files_scope_and_dispositions() -> None:
    import csv
    from pathlib import Path

    from governance.phase2_d17_contract_test_denylist import MONEY_PATH_PATHS
    from governance.phase3_d17_adapter_boundary import (
        PHASE3_ADAPTER_PATHS,
        PHASE3_ADAPTER_WIRE_DENYLIST,
        PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST,
        WIRE_PATTERN_KINDS,
    )

    root = Path(__file__).resolve().parents[1]
    slice_dir = root / "governance" / "register_slices"
    lexical_name = "phase3_adapter_lexical_not_market_data.csv"
    wire_name = "phase3_adapter_wire_disposition.csv"
    forbidden_runtime = {
        "server.py",
        "db.py",
        "market_state.py",
    } | set(MONEY_PATH_PATHS)

    lex_path = slice_dir / lexical_name
    wire_path = slice_dir / wire_name
    assert lex_path.is_file(), lexical_name
    assert wire_path.is_file(), wire_name

    lex_rows = list(csv.DictReader(lex_path.open(newline="", encoding="utf-8")))
    wire_rows = list(csv.DictReader(wire_path.open(newline="", encoding="utf-8")))
    assert len(lex_rows) == 548, lexical_name
    assert len(wire_rows) == 73, wire_name

    wire_ids_in_slice = set()
    for row in wire_rows:
        rid = (row.get("register_id") or "").strip()
        wire_ids_in_slice.add(rid)
        disp = (row.get("disposition") or "").strip()
        assert disp in {"REPLACED", "KEEP_DERIVED", "NOT_MARKET_DATA"}, wire_name
        rel = (row.get("path") or "").replace("\\", "/")
        assert rel in PHASE3_ADAPTER_PATHS, rel
        assert rel not in forbidden_runtime, rel
        pk = (row.get("pattern_kind") or "").strip()
        if rid in PHASE3_ADAPTER_WIRE_DENYLIST:
            assert pk in WIRE_PATTERN_KINDS, rid
        if rid in PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST:
            assert disp == "KEEP_DERIVED", rid
        assert rid not in PHASE3_ADAPTER_WIRE_DENYLIST or rid in wire_ids_in_slice

    assert PHASE3_ADAPTER_WIRE_DENYLIST <= wire_ids_in_slice
    assert PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST <= wire_ids_in_slice

    for row in lex_rows:
        assert (row.get("disposition") or "").strip() == "NOT_MARKET_DATA", lexical_name
        rel = (row.get("path") or "").replace("\\", "/")
        assert rel in PHASE3_ADAPTER_PATHS, rel
        assert rel not in forbidden_runtime, rel
        rid = (row.get("register_id") or "").strip()
        assert rid not in PHASE3_ADAPTER_WIRE_DENYLIST, rid
        assert rid not in PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST, rid
        pk = (row.get("pattern_kind") or "").strip()
        assert pk not in WIRE_PATTERN_KINDS, rid


def test_phase3_slice_merge_leaves_money_path_and_runtime_untouched(tmp_path: Path) -> None:
    import csv
    import shutil

    from governance.phase2_d17_contract_test_denylist import MONEY_PATH_PATHS
    from governance.phase3_d17_adapter_boundary import PHASE3_ADAPTER_PATHS
    from tools.stream_revert_v4_register_and_sync_perf import merge_register_slices

    repo = Path(__file__).resolve().parents[1]
    src_reg = repo / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
    if not src_reg.is_file():
        pytest.skip("canonical register not generated locally")

    reg = tmp_path / "register.csv"
    shutil.copy2(src_reg, reg)

    # Repo register may already include Phase 3 merges; reset adapter trio for isolated merge proof.
    fieldnames: list[str] | None = None
    reset_rows: list[dict[str, str]] = []
    with reg.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            p = (row.get("path") or "").replace("\\", "/")
            if p in PHASE3_ADAPTER_PATHS:
                row["disposition"] = "UNREVIEWED"
                row["canonical_field_citation"] = ""
                row["governed_ref"] = ""
                row["notes"] = ""
                row["v2_trace"] = ""
            reset_rows.append(row)
    assert fieldnames
    with reg.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(reset_rows)

    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    for name in (
        "phase3_adapter_lexical_not_market_data.csv",
        "phase3_adapter_wire_disposition.csv",
    ):
        shutil.copy2(repo / "governance" / "register_slices" / name, slice_dir / name)

    def _count(pred) -> int:
        n = 0
        with reg.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("disposition") or "").strip() != "UNREVIEWED":
                    continue
                p = (row.get("path") or "").replace("\\", "/")
                if pred(p):
                    n += 1
        return n

    adapter_before = _count(lambda p: p in PHASE3_ADAPTER_PATHS)
    money_before = _count(lambda p: p in MONEY_PATH_PATHS)
    server_before = _count(lambda p: p == "server.py")
    db_before = _count(lambda p: p == "db.py")
    market_state_before = _count(lambda p: p == "market_state.py")
    assert adapter_before == 621

    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 621

    assert _count(lambda p: p in PHASE3_ADAPTER_PATHS) == 0
    assert _count(lambda p: p in MONEY_PATH_PATHS) == money_before
    assert _count(lambda p: p == "server.py") == server_before
    assert _count(lambda p: p == "db.py") == db_before
    assert _count(lambda p: p == "market_state.py") == market_state_before


def test_phase3_wire_denylist_rows_not_in_lexical_nmd_slice() -> None:
    import csv
    from pathlib import Path

    from governance.phase3_d17_adapter_boundary import (
        PHASE3_ADAPTER_WIRE_DENYLIST,
        PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST,
    )

    root = Path(__file__).resolve().parents[1]
    lex_path = root / "governance" / "register_slices" / "phase3_adapter_lexical_not_market_data.csv"
    lex_ids = {
        (row.get("register_id") or "").strip()
        for row in csv.DictReader(lex_path.open(newline="", encoding="utf-8"))
    }
    assert not PHASE3_ADAPTER_WIRE_DENYLIST & lex_ids
    assert not PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST & lex_ids


def test_phase4_market_state_lexical_denylist_count() -> None:
    from governance.phase4_d17_market_state_boundary import (
        PHASE4_LEXICAL_REGISTER_DENYLIST,
        PHASE4_LEXICAL_WIRE_LINE_DENYLIST,
    )

    assert len(PHASE4_LEXICAL_REGISTER_DENYLIST) == 35
    assert len(PHASE4_LEXICAL_WIRE_LINE_DENYLIST) == 35


def test_phase4_slice_files_scope_and_dispositions() -> None:
    import csv
    from pathlib import Path

    from governance.phase3_d17_adapter_boundary import WIRE_PATTERN_KINDS
    from governance.phase4_d17_market_state_boundary import (
        PHASE4_LEXICAL_PATTERN_KINDS,
        PHASE4_LEXICAL_REGISTER_DENYLIST,
        PHASE4_LEXICAL_WIRE_LINE_DENYLIST,
        PHASE4_MARKET_STATE_PATH,
    )

    root = Path(__file__).resolve().parents[1]
    slice_name = "phase4_market_state_lexical_not_market_data.csv"
    path = root / "governance" / "register_slices" / slice_name
    assert path.is_file(), slice_name

    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    assert len(rows) == 424, slice_name

    for row in rows:
        assert (row.get("disposition") or "").strip() == "NOT_MARKET_DATA", slice_name
        rel = (row.get("path") or "").replace("\\", "/")
        assert rel == PHASE4_MARKET_STATE_PATH, rel
        pk = (row.get("pattern_kind") or "").strip()
        assert pk in PHASE4_LEXICAL_PATTERN_KINDS, pk
        assert pk not in WIRE_PATTERN_KINDS, pk
        rid = (row.get("register_id") or "").strip()
        assert rid not in PHASE4_LEXICAL_REGISTER_DENYLIST, rid
        line = (row.get("line") or "").strip()
        assert line not in PHASE4_LEXICAL_WIRE_LINE_DENYLIST, line
        disp = (row.get("disposition") or "").strip()
        assert disp not in {"REPLACED", "KEEP_DERIVED", "GOVERNED_EXCEPTION"}, rid


def test_phase4_slice_merge_leaves_wire_rows_unreviewed(tmp_path: Path) -> None:
    import csv
    import shutil

    from governance.phase4_d17_market_state_boundary import (
        PHASE4_LEXICAL_PATTERN_KINDS,
        PHASE4_LEXICAL_REGISTER_DENYLIST,
        PHASE4_MARKET_STATE_PATH,
    )
    from tools.stream_revert_v4_register_and_sync_perf import merge_register_slices

    repo = Path(__file__).resolve().parents[1]
    src_reg = repo / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
    if not src_reg.is_file():
        pytest.skip("canonical register not generated locally")

    reg = tmp_path / "register.csv"
    shutil.copy2(src_reg, reg)
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    shutil.copy2(
        repo / "governance" / "register_slices" / "phase4_market_state_lexical_not_market_data.csv",
        slice_dir / "phase4_market_state_lexical_not_market_data.csv",
    )

    def _count_ms(pred) -> int:
        n = 0
        with reg.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("disposition") or "").strip() != "UNREVIEWED":
                    continue
                p = (row.get("path") or "").replace("\\", "/")
                if p != PHASE4_MARKET_STATE_PATH:
                    continue
                if pred(row):
                    n += 1
        return n

    ms_before = _count_ms(lambda _row: True)
    non_lexical_before = _count_ms(
        lambda row: (row.get("pattern_kind") or "").strip() not in PHASE4_LEXICAL_PATTERN_KINDS
    )
    deny_before = _count_ms(
        lambda row: (row.get("register_id") or "").strip() in PHASE4_LEXICAL_REGISTER_DENYLIST
    )
    assert ms_before == 657
    assert non_lexical_before == 198
    assert deny_before == 35

    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] >= 424

    ms_after = _count_ms(lambda _row: True)
    non_lexical_after = _count_ms(
        lambda row: (row.get("pattern_kind") or "").strip() not in PHASE4_LEXICAL_PATTERN_KINDS
    )
    deny_after = _count_ms(
        lambda row: (row.get("register_id") or "").strip() in PHASE4_LEXICAL_REGISTER_DENYLIST
    )

    assert ms_after == 233
    assert ms_before - ms_after == 424
    assert non_lexical_after == non_lexical_before
    assert deny_after == deny_before


def test_phase5a_structural_boundary_frozen_scope() -> None:
    from governance.phase4_d17_market_state_boundary import PHASE4_LEXICAL_WIRE_LINE_DENYLIST
    from governance.phase5a_d17_market_state_structural_boundary import (
        PHASE5A_STRUCTURAL_LINES,
        PHASE5A_STRUCTURAL_PATTERN_KINDS,
        PHASE5A_STRUCTURAL_REGISTER_IDS,
    )

    assert len(PHASE5A_STRUCTURAL_REGISTER_IDS) == 3
    assert PHASE5A_STRUCTURAL_LINES == frozenset({"133", "631", "812"})
    assert PHASE5A_STRUCTURAL_PATTERN_KINDS == frozenset(
        {"DECORATOR_SITE", "REGISTRY_DISPATCH"}
    )
    assert not PHASE5A_STRUCTURAL_LINES & PHASE4_LEXICAL_WIRE_LINE_DENYLIST


def test_phase5a_slice_files_scope_and_dispositions() -> None:
    import csv
    from pathlib import Path

    from governance.phase3_d17_adapter_boundary import WIRE_PATTERN_KINDS
    from governance.phase4_d17_market_state_boundary import (
        PHASE4_LEXICAL_REGISTER_DENYLIST,
        PHASE4_LEXICAL_WIRE_LINE_DENYLIST,
    )
    from governance.phase5a_d17_market_state_structural_boundary import (
        PHASE5A_MARKET_STATE_PATH,
        PHASE5A_STRUCTURAL_LINES,
        PHASE5A_STRUCTURAL_PATTERN_KINDS,
        PHASE5A_STRUCTURAL_REGISTER_IDS,
    )

    root = Path(__file__).resolve().parents[1]
    slice_name = "phase5a_market_state_structural_not_market_data.csv"
    path = root / "governance" / "register_slices" / slice_name
    assert path.is_file(), slice_name

    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
    assert len(rows) == 3, slice_name

    seen_ids: set[str] = set()
    seen_lines: set[str] = set()
    for row in rows:
        assert (row.get("disposition") or "").strip() == "NOT_MARKET_DATA", slice_name
        rel = (row.get("path") or "").replace("\\", "/")
        assert rel == PHASE5A_MARKET_STATE_PATH, rel
        pk = (row.get("pattern_kind") or "").strip()
        assert pk in PHASE5A_STRUCTURAL_PATTERN_KINDS, pk
        assert pk not in WIRE_PATTERN_KINDS, pk
        rid = (row.get("register_id") or "").strip()
        assert rid in PHASE5A_STRUCTURAL_REGISTER_IDS, rid
        seen_ids.add(rid)
        line = (row.get("line") or "").strip()
        assert line in PHASE5A_STRUCTURAL_LINES, line
        seen_lines.add(line)
        assert line not in PHASE4_LEXICAL_WIRE_LINE_DENYLIST, line
        assert rid not in PHASE4_LEXICAL_REGISTER_DENYLIST, rid
        disp = (row.get("disposition") or "").strip()
        assert disp not in {"REPLACED", "KEEP_DERIVED", "PASS_THROUGH", "GOVERNED_EXCEPTION"}, rid

    assert seen_ids == set(PHASE5A_STRUCTURAL_REGISTER_IDS)
    assert seen_lines == set(PHASE5A_STRUCTURAL_LINES)


def test_phase5a_slice_merge_reduces_only_structural_rows(tmp_path: Path) -> None:
    import csv
    import shutil

    from governance.phase3_d17_adapter_boundary import WIRE_PATTERN_KINDS
    from governance.phase4_d17_market_state_boundary import (
        PHASE4_LEXICAL_REGISTER_DENYLIST,
        PHASE4_LEXICAL_WIRE_LINE_DENYLIST,
        PHASE4_MARKET_STATE_PATH,
    )
    from governance.phase5a_d17_market_state_structural_boundary import (
        PHASE5A_STRUCTURAL_LINES,
        PHASE5A_STRUCTURAL_REGISTER_IDS,
    )
    from tools.stream_revert_v4_register_and_sync_perf import merge_register_slices

    repo = Path(__file__).resolve().parents[1]
    src_reg = repo / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
    if not src_reg.is_file():
        pytest.skip("canonical register not generated locally")

    reg = tmp_path / "register.csv"
    shutil.copy2(src_reg, reg)
    slice_dir = tmp_path / "slices"
    slice_dir.mkdir()
    shutil.copy2(
        repo / "governance" / "register_slices" / "phase5a_market_state_structural_not_market_data.csv",
        slice_dir / "phase5a_market_state_structural_not_market_data.csv",
    )

    mixed_lines = set(PHASE4_LEXICAL_WIRE_LINE_DENYLIST)

    def _count_ms(pred) -> int:
        n = 0
        with reg.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                p = (row.get("path") or "").replace("\\", "/")
                if p != PHASE4_MARKET_STATE_PATH:
                    continue
                if pred(row):
                    n += 1
        return n

    structural_before = _count_ms(
        lambda row: (row.get("register_id") or "").strip() in PHASE5A_STRUCTURAL_REGISTER_IDS
        and (row.get("disposition") or "").strip() == "UNREVIEWED"
    )
    wire_unrev_before = _count_ms(
        lambda row: (row.get("disposition") or "").strip() == "UNREVIEWED"
        and (row.get("pattern_kind") or "").strip() in WIRE_PATTERN_KINDS
    )
    deny_unrev_before = _count_ms(
        lambda row: (row.get("disposition") or "").strip() == "UNREVIEWED"
        and (row.get("register_id") or "").strip() in PHASE4_LEXICAL_REGISTER_DENYLIST
    )
    binop_mixed_before = _count_ms(
        lambda row: (row.get("disposition") or "").strip() == "UNREVIEWED"
        and (row.get("pattern_kind") or "").strip() == "BINOP_MARKET_IDENT"
        and (row.get("line") or "").strip() in mixed_lines
    )
    ms_unrev_before = _count_ms(lambda row: (row.get("disposition") or "").strip() == "UNREVIEWED")

    assert structural_before == 3
    assert not (set(PHASE5A_STRUCTURAL_LINES) & mixed_lines)

    rep = merge_register_slices(reg, slice_dir, dry_run=False)
    assert rep["rows_updated"] == 3

    structural_nmd_after = _count_ms(
        lambda row: (row.get("register_id") or "").strip() in PHASE5A_STRUCTURAL_REGISTER_IDS
        and (row.get("disposition") or "").strip() == "NOT_MARKET_DATA"
    )
    wire_unrev_after = _count_ms(
        lambda row: (row.get("disposition") or "").strip() == "UNREVIEWED"
        and (row.get("pattern_kind") or "").strip() in WIRE_PATTERN_KINDS
    )
    deny_unrev_after = _count_ms(
        lambda row: (row.get("disposition") or "").strip() == "UNREVIEWED"
        and (row.get("register_id") or "").strip() in PHASE4_LEXICAL_REGISTER_DENYLIST
    )
    binop_mixed_after = _count_ms(
        lambda row: (row.get("disposition") or "").strip() == "UNREVIEWED"
        and (row.get("pattern_kind") or "").strip() == "BINOP_MARKET_IDENT"
        and (row.get("line") or "").strip() in mixed_lines
    )
    ms_unrev_after = _count_ms(lambda row: (row.get("disposition") or "").strip() == "UNREVIEWED")

    assert structural_nmd_after == 3
    assert ms_unrev_before - ms_unrev_after == 3
    assert wire_unrev_after == wire_unrev_before
    assert deny_unrev_after == deny_unrev_before
    assert binop_mixed_after == binop_mixed_before
