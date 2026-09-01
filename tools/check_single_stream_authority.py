#!/usr/bin/env python3
"""SINGLE-STREAM-AUTHORITY — exactly one production Schwab StreamClient constructor.

OPERATOR MANDATE (2026-08-30): "PRODUCTION_SCHWAB_STREAMCLIENT_CONSTRUCTORS = exactly 1
or STOP with exact remaining violations." order_flow_streaming.py used to open a second,
independent `schwab.streaming.StreamClient` at server startup — racing the canonical
capture daemon's own session for the same account's market truth. The repair retired that
socket; this gate is the MUTATION-TESTABLE proof it stays retired, not a one-time cleanup
that could silently regress on the next PR that "just needs a quick stream for X".

WHAT IS COUNTED. A `StreamClient(...)` call, traced through actual `import` statements in
the SAME file — not a substring match on the word "StreamClient", which a docstring
explaining this very repair would trip (measured: order_flow_streaming.py's own comment
mentions the class by name). Only calls resolvable to `schwab.streaming.StreamClient`
count; an unrelated class of the same name in an unrelated module does not.

CLASSIFICATION, one of:
    PRODUCTION_OWNER   tools/run_stream_capture.py — the canonical capture daemon.
    OFFLINE_TOOL       schwab_full_field_inventory.py — manual field-discovery CLI, only
                       reachable via `if __name__ == "__main__"`, never imported by any
                       automated path (verified 2026-08-30: its one production import,
                       tools/sync_schwab_field_dictionary.py, pulls a pure JSON-flattening
                       helper, never the streaming function).
    TEST_ONLY          anything under tests/ — isolated by convention, never live Schwab.
    VIOLATION          anything else. A single VIOLATION fails the gate.

    .venv/Scripts/python.exe tools/check_single_stream_authority.py
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: `git ls-files` always yields forward-slash paths regardless of OS — compare against
#: that literally, never a Path-joined (backslash-on-Windows) string.
PRODUCTION_OWNER = "tools/run_stream_capture.py"
OFFLINE_TOOLS = {"schwab_full_field_inventory.py"}


def _tracked_python() -> list[str]:
    proc = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed, so the scan scope is unknown: "
                           + proc.stderr.strip()[:160])
    return [p for p in proc.stdout.split("\0") if p]


def _stream_client_local_names(tree: ast.Module) -> set[str]:
    """Names in THIS file's scope that resolve to schwab.streaming.StreamClient — via
    `from schwab.streaming import StreamClient` (optionally `as X`) or
    `import schwab.streaming as m` (then `m.StreamClient(...)`, tracked separately)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "schwab.streaming":
            for alias in node.names:
                if alias.name == "StreamClient":
                    names.add(alias.asname or alias.name)
    return names


def _module_aliases_for_schwab_streaming(tree: ast.Module) -> set[str]:
    """Names bound DIRECTLY to the `schwab.streaming` MODULE, for single-attribute
    `m.StreamClient(...)` calls — `import schwab.streaming as m` (an explicit alias,
    which binds exactly `m` to the submodule), and `from schwab import streaming` /
    `from schwab import streaming as s` (ADVERSARIAL RECHECK 2026-08-30: this second
    form was a real, if unexploited, blind spot — only `ast.Import` nodes were
    inspected, so `from schwab import streaming as s` followed by `s.StreamClient(...)`
    anywhere outside the canonical daemon would have gone undetected and silently
    PASSED the gate). A BARE `import schwab.streaming` (no `as`) does NOT belong here —
    Python binds the top-level name `schwab`, not `schwab.streaming`, so the correct
    call shape is the double-attribute `schwab.streaming.StreamClient(...)`, handled by
    `_package_aliases_for_schwab` below."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "schwab.streaming" and alias.asname:
                    aliases.add(alias.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == "schwab":
            for alias in node.names:
                if alias.name == "streaming":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _package_aliases_for_schwab(tree: ast.Module) -> set[str]:
    """Names bound to the TOP-LEVEL `schwab` PACKAGE, for double-attribute
    `X.streaming.StreamClient(...)` calls -- covers a bare `import schwab` (optionally
    `as X`) AND a bare `import schwab.streaming` with no `as` (Python binds `schwab`,
    not `schwab.streaming`, so `schwab.streaming.StreamClient(...)` is the correct and
    only valid call shape for that unaliased form).

    TEST_SYSTEM_REHAB_V2 (2026-08-31, Cursor-confirmed hole): a bare `import schwab`
    followed by `schwab.streaming.StreamClient(...)` was NOT detected at all -- this
    function did not exist, and the call-site loop below only matched single-level
    attribute access, which a double-attribute chain like `schwab.streaming.X` can
    never satisfy even if `schwab` had been tracked."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.name == "schwab":
                aliases.add(alias.asname or "schwab")
            elif alias.name == "schwab.streaming" and not alias.asname:
                aliases.add("schwab")
    return aliases


def find_stream_client_constructions(path: Path) -> list[int]:
    """Line numbers of every `StreamClient(...)` call in `path` that resolves to
    schwab.streaming.StreamClient via an actual import in the same file."""
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return []

    direct_names = _stream_client_local_names(tree)
    module_aliases = _module_aliases_for_schwab_streaming(tree)
    package_aliases = _package_aliases_for_schwab(tree)
    if not direct_names and not module_aliases and not package_aliases:
        return []

    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in direct_names:
            lines.append(node.lineno)
        elif (isinstance(fn, ast.Attribute) and fn.attr == "StreamClient"
              and isinstance(fn.value, ast.Name) and fn.value.id in module_aliases):
            lines.append(node.lineno)
        elif (isinstance(fn, ast.Attribute) and fn.attr == "StreamClient"
              and isinstance(fn.value, ast.Attribute) and fn.value.attr == "streaming"
              and isinstance(fn.value.value, ast.Name) and fn.value.value.id in package_aliases):
            # X.streaming.StreamClient(...) where X resolves to the top-level `schwab`
            # package -- the bare `import schwab` / bare `import schwab.streaming` hole.
            lines.append(node.lineno)
    return lines


def classify(rel_path: str) -> str:
    if rel_path == PRODUCTION_OWNER:
        return "PRODUCTION_OWNER"
    if rel_path in OFFLINE_TOOLS:
        return "OFFLINE_TOOL"
    if rel_path.startswith("tests/") or rel_path.startswith("tests\\"):
        return "TEST_ONLY"
    return "VIOLATION"


def run_census() -> dict[str, list[str]]:
    """{classification: [file:line, ...]} for every StreamClient constructor found."""
    out: dict[str, list[str]] = {
        "PRODUCTION_OWNER": [], "OFFLINE_TOOL": [], "TEST_ONLY": [], "VIOLATION": [],
    }
    for rel in _tracked_python():
        lines = find_stream_client_constructions(REPO / rel)
        if not lines:
            continue
        cls = classify(rel)
        for ln in lines:
            out[cls].append(f"{rel}:{ln}")
    return out


def violations() -> list[str]:
    """Human-readable violation messages, for wiring into check_institutional_correctness.py
    (same shape as check_one_producer.violations)."""
    census = run_census()
    out: list[str] = []
    n_owner = len(census["PRODUCTION_OWNER"])
    if n_owner != 1:
        out.append(f"PRODUCTION_SCHWAB_STREAMCLIENT_CONSTRUCTORS = {n_owner}, expected "
                   f"exactly 1 ({PRODUCTION_OWNER}); owners found: {census['PRODUCTION_OWNER']}")
    for v in census["VIOLATION"]:
        out.append(f"unauthorized Schwab StreamClient constructor at {v} — single-stream-"
                   f"authority law: only {PRODUCTION_OWNER} may open a Schwab streaming session")
    return out


def main() -> int:
    census = run_census()
    n_owner = len(census["PRODUCTION_OWNER"])
    violations = census["VIOLATION"]

    print("SINGLE-STREAM-AUTHORITY CENSUS")
    for cls in ("PRODUCTION_OWNER", "OFFLINE_TOOL", "TEST_ONLY", "VIOLATION"):
        for site in census[cls]:
            print(f"  {cls:18s} {site}")

    if n_owner != 1:
        print(f"FAIL: PRODUCTION_SCHWAB_STREAMCLIENT_CONSTRUCTORS = {n_owner}, expected exactly 1 "
              f"({PRODUCTION_OWNER})")
        return 1
    if violations:
        print(f"FAIL: {len(violations)} unauthorized StreamClient constructor(s):")
        for v in violations:
            print(f"  VIOLATION {v}")
        return 1

    print(f"PASS: PRODUCTION_SCHWAB_STREAMCLIENT_CONSTRUCTORS = 1 ({PRODUCTION_OWNER}); "
          f"0 violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
