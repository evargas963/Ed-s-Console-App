"""Dead / weak test surface audit (exact counts + classified presence locks).

Not a delete list. Classifies living tests so landfill and theater stay visible:

  ARCHIVE     — under tests/archive/ (not a living suite)
  SKIP_DECOR  — @pytest.mark.skip / skipif / unittest.skip on the test
  SKIP_CALL   — pytest.skip( / unittest.skip in the test body (or module)
  PRESENCE    — asserts a string is in source text; weak if that is the only contract
  ASSERT_FREE — no assert/raises/fail mechanism (mirrors institutional check shape)

  python -m tools.dead_tests_audit_v1
  python -m tools.dead_tests_audit_v1 --json reports/dead_tests_audit_v1.json
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"

_PRESENCE_ASSERT = re.compile(
    r"""assert\s+(?:[fF]?[\"'][^\"']+[\"']|[\"'][^\"']+[\"'])\s+in\s+(\w+)"""
)
_SKIP_DECO = re.compile(r"""(?:pytest\.mark\.(?:skip|skipif)|unittest\.skip)""")
_SKIP_CALL = re.compile(r"""(?:pytest\.skip\s*\(|unittest\.skip\s*\()""")


def _is_test_func(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
        "test_"
    )


def _failure_mechanism(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Raise):
            return True
        if isinstance(n, ast.Assert):
            return True
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr in (
                "raises", "fail", "warns", "approx",
            ):
                return True
            if isinstance(f, ast.Attribute) and f.attr.startswith("assert"):
                return True
            if isinstance(f, ast.Name) and f.id.startswith("assert"):
                return True
        if isinstance(n, ast.With):
            for item in n.items:
                if isinstance(item.context_expr, ast.Call):
                    f = item.context_expr.func
                    if isinstance(f, ast.Attribute) and f.attr in ("raises", "warns"):
                        return True
    return False


def _deco_text(src: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    parts = []
    for d in node.decorator_list:
        seg = ast.get_source_segment(src, d)
        if seg:
            parts.append(seg)
    return "\n".join(parts)


def _presence_vars(body: str) -> list[str]:
    return list(dict.fromkeys(_PRESENCE_ASSERT.findall(body)))


def _looks_like_source_blob(body: str, var: str) -> bool:
    """True when `var` is bound from reading a text file / Path / CONSOLE constant."""
    # Common patterns in this repo's source-lock tests.
    patterns = [
        rf"{var}\s*=\s*.*read_text\s*\(",
        rf"{var}\s*=\s*.*\.read\s*\(",
        rf"{var}\s*=\s*.*Path\s*\(",
        rf"{var}\s*=\s*CONSOLE",
        rf"{var}\s*=\s*.*\.read_text",
        rf"read_text\([^\)]*\).*{var}",
    ]
    if any(re.search(p, body, re.S) for p in patterns):
        return True
    # Module-level CONSOLE / SRC constants used inside the function
    if var in ("src", "text", "html", "body", "code", "source") and (
        "read_text" in body or "CONSOLE" in body or "Path(" in body
    ):
        return True
    return False


_BORING_CALLS = frozenset(
    {
        "Path",
        "open",
        "print",
        "len",
        "str",
        "int",
        "float",
        "list",
        "dict",
        "set",
        "tuple",
        "range",
        "enumerate",
        "zip",
        "sorted",
        "isinstance",
        "hasattr",
        "getattr",
        "setattr",
        "repr",
        "type",
        "any",
        "all",
        "min",
        "max",
        "sum",
        "abs",
        "round",
        "format",
        "join",
        "search",
        "sub",
        "compile",
        "match",
        "findall",
        "read_text",
        "write_text",
        "read_bytes",
        "write_bytes",
        "exists",
        "resolve",
        "relative_to",
        "as_posix",
        "mkdir",
        "parent",
        "loads",
        "dumps",
        "load",
        "dump",
        "pytest",
        "raises",
        "fail",
        "warns",
        "mark",
        "fixture",
        "param",
        "approx",
        "skip",
        "xfail",
        "Warning",
        "Exception",
        "ValueError",
        "TypeError",
        "RuntimeError",
        "AssertionError",
        "KeyError",
        "OSError",
        "FileNotFoundError",
        "bytes",
        "bytearray",
        "frozenset",
        "bool",
        "complex",
        "object",
        "super",
        "property",
        "staticmethod",
        "classmethod",
        "vars",
        "dir",
        "id",
        "hex",
        "bin",
        "oct",
        "chr",
        "ord",
        "ascii",
        "iter",
        "next",
        "map",
        "filter",
        "reversed",
        "slice",
        "memoryview",
        "hash",
        "callable",
        "issubclass",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "eval",
        "exec",
        "input",
        "help",
        "exit",
        "quit",
    }
)


def _call_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _has_runtime_call(node: ast.FunctionDef | ast.AsyncFunctionDef, body: str) -> bool:
    """True when the test invokes something beyond IO / assert helpers."""
    if re.search(r"\b(?:importlib\.import_module|__import__)\s*\(", body):
        return True
    if re.search(r"\b(?:client|app|TestClient)\b", body):
        return True
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        name = _call_name(n)
        if name is None:
            return True
        if name in _BORING_CALLS or name.startswith("assert"):
            continue
        return True
    return False


def classify_test(src: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    body = ast.get_source_segment(src, node) or ""
    deco = _deco_text(src, node)
    skip_decorated = bool(_SKIP_DECO.search(deco))
    skip_call = bool(_SKIP_CALL.search(body))
    assert_free = not _failure_mechanism(node)
    pvars = _presence_vars(body)
    presence_on_source = [v for v in pvars if _looks_like_source_blob(body, v)]
    runtime = _has_runtime_call(node, body)
    if presence_on_source and not runtime and body.count("assert") <= 4:
        presence_class = "PRESENCE_ONLY"
    elif presence_on_source and runtime:
        presence_class = "PRESENCE_AND_RUNTIME"
    elif pvars:
        presence_class = "PRESENCE_OTHER"
    else:
        presence_class = "NONE"
    return {
        "name": node.name,
        "line": node.lineno,
        "skip_decorated": skip_decorated,
        "skip_call": skip_call,
        "assert_free": assert_free,
        "presence_class": presence_class,
        "presence_vars": presence_on_source or pvars,
    }


def scan() -> dict:
    archive_files: list[str] = []
    archive_tests: list[dict] = []
    live_tests: list[dict] = []
    for p in sorted(TESTS.rglob("test_*.py")):
        rel = p.relative_to(REPO).as_posix()
        try:
            src = p.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(p))
        except (OSError, SyntaxError):
            continue
        is_arch = "archive" in p.relative_to(TESTS).parts
        if is_arch:
            archive_files.append(rel)
        for node in ast.walk(tree):
            if not _is_test_func(node):
                continue
            row = classify_test(src, node)
            row["file"] = rel
            if is_arch:
                archive_tests.append(row)
            else:
                live_tests.append(row)

    presence_only = [t for t in live_tests if t["presence_class"] == "PRESENCE_ONLY"]
    presence_mixed = [t for t in live_tests if t["presence_class"] == "PRESENCE_AND_RUNTIME"]
    assert_free = [t for t in live_tests if t["assert_free"]]
    skip_decor = [t for t in live_tests if t["skip_decorated"]]
    skip_call = [t for t in live_tests if t["skip_call"]]

    return {
        "schema": "dead_tests_audit_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "live_test_functions": len(live_tests),
            "archive_test_functions": len(archive_tests),
            "archive_files": len(set(archive_files)),
            "skip_decorated": len(skip_decor),
            "skip_call_in_body": len(skip_call),
            "assert_free": len(assert_free),
            "presence_only": len(presence_only),
            "presence_and_runtime": len(presence_mixed),
        },
        "note": (
            "presence_only = APPROX classifier (source-substring contract, little/no runtime). "
            "Not an automatic delete list. archive_* are landfill relative to the living suite."
        ),
        "archive_files": sorted(set(archive_files)),
        "skip_decorated": [
            {"file": t["file"], "name": t["name"], "line": t["line"]} for t in skip_decor
        ],
        "assert_free": [
            {"file": t["file"], "name": t["name"], "line": t["line"]} for t in assert_free
        ],
        "presence_only": [
            {
                "file": t["file"],
                "name": t["name"],
                "line": t["line"],
                "vars": t["presence_vars"],
            }
            for t in presence_only
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--json",
        nargs="?",
        const=str(REPO / "reports" / "dead_tests_audit_v1.json"),
        default=None,
        help="Write JSON report (default path if flag present with no value)",
    )
    args = ap.parse_args(argv)
    rep = scan()
    c = rep["counts"]
    print(
        f"live={c['live_test_functions']} archive={c['archive_test_functions']} "
        f"skip_deco={c['skip_decorated']} skip_call={c['skip_call_in_body']} "
        f"assert_free={c['assert_free']} presence_only={c['presence_only']} "
        f"presence+runtime={c['presence_and_runtime']}"
    )
    print(rep["note"])
    if args.json:
        out = Path(args.json)
        if not out.is_absolute():
            out = REPO / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
