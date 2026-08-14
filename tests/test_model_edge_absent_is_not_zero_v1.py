"""RC-285 — a model that was never scored has not scored zero.

``_model_status_from_artifact`` published ``{"status": "LIVE", "edge": 0}``
when metadata omitted the edge metric. Literal ``"edge": 0`` on the
NOT TRAINED / BINARY MISSING / NON-COMPLIANT / ERROR branches made
measured-zero and unmeasured the same type.

Unmeasured edge is ``None``, never ``val_accuracy * 100`` mislabeled as edge.
The model-health row renders ``edge === null`` as ``—``.
"""

from __future__ import annotations

from pathlib import Path

from verify_active_models import model_health_edge_from_meta

REPO = Path(__file__).resolve().parent.parent

def functions_that_get_unrelated_literal_on_key_miss(src: str) -> list[str]:
    """Functions that look up a mapping by a name and on miss read another literal.

    The class is substituting field V when the caller asked for field K.
    Mapping may be a Name or Attribute. The requested key may be any Name.
    """
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    found: list[str] = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        key_args = {a.arg for a in (*fn.args.args, *fn.args.kwonlyargs)} - {"self", "cls"}
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


def _mapping_id(node) -> str | None:
    import ast

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _mapping_id(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _lookup_mapping_and_key(expr):
    """Return (mapping_id, key_node) for mapping.get(k) / mapping[k], else None."""
    import ast

    if _is_get_call(expr):
        mid = _mapping_id(expr.func.value)
        if mid:
            return mid, expr.args[0]
    if isinstance(expr, ast.Subscript):
        mid = _mapping_id(expr.value)
        if mid:
            return mid, expr.slice
    return None


def _unwrap_lookup(expr):
    looked = _lookup_mapping_and_key(expr)
    if looked:
        return looked
    import ast

    if isinstance(expr, ast.Call) and expr.args:
        return _lookup_mapping_and_key(expr.args[0])
    return None


def _key_kind(key_node, key_args: set[str]) -> str | None:
    import ast

    if isinstance(key_node, ast.Name) and key_node.id in key_args:
        return "name"
    if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
        return "literal"
    return None


def _returned_lookup(stmts: list):
    """If stmts is a single `return mapping[key]`, return that lookup."""
    import ast

    if len(stmts) != 1 or not isinstance(stmts[0], ast.Return) or stmts[0].value is None:
        return None
    return _unwrap_lookup(stmts[0].value)


def _is_none_test(test, name: str) -> bool:
    import ast

    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Is):
        return False
    if not (isinstance(test.left, ast.Name) and test.left.id == name):
        return False
    return (
        isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value is None
    )


def _body_has_literal_key_on(stmts: list, mapping: str) -> bool:
    import ast

    for stmt in stmts:
        for node in ast.walk(stmt):
            looked = _lookup_mapping_and_key(node)
            if looked is None:
                continue
            mid, key = looked
            if mid == mapping and isinstance(key, ast.Constant) and isinstance(key.value, str):
                return True
    return False


def _reads_unrelated_literal_on_key_miss(fn, key_args: set[str]) -> bool:
    import ast

    for node in ast.walk(fn):
        if not _is_get_call(node):
            continue
        first = node.args[0]
        inner = node.args[1] if len(node.args) >= 2 else None
        if not (
            isinstance(first, ast.Name)
            and first.id in key_args
            and _is_get_call(inner)
            and isinstance(inner.args[0], ast.Constant)
            and isinstance(inner.args[0].value, str)
        ):
            continue
        outer_id = _mapping_id(node.func.value)
        inner_id = _mapping_id(inner.func.value)
        if outer_id and outer_id == inner_id:
            return True
    for node in ast.walk(fn):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        gets = [v for v in node.values if _is_get_call(v)]
        if len(gets) < 2:
            continue
        bases = []
        uses_key = False
        has_lit = False
        for g in gets:
            bases.append(_mapping_id(g.func.value))
            first = g.args[0]
            if isinstance(first, ast.Name) and first.id in key_args:
                uses_key = True
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                has_lit = True
        if uses_key and has_lit and len(set(bases)) == 1 and bases[0] is not None:
            return True
    for node in ast.walk(fn):
        if isinstance(node, ast.IfExp):
            a = _unwrap_lookup(node.body)
            b = _unwrap_lookup(node.orelse)
            if a and b and a[0] == b[0]:
                if {_key_kind(a[1], key_args), _key_kind(b[1], key_args)} == {
                    "name",
                    "literal",
                }:
                    return True
        if not isinstance(node, ast.If):
            continue
        a = _returned_lookup(node.body)
        b = _returned_lookup(node.orelse)
        if a and b and a[0] == b[0]:
            if {_key_kind(a[1], key_args), _key_kind(b[1], key_args)} == {
                "name",
                "literal",
            }:
                return True
    for i, stmt in enumerate(fn.body):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            looked = _unwrap_lookup(stmt.value)
            if (
                isinstance(target, ast.Name)
                and looked
                and _key_kind(looked[1], key_args) == "name"
            ):
                for nxt in fn.body[i + 1 :]:
                    if not isinstance(nxt, ast.If):
                        continue
                    if _is_none_test(nxt.test, target.id) and _body_has_literal_key_on(
                        nxt.body, looked[0]
                    ):
                        return True
                    break
        if not isinstance(stmt, ast.If) or i + 1 >= len(fn.body):
            continue
        a = _returned_lookup(stmt.body)
        nxt = fn.body[i + 1]
        b = _returned_lookup([nxt])
        if a and b and a[0] == b[0]:
            if {_key_kind(a[1], key_args), _key_kind(b[1], key_args)} == {
                "name",
                "literal",
            }:
                return True
    return False


def test_no_write_site_fabricates_a_zero_edge():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    assert '"edge": 0' not in src


def test_the_metadata_read_has_no_zero_default():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    assert '_m.get(edge_key, _m.get("val_accuracy", 0))' not in src
    assert '_m.get(version_key, _m.get("model_version"' not in src
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
    """Defect-learning: substitute-on-miss fires without a `*_key` suffix."""
    plant = (
        "def published_from_blob(blob, requested):\n"
        "    if requested in blob:\n"
        "        return blob[requested]\n"
        "    return blob.get('train_accuracy')\n"
    )
    assert functions_that_get_unrelated_literal_on_key_miss(plant) == ["published_from_blob"]
    nested = (
        "def reading_from_meta(meta, field):\n"
        "    return meta.get(field, meta.get('train_accuracy', 0))\n"
    )
    assert functions_that_get_unrelated_literal_on_key_miss(nested) == ["reading_from_meta"]
    subscript = (
        "def published_via_subscript(blob, requested):\n"
        "    if requested in blob:\n"
        "        return blob[requested]\n"
        "    return blob['train_accuracy']\n"
    )
    assert functions_that_get_unrelated_literal_on_key_miss(subscript) == [
        "published_via_subscript"
    ]
    assign_none = (
        "def assign_then_none(meta, requested):\n"
        "    raw = meta.get(requested)\n"
        "    if raw is None:\n"
        "        return meta.get('val_accuracy')\n"
    )
    assert functions_that_get_unrelated_literal_on_key_miss(assign_none) == [
        "assign_then_none"
    ]
    attr_map = (
        "def reading_from_self(self, requested):\n"
        "    return self.meta.get(requested, self.meta.get('val_accuracy', 0))\n"
    )
    assert functions_that_get_unrelated_literal_on_key_miss(attr_map) == [
        "reading_from_self"
    ]
    ternary = (
        "def via_ternary(blob, requested):\n"
        "    return blob[requested] if requested in blob else blob['train_accuracy']\n"
    )
    assert functions_that_get_unrelated_literal_on_key_miss(ternary) == ["via_ternary"]


def test_repo_has_no_measurement_key_literal_fallback():
    """Class scan: any measurement `*_key` that `.get`s a different literal on miss."""
    import subprocess

    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
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
