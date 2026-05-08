from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_schwab_csv_first as guard


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
