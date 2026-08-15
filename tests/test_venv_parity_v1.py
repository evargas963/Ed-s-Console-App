"""Seams for virtualenv parity gate."""
from tools.check_venv_parity import venv_parity_violations


def test_ci_exempt(monkeypatch):
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("ED_CONSOLE_ALLOW_SYSTEM_PYTHON", raising=False)
    assert venv_parity_violations(executable=r"C:\Python313\python.exe") == []


def test_global_python_fails_when_not_ci(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("ED_CONSOLE_ALLOW_SYSTEM_PYTHON", raising=False)
    # Point REPO's .venv check at a temp tree via monkeypatch of module REPO
    import tools.check_venv_parity as mod
    monkeypatch.setattr(mod, "REPO", tmp_path)
    (tmp_path / ".venv").mkdir()
    fake_global = tmp_path / "global" / "python.exe"
    fake_global.parent.mkdir(parents=True)
    fake_global.write_text("", encoding="utf-8")
    v = venv_parity_violations(executable=str(fake_global))
    assert v and "outside .venv" in v[0]
