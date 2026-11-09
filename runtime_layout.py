"""Where runtime state lives (docs/ARCHITECTURE.md "Runtime state is not source").

Source and runtime state are separate concerns:

    SOURCE      this checkout (code, tests, records)
    RUNTIME     the live database, logs, tokens            ED_RUNTIME_ROOT

Runtime state lives in the runtime root's ``data/`` and ``logs/`` (data_dir, logs_dir) and its
``schwab_token.json`` (config.token_path), each ignored by git, so a source update never touches
it (docs/ARCHITECTURE.md §5), whatever the process's working directory. A standalone checkout is
its own runtime root, so production's database, logs and token sit in its checkout. A linked Git
worktree resolves runtime state to its primary worktree by reading Git's own ``.git`` /
``commondir`` metadata.
``ED_RUNTIME_ROOT`` may move runtime state to a dedicated non-checkout directory, but may not
select a linked source worktree.

This module imports nothing from `tools/` or `governance/`: it is on the runtime path and
governance does not decide whether the desk may run. It reads the environment when asked
(runtime_root), never at import: an `ED_RUNTIME_ROOT` in `.env` reaches it once an entry point
has loaded `.env` (config.load_dotenv_file), whatever was imported first.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent


def _dir_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    resolved = Path(raw).expanduser().resolve()
    if name == "ED_RUNTIME_ROOT" and any(
        (candidate / ".git").is_file() for candidate in (resolved, *resolved.parents)
    ):
        raise ValueError(
            f"{name} cannot select a linked source worktree or any path inside it "
            f"as production runtime: {resolved}"
        )
    return resolved


def _default_runtime_root() -> Path:
    """Return Git's primary worktree, or this standalone checkout.

    Linked worktrees store a text ``.git`` file pointing into
    ``<primary>/.git/worktrees/<name>``. Git's adjacent ``commondir`` file points back to
    the primary ``.git`` directory. Reading those native files avoids a second path
    registry and makes every linked checkout converge on the same runtime identity.
    """
    dotgit = SOURCE_ROOT / ".git"
    if not dotgit.is_file():
        return SOURCE_ROOT
    why = f"cannot resolve canonical runtime root from linked worktree {SOURCE_ROOT}"
    marker = dotgit.read_text(encoding="utf-8").strip()  # an OSError names the file itself
    if not marker.lower().startswith("gitdir:"):
        raise RuntimeError(f"{why}: invalid linked-worktree marker: {dotgit}")
    gitdir = Path(marker.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (SOURCE_ROOT / gitdir).resolve()
    commondir_file = gitdir / "commondir"
    if not commondir_file.is_file():
        raise RuntimeError(f"{why}: linked-worktree commondir missing: {commondir_file}")
    common_git = (gitdir / commondir_file.read_text(encoding="utf-8").strip()).resolve()
    if common_git.name != ".git":
        raise RuntimeError(
            f"{why}: linked-worktree commondir is not a .git directory: {common_git}"
        )
    primary = common_git.parent.resolve()
    if not primary.is_dir():
        raise RuntimeError(f"{why}: linked-worktree primary root missing: {primary}")
    return primary


def runtime_root() -> Path:
    """Return where the live database, logs and token live, as the environment says now.

    Linked worktrees share the primary root. Read on each call, so an entry point that loads
    `.env` and a test that sets ED_RUNTIME_ROOT need not do it before this module is imported.
    """
    return _dir_from_env("ED_RUNTIME_ROOT", _default_runtime_root())


def data_dir() -> Path:
    """`<runtime>/data` — the live SQLite database and its siblings."""
    return runtime_root() / "data"


def logs_dir() -> Path:
    """`<runtime>/logs` — the server log sink and other process logs."""
    return runtime_root() / "logs"


def daemon_log_path(folder: Path, day: date) -> Path:
    """The capture daemon's log file for `day` (local date) in `folder`."""
    return folder / f"stream_capture.{day:%Y-%m-%d}.log"


def live_binding_error(source: Path | None = None, runtime: Path | None = None) -> str | None:
    """Why THIS checkout may not run a LIVE process (the console server, the capture daemon)
    against the runtime root -- or None when it may.

    A linked worktree resolves its runtime to the primary checkout (above), so a worktree can
    never become a second production data root; that must not let unmerged code run as the
    first one, against production's database, token and logs.

    Allowed: the runtime root IS this checkout (production running itself), or the runtime
    root is a dedicated directory that is not a git checkout (an explicit ED_RUNTIME_ROOT
    sandbox, the test and e2e runtime roots). Refused: the runtime root is ANOTHER checkout.
    Reading tools and tests are unaffected -- only live processes call this.
    """
    src = (source or SOURCE_ROOT).resolve()
    rt = (runtime or runtime_root()).resolve()
    if rt == src:
        return None
    if (rt / ".git").exists():
        return (
            f"this checkout ({src}) resolves its runtime to another checkout ({rt}) -- the "
            f"live database, token and logs of that checkout. A live console or capture "
            f"daemon runs only from the checkout that owns its runtime; to run this one, "
            f"set ED_RUNTIME_ROOT to a separate sandbox directory (not a git checkout)."
        )
    return None
