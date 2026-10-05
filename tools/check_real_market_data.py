"""REAL-DATA (operator 2026-10-04): a test feeds the code what Schwab sent, never typed or generated values.

A pull request's test files are compared unit by unit with the base; only what the PR adds or
changes is judged.

Python (tests/**/*.py; a unit is a top-level function, a method of a top-level class, or a
module-level statement). A unit is refused when it gives a market field a value that is a numeric
literal, arithmetic involving one, a loop or comprehension variable over range()/enumerate()/a
literal list, or a name bound to any of those. Market fields are computed: every key that holds a
number somewhere inside a captured fixture's data under tests/fixtures/ (below the file's
top-level wrapper, whose own keys are capture metadata). The places judged: a dict literal's key,
a keyword argument, an item or attribute assignment, a parameter default, a
pytest.mark.parametrize argument, and the positional values of an SQL "INSERT INTO" passed to
execute()/executemany() (columns from the statement, or from a CREATE TABLE in the same file).
Numbers inside an `assert` are expected values and pass, except what the assert passes into a
call (other than pytest.approx). A changed unit that uses a unit of its file, or a conftest.py
fixture, which feeds such values is refused too.

JavaScript (tests/e2e/*.spec.js; a unit is a test(...) or test.beforeEach/afterEach/... call, or a
function/const/let/var declaration outside a test). A token scanner (strings, template
literals, comments and regex literals are told apart; it does not parse JavaScript) finds the
units that serve a browser route (`.route(` or `.fulfill(`) and the units that build market values
inline: a market field followed by `:` whose value holds a numeric literal (an index such as
`[0]` is not a value), the same inside a JSON string literal, or a .json file loaded from outside
tests/fixtures/. A changed unit is refused when a route it reaches (itself, or a unit it names, to
any depth) serves such a unit, or when it is such a unit and a route reaches it.

Limits: a value passed by position to an ordinary function, a value built by a call this check
does not know (anything but float/int/round/abs/min/max/sum/Decimal/datetime/date/timedelta and
methods on their results), a key built at run time, and a payload built inside a helper module
(tests/e2e/fixtures/*.js) are not seen. Only market fields present in the captured fixtures are
known; a payload of server-computed fields (e.g. gex) is judged only by its Schwab fields.

    python tools/check_real_market_data.py --base origin/main
Exit 0: nothing the PR adds or changes feeds typed or generated market values. Exit 1: refused,
each offender named with file:line and reason. Exit 2: the check itself failed.
"""
from __future__ import annotations

import argparse
import ast
import json
import posixpath
import re
import sys
from pathlib import Path

from check_no_new_patches import ToolError, _dotted, _git, _source

FIXTURES = "tests/fixtures/"
LITERAL_CALLS = {"float", "int", "round", "abs", "min", "max", "sum", "Decimal", "datetime", "date",
                 "timedelta", "datetime.datetime", "datetime.date", "datetime.timedelta"}
GENERATORS = {"range", "np.arange", "numpy.arange", "np.linspace", "numpy.linspace", "itertools.count",
              "count"}
APPROX = {"approx", "pytest.approx"}
INSERT = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)\s*(?:\(([^)]*)\))?\s*VALUES", re.I)
CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\(([^;]*)\)", re.I | re.S)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def market_fields(root: Path) -> set[str]:
    """Every key holding a number below the top level of a captured fixture under tests/fixtures/."""
    found: set[str] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if _is_number(v):
                    found.add(k)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    files = sorted((root / FIXTURES).rglob("*.json"))
    if not files:
        raise ToolError(f"no captured fixtures under {FIXTURES}: the market fields cannot be computed")
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        for v in (data.values() if isinstance(data, dict) else [data]):
            walk(v)
    return found


# ------------------------------------------------------------------------------------- Python

def python_units(src: str) -> dict[str, ast.AST]:
    """Top-level functions, methods of top-level classes (Class.method) and module statements."""
    out: dict[str, ast.AST] = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = sub
        elif not isinstance(node, (ast.Import, ast.ImportFrom, ast.Expr)):
            targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            out[names[0] if names else f"<module line {node.lineno}>"] = node
    return out


def changed_names(units: dict[str, ast.AST], old_src: str | None) -> set[str]:
    old = {n: ast.dump(u) for n, u in python_units(old_src).items()} if old_src else {}
    return {n for n, u in units.items() if old.get(n) != ast.dump(u)}


def references(unit: ast.AST) -> set[str]:
    names = {n.id for n in ast.walk(unit) if isinstance(n, ast.Name)}
    if isinstance(unit, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names |= {a.arg for a in unit.args.args + unit.args.kwonlyargs}
    return names


def is_fixture(unit: ast.AST) -> bool:
    return isinstance(unit, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        _dotted(d.func if isinstance(d, ast.Call) else d) in ("pytest.fixture", "fixture")
        for d in unit.decorator_list)


class _Feeds:
    """The market values one unit types or generates: [(line, field, how)]."""

    def __init__(self, unit: ast.AST, fields: set[str], literal_names: set[str], tables: dict[str, list[str]]):
        self.fields, self.tables, self.found = fields, tables, []
        self.generated = self._generated(unit)
        self.literal = set(literal_names)
        assigns = [n for n in ast.walk(unit) if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign))]
        while True:
            more = {t.id for a in assigns if a.value is not None and self.typed(a.value)
                    for t in (a.targets if isinstance(a, ast.Assign) else [a.target])
                    if isinstance(t, ast.Name)} - self.literal
            if not more:
                break
            self.literal |= more
        self._visit(unit, exempt=False)

    @staticmethod
    def _generated(unit: ast.AST) -> set[str]:
        out: set[str] = set()
        loops = [(n.target, n.iter) for n in ast.walk(unit) if isinstance(n, (ast.For, ast.AsyncFor))]
        loops += [(n.target, n.iter) for n in ast.walk(unit) if isinstance(n, ast.comprehension)]
        for target, it in loops:
            if isinstance(it, ast.Call) and _dotted(it.func) == "enumerate" and isinstance(target, ast.Tuple):
                target = target.elts[0]
            elif not ((isinstance(it, ast.Call) and _dotted(it.func) in GENERATORS) or (
                    isinstance(it, (ast.List, ast.Tuple, ast.Set))
                    and any(isinstance(e, ast.Constant) and _is_number(e.value) for e in ast.walk(it)))):
                continue
            out |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        return out

    def typed(self, e: ast.AST) -> bool:
        if isinstance(e, ast.Constant):
            return _is_number(e.value)
        if isinstance(e, ast.Name):
            return e.id in self.generated or e.id in self.literal
        if isinstance(e, ast.UnaryOp):
            return self.typed(e.operand)
        if isinstance(e, ast.BinOp):
            return self.typed(e.left) or self.typed(e.right)
        if isinstance(e, ast.IfExp):
            return self.typed(e.body) or self.typed(e.orelse)
        if isinstance(e, (ast.List, ast.Tuple, ast.Set)):
            return any(self.typed(x) for x in e.elts)
        if isinstance(e, ast.Call):
            if isinstance(e.func, ast.Attribute) and self.typed(e.func.value):
                return True
            return _dotted(e.func) in LITERAL_CALLS and any(
                self.typed(a) for a in [*e.args, *(k.value for k in e.keywords)])
        return False

    def _hit(self, node: ast.AST, field, value: ast.AST, how: str) -> None:
        if isinstance(field, str) and field in self.fields and self.typed(value):
            self.found.append((getattr(value, "lineno", getattr(node, "lineno", 0)), field, how))

    def _visit(self, node: ast.AST, exempt: bool) -> None:
        if isinstance(node, ast.Assert):
            exempt = True
        if not exempt:
            self._judge(node)
        if isinstance(node, ast.Call) and _dotted(node.func) not in APPROX:
            self._visit(node.func, exempt)
            for a in [*node.args, *node.keywords]:
                self._visit(a, False)
            return
        for child in ast.iter_child_nodes(node):
            self._visit(child, exempt)

    def _judge(self, node: ast.AST) -> None:
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant):
                    self._hit(node, k.value, v, "dict value")
        elif isinstance(node, ast.Call):
            for k in node.keywords:
                self._hit(node, k.arg, k.value, "keyword argument")
            self._sql(node)
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant):
                    self._hit(node, t.slice.value, node.value, "item assignment")
                elif isinstance(t, ast.Attribute):
                    self._hit(node, t.attr, node.value, "attribute assignment")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pos = node.args.posonlyargs + node.args.args
            for a, d in zip(pos[len(pos) - len(node.args.defaults):], node.args.defaults):
                self._hit(node, a.arg, d, "parameter default")
            for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults):
                if d is not None:
                    self._hit(node, a.arg, d, "parameter default")
            for dec in node.decorator_list:
                self._parametrize(dec)

    def _parametrize(self, dec: ast.AST) -> None:
        if not (isinstance(dec, ast.Call) and _dotted(dec.func).endswith("parametrize") and len(dec.args) >= 2):
            return
        names, values = dec.args[0], dec.args[1]
        if isinstance(names, ast.Constant) and isinstance(names.value, str):
            cols = [c.strip() for c in names.value.split(",") if c.strip()]
        elif isinstance(names, (ast.List, ast.Tuple)):
            cols = [c.value for c in names.elts if isinstance(c, ast.Constant)]
        else:
            return
        if not isinstance(values, (ast.List, ast.Tuple)):
            return
        for row in values.elts:
            if isinstance(row, ast.Call) and _dotted(row.func).endswith("param"):
                items = row.args
            else:
                items = row.elts if len(cols) > 1 and isinstance(row, (ast.Tuple, ast.List)) else [row]
            for col, v in zip(cols, items):
                self._hit(dec, col, v, "parametrize value")

    def _sql(self, call: ast.Call) -> None:
        verb = call.func.attr if isinstance(call.func, ast.Attribute) else ""
        if verb not in ("execute", "executemany") or len(call.args) < 2:
            return
        sql = call.args[0]
        m = INSERT.search(sql.value) if isinstance(sql, ast.Constant) and isinstance(sql.value, str) else None
        if not m:
            return
        cols = [c.strip() for c in m.group(2).split(",")] if m.group(2) else self.tables.get(m.group(1).lower(), [])
        params = call.args[1]
        rows = [params]
        if verb == "executemany":
            if isinstance(params, (ast.ListComp, ast.GeneratorExp)):
                rows = [params.elt]
            elif isinstance(params, (ast.List, ast.Tuple)):
                rows = params.elts
        for row in rows:
            if isinstance(row, (ast.Tuple, ast.List)):
                for col, v in zip(cols, row.elts):
                    self._hit(call, col, v, f"INSERT INTO {m.group(1)} value")


def sql_tables(src: str) -> dict[str, list[str]]:
    """Columns of every CREATE TABLE written in the file's string literals."""
    out = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for m in CREATE.finditer(node.value):
                out[m.group(1).lower()] = [c.split()[0] for c in m.group(2).split(",") if c.split()]
    return out


def module_literals(units: dict[str, ast.AST]) -> set[str]:
    """Module-level names bound to typed numbers (SPOT = 100.0), to a fixed point."""
    out: set[str] = set()
    while True:
        probe = _Feeds(ast.Module(body=[], type_ignores=[]), set(), out, {})
        more = {n for n, u in units.items() if isinstance(u, (ast.Assign, ast.AnnAssign))
                and u.value is not None and probe.typed(u.value)} - out
        if not more:
            return out
        out |= more


def feeding(src: str, fields: set[str]) -> dict[str, list[tuple[int, str, str]]]:
    """For each unit of one test file, the market values it types or generates."""
    units = python_units(src)
    literal, tables = module_literals(units), sql_tables(src)
    return {n: f.found for n, u in units.items() if (f := _Feeds(u, fields, literal, tables)).found}


def _conftest_feeding(root: Path, fields: set[str]) -> set[str]:
    out: set[str] = set()
    for path in _git(root, "ls-tree", "-r", "--name-only", "HEAD", "tests").splitlines():
        if path.endswith("conftest.py") and (src := _source(root, "HEAD", path)):
            units = python_units(src)
            out |= {n for n in feeding(src, fields) if is_fixture(units[n])}
    return out


def _used(units: dict[str, ast.AST], start: str, bad: set[str]) -> list[str]:
    """Same-file units `start` reaches by name, to any depth, that are in `bad`."""
    seen, todo = {start}, [start]
    while todo:
        for ref in references(units[todo.pop()]):
            if ref in units and ref not in seen:
                seen.add(ref)
                todo.append(ref)
    return sorted((seen - {start}) & bad)


def python_violations(root: Path, base: str, paths: list[str], fields: set[str]) -> list[str]:
    shared = _conftest_feeding(root, fields) if paths else set()
    out = []
    for path in paths:
        head = _source(root, "HEAD", path)
        if head is None:
            continue
        units = python_units(head)
        feeds = feeding(head, fields)
        for name in sorted(changed_names(units, _source(root, base, path)), key=lambda n: units[n].lineno):
            if found := feeds.get(name):
                what = "; ".join(f"line {line}: '{field}' ({how})" for line, field, how in found)
                out.append(f"{path}:{found[0][0]} {name}: market fields given typed or generated numbers: {what}")
            for dep in _used(units, name, set(feeds)):
                out.append(f"{path}:{units[name].lineno} {name}: uses {dep}, which types or generates market "
                           f"values (line {feeds[dep][0][0]}, '{feeds[dep][0][1]}')")
            for fx in sorted(references(units[name]) & shared - set(units)):
                out.append(f"{path}:{units[name].lineno} {name}: uses the conftest fixture {fx}, which types or "
                           f"generates market values")
    return out


# --------------------------------------------------------------------------------- JavaScript

NUMBER = re.compile(r"(?<![\w$.])[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?\b")
INDEX = re.compile(r"[\w$\])]\s*\[[^\[\]]*\]")
KEY = re.compile(r"(?<![\w$.])(?:([A-Za-z_$][\w$]*)|'([^'\n]+)'|\"([^\"\n]+)\")\s*:(?!:)")
JSON_KEY = re.compile(r"\"([^\"\n]+)\"\s*:\s*[-+]?(?:\d|\.\d)")
TEST_CALL = re.compile(r"\btest(?:\.(only|skip|fixme|beforeEach|afterEach|beforeAll|afterAll))?\s*\(")
DECL = re.compile(r"\b(?:(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)|(?:const|let|var)\s+"
                  r"(\{[^}]*\}|\[[^\]]*\]|[A-Za-z_$][\w$]*)\s*=)")
LOAD = re.compile(r"\b(?:require|readFileSync|import)\s*\(([^)]*)\)|\bfrom\s+(['\"][^'\"]+['\"])")
IDENT = re.compile(r"[A-Za-z_$][\w$]*")
REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^") | {""}


def js_mask(src: str) -> tuple[str, list[tuple[int, int]]]:
    """`src` with the contents of strings, template text, comments and regex literals blanked
    (newlines kept, `${...}` expressions kept as code), and the (start, end) span of every
    ordinary string literal."""
    out, strings, i, n = list(src), [], 0, len(src)
    stack: list[int] = []                 # brace depth at each open `${`
    depth, last = 0, ""

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    def template(k: int) -> int:          # from inside a template, to its end or to a `${`
        while k < n:
            if src[k] == "\\":
                k += 2
            elif src[k] == "`":
                return k + 1
            elif src.startswith("${", k):
                stack.append(depth)
                return k + 2
            else:
                k += 1
        return n

    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif c in "'\"":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            strings.append((i, j + 1))
            blank(i + 1, j)
            i, last = j + 1, "a"
        elif c == "`":
            j = template(i + 1)
            blank(i + 1, j - (2 if src.startswith("${", j - 2) else 1))
            i, last = j, "a"
        elif c == "/" and (last in REGEX_BEFORE or re.search(r"\b(return|typeof|case)\s*$", src[max(0, i - 8):i])):
            j, cls = i + 1, False
            while j < n and src[j] != "\n" and (cls or src[j] != "/"):
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                j += 1
            blank(i + 1, j)
            i, last = j + 1, "a"
        elif c == "}" and stack and depth == stack[-1]:
            stack.pop()
            j = template(i + 1)
            blank(i + 1, j - (2 if src.startswith("${", j - 2) else 1))
            i, last = j, "a"
        else:
            if c in "{":
                depth += 1
            elif c == "}":
                depth -= 1
            if not c.isspace():
                last = c if c in REGEX_BEFORE else "a"
            i += 1
    return "".join(out), strings


def _close(code: str, i: int) -> int:
    """Index after the bracket that closes the one at `i`."""
    depth = 0
    for k in range(i, len(code)):
        if code[k] in "([{":
            depth += 1
        elif code[k] in ")]}":
            depth -= 1
            if depth == 0:
                return k + 1
    return len(code)


def _depth(code: str, a: int, b: int) -> int:
    return sum(code.count(o, a, b) for o in "([{") - sum(code.count(c, a, b) for c in ")]}")


def _statement_end(code: str, i: int) -> int:
    depth = 0
    for k in range(i, len(code)):
        ch = code[k]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return k
        elif depth == 0 and ch == ";":
            return k + 1
        elif depth == 0 and ch == "\n":
            before = code[i:k].rstrip()
            after = code[k:].lstrip()
            if before and before[-1] not in ",=+-*/?:([{&|.<>!" and not re.match(r"[.?:+\-*/&|,)]", after):
                return k
    return len(code)


def js_units(src: str) -> list[dict]:
    """[{key, name, names, start, end, text}] of a spec: its test calls and its declarations."""
    code, strings = js_mask(src)
    units, spans = [], []
    seen: dict[tuple, int] = {}
    for m in TEST_CALL.finditer(code):
        start = m.end() - 1
        end = _close(code, start)
        title = next((src[a + 1:b - 1] for a, b in strings if a >= start), "")[:120] if m.group(1) is None else ""
        kind = m.group(1) or "test"
        nth = seen[(kind, title)] = seen.get((kind, title), -1) + 1
        units.append({"key": (kind, title, nth), "name": f"test.{kind}" if m.group(1) else f"test('{title}')",
                      "names": [], "start": m.start(), "end": end})
        spans.append((m.start(), end))
    for m in DECL.finditer(code):
        if any(a <= m.start() < b for a, b in spans):          # inside a test or a declaration
            continue
        if m.group(1):
            body = code.find("{", _close(code, code.find("(", m.end())))
            end, names = _close(code, body), [m.group(1)]
        else:
            end, names = _statement_end(code, m.end()), IDENT.findall(m.group(2))
        nth = seen[("decl", names[0])] = seen.get(("decl", names[0]), -1) + 1
        units.append({"key": ("decl", names[0], nth), "name": names[0], "names": names, "start": m.start(),
                      "end": end})
        spans.append((m.start(), end))
    for u in units:
        u["text"], u["code"] = src[u["start"]:u["end"]], code[u["start"]:u["end"]]
        u["line"] = src.count("\n", 0, u["start"]) + 1
        u["strings"] = [(a, b) for a, b in strings if u["start"] <= a < u["end"]]
    return units


def _inline_values(u: dict, src: str, fields: set[str], spec_dir: str) -> list[tuple[int, str]]:
    """[(line, what)] market values unit `u` builds inline or loads from outside tests/fixtures/."""
    code, base, found = u["code"], u["start"], []
    options = []                                    # fulfill({status, body, ...}): its own keys
    for m in re.finditer(r"\.fulfill\s*\(\s*\{", code):
        options.append((m.end() - 1, _close(code, m.end() - 1)))
    for m in KEY.finditer(code):
        if any(a < m.start() < b and _depth(code, a, m.start()) == 1 for a, b in options):
            continue
        key = m.group(1) or m.group(2) or m.group(3)
        if m.group(1) is None:                      # a quoted key: read it from the source
            q = src[base + m.start():base + m.end()]
            key = q.split(":")[0].strip()[1:-1]
        if key not in fields:
            continue
        depth, cut = 0, len(code) - m.end()
        for k, ch in enumerate(code[m.end():]):
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    cut = k
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                cut = k
                break
        value = code[m.end():m.end() + cut]
        if NUMBER.search(INDEX.sub("", value)):
            found.append((src.count("\n", 0, base + m.start()) + 1, f"'{key}' typed inline"))
    for a, b in u["strings"]:
        for m in JSON_KEY.finditer(src[a:b]):
            if m.group(1) in fields:
                found.append((src.count("\n", 0, a) + 1, f"'{m.group(1)}' typed in a JSON string"))
    for m in LOAD.finditer(code):
        arg = src[base + m.start():base + m.end()]
        parts = re.findall(r"['\"]([^'\"]+)['\"]", arg)
        path = posixpath.normpath(posixpath.join(spec_dir, *parts)) if parts else ""
        if path.endswith(".json") and not path.startswith(FIXTURES):
            found.append((src.count("\n", 0, base + m.start()) + 1, f"loads {path}, not a captured fixture under "
                                                                    f"{FIXTURES}"))
    return found


def js_violations(root: Path, base: str, paths: list[str], fields: set[str]) -> list[str]:
    out = []
    for path in paths:
        src = _source(root, "HEAD", path)
        if src is None:
            continue
        units = js_units(src)
        old = _source(root, base, path)
        old_text = {u["key"]: " ".join(u["text"].split()) for u in js_units(old)} if old else {}
        by_name: dict[str, list[int]] = {}
        for i, u in enumerate(units):
            for nm in u["names"]:
                by_name.setdefault(nm, []).append(i)
        refs = [{j for nm in set(IDENT.findall(u["code"])) for j in by_name.get(nm, []) if j != i}
                for i, u in enumerate(units)]

        reach = []
        for i in range(len(units)):
            seen, todo = {i}, [i]
            while todo:
                for j in refs[todo.pop()] - seen:
                    seen.add(j)
                    todo.append(j)
            reach.append(seen)
        spec_dir = posixpath.dirname(path)
        inline = {i: f for i, u in enumerate(units) if (f := _inline_values(u, src, fields, spec_dir))}
        routes = [i for i, u in enumerate(units) if ".route(" in u["code"] or ".fulfill(" in u["code"]]
        for i, u in enumerate(units):
            if old_text.get(u["key"]) == " ".join(u["text"].split()):
                continue
            served = {j for r in routes if r in reach[i] for j in reach[r] if j in inline}
            if i in inline and any(i in reach[r] for r in routes):
                served.add(i)
            for j in sorted(served):
                where = "" if j == i else f" in {units[j]['name']}"
                what = "; ".join(f"line {line}: {w}" for line, w in inline[j])
                out.append(f"{path}:{inline[j][0][0]} {u['name']}: a browser route serves market values not "
                           f"loaded from {FIXTURES}{where} ({what})")
    return out


def violations(root: Path, base: str) -> list[str]:
    changed = _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD").splitlines()
    py = [f for f in changed if f.startswith("tests/") and f.endswith(".py")]
    js = [f for f in changed if re.fullmatch(r"tests/e2e/[^/]+\.spec\.js", f)]
    if not py and not js:
        return []
    fields = market_fields(root)
    return python_violations(root, base, py, fields) + js_violations(root, base, js, fields)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base)
    except (ToolError, SyntaxError, ValueError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
