"""Typed, identity-bound per-turn audit transaction (RC-330).

The authoritative result is the JSON document returned to the Stop supervisor
for that supervisor's own child process.  Command history and repository JSONL
files are telemetry only and never authorize Stop.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
LOG_REL = "reports/turn_self_audit_log.jsonl"
CONTRACT_ID = "CLEAN_FOR_TURN_CONTRACT_V1"
SCHEMA_VERSION = 1

#: FC-13: the production-surface geometry moved to tools/pretooluse_guard.classify_path so
#: one resolve-and-compare answers governance and product-surface for every caller. These
#: names are retained as re-exports because they are part of this module's public surface.
try:  # guards run both as `tools.x` and as bare `x` from inside tools/ — support both
    from tools.pretooluse_guard import NOT_PRODUCT_PREFIXES as NON_PROD_PREFIXES
    from tools.pretooluse_guard import PRODUCTION_SUFFIXES as PROD_SUFFIXES
except ImportError:  # pragma: no cover - exercised by the guard subprocess tests
    from pretooluse_guard import NOT_PRODUCT_PREFIXES as NON_PROD_PREFIXES  # type: ignore # noqa: F401
    from pretooluse_guard import PRODUCTION_SUFFIXES as PROD_SUFFIXES  # type: ignore # noqa: F401

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_PROVEN = "NOT_PROVEN"
STATUS_INCOMPLETE = "INCOMPLETE"
CHECK_STATUSES = {STATUS_PASS, STATUS_FAIL, STATUS_NOT_PROVEN, STATUS_INCOMPLETE}

VERDICT_CLEAN = "CLEAN"
VERDICT_FAIL = "FAIL"
VERDICT_NOT_PROVEN = "NOT_PROVEN"
VERDICT_INCOMPLETE = "INCOMPLETE"
VERDICT_NO_CHANGE = "NO_RELEVANT_PRODUCTION_CHANGE"
VERDICT_EXIT = {
    VERDICT_CLEAN: 0,
    VERDICT_NO_CHANGE: 0,
    VERDICT_FAIL: 1,
    VERDICT_NOT_PROVEN: 2,
    VERDICT_INCOMPLETE: 3,
}

OUTCOME_OK = "ok"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_LAUNCH_FAILURE = "launch_failure"


@dataclass(frozen=True)
class ScopeEntry:
    kind: str
    path: str
    old_path: str | None = None
    tracked: bool = True


@dataclass
class ScopeResult:
    status: str
    entries: list[ScopeEntry] = field(default_factory=list)
    production_entries: list[ScopeEntry] = field(default_factory=list)
    changed_tests: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class OwnershipResult:
    status: str
    suites: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reasons: dict[str, list[str]] = field(default_factory=dict)
    # RC-368 contract: mechanical dispositions instead of silent inclusion/omission —
    # a CHANGED test file with no changed-production ownership evidence is excluded
    # (it must not smuggle itself into the owned run), and a changed production file
    # outside the authoritative session subject is surfaced, not silently covered.
    excluded_changed_tests: dict[str, str] = field(default_factory=dict)
    excluded_production: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckSpec:
    """Typed registration record consumed by the audit transaction."""

    check_id: str
    applicability: str


CORE_CHECK_SPECS = (
    CheckSpec("scope_integrity", "always"),
    # V3 Step 2: the state measurements move here from the process-lock Stop path so their
    # result becomes typed evidence a reviewer can read, instead of a pass/fail with no
    # artifact. The formulas are NOT reimplemented — both delegate to the functions that
    # already own them in tools/operating_process_lock.py.
    CheckSpec("index_worktree_state", "always"),
    CheckSpec("runtime_identity_state", "always"),
    CheckSpec("ruff_changed", "changed_existing_python"),
    CheckSpec("test_ownership", "production_change"),
    CheckSpec("owned_pytest", "production_change"),
)


def _norm(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def is_production_path(path: str) -> bool:
    """Thin accessor over the single path authority (FC-13).

    This used to be an independent formula: `_norm` only stripped a leading "./", so the
    relative-prefix exemption could never match an absolute path and an absolute
    scratchpad/*.py was classified production even though `scratchpad/` was already in the
    exemption list. The governance step (is this path OURS) was missing entirely. Both
    questions now come from one resolve-and-compare in tools/pretooluse_guard.classify_path.
    """
    try:
        from tools.pretooluse_guard import classify_path
    except ImportError:
        from pretooluse_guard import classify_path  # type: ignore
    return classify_path(path).production


def _run(
    args: list[str],
    timeout: int | float = 600,
    *,
    cwd: Path | None = None,
) -> tuple[int, str, str]:
    """Return (exit_code, combined_output, typed process outcome)."""
    try:
        r = subprocess.run(
            args,
            cwd=str(cwd or REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = ""
        for stream in (getattr(exc, "stdout", None), getattr(exc, "stderr", None)):
            if stream:
                partial += stream if isinstance(stream, str) else stream.decode("utf-8", "replace")
        return 1, f"TIMED OUT after {timeout}s (nothing was measured)\n{partial}", OUTCOME_TIMEOUT
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"RUN FAILED: {exc}", OUTCOME_LAUNCH_FAILURE
    return r.returncode, (r.stdout or "") + (r.stderr or ""), OUTCOME_OK


def _git_z(repo: Path, args: list[str]) -> tuple[list[str], str | None]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git {' '.join(args)} launch failed: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        return [], f"git {' '.join(args)} failed with exit {proc.returncode}: {detail}"
    return proc.stdout.split("\0"), None


def discover_scope(
    repo: Path,
    required_session_paths: list[str] | tuple[str, ...] | None = None,
) -> ScopeResult:
    """Return a NUL-safe typed HEAD-to-worktree scope, including untracked files."""
    root = Path(repo).resolve()
    tokens, error = _git_z(root, ["diff", "--name-status", "-z", "--find-renames", "HEAD"])
    if error:
        return ScopeResult(status=STATUS_INCOMPLETE, errors=[error])

    entries: list[ScopeEntry] = []
    i = 0
    while i < len(tokens):
        status = tokens[i]
        i += 1
        if not status:
            continue
        code = status[0]
        if code in ("R", "C"):
            if i + 1 >= len(tokens):
                return ScopeResult(
                    status=STATUS_INCOMPLETE,
                    errors=[f"malformed git rename/copy status record {status!r}"],
                )
            old_path, new_path = _norm(tokens[i]), _norm(tokens[i + 1])
            i += 2
            entries.append(ScopeEntry("RENAME" if code == "R" else "COPY", new_path, old_path))
            continue
        if i >= len(tokens):
            return ScopeResult(
                status=STATUS_INCOMPLETE,
                errors=[f"malformed git status record {status!r}"],
            )
        path = _norm(tokens[i])
        i += 1
        kind = {
            "A": "ADD", "M": "MODIFY", "D": "DELETE", "T": "TYPECHANGE",
            "U": "UNMERGED",
        }.get(code)
        if kind is None:
            return ScopeResult(
                status=STATUS_INCOMPLETE,
                errors=[f"unknown git status {status!r} for {path!r}"],
            )
        entries.append(ScopeEntry(kind, path))

    untracked, error = _git_z(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    if error:
        return ScopeResult(status=STATUS_INCOMPLETE, errors=[error])
    for path in untracked:
        if path:
            entries.append(ScopeEntry("UNTRACKED", _norm(path), tracked=False))

    represented = {
        candidate
        for entry in entries
        for candidate in (entry.path, entry.old_path)
        if candidate
    }
    for raw_path in required_session_paths or ():
        rel = _norm(raw_path)
        if not rel or rel in represented or not is_production_path(rel):
            continue
        entries.append(ScopeEntry(
            "SESSION_EDIT" if (root / rel).is_file() else "SESSION_DELETE",
            rel,
            tracked=True,
        ))
        represented.add(rel)

    # RC-331: the audit's OWN telemetry receipt is not a change to the subject. It is
    # written under reports/ inside the tree the identity hash covers, so in any repository
    # where it does not already exist the write lands between worktree_identity_start and
    # worktree_identity_end and the audit reports its own footprint as drift — verdict
    # INCOMPLETE with every check PASS and checks_failed empty. That is what the ten
    # actual-path controls in tests/test_turn_self_audit_contract_v1.py were hitting: each
    # builds a clean fixture repo, so the receipt is new every time. An observer must not
    # count its own recording as an observation.
    entries = [e for e in entries if e.path != LOG_REL]
    unique = {
        (entry.kind, entry.path, entry.old_path, entry.tracked): entry for entry in entries
    }
    ordered = sorted(unique.values(), key=lambda e: (e.path, e.kind, e.old_path or ""))
    production = [
        entry for entry in ordered
        if is_production_path(entry.path)
        or (entry.old_path is not None and is_production_path(entry.old_path))
    ]
    tests = sorted({
        entry.path for entry in ordered
        if entry.path.startswith("tests/") and Path(entry.path).name.startswith("test_")
        and entry.path.endswith(".py")
    })
    return ScopeResult(
        status=STATUS_PASS,
        entries=ordered,
        production_entries=production,
        changed_tests=tests,
    )


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path_identity(repo: Path, entry: ScopeEntry) -> dict[str, Any]:
    path = repo / entry.path
    if path.is_file():
        try:
            content = _hash_bytes(path.read_bytes())
        except OSError as exc:
            content = f"UNREADABLE:{type(exc).__name__}:{exc}"
    elif entry.kind == "DELETE":
        content = "DELETED"
    else:
        content = "MISSING"
    result = {
        "kind": entry.kind,
        "path": entry.path,
        "old_path": entry.old_path,
        "tracked": entry.tracked,
        "content_sha256": content,
    }
    return result


def _git_scalar(repo: Path, args: list[str]) -> tuple[str, str | None]:
    code, out, outcome = _run(["git", *args], timeout=30, cwd=repo)
    if outcome != OUTCOME_OK or code != 0:
        return "", f"git {' '.join(args)} unavailable ({outcome}, exit={code}): {out.strip()[:240]}"
    value = out.strip()
    if not value:
        return "", f"git {' '.join(args)} returned an empty identity"
    return value, None


def capture_identity(repo: Path, scope: ScopeResult | None = None) -> tuple[dict[str, str], list[str]]:
    root = Path(repo).resolve()
    errors: list[str] = []
    canonical, err = _git_scalar(root, ["rev-parse", "--show-toplevel"])
    if err:
        errors.append(err)
        canonical = str(root)
    else:
        canonical = str(Path(canonical).resolve())
    head, err = _git_scalar(root, ["rev-parse", "HEAD"])
    if err:
        errors.append(err)
    index, err = _git_scalar(root, ["write-tree"])
    if err:
        errors.append(err)
    current_scope = scope or discover_scope(root)
    if current_scope.status != STATUS_PASS:
        errors.extend(current_scope.errors)
    # RC-371 (extends RC-331): reports/ artifacts are RECORDINGS — test observability
    # ledgers and telemetry written while the audit observes. An observer must not
    # count its own recording: hashing them made every owned run that logged anything
    # read as subject mutation. The production scope digest below is untouched.
    manifest = [
        _path_identity(root, entry)
        for entry in current_scope.entries
        if not entry.path.startswith("reports/")
    ]
    worktree = _hash_bytes(json.dumps(manifest, sort_keys=True).encode("utf-8"))
    prod_manifest = [
        _path_identity(root, entry) for entry in current_scope.production_entries
    ]
    scope_digest = _hash_bytes(json.dumps(prod_manifest, sort_keys=True).encode("utf-8"))
    return {
        "repo_root": canonical,
        "repo_head": head,
        "index_tree": index,
        "worktree_identity": worktree,
        "scope_digest": scope_digest,
    }, errors


def _module_names(path: str) -> set[str]:
    rel = _norm(path)
    if not rel.endswith(".py"):
        return set()
    parts = list(Path(rel[:-3]).parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    dotted = ".".join(parts)
    names = {dotted} if dotted else set()
    # tools are also intentionally importable as bare modules in this repository.
    if len(parts) == 2 and parts[0] == "tools":
        names.add(parts[-1])
    return names


def _test_ownership_evidence(path: Path) -> tuple[set[str], set[str], str | None]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return set(), set(), f"{path}: read failed: {type(exc).__name__}: {exc}"
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return set(), set(), f"{path}: AST parse failed at line {exc.lineno}: {exc.msg}"

    imports: set[str] = set()
    explicit: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imports.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in ("import_module", "__import__") and node.args:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    imports.add(value.value)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(t, ast.Name) and t.id == "TURN_AUDIT_OWNS" for t in targets):
                continue
            value = node.value
            if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                for item in value.elts:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        explicit.add(_norm(item.value))
    return imports, explicit, None


def resolve_test_ownership(
    repo: Path,
    scope: ScopeResult,
    subject_paths: set[str] | frozenset[str] | None = None,
) -> OwnershipResult:
    root = Path(repo).resolve()
    tests_root = root / "tests"
    if not tests_root.is_dir():
        return OwnershipResult(
            status=STATUS_INCOMPLETE,
            errors=["tests/ directory is missing; ownership cannot be established"],
        )

    evidence: list[tuple[str, set[str], set[str]]] = []
    errors: list[str] = []
    # SCOPE IS THE GIT INDEX, not the filesystem (RC-274 -> RC-286 -> RC-307). An rglob here
    # walked whatever happened to be on disk, so untracked scratch files counted as evidence
    # and the audit's own scope moved with the working directory's litter. `git ls-files`
    # gives the same answer on every machine and after every clean.
    _tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "tests/**/test_*.py", "tests/test_*.py"],
        cwd=root, capture_output=True, text=True, check=False).stdout
    for rel in sorted({p for p in _tracked.split("\0") if p}):
        test_path = root / rel
        if not test_path.is_file():
            continue
        if "archive" in Path(rel).parts:
            continue
        imports, explicit, error = _test_ownership_evidence(test_path)
        if error:
            errors.append(error)
        else:
            evidence.append((rel, imports, explicit))
    if errors:
        return OwnershipResult(status=STATUS_INCOMPLETE, errors=errors)

    # RC-368 contract: changed tests are NOT automatic suites — a changed test joins the
    # owned run only through ownership evidence for changed production, else it gets a
    # mechanical exclusion disposition (it must not smuggle itself into its own audit).
    changed_tests = {path for path in scope.changed_tests if (root / path).is_file()}
    suites: set[str] = set()
    unknown: list[str] = []
    reasons: dict[str, list[str]] = {}
    excluded_production: dict[str, str] = {}
    # RC-369: subject paths are FIRST-CLASS subject — a declared subject file whose
    # worktree happens to be clean still gets its owner set resolved (the owner-set
    # question is about the subject, not about whether it is dirty right now).
    entries = list(scope.production_entries)
    if subject_paths is not None:
        represented = {e.path for e in entries} | {
            e.old_path for e in entries if e.old_path
        }
        for rel in sorted(set(subject_paths) - represented):
            if is_production_path(rel) and (Path(repo) / rel).is_file():
                entries.append(ScopeEntry("SESSION_EDIT", rel, tracked=True))
    for entry in entries:
        candidates = {entry.path}
        if entry.old_path:
            candidates.add(entry.old_path)
        if subject_paths is not None and not (candidates & set(subject_paths)):
            # RC-368: outside the authoritative session subject — fail-closed surface,
            # never silent import-fanout coverage.
            excluded_production[entry.path] = "outside authoritative session subject"
            unknown.append(entry.path)
            continue
        modules = set().union(*(_module_names(path) for path in candidates))
        explicit_owners: list[str] = []
        import_owners: list[str] = []
        for rel, imports, explicit in evidence:
            if candidates & explicit:
                explicit_owners.append(rel)
            elif modules & imports:
                import_owners.append(rel)
        # RC-368: explicit precedence is PER CHANGED ENTRY — a declared TURN_AUDIT_OWNS
        # owner set replaces incidental import owners for that entry, so the owned run
        # is the declared contract, not the import fan-out.
        if explicit_owners:
            chosen = explicit_owners
            owners = [f"{rel}:TURN_AUDIT_OWNS" for rel in explicit_owners]
        else:
            chosen = import_owners
            owners = [f"{rel}:import" for rel in import_owners]
        suites.update(chosen)
        if owners:
            reasons[entry.path] = sorted(owners)
        else:
            unknown.append(entry.path)
    excluded_changed_tests = {
        rel: "no changed production ownership evidence"
        for rel in sorted(changed_tests)
        if rel not in suites
    }
    return OwnershipResult(
        status=STATUS_NOT_PROVEN if unknown else STATUS_PASS,
        suites=sorted(suites),
        unknown=sorted(set(unknown)),
        reasons=reasons,
        excluded_changed_tests=excluded_changed_tests,
        excluded_production=excluded_production,
    )


def _state_check_records(root: Path) -> list[dict[str, Any]]:
    """V3 Step 2 — typed evidence for the two repository-state measurements.

    Both delegate to tools/operating_process_lock, which already owns the computations. A
    measurement that cannot be taken records INCOMPLETE, never PASS: an unmeasurable state
    is not a clean state (RC-57).
    """
    out: list[dict[str, Any]] = []

    started = time.time()
    try:
        try:
            from tools.operating_process_lock import index_worktree_mismatches
        except ImportError:
            from operating_process_lock import index_worktree_mismatches  # type: ignore
        mismatches = index_worktree_mismatches(root)
        out.append(_check_record(
            "index_worktree_state",
            STATUS_PASS if not mismatches else STATUS_FAIL,
            started=started,
            exit_code=0 if not mismatches else 1,
            outcome=OUTCOME_OK,
            detail=("no enforcement path differs between index and worktree"
                    if not mismatches else "; ".join(mismatches[:10])),
        ))
    except Exception as exc:  # noqa: BLE001 - unmeasurable must not read as clean
        out.append(_check_record(
            "index_worktree_state", STATUS_INCOMPLETE, started=started,
            exit_code=None, outcome="measurement_failed",
            detail=f"{type(exc).__name__}: {exc}",
        ))

    started = time.time()
    try:
        try:
            from tools.operating_process_lock import live_collect_disk_only
        except ImportError:
            from operating_process_lock import live_collect_disk_only  # type: ignore
        disk_only = live_collect_disk_only(root)
        out.append(_check_record(
            "runtime_identity_state",
            STATUS_PASS if not disk_only else STATUS_FAIL,
            started=started,
            exit_code=0 if not disk_only else 1,
            outcome=OUTCOME_OK,
            detail=("running console matches the tree, or no console is running"
                    if not disk_only else str(disk_only)),
        ))
    except Exception as exc:  # noqa: BLE001
        out.append(_check_record(
            "runtime_identity_state", STATUS_INCOMPLETE, started=started,
            exit_code=None, outcome="measurement_failed",
            detail=f"{type(exc).__name__}: {exc}",
        ))

    return out


def _check_record(
    check_id: str,
    status: str,
    *,
    started: float,
    exit_code: int | None,
    outcome: str,
    command: list[str] | None = None,
    detail: str = "",
) -> dict[str, Any]:
    ended = time.time()
    return {
        "check_id": check_id,
        "status": status,
        "started_at": started,
        "ended_at": ended,
        "duration_ms": round((ended - started) * 1000, 3),
        "exit_code": exit_code,
        "outcome": outcome,
        "command": command or [],
        "detail": detail[-4000:],
    }


def _status_for_process(code: int, outcome: str) -> str:
    if outcome != OUTCOME_OK:
        return STATUS_INCOMPLETE
    return STATUS_PASS if code == 0 else STATUS_FAIL


def required_check_ids(repo: Path, scope: ScopeResult) -> list[str]:
    """Independently derive the complete required check set for this subject."""
    has_production = bool(scope.production_entries)
    has_existing_python = any(
        entry.path.endswith(".py")
        and entry.kind != "DELETE"
        and (Path(repo) / entry.path).is_file()
        for entry in scope.production_entries
    )
    required: list[str] = []
    for spec in CORE_CHECK_SPECS:
        applies = (
            spec.applicability == "always"
            or (spec.applicability == "production_change" and has_production)
            or (spec.applicability == "changed_existing_python" and has_existing_python)
        )
        if applies:
            required.append(spec.check_id)
    return required


def _aggregate_verdict(
    checks: list[dict[str, Any]],
    *,
    has_production_change: bool,
    internal_errors: list[str],
    stable: bool,
) -> str:
    statuses = [str(check.get("status")) for check in checks]
    if internal_errors or not stable or STATUS_INCOMPLETE in statuses:
        return VERDICT_INCOMPLETE
    if STATUS_FAIL in statuses:
        return VERDICT_FAIL
    if STATUS_NOT_PROVEN in statuses:
        return VERDICT_NOT_PROVEN
    if not has_production_change:
        return VERDICT_NO_CHANGE
    return VERDICT_CLEAN


def _scope_payload(scope: ScopeResult) -> dict[str, Any]:
    return {
        "status": scope.status,
        "entries": [asdict(entry) for entry in scope.entries],
        "production_entries": [asdict(entry) for entry in scope.production_entries],
        "changed_tests": scope.changed_tests,
        "errors": scope.errors,
    }


def _ownership_payload(ownership: OwnershipResult) -> dict[str, Any]:
    return asdict(ownership)


def run_audit(
    repo: Path,
    session_id: str,
    *,
    authoritative: bool = True,
    research: str = "",
    pytest_timeout: int = 1800,
    required_session_paths: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Execute one complete typed audit transaction."""
    started = time.time()
    run_id = str(uuid.uuid4())
    root = Path(repo).resolve()
    internal_errors: list[str] = []
    checks: list[dict[str, Any]] = []

    session_paths = sorted({_norm(path) for path in required_session_paths or ()})
    scope = discover_scope(root, session_paths)
    start_identity, identity_errors = capture_identity(root, scope)
    internal_errors.extend(identity_errors)

    check_started = time.time()
    scope_status = STATUS_PASS if scope.status == STATUS_PASS and not identity_errors \
        else STATUS_INCOMPLETE
    checks.append(_check_record(
        "scope_integrity",
        scope_status,
        started=check_started,
        exit_code=0 if scope_status == STATUS_PASS else None,
        outcome=OUTCOME_OK if scope_status == STATUS_PASS else "scope_error",
        detail="; ".join(scope.errors + identity_errors),
    ))

    for record in _state_check_records(root):
        checks.append(record)

    ownership = OwnershipResult(status=STATUS_PASS)
    relevant = bool(scope.production_entries)
    py_files = sorted({
        entry.path for entry in scope.production_entries
        if entry.path.endswith(".py") and entry.kind != "DELETE" and (root / entry.path).is_file()
    })

    if relevant and scope_status == STATUS_PASS:
        if py_files:
            # RC-368: the observer leaves no footprint — a .ruff_cache written into the
            # subject flips worktree identity between start and end and self-INCOMPLETEs
            # the audit (same class as the RC-331 receipt exclusion below).
            command = [
                sys.executable, "-m", "ruff", "check", *py_files,
                "--select", "F401,F821,E9", "--no-cache",
            ]
            check_started = time.time()
            code, output, outcome = _run(command, timeout=600, cwd=root)
            checks.append(_check_record(
                "ruff_changed",
                _status_for_process(code, outcome),
                started=check_started,
                exit_code=code if outcome == OUTCOME_OK else None,
                outcome=outcome,
                command=command,
                detail=output,
            ))

        check_started = time.time()
        ownership = resolve_test_ownership(root, scope)
        checks.append(_check_record(
            "test_ownership",
            ownership.status,
            started=check_started,
            exit_code=0 if ownership.status == STATUS_PASS else None,
            outcome="resolved" if ownership.status == STATUS_PASS else "unresolved",
            detail=json.dumps(_ownership_payload(ownership), sort_keys=True),
        ))

        check_started = time.time()
        if ownership.status == STATUS_PASS and ownership.suites:
            # RC-368: -B (no __pycache__) + no:cacheprovider (no .pytest_cache) — the
            # audit's own pytest child must not mutate the subject it is measuring, or
            # identity start != end and every clean audit self-INCOMPLETEs.
            command = [
                sys.executable, "-B", "-m", "pytest",
                "-p", "no:cacheprovider", *ownership.suites, "-q",
            ]
            code, output, outcome = _run(command, timeout=pytest_timeout, cwd=root)
            pytest_status = _status_for_process(code, outcome)
            checks.append(_check_record(
                "owned_pytest",
                pytest_status,
                started=check_started,
                exit_code=code if outcome == OUTCOME_OK else None,
                outcome=outcome,
                command=command,
                detail=output,
            ))
        elif ownership.status == STATUS_INCOMPLETE:
            checks.append(_check_record(
                "owned_pytest", STATUS_INCOMPLETE, started=check_started,
                exit_code=None, outcome="ownership_incomplete",
                detail="test ownership could not be parsed",
            ))
        else:
            checks.append(_check_record(
                "owned_pytest", STATUS_NOT_PROVEN, started=check_started,
                exit_code=None, outcome="ownership_not_proven",
                detail=f"unknown production owners: {ownership.unknown}",
            ))

    end_scope = discover_scope(root, session_paths)
    end_identity, end_errors = capture_identity(root, end_scope)
    internal_errors.extend(end_errors)
    stable = (
        not internal_errors
        and scope.status == STATUS_PASS
        and end_scope.status == STATUS_PASS
        and start_identity == end_identity
    )
    if not stable:
        internal_errors.append("repository identity or scope changed during audit")

    required = required_check_ids(root, scope)
    executed = [str(check["check_id"]) for check in checks]
    verdict = _aggregate_verdict(
        checks,
        has_production_change=relevant,
        internal_errors=internal_errors,
        stable=stable,
    )
    passed = [c["check_id"] for c in checks if c["status"] == STATUS_PASS]
    failed = [c["check_id"] for c in checks if c["status"] == STATUS_FAIL]
    not_proven = [c["check_id"] for c in checks if c["status"] == STATUS_NOT_PROVEN]
    incomplete = [c["check_id"] for c in checks if c["status"] == STATUS_INCOMPLETE]
    ruff = next((c for c in checks if c["check_id"] == "ruff_changed"), {
        "check_id": "ruff_changed", "status": "NOT_APPLICABLE",
    })
    pytest_result = next((c for c in checks if c["check_id"] == "owned_pytest"), {
        "check_id": "owned_pytest",
        "status": "NOT_APPLICABLE" if not relevant else STATUS_NOT_PROVEN,
    })
    result = {
        "schema_version": SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "audit_run_id": run_id,
        "session_id": session_id,
        "authoritative": bool(authoritative),
        "completed": True,
        "start_time": started,
        "end_time": time.time(),
        "requested_scope": "AUTO_CURRENT_WORKTREE",
        "session_required_files": session_paths,
        "actual_scope": _scope_payload(scope),
        "changed_tracked_files": sorted(
            e.path for e in scope.entries if e.tracked
        ),
        "untracked_production_files": sorted(
            e.path for e in scope.production_entries if not e.tracked
        ),
        "repo_root": start_identity.get("repo_root", str(root)),
        "repo_head": start_identity.get("repo_head", ""),
        "index_tree": start_identity.get("index_tree", ""),
        "worktree_identity_start": start_identity.get("worktree_identity", ""),
        "worktree_identity_end": end_identity.get("worktree_identity", ""),
        "scope_digest": start_identity.get("scope_digest", ""),
        "requirements_digest": _hash_bytes(
            json.dumps(required, separators=(",", ":")).encode("utf-8")
        ),
        "runner_digest": _hash_bytes(Path(__file__).read_bytes()),
        "checks_required": required,
        "checks_executed": executed,
        "checks_passed": passed,
        "checks_failed": failed,
        "checks_not_proven": not_proven,
        "checks_incomplete": incomplete,
        "checks_skipped": [],
        "checks": checks,
        "ownership": _ownership_payload(ownership),
        "ruff_result": ruff,
        "pytest_result": pytest_result,
        "timeouts": [c["check_id"] for c in checks if c["outcome"] == OUTCOME_TIMEOUT],
        "internal_errors": sorted(set(internal_errors)),
        "research": research.strip(),
        "verdict": verdict,
        "exit_code": VERDICT_EXIT[verdict],
        "assurance_claims": [
            "TURN_CONTRACT_V1 required checks executed against the exact recorded subject",
            "no repository-wide or mission-specific correctness is implied",
        ],
    }
    result["result_identity"] = _hash_bytes(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return result


def _canonical_repo(repo: Path) -> str:
    value, error = _git_scalar(Path(repo).resolve(), ["rev-parse", "--show-toplevel"])
    return str(Path(value).resolve()) if not error else str(Path(repo).resolve())


def validate_result(
    result: Any,
    *,
    repo: Path,
    session_id: str,
    observed_exit_code: int | None,
    required_session_paths: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """Strictly validate one result against the subject as it exists now."""
    if not isinstance(result, dict):
        return ["malformed structured result: expected a JSON object"]
    errors: list[str] = []
    required_fields = {
        "schema_version", "contract_id", "audit_run_id", "session_id", "authoritative",
        "completed", "repo_root", "repo_head", "index_tree", "worktree_identity_start",
        "worktree_identity_end", "scope_digest", "checks_required", "checks_executed",
        "requirements_digest", "runner_digest", "result_identity", "checks", "verdict",
        "exit_code", "internal_errors", "session_required_files",
    }
    missing = sorted(required_fields - set(result))
    if missing:
        errors.append(f"malformed structured result: missing fields {missing}")
        return errors
    scalar_types = {
        "schema_version": int,
        "contract_id": str,
        "audit_run_id": str,
        "session_id": str,
        "authoritative": bool,
        "completed": bool,
        "repo_root": str,
        "repo_head": str,
        "index_tree": str,
        "worktree_identity_start": str,
        "worktree_identity_end": str,
        "scope_digest": str,
        "requirements_digest": str,
        "runner_digest": str,
        "result_identity": str,
        "verdict": str,
        "exit_code": int,
    }
    for key, expected_type in scalar_types.items():
        if not isinstance(result.get(key), expected_type):
            errors.append(
                f"malformed structured result: {key} must be {expected_type.__name__}"
            )
    list_fields = (
        "checks_required", "checks_executed", "checks", "checks_passed",
        "checks_failed", "checks_not_proven", "checks_incomplete",
        "checks_skipped", "internal_errors", "session_required_files",
    )
    for key in list_fields:
        if not isinstance(result.get(key), list):
            errors.append(f"malformed structured result: {key} must be list")
    if not isinstance(result.get("actual_scope"), dict):
        errors.append("malformed structured result: actual_scope must be object")
    if errors:
        return errors
    if result.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema version mismatch")
    if result.get("contract_id") != CONTRACT_ID:
        errors.append("contract id mismatch")
    identity_copy = dict(result)
    claimed_result_identity = identity_copy.pop("result_identity", "")
    actual_result_identity = _hash_bytes(
        json.dumps(identity_copy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if claimed_result_identity != actual_result_identity:
        errors.append("structured result identity mismatch")
    try:
        current_runner_digest = _hash_bytes(Path(__file__).read_bytes())
    except OSError:
        current_runner_digest = ""
    if result.get("runner_digest") != current_runner_digest:
        errors.append("audit runner identity mismatch")
    if not result.get("authoritative"):
        errors.append("result is not authoritative")
    if result.get("completed") is not True:
        errors.append("audit did not complete")
    if not session_id or result.get("session_id") != session_id:
        errors.append("session identity mismatch")
    if not str(result.get("audit_run_id") or ""):
        errors.append("audit run identity missing")

    expected_repo = _canonical_repo(repo)
    try:
        result_repo = str(Path(str(result.get("repo_root"))).resolve())
    except (OSError, ValueError):
        result_repo = ""
    if result_repo != expected_repo:
        errors.append(f"wrong repository/worktree result: {result_repo!r} != {expected_repo!r}")

    expected_session_paths = sorted({
        _norm(path) for path in required_session_paths or ()
    })
    if result.get("session_required_files") != expected_session_paths:
        errors.append("session-required file inventory mismatch")
    scope = discover_scope(repo, expected_session_paths)
    identity, identity_errors = capture_identity(repo, scope)
    errors.extend(identity_errors)
    expected_scope_payload = _scope_payload(scope)
    if result.get("actual_scope") != expected_scope_payload:
        errors.append("actual scope does not match independent current scope discovery")
    expected_tracked = sorted(e.path for e in scope.entries if e.tracked)
    if result.get("changed_tracked_files") != expected_tracked:
        errors.append("changed tracked-file inventory mismatch")
    expected_untracked_production = sorted(
        e.path for e in scope.production_entries if not e.tracked
    )
    if result.get("untracked_production_files") != expected_untracked_production:
        errors.append("untracked production-file inventory mismatch")
    for result_key, identity_key in (
        ("repo_head", "repo_head"),
        ("index_tree", "index_tree"),
        ("worktree_identity_end", "worktree_identity"),
        ("scope_digest", "scope_digest"),
    ):
        if result.get(result_key) != identity.get(identity_key):
            errors.append(f"current identity mismatch for {result_key}")
    if result.get("worktree_identity_start") != result.get("worktree_identity_end"):
        errors.append("worktree identity changed during audit")

    required = result.get("checks_required")
    executed = result.get("checks_executed")
    checks = result.get("checks")
    if not isinstance(required, list) or not isinstance(executed, list) \
            or not isinstance(checks, list):
        errors.append("required/executed/check records must be lists")
        return errors
    malformed_checks: list[str] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            malformed_checks.append(f"checks[{index}] must be object")
            continue
        if not isinstance(check.get("check_id"), str) or not check.get("check_id"):
            malformed_checks.append(f"checks[{index}].check_id must be non-empty string")
        if not isinstance(check.get("status"), str):
            malformed_checks.append(f"checks[{index}].status must be string")
    if malformed_checks:
        errors.extend(
            f"malformed structured result: {message}" for message in malformed_checks
        )
        return errors
    if len(required) != len(set(required)):
        errors.append("duplicate required check id")
    if len(executed) != len(set(executed)):
        errors.append("duplicate executed check id")
    expected_required = required_check_ids(Path(repo), scope)
    if required != expected_required:
        errors.append(
            f"required check set mismatch: result={required}, current={expected_required}"
        )
    expected_requirements_digest = _hash_bytes(
        json.dumps(expected_required, separators=(",", ":")).encode("utf-8")
    )
    if result.get("requirements_digest") != expected_requirements_digest:
        errors.append("required check-set identity mismatch")
    if required != executed:
        errors.append(f"required checks do not exactly equal executed checks: {required} != {executed}")
    check_ids = [c.get("check_id") for c in checks if isinstance(c, dict)]
    if check_ids != executed:
        errors.append("executed checks do not exactly equal structured check records")
    statuses = [c.get("status") for c in checks if isinstance(c, dict)]
    unknown_status = [status for status in statuses if status not in CHECK_STATUSES]
    if unknown_status:
        errors.append(f"unknown check status(es): {unknown_status}")
    expected_status_lists = {
        "checks_passed": [c.get("check_id") for c in checks if c.get("status") == STATUS_PASS],
        "checks_failed": [c.get("check_id") for c in checks if c.get("status") == STATUS_FAIL],
        "checks_not_proven": [
            c.get("check_id") for c in checks if c.get("status") == STATUS_NOT_PROVEN
        ],
        "checks_incomplete": [
            c.get("check_id") for c in checks if c.get("status") == STATUS_INCOMPLETE
        ],
    }
    for key, expected in expected_status_lists.items():
        if result.get(key) != expected:
            errors.append(f"{key} disagrees with typed check records")
    if result.get("checks_skipped"):
        errors.append("required check was skipped")

    stable = result.get("worktree_identity_start") == result.get("worktree_identity_end")
    has_prod = bool(scope.production_entries)
    expected_verdict = _aggregate_verdict(
        checks,
        has_production_change=has_prod,
        internal_errors=list(result.get("internal_errors") or []),
        stable=stable,
    )
    if result.get("verdict") != expected_verdict:
        errors.append(
            f"verdict/status disagreement: {result.get('verdict')!r} != {expected_verdict!r}"
        )
    expected_exit = VERDICT_EXIT.get(str(result.get("verdict")))
    if expected_exit is None or result.get("exit_code") != expected_exit:
        errors.append("result verdict and declared exit code disagree")
    if observed_exit_code is not None and observed_exit_code != result.get("exit_code"):
        errors.append(
            f"observed process exit {observed_exit_code} disagrees with result "
            f"{result.get('exit_code')}"
        )
    if result.get("verdict") == VERDICT_CLEAN:
        if any(status != STATUS_PASS for status in statuses):
            errors.append("CLEAN contains a required non-PASS check")
        if result.get("internal_errors"):
            errors.append("CLEAN contains internal errors")
    return errors


def changed_production_files() -> list[str]:
    """Compatibility API backed by canonical scope; scope failure is never hidden."""
    scope = discover_scope(REPO)
    if scope.status != STATUS_PASS:
        raise RuntimeError("; ".join(scope.errors))
    return sorted({entry.path for entry in scope.production_entries})


def matching_attack_suites(changed: list[str]) -> tuple[list[str], list[str]]:
    """Compatibility API using deterministic imports/metadata, not source substrings."""
    entries = [
        ScopeEntry("MODIFY", _norm(path)) for path in changed if is_production_path(path)
    ]
    scope = ScopeResult(status=STATUS_PASS, entries=entries, production_entries=entries)
    ownership = resolve_test_ownership(REPO, scope)
    uncovered = [Path(path).stem for path in ownership.unknown]
    return ownership.suites, sorted(uncovered)


def research_violation(research: str, changed: list[str]) -> str | None:
    """Legacy research telemetry validation; it is not Stop authorization."""
    if not changed:
        return None
    value = (research or "").strip()
    concrete = any(token in value for token in ("/", "§", "http", ".md", ".py", ".html", ".js"))
    if len(value) < 20 or not concrete:
        return (
            "no research record (RC-203/RC-205): name a concrete reference consulted "
            "before acting"
        )
    try:
        from tools.plus_player_locks import research_path_resolves
    except ImportError:
        from plus_player_locks import research_path_resolves  # type: ignore
    if not research_path_resolves(value):
        return "research does not resolve (RC-205): cite an existing repo path or http(s) URL"
    return None


def _incomplete_cli_result(repo: Path, session_id: str, message: str) -> dict[str, Any]:
    scope = discover_scope(repo)
    identity, _ = capture_identity(repo, scope)
    check = _check_record(
        "scope_integrity", STATUS_INCOMPLETE, started=time.time(),
        exit_code=None, outcome="protocol_error", detail=message,
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "audit_run_id": str(uuid.uuid4()),
        "session_id": session_id,
        "authoritative": True,
        "completed": True,
        "start_time": time.time(),
        "end_time": time.time(),
        "requested_scope": "REJECTED_CALLER_NARROWING",
        "session_required_files": [],
        "actual_scope": _scope_payload(scope),
        "changed_tracked_files": [],
        "untracked_production_files": [],
        "repo_root": identity.get("repo_root", str(Path(repo).resolve())),
        "repo_head": identity.get("repo_head", ""),
        "index_tree": identity.get("index_tree", ""),
        "worktree_identity_start": identity.get("worktree_identity", ""),
        "worktree_identity_end": identity.get("worktree_identity", ""),
        "scope_digest": identity.get("scope_digest", ""),
        "requirements_digest": _hash_bytes(
            json.dumps(["scope_integrity"], separators=(",", ":")).encode("utf-8")
        ),
        "runner_digest": _hash_bytes(Path(__file__).read_bytes()),
        "checks_required": ["scope_integrity"],
        "checks_executed": ["scope_integrity"],
        "checks_passed": [],
        "checks_failed": [],
        "checks_not_proven": [],
        "checks_incomplete": ["scope_integrity"],
        "checks_skipped": [],
        "checks": [check],
        "ownership": asdict(OwnershipResult(status=STATUS_INCOMPLETE)),
        "ruff_result": {"check_id": "ruff_changed", "status": "NOT_APPLICABLE"},
        "pytest_result": {"check_id": "owned_pytest", "status": "NOT_APPLICABLE"},
        "timeouts": [],
        "internal_errors": [message],
        "research": "",
        "verdict": VERDICT_INCOMPLETE,
        "exit_code": VERDICT_EXIT[VERDICT_INCOMPLETE],
        "assurance_claims": ["no assurance: caller attempted to narrow authoritative scope"],
    }
    result["result_identity"] = _hash_bytes(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return result


def _append_preview_telemetry(result: dict[str, Any]) -> None:
    try:
        path = REPO / LOG_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "ts_utc": time.time(),
                "changed": [e["path"] for e in result["actual_scope"]["production_entries"]],
                "research": result.get("research", ""),
                "verdict": result.get("verdict", "").lower(),
                "contract_id": CONTRACT_ID,
                "authoritative": False,
            }, sort_keys=True) + "\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="typed per-turn self audit (RC-330)")
    parser.add_argument("--authoritative", action="store_true")
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--session-id", default="")
    parser.add_argument("--research", default="")
    parser.add_argument(
        "--required-session-file",
        action="append",
        default=[],
        help="Stop-owned additive session scope; independently revalidated by the parent",
    )
    parser.add_argument("--files", default=None, help="REJECTED in v1: scope is mechanically derived")
    parser.add_argument("--tests", default=None, help="REJECTED in v1: ownership is mechanically derived")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if args.files is not None or args.tests is not None:
        result = _incomplete_cli_result(
            repo,
            args.session_id,
            "authoritative scope/test narrowing is rejected; --files/--tests cannot subtract proof",
        )
    elif args.authoritative and not args.session_id:
        result = _incomplete_cli_result(repo, "", "authoritative audit requires session identity")
    else:
        result = run_audit(
            repo,
            args.session_id or "PREVIEW",
            authoritative=args.authoritative,
            research=args.research,
            required_session_paths=args.required_session_file,
        )
    if not args.authoritative:
        _append_preview_telemetry(result)
    # RC-284/RC-368: the JSON ledger is the artefact; this stderr tail distinguishes the
    # three process outcomes for a human reader. A timeout or launch failure measured
    # NOTHING, so it can never read as a pass — each one fails the turn.
    fails: list[str] = []
    for check in result.get("checks", []):
        outcome = check.get("outcome")
        if outcome == OUTCOME_TIMEOUT:
            fails.append(
                f"{check.get('check_id')}: TIMED OUT after 1800s pytest budget — "
                f"NOTHING was measured, so the turn is not proven clean"
            )
        elif outcome == OUTCOME_LAUNCH_FAILURE:
            fails.append(
                f"{check.get('check_id')}: could not be LAUNCHED — NOTHING was measured"
            )
    for check, line in zip(
        [c for c in result.get("checks", [])
         if c.get("outcome") in (OUTCOME_TIMEOUT, OUTCOME_LAUNCH_FAILURE)],
        fails,
    ):
        outcome = check.get("outcome")
        step = {"check_id": check.get("check_id"), "outcome": outcome}
        sys.stderr.write(line + " " + json.dumps(step, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
