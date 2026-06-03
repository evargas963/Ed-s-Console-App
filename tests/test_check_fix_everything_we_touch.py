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


def test_persistence_map_fresh_missing_map_fails_when_persistence_source_staged() -> None:
    """Staging db.py without re-staging the persistence_consumer_map.json must fail
    Pass 2b — operator forgot to regenerate the map after editing the writer."""
    staged = {"db.py"}  # map NOT staged
    hits = mod.check_persistence_map_fresh(staged)
    assert hits, "expected Pass 2b hit when persistence source staged without map"
    assert any("persistence_consumer_map.json" in h for h in hits)
    assert any("Pass 2b" in h for h in hits)


def test_persistence_map_fresh_missing_map_fails_when_tool_staged() -> None:
    """Editing the audit tool itself also requires re-staging the map (the tool's
    output shape may have changed)."""
    staged = {"tools/audit_persistence_consumers.py"}  # map NOT staged
    hits = mod.check_persistence_map_fresh(staged)
    assert hits, "expected Pass 2b hit when audit tool staged without map"
    assert any("persistence_consumer_map.json" in h for h in hits)


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


def test_meet_or_exceed_cycle_documentation_passes_on_current_repo() -> None:
    assert mod.check_meet_or_exceed_cycle_documentation() == []


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
        "VERDICT: MET\nCYCLE_ITERATIONS: 2\nGATE_TABLE:\n  tests: MET — tests/test_batch2\n",
        encoding="utf-8",
    )
    assert mod.check_meet_or_exceed_signoff(msg) == []


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
