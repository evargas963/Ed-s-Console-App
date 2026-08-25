"""
Pytest: allow EdDB against temp paths (non-canonical) without per-call flags.

Production processes must NOT set ED_CONSOLE_ALLOW_NONCANONICAL_DB globally.

Schwab placeholders (CI / adversarial): ``server`` calls ``build_config`` at import
time. Objective-audit adversarial tests import ``server`` without live Schwab access.
Module-level setdefault here runs before test collection so ``import server`` never
requires real GitHub secrets. Production uvicorn startup is unchanged — these vars are
not set outside pytest. Fail-closed without secrets is locked by
``test_build_config_fail_closed_without_secrets`` (monkeypatch.delenv).
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")

# GOV-GATE-PERF-V1: the governance gate cache is a CLI-entry-point optimization.
# Tests must always exercise REAL compute — many inject failures via in-process
# monkeypatched state that file-identity cache keys cannot represent, so a stored
# success must never satisfy an injected-failure test. Force-no-cache is the
# cache's own designated verification mode (tools/governance_gate_cache.py).
os.environ.setdefault("ED_GATE_CACHE_DISABLE", "1")

# Hermetic Schwab config for pytest only — not real credentials; no network at import.
os.environ.setdefault("SCHWAB_API_KEY", "ci-placeholder-api-key")
os.environ.setdefault("SCHWAB_APP_SECRET", "ci-placeholder-app-secret")
os.environ.setdefault("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")

# TEARDOWN 2026-08-24: the tracked terrain quarantine ledger can never be a test's
# write target, REGARDLESS of when server is imported — the env override is read at
# server import time, and this line runs before any test module can import server
# (CI caught a lazy mid-test import writing the real file; the autouse firewall
# fixture below remains the byte-level backstop).
import tempfile as _tempfile  # noqa: E402
os.environ.setdefault(
    "ED_TERRAIN_QUARANTINE_LEDGER",
    str(Path(_tempfile.mkdtemp(prefix="ed-pytest-ledger-")) / "terrain_quarantine_ledger.jsonl"))


def pytest_configure(config) -> None:
    """xdist workers must not share one console DB file.

    `db.DB_PATH` is resolved at import from ED_CONSOLE_DB. Each worker is a fresh
    process; set the override here (before test modules import db) so schema-init
    and writes cannot collide. Serial pytest is unchanged (no PYTEST_XDIST_WORKER).
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return
    root = Path(os.environ.get("TMPDIR") or "/tmp") / f"ed-pytest-{worker}-{os.getpid()}"
    root.mkdir(parents=True, exist_ok=True)
    db = root / "ed_console.db"
    db.touch()
    os.environ["ED_CONSOLE_DB"] = str(db)
    os.environ["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] = "1"


@pytest.fixture(autouse=True)
def _no_fusion_temperature_calibration(monkeypatch):
    """Hermetic tests: never read the operator's live fusion calibration artifact.

    models/calibration/fusion_temperature.json is machine-fit operator state; with
    it present, every bundle-path test would change behavior by environment. Tests
    that exercise the serve hook monkeypatch _applied_fusion_temperatures themselves
    (their setattr runs after this fixture and wins).
    """
    import multi_horizon_ml_bundle as mhb

    monkeypatch.setattr(mhb, "_applied_fusion_temperatures", lambda: {})


@pytest.fixture(autouse=True)
def _equal_mh_pool_weights(monkeypatch):
    """Hermetic tests: never read the operator's live calibration DB for ALL-card
    pool weights. Equal weights = unweighted log opinion pool (the fail-closed
    default). Tests exercising skill weighting pass pool_weights explicitly or
    monkeypatch after this fixture (their setattr wins)."""
    import multi_horizon_decision as mhd

    monkeypatch.setattr(
        mhd,
        "_horizon_skill_weights_cached",
        lambda: ({h: 1.0 / len(mhd.PRODUCT_HORIZONS) for h in mhd.PRODUCT_HORIZONS}, True),
    )


@pytest.fixture(scope="session", autouse=True)
def _ensure_console_db_snapshots_1m_normalized_schema():
    """Hermetic pytest/CI: governance live-drift reads ``db_training_fingerprint`` on ``DB_PATH``."""
    from db import ensure_console_db_training_schema

    ensure_console_db_training_schema()


@pytest.fixture(autouse=True)
def _ensure_console_db_schema_before_each_test():
    """Playwright / early tests may touch ``data/ed_console.db`` without normalized schema."""
    from db import ensure_console_db_training_schema

    ensure_console_db_training_schema()


@pytest.fixture(scope="session")
def _admitted_decision_registry_path(tmp_path_factory):
    """Session-scoped registry file that admits the decision path (test default)."""
    import json

    from decision_gate import (
        DECISION_PATH_COMPONENT,
        REQUIRED_EVIDENCE_FIELDS,
        SCHEMA_VERSION,
    )

    doc = {
        "schema_version": SCHEMA_VERSION,
        "admissions": [
            {
                "component": DECISION_PATH_COMPONENT,
                "status": "ADMITTED",
                "evidence": {f: f"pytest-fixture:{f}" for f in REQUIRED_EVIDENCE_FIELDS},
                "operator_decision": {"date": "2026-01-01", "decided_by": "pytest-fixture"},
            }
        ],
    }
    p = tmp_path_factory.mktemp("decision_gate") / "decision_path_admissions.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _decision_path_admitted_by_default(monkeypatch, _admitted_decision_registry_path):
    """Hermetic tests: stack/policy tests exercise compute_call behavior, not the
    charter admission gate — run them with an admitted registry so a directional
    call is reachable. Production default (committed registry is EMPTY → forced
    WAIT) is locked explicitly by tests/test_decision_gate.py, which overrides
    ED_DECISION_ADMISSIONS_PATH / passes explicit paths (its setenv wins)."""
    monkeypatch.setenv("ED_DECISION_ADMISSIONS_PATH", str(_admitted_decision_registry_path))


def most_recent_trading_day_et(*, on_or_before: date | None = None) -> date:
    """The newest ET date the market calendar admits, at or before `on_or_before` (today).

    RC-306. Fixtures that need a session date had two obvious sources and both are wrong.
    A hard-coded date goes stale against readers that default to today — that broke twice
    across 2026-07-30. The wall clock does not go stale, but it does not know about
    weekends or holidays, and RC-278 gave the accrual writers `is_trading_day_et` as their
    calendar authority, so on a Saturday a clock-derived fixture hands the writer a date
    the writer is REQUIRED to reject. Five tests then failed two days in seven while
    reporting nothing about the code.

    The third source is the authority itself. Drawing the fixture date from the same
    function the code validates against means the test can no longer disagree with the
    calendar, and there is no literal to rot.
    """
    from time_et import ET, is_trading_day_et

    day = on_or_before or datetime.now(ET).date()
    for _ in range(14):          # the longest market closure gap is far under two weeks
        if is_trading_day_et(day.isoformat()):
            return day
        day -= timedelta(days=1)
    raise AssertionError(
        f"no trading day found in the 14 ET days before {on_or_before or 'today'} — "
        "the market calendar authority (time_et.is_trading_day_et) is answering False "
        "for every date, which is a calendar defect, not a fixture one")


@pytest.fixture(autouse=True)
def _clear_quote_memo_between_tests():
    """RC-314: `server._quote_memo` is process-global and outlives every pytest boundary.

    `test_rest_fast_quote_spot_fail_closed_not_zero` passed as a single node and FAILED as
    part of its own file, with `quote_attempts=0` in the log: a sibling had left SPY at
    501.25 in the memo, `_memoized_quote_response` served it, and the fail-closed path under
    test never ran. tmp_path, fresh DBs and monkeypatch all isolate what the TEST owns; a
    cache owned by the import is invisible to them.

    Guarded on `server` already being imported, so the tests that never touch it pay nothing
    and none of them triggers a server import it did not ask for.
    """
    srv = sys.modules.get("server")
    memo = getattr(srv, "_quote_memo", None) if srv is not None else None
    if isinstance(memo, dict):
        memo.clear()
    yield


def in_window_ts(hour: int = 10, minute: int = 0, *, span_minutes: int = 0) -> float:
    """A bar timestamp the COLLECT-WINDOW LAW admits: RTH, on a real trading day.

    RC-306, shared. Fixtures reached the write seam three different wrong ways — a wall
    clock (fails on weekends), a literal epoch from a year the calendar does not cover, and
    a synthetic small integer like 1_020_000.0, which is 1970-01-12. RC-214's collect-window
    law narrowed `upsert_1m_bars` to (555, min(975, close+15)] on trading days, so all three
    are refused, no bars are written, and the outcome columns the test asserts on come back
    None — a true statement about the calendar, not about the code.

    `span_minutes` is the length of the bar series that will start here: it is checked
    against the window's end so a fixture cannot half-fit and fail on its tail alone.
    """
    from time_et import COLLECT_WINDOW_END_MINS, COLLECT_WINDOW_START_MINS, ET

    start = hour * 60 + minute
    if start <= COLLECT_WINDOW_START_MINS:
        raise AssertionError(
            f"{hour:02d}:{minute:02d} ET is at or before the collect window's open "
            f"({COLLECT_WINDOW_START_MINS} minutes); the seam would refuse these bars")
    if start + span_minutes > COLLECT_WINDOW_END_MINS:
        raise AssertionError(
            f"a {span_minutes}-minute series from {hour:02d}:{minute:02d} ET runs past the "
            f"window's close ({COLLECT_WINDOW_END_MINS} minutes); start it earlier")
    day = most_recent_completed_session_et()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).timestamp()


def most_recent_completed_session_et() -> date:
    """The newest ET trading day whose COLLECT WINDOW has already CLOSED.

    A trading day is not the same thing as a FINISHED trading day, and every fixture that
    reaches this helper writes a forward-running bar series and then asserts on an outcome
    computed from its tail. `most_recent_trading_day_et` answers "today" from the moment
    the date rolls over, so between midnight and the window's close those fixtures were
    generating bars for a session that HAS NOT HAPPENED YET: the writer accepts them, the
    outcome columns come back None, and the test reports a true statement about the clock
    instead of about the code.

    That is the same defect a previous repair had already closed in ONE fixture. It
    survived here because the fix was applied to the instance rather than to the shared
    authority the other fixtures draw from — the exact "fixed the instance, not the class"
    loop RC-286's docstring names. The completion rule now lives in one place, so a fixture
    cannot anchor to an unfinished session by forgetting to ask.
    """
    from time_et import COLLECT_WINDOW_END_MINS, ET

    now = datetime.now(ET)
    day = most_recent_trading_day_et()
    if day == now.date() and (now.hour * 60 + now.minute) <= COLLECT_WINDOW_END_MINS:
        day = most_recent_trading_day_et(on_or_before=day - timedelta(days=1))
    return day


@pytest.fixture
def fresh_ablation_static_lock_index():
    """Opt-in reset for tests that mutate manifest/DB/spec inputs or fake the index builder."""
    from tools.ablation_static_lock_index import reset_ablation_static_lock_index_for_tests

    reset_ablation_static_lock_index_for_tests()
    yield
    reset_ablation_static_lock_index_for_tests()


# ---------------------------------------------------------------- repo index --
# REHAB 2026-08-24: ~33 test files each independently rglob'd + read + ast.parse'd the
# whole repository (one warm pass measured 6.8s; the duplicated passes cost 400-700s of
# CPU per suite run). This is ONE live pass per session (per xdist worker), shared by the
# repo-sweep tests. The measurement stays live — it is rebuilt on every suite run from
# the working tree, never stored (RC-268) — only the I/O is shared.

_REPO_INDEX_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".claude",
    "build", "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})


class RepoIndex:
    """rel_path -> (source_text, ast_tree_or_None) over every repo .py file."""

    def __init__(self, root: Path) -> None:
        import ast as _ast
        self.root = root
        self.files: dict[Path, tuple[str, object | None]] = {}
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root)
            if any(part in _REPO_INDEX_SKIP_DIRS for part in rel.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            try:
                tree = _ast.parse(text)
            except SyntaxError:
                tree = None
            self.files[rel] = (text, tree)

    def items(self):
        """(rel_path, source_text, tree_or_None), sorted by path."""
        for rel, (text, tree) in self.files.items():
            yield rel, text, tree


@pytest.fixture(scope="session")
def repo_index() -> RepoIndex:
    return RepoIndex(Path(__file__).resolve().parent.parent)


# ------------------------------------------------- tracked-ledger firewall --
# REHAB 2026-08-24: reports/terrain_quarantine_ledger.jsonl is a TRACKED operator audit
# file, and tests exercising the quarantine machinery (scorecard file, silent-zero file,
# and any future caller of server._note_terrain_failure / _terrain_quarantine_blocks)
# were appending ZZTEST*/ZZQ fixture rows to it on every suite run. This GLOBAL autouse
# fixture redirects the module's ledger path to tmp for EVERY test whenever `server` is
# imported — per-file fixtures kept missing writers (measured: ZZQ rows landed from a
# file with no redirect). Costs nothing for tests that never import server.
#
# LATE-IMPORT HARDENING (operator-named hole, 2026-08-24): the redirect above only fires
# when `server` is ALREADY imported at fixture setup. A test that imports server inside
# its own body gets an unpatched TERRAIN_QUARANTINE_LEDGER and writes the real tracked
# file. The fixture therefore also snapshots the tracked file's byte length before every
# test; if the file GREW during the test, it is truncated back to the snapshot FIRST
# (the tracked file must never stay polluted) and the test then FAILS naming the hole.
# Proven end-to-end by tests/test_terrain_ledger_isolation_v1.py.
_TRACKED_TERRAIN_LEDGER = (
    Path(__file__).resolve().parent.parent / "reports" / "terrain_quarantine_ledger.jsonl"
)


@pytest.fixture(autouse=True)
def _terrain_ledger_to_tmp(tmp_path, monkeypatch):
    try:
        size_before = _TRACKED_TERRAIN_LEDGER.stat().st_size
    except OSError:
        size_before = None                       # tracked file absent — creation is growth too
    srv = sys.modules.get("server")
    if srv is not None and hasattr(srv, "TERRAIN_QUARANTINE_LEDGER"):
        monkeypatch.setattr(srv, "TERRAIN_QUARANTINE_LEDGER",
                            tmp_path / "terrain_quarantine_ledger.jsonl")
    yield
    try:
        size_after = _TRACKED_TERRAIN_LEDGER.stat().st_size
    except OSError:
        size_after = None
    if size_after is None:
        return
    grew = size_after - (size_before or 0)
    if size_before is None:
        _TRACKED_TERRAIN_LEDGER.unlink()         # restore first: it did not exist before
        pytest.fail(
            "TERRAIN LEDGER LATE-IMPORT HOLE: this test CREATED the tracked "
            f"{_TRACKED_TERRAIN_LEDGER.name} ({grew} bytes) — server was imported after "
            "fixture setup, so TERRAIN_QUARANTINE_LEDGER was never redirected to tmp. "
            "The file has been removed to restore the tracked state; import server before "
            "the write (or patch server.TERRAIN_QUARANTINE_LEDGER inside the test)."
        )
    if size_after > size_before:
        # xdist: every worker watches the SAME tracked file, so a concurrent worker's
        # SELF-RESTORING probe (tests/test_terrain_ledger_isolation_v1.py deliberately
        # appends to the tracked file and truncates it back inside its own run) can be
        # observed mid-window by an innocent neighbor — CI 2026-08-24 blamed
        # test_rc359_oi_banking (a tmp-DB test that touches no server path) for a +479B
        # window. Re-check briefly: growth that HEALS ITSELF was another worker's probe
        # completing its restore; growth that PERSISTS is a real writer and fails loud.
        import time as _time
        for _ in range(6):
            _time.sleep(0.25)
            try:
                size_after = _TRACKED_TERRAIN_LEDGER.stat().st_size
            except OSError:
                size_after = None
                break
            if size_after <= size_before:
                break
        if size_after is not None and size_after <= size_before:
            return                                 # transient — the writer restored it
        grew = (size_after or 0) - size_before
        with open(_TRACKED_TERRAIN_LEDGER, "r+b") as fh:   # restore first, then fail loud
            fh.truncate(size_before)
        pytest.fail(
            "TERRAIN LEDGER LATE-IMPORT HOLE: the tracked "
            f"{_TRACKED_TERRAIN_LEDGER.name} GREW by {grew} bytes during this test and "
            "STAYED grown across a 1.5s recheck. The usual cause: server was imported "
            "after fixture setup (a mid-test `import server`), so "
            "TERRAIN_QUARANTINE_LEDGER was never redirected to tmp and the quarantine "
            "write landed in the real operator audit file (an external writer touching "
            "the tracked file mid-test trips this too). It has been truncated back to "
            f"its pre-test length ({size_before} bytes); import server before the write "
            "(or patch server.TERRAIN_QUARANTINE_LEDGER inside the test)."
        )
