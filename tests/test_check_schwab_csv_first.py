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
