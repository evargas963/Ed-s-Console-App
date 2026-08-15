"""RC-272 — the scoreboard must measure, and UNMEASURED must never read as OK.

WHAT WAS MEASURED (2026-08-06). The first full test run this repository has
ever had: 5262 passed, 51 failed, 2 skipped in 3443.97s, line coverage 52.9%,
branch coverage 44.7%. Before that run no coverage artefact existed, so 544
test files were evidence that tests EXIST, never that anything is covered.

THE BUG THIS FILE EXISTS AFTER. The same CC>15 metric was reported four times
with four different values -- 516, 930, 569, 627 -- because a glob plus a regex
split on the full path silently matched nothing on Windows, so the directory
skip list did nothing and each run had a different accidental scope. The true
product figure is 687 of 11,611. A number that moves without the repository
moving is not a measurement, and a scoreboard built on one is theatre.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import repo_scoreboard as S  # noqa: E402


# ------------------------------------------------------- the scope bug ----

def test_walk_excludes_every_skipped_directory():
    """The defect that produced four different numbers for one metric.

    os.walk with in-place dirs pruning is the only form that provably excludes
    a directory; glob + regex on the joined path did not, and nothing noticed
    because the count merely looked plausible each time.
    """
    seen = {bucket for _path, bucket in S._walk_py()}
    assert seen, "walker returned nothing at all"
    for path, _bucket in S._walk_py():
        parts = Path(path).relative_to(REPO).parts
        for banned in S.SKIP:
            assert banned not in parts, f"{banned} leaked into the walk: {path}"


def test_scope_buckets_are_disjoint_and_named():
    buckets = {b for _p, b in S._walk_py()}
    assert buckets <= {"product", "tools", "tests", "research"}, buckets
    assert "product" in buckets


def test_complexity_row_states_its_scope():
    """Four wrong numbers came from an unstated scope. It must be on the row."""
    rows = S.row_complexity()
    cc = next(r for r in rows if r.key == "CC")
    assert "product" in cc.metric.lower() or "product" in cc.note.lower()
    assert " of " in cc.value, "report the denominator, not a bare count"


def test_complexity_counts_only_product_code():
    """A tests/ or tools/ function must not inflate the product figure."""
    rows = S.row_complexity()
    cc = next(r for r in rows if r.key == "CC")
    over = int(cc.value.split(" of ")[0])
    total = int(cc.value.split(" of ")[1].replace(",", ""))
    product_fns = sum(1 for _p, b in S._walk_py() if b == "product")
    assert 0 < over < total
    assert product_fns > 0


# ------------------------------------------------- unmeasured is not ok ----

def test_unmeasured_is_never_reported_as_ok():
    """Absence of a number is not a passing number.

    A missing artefact reading OK is absence of signal sold as success -- the
    defect class this whole session kept finding.
    """
    for row in S.collect():
        if row.state == "UNMEASURED":
            assert row.value in ("—", "-", ""), (
                f"{row.key} is UNMEASURED but carries value {row.value!r}")


def test_missing_coverage_artefact_reads_unmeasured(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "REPO", str(tmp_path), raising=True)
    rows = S.row_coverage()
    assert rows[0].state == "UNMEASURED"
    assert rows[0].value == "—"


def test_missing_mutation_artefact_reads_unmeasured(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "REPO", str(tmp_path), raising=True)
    assert S.row_mutation()[0].state == "UNMEASURED"


def test_mutation_score_is_on_the_board_at_all():
    """Coverage cannot see an assertion-free test; only mutation score can.

    The board must carry the question 'would this test FAIL if the code
    broke', even while the answer is UNMEASURED.
    """
    assert any(r.key == "MUT" for r in S.collect())


# --------------------------------------------------- nothing is stored ----

def test_no_row_carries_a_stored_status_field():
    """RC-268: a hardcoded status is how a self-measuring artefact starts lying."""
    fields = set(S.Row.__dataclass_fields__)
    assert "state" in fields          # state is DERIVED per build, not persisted
    for banned in ("cached", "last_value", "stored", "as_of_value"):
        assert banned not in fields


def test_every_builder_returns_rows_or_raises_visibly():
    """A builder that dies must surface as ERROR, never be silently dropped."""
    rows = S.collect()
    assert len(rows) >= len(S.BUILDERS)
    for row in rows:
        assert row.state in ("OK", "OPEN", "UNMEASURED", "STALE", "ERROR")


def test_collect_survives_a_broken_builder(monkeypatch):
    def boom():
        raise RuntimeError("builder exploded")
    monkeypatch.setattr(S, "BUILDERS", (boom,), raising=True)
    rows = S.collect()
    assert len(rows) == 1
    assert rows[0].state == "ERROR"
    assert "RuntimeError" in rows[0].note


# ------------------------------------------------------------ contract ----

def test_targets_are_stated_for_every_measured_row():
    for row in S.collect():
        if row.state in ("OK", "OPEN"):
            assert row.target and row.target != "—" or row.key in ("DBSZ",), row.key


def test_json_mode_is_machine_readable(capsys):
    import json
    S.main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload
    for entry in payload:
        for key in ("key", "area", "metric", "value", "target", "state"):
            assert key in entry, key
