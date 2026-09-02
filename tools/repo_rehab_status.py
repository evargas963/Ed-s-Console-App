"""REPO REHABILITATION — CURRENT / TARGET / DELTA, generated from facts, plus the ratchet.

WHY ONE FILE. The mission asks for a status generator AND a no-regression ratchet. They are the
same computation asked twice: the ratchet is "measure CURRENT at two refs and refuse the ones
that got worse". Splitting them would create two producers of "what does this repo look like",
which is the duplicate-authority defect the rehabilitation exists to remove. No new registry, no
new governance surface, no report archive: the daily job prints to the job summary.

WHAT IS MEASURED. Structural facts only, read from a git tree — module placement, tracked
runtime artifacts, directory ownership, import direction. Institutional debt is NOT recomputed
here: `tools/check_delta_adds_no_debt.py` already owns that question and already runs in
Hardening, so this defers to it rather than growing a second opinion.

USAGE
    python tools/repo_rehab_status.py                      # CURRENT / TARGET / DELTA
    python tools/repo_rehab_status.py --ratchet --base origin/main   # no-regression gate
    python tools/repo_rehab_status.py --host               # host separation (local only)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: The rehabilitation's fixed origin. Re-anchored to the merge of PR #218 when this work was
#: rebased onto it, so cumulative progress is measured from the tree the plan actually starts on.
START_SHA = "e3a7071419dff0ce08b3cc235925eeb7a0c13278"

# ── THE TARGET — FIXED AND HASH-PINNED ────────────────────────────────────────────────────
#: Pinned so the score cannot be improved by redefining what "done" means. Two protections, and
#: the second exists because the first is not enough: `tests/test_repo_rehab_ratchet_v1.py`
#: asserts the digest, AND the ratchet re-derives the BASE ref's TARGET and refuses any change —
#: a delta that edited the target, the pin and the test together would satisfy every test it
#: shipped with and still be moving its own goalposts.
#:
#: OPERATOR RULING 2026-09-02: `app/models` is KEPT (the earlier recommendation to rename it
#: `app/ml` is rejected); `docs/` is added to source. Every other legacy top-level directory is
#: dispositioned below — none is left unexplained, because "unexplained difference = NONE" is
#: the goal and a directory with no stated destination can never reach it.
TARGET: dict = {
    "app_packages": [
        "api", "domain", "market_data", "options", "signals", "models", "decision",
        "infrastructure",
    ],
    "source_top_level": [
        "app", "research", "tests", "tools", "static", "config", "governance", "docs",
    ],
    "root_production_modules": 0,
    "tracked_runtime_artifacts": 0,
    #: Where each legacy top-level directory GOES. "<host>" means it leaves source entirely.
    "legacy_disposition": {
        "reports": "<host>/artifacts",
        "models": "<host>/artifacts",
        "backups": "<host>/recovery",
        "data": "<host>/runtime",
        "calibration": "app/models",
        "features": "app/signals",
        "arch_competition": "research",
        "v2_decision": "app/decision",
        "verification": "tools",
        "planes": "app/domain",
        "schwab_field_inventory": "app/market_data",
        "snapshot_sql": "app/infrastructure",
        "scripts": "tools",
    },
    #: Dot-prefixed top-level directories that are legitimately part of the repository. Without
    #: this the top-level scan skipped every dotted name, so `.internal/` was a blind spot.
    "allowed_dot_top_level": [".github", ".claude", ".cursor", ".vscode"],
    #: Ed Console-specific host paths, relative to the directory ABOVE the source checkout.
    "host_paths": [
        "runtime/EdWebConsole", "recovery/EdWebConsole", "artifacts/EdWebConsole", "worktrees",
    ],
    "dependency_direction": {
        "domain": [],
        "market_data": ["domain"],
        "options": ["domain", "market_data"],
        "signals": ["domain", "market_data", "options"],
        "models": ["domain", "market_data", "options", "signals"],
        "decision": ["domain", "market_data", "options", "signals", "models"],
        "api": ["domain", "market_data", "options", "signals", "models", "decision",
                "infrastructure"],
        "infrastructure": ["domain"],
    },
}


def _digest(target: dict) -> str:
    return hashlib.sha256(
        json.dumps(target, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


TARGET_SHA256 = _digest(TARGET)

#: Extensions that are runtime/generated state, never source. A NAME LIST IS NOT AUTHORITY —
#: `.safetensors`, `.npz`, `.arrow` and whatever ships next are all missing from it by
#: construction, which is the same failure mode as deciding enforcement by vocabulary. It is a
#: fast path; `is_generated_state` below is the structural answer.
RUNTIME_EXT = frozenset({".db", ".sqlite", ".sqlite3", ".log", ".pkl", ".joblib", ".h5",
                         ".pt", ".onnx", ".parquet", ".bin", ".ckpt", ".npz", ".npy",
                         ".safetensors", ".arrow", ".feather", ".pb", ".tflite"})

#: Extensions that are unambiguously source/config text, whatever their size.
SOURCE_EXT = frozenset({".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".sql", ".md",
                        ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".txt",
                        ".csv", ".bat", ".ps1", ".sh", ".mdc", ".gitignore", ".example"})

#: A tracked file above this size that is not known source is generated state whatever it is
#: called. Chosen against the tree: the largest tracked source file on main is far below it.
LARGE_UNKNOWN_BYTES = 1_000_000

#: Directories that are tool caches, not repository content, for the on-disk scan.
_SCAN_SKIP = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
                        ".pytest_cache", ".ruff_cache", ".idea", "htmlcov"})


def is_generated_state(path: str, size: int | None = None, sample: bytes | None = None) -> bool:
    """Is this file runtime/generated state rather than source?

    Three tests, in order of confidence, because no single one is complete:
      1. a known runtime extension        — fast, incomplete by construction
      2. BINARY content (a NUL byte)      — structural; source text has none
      3. large AND not a known source ext — catches a generated text dump

    The suffix list alone was the whole authority before; a name list can always be stepped
    around by choosing another name, which is the defect class this repository keeps removing.
    """
    # EVERY suffix in the chain, not just the last: `model.pt.bak` and `db.sqlite.old` are the
    # artifact with a word appended, and reading only the final suffix misses both.
    suffixes = {s.lower() for s in Path(path).suffixes}
    ext = os.path.splitext(path)[1].lower()
    if suffixes & RUNTIME_EXT:
        return True
    if sample is not None and b"\x00" in sample:
        return True
    if size is not None and size > LARGE_UNKNOWN_BYTES and ext not in SOURCE_EXT:
        return True
    return False


def _legacy_dirs() -> frozenset[str]:
    return frozenset(TARGET["legacy_disposition"])


def _allowed_top_level() -> frozenset[str]:
    """Directories a tree may contain: TARGET source, plus legacy ones still being drained."""
    return frozenset(TARGET["source_top_level"]) | _legacy_dirs()


# ── facts ─────────────────────────────────────────────────────────────────────────────────
def _git(args: list[str], repo: Path = REPO) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def tracked_files(ref: str, repo: Path = REPO) -> list[str]:
    out = _git(["ls-tree", "-r", "--name-only", ref], repo)
    return out.splitlines() if out else []


def _blob_lines(ref: str, path: str, repo: Path = REPO) -> int:
    out = _git(["show", f"{ref}:{path}"], repo)
    return len(out.splitlines()) if out else 0


def top_level_dirs(files: list[str]) -> set[str]:
    """Every top-level directory, DOT-PREFIXED ONES INCLUDED.

    The earlier form skipped anything beginning with '.', so `.internal/` was a place production
    code could live that no rule inspected. Dotted names are now declared in the TARGET like any
    other, so the population is closed rather than assumed.
    """
    return {f.split("/")[0] for f in files if "/" in f}


def _blob_sizes(ref: str, repo: Path = REPO) -> dict[str, int]:
    """path -> byte size for every tracked blob at `ref`, in one git call."""
    out = _git(["ls-tree", "-r", "-l", ref], repo)
    sizes: dict[str, int] = {}
    for line in (out or "").splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5 and parts[1] == "blob":
            try:
                sizes[parts[4].strip()] = int(parts[3])
            except ValueError:
                continue
    return sizes


def tracked_gitlinks(ref: str, repo: Path = REPO) -> list[str]:
    """Submodule gitlinks at `ref`.

    A submodule is the perfect hiding place and was invisible to every predicate: `git ls-tree`
    reports the gitlink as a bare name with NO slash and type `commit`, so it entered neither
    `top_level_dirs` (needs a '/'), nor the root-module scan (needs `.py`), nor
    `tracked_generated_state` (needs a blob). PROVEN in review: a submodule holding 1500 LOC and
    a 2 MB database passed the ratchet, and moving 40 root modules into it read as IMPROVED.
    """
    out = _git(["ls-tree", "-r", "-t", ref], repo)
    links = []
    for line in (out or "").splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[1] == "commit":
            links.append(parts[3].strip())
    return sorted(links)


def tracked_generated_state(ref: str, repo: Path = REPO) -> list[str]:
    """Tracked files that are generated state — by extension, size, or binary content."""
    sizes = _blob_sizes(ref, repo)
    out = []
    for f, n in sizes.items():
        if is_generated_state(f, n):
            out.append(f)
    return sorted(out)


def physical_generated_state(root: Path | None = None) -> list[str]:
    """Generated state ON DISK inside the source checkout — IGNORED FILES INCLUDED.

    This is the measurement that matters and the one that was missing. The tracked count can be
    driven to zero without moving a byte: `.gitignore` on this repository ALREADY carries
    `models/**`, `data/*`, `backups/db/*` and `logs/`, so new contamination is invisible to any
    tracked-file rule, and `git rm --cached` would have reported a 224 -> 0 improvement while
    every file stayed exactly where it was.
    """
    base = (root or REPO).resolve()
    found: list[str] = []
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in _SCAN_SKIP]
        for name in fn:
            p = Path(dp) / name
            try:
                size = p.stat().st_size
            except OSError:
                continue
            sample = None
            if os.path.splitext(name)[1].lower() not in RUNTIME_EXT:
                try:
                    with p.open("rb") as fh:
                        sample = fh.read(4096)
                except OSError:
                    sample = None
            if is_generated_state(name, size, sample):
                try:
                    found.append(p.relative_to(base).as_posix())
                except ValueError:
                    continue
    return sorted(found)


def current(ref: str = "HEAD", repo: Path = REPO, with_loc: bool = True) -> dict:
    """CURRENT, generated from the tree at `ref`. No hand-entered status anywhere."""
    files = tracked_files(ref, repo)
    root_py = sorted(f for f in files if "/" not in f and f.endswith(".py"))
    app_py = sorted(f for f in files if f.startswith("app/") and f.endswith(".py"))
    runtime = tracked_generated_state(ref, repo)
    tops = top_level_dirs(files)
    legacy_present = sorted(tops & _legacy_dirs())
    legacy_files = sorted(f for f in files if f.split("/")[0] in _legacy_dirs() and "/" in f)
    unknown = sorted(tops - _allowed_top_level() - set(TARGET["allowed_dot_top_level"]))
    # Anything under app/ that is not inside a DECLARED package: a file directly at app/x.py,
    # or app/<undeclared>/... . Both used to fall between the root rule and the package rule.
    undeclared_app = sorted(
        f for f in files if f.startswith("app/")
        and (f.count("/") == 1 or f.split("/")[1] not in TARGET["app_packages"]))
    gov = sorted(f for f in files if f.startswith("governance/"))
    return {
        "ref": (_git(["rev-parse", "--short", ref], repo) or ref).strip(),
        "tracked_files": len(files),
        "root_production_modules": len(root_py),
        "root_production_loc": sum(_blob_lines(ref, f, repo) for f in root_py) if with_loc else -1,
        "server_py_loc": _blob_lines(ref, "server.py", repo) if with_loc else -1,
        "app_modules": len(app_py),
        "app_loc": sum(_blob_lines(ref, f, repo) for f in app_py) if with_loc else -1,
        "app_packages_present": sorted({f.split("/")[1] for f in app_py if f.count("/") >= 2}),
        "tools_py": len([f for f in files if f.startswith("tools/") and f.endswith(".py")]),
        "governance_files": len(gov),
        "tracked_runtime_artifacts": len(runtime),
        "legacy_dirs_present": legacy_present,
        "legacy_tracked_files": len(legacy_files),
        "unknown_top_level_dirs": unknown,
        "undeclared_app_paths": undeclared_app,
        "app_imports_legacy": len(app_files_importing_legacy(ref, repo)),
        "_root_py_names": root_py,
        "_app_py_names": app_py,
        "_runtime_names": runtime,
        "_top_level": sorted(tops),
    }


# ── host separation ───────────────────────────────────────────────────────────────────────
def _in_ci() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


def host_separation(root: Path | None = None, baseline: str | None = None,
                    ref: str = "HEAD", force_local: bool = False) -> dict:
    """Is Ed Console's runtime/recovery/artifacts/worktree state OUTSIDE the source checkout?

    NOT_PROVEN_FROM_CI is the honest answer in CI. A CI runner clones the repository into an
    ephemeral path with no host layout around it, so any SEPARATED/VIOLATED verdict there would
    describe the runner, not the operator's machine — a measurement of the wrong subject read as
    a measurement of the right one.

    Locally the check is Ed Console-SPECIFIC: it looks for this console's own external paths
    (`runtime/EdWebConsole`, `recovery/EdWebConsole`, `artifacts/EdWebConsole`, `worktrees`)
    beside the checkout, not for generic directory names that some other project might own.

      NOT_PROVEN_FROM_CI  running in CI; the host is not observable from here
      SEPARATED           all four host paths exist and no runtime state is tracked in source
      NOT_YET_SEPARATED   inherited runtime state still in source, not growing — the baseline
      VIOLATED            runtime state is being RE-CREATED inside source (above baseline)
    """
    src = (root or REPO).resolve()
    if _in_ci() and not force_local:
        return {"state": "NOT_PROVEN_FROM_CI", "host_root": None, "host_paths_present": {},
                "tracked_runtime_in_source": None, "baseline_runtime_in_source": None,
                "why": "a CI runner has no host layout; the operator's machine is the subject"}
    host = src.parent
    present = {p: (host / p).is_dir() for p in TARGET["host_paths"]}
    # PHYSICAL, not tracked. Ignored files count — that is the whole point, since .gitignore
    # already hides models/**, data/*, backups/db/* and logs/ on this repository.
    physical = physical_generated_state(src)
    tracked = tracked_generated_state(ref, src)
    base_n = len(tracked_generated_state(baseline, src)) if baseline else None
    if base_n is not None and len(tracked) > base_n:
        state = "VIOLATED"
    elif not physical and all(present.values()):
        state = "SEPARATED"
    else:
        state = "NOT_YET_SEPARATED"
    return {"state": state, "host_root": str(host), "host_paths_present": present,
            "physical_generated_in_source": len(physical),
            "tracked_runtime_in_source": len(tracked),
            "baseline_runtime_in_source": base_n,
            "sample": physical[:5]}


# ── the ratchet ───────────────────────────────────────────────────────────────────────────
def _target_at(ref: str, repo: Path = REPO) -> dict | None:
    """The TARGET literal as it exists at `ref`, parsed without executing that revision."""
    src = _git(["show", f"{ref}:tools/repo_rehab_status.py"], repo)
    if not src:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "TARGET" and node.value is not None:
            try:
                return ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                return None
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "TARGET" for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                return None
    return None


def _imported_module_names(src: str) -> list[tuple[str, int]]:
    """(dotted module, relative-level) for EVERY import form a static reader can see.

    Four forms, because a rule that only reads `import x` at module scope is a rule about
    formatting. Covered: absolute `import a.b` / `from a.b import c`; relative
    `from ..pkg import c` (level > 0); imports nested inside functions, `if TYPE_CHECKING`,
    try/except and conditionals (ast.walk, not tree.body); and dynamic
    `importlib.import_module("a.b")` / `__import__("a.b")` when the argument is a literal.

    HONEST LIMIT: a dynamic import whose name is computed at runtime cannot be read statically.
    That is why this feeds a RATCHET on a count rather than a prohibition — the number may not
    grow, and a computed import is visible to review as an obvious outlier.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            # The BARE module AND every alias. `from app import decision` carries the package in
            # `names`, not in `module`, so reading `module` alone let the whole dependency
            # lattice be walked around by spelling the import differently. `from .. import api`
            # is the same hole through the relative form.
            base_mod = node.module or ""
            lvl = node.level or 0
            out.append((base_mod, lvl))
            for a in node.names:
                out.append((f"{base_mod}.{a.name}" if base_mod else a.name, lvl))
        elif isinstance(node, ast.Call):
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else "")
            if name in ("import_module", "__import__") and node.args:
                a0 = node.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    out.append((a0.value, 0))
    return out


def app_files_importing_legacy(ref: str, repo: Path = REPO) -> list[str]:
    """app/** files that still depend on root modules or legacy directories.

    THE FACADE RISK, made countable. Nothing stops `app/domain/foo.py` importing root `db` or
    `calibration.*`, and unbounded that produces the worst available outcome: `app/` satisfies
    every structural metric while delegating to an unchanged root — a directory rename wearing a
    migration's name. Legacy imports are legal (they must be, mid-migration) but the COUNT may
    only fall.
    """
    files = tracked_files(ref, repo)
    root_mods = {Path(f).stem for f in files if "/" not in f and f.endswith(".py")}
    legacy = _legacy_dirs()
    out: list[str] = []
    for f in files:
        if not (f.startswith("app/") and f.endswith(".py")):
            continue
        for mod, level in _imported_module_names(_git(["show", f"{ref}:{f}"], repo) or ""):
            if level:
                continue                   # relative imports stay inside app/ by construction
            head = mod.split(".")[0]
            if head and (head in root_mods or head in legacy):
                out.append(f)
                break
    return sorted(set(out))


def is_compatibility_shim(src: str) -> bool:
    """True when a module only RE-EXPORTS from app/ — no logic of its own.

    This is what makes incremental migration possible. `app/foo.py` lands, root `foo.py` becomes
    `from app.domain.foo import *`, every existing import keeps working, and the root file dies
    in a later delta. Blocking that would force a flag-day rewrite, which is the one thing the
    rehabilitation must not require.

    Structural, not a size heuristic: every top-level statement must be an import, a simple
    assignment (`__all__`), a docstring or `pass`, AND at least one import must come from `app`.
    A file with a function or class body is carrying logic and is a second owner, however short.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    touches_app = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "app":
                touches_app = True
        elif isinstance(node, ast.Import):
            if any(a.name.split(".")[0] == "app" for a in node.names):
                touches_app = True
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.Pass)):
            # The VALUE must be inert too. Checking only the statement TYPE let a root module
            # keep every line of its logic as `RESULT = (lambda: ...)()` or a comprehension and
            # still be certified a re-export — the docstring promised "no logic" while the code
            # only checked "no def".
            val = getattr(node, "value", None)
            if val is not None and any(
                    isinstance(n, (ast.Call, ast.Lambda, ast.ListComp, ast.SetComp,
                                   ast.DictComp, ast.GeneratorExp, ast.Await, ast.IfExp))
                    for n in ast.walk(val)):
                return False
            continue
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue                       # module docstring
        else:
            return False                   # a def/class/if/loop is logic, not a re-export
    return touches_app


def _target_literal_in_own_source() -> dict | None:
    """The TARGET literal as written in THIS file, for comparison against the live object."""
    try:
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        tgt = (node.target if isinstance(node, ast.AnnAssign)
               else next((t for t in node.targets), None) if isinstance(node, ast.Assign)
               else None)
        if isinstance(tgt, ast.Name) and tgt.id == "TARGET" and node.value is not None:
            try:
                return ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                return None
    return None


def ratchet(base: str = "origin/main", head: str = "HEAD", repo: Path = REPO) -> list[str]:
    """Refuse NEW divergence from the TARGET. Inherited debt may stay; it may not grow.

    Deliberately NOT a debt checker: `check_delta_adds_no_debt` already owns institutional
    violations. This adds only the architecture predicates nothing else measures.
    """
    # BASE==HEAD NEUTERS EVERY RULE. Every predicate below is a set difference between two
    # trees; with the same commit on both sides they are all empty and the gate reports PASS.
    # MEASURED: `--ratchet --base HEAD` passed on the live repository. The workflow supplies the
    # base, so the gate must not trust it.
    b_sha = (_git(["rev-parse", base], repo) or base).strip()
    h_sha = (_git(["rev-parse", head], repo) or head).strip()
    if b_sha and b_sha == h_sha:
        return [f"RATCHET NEUTERED BY ARGUMENT: base and head both resolve to {b_sha[:12]}, so "
                f"every comparison is empty and the gate cannot fail. Pass the real trunk."]

    # Before ANY predicate reads TARGET. If the live object is not the one written in this file,
    # every measurement below is taken against something nobody reviewed — including the
    # measurements that would have reported the mutation.
    mutated = _runtime_mutation_violations()
    if mutated:
        return mutated

    b, h = current(base, repo, with_loc=False), current(head, repo, with_loc=False)
    out: list[str] = []

    out.extend(_target_drift_violations(base, head, repo))

    # Inherited root LOC is START_SHA debt: it may stay or shrink, never grow. Without this a
    # repo can hold 147 root modules forever and keep FEEDING them, which is drift wearing
    # inherited debt's name — MEASURED: +33 LOC landed that way in one day.
    b_loc = current(base, repo)["root_production_loc"]
    h_loc = current(head, repo)["root_production_loc"]
    if h_loc > b_loc:
        out.append(
            f"INHERITED ROOT LOC GREW: {b_loc} -> {h_loc} (+{h_loc - b_loc}). Existing root "
            f"modules are START_SHA debt — they may remain or shrink while they are migrated, "
            f"but adding lines to them deepens the debt this rehabilitation is retiring. Put "
            f"new logic in app/<package>/.")

    if h["undeclared_app_paths"]:
        new_undeclared = sorted(set(h["undeclared_app_paths"]) - set(b["undeclared_app_paths"]))
        if new_undeclared:
            out.append(
                f"UNDECLARED APP CHILD: {', '.join(new_undeclared[:6])}"
                f"{' ...' if len(new_undeclared) > 6 else ''}. Every file under app/ must sit "
                f"inside a DECLARED package ({', '.join(TARGET['app_packages'])}). A file at "
                f"app/x.py or in an undeclared subpackage is inspected by neither the root rule "
                f"nor the dependency rule.")

    if h["app_imports_legacy"] > b["app_imports_legacy"]:
        out.append(
            f"APP->LEGACY DEPENDENCIES GREW: {b['app_imports_legacy']} -> "
            f"{h['app_imports_legacy']} app/ files import root or legacy modules. Such imports "
            f"are legal mid-migration and the count may only FALL — otherwise app/ becomes a "
            f"facade over an unchanged root and every structural metric still reads green.")

    new_links = sorted(set(tracked_gitlinks(head, repo)) - set(tracked_gitlinks(base, repo)))
    if new_links:
        out.append(
            f"NEW SUBMODULE: {', '.join(new_links)}. A gitlink carries unlimited code and binary "
            f"state that no path rule can see — it has no slash, no suffix and no blob. Adding "
            f"one moves the repository somewhere this design cannot measure.")

    new_root = sorted(set(h["_root_py_names"]) - set(b["_root_py_names"]))
    if new_root:
        out.append(
            f"NEW ROOT PRODUCTION MODULE(S): {', '.join(new_root)}. The TARGET has none; new "
            f"code belongs in app/<package>/. Inherited root modules may stay — this refuses "
            f"ADDING to them.")

    # Duplicate production authority at HEAD — but a temporary COMPATIBILITY SHIM is the
    # intended migration step, not a violation. `app/foo.py` landing while root `foo.py` stays
    # behind as a re-export is exactly how imports get moved without a flag day.
    app_stems = {Path(f).stem for f in h["_app_py_names"]}
    real_dupes = []
    for stem in sorted(app_stems & {Path(f).stem for f in h["_root_py_names"]}):
        if not is_compatibility_shim(_git(["show", f"{head}:{stem}.py"], repo) or ""):
            real_dupes.append(stem)
    if real_dupes:
        out.append(
            f"DUPLICATE PRODUCTION AUTHORITY: {', '.join(real_dupes)} exists under app/ AND at "
            f"the repo root at HEAD, and the root copy still carries logic. One module, two "
            f"owners. Reduce the root file to a re-export shim (imports only) or delete it.")

    base_app_stems = {Path(f).stem for f in b["_app_py_names"]}
    regressed = sorted(base_app_stems & {Path(f).stem for f in h["_root_py_names"]} - app_stems)
    if regressed:
        out.append(
            f"MIGRATED CODE MOVED BACK TOWARD ROOT: {', '.join(regressed)} was under app/ at the "
            f"base and is at the repo root at HEAD. Migration is one-way.")

    new_rt = sorted(set(h["_runtime_names"]) - set(b["_runtime_names"]))
    if new_rt:
        out.append(
            f"NEW TRACKED RUNTIME/GENERATED STATE: {', '.join(new_rt[:6])}"
            f"{' ...' if len(new_rt) > 6 else ''}. Runtime, DB, backup, log and trained-model "
            f"state lives outside source — see the TARGET host paths.")

    # DYNAMIC: any top-level directory the TARGET neither names nor dispositions.
    new_unknown = sorted(set(h["unknown_top_level_dirs"]) - set(b["unknown_top_level_dirs"]))
    if new_unknown:
        out.append(
            f"NEW NON-TARGET TOP-LEVEL DIRECTORY: {', '.join(new_unknown)}. Every top-level "
            f"directory is either TARGET source ({', '.join(TARGET['source_top_level'])}) or a "
            f"legacy directory with a stated disposition. A new one is a new unexplained "
            f"difference, which is what this rehabilitation is closing.")

    # ADDITIONS, not net. A single aggregate over 13 directories stays flat while 100 curated
    # files leave and 99 generated ones arrive — composition worsens, the scalar does not move.
    b_legacy = {f for f in tracked_files(base, repo)
                if "/" in f and f.split("/")[0] in _legacy_dirs()}
    h_legacy = {f for f in tracked_files(head, repo)
                if "/" in f and f.split("/")[0] in _legacy_dirs()}
    added_legacy = sorted(h_legacy - b_legacy)
    if added_legacy:
        out.append(
            f"NEW FILES IN A LEGACY DIRECTORY: {', '.join(added_legacy[:6])}"
            f"{' ...' if len(added_legacy) > 6 else ''}. Directories awaiting disposition may "
            f"only shrink — a net count that stays flat while the contents churn is not "
            f"progress.")

    out.extend(_dependency_direction_violations(head, repo))
    out.extend(_self_protection_violations(base, head, repo))
    return out


def _runtime_mutation_violations() -> list[str]:
    """The live TARGET object must be the literal written in this file.

    RUNTIME MUTATION defeats both other protections at once: `TARGET["app_packages"].append(x)`
    placed AFTER the digest is computed leaves TARGET_SHA256 untouched (already taken) and leaves
    the AST literal untouched (the mutation is a separate statement), while the live object every
    predicate reads is different. PROVEN in review: a poisoned module admitted a `vendor/` top
    level, an undeclared app package and a reversed dependency edge with the digest still
    matching. This runs FIRST in ratchet(), before any predicate reads TARGET.
    """
    own = _target_literal_in_own_source()
    if own is not None and _digest(own) != _digest(TARGET):
        return [f"TARGET MUTATED AT RUNTIME: the live TARGET object ({_digest(TARGET)[:16]}) "
                f"does not match the literal in this file ({_digest(own)[:16]}). Something "
                f"edits it after definition, so both the digest pin and the base-ref comparison "
                f"read a target that is not the one in force."]
    return []


def _target_drift_violations(base: str, head: str, repo: Path = REPO) -> list[str]:
    """The TARGET may not move to flatter the score — checked BASE against HEAD.

    The digest pin in the test suite is necessary and NOT sufficient: a single delta can edit
    the target, update the pin and update the test together, and every test it ships with will
    pass. Only a comparison against the base ref can see that, and reading the base is what
    makes it impossible for a change to authorise its own goalpost move.
    """
    base_target = _target_at(base, repo)
    if base_target is None:
        return []                      # the tool does not exist at the base: first landing
    head_target = _target_at(head, repo)
    if head_target is None:
        return ["TARGET UNREADABLE AT HEAD: tools/repo_rehab_status.py no longer defines a "
                "literal TARGET, so drift cannot be measured. Unmeasurable is not compliant."]
    if _digest(base_target) == _digest(head_target):
        return []
    changed = sorted(
        k for k in set(base_target) | set(head_target)
        if base_target.get(k) != head_target.get(k))
    return [
        f"TARGET DRIFT: the fixed target changed in this delta (fields: {', '.join(changed)}). "
        f"base sha256={_digest(base_target)[:16]} head sha256={_digest(head_target)[:16]}. The "
        f"target is the operator's, and a rehabilitation that can redefine 'done' measures "
        f"nothing. Land the target change as its own reviewed decision."]


def _dependency_direction_violations(ref: str, repo: Path = REPO) -> list[str]:
    """Once app/<pkg> exists, it may only import the packages the TARGET allows it to."""
    allowed = TARGET["dependency_direction"]
    out: list[str] = []
    for f in tracked_files(ref, repo):
        if not (f.startswith("app/") and f.endswith(".py") and f.count("/") >= 2):
            continue
        pkg = f.split("/")[1]
        if pkg not in allowed:
            continue
        for mod, level in _imported_module_names(_git(["show", f"{ref}:{f}"], repo) or ""):
            if level:
                # Relative: resolve against this file's package. `from ..signals import x`
                # inside app/domain/sub/f.py walks up `level` segments from the file's dir.
                segs = f.split("/")[:-1]                     # app, pkg, [sub...]
                up = segs[:len(segs) - (level - 1)] if level > 1 else segs
                target = (up + (mod.split(".") if mod else []))
                if len(target) >= 2 and target[0] == "app":
                    other = target[1]
                else:
                    continue
            else:
                parts = mod.split(".")
                if len(parts) < 2 or parts[0] != "app":
                    continue
                other = parts[1]
            if other != pkg and other not in allowed[pkg]:
                out.append(
                    f"FORBIDDEN DEPENDENCY DIRECTION: {f} (app/{pkg}) imports app.{other}, "
                    f"which app/{pkg} may not depend on.")
    return sorted(set(out))


#: WHERE THE TRUST ROOT ACTUALLY IS — and it is not here.
#:
#: Every protection in this file, and the institutional fold that watches this file, runs FROM
#: THE PULL REQUEST'S OWN CODE. A change may therefore weaken the checker and ship the weakened
#: checker in the same delta; each layer only catches the layer below it, and the recursion has
#: to stop somewhere. It stops OUTSIDE the repository, at branch protection — a GitHub setting
#: no file in this tree can assert.
#:
#: Pretending otherwise would be the same false-enforcement defect this repository has spent the
#: week removing, so the honest move is to name the surface an out-of-repo anchor must lock. A
#: `pull_request_target` workflow, defined on the BASE branch and therefore not editable by the
#: PR, would run these checks from trusted code against the candidate tree. NOT BUILT HERE: it
#: needs an operator decision about workflow permissions, and inventing it unilaterally is
#: exactly the governance sprawl the charter forbids.
TRUST_ANCHOR_LOCK_SURFACE = (
    ".github/workflows/hardening.yml",        # the required job and its steps
    ".github/workflows/pytest.yml",           # the other required job
    "tools/repo_rehab_status.py",             # the ratchet and the TARGET literal
    "tools/check_institutional_correctness.py",   # the enforced catalog + the CI-invocation fold
    "tools/check_delta_adds_no_debt.py",      # the delta owner that runs the catalog twice
    "tools/precommit_institutional.py",       # the retirement two-step
    "tools/gate_test_ownership.py",           # which tests a change must run
    "tests/test_repo_rehab_ratchet_v1.py",    # the ratchet's negative controls
    "governance/retired_checks.md",           # the declared-retirement register
    ".pre-commit-config.yaml",                # the commit-time wiring
)


def _self_protection_violations(base: str, head: str, repo: Path = REPO) -> list[str]:
    """Deleting, disabling or unwiring this ratchet is itself a regression.

    Same contract `check_delta_adds_no_debt` applies to enforced checks: if the BASE ref had the
    protection and HEAD does not, refuse — read from the base so a change cannot authorise the
    removal of its own gate in the same delta.
    """
    wf = ".github/workflows/hardening.yml"
    tool = "tools/repo_rehab_status.py"
    base_wf = _git(["show", f"{base}:{wf}"], repo) or ""
    head_wf = _git(["show", f"{head}:{wf}"], repo) or ""
    head_files = set(tracked_files(head, repo))
    out: list[str] = []
    if "repo_rehab_status.py" in base_wf and "repo_rehab_status.py" not in head_wf:
        out.append(
            f"REHAB RATCHET REMOVED FROM REQUIRED CI: {wf} invoked it at the base and does not "
            f"at HEAD. The gate is not optional; restore the step.")
    if "repo_rehab_status.py" in base_wf and tool not in head_files:
        out.append(f"REHAB RATCHET DELETED: {tool} is gone at HEAD while CI still requires it.")
    step = "\n".join(ln for ln in head_wf.splitlines() if "repo_rehab_status" in ln)
    if "repo_rehab_status.py" in head_wf and "--ratchet" not in step:
        out.append(
            f"REHAB RATCHET DEMOTED: {wf} runs {tool} without --ratchet, so it reports without "
            f"blocking. A gate that cannot fail is not a gate.")
    if "repo_rehab_status.py" in head_wf and "|| true" in step:
        out.append(f"REHAB RATCHET DEMOTED: its step in {wf} swallows failure with `|| true`.")
    return out


# ── report ────────────────────────────────────────────────────────────────────────────────
def prior_daily_point(ref: str = "origin/main", hours: int = 24, repo: Path = REPO) -> str:
    """The merged point this report's DAILY delta is measured FROM.

    A git fact, not stored state: the last commit on the trunk older than `hours`. No report
    archive is needed to know where yesterday was, and none is written.
    """
    out = _git(["rev-list", "-1", f"--before={hours}.hours.ago", ref], repo)
    return (out or "").strip() or ref


#: (label, key, target, direction). DIRECTION IS EXPLICIT because inferring it from the key
#: prefix scored two metrics backwards: `app_imports_legacy` starts with "app_" and so a RISE in
#: facade edges read as improvement, and `tools_py`/`governance_files` were scored "better" when
#: they FELL, rewarding deletion of the tooling and governance that hold the line.
#:   "down" progress is a decrease · "up" progress is an increase · "info" is not scored
_METRICS = [
    ("root production modules", "root_production_modules", 0, "down"),
    ("root production LOC", "root_production_loc", 0, "down"),
    ("server.py LOC", "server_py_loc", 0, "down"),
    ("app modules", "app_modules", None, "up"),
    ("app LOC", "app_loc", None, "up"),
    ("tools .py files", "tools_py", None, "info"),
    ("governance files", "governance_files", None, "info"),
    ("tracked runtime artifacts", "tracked_runtime_artifacts", 0, "down"),
    ("legacy tracked files", "legacy_tracked_files", 0, "down"),
    ("app files importing legacy", "app_imports_legacy", 0, "down"),
]


def _delta_block(title: str, a: dict, b: dict) -> tuple[list[str], str]:
    rows, better, worse = [], 0, 0
    for label, key, target, direction in _METRICS:
        s, c = a[key], b[key]
        d = c - s
        if d and direction != "info":
            good = d > 0 if direction == "up" else d < 0
            better, worse = better + (1 if good else 0), worse + (0 if good else 1)
        rows.append(f"  {label:<28} {s:>8} -> {c:<8} {d:+8d}   target "
                    f"{'—' if target is None else target}"
                    f"{'  (info)' if direction == 'info' else ''}")
    verdict = "REGRESSED" if worse else ("IMPROVED" if better else "FLAT")
    return ([title, *rows, f"  VERDICT: {verdict}"], verdict)


def report(start_sha: str = START_SHA, base: str = "origin/main") -> str:
    cur = current(base)
    start = current(start_sha)
    prior = prior_daily_point(base)
    yday = current(prior)
    host = host_separation(baseline=start_sha, ref=base)

    daily, _ = _delta_block(
        f"C. TODAY'S DELTA — prior merged point {yday['ref']} -> {cur['ref']}", yday, cur)
    cumulative, _ = _delta_block(
        f"D. CUMULATIVE — START_SHA {start['ref']} -> {cur['ref']}", start, cur)

    out = ["=" * 78, "A. CURRENT SCHEMATIC (generated from the tree)", "=" * 78, "EdWebConsole/"]
    if cur["app_packages_present"]:
        out += ["  app/"] + [f"    {p}/" for p in cur["app_packages_present"]]
    out += [f"  {d}/" for d in sorted(set(cur["_top_level"]))]
    out += [f"  <{cur['root_production_modules']} root .py modules, "
            f"{cur['root_production_loc']} LOC>"]
    if cur["unknown_top_level_dirs"]:
        out += [f"  !! UNDISPOSITIONED: {', '.join(cur['unknown_top_level_dirs'])}"]

    out += ["", "=" * 78, f"B. FIXED TARGET SCHEMATIC   sha256={TARGET_SHA256[:16]}", "=" * 78,
            "EdWebConsole/", "  app/"]
    out += [f"    {p}/" for p in TARGET["app_packages"]]
    out += [f"  {d}/" for d in TARGET["source_top_level"] if d != "app"]
    out += ["  (host, outside source: " + ", ".join(TARGET["host_paths"]) + ")",
            "  legacy dispositions:"]
    out += [f"    {k:<24} -> {v}" for k, v in sorted(TARGET["legacy_disposition"].items())]

    out += ["", "=" * 78] + daily + ["", "=" * 78] + cumulative
    out += ["", f"  HOST SEPARATION: {host['state']}"]
    if host["state"] == "NOT_PROVEN_FROM_CI":
        out += [f"    ({host['why']}; run locally for a verdict)"]
    else:
        out += [f"    host paths present "
                f"{sum(host['host_paths_present'].values())}/{len(host['host_paths_present'])}",
                f"    generated state PHYSICALLY in source (ignored files included): "
                f"{host['physical_generated_in_source']}",
                f"    of which TRACKED: {host['tracked_runtime_in_source']} "
                f"(baseline {host['baseline_runtime_in_source']})"]
    if cur["undeclared_app_paths"]:
        out += [f"  !! UNDECLARED APP PATHS: {len(cur['undeclared_app_paths'])}"]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratchet", action="store_true")
    ap.add_argument("--host", action="store_true")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--start-sha", default=START_SHA)
    a = ap.parse_args()

    if a.host:
        print(json.dumps(host_separation(baseline=a.start_sha), indent=2))
        return 0
    if a.ratchet:
        bad = ratchet(a.base, a.head)
        if bad:
            sys.stderr.write(
                "[FAIL] repo rehabilitation ratchet — this delta moves AWAY from the TARGET:\n\n"
                + "".join(f"  * {b}\n" for b in bad)
                + "\nInherited debt is allowed to remain. It is not allowed to grow.\n")
            return 1
        print("[PASS] repo rehabilitation ratchet: no new divergence from the TARGET.")
        return 0
    print(report(a.start_sha, a.base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
