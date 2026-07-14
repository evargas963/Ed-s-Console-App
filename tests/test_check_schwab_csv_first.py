from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_schwab_csv_first as guard


def _time_time_call() -> str:
    return "time" + "." + "time()"


def _quote_time_key() -> str:
    return "quote" + "Time"


def _quotes_quote_time_field() -> str:
    return "quotes.quote." + _quote_time_key()


def test_schwab_csv_authority_loads_expected_inventory():
    fields = guard._load_canonical_fields()

    assert "quotes.quote.lastPrice" in fields
    assert "chains.callExpDateMap.*.multiplier" in fields
    assert len(fields) == 2393


def test_guard_flags_risky_market_data_default_without_marker():
    diff = "\n".join(
        [
            "+++ b/example.py",
            "+spot = row.get(\"spot\") or 0.0",
        ]
    )

    risky = [(path, line) for path, line in guard._added_lines(diff) if guard._is_risky(line)]

    assert risky == [("example.py", "spot = row.get(\"spot\") or 0.0")]
    assert guard._has_marker(diff) is False


def test_guard_accepts_csv_first_marker():
    diff = "\n".join(
        [
            "+++ b/governance/example.md",
            "+Schwab CSV authority checked: yes",
            "+CSV row(s): quotes.quote.lastPrice",
            "+++ b/example.py",
            "+spot = row.get(\"spot\") or 0.0",
        ]
    )

    risky = [(path, line) for path, line in guard._added_lines(diff) if guard._is_risky(line)]

    assert risky
    assert guard._has_marker(diff) is True


def test_guard_identifies_market_data_file_changes():
    diff = "\n".join(
        [
            "+++ b/server.py",
            "+some_non_risky_line = True",
            "+++ b/docs/readme.md",
            "+not market data",
        ]
    )

    changed = sorted(p for p in guard._changed_paths(diff) if guard._is_market_data_path(p))

    assert changed == ["server.py"]


@pytest.mark.parametrize(
    "path",
    [
        "order_flow_engine.py",
        "order_flow_streaming.py",
        "order_flow_live_state.py",
        "lstm_data.py",
        "lstm_model.py",
        "ml_train.py",
        "ml_predict.py",
        "ml_data_common.py",
        "transformer_train.py",
        "transformer_model.py",
        "prediction_engine.py",
        "liquidity_value_engine.py",
    ],
)
def test_guard_market_data_path_coverage_includes_runtime_audit_files(path):
    assert guard._is_market_data_path(path) is True


def test_main_fails_on_market_data_diff_without_csv_marker(monkeypatch, capsys):
    diff = "\n".join(
        [
            "+++ b/server.py",
            "+spot = row.get(\"spot\") or 0.0",
        ]
    )
    monkeypatch.setattr(guard, "_git_diff", lambda *, staged: diff)
    monkeypatch.setattr(sys, "argv", ["check_schwab_csv_first.py"])

    rc = guard.main()

    out = capsys.readouterr().out
    assert rc == 1
    assert "Schwab CSV-first guard FAILED" in out
    assert "CSV row(s): <canonical_field rows or NO_SCHWAB_EQUIVALENT>" in out


def test_main_passes_on_market_data_diff_with_csv_marker(monkeypatch, capsys):
    diff = "\n".join(
        [
            "+++ b/governance/slice.md",
            "+Schwab CSV authority checked: yes",
            "+CSV row(s): quotes.quote.lastPrice",
            "+++ b/server.py",
            "+spot = row.get(\"spot\") or 0.0",
        ]
    )
    monkeypatch.setattr(guard, "_git_diff", lambda *, staged: diff)
    monkeypatch.setattr(sys, "argv", ["check_schwab_csv_first.py"])

    rc = guard.main()

    out = capsys.readouterr().out
    assert rc == 0
    assert "passed with declaration marker" in out


def test_t0_static_index_instrumentation_passes_with_governance_csv_declaration(tmp_path, capsys):
    """T0 class: static/index.html instrumentation without +line CSV markers if declaration is in governance diff."""
    diff = "\n".join(
        [
            "+++ b/docs/CARD_TRUST_CONTRACT.md",
            "+Schwab CSV authority checked: yes",
            "+CSV row(s): NO_SCHWAB_EQUIVALENT",
            "+Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE",
            "+All consumers checked: yes",
            "+SCHWAB_CSV_CHECKED",
            "+++ b/static/index.html",
            "+function _edMplInit() {",
            "+  window.__edMoneyPathLatency = { initialized: true };",
        ]
    )
    diff_file = tmp_path / "t0_repair.diff"
    diff_file.write_text(diff, encoding="utf-8")
    sys.argv = ["check_schwab_csv_first.py", "--diff-file", str(diff_file)]
    rc = guard.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "passed with declaration marker" in out
    assert "static/index.html" in out or "1 market-data file(s)" in out


def test_t2_static_index_raf_scheduler_passes_with_governance_csv_declaration(tmp_path, capsys):
    """T2 class: static/index.html rAF scheduler without +line CSV markers if declaration is in governance diff."""
    diff = "\n".join(
        [
            "+++ b/docs/CARD_TRUST_CONTRACT.md",
            "+Schwab CSV authority checked: yes",
            "+CSV row(s): NO_SCHWAB_EQUIVALENT",
            "+Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE",
            "+All consumers checked: yes",
            "+SCHWAB_CSV_CHECKED",
            "+++ b/static/index.html",
            "+function scheduleMoneyPathRender(d, fullRenderSource, onComplete) {",
            "+  requestAnimationFrame(function _edMplRafFlush() {",
        ]
    )
    diff_file = tmp_path / "t2_repair.diff"
    diff_file.write_text(diff, encoding="utf-8")
    sys.argv = ["check_schwab_csv_first.py", "--diff-file", str(diff_file)]
    rc = guard.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "passed with declaration marker" in out
    assert "static/index.html" in out or "1 market-data file(s)" in out


def test_t3_static_index_monotonic_gate_passes_with_governance_csv_declaration(tmp_path, capsys):
    """T3 class: static/index.html monotonic gate without +line CSV markers if declaration is in governance diff."""
    diff = "\n".join(
        [
            "+++ b/docs/CARD_TRUST_CONTRACT.md",
            "+Schwab CSV authority checked: yes",
            "+CSV row(s): NO_SCHWAB_EQUIVALENT",
            "+Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE",
            "+All consumers checked: yes",
            "+SCHWAB_CSV_CHECKED",
            "+++ b/static/index.html",
            "+function acceptAndScheduleMoneyPathRender(d, fullRenderSource, onComplete) {",
            "+function acceptMoneyPathPayload(d, source) {",
        ]
    )
    diff_file = tmp_path / "t3_repair.diff"
    diff_file.write_text(diff, encoding="utf-8")
    sys.argv = ["check_schwab_csv_first.py", "--diff-file", str(diff_file)]
    rc = guard.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "passed with declaration marker" in out
    assert "static/index.html" in out or "1 market-data file(s)" in out


def test_t4_static_index_freshness_snapshot_passes_with_governance_csv_declaration(tmp_path, capsys):
    """T4 class: static/index.html freshness/snapshot slice with governance CSV declaration."""
    diff = "\n".join(
        [
            "+++ b/docs/CARD_TRUST_CONTRACT.md",
            "+Schwab CSV authority checked: yes",
            "+CSV row(s): NO_SCHWAB_EQUIVALENT",
            "+Derived-field disposition: KEEP_DERIVED_WITH_PROVENANCE",
            "+All consumers checked: yes",
            "+SCHWAB_CSV_CHECKED",
            "+++ b/static/index.html",
            "+function ingestMoneyPathSnapshot(snapshot, source, onComplete) {",
            "+function extractMoneyPathSnapshot(raw) {",
        ]
    )
    diff_file = tmp_path / "t4_repair.diff"
    diff_file.write_text(diff, encoding="utf-8")
    sys.argv = ["check_schwab_csv_first.py", "--diff-file", str(diff_file)]
    rc = guard.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "passed with declaration marker" in out
    assert "static/index.html" in out or "1 market-data file(s)" in out


def test_s3a_static_index_ui_slice_passes_with_governance_csv_declaration(tmp_path, capsys):
    """S3A class: static/index.html changed without +line CSV markers if declaration is in governance diff."""
    diff = "\n".join(
        [
            "+++ b/docs/CARD_TRUST_CONTRACT.md",
            "+Schwab CSV authority checked: yes",
            "+CSV row(s): NO_SCHWAB_EQUIVALENT",
            "+Derived-field disposition: GATE_FAIL_CLOSED",
            "+All consumers checked: yes",
            "+SCHWAB_CSV_CHECKED",
            "+++ b/static/index.html",
            "+function resolveCardTrustGate(d, opts) {",
            "+  if (hasOperatorCardMirrorFields(d)) {",
        ]
    )
    diff_file = tmp_path / "s3a_repair.diff"
    diff_file.write_text(diff, encoding="utf-8")
    sys.argv = ["check_schwab_csv_first.py", "--diff-file", str(diff_file)]
    rc = guard.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "passed with declaration marker" in out
    assert "static/index.html" in out or "1 market-data file(s)" in out


def test_main_can_read_explicit_diff_file(monkeypatch, tmp_path, capsys):
    diff_file = tmp_path / "change.diff"
    diff_file.write_text(
        "\n".join(
            [
                "+++ b/governance/slice.md",
                "+Schwab CSV authority checked: yes",
                "+CSV row(s): quotes.quote.lastPrice",
                "+++ b/ml_train.py",
                "+spot = row.get(\"spot\") or 0.0",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["check_schwab_csv_first.py", "--diff-file", str(diff_file)])

    rc = guard.main()

    out = capsys.readouterr().out
    assert rc == 0
    assert "1 market-data file(s)" in out


def test_main_whole_repo_fails_when_repo_risky_lines_remain(monkeypatch, capsys):
    monkeypatch.setattr(
        guard,
        "_iter_repo_lines",
        lambda: [("server.py", 10, 'spot = row.get("spot") or 0.0')],
    )
    monkeypatch.setattr(sys, "argv", ["check_schwab_csv_first.py", "--whole-repo"])

    rc = guard.main()

    out = capsys.readouterr().out
    assert rc == 1
    assert "whole-repo guard FAILED" in out
    assert "server.py:10" in out


def test_main_whole_repo_passes_when_no_risky_lines(monkeypatch, capsys):
    monkeypatch.setattr(guard, "_iter_repo_lines", lambda: [])
    monkeypatch.setattr(sys, "argv", ["check_schwab_csv_first.py", "--whole-repo"])

    rc = guard.main()

    out = capsys.readouterr().out
    assert rc == 0
    assert "whole-repo guard passed" in out


def test_gatekeeper_crosscheck_bayesian_fusion_homonym_count():
    collisions = guard.lexical_csv_collisions(ROOT / "bayesian_fusion.py")
    assert len(collisions) == 11
    tokens = {c.token for c in collisions}
    assert "high" in tokens
    assert "low" in tokens
    assert "volatility" in tokens
    assert "bidPrice" not in tokens


def test_gatekeeper_memo_requires_section_and_count(tmp_path: Path):
    py = tmp_path / "sample.py"
    py.write_text('x = {"high": 1}\n', encoding="utf-8")
    memo = tmp_path / "sample.py.md"
    memo.write_text("# memo\n", encoding="utf-8")
    errs = guard.check_v4_memo_gatekeeper_csv(memo, repo_root=tmp_path)
    assert any("Gatekeeper CSV cross-check" in e for e in errs)

    memo.write_text(
        "## Gatekeeper CSV cross-check\n**lexical_csv_collision_count:** 99\n",
        encoding="utf-8",
    )
    errs = guard.check_v4_memo_gatekeeper_csv(memo, repo_root=tmp_path)
    assert any("!= tool count" in e for e in errs)


def test_bayesian_fusion_memo_gatekeeper_section_passes():
    memo = ROOT / "governance/SCHWAB_V4_REVIEW_MEMOS/bayesian_fusion.py.md"
    errs = guard.check_v4_memo_gatekeeper_csv(memo, repo_root=ROOT)
    assert errs == []


def test_live_decision_bundle_memo_gatekeeper_section_passes():
    memo = ROOT / "governance/SCHWAB_V4_REVIEW_MEMOS/live_decision_bundle.py.md"
    errs = guard.check_v4_memo_gatekeeper_csv(memo, repo_root=ROOT)
    assert errs == []


def test_gatekeeper_crosscheck_live_decision_bundle_zero_collisions():
    collisions = guard.lexical_csv_collisions(ROOT / "live_decision_bundle.py")
    assert len(collisions) == 0


def test_memo_target_py_path_nested_features():
    memo = ROOT / "governance/SCHWAB_V4_REVIEW_MEMOS/features/signal_layer_v1.py.md"
    py = guard._memo_target_py_path(memo, ROOT)
    assert py == ROOT / "features/signal_layer_v1.py"
    assert py.is_file()


def test_gatekeeper_crosscheck_signal_layer_v1_ohlcv_homonyms():
    collisions = guard.lexical_csv_collisions(ROOT / "features" / "signal_layer_v1.py")
    assert len(collisions) == 82
    tokens = {c.token for c in collisions}
    assert tokens <= {"open", "high", "low", "close", "volume", "_prev_close"}


def test_signal_layer_v1_memo_gatekeeper_section_passes():
    memo = ROOT / "governance/SCHWAB_V4_REVIEW_MEMOS/features/signal_layer_v1.py.md"
    errs = guard.check_v4_memo_gatekeeper_csv(memo, repo_root=ROOT)
    assert errs == []


def test_inference_snapshot_memo_gatekeeper_section_passes():
    memo = ROOT / "governance/SCHWAB_V4_REVIEW_MEMOS/features/inference_snapshot.py.md"
    errs = guard.check_v4_memo_gatekeeper_csv(memo, repo_root=ROOT)
    assert errs == []


def test_fusion_policy_contract_memo_gatekeeper_section_passes():
    memo = ROOT / "governance/SCHWAB_V4_REVIEW_MEMOS/features/fusion_policy_contract.py.md"
    errs = guard.check_v4_memo_gatekeeper_csv(memo, repo_root=ROOT)
    assert errs == []


def test_diff_emission_skips_operator_trust_governance_paths():
    diff = "\n".join(
        [
            "+++ b/tools/check_operator_trust_governance.py",
            '+        errors.append("operator_trust: next_allowed_branch must be audit/ci-nonblocking-failures-triage while CI items open")',
            "+++ b/verification/operator_trust_rth_validation.py",
            '+    ("SPY", "$VIX"),',
        ]
    )
    sites = guard._extract_emission_sites(diff)
    assert sites == []


def test_diff_emission_ignores_english_open_close_without_quoted_keys():
    diff = "\n".join(
        [
            "+++ b/tools/some_helper.py",
            '+    conn.close()',
            '+    # items still open for triage',
        ]
    )
    sites = guard._extract_emission_sites(diff)
    assert sites == []


def test_diff_emission_ignores_homonym_catalog_definition():
    diff = "\n".join(
        [
            "+++ b/tools/check_schwab_csv_first.py",
            '+AMBIGUOUS_MARKET_TOKENS = frozenset({"open", "close", "high", "low", "vix"})',
        ]
    )
    sites = guard._extract_emission_sites(diff)
    assert sites == []


def test_diff_emission_ignores_multiline_non_ticker_catalog_members():
    """Frozenset catalog continuation lines are not market-fact emissions."""
    diff = "\n".join(
        [
            "+++ b/tools/universal_gate_ast.py",
            "+COMMON_NON_TICKERS: frozenset[str] = frozenset(",
            "+    {",
            '+        "ETF", "USD", "EPS", "PE", "IV", "ATR", "VIX", "MACD", "RSI", "EMA",',
            '+        "SMA", "OHLC", "TRUE", "FALSE", "NONE", "NULL", "NAN", "ALL", "ANY",',
            '+        "EST", "PST", "CST", "MST", "EDT", "PDT", "CDT", "MDT", "HIGH", "LOW",',
            '+        "XGB", "DIR", "LIVE", "MARK", "ABOVE", "BELOW", "FIXED", "MIXED",',
            "+    }",
            "+)",
        ]
    )
    sites = guard._extract_emission_sites(diff)
    assert sites == []


def test_diff_emission_skips_mega_traceable_inventory_paths():
    diff = "\n".join(
        [
            "+++ b/governance/mega1_traceable_inventory.py",
            '+    Mega1TraceableDerivation("server.py", 2295, "_parse_quote_node_session_fields", "DERIVED", None, ("schwab_client.py:safe_get_quote",), None, "Reads Schwab quote leaves (lastPrice / mark / bid / ask / quoteTime / tradeTime + extended + regular variants) and derives spot."),',
            "+++ b/governance/mega2_traceable_inventory.py",
            '+    Mega2TraceableDerivation("math_levels.py", 10, "_resolve_bid_ask_prices", "DERIVED", None, (), None, "gamma openInterest volatility mark bid ask"),',
        ]
    )
    sites = guard._extract_emission_sites(diff)
    assert sites == []


def test_diff_emission_still_flags_real_market_fact_emission():
    diff = "\n".join(
        [
            "+++ b/server.py",
            '+    ms_dict["lastPrice"] = row.get("lastPrice")',
        ]
    )
    sites = guard._extract_emission_sites(diff)
    assert sites
    assert any("lastPrice" in s.surfaces for s in sites)


def test_guard_skips_risky_time_time_in_register_slice_ledger():
    time_call = _time_time_call()
    quote_field = _quotes_quote_time_field()
    phase3_row = (
        "07121dccbe05b0dfe39c,py,live_market_plane.py,143,0,TEXT_LINE_MARKET_TOKEN,"
        f"    server_received_ts = {time_call},time,{quote_field}"
    )
    wire_row = (
        "a46779603022537945a5,python,live_market_plane.py,143,25,ATTRIBUTE_MARKET,attr .time,time,"
        f"{quote_field},,NOT_MARKET_DATA,,,server_received_ts wall clock {time_call}"
    )
    diff = "\n".join(
        [
            "+++ b/governance/register_slices/phase3_adapter_lexical_not_market_data.csv",
            f"+{phase3_row}",
            "+++ b/governance/register_slices/phase3_adapter_wire_disposition.csv",
            f"+{wire_row}",
        ]
    )

    assert guard._is_register_slice_ledger_path(
        "governance/register_slices/phase3_adapter_wire_disposition.csv"
    )
    assert guard._risky_added_lines(diff) == []


def test_guard_still_flags_time_time_in_runtime_path_without_marker():
    quote_key = _quote_time_key()
    time_call = _time_time_call()
    runtime_line = f'    ts = row.get("{quote_key}") or {time_call}'
    diff = "\n".join(
        [
            "+++ b/live_market_plane.py",
            f"+{runtime_line}",
        ]
    )

    risky = guard._risky_added_lines(diff)

    assert risky == [("live_market_plane.py", runtime_line)]
    assert guard._has_marker(diff) is False


def test_main_passes_on_phase3_shaped_register_slice_diff_without_csv_marker(
    monkeypatch, tmp_path, capsys
):
    time_call = _time_time_call()
    quote_field = _quotes_quote_time_field()
    lexical_row = (
        f"+8ccf858b87a324cd444f,python,live_market_plane.py,143,25,TIME_TIME,{time_call},"
        f"time time,{quote_field},,NOT_MARKET_DATA,,,Phase 3 lexical"
    )
    wire_row = (
        f"+707587b873e07d0df79b,python,schwab_client.py,152,18,ATTRIBUTE_MARKET,attr .time,time,"
        f"{quote_field},,NOT_MARKET_DATA,,,token expiry wall clock {time_call}"
    )
    diff_file = tmp_path / "phase3_register_slices.diff"
    diff_file.write_text(
        "\n".join(
            [
                "+++ b/governance/register_slices/phase3_adapter_lexical_not_market_data.csv",
                lexical_row,
                "+++ b/governance/register_slices/phase3_adapter_wire_disposition.csv",
                wire_row,
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_schwab_csv_first.py", "--diff-file", str(diff_file)],
    )

    rc = guard.main()

    out = capsys.readouterr().out
    assert rc == 0
    assert "no risky market-data additions found" in out


def test_workflow_pin_check_is_non_circular_and_covers_multi_commit_push():
    """PR-lane repair locks (2026-07-03):

    1. NON-CIRCULAR pin: the scanner OVERWRITES schwab_v4_register_build_meta.json, so
       the old workflow compared the regenerated CSV against the meta the scanner had
       just written — a self-comparison that could never detect drift. The workflow must
       preserve the COMMITTED meta before scanning and compare against that copy.
    2. MULTI-COMMIT push coverage: HEAD~1..HEAD let every non-tip commit of a
       multi-commit push skip the guard; push mode must diff github.event.before..HEAD.
    3. CRASH DIAGNOSTICS: the 2026-07-03 PR runs segfaulted with no frame; the scanner
       must run under faulthandler so the next native crash names its location.
    """
    wf = (ROOT / ".github" / "workflows" / "schwab-csv-first.yml").read_text(encoding="utf-8")
    # (1) committed meta preserved before the scan, and the pin compare reads the copy.
    cp_pos = wf.find(
        "cp governance/artifacts/schwab_v4_register_build_meta.json /tmp/committed_register_meta.json"
    )
    scan_pos = wf.find("-m tools.schwab_universal_coverage_scanner_v3")
    assert cp_pos != -1, "workflow must preserve the committed meta before scanning"
    assert scan_pos != -1
    assert cp_pos < scan_pos, "meta copy must happen BEFORE the scanner can overwrite it"
    assert '"/tmp/committed_register_meta.json"' in wf, (
        "pin compare must read the preserved committed meta, not the workspace file"
    )
    assert 'pathlib.Path("governance/artifacts/schwab_v4_register_build_meta.json").read_text' not in wf.split(
        "Generate V4 register"
    )[1], "pin compare must not read the scanner-overwritten workspace meta"
    # (2) push mode diffs the full pushed range with a null-sha/new-branch fallback.
    assert "github.event.before" in wf
    assert '"$BEFORE"..HEAD' in wf
    assert "0000000000000000000000000000000000000000" in wf
    # (3) faulthandler on the scanner invocation.
    assert "python -X faulthandler -m tools.schwab_universal_coverage_scanner_v3" in wf


def test_main_still_fails_runtime_time_time_without_csv_marker(monkeypatch, capsys):
    quote_key = _quote_time_key()
    time_call = _time_time_call()
    diff = "\n".join(
        [
            "+++ b/schwab_client.py",
            f'+        now = row.get("{quote_key}") or int({time_call})',
        ]
    )
    monkeypatch.setattr(guard, "_git_diff", lambda *, staged: diff)
    monkeypatch.setattr(sys, "argv", ["check_schwab_csv_first.py"])

    rc = guard.main()

    out = capsys.readouterr().out
    assert rc == 1
    assert "Schwab CSV-first guard FAILED" in out
    assert "schwab_client.py" in out


def test_universal_fix_gate_sources_require_runner_authoritative_v4_pin():
    """Non-excluded mission sources must keep meta pin coherent with scoreboard.

    tools/ and governance/artifacts/ are scanner-excluded; tests/, governance/*.json
    mission surfaces, and workflow docs are scanned. Adding those without adopting
    the runner-authoritative meta fails Schwab CSV First on PR event. This lock
    proves committed meta/scoreboard pin coherence and that the mission scannable
    surfaces exist as tracked files.
    """
    import json

    meta = json.loads(
        (ROOT / "governance/artifacts/schwab_v4_register_build_meta.json").read_text(
            encoding="utf-8"
        )
    )
    sb = json.loads(
        (ROOT / "governance/artifacts/schwab_v4_scoreboard.json").read_text(encoding="utf-8")
    )
    assert meta["register_content_sha256"]
    assert meta["register_content_sha256"] == sb["register_build"]["register_content_sha256"]
    assert meta["register_rows_written"] == sb["register_build"]["register_rows_written"]
    assert meta.get("partial_scan") is False
    excludes = set(meta["scanner_flags"]["scope_exclude_prefixes"])
    assert "tools" in excludes
    assert "governance/artifacts" in excludes
    scannable = [
        "tests/test_universal_fix_impact_gate.py",
        "tests/test_universal_fix_impact_gate_adversarial.py",
        "governance/universal_fix_impact_manifest.json",
        # Mission retired 2026-07-13 (implementation merged via PR #38 at final main
        # 87213d3692bd); the retired contract remains a tracked, scanned source.
        "governance/mission_authorization/consumed/UNIVERSAL-FIX-IMPACT-GATE-V1.retired.json",
    ]
    for rel in scannable:
        assert (ROOT / rel).is_file(), rel
        assert not any(rel.startswith(p + "/") or rel.startswith(p) and False for p in excludes)
        # Explicit: none of these live under a scanner exclude prefix.
        assert not any(rel.replace("\\", "/").startswith(p.rstrip("/") + "/") for p in excludes)


# ── Scope-coherent excluded-path disposition markers (PR #41 root cause) ─────
# The register walk excludes whole subtrees (scanner paths.SCAN_SCOPE_EXCLUDE_
# PREFIXES), so excluded-path emission sites require an exact-site
# REGISTER_SCOPE_EXCLUDED comment marker; scanner-in-scope paths keep the
# REGISTER_ROW / register-row contract unchanged. Every marker defect class is
# fail-closed and each protection has a mutation-sensitivity twin below.

_EXCLUDED_FILE = "calibration/daily_scoreboard.py"
_NESTED_EXCLUDED_FILE = "calibration/sub/deep_report.py"
_DELTA_SITE = '+            delta = float(m_ts) - float(row["decision_ts_utc"])'
_CONFIDENCE_SITE = '+            "CALIBRATION_NOT_PROVEN: descriptive confidence only; no calibration-validity claim",'


def _scope_marker(
    prefix: str = "calibration",
    token: str = "delta",
    mid: str = "t-delta-a",
    cls: str = "timestamp_difference",
    trace: str = "epoch-seconds difference between internal decision-log timestamps",
) -> str:
    return (
        f"+# REGISTER_SCOPE_EXCLUDED: prefix={prefix} token={token} id={mid} "
        f'class={cls} impact=NO_REGISTER_IMPACT trace="{trace}"'
    )


def _empty_register(tmp_path: Path) -> Path:
    p = tmp_path / "reg.csv"
    p.write_text(",".join(guard.REGISTER_COLUMNS_FALLBACK) + "\n", encoding="utf-8")
    return p


def _register_with_row(tmp_path: Path, *, path: str, line: int, surface: str) -> Path:
    p = tmp_path / "reg.csv"
    rid = "ab12cd34ef56ab78cd90"
    row = f"{rid},py,{path},{line},0,TEXT_LINE_MARKET_TOKEN,{surface},{surface},,,,UNREVIEWED,,,"
    p.write_text(",".join(guard.REGISTER_COLUMNS_FALLBACK) + "\n" + row + "\n", encoding="utf-8")
    return p


def test_scope_marker_covers_excluded_site(tmp_path: Path):
    diff = "\n".join([f"+++ b/{_EXCLUDED_FILE}", _scope_marker(), _DELTA_SITE])
    assert guard.check_diff_emission_gate(diff, _empty_register(tmp_path)) == []


def test_scope_marker_covers_nested_excluded_prefix(tmp_path: Path):
    diff = "\n".join([f"+++ b/{_NESTED_EXCLUDED_FILE}", _scope_marker(), _DELTA_SITE])
    assert guard.check_diff_emission_gate(diff, _empty_register(tmp_path)) == []


def test_scope_marker_covers_confidence_disclosure_homonym(tmp_path: Path):
    diff = "\n".join(
        [
            f"+++ b/{_EXCLUDED_FILE}",
            _scope_marker(token="confidence", mid="t-conf-a", cls="static_disclosure_text",
                          trace="static fail-closed operator disclosure string only"),
            _CONFIDENCE_SITE,
        ]
    )
    assert guard.check_diff_emission_gate(diff, _empty_register(tmp_path)) == []


def test_scope_marker_each_site_needs_its_own_marker(tmp_path: Path):
    covered = "\n".join(
        [
            f"+++ b/{_EXCLUDED_FILE}",
            _scope_marker(mid="t-delta-1"),
            _DELTA_SITE,
            _scope_marker(mid="t-delta-2"),
            '+            return "nearest_earlier" if delta < 0 else "nearest_later"',
        ]
    )
    assert guard.check_diff_emission_gate(covered, _empty_register(tmp_path)) == []
    one_marker = "\n".join(
        [
            f"+++ b/{_EXCLUDED_FILE}",
            _scope_marker(mid="t-delta-1"),
            _DELTA_SITE,
            '+            return "nearest_earlier" if delta < 0 else "nearest_later"',
        ]
    )
    v = guard.check_diff_emission_gate(one_marker, _empty_register(tmp_path))
    assert len(v) == 1 and "no exact-site" in v[0]


def test_scope_marker_excluded_site_without_marker_fails(tmp_path: Path):
    diff = "\n".join([f"+++ b/{_EXCLUDED_FILE}", _DELTA_SITE])
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert len(v) == 1 and "scanner-scope-excluded path" in v[0]


def test_scope_marker_rejected_on_in_scope_path(tmp_path: Path):
    diff = "\n".join(
        [
            "+++ b/server.py",
            _scope_marker(prefix="calibration", mid="t-inscope"),
            '+    ms_dict["delta"] = row.get("delta")',
        ]
    )
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("scanner-IN-scope path" in x for x in v)
    assert any("no matching" in x and "server.py" in x for x in v)


def test_scope_marker_wrong_token_is_orphan_and_site_uncovered(tmp_path: Path):
    diff = "\n".join([f"+++ b/{_EXCLUDED_FILE}", _scope_marker(token="gamma", mid="t-gamma"), _DELTA_SITE])
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("orphan" in x for x in v)
    assert any("no exact-site" in x for x in v)


def test_scope_marker_outside_line_adjacency_is_orphan(tmp_path: Path):
    diff = "\n".join(
        [
            f"+++ b/{_EXCLUDED_FILE}",
            _scope_marker(),
            "+            method_note = str(1)",
            "+            method_note2 = str(2)",
            _DELTA_SITE,
        ]
    )
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("orphan" in x for x in v)
    assert any("no exact-site" in x for x in v)


def test_scope_marker_cross_file_cannot_cover(tmp_path: Path):
    # The site line sits INSIDE the marker's line window and matches its token —
    # path equality must be the protection that rejects the cross-file bind.
    diff = "\n".join(
        [
            "+++ b/calibration/other_module.py",
            _scope_marker(mid="t-crossfile"),
            f"+++ b/{_EXCLUDED_FILE}",
            "+import json",
            _DELTA_SITE,
        ]
    )
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("orphan" in x for x in v)
    assert any("no exact-site" in x for x in v)


def test_scope_marker_malformed_fails_closed(tmp_path: Path):
    diff = "\n".join(
        [
            f"+++ b/{_EXCLUDED_FILE}",
            "+# REGISTER_SCOPE_EXCLUDED: prefix=calibration token=delta",
            _DELTA_SITE,
        ]
    )
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("malformed" in x for x in v)
    assert any("no exact-site" in x for x in v)


def test_scope_marker_missing_trace_field_is_malformed(tmp_path: Path):
    line = _scope_marker().replace(
        ' trace="epoch-seconds difference between internal decision-log timestamps"', ""
    )
    diff = "\n".join([f"+++ b/{_EXCLUDED_FILE}", line, _DELTA_SITE])
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("malformed" in x for x in v)


def test_scope_marker_duplicate_id_fails(tmp_path: Path):
    diff = "\n".join(
        [
            f"+++ b/{_EXCLUDED_FILE}",
            _scope_marker(mid="t-dup-marker"),
            _DELTA_SITE,
            _scope_marker(mid="t-dup-marker"),
            '+            return "nearest_earlier" if delta < 0 else "nearest_later"',
        ]
    )
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("duplicate" in x for x in v)


def test_scope_marker_one_marker_cannot_cover_two_sites(tmp_path: Path):
    diff = "\n".join(
        [
            f"+++ b/{_EXCLUDED_FILE}",
            _scope_marker(mid="t-one-marker"),
            _DELTA_SITE,
            '+            return "nearest_earlier" if delta < 0 else "nearest_later"',
        ]
    )
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert len(v) == 1 and "no exact-site" in v[0]


def test_scope_marker_orphan_without_any_site_fails(tmp_path: Path):
    diff = "\n".join([f"+++ b/{_EXCLUDED_FILE}", _scope_marker(mid="t-orphan")])
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert len(v) == 1 and "orphan" in v[0]


def test_scope_marker_prefix_not_covering_path_fails(tmp_path: Path):
    diff = "\n".join(
        [f"+++ b/{_EXCLUDED_FILE}", _scope_marker(prefix="reports", mid="t-wrongpfx"), _DELTA_SITE]
    )
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("does not cover this path" in x for x in v)
    assert any("no exact-site" in x for x in v)


def test_scope_marker_non_canonical_prefix_fails(tmp_path: Path):
    diff = "\n".join(
        [f"+++ b/{_EXCLUDED_FILE}", _scope_marker(prefix="not-a-real-prefix", mid="t-badpfx"), _DELTA_SITE]
    )
    v = guard.check_diff_emission_gate(diff, _empty_register(tmp_path))
    assert any("not a canonical" in x for x in v)


def test_scope_marker_tag_in_code_line_is_not_marker_intent(tmp_path: Path):
    diff = "\n".join(
        [
            "+++ b/tools/check_schwab_csv_first.py",
            '+SCOPE_EXCLUDED_MARKER_TAG = "REGISTER_SCOPE_EXCLUDED"',
        ]
    )
    assert guard.check_diff_emission_gate(diff, _empty_register(tmp_path)) == []


def test_scope_marker_does_not_weaken_register_row_wrong_path(tmp_path: Path):
    reg = _register_with_row(tmp_path, path="market_context.py", line=10, surface="delta")
    diff = "\n".join(
        [
            "+++ b/server.py",
            "+# REGISTER_ROW: ab12cd34ef56ab78cd90",
            '+    ms_dict["delta"] = row.get("delta")',
        ]
    )
    v = guard.check_diff_emission_gate(diff, reg)
    assert any("no matching" in x for x in v)


def test_scope_marker_register_row_citation_cannot_cover_excluded_site(tmp_path: Path):
    reg = _register_with_row(tmp_path, path=_EXCLUDED_FILE, line=186, surface="delta")
    diff = "\n".join(
        [
            f"+++ b/{_EXCLUDED_FILE}",
            "+# REGISTER_ROW: ab12cd34ef56ab78cd90",
            _DELTA_SITE,
        ]
    )
    v = guard.check_diff_emission_gate(diff, reg)
    assert len(v) == 1 and "no exact-site" in v[0]


def test_scope_marker_in_scope_register_row_contract_unchanged(tmp_path: Path):
    reg = _register_with_row(tmp_path, path="server.py", line=2, surface="delta")
    diff = "\n".join(
        [
            "+++ b/server.py",
            "+# REGISTER_ROW: ab12cd34ef56ab78cd90",
            '+    ms_dict["delta"] = row.get("delta")',
        ]
    )
    assert guard.check_diff_emission_gate(diff, reg) == []
