"""Paired test for tools/check_fix_everything_we_touch.py (AGENTS top rule)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_fix_everything_we_touch as mod  # noqa: E402


@pytest.mark.parametrize(
    "phrase",
    [
        "This is by design — we only patch server.py.",
        "Out of scope for this PR; will fix later.",
        "Mostly complete; good enough for now.",
        "Policy by design for the asymmetry.",
    ],
)
def test_commit_message_excuse_phrases_fail(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    hits = mod.check_commit_message(msg)
    assert hits, f"expected rule-drift hit for: {phrase!r}"


def test_staged_py_excuse_phrase_fails(tmp_path: Path, monkeypatch) -> None:
    py = tmp_path / "signals.py"
    py.write_text('# patch only — skip tests\nx = 1\n', encoding="utf-8")
    rel = py.relative_to(tmp_path).as_posix()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    hits = mod.check_staged_rule_drift({rel})
    assert hits
    assert "patch-only" in hits[0].lower() or "patch only" in hits[0].lower()


def test_commit_message_meta_describing_checker_passes(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "Mechanical lock — commit-message guard blocks read-only investigation "
        "and memo-only admissible when code edit is known.\n",
        encoding="utf-8",
    )
    assert mod.check_commit_message(msg) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "CSV re-check was a read-only investigation.",
        "Investigation only — no code changes.",
        "Investigation complete with no fix required.",
        "No further code change needed on this path.",
        "Memo-only admissible for this walk.",
        "Flagged the FIND without landing the fix.",
    ],
)
def test_commit_message_investigation_only_phrases_fail(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    hits = mod.check_commit_message(msg)
    assert hits, f"expected investigation-only hit for: {phrase!r}"


def test_actionable_code_edit_detection() -> None:
    assert not mod.is_actionable_code_edit("none.")
    assert not mod.is_actionable_code_edit("none")
    assert not mod.is_actionable_code_edit("landed — removed fallbacks.")
    assert mod.is_actionable_code_edit("deferred — add provider wrappers.")


def test_v4_memo_blocks_actionable_code_edit_without_staged_py(tmp_path: Path) -> None:
    memo = tmp_path / "live_market_plane.py.md"
    memo.write_text(
        "- **code edit:** proposed — remove non-canonical BID/ASK fallbacks.\n",
        encoding="utf-8",
    )
    hits = mod.check_v4_memo(memo, staged={"governance/SCHWAB_V4_REVIEW_MEMOS/live_market_plane.py.md"})
    assert len(hits) == 1
    assert "live_market_plane.py" in hits[0]


def test_v4_memo_passes_when_py_staged(tmp_path: Path) -> None:
    memo = tmp_path / "live_market_plane.py.md"
    memo.write_text(
        "- **code edit:** proposed — remove non-canonical BID/ASK fallbacks.\n",
        encoding="utf-8",
    )
    hits = mod.check_v4_memo(
        memo,
        staged={
            "governance/SCHWAB_V4_REVIEW_MEMOS/live_market_plane.py.md",
            "live_market_plane.py",
            "tests/test_live_market_plane_streaming.py",
        },
    )
    assert hits == []


def test_v4_memo_landed_code_edit_passes_without_py(tmp_path: Path) -> None:
    memo = tmp_path / "live_market_plane.py.md"
    memo.write_text(
        "- **code edit:** landed — fallbacks removed.\n",
        encoding="utf-8",
    )
    hits = mod.check_v4_memo(memo, staged={"governance/SCHWAB_V4_REVIEW_MEMOS/live_market_plane.py.md"})
    assert hits == []


def test_open_audit_catch_requires_py(tmp_path: Path) -> None:
    memo = tmp_path / "order_flow_engine.py.md"
    memo.write_text(
        "**Audit catch flagged (S2a):** bare bidSize on streaming content.\n",
        encoding="utf-8",
    )
    hits = mod.check_v4_memo(memo, staged={"governance/SCHWAB_V4_REVIEW_MEMOS/order_flow_engine.py.md"})
    assert hits


def test_agents_md_documents_top_rule() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Do not lie to the operator" in text
    assert "## Fix everything we touch" in text
    assert "## Self-governance quality loop" in text


def test_commit_message_do_not_lie_meta_describing_checker_passes(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "Partial coverage — commit-msg guard for unverified claim patterns (verified without evidence).\n",
        encoding="utf-8",
    )
    assert mod.check_commit_message(msg) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "Verified the bid fix end-to-end.",
        "Confirmed all sites clean.",
        "This guarantees no regression.",
        "All clear on wire reads.",
    ],
)
def test_commit_message_unverified_claim_phrases_fail(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    hits = mod.check_commit_message(msg)
    assert hits, f"expected unverified-claim hit for: {phrase!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        "Verified bid fix @ 71dafb2 in live_decision_bundle.py:120",
        "Confirmed via tests/test_live_market_plane_streaming.py",
        "pytest green — guarantees cited in tests/test_foo.py:42",
    ],
)
def test_commit_message_unverified_claim_with_evidence_passes(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    assert mod.check_commit_message(msg) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "Looks clean on the cone walk.",
        "Appears orphaned — zero refs.",
        "Should be safe to delete.",
        "Seems correct based on the summary.",
    ],
)
def test_commit_message_inference_verdict_phrases_fail(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    hits = mod.check_commit_message(msg)
    assert hits, f"expected inference-verdict hit for: {phrase!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        "Per cursor summary the slice is closed.",
        "Per subagent report the refs are zero.",
        "Per peer's read all sites are NMD.",
    ],
)
def test_commit_message_echoed_upstream_summary_phrases_fail(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    hits = mod.check_commit_message(msg)
    assert hits, f"expected upstream-summary-echo hit for: {phrase!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        "Haven't verified the parallel bid/ask sites at server.py:2328-2333.",
        "Haven't checked whether the same gap applies upstream.",
        "Haven't enumerated the cone yet.",
        "Not verified this turn; flagging for follow-on.",
        "Not checked here; deferring to next slice.",
        "Unverified by me — relying on Cursor's enumeration.",
        "Separate verification needed for the producer cone.",
        "Further verification required before sign-off.",
        "Would need to verify the L1 site list before claiming closure.",
        "Would have to check the slice CSV first.",
        "Same gap applies to the bid/ask leaves at L2328-2333.",
        "Same pattern likely affects the adjacent _ext.get sites.",
        "Same issue presumably extends to the chain consumers.",
        "Parallel observation likely applies to the streaming path.",
        "Presumably affects the L1 SSE diag path as well.",
        "Likely applies to the prediction_engine consumer.",
        "Likely the case for market_state.py too.",
        "Out of scope of this turn — flagging for the next walk.",
        "Out of scope of this verification, but worth a follow-on.",
    ],
)
def test_commit_message_unverified_admission_phrases_fail(phrase: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(phrase, encoding="utf-8")
    hits = mod.check_commit_message(msg)
    assert hits, f"expected unverified-admission hit for: {phrase!r}"
    assert any("unverified-admission" in h for h in hits), (
        f"expected admission-class label for: {phrase!r}; got {hits!r}"
    )


def test_commit_message_unverified_admission_meta_describing_checker_passes(tmp_path: Path) -> None:
    """Meta lines that describe the new checker family itself must not fire."""
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "Self-governance: extend commit-msg guard with unverified-admission patterns "
        "(parallel observation / scope-extension / verify-in-turn-or-omit).\n",
        encoding="utf-8",
    )
    assert mod.check_commit_message(msg) == []


def test_commit_message_unverified_admission_evidence_cite_does_not_redeem(tmp_path: Path) -> None:
    """Evidence cite cannot redeem an explicit unverified-admission — the admission IS the violation."""
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "Haven't verified server.py:2328 — flagged tests/test_foo.py::test_bar for next slice.\n",
        encoding="utf-8",
    )
    hits = mod.check_commit_message(msg)
    assert hits, "evidence cite must not bypass unverified-admission family"
    assert any("unverified-admission" in h for h in hits)


def test_agents_md_documents_verify_in_turn_rule() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Verify-in-turn-or-omit" in text
    assert '"Same gap applies"' in text or "Same gap applies" in text
    assert '"Haven\'t verified"' in text or "Haven't verified" in text


def test_agents_md_documents_action_not_documentation_rule() -> None:
    """Lock the §Action-not-documentation section presence + key contract phrases."""
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Action-not-documentation" in text
    assert "No documentation without code-fix scope" in text
    assert "ALL PLANS, ALL PHASES, MEMOS, AUDITS" in text  # operator-intent verbatim block
    # Honest limit re-affirmed
    assert "Rule files" in text and "are not in scope" in text


def test_action_not_documentation_blocks_audit_only_commit(tmp_path: Path) -> None:
    """Pre-commit must block a commit that stages only an audit MD containing
    action language without paired code change."""
    audit = tmp_path / "governance" / "audits" / "fake_audit_v1.md"
    audit.parent.mkdir(parents=True)
    audit.write_text(
        "# Audit\n\n## FIND-FAKE-1\nFix direction: do the thing.\n",
        encoding="utf-8",
    )
    staged = {"governance/audits/fake_audit_v1.md"}
    # Patch REPO_ROOT for this test so the helper reads from tmp.
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_action_not_documentation(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits, "expected action-not-documentation hit on doc-only audit commit"
    assert any("Action-not-documentation" in h for h in hits)
    assert any("FIND-" in h for h in hits), "must name the action token that fired"


def test_action_not_documentation_allows_audit_paired_with_code(tmp_path: Path) -> None:
    """Paired audit + .py code change in the same commit must pass the gate."""
    audit = tmp_path / "governance" / "audits" / "fake_audit_v1.md"
    audit.parent.mkdir(parents=True)
    audit.write_text("# Audit\n\n## FIND-FAKE-1\nFix direction: do the thing.\n", encoding="utf-8")
    staged = {"governance/audits/fake_audit_v1.md", "some_module.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_action_not_documentation(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits == [], f"paired audit + .py code should pass; got {hits!r}"


def test_action_not_documentation_allows_pure_signoff_pin_artifact(tmp_path: Path) -> None:
    """A .json sign-off pin under governance/artifacts/ is NOT in scope of this rule
    (rule explicitly carves out sign-off pins). Commits with only pin artifacts pass."""
    pin = tmp_path / "governance" / "artifacts" / "schwab_v4_register_build_meta.json"
    pin.parent.mkdir(parents=True)
    pin.write_text('{"register_content_sha256": "abc123"}\n', encoding="utf-8")
    staged = {"governance/artifacts/schwab_v4_register_build_meta.json"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_action_not_documentation(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits == [], f"sign-off pin update should pass (carved out); got {hits!r}"


def test_action_not_documentation_allows_rule_file_update(tmp_path: Path) -> None:
    """AGENTS.md / CLAUDE.md / MEMORY.md are rule files, explicitly carved out
    of the Action-not-documentation rule. Updates to them should pass even
    without paired code."""
    rule_md = tmp_path / "AGENTS.md"
    rule_md.write_text("## Some rule\nFix direction: future code.\n", encoding="utf-8")
    staged = {"AGENTS.md"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_action_not_documentation(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits == [], f"rule-file update should pass (out of scope); got {hits!r}"


def test_agents_md_documents_storage_needs_consumer_rule() -> None:
    """Lock §Storage-needs-consumer rule presence + key contract phrases."""
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Storage-needs-consumer" in text
    assert "No writer without a consumer" in text
    # Operator-intent block verbatim
    assert "WE BETTER NOT HAVE GOVERNANCE, OR RULES, ETC WITH NO PATH TO CODE CHANGES UPDATE" in text
    # 4-dormant-table precedent must be named so the rule is grounded in evidence
    for tbl in ("level_crosses", "confluence_log", "model_accuracy", "session_log"):
        assert tbl in text, f"§Storage-needs-consumer rule must cite {tbl} as the empirical precedent"


def test_storage_needs_consumer_blocks_new_writer_without_caller(tmp_path: Path) -> None:
    """Pre-commit must block a commit that adds new INSERT statements in db.py
    without staging a production caller in the same commit."""
    import subprocess

    # Set up a fake git repo with HEAD db.py + staged db.py adding a new INSERT.
    (tmp_path / "db.py").write_text(
        "import sqlite3\n"
        "def existing_writer(conn):\n"
        "    conn.execute('INSERT INTO existing_table VALUES (1)')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    # Now stage a new writer for a new table — no production caller staged.
    (tmp_path / "db.py").write_text(
        "import sqlite3\n"
        "def existing_writer(conn):\n"
        "    conn.execute('INSERT INTO existing_table VALUES (1)')\n"
        "def new_dormant_writer(conn):\n"
        "    conn.execute('INSERT INTO new_dormant_table VALUES (?)', (1,))\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)

    staged = {"db.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_storage_writer_has_consumer(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits, "expected Storage-needs-consumer hit for new INSERT without paired caller"
    assert any("Storage-needs-consumer" in h for h in hits)
    assert any("new_dormant" not in h or "INSERT" in h for h in hits)


def test_storage_needs_consumer_allows_new_writer_with_paired_caller(tmp_path: Path) -> None:
    """Same shape but with a paired production caller staged — must pass."""
    import subprocess

    (tmp_path / "db.py").write_text("# db\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    (tmp_path / "db.py").write_text(
        "def new_writer(conn):\n"
        "    conn.execute('INSERT INTO new_table VALUES (?)', (1,))\n",
        encoding="utf-8",
    )
    (tmp_path / "server.py").write_text(
        "from db import new_writer\n"
        "def fetch_state(conn):\n"
        "    new_writer(conn)\n",
        encoding="utf-8",
    )
    staged = {"db.py", "server.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_storage_writer_has_consumer(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits == [], f"new writer + paired caller in same commit should pass; got {hits!r}"


def test_storage_needs_consumer_ignores_db_edits_with_no_new_inserts(tmp_path: Path) -> None:
    """Refactor that doesn't add new INSERTs (e.g., docstring tweak, reader-only change)
    must NOT fire the rule even without a paired caller."""
    import subprocess

    (tmp_path / "db.py").write_text(
        "def existing_writer(conn):\n"
        "    conn.execute('INSERT INTO existing VALUES (1)')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    # Pure docstring / formatting change — no new INSERTs.
    (tmp_path / "db.py").write_text(
        '"""DB module docstring."""\n'
        "def existing_writer(conn):\n"
        "    conn.execute('INSERT INTO existing VALUES (1)')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)

    staged = {"db.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_storage_writer_has_consumer(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits == [], f"refactor with no new INSERTs should pass; got {hits!r}"


def test_persistence_writer_has_reader_no_triggers_passes() -> None:
    """Pass 1b: no persistence files staged -> no work."""
    staged = {"server.py", "static/index.html"}
    hits = mod.check_persistence_writer_has_reader(staged)
    assert hits == [], f"check should no-op when no persistence files staged; got {hits!r}"


def test_persistence_writer_has_reader_passes_for_table_with_real_gate(tmp_path: Path) -> None:
    """A new INSERT against a dormant table that's tracked in OPEN_ITEMS under
    [REAL-GATE: <tag>] must pass — the dormancy is intentional and disclosed."""
    import subprocess

    (tmp_path / "db.py").write_text("# db\n", encoding="utf-8")
    (tmp_path / "OPEN_ITEMS.md").write_text(
        "- [ ] DORMANT-TABLES-PRE-WIRE [REAL-GATE: unwalked-file] level_crosses, confluence_log, "
        "session_log — wire or drop in Passes 4-7.\n",
        encoding="utf-8",
    )
    (tmp_path / "governance" / "artifacts").mkdir(parents=True)
    (tmp_path / "governance" / "artifacts" / "persistence_consumer_map.json").write_text(
        '{"schema_version":1,"writers":[{"writer_fn":"log_level_cross","file":"db.py",'
        '"line":1,"tables_written":["level_crosses"],"production_callers":[],'
        '"read_consumers":{"level_crosses":[]},"status":"dormant"}]}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    (tmp_path / "db.py").write_text(
        "def log_level_cross(conn):\n"
        "    conn.execute('INSERT INTO level_crosses VALUES (?)', (1,))\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)

    staged = {"db.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_persistence_writer_has_reader(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits == [], f"REAL-GATE-tagged table should pass; got {hits!r}"


def test_persistence_writer_has_reader_fails_for_dormant_table_without_real_gate(tmp_path: Path) -> None:
    """A new INSERT against a table with no readers AND no REAL-GATE row fails."""
    import subprocess

    (tmp_path / "db.py").write_text("# db\n", encoding="utf-8")
    (tmp_path / "OPEN_ITEMS.md").write_text("# nothing relevant here\n", encoding="utf-8")
    (tmp_path / "governance" / "artifacts").mkdir(parents=True)
    (tmp_path / "governance" / "artifacts" / "persistence_consumer_map.json").write_text(
        '{"schema_version":1,"writers":[{"writer_fn":"log_orphan","file":"db.py",'
        '"line":1,"tables_written":["orphan_table"],"production_callers":[],'
        '"read_consumers":{"orphan_table":[]},"status":"dormant"}]}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    (tmp_path / "db.py").write_text(
        "def log_orphan(conn):\n"
        "    conn.execute('INSERT INTO orphan_table VALUES (?)', (1,))\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)

    staged = {"db.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_persistence_writer_has_reader(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits, "expected Pass 1b hit for INSERT into table with 0 readers and no REAL-GATE row"
    assert any("orphan_table" in h for h in hits)
    assert any("Pass 1b" in h for h in hits)


def test_persistence_writer_has_reader_passes_for_table_with_existing_reader(tmp_path: Path) -> None:
    """When the map shows the table HAS a read consumer, new INSERT passes."""
    import subprocess

    (tmp_path / "db.py").write_text("# db\n", encoding="utf-8")
    (tmp_path / "OPEN_ITEMS.md").write_text("", encoding="utf-8")
    (tmp_path / "governance" / "artifacts").mkdir(parents=True)
    (tmp_path / "governance" / "artifacts" / "persistence_consumer_map.json").write_text(
        '{"schema_version":1,"writers":[{"writer_fn":"insert_snapshot","file":"db.py",'
        '"line":1,"tables_written":["snapshots"],"production_callers":["server.py"],'
        '"read_consumers":{"snapshots":["calibration/analyze_phase3.py"]},"status":"live"}]}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    (tmp_path / "db.py").write_text(
        "def insert_snapshot(conn):\n"
        "    conn.execute('INSERT INTO snapshots VALUES (?)', (1,))\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)

    staged = {"db.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_persistence_writer_has_reader(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits == [], f"table with existing reader should pass; got {hits!r}"


def test_persistence_writer_has_reader_ignores_pre_existing_inserts(tmp_path: Path) -> None:
    """Refactor that doesn't change the set of INSERTed tables must not fire,
    even if all of those tables are dormant."""
    import subprocess

    (tmp_path / "db.py").write_text(
        "def log_orphan(conn):\n"
        "    conn.execute('INSERT INTO orphan_table VALUES (1)')\n",
        encoding="utf-8",
    )
    (tmp_path / "OPEN_ITEMS.md").write_text("", encoding="utf-8")
    (tmp_path / "governance" / "artifacts").mkdir(parents=True)
    (tmp_path / "governance" / "artifacts" / "persistence_consumer_map.json").write_text(
        '{"schema_version":1,"writers":[{"writer_fn":"log_orphan","file":"db.py",'
        '"line":1,"tables_written":["orphan_table"],"production_callers":[],'
        '"read_consumers":{"orphan_table":[]},"status":"dormant"}]}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    # Add docstring; INSERT target table unchanged.
    (tmp_path / "db.py").write_text(
        '"""docstring"""\n'
        "def log_orphan(conn):\n"
        "    conn.execute('INSERT INTO orphan_table VALUES (1)')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)

    staged = {"db.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_persistence_writer_has_reader(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits == [], (
        f"refactor that doesn't add new INSERT-target tables should pass; got {hits!r}"
    )


def test_persistence_map_fresh_no_triggers_passes() -> None:
    """When no persistence-source / tool / map paths are staged, Pass 2b stays quiet."""
    staged = {"server.py", "tests/test_unrelated.py"}
    hits = mod.check_persistence_map_fresh(staged)
    assert hits == [], f"check should no-op when no triggers staged; got {hits!r}"


def test_persistence_map_fresh_stale_map_fails_when_persistence_source_staged(monkeypatch) -> None:
    """When the on-disk map is STALE vs sources (real persistence drift) and the
    map is not re-staged, Pass 2b must fail. Behavior-aware (2026-06-03): the
    trigger is staleness, not the mere fact that db.py is staged."""
    monkeypatch.setattr(mod, "_persistence_map_matches_sources", lambda: (False, "drift"))
    staged = {"db.py"}  # map NOT staged
    hits = mod.check_persistence_map_fresh(staged)
    assert hits, "expected Pass 2b hit when persistence map stale vs sources without re-stage"
    assert any("persistence_consumer_map.json" in h for h in hits)
    assert any("Pass 2b" in h for h in hits)


def test_persistence_map_fresh_stale_map_fails_when_tool_staged(monkeypatch) -> None:
    """Editing the audit tool with a stale map (output shape changed) must fail."""
    monkeypatch.setattr(mod, "_persistence_map_matches_sources", lambda: (False, "drift"))
    staged = {"tools/audit_persistence_consumers.py"}  # map NOT staged
    hits = mod.check_persistence_map_fresh(staged)
    assert hits, "expected Pass 2b hit when audit tool staged with stale map"
    assert any("persistence_consumer_map.json" in h for h in hits)


def test_persistence_map_fresh_behavior_neutral_edit_passes(monkeypatch) -> None:
    """The fix: a behavior-neutral edit to db.py (e.g. removing an unused import)
    leaves the map matching sources AND identical to HEAD. Pass 2b must NOT demand
    a phantom map row — an unsatisfiable gate forces bypasses. Regression lock for
    the 2026-06-03 unsatisfiable-gate incident."""
    monkeypatch.setattr(mod, "_persistence_map_matches_sources", lambda: (True, ""))
    monkeypatch.setattr(mod, "_persistence_map_changed_vs_head", lambda: False)
    staged = {"db.py"}  # map NOT staged, but nothing to stage
    hits = mod.check_persistence_map_fresh(staged)
    assert hits == [], f"behavior-neutral db.py edit must pass Pass 2b; got {hits!r}"


def test_persistence_map_fresh_real_change_unstaged_map_fails(monkeypatch) -> None:
    """When the regenerated map differs from HEAD (a real persistence change) but
    the map is not staged, Pass 2b must fail and tell the committer to stage it."""
    monkeypatch.setattr(mod, "_persistence_map_matches_sources", lambda: (True, ""))
    monkeypatch.setattr(mod, "_persistence_map_changed_vs_head", lambda: True)
    staged = {"db.py"}  # map changed vs HEAD but NOT staged
    hits = mod.check_persistence_map_fresh(staged)
    assert hits, "expected Pass 2b hit when map changed vs HEAD but not staged"
    assert any("changed vs HEAD" in h for h in hits)


def test_persistence_map_fresh_passes_when_map_staged_alongside() -> None:
    """When both persistence source and map are staged AND the on-disk map matches
    current sources (Pass 2 just committed a fresh map), Pass 2b passes."""
    staged = {"db.py", "governance/artifacts/persistence_consumer_map.json"}
    hits = mod.check_persistence_map_fresh(staged)
    # The on-disk map at this point in the test suite is the one committed by Pass 2,
    # matching current db.py / calibration/writer.py. So --check should pass.
    assert hits == [], (
        f"map fresh + staged alongside source should pass; got {hits!r}. "
        "If this fails after a real persistence edit, regenerate with "
        "`python tools/audit_persistence_consumers.py --stable-time`."
    )


def test_storage_needs_consumer_tests_caller_alone_does_not_satisfy(tmp_path: Path) -> None:
    """A test-only caller does NOT count as a production caller — must still fire."""
    import subprocess

    (tmp_path / "db.py").write_text("# db\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "db.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )
    (tmp_path / "db.py").write_text(
        "def new_writer(conn):\n"
        "    conn.execute('INSERT INTO new_table VALUES (?)', (1,))\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_new_writer.py").write_text(
        "from db import new_writer\n"
        "def test_writer(): pass\n",
        encoding="utf-8",
    )
    staged = {"db.py", "tests/test_new_writer.py"}
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_storage_writer_has_consumer(staged)
    finally:
        mod.REPO_ROOT = orig_root
    assert hits, "test-only caller must not satisfy production-caller requirement"


def test_mvp_dataframe_ingress_passes_on_current_repo() -> None:
    assert mod.check_mvp_dataframe_ingress() == []


def test_institutional_contract_passes_on_current_repo() -> None:
    assert mod.check_institutional_contract() == []


def test_fusion_only_card_contract_passes_on_current_repo() -> None:
    assert mod.check_fusion_only_card_contract() == []


def test_four_horizon_promotion_contract_passes_on_current_repo() -> None:
    assert mod.check_four_horizon_promotion_contract() == []


def test_training_anchor_roster_contract_passes_on_current_repo() -> None:
    assert mod.check_training_anchor_roster_contract() == []


def test_mandatory_enforcement_registry_passes_on_current_repo() -> None:
    assert mod.check_mandatory_enforcement_registry() == []


def test_promoted_agents_rules_mechanically_locked() -> None:
    assert mod.check_promoted_agents_rules_mechanically_locked() == []


def test_external_rule_tools_wired() -> None:
    assert mod.check_external_rule_tools_wired() == []


def test_meet_or_exceed_cycle_documentation_passes_on_current_repo() -> None:
    assert mod.check_meet_or_exceed_cycle_documentation() == []


def test_definition_of_done_for_fixes_contract_passes_on_current_repo() -> None:
    assert mod.check_definition_of_done_for_fixes_contract() == []


def test_meet_or_exceed_cycle_documentation_requires_universal_scope(tmp_path: Path, monkeypatch) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "Meet-or-Exceed Closure Cycle\nVERDICT: MET\n",
        encoding="utf-8",
    )
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_meet_or_exceed_cycle_documentation()
    finally:
        mod.REPO_ROOT = orig_root
    assert hits
    assert any("universal-scope marker" in h for h in hits)


@pytest.mark.parametrize(
    "body",
    [
        "Slice mostly meets the standard — ship it.",
        "VERDICT: PARTIAL\nGATE_TABLE:\n  tests: MET",
        "Grade: B+ on institutional contract.",
        "Standard met for this slice only — operator coherence done.",
        "VERDICT applies to the operator coherence slice.",
    ],
)
def test_meet_or_exceed_signoff_banned_verdicts(body: str, tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(body, encoding="utf-8")
    hits = mod.check_meet_or_exceed_signoff(msg)
    assert hits


def test_meet_or_exceed_signoff_verdict_met_passes(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "OBJECTIVE: land Objective→Code→Audit mechanical lock\n"
        "AUDIT: CLEAN — python tools/enforce_all_rules.py --objective-audit\n"
        "VERDICT: MET\nCYCLE_ITERATIONS: 2\nGATE_TABLE:\n  tests: MET — tests/test_batch2\n",
        encoding="utf-8",
    )
    assert mod.check_meet_or_exceed_signoff(msg) == []


def test_objective_code_audit_contract() -> None:
    assert mod.check_objective_code_audit_contract() == []


def test_objective_code_audit_signoff_requires_objective_and_audit_clean(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("VERDICT: MET\n", encoding="utf-8")
    hits = mod.check_objective_code_audit_signoff(msg)
    assert any("OBJECTIVE" in h for h in hits)
    assert any("AUDIT: CLEAN" in h for h in hits)


def test_map_knockout_columns_to_encoder_indices_v2_spy_bundle() -> None:
    import torch
    from active_bundle_contract import active_bundle_dir
    from arch_competition.ablation_bundle_inference import map_knockout_columns_to_encoder_indices

    bundle = active_bundle_dir("SPY", "1c", models_dir=mod.REPO_ROOT / "models")
    ckpt = torch.load(str(bundle / "lstm_SPY_1c.pt"), map_location="cpu", weights_only=False)
    mapped = map_knockout_columns_to_encoder_indices(ckpt, ["net_gamma"], stream="lstm_5m")
    if mapped.get("error") == "encoder_schema_version=0_unsupported":
        pytest.skip("SPY active LSTM bundle is pre-v2 encoder — host retrain required for v2 map proof")
    assert mapped["reachable"] is True, mapped
    assert mapped["post_mask_indices"]
    assert mapped["effective_snapshot_columns"] == ["net_gamma"]


def test_offline_v2_knockout_columns_excludes_v3_only_atoms() -> None:
    from arch_competition.ablation_bundle_inference import offline_v2_knockout_snapshot_columns

    assert offline_v2_knockout_snapshot_columns("absorption_score", "lstm") == []
    assert offline_v2_knockout_snapshot_columns("net_gamma", "lstm") == ["net_gamma"]


def test_ablation_placement_validity_passes_after_fix2() -> None:
    """Offline v2 bundles + FIX 2 map — placement audit must pass (no retrain required)."""
    result = mod.audit_ablation_placement_validity(tickers=["SPY"], horizons=["1c"])
    if not result["ok"]:
        joined = " ".join(str(x) for x in (result.get("errors") or []))
        if "offline ablation loads failed" in joined:
            pytest.skip("SPY active bundles need v2 encoder offline load — host retrain required")
    assert result["ok"] is True, result
    stats = result.get("stats") or {}
    assert stats.get("lstm_noop_knockout_atoms", 99) == 0
    assert stats.get("transformer_noop_knockout_atoms", 99) == 0


def test_run_objective_code_audit_static_passes() -> None:
    """Single full static integration — real repo-wide locks including ablation grid."""
    result = mod.run_objective_code_audit(staged=set(), runtime=False, force_fresh_static=True)
    assert result["static_ok"] is True, result.get("static_errors")
    assert result["audit"] == "objective_code_audit"
    assert "full repo" in result.get("scope", "")


def test_objective_code_audit_universal_scope() -> None:
    assert mod.check_objective_code_audit_documentation() == []


def test_objective_code_audit_situational_runtime_dispatch(monkeypatch) -> None:
    """Unrelated staged path skips ablation runtime; ablation cone path triggers it."""
    monkeypatch.setattr(
        mod,
        "audit_ablation_placement_validity",
        lambda **kw: {"ok": True, "stats": {}, "errors": []},
    )

    ui_only = mod.run_situational_runtime_audits(staged={"static/index.html"})
    assert "ablation_placement_validity" in (ui_only.get("skipped_runtime_audits") or [])

    ml_staged = mod.run_situational_runtime_audits(staged={"ml_predict.py"})
    assert "ablation_placement_validity" in (ml_staged.get("applied_runtime_audits") or [])
    assert "runtime_ok" in ml_staged

    forced = mod.run_situational_runtime_audits(staged={"static/index.html"}, force_all=True)
    assert "ablation_placement_validity" in (forced.get("applied_runtime_audits") or [])


def test_institutional_contract_banned_analytics_stale_sse_pattern(tmp_path: Path, monkeypatch) -> None:
    bad = tmp_path / "server.py"
    bad.write_text(
        'def _resolve_ticker_param():\n'
        '    pass\n'
        'analytics_refresh_due\n'
        '@app.get("/api/build")\n'
        'md["analytics_stale"] = bool(sse_live or (age >= ttl))\n',
        encoding="utf-8",
    )
    good = tmp_path / "AGENTS.md"
    good.write_text(
        "Mandatory enforcement registry\nMeet-or-Exceed Closure Cycle\n"
        "Scope — universal, not gated\nfull repo\none cycle, one verdict vocabulary\nVERDICT: MET\n",
        encoding="utf-8",
    )
    ui = tmp_path / "static"
    ui.mkdir()
    (ui / "index.html").write_text(
        "INSTITUTIONAL_BUNDLE_TRUST_SEC\nfunction laneStaleOperatorLabel\nSYNCING ANALYTICS\n",
        encoding="utf-8",
    )
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_institutional_contract()
    finally:
        mod.REPO_ROOT = orig_root
    assert hits
    assert any("analytics_stale must not be sse_live alone" in h for h in hits)


def test_encoder_cone_documentation_passes_on_current_repo() -> None:
    import check_encoder_cone_tests as enc

    assert enc.check_encoder_cone_documentation() == []


def test_encoder_cone_collects_lstm_and_transformer_tests() -> None:
    import check_encoder_cone_tests as enc

    paths = enc.collect_encoder_cone_test_paths()
    assert "tests/test_lstm_sequence_input.py" in paths
    assert "tests/test_transformer_sequence_input.py" in paths
    assert "tests/test_ml_feature_provenance.py" in paths
    assert len(paths) >= 10


def test_encoder_cone_trigger_on_lstm_data_staged() -> None:
    import check_encoder_cone_tests as enc

    assert enc.staged_touches_encoder_cone({"lstm_data.py"})
    assert not enc.staged_touches_encoder_cone({"server.py"})


def test_encoder_cone_commit_claim_blocks_false_green(tmp_path: Path) -> None:
    import check_encoder_cone_tests as enc

    hits = enc.check_encoder_cone_commit_claim(
        "LSTM encoder fix — 27 passed, ready to ship.",
        {"lstm_data.py"},
    )
    assert hits
    assert enc.check_encoder_cone_commit_claim(
        "encoder-cone: 134 passed\n",
        {"lstm_data.py"},
    ) == []


def test_mvp_dataframe_ingress_flags_raw_to_dict_on_mvp_path(tmp_path: Path) -> None:
    bad = tmp_path / "bad_meta.py"
    bad.write_text(
        "def f(df):\n"
        "    rows = df.to_dict('records')\n"
        "    return build_inference_snapshot_v1_from_db_row(db_row=rows[0])\n",
        encoding="utf-8",
    )
    orig_root = mod.REPO_ROOT
    mod.REPO_ROOT = tmp_path
    try:
        hits = mod.check_mvp_dataframe_ingress()
    finally:
        mod.REPO_ROOT = orig_root
    assert len(hits) == 1
    assert "records_for_mvp_from_dataframe" in hits[0]


# ── O-56: ablated training is the only valid retrain target (AGENTS §Ablation contract) ──


def test_check_ablated_training_only_passes_on_real_orchestrator():
    # the committed orchestrator must enable ED_APPLY_ABLATION_SURVIVORS=1 -> no errors
    assert mod.check_ablated_training_only() == []


def test_check_ablated_training_only_flags_full_feature_default(tmp_path, monkeypatch):
    bad = tmp_path / "orch.ps1"
    bad.write_text('$env:ED_APPLY_ABLATION_SURVIVORS = "0"\n', encoding="utf-8")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "ABLATED_TRAINING_ORCHESTRATOR", "orch.ps1")
    errs = mod.check_ablated_training_only()
    assert errs and "ED_APPLY_ABLATION_SURVIVORS" in errs[0]


def test_check_ablated_training_only_flags_missing_enable(tmp_path, monkeypatch):
    bad = tmp_path / "orch.ps1"
    bad.write_text('$env:ED_SCHEDULER_AUTO_PROMOTE = "1"\n', encoding="utf-8")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "ABLATED_TRAINING_ORCHESTRATOR", "orch.ps1")
    errs = mod.check_ablated_training_only()
    assert errs and "must set ED_APPLY_ABLATION_SURVIVORS=1" in errs[0]


def test_zero_bias_ablation_contract_agents_markers():
    agents = mod.REPO_ROOT / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    for marker in mod._ZERO_BIAS_AGENTS_MARKERS:
        assert marker in text, f"missing ZERO-BIAS marker {marker!r}"


def test_zero_bias_ablation_contract_stage2_clears_pinning():
    """Stage 2: atomic manifest + full sequence ingest — no members-as-assignment pinning."""
    errs = mod.check_zero_bias_ablation_contract()
    joined = "\n".join(errs)
    assert "grouped" not in joined.lower()
    assert "live LSTM inputs pre-excluded" not in joined
    assert "pinned" not in joined.lower()
    assert "members-as-assignment" not in joined.lower()
    assert errs == [], joined


def test_zero_bias_ablation_contract_stage1_clears_grouped_and_cf_exclusion():
    """Stage 1 regression: atomic pass strings + cf_* in manifest (superseded by stage2 pinning clear)."""
    test_zero_bias_ablation_contract_stage2_clears_pinning()


def test_zero_bias_transformer_ingest_mapping_is_5m_stream_only():
    """Transformer holdout permutes ENCODED_FEATURES_5M channels only — not lstm_1m / X_conf."""
    assert mod.ZERO_BIAS_FEATURE_MODEL_INGEST_FAMILIES["transformer"] == ("lstm_5m",)
    assert "lstm_1m" not in mod.ZERO_BIAS_FEATURE_MODEL_INGEST_FAMILIES["transformer"]


def test_write_feature_ablation_manifest_skips_reconcile_when_db_missing(monkeypatch, tmp_path):
    """Missing DB_PATH file: manifest write proceeds without DB-wire reconcile."""
    import build_feature_assignment_matrix_v2 as fam

    payload = {"groups": [{"group_id": "g1", "ingest_status": "not_wired"}]}
    monkeypatch.setattr(fam, "resolve_ablation_universe", lambda **kw: payload)
    monkeypatch.setattr(
        fam,
        "write_feature_ablation_universe_xlsx",
        lambda **kw: tmp_path / "universe.xlsx",
    )
    monkeypatch.setattr("db.DB_PATH", str(tmp_path / "missing.db"))
    out = tmp_path / "manifest.json"
    fam.write_feature_ablation_manifest(out)
    assert out.is_file()
    written = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert written["groups"][0]["ingest_status"] == "not_wired"


def test_write_feature_ablation_manifest_fails_closed_when_db_reconcile_raises(
    monkeypatch, tmp_path
):
    """Existing DB + reconcile failure must raise — no silent degraded manifest."""
    import build_feature_assignment_matrix_v2 as fam

    payload = {"groups": []}
    monkeypatch.setattr(fam, "resolve_ablation_universe", lambda **kw: payload)
    monkeypatch.setattr(
        fam,
        "write_feature_ablation_universe_xlsx",
        lambda **kw: tmp_path / "universe.xlsx",
    )
    db_file = tmp_path / "ed_console.db"
    db_file.write_bytes(b"sqlite")
    monkeypatch.setattr("db.DB_PATH", str(db_file))

    def _boom(_manifest, _db_path):
        raise RuntimeError("reconcile failed")

    monkeypatch.setattr(
        "tools.feature_curation_gate.reconcile_manifest_ingest_status_to_db_wire",
        _boom,
    )
    out = tmp_path / "manifest.json"
    with pytest.raises(RuntimeError, match="reconcile failed"):
        fam.write_feature_ablation_manifest(out)
    assert not out.is_file()


def test_reconcile_manifest_preserves_registered_engineered_in_cone():
    """Registered engineer_features columns stay in_cone even when absent from DB wire."""
    from tools.feature_curation_gate import reconcile_manifest_ingest_status_to_db_wire

    manifest = {
        "groups": [
            {
                "group_id": "reg__atomic__candle_body_pct",
                "disposition": "ABLATE",
                "atomic_column": "candle_body_pct",
                "catalog_tier": "REGISTERED_UNIVERSE",
                "ingest_status": "not_wired",
            },
            {
                "group_id": "schwab__example_leaf",
                "disposition": "ABLATE",
                "atomic_column": "example_leaf",
                "catalog_tier": "ML_ABLATION_CANDIDATE",
                "ingest_status": "not_wired",
            },
        ]
    }
    out = reconcile_manifest_ingest_status_to_db_wire(manifest, db_path="__missing__.db")
    by_id = {g["group_id"]: g for g in out["groups"]}
    assert by_id["reg__atomic__candle_body_pct"]["ingest_status"] == "in_cone"
    assert by_id["schwab__example_leaf"]["ingest_status"] == "not_wired"


def test_zero_bias_ablation_contract_no_db_registered_not_wired(monkeypatch):
    """CI path without DB: registered engineered features cannot stay not_wired."""
    import json
    from copy import deepcopy

    real_path = mod.REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
    payload = json.loads(real_path.read_text(encoding="utf-8"))
    patched = deepcopy(payload)
    for g in patched.get("groups") or []:
        if g.get("group_id") == "reg__atomic__candle_body_pct":
            g["ingest_status"] = "not_wired"
            break
    else:
        raise AssertionError("expected reg__atomic__candle_body_pct in manifest")

    monkeypatch.setattr("db.DB_PATH", mod.REPO_ROOT / "__missing_for_test__.db")
    orig_read_text = Path.read_text

    def _read_text(self, *args, **kwargs):
        if self.resolve() == real_path.resolve():
            return json.dumps(patched)
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)
    errs = mod.check_zero_bias_ablation_contract()
    assert any("not_wired groups belong in the ML/DB wire cone" in e for e in errs)


def test_ablation_manifest_generator_has_no_model_stamp_builder():
    """Generator source must not retain legacy compound model-stamp builders."""
    assert mod.check_ablation_manifest_generator_no_model_preassignment() == []


def test_zero_bias_ablation_contract_rejects_manifest_model_stamps(monkeypatch):
    """Feature list must not carry model pre-assignment fields — vestigial members fail gate."""
    import json
    from copy import deepcopy
    from pathlib import Path

    real_path = mod.REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
    payload = json.loads(real_path.read_text(encoding="utf-8"))
    patched = deepcopy(payload)
    for g in patched.get("groups") or []:
        if g.get("disposition") == "ABLATE":
            g["members"] = {"xgb": ["__stale_hand_stamp__"]}
            break
    else:
        raise AssertionError("no ABLATE group in leaf manifest")

    _orig_read = Path.read_text

    def _read_text(self, *args, **kwargs):
        if self.resolve() == real_path.resolve():
            return json.dumps(patched)
        return _orig_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)
    errs = mod.check_feature_list_no_model_preassignment()
    assert any("pre-ordain models" in e for e in errs), errs
    errs2 = mod.check_zero_bias_ablation_contract()
    assert any("pre-ordain models" in e for e in errs2), errs2


def test_zero_bias_ablation_contract_rejects_unmapped_feature_model(monkeypatch):
    """Injected ablation model with no ingest mapping must fail the build (no silent 3-of-N)."""
    import json
    from copy import deepcopy
    from pathlib import Path

    real_path = mod.REPO_ROOT / "governance" / "artifacts" / "feature_ablation_manifest_leaf.json"
    payload = json.loads(real_path.read_text(encoding="utf-8"))
    patched = deepcopy(payload)
    patched["ablation_method"] = dict(patched.get("ablation_method") or {})
    patched["ablation_method"]["models"] = list(
        patched["ablation_method"].get("models") or ["xgb", "lstm", "transformer"]
    ) + ["newmodel"]

    _orig_read = Path.read_text

    def _read_text(self, *args, **kwargs):
        if self.resolve() == real_path.resolve():
            return json.dumps(patched)
        return _orig_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)
    errs = mod.check_zero_bias_ablation_contract()
    assert any("newmodel" in e and "NO ingest mapping" in e for e in errs), errs


def _write_ablation_report_fixture(tmp_path, payload: dict, *, leaf: bool = True) -> None:
    import json

    art = tmp_path / "governance" / "artifacts"
    art.mkdir(parents=True)
    name = "feature_ablation_report_leaf.json" if leaf else "feature_ablation_report.json"
    (art / name).write_text(json.dumps(payload), encoding="utf-8")


def _fusion_cell(
    hz: str,
    *,
    group_id: str = "feat_test",
    model_family: str = "xgb",
    delta: float = 0.001,
) -> dict:
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS

    layers = list(FULL_STACK_MODEL_LAYERS)
    entry = [model_family] if model_family in ("xgb", "lstm", "transformer") else ["xgb", "lstm", "transformer"]
    return {
        "model_family": model_family,
        "horizon_slug": hz,
        "group_id": group_id,
        "status": "ok",
        "baseline_multiclass_log_loss": 1.0,
        "permuted_multiclass_log_loss": 1.0 + delta,
        "log_loss_delta": delta,
        "ablation_kind": "whole_stack_feature_group",
        "decision_mode": "full_fusion",
        "stack_entry_layers": entry,
        "stack_layers_scored": layers,
        "mc_stack_probability_source": "stack_probs_meta_or_weighted",
        "pool_tickers": ["SPY", "QQQ", "IWM"],
        "paired_rows": 42,
    }


def _full_stack_report_payload(**extra) -> dict:
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS

    base = {
        "source_manifest": "governance/artifacts/feature_ablation_manifest_leaf.json",
        "full_stack_layers": list(FULL_STACK_MODEL_LAYERS),
        "stage3_pool_tickers": ["SPY", "QQQ", "IWM"],
    }
    base.update(extra)
    return base


def test_full_stack_ablation_coverage_rejects_legacy_when_leaf_missing(tmp_path, monkeypatch):
    """Legacy compound report must not satisfy Part B when leaf report was never produced."""
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    _write_ablation_report_fixture(
        tmp_path,
        _full_stack_report_payload(
            source_manifest="governance/artifacts/feature_ablation_manifest.json",
            whole_stack_feature_cells=[_fusion_cell("1c")],
        ),
        leaf=False,
    )
    errs = mod.check_full_stack_ablation_coverage()
    assert len(errs) == 1, errs
    assert "leaf ablation report missing" in errs[0]
    assert "not admissible" in errs[0]
    assert "--ablation" in errs[0]


def test_full_stack_ablation_coverage_stale_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    _write_ablation_report_fixture(
        tmp_path,
        _full_stack_report_payload(
            source_manifest="governance/artifacts/feature_ablation_manifest.json",
            whole_stack_feature_cells=[_fusion_cell("1c")],
        ),
        leaf=True,
    )
    errs = mod.check_full_stack_ablation_coverage()
    assert any("STALE" in e and "leaf" in e for e in errs), errs


def test_full_stack_ablation_coverage_zero_fusion(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    _write_ablation_report_fixture(
        tmp_path,
        _full_stack_report_payload(whole_stack_feature_cells=[]),
    )
    errs = mod.check_full_stack_ablation_coverage()
    assert any("CONTIGUOUS 7-layer stack" in e for e in errs), errs


def test_full_stack_ablation_coverage_missing_horizons(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    _write_ablation_report_fixture(
        tmp_path,
        _full_stack_report_payload(whole_stack_feature_cells=[_fusion_cell("1c")]),
    )
    errs = mod.check_full_stack_ablation_coverage()
    assert any(
        "missing horizons" in e
        or "missing scored (feature×model×horizon)" in e
        or "2632" in e
        for e in errs
    ), errs


def test_full_stack_ablation_coverage_rejects_missing_model_family(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    bad = _fusion_cell("1c")
    bad.pop("model_family")
    _write_ablation_report_fixture(
        tmp_path,
        _full_stack_report_payload(whole_stack_feature_cells=[bad]),
    )
    errs = mod.check_full_stack_ablation_coverage()
    assert any("model_family" in e for e in errs), errs


def test_full_stack_ablation_coverage_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS
    from tools.feature_curation_gate import ablation_grid_groups, load_ablation_manifest

    groups = ablation_grid_groups(load_ablation_manifest())
    n_groups = len(groups)
    cells = [
        _fusion_cell(hz, group_id=g["group_id"], model_family=m)
        for g in groups
        for hz in ("1c", "5c", "15c", "60c")
        for m in FULL_STACK_MODEL_LAYERS
    ]
    assert len(cells) == n_groups * 7 * 4, len(cells)
    _write_ablation_report_fixture(
        tmp_path,
        _full_stack_report_payload(whole_stack_feature_cells=cells),
    )
    assert mod.check_full_stack_ablation_coverage() == []


def test_production_fusion_score_path_contract_passes():
    """Ablation must use unified wire-row scorer — not production_fusion_payload_for_stack fork."""
    assert mod.check_production_fusion_score_path_contract() == []


def test_unified_ablation_scorer_used_under_scoring_pass(monkeypatch):
    """ED_ABLATION_SCORING_PASS must route _production_fusion_prob_for_row to unified scorer."""
    from unittest.mock import patch

    from arch_competition.stack_bundle_eval_v1 import (
        ABLATION_SCORING_PASS_ENV,
        _production_fusion_prob_for_row,
    )

    row = {"ts_utc": 1_700_000_000.0, "outcome_1c": "up", "spot": 500.0}
    monkeypatch.setenv(ABLATION_SCORING_PASS_ENV, "1")
    with patch(
        "arch_competition.ablation_bundle_inference.score_unified_ablation_fusion_from_wire_row",
        return_value=([0.4, 0.35, 0.25], 0, None, {"stack_layers_scored": ["xgb", "fusion"], "scoring_path": "unified_wire_row_only"}),
    ) as unified:
        triplet, yt, skip, audit = _production_fusion_prob_for_row(
            row,
            ticker="SPY",
            target_column="outcome_1c",
            hist_db=None,
        )
    unified.assert_called_once()
    assert skip is None
    assert triplet == [0.4, 0.35, 0.25]
    assert yt == 0
    assert audit.get("scoring_path") == "unified_wire_row_only"


def test_full_stack_ablation_coverage_rejects_partial_stack_layers(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    cells = [_fusion_cell("1c")]
    _write_ablation_report_fixture(
        tmp_path,
        {
            "source_manifest": "governance/artifacts/feature_ablation_manifest_leaf.json",
            "full_stack_layers": ["xgb", "lstm", "transformer"],
            "whole_stack_feature_cells": cells,
        },
    )
    errs = mod.check_full_stack_ablation_coverage()
    assert any("contiguous 7-layer stack" in e for e in errs), errs


def test_full_stack_ablation_coverage_rejects_anchor_ticker_axis(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    bad = _fusion_cell("1c")
    bad["anchor_ticker"] = "SPY"
    _write_ablation_report_fixture(
        tmp_path,
        _full_stack_report_payload(whole_stack_feature_cells=[bad]),
    )
    errs = mod.check_full_stack_ablation_coverage()
    assert any("anchor_ticker" in e for e in errs), errs


def test_full_stack_ablation_coverage_rejects_missing_pool_tickers(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    bad = _fusion_cell("1c")
    bad.pop("pool_tickers")
    _write_ablation_report_fixture(
        tmp_path,
        _full_stack_report_payload(whole_stack_feature_cells=[bad]),
    )
    errs = mod.check_full_stack_ablation_coverage()
    assert any("pool_tickers" in e for e in errs), errs


def test_universal_code_quality_contract() -> None:
    assert mod.check_universal_code_quality_contract() == []


def test_universal_code_quality_audit_passes_on_current_repo() -> None:
    result = mod.run_universal_code_quality_audit(staged=set())
    assert result["ok"] is True, result.get("errors")


def test_staged_simplicity_long_function_warns_not_blocks(tmp_path: Path, monkeypatch) -> None:
    """Pre-existing orchestrator-scale functions must not fail pre-commit on touch alone."""
    repo = tmp_path
    gate = repo / "tools" / "feature_curation_gate.py"
    gate.parent.mkdir(parents=True)
    body = "def build_ablation_confirm_report():\n" + "    x = 1\n" * 160 + "\n"
    gate.write_text(body, encoding="utf-8")
    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    errors, warnings = mod.audit_staged_python_simplicity({"tools/feature_curation_gate.py"})
    assert errors == []
    assert any("build_ablation_confirm_report" in w for w in warnings)


def test_staged_simplicity_duplicate_def_blocks(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path
    mod_py = repo / "foo.py"
    mod_py.write_text(
        "def helper():\n    return 1\n\ndef helper():\n    return 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    errors, warnings = mod.audit_staged_python_simplicity({"foo.py"})
    assert any("duplicate function" in e for e in errors)
    assert warnings == []


def test_ablation_preflight_ready_equals_unbiased_only(monkeypatch):
    """Preflight ready must never mean whole-stack-only or production-path-only without disclosure."""
    from tools.feature_curation_gate import load_ablation_manifest, run_ablation_preflight

    manifest = load_ablation_manifest()
    pf = run_ablation_preflight(
        manifest,
        db_path="nonexistent.db",
        tickers=["SPY"],
    )
    assert pf["ready"] is False
    assert pf["ready"] == pf["ready_for_unbiased_ablation"]
    assert pf["ready_for_whole_stack"] is False


def test_ablation_agnostic_ingest_contract():
    assert mod.check_ablation_agnostic_ingest_contract() == []


def test_ablation_score_path_bias_audit_passes():
    from tools.feature_curation_gate import audit_ablation_score_path_bias

    result = audit_ablation_score_path_bias()
    assert result.get("ok") is True, result.get("errors") or result.get("checks")


def test_ablation_full_stack_non_negotiable_contract():
    assert mod.check_ablation_full_stack_non_negotiable() == []


def test_ablation_integrity_audit_static_passes():
    from tools.check_fix_everything_we_touch import run_ablation_integrity_audit

    result = run_ablation_integrity_audit(runtime=False)
    assert result["static_ok"] is True, result.get("static_errors")
    assert result["audit"] == "ablation_full_stack_non_negotiable"


def test_ablation_ci_empty_enriched_sample_fusion_equals_runnable(tmp_path, monkeypatch) -> None:
    """CI bootstrap DB: schema present, zero snapshot rows → enriched=[] stays fidelity-first."""
    from db import ensure_console_db_training_schema
    from tools.ablation_static_lock_index import (
        get_ablation_static_lock_index as _get_ablation_index,
        reset_ablation_static_lock_index_for_tests,
    )
    from tools.feature_curation_gate import (
        ablation_cell_accounting,
        load_ablation_manifest,
        whole_stack_fusion_cell_target,
    )

    ci_db = tmp_path / "ed_console.db"
    ensure_console_db_training_schema(db_path=ci_db)
    monkeypatch.setattr("db.DB_PATH", str(ci_db))
    monkeypatch.setattr("tools.feature_curation_gate.DB_PATH", str(ci_db))

    def _ci_ablation_index(**kwargs):
        if kwargs.get("db_path") is None:
            kwargs = {**kwargs, "db_path": ci_db}
        return _get_ablation_index(**kwargs)

    monkeypatch.setattr(
        "tools.ablation_static_lock_index.get_ablation_static_lock_index",
        _ci_ablation_index,
    )
    reset_ablation_static_lock_index_for_tests()
    try:
        idx = _ci_ablation_index()
        assert idx.enriched == []
        assert idx.runnable_target == 0
        manifest = load_ablation_manifest()
        accounting = ablation_cell_accounting(manifest, idx.specs, enriched_rows=[])
        assert accounting["runnable_target"] == 0
        assert whole_stack_fusion_cell_target(manifest) == 0
        assert mod.check_ablation_seven_model_four_horizon_grid() == []
    finally:
        reset_ablation_static_lock_index_for_tests()


def test_ablation_fusion_runnable_target_divergence_fails_grid_check(monkeypatch) -> None:
    """Regression: objective-audit must fail when fusion and runnable denominators diverge."""
    monkeypatch.setattr(
        "tools.feature_curation_gate.whole_stack_fusion_cell_target",
        lambda manifest=None: 999_999,
    )
    errors = mod.check_ablation_seven_model_four_horizon_grid()
    assert any(
        "whole_stack_fusion_cell_target must equal runnable_target" in e for e in errors
    ), errors


def test_ablation_grid_requires_all_seven_models_and_four_horizons():
    """Catalog grid 7840 slots; Stage 3 specs score DB-wire groups only; runnable from row fidelity."""
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS, STAGE3_ABLATION_HORIZONS
    from tools.ablation_static_lock_index import (
        get_ablation_static_lock_index,
        reset_ablation_static_lock_index_for_tests,
    )
    from tools.feature_curation_gate import (
        ablation_cell_accounting,
        ablation_grid_groups,
        ablation_scoring_groups,
        whole_stack_catalog_cell_target,
        whole_stack_runnable_cell_target,
    )

    reset_ablation_static_lock_index_for_tests()
    assert mod.check_ablation_seven_model_four_horizon_grid() == []

    idx = get_ablation_static_lock_index()
    manifest = idx.manifest
    assert manifest is not None
    dbp = REPO_ROOT / "data" / "ed_console.db"
    dbp_str = str(dbp) if dbp.is_file() else None
    scoring = ablation_scoring_groups(manifest, db_path=dbp_str)
    specs = idx.specs
    enriched = idx.enriched
    specs_fidelity = specs
    from tools.ablation_static_lock_index import enriched_rows_for_spec_build

    accounting = ablation_cell_accounting(
        manifest, specs_fidelity, enriched_rows=enriched_rows_for_spec_build(enriched)
    )
    grid_groups = ablation_grid_groups(manifest)
    catalog_groups = len(grid_groups)
    manifest_in_cone = len(
        [g for g in grid_groups if g.get("ingest_status") == "in_cone"]
    )
    assert catalog_groups >= 280
    assert len(scoring) <= manifest_in_cone
    if dbp.is_file():
        from tools.build_feature_assignment_matrix_v2 import atomic_column_for_manifest_group
        from tools.feature_curation_gate import ablation_db_wire_ablatable_columns

        wire = ablation_db_wire_ablatable_columns(str(dbp))
        db_wire_in_cone = len(
            [
                g
                for g in grid_groups
                if g.get("ingest_status") == "in_cone"
                and atomic_column_for_manifest_group(g) in wire
            ]
        )
        assert len(scoring) == db_wire_in_cone
        assert manifest_in_cone >= len(scoring)
    assert len(specs) == len(scoring) * len(FULL_STACK_MODEL_LAYERS) * len(STAGE3_ABLATION_HORIZONS)
    assert whole_stack_catalog_cell_target(manifest) == catalog_groups * 7 * 4
    assert whole_stack_runnable_cell_target(manifest) == accounting["runnable_target"]
    assert accounting["catalog_target"] - accounting["runnable_target"] == accounting["catalog_only_target"]
    assert accounting["manifest_schwab_catalog"] == 186
    in_cone = accounting["manifest_in_cone"]
    if enriched:
        runnable_per_model = accounting["runnable_target"] // len(FULL_STACK_MODEL_LAYERS)
        for model in FULL_STACK_MODEL_LAYERS:
            assert accounting["runnable_by_model"].get(model) == runnable_per_model, model
        assert accounting["meta_runnable"] == runnable_per_model
        assert accounting["runnable_target"] <= in_cone * len(FULL_STACK_MODEL_LAYERS) * len(STAGE3_ABLATION_HORIZONS)
        assert accounting["runnable_target"] == in_cone * len(FULL_STACK_MODEL_LAYERS) * len(STAGE3_ABLATION_HORIZONS)
    ng = [s for s in specs_fidelity if s["group_id"] == "reg__atomic__net_gamma" and s["horizon_slug"] == "1c"]
    assert len(ng) == len(FULL_STACK_MODEL_LAYERS)
    if enriched:
        assert all(s.get("runnable") for s in ng)
    assert "anchor_ticker" not in specs[0]
    assert specs[0]["model_family"] in FULL_STACK_MODEL_LAYERS
    assert specs[0]["pool_tickers"] == ["SPY", "QQQ", "IWM"]
    assert set(s["horizon_slug"] for s in specs) == set(STAGE3_ABLATION_HORIZONS)
    assert set(s["model_family"] for s in specs) == set(FULL_STACK_MODEL_LAYERS)
    for model in FULL_STACK_MODEL_LAYERS:
        for hz in STAGE3_ABLATION_HORIZONS:
            model_hz_specs = [s for s in specs if s["model_family"] == model and s["horizon_slug"] == hz]
            assert len(model_hz_specs) == len(scoring), (model, hz, len(model_hz_specs))


def test_ablation_report_status_uses_runnable_denominator(tmp_path, monkeypatch):
    """Status/progress must not treat 7840 catalog slots as the scored denominator."""
    import json

    report = {
        "ablation_accounting": {
            "catalog_target": 7840,
            "runnable_target": 624,
        },
        "whole_stack_runnable_cell_target": 624,
        "whole_stack_catalog_cell_target": 7840,
        "whole_stack_feature_cells": [
            {"runnable": True, "status": "ok", "model_family": "xgb", "horizon_slug": "1c"},
            {"runnable": False, "status": "skipped", "grid_skip_reason": "not_wired"},
        ],
        "run_meta": {"status": "partial"},
        "survivor_summary": {"confirm_pass_cli": "whole_stack_drop_column_refit__run_with_--ablation-confirm"},
    }
    p = tmp_path / "feature_ablation_report_leaf.json"
    p.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        "tools.feature_curation_gate.ABLATION_REPORT_PATH",
        p,
    )
    from tools.feature_curation_gate import ablation_report_status

    st = ablation_report_status(p)
    assert st["whole_stack_runnable_cell_target"] == 624
    assert st["whole_stack_runnable_done"] == 1
    assert st["catalog_only_cells"] == 1
    assert st["complete"] is False


def test_ablation_equal_layer_consumers_fix1():
    """Fidelity-first: unified knockouts per feature across all seven layers (one cohesive stack)."""
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS, STACK_AUTHORITY_LAYERS
    from tools.ablation_static_lock_index import (
        get_ablation_static_lock_index,
        reset_ablation_static_lock_index_for_tests,
    )
    from tools.feature_curation_gate import ablation_scoring_groups

    reset_ablation_static_lock_index_for_tests()
    assert mod.check_ablation_equal_layer_consumers() == []

    idx = get_ablation_static_lock_index()
    manifest = idx.manifest
    assert manifest is not None
    specs = idx.specs
    enriched = idx.enriched
    upper = [s for s in specs if s["model_family"] in STACK_AUTHORITY_LAYERS]
    assert upper, "expected upper-layer placement cells"
    for s in upper:
        layers = s.get("stack_entry_layers") or []
        assert len(layers) <= 1
        if s.get("group_columns"):
            assert layers == [s["model_family"]]
    regime_cols = [
        s for s in specs
        if s["model_family"] == "regime"
        and s.get("group_columns")
    ]
    fusion_cols = [
        s for s in specs
        if s["model_family"] == "fusion"
        and s.get("group_columns")
    ]
    meta_cols = [
        s for s in specs
        if s["model_family"] == "meta"
        and s.get("group_columns")
    ]
    if enriched:
        assert regime_cols, "regime layer must resolve knockout columns for row-present features"
        assert fusion_cols, "fusion layer must resolve knockout columns for row-present features"
        assert meta_cols, "meta layer must resolve knockout columns for row-present features"
        assert len(meta_cols) == len(fusion_cols) == len(regime_cols)
        runnable_by_model = {
            m: sum(1 for s in specs if s.get("model_family") == m and s.get("runnable"))
            for m in FULL_STACK_MODEL_LAYERS
        }
        assert len(set(runnable_by_model.values())) == 1, runnable_by_model
        assert runnable_by_model["xgb"] <= len(ablation_scoring_groups(manifest)) * 4


def test_graphrag_fidelity_ablation_contract():
    """GraphRAG fidelity-first — no registry fallback knockouts on placement grid."""
    assert mod.check_graphrag_fidelity_ablation_contract() == []

def test_ablation_experiment_integrity_flags_noop_knockout():
    from tools.feature_curation_gate import build_ablation_experiment_integrity

    report = {
        "source_manifest": "governance/artifacts/feature_ablation_manifest_leaf.json",
        "ablation_accounting": {"runnable_target": 2, "runnable_by_model": {"xgb": 2}},
        "whole_stack_runnable_cell_target": 2,
        "run_meta": {"status": "partial"},
        "whole_stack_feature_cells": [
            {
                "runnable": True,
                "model_family": "xgb",
                "horizon_slug": "1c",
                "group_id": "snap__net_gamma",
                "status": "ok",
                "group_columns": ["net_gamma"],
                "stack_entry_layers": ["xgb"],
                "columns_permuted_count": 0,
                "columns_requested": ["net_gamma"],
                "log_loss_delta": 0.0,
            },
            {
                "runnable": True,
                "model_family": "xgb",
                "horizon_slug": "5c",
                "group_id": "snap__vix_level",
                "status": "skipped",
                "reason": "insufficient_paired_rows:3",
                "stack_entry_layers": ["xgb"],
            },
        ],
    }
    integrity = build_ablation_experiment_integrity(report)
    codes = {f["code"] for f in integrity.get("skew_flags") or []}
    assert integrity["verdict"] in ("FAIL", "INVESTIGATE")
    assert "NOOP_KNOCKOUT_SCORED_OK" in codes
    assert integrity.get("trace_cells")


def test_ablation_finalize_whole_stack_cell_fail_closed_on_noop():
    from tools.feature_curation_gate import _finalize_whole_stack_scored_cell

    cell = {
        "status": "ok",
        "columns_permuted_count": 0,
        "columns_requested": ["bid_ask_imbalance"],
        "log_loss_delta": 1.3e-05,
        "group_matters": True,
    }
    out = _finalize_whole_stack_scored_cell(cell)
    assert out["status"] == "skipped"
    assert out["reason"] == "noop_knockout:zero_columns_permuted"
    assert out["group_matters"] is False


def test_ablation_legacy_report_runnable_inference_and_target(tmp_path, monkeypatch):
    """Legacy checkpoints without runnable stamps still count for status/integrity."""
    import json

    from tools.ablation_static_lock_index import (
        get_ablation_static_lock_index,
        reset_ablation_static_lock_index_for_tests,
    )
    from tools.feature_curation_gate import (
        ablation_report_status,
        build_ablation_experiment_integrity,
        whole_stack_runnable_cell_target,
    )

    reset_ablation_static_lock_index_for_tests()
    idx = get_ablation_static_lock_index()
    assert idx.manifest is not None
    wire_runnable_target = whole_stack_runnable_cell_target(idx.manifest)
    assert wire_runnable_target == idx.runnable_target

    report = {
        "source_manifest": "governance/artifacts/feature_ablation_manifest_leaf.json",
        "whole_stack_feature_cells": [
            {
                "ablation_kind": "whole_stack_feature_group",
                "model_family": "xgb",
                "horizon_slug": "1c",
                "group_id": "reg__atomic__atr",
                "status": "ok",
                "columns_permuted_count": 1,
                "log_loss_delta": 0.0005,
            },
            {
                "ablation_kind": "whole_stack_feature_group",
                "model_family": "xgb",
                "horizon_slug": "1c",
                "group_id": "schwab__bid",
                "status": "skipped",
                "reason": "not_wired",
            },
        ],
        "run_meta": {"status": "partial"},
    }
    p = tmp_path / "feature_ablation_report_leaf.json"
    p.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr("tools.feature_curation_gate.ABLATION_REPORT_PATH", p)

    st = ablation_report_status(p)
    assert st["whole_stack_runnable_done"] == 1
    assert st["whole_stack_runnable_ok"] == 1
    assert st["whole_stack_runnable_cell_target"] == wire_runnable_target

    integrity = build_ablation_experiment_integrity(report)
    assert integrity["run_completion"]["runnable_target"] == wire_runnable_target
    assert integrity["run_completion"]["runnable_terminal"] == 1


def test_stop_hook_blocks_assumption_vocabulary():
    """AGENTS §No assumptions — verify, never assume. The Stop hook must FAIL the turn on asserted
    assume/assuming/assumption/presume/my-guess, and must NOT trip on the same words inside code
    fences / inline code / >-quotes (so the rule can still be written about)."""
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("ear_assume", repo / "tools" / "enforce_all_rules.py")
    ear = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ear)

    CODE = "```\ngate exit: 1\n```"

    def word_blocked(text):
        return any("no-assume-verify" in h and "ACTION" not in h for h in ear._scan_output(text))

    def action_blocked(text):
        return any("no-assume-verify" in h and "ACTION" in h for h in ear._scan_output(text))

    # LAYER 1 — the WORD: asserted assumption vocabulary MUST block (no [REAL-GATE] escape)
    assert word_blocked("I assume the gate passes.")
    assert word_blocked("Assuming the run is clean, we proceed.")
    assert word_blocked("The assumption is it ablates all seven.")
    assert word_blocked("Presumably the baseline is fine.")
    assert word_blocked("My guess is it works.")
    # the word may be discussed inside code fence / inline code / >-quote
    assert not word_blocked("```\nthe banned word is assume\n```")
    assert not word_blocked("the token is `assume`")
    assert not word_blocked("> we ban the word assume here")

    # LAYER 2 — the ACTION: a verdict asserted with NO shown evidence MUST block
    assert action_blocked("The fix is verified and the run passes.")
    assert action_blocked("The audit checks out and it is clean.")
    assert action_blocked("Verified: baseline 1.1982 on 11 scored cells.")  # bare claim, no evidence
    # a verdict WITH a shown command/Read block does NOT block (evidence present)
    assert not action_blocked("Verified below:\n" + CODE)
    # a verdict only inside a >-quote does NOT block (stripped before scan)
    assert not action_blocked("> you said it is verified")
    # non-claim prose with no verdict word does NOT block
    assert not action_blocked("You are right; I will trace the source next time.")


def test_unified_stack_team_contract_checker():
    assert mod.check_unified_stack_team_contract() == []


def test_live_ablation_experiment_wiring_checker():
    assert mod.check_live_ablation_experiment_wiring() == []


def test_unified_stack_docs_governance_vocabulary_checker():
    assert mod.check_unified_stack_docs_governance_vocabulary() == []


def test_unified_stack_canonical_vocabulary_checker():
    assert mod.check_unified_stack_canonical_vocabulary() == []


def test_unified_stack_producer_language_checker():
    assert mod.check_unified_stack_producer_language() == []


def test_prepush_does_not_include_full_static_hook():
    """Local pre-push must not run repo-wide --full-static (CI objective-audit owns it)."""
    cfg = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    idx = cfg.find("id: fix-everything-we-touch-full-static")
    if idx >= 0:
        rest = cfg[idx:]
        next_hook = rest.find("\n      - id:", len("id: fix-everything-we-touch-full-static"))
        block = rest if next_hook < 0 else rest[:next_hook]
        assert "pre-push" not in block
    assert mod.check_precommit_performance_contract() == []


def test_precommit_staged_fix_everything_we_touch_retained():
    cfg = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "id: fix-everything-we-touch" in cfg
    idx = cfg.find("id: fix-everything-we-touch\n")
    if idx < 0:
        idx = cfg.find("id: fix-everything-we-touch-msg")
    assert idx >= 0
    assert "id: fix-everything-we-touch-msg" in cfg


def test_prepush_fast_gate_and_generated_artifacts_retained():
    cfg = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    for hook_id in ("prepush-fast-gate", "generated-artifacts-clean-check"):
        assert f"id: {hook_id}" in cfg
        idx = cfg.find(f"id: {hook_id}")
        rest = cfg[idx:]
        next_hook = rest.find("\n      - id:", len(f"id: {hook_id}"))
        block = rest if next_hook < 0 else rest[:next_hook]
        assert "pre-push" in block


def test_objective_audit_ci_full_static_documented_in_prepush_policy():
    policy = (REPO_ROOT / "governance" / "docs" / "PREPUSH_FAST_FAIL_POLICY.md").read_text(
        encoding="utf-8"
    )
    assert "Local pre-push is a fast gate" in policy
    assert "objective-audit" in policy
    assert "not coverage removal" in policy.lower()
    wf = REPO_ROOT / ".github" / "workflows" / "objective-audit.yml"
    assert wf.is_file()
    assert "--objective-audit" in wf.read_text(encoding="utf-8")


# ── FULL_FIXES_ONLY_V1 (AGENTS § FULL_FIXES_ONLY_V1, 2026-07-09 operator binding) ──


_FULL_FIX_TEMPLATE_OK = (
    "FULL_FIX_PROVEN = YES\n"
    "ROOT_CAUSE_PROVEN = YES\n"
    "UNIVERSAL_SCOPE_PROVEN = YES\n"
    "MECHANICAL_LOCK_ADDED = YES\n"
    "PATCH_OR_WORKAROUND = NO\n"
)


def _full_fix_msg(tmp_path: Path, body: str) -> Path:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(body, encoding="utf-8")
    return msg


def test_full_fixes_closure_language_without_template_fails(tmp_path: Path) -> None:
    msg = _full_fix_msg(tmp_path, "EXEC-99: CLOSED — root cause repaired.\n")
    hits = mod.check_full_fixes_only(msg)
    assert hits and "FULL_FIX proof" in hits[0]


def test_full_fixes_closure_with_complete_template_passes(tmp_path: Path) -> None:
    msg = _full_fix_msg(tmp_path, "EXEC-99: CLOSED.\n\n" + _FULL_FIX_TEMPLATE_OK)
    assert mod.check_full_fixes_only(msg) == []


def test_full_fixes_patch_or_workaround_yes_is_nonclosure(tmp_path: Path) -> None:
    body = "Lane closed.\n\n" + _FULL_FIX_TEMPLATE_OK.replace(
        "PATCH_OR_WORKAROUND = NO", "PATCH_OR_WORKAROUND = YES"
    )
    hits = mod.check_full_fixes_only(_full_fix_msg(tmp_path, body))
    assert any("PATCH_OR_WORKAROUND must be NO" in h for h in hits)


def test_full_fixes_root_cause_no_is_nonclosure(tmp_path: Path) -> None:
    body = "Lane closed.\n\n" + _FULL_FIX_TEMPLATE_OK.replace(
        "ROOT_CAUSE_PROVEN = YES", "ROOT_CAUSE_PROVEN = NO"
    )
    hits = mod.check_full_fixes_only(_full_fix_msg(tmp_path, body))
    assert any("ROOT_CAUSE_PROVEN must be YES" in h for h in hits)


def test_full_fixes_universal_scope_no_requires_exception_marker(tmp_path: Path) -> None:
    bare = "Lane closed.\n\n" + _FULL_FIX_TEMPLATE_OK.replace(
        "UNIVERSAL_SCOPE_PROVEN = YES", "UNIVERSAL_SCOPE_PROVEN = NO"
    )
    hits = mod.check_full_fixes_only(_full_fix_msg(tmp_path, bare))
    assert any("UNIVERSAL_SCOPE_PROVEN" in h for h in hits)
    excepted = "Lane closed.\n\n" + _FULL_FIX_TEMPLATE_OK.replace(
        "UNIVERSAL_SCOPE_PROVEN = YES",
        "UNIVERSAL_SCOPE_PROVEN = NO FULL_FIX_EXCEPTION_APPROVED: operator 2026-07-09",
    )
    assert mod.check_full_fixes_only(_full_fix_msg(tmp_path, excepted)) == []


def test_full_fixes_mechanical_lock_no_requires_infeasible_reason(tmp_path: Path) -> None:
    bare = "Lane closed.\n\n" + _FULL_FIX_TEMPLATE_OK.replace(
        "MECHANICAL_LOCK_ADDED = YES", "MECHANICAL_LOCK_ADDED = NO"
    )
    hits = mod.check_full_fixes_only(_full_fix_msg(tmp_path, bare))
    assert any("MECHANICAL_LOCK_ADDED" in h for h in hits)
    reasoned = "Lane closed.\n\n" + _FULL_FIX_TEMPLATE_OK.replace(
        "MECHANICAL_LOCK_ADDED = YES",
        "MECHANICAL_LOCK_ADDED = NO (infeasible: pure runtime observation, no code surface)",
    )
    assert mod.check_full_fixes_only(_full_fix_msg(tmp_path, reasoned)) == []


def test_full_fixes_workaround_framing_fails_and_exception_marker_exempts(tmp_path: Path) -> None:
    hits = mod.check_full_fixes_only(
        _full_fix_msg(tmp_path, "Ship a quick fix for the stale cards.\n")
    )
    assert any("banned framing" in h for h in hits)
    assert mod.check_full_fixes_only(
        _full_fix_msg(
            tmp_path,
            "Ship a quick fix for the stale cards. FULL_FIX_EXCEPTION_APPROVED: operator 2026-07-09\n",
        )
    ) == []


def test_full_fixes_prose_lowercase_closed_is_not_closure_language(tmp_path: Path) -> None:
    assert mod.check_full_fixes_only(
        _full_fix_msg(tmp_path, "Refactor: closed the file handle before returning.\n")
    ) == []


def test_full_fixes_wired_into_commit_message_check(tmp_path: Path) -> None:
    msg = _full_fix_msg(tmp_path, "EXEC-99: CLOSED — see board.\n")
    hits = mod.check_commit_message(msg)
    assert any("FULL_FIX" in h for h in hits)


def test_full_fixes_agents_section_and_checklist_row_present() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "## FULL_FIXES_ONLY_V1" in agents
    for field in mod.FULL_FIX_TEMPLATE_FIELDS:
        assert field in agents
    checklist = (REPO_ROOT / "governance" / "docs" / "INSTITUTIONAL_MASTER_CHECKLIST.md").read_text(
        encoding="utf-8"
    )
    assert "FULL_FIXES_ONLY_V1" in checklist
    open_items = (REPO_ROOT / "OPEN_ITEMS.md").read_text(encoding="utf-8")
    assert "FULL_FIXES_ONLY_V1" in open_items
    assert "IDLE_SENTINEL_FRESHNESS_V1" in open_items
