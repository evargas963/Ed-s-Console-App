"""ONE APP, ONE MAIN, ONE DB — no ambient state may move the default off canonical.

RC-401. This suite used to assert the opposite: that ED_AGENT_ROLE=claude routed to a
dedicated ``data/ed_console_claude.db``. That fork put real money-path rows (503
snapshots, 954 decision_persistence_ledger, 49,173 confluence_quote_ticks) into a 35.78 MB
sibling of the 34.28 GB canonical database, and produced a default path that
``EdDB.__init__`` then refused as non-canonical. The tests are inverted rather than
deleted, because the property worth locking is the one whose absence caused the defect.
"""
import db_authority as auth


def test_claude_role_does_not_fork_the_database(monkeypatch, tmp_path):
    """The env var a child process inherits must not choose the money path's data source."""
    monkeypatch.setattr(auth, "project_root", lambda: tmp_path / "EdWebConsole")
    (tmp_path / "EdWebConsole" / "data").mkdir(parents=True)
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    assert auth.default_console_db_path() == auth.canonical_console_db_path()
    assert auth.default_console_db_path().name == "ed_console.db"


def test_a_claude_suffixed_directory_does_not_fork_the_database(monkeypatch, tmp_path):
    """Nor may the directory a worktree happens to be checked out into."""
    monkeypatch.setattr(auth, "project_root", lambda: tmp_path / "EdWebConsole-Claude")
    (tmp_path / "EdWebConsole-Claude" / "data").mkdir(parents=True)
    monkeypatch.delenv("ED_AGENT_ROLE", raising=False)
    assert auth.default_console_db_path().name == "ed_console.db"


def test_cursor_role_keeps_canonical_name(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "project_root", lambda: tmp_path / "EdWebConsole")
    (tmp_path / "EdWebConsole" / "data").mkdir(parents=True)
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    assert auth.default_console_db_path().name == "ed_console.db"


def test_every_role_resolves_to_the_same_file(monkeypatch, tmp_path):
    """The fork's real cost was divergence, so assert agreement directly."""
    monkeypatch.setattr(auth, "project_root", lambda: tmp_path / "EdWebConsole")
    (tmp_path / "EdWebConsole" / "data").mkdir(parents=True)
    seen = set()
    for role in ("claude", "cursor", "CLAUDE", "", "someone-else"):
        monkeypatch.setenv("ED_AGENT_ROLE", role)
        seen.add(auth.default_console_db_path())
    assert len(seen) == 1, f"the default DB forked across roles: {seen}"


def test_exactly_two_permanent_database_identities(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    import runtime_layout

    monkeypatch.setattr(runtime_layout, "RUNTIME_ROOT", runtime)
    assert auth.canonical_permanent_db_paths() == (
        (runtime / "data" / "ed_console.db").resolve(),
        (runtime / "data" / "stream_capture.db").resolve(),
    )
    assert auth.permanent_database_identity(runtime / "data" / "ed_console.db") == "ed_console"
    assert auth.permanent_database_identity(runtime / "data" / "stream_capture.db") == "stream_capture"
    assert auth.permanent_database_identity(runtime / "data" / "ed_console_claude.db") is None
    assert auth.classify_db_path(runtime / "data" / "ed_console.db") == "canonical"
    assert auth.classify_db_path(runtime / "data" / "stream_capture.db") == "canonical"
