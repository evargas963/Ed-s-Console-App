"""tools/check_ticker_coverage.py (TICKER-COVERAGE) on real git repositories built from this
repository's own files and captured fixtures: a test the PR adds or changes that reads one ticker's
captures is refused, unless it carries a one_capture exception whose predicate holds for exactly
the capture it names among every captured fixture."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import check_ticker_coverage as ctc  # noqa: E402

MAIN = "059b7e64"                     # origin/main when the check was written
DESK = "tests/test_trade_desk_served_v1.py"
PROVENANCE_TEST = "tests/test_check_fixture_provenance_v1.py"
EVIDENCE = "real_spy_strike_count_vs_strike_range_all_evidence" + ".json"

ONE_CAPTURE = '''import json
from pathlib import Path

import pytest


def _measured_both_ways(fx):
    return isinstance(fx, dict) and "strike_count_250" in fx and "strike_range_all" in fx


def _has_bars(fx):
    return isinstance(fx, dict) and "bars" in fx


def _has_a_ticker(fx):
    return fx["ticker"] != ""


@pytest.mark.one_capture("{fixture}", {predicate})
def test_the_capture():
    fx = json.loads((Path(__file__).parent / "fixtures" / "{fixture}").read_text())
    assert fx
'''


def _at_main(path: str) -> str:
    return subprocess.run(["git", "show", f"{MAIN}:{path}"], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def _fixtures_at_main() -> dict[str, bytes]:
    names = subprocess.run(["git", "ls-tree", "--name-only", f"{MAIN}:tests/fixtures"], cwd=REPO, capture_output=True,
                           text=True, check=True).stdout.split()
    return {f"tests/fixtures/{n}": subprocess.run(["git", "show", f"{MAIN}:tests/fixtures/{n}"], cwd=REPO,
                                                  capture_output=True, check=True).stdout
            for n in names if n.endswith(".json")}


def _git(root: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _write(root: Path, files: dict[str, str | bytes]) -> None:
    for name, body in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            (root / name).write_bytes(body)
        else:
            (root / name).write_text(body, encoding="utf-8", newline="")


def _pr(tmp_path: Path, base: dict[str, str], pr: dict[str, str]) -> Path:
    """A repository whose base holds every captured fixture of MAIN and `base`, and a branch adding `pr`."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    fixtures = _fixtures_at_main()
    _write(root, {**fixtures, **base})
    _git(root, "add", *fixtures, *base)
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "pr")
    _write(root, pr)
    _git(root, "add", *pr)
    _git(root, "commit", "-q", "-m", "pr")
    return root


def _refused(found: list[str]) -> set[str]:
    return {v.split(" ", 1)[1].split(":")[0] for v in found}


def test_single_ticker_tests_on_main_are_refused(tmp_path):
    root = _pr(tmp_path, {}, {DESK: _at_main(DESK)})
    found = ctc.violations(root, "main")
    assert f"{DESK}:24 test_the_book_side_is_served_from_the_real_book: reads captures of one ticker only " \
           "(TSLA: real_equity_book.json); run it on the SPY and TSLA captures, or prove a one_capture " \
           "exception" in found
    refused = _refused(found)
    assert "test_the_desk_event_feed_numbers_orders_and_counts_the_real_crosses" in refused          # SPY only
    assert "test_each_cross_is_served_as_recorded_and_the_chart_draws_the_newest_at_each_level" not in refused


def test_a_test_on_the_spy_and_tsla_captures_is_allowed(tmp_path):
    """The provenance hook's tests record SPY's and TSLA's captured books through the daemon's writer."""
    root = _pr(tmp_path, {}, {PROVENANCE_TEST: (REPO / PROVENANCE_TEST).read_text(encoding="utf-8")})
    assert ctc.violations(root, "main") == []


def test_a_changed_helper_rejudges_the_tests_that_use_it(tmp_path):
    """The desk's tests, unchanged, read whatever its `_load` helper is changed to read."""
    desk = _at_main(DESK)
    root = _pr(tmp_path, {DESK: desk}, {DESK: desk.replace("def _load(name):", "def _load(name, other=None):")})
    assert "test_the_book_side_is_served_from_the_real_book" in _refused(ctc.violations(root, "main"))


def test_tests_the_pr_leaves_as_they_were_are_not_judged(tmp_path):
    desk = _at_main(DESK)
    root = _pr(tmp_path, {DESK: desk}, {DESK: desk.replace("def test_one_strike_holding_both_walls_is_two_sided():",
                                                           "def test_one_strike_holding_both_walls_is_two_sided():\n"
                                                           "    assert True")})
    assert ctc.violations(root, "main") == []


def test_a_one_capture_exception_holding_for_that_capture_alone_is_allowed(tmp_path):
    test = ONE_CAPTURE.replace("{fixture}", EVIDENCE).replace("{predicate}", "_measured_both_ways")
    root = _pr(tmp_path, {}, {"tests/test_one.py": test})
    assert ctc.violations(root, "main") == []


def test_a_one_capture_exception_holding_for_several_captures_is_refused(tmp_path):
    bars = "real_spy_1m_bars_2026_09_24_25" + ".json"
    test = ONE_CAPTURE.replace("{fixture}", bars).replace("{predicate}", "_has_bars")
    root = _pr(tmp_path, {}, {"tests/test_one.py": test})
    assert ctc.violations(root, "main") == [
        "tests/test_one.py:20 test_the_capture: one_capture's predicate _has_bars holds for 3 captured fixtures "
        "(real_spx_1m_bars_2026_09_25_28.json, real_spy_1m_bars_2026_09_23_zero_volume.json, "
        f"{bars}), not for {bars} alone"]


def test_a_one_capture_predicate_that_fails_on_a_capture_refuses_the_test(tmp_path):
    test = ONE_CAPTURE.replace("{fixture}", EVIDENCE).replace("{predicate}", "_has_a_ticker")
    root = _pr(tmp_path, {}, {"tests/test_one.py": test})
    found = ctc.violations(root, "main")
    assert len(found) == 1 and "one_capture's predicate _has_a_ticker raised KeyError" in found[0]


def test_each_capture_is_known_by_the_tickers_it_holds(tmp_path):
    caps = ctc.captures(_pr(tmp_path, {}, {"tests/x.py": ""}))
    assert ctc.fixture_tickers(caps["real_tsla_book_rows.json"]) == {"TSLA"}
    assert ctc.fixture_tickers(caps["real_spy_2026_10_14_chain_oi_zero.json"]) == {"SPY"}
    assert ctc.fixture_tickers(caps["real_options_stream_history_samples.json"]) == {"QQQ", "SPY", "TSLA"}
