"""RUNTIME LAYOUT — the ONE owner of where runtime state lives (docs/ARCHITECTURE.md §8).

Source, runtime state and generated artifacts are separate concerns:

    SOURCE      this checkout (code, tests, records)
    RUNTIME     the live database, logs, tokens            ED_RUNTIME_ROOT
    ARTIFACTS   generated reports and scorecards           ED_ARTIFACTS_ROOT (default: RUNTIME)

RC-523 (2026-09-06, bedrock step 7). Every runtime path was rooted in the source checkout
(`Path(__file__).parent / "data"`, `/ "logs"`, `/ "reports"`) with an override for the
database alone, so a source update could endanger the live database and runtime output
polluted the checkout — the two things §8 forbids — and the production checkout had to be
the desk's cwd. RC-534 closes the remaining worktree split: a linked Git worktree resolves
runtime state to its primary worktree by reading Git's own ``.git`` / ``commondir`` metadata.
A standalone checkout still owns its own runtime root. ``ED_RUNTIME_ROOT`` may move runtime
state to a dedicated non-checkout directory, but may not select a linked source worktree.

This module imports nothing from `tools/` or `governance/`: it is on the runtime path and
governance does not decide whether the desk may run (RC-512). It reads `.env` at the source
root the same way `config.py` does, so the variables can live beside the other host settings.
"""
from __future__ import annotations

import os
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
    try:
        marker = dotgit.read_text(encoding="utf-8").strip()
        if not marker.lower().startswith("gitdir:"):
            raise ValueError(f"invalid linked-worktree marker: {dotgit}")
        gitdir = Path(marker.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = (SOURCE_ROOT / gitdir).resolve()
        commondir_file = gitdir / "commondir"
        if not commondir_file.is_file():
            raise ValueError(f"linked-worktree commondir missing: {commondir_file}")
        common_git = (gitdir / commondir_file.read_text(encoding="utf-8").strip()).resolve()
        if common_git.name != ".git":
            raise ValueError(f"linked-worktree commondir is not a .git directory: {common_git}")
        primary = common_git.parent.resolve()
        if not primary.is_dir():
            raise ValueError(f"linked-worktree primary root missing: {primary}")
        return primary
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"cannot resolve canonical runtime root from linked worktree {SOURCE_ROOT}: {exc}"
        ) from exc


#: Live database, logs and tokens live here. Linked worktrees share the primary root.
RUNTIME_ROOT: Path = _dir_from_env("ED_RUNTIME_ROOT", _default_runtime_root())
#: Generated reports and scorecards live under here. Default: the runtime root.
ARTIFACTS_ROOT: Path = _dir_from_env("ED_ARTIFACTS_ROOT", RUNTIME_ROOT)


def data_dir() -> Path:
    """`<runtime>/data` — the live SQLite database and its siblings."""
    return RUNTIME_ROOT / "data"


def logs_dir() -> Path:
    """`<runtime>/logs` — the server log sink and other process logs."""
    return RUNTIME_ROOT / "logs"


def reports_dir() -> Path:
    """`<artifacts>/reports` — runtime-written reports (terrain, operable surface, scoreboards)."""
    return ARTIFACTS_ROOT / "reports"


def live_binding_error(source_root: "Path | None" = None,
                       runtime_root: "Path | None" = None) -> "str | None":
    """Why THIS checkout may not run a LIVE process (the console server, the capture daemon)
    against the runtime root -- or None when it may.

    MEASURED 2026-09-23 (found 2026-09-25): a console started from the EdWebConsole-phase1
    worktree (unmerged commit ce375cae) resolved its runtime to the primary checkout -- the
    linked-worktree convergence above, RC-534 -- and ran for hours against PRODUCTION: the
    production ed_console.db, token and logs/ed_server.log, into which it wrote 15,451
    "Schwab capability UNAVAILABLE" errors (the worktree had no .env). Convergence exists so
    a worktree can never become a SECOND production data root; it must not let unmerged code
    RUN as the first one.

    Allowed: the runtime root IS this checkout (production running itself), or the runtime
    root is a dedicated directory that is not a git checkout (an explicit ED_RUNTIME_ROOT
    sandbox, the test and e2e runtime roots). Refused: the runtime root is ANOTHER checkout.
    Reading tools and tests are unaffected -- only live processes call this."""
    src = (source_root or SOURCE_ROOT).resolve()
    rt = (runtime_root or RUNTIME_ROOT).resolve()
    if rt == src:
        return None
    if (rt / ".git").exists():
        return (f"this checkout ({src}) resolves its runtime to another checkout ({rt}) -- the "
                f"live database, token and logs of that checkout. A live console or capture "
                f"daemon runs only from the checkout that owns its runtime; to run this one, "
                f"set ED_RUNTIME_ROOT to a separate sandbox directory (not a git checkout).")
    return None


