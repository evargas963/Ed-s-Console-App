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
