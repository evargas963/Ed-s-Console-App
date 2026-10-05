"""tools/check_real_market_data.py (REAL-DATA) on real git repositories built from this repository's
own files: a test, helper or Playwright route the PR adds or changes may not feed the code typed,
generated or edited market values; one that feeds what Schwab sent, or that the PR leaves as it
was, passes."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import check_real_market_data as crd  # noqa: E402

MAIN = "059b7e64"                     # origin/main when the check was written
BANKED = "tests/test_banked_prior_coverage_gate_v1.py"
ASOF = "tests/e2e/console-gamma-asof.spec.js"


def _at_main(path: str) -> str:
    return subprocess.run(["git", "show", f"{MAIN}:{path}"], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


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
    """A repository whose base holds the captured fixtures and `base`, and a branch adding `pr`."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    fixtures = {f"tests/fixtures/{f.name}": f.read_bytes() for f in (REPO / "tests" / "fixtures").glob("*.json")}
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


def test_the_crafted_banked_prior_tape_is_refused(tmp_path):
    """origin/main's banked-prior test wrote its own tape: 100 + i*0.01 prices, volume 1000."""
    root = _pr(tmp_path, {}, {BANKED: _at_main(BANKED)})
    found = crd.violations(root, "main")
    assert found[0] == (
        f"{BANKED}:41 _seed_thin_prior_db: market fields given typed or generated numbers: "
        "line 41: 'open' (INSERT INTO price_bars_1m value); line 41: 'high' (INSERT INTO price_bars_1m value); "
        "line 41: 'low' (INSERT INTO price_bars_1m value); line 42: 'close' (INSERT INTO price_bars_1m value); "
        "line 42: 'volume' (INSERT INTO price_bars_1m value)")
    assert _refused(found) == {"_seed_thin_prior_db", "_published", "test_thin_banked_prior_session_is_stamped_degraded",
                               "test_full_banked_prior_session_carries_no_stamp"}


def test_hand_written_route_payloads_are_refused(tmp_path):
    """The as-of spec serves a chain, a surface, levels and strikes it typed in itself."""
    root = _pr(tmp_path, {}, {ASOF: _at_main(ASOF)})
    found = crd.violations(root, "main")
    assert {"SURFACE", "TERRAIN", "STRIKES", "CHAIN", "routes",
            "test('GEX-by-strike discloses its terrain source + as-of (not a global LIVE)')",
            "test('a stale terrain generation makes the GEX-by-strike badge read stale')"} <= _refused(found)
    assert (f"{ASOF}:26 CHAIN: a browser route serves market values not loaded from tests/fixtures/ "
            "(line 26: 'spot' typed inline; line 29: 'strikePrice' typed inline; line 29: 'openInterest' typed inline; "
            "line 29: 'totalVolume' typed inline; line 29: 'gamma' typed inline; line 29: 'delta' typed inline; "
            "line 29: 'volatility' typed inline; line 30: 'strikePrice' typed inline; line 30: 'openInterest' typed "
            "inline; line 30: 'totalVolume' typed inline; line 30: 'gamma' typed inline; line 30: 'delta' typed "
            "inline; line 30: 'volatility' typed inline)") in found


def test_an_edit_to_a_bar_is_refused(tmp_path):
    """The snapshot-integrity test shifts a bar's timestamp by a typed 60_000."""
    path = "tests/test_phase2a_snapshot_integrity_v1.py"
    root = _pr(tmp_path, {}, {path: _at_main(path)})
    assert any("line 138: 'timestamp' (item assignment)" in v for v in crd.violations(root, "main"))


def test_a_test_that_feeds_only_captured_data_is_allowed(tmp_path):
    path = "tests/test_options_contract_identity_v1.py"
    root = _pr(tmp_path, {}, {path: _at_main(path)})
    assert crd.violations(root, "main") == []


def test_a_spec_that_serves_nothing_typed_is_allowed(tmp_path):
    path = "tests/e2e/first-run-no-ticker.spec.js"
    root = _pr(tmp_path, {}, {path: _at_main(path)})
    assert crd.violations(root, "main") == []


def test_units_the_pr_leaves_as_they_were_are_not_judged(tmp_path):
    banked, asof = _at_main(BANKED), _at_main(ASOF)
    root = _pr(tmp_path, {BANKED: banked, ASOF: asof},
               {BANKED: banked.replace('"""', '"""Banked prior. ', 1), ASOF: asof.replace("// @ts-check", "// @ts-check ", 1)})
    assert crd.violations(root, "main") == []


def test_the_market_fields_are_the_captured_fixtures_numeric_keys():
    fields = crd.market_fields(REPO)
    assert {"BID_PRICE", "strikePrice", "openInterest", "close", "volume", "spot"} <= fields
    assert not {"ticker", "symbol", "putCall", "description", "chain_as_of_ts_utc"} & fields
