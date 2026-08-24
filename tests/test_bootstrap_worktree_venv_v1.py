"""Seam: bootstrap creates a worktree-local .venv (venv-only, no pip)."""
from tools.bootstrap_worktree_venv import ensure_venv, venv_python


def test_ensure_venv_creates_interpreter(tmp_path):
    # with_pip=False: this asserts interpreter creation; ensurepip alone measured ~27s
    # and installs nothing this test reads. install_requirements=True paths keep pip.
    py = ensure_venv(tmp_path, install_requirements=False, with_pip=False)
    assert py == venv_python(tmp_path)
    assert py.is_file()
