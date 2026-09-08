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


def test_a_sibling_console_db_is_no_longer_silently_exempt(monkeypatch, tmp_path):
    """An explicit override to a sibling file must be acknowledged, not waved through.

    This is the inversion of the old
    ``test_agent_db_env_override_allowed_without_noncanonical_flag``: that exemption is
    how a second database could be selected with the operator never being asked.
    """
    root = tmp_path / "EdWebConsole"
    data = root / "data"
    data.mkdir(parents=True)
    sibling = data / "ed_console_claude.db"
    sibling.write_bytes(b"")
    monkeypatch.setattr(auth, "project_root", lambda: root)
    monkeypatch.delenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB", raising=False)
    try:
        auth.assert_ed_console_db_env_resolves_safely(sibling.resolve())
    except ValueError as exc:
        assert "ED_CONSOLE_ALLOW_NONCANONICAL_DB" in str(exc)
    else:
        raise AssertionError("a sibling ed_console*.db was accepted without acknowledgement")


def test_an_acknowledged_override_still_works(monkeypatch, tmp_path):
    """Recovery and alternate-volume deployments are not collateral damage of the fix."""
    root = tmp_path / "EdWebConsole"
    data = root / "data"
    data.mkdir(parents=True)
    alt = data / "ed_console_claude.db"
    alt.write_bytes(b"")
    monkeypatch.setattr(auth, "project_root", lambda: root)
    monkeypatch.setenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB", "1")
    auth.assert_ed_console_db_env_resolves_safely(alt.resolve())
