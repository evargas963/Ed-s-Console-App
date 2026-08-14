"""RC-285 — a model that was never scored has not scored zero.

``_model_status_from_artifact`` published ``{"status": "LIVE", "edge": 0}``
when metadata omitted the edge metric. Literal ``"edge": 0`` on the
NOT TRAINED / BINARY MISSING / NON-COMPLIANT / ERROR branches made
measured-zero and unmeasured the same type.

Unmeasured edge is ``None``, never ``val_accuracy * 100`` mislabeled as edge.
The model-health row renders ``edge === null`` as ``—``.
"""

from __future__ import annotations

import re
from pathlib import Path

from verify_active_models import model_health_edge_from_meta

REPO = Path(__file__).resolve().parent.parent

_MEASUREMENT_KEY_RE = re.compile(
    r"(edge|score|metric|acc|accuracy|promotion)_key$"
)


def functions_that_get_unrelated_literal_on_key_miss(src: str) -> list[str]:
    """Functions that take a measurement `*_key` and on miss `.get` a different literal.

    The class is substituting metric V when the caller asked for metric K.
    Cite-scoped repair named `model_health_edge_from_meta`. A new `score_key`
    helper that falls back to `val_accuracy` is the same class.
    """
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    found: list[str] = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        key_args = {
            a.arg
            for a in (*fn.args.args, *fn.args.kwonlyargs)
            if _MEASUREMENT_KEY_RE.search(a.arg)
        }
        if not key_args:
            continue
        if _reads_unrelated_literal_on_key_miss(fn, key_args):
            found.append(fn.name)
    return found


def _is_get_call(node: object) -> bool:
    import ast

    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and bool(node.args)
    )


def _has_literal_get(nodes: list) -> bool:
    import ast

    for node in nodes:
        for child in ast.walk(node):
            if not _is_get_call(child):
                continue
            first = child.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return True
    return False


def _uses_key_as_lookup(nodes: list, key_args: set[str]) -> bool:
    import ast

    for node in nodes:
        for child in ast.walk(node):
            if _is_get_call(child) and isinstance(child.args[0], ast.Name) and child.args[0].id in key_args:
                return True
            if (
                isinstance(child, ast.Subscript)
                and isinstance(child.slice, ast.Name)
                and child.slice.id in key_args
            ):
                return True
    return False


def _reads_unrelated_literal_on_key_miss(fn, key_args: set[str]) -> bool:
    import ast

    for node in ast.walk(fn):
        if not _is_get_call(node):
            continue
        first = node.args[0]
        if (
            isinstance(first, ast.Name)
            and first.id in key_args
            and len(node.args) >= 2
            and _is_get_call(node.args[1])
            and isinstance(node.args[1].args[0], ast.Constant)
            and isinstance(node.args[1].args[0].value, str)
        ):
            return True
    for node in ast.walk(fn):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            uses_key = _uses_key_as_lookup(node.values, key_args)
            has_lit = _has_literal_get(node.values)
            if uses_key and has_lit:
                return True
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if _uses_key_as_lookup(node.body, key_args) and _has_literal_get(node.orelse):
            return True
        if _has_literal_get(node.body) and _uses_key_as_lookup(node.orelse, key_args):
            return True
    if _uses_key_as_lookup(fn.body, key_args) and _has_literal_get(fn.body):
        return True
    return False


def test_no_write_site_fabricates_a_zero_edge():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    assert '"edge": 0' not in src


def test_the_metadata_read_has_no_zero_default():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    assert '_m.get(edge_key, _m.get("val_accuracy", 0))' not in src
    assert "float(raw or 0)" not in src
    assert "model_health_edge_from_meta" in src


def test_absent_metric_reads_as_none_not_zero():
    assert model_health_edge_from_meta({"model_version": "v9"}, "edge_pp") is None


def test_a_real_metric_is_still_reported():
    assert model_health_edge_from_meta({"edge_pp": 3.5}, "edge_pp") == 3.5


def test_a_genuine_zero_edge_survives():
    assert model_health_edge_from_meta({"edge_pp": 0.0}, "edge_pp") == 0.0


def test_val_accuracy_is_still_scaled_to_percent():
    assert model_health_edge_from_meta({"val_accuracy": 0.62}, "val_accuracy") == 62.0


def test_absent_edge_pp_is_none_even_when_val_accuracy_is_present():
    """RC-285 bedrock: accuracy is not an edge. No fallback when edge_key is absent."""
    assert model_health_edge_from_meta({"val_accuracy": 0.55}, "edge_pp") is None


def test_edge_key_miss_class_flags_uncited_function():
    """Defect-learning: accuracy-as-edge fires on a helper the last audit did not name."""
    plant = (
        "def score_from_meta(meta, score_key):\n"
        "    if score_key and score_key in meta:\n"
        "        return meta[score_key]\n"
        "    return meta.get('val_accuracy')\n"
    )
    assert functions_that_get_unrelated_literal_on_key_miss(plant) == ["score_from_meta"]
    nested = (
        "def edge_from_blob(meta, edge_key):\n"
        "    return meta.get(edge_key, meta.get('val_accuracy', 0))\n"
    )
    assert functions_that_get_unrelated_literal_on_key_miss(nested) == ["edge_from_blob"]


def test_repo_has_no_measurement_key_literal_fallback():
    """Class scan: any measurement `*_key` that `.get`s a different literal on miss."""
    import subprocess

    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    skip = ("tests/", "tools/", "research/", "governance/", "arch_competition/")
    offenders: list[str] = []
    for rel in [p for p in proc.stdout.split("\0") if p]:
        if rel.startswith(skip):
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for name in functions_that_get_unrelated_literal_on_key_miss(text):
            offenders.append(f"{rel}:{name}")
    assert offenders == []


def test_model_health_edge_null_renders_em_dash():
    """DOM contract: formatModelHealthEdge(null) is — , not 0 / NaN / throw."""
    import re
    import subprocess

    ui = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    i = ui.find("d.model_health")
    assert i > 0
    block = ui[i : i + 1800]
    assert "m.edge" in block
    assert "formatModelHealthEdge" in block
    match = re.search(
        r"function formatModelHealthEdge\(edge\) \{.*?\n  \}",
        ui,
        flags=re.S,
    )
    assert match, "formatModelHealthEdge must be extractable from index.html"
    fn = match.group(0)
    script = (
        fn
        + "\n"
        + "const fail = (m) => { console.error(m); process.exit(1); };\n"
        + "if (formatModelHealthEdge(null) !== '—') fail('null');\n"
        + "if (formatModelHealthEdge(undefined) !== '—') fail('undefined');\n"
        + "if (formatModelHealthEdge(Number.NaN) !== '—') fail('NaN');\n"
        + "if (formatModelHealthEdge(0) !== '0') fail('genuine zero');\n"
        + "if (formatModelHealthEdge(3.5) !== '3.5') fail('value');\n"
        + "console.log('ok');\n"
    )
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "ok" in proc.stdout
