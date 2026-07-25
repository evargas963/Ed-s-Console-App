"""Worktree-scoped console DB routing (Cursor vs Claude isolation)."""
import db_authority as auth


def test_claude_role_routes_to_dedicated_db(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "project_root", lambda: tmp_path / "EdWebConsole-Claude")
    (tmp_path / "EdWebConsole-Claude" / "data").mkdir(parents=True)
    monkeypatch.setenv("ED_AGENT_ROLE", "claude")
    p = auth.default_console_db_path()
    assert p.name == "ed_console_claude.db"
    assert p.parent.name == "data"


def test_cursor_role_keeps_canonical_name(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "project_root", lambda: tmp_path / "EdWebConsole")
    (tmp_path / "EdWebConsole" / "data").mkdir(parents=True)
    monkeypatch.setenv("ED_AGENT_ROLE", "cursor")
    p = auth.default_console_db_path()
    assert p.name == "ed_console.db"


def test_agent_db_env_override_allowed_without_noncanonical_flag(monkeypatch, tmp_path):
    root = tmp_path / "EdWebConsole-Claude"
    data = root / "data"
    data.mkdir(parents=True)
    db = data / "ed_console_claude.db"
    db.write_bytes(b"")
    monkeypatch.setattr(auth, "project_root", lambda: root)
    monkeypatch.delenv("ED_CONSOLE_ALLOW_NONCANONICAL_DB", raising=False)
    auth.assert_ed_console_db_env_resolves_safely(db.resolve())
