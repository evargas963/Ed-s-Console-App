"""Whether a Python literal that check_end_to_end found puts a value where one is missing.

check_end_to_end counts every `if x is None: <literal>`, None-check ternary, `or <literal>` and
`.get(key, <literal>)` alike. The census reports apart the ones that invent nothing (operator
2026-11-11, on the 24 he read one at a time: "Yes, stop counting"): text for a person (a reason,
a state word, a label), '' and an empty list, tuple, set or dict (nothing to show), and a
setting of the program's own read from the environment. A number, a boolean, a string that
reads as a number, and a container holding one stand in for a value: those are fallbacks.
"""

from __future__ import annotations

import ast
import re

from tools import check_end_to_end as e2e

_NUMBER = re.compile(r"[+-]?\d")


def _invents(node: ast.AST) -> bool:
    """Return whether the literal `node` is a value of the data's kind."""
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, str):
            return bool(_NUMBER.match(v))
        return isinstance(v, (bool, int, float))
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_invents(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return any(_invents(v) for v in node.values)
    return False


def _environment(call: ast.Call) -> bool:
    """Return whether `call` reads the environment: `os.environ.get(...)`."""
    f = call.func
    return (
        isinstance(f, ast.Attribute)
        and isinstance(f.value, ast.Attribute)
        and f.value.attr == "environ"
    )


def _stand_ins(node: ast.AST) -> list[ast.AST] | None:
    """Return the values `node` puts where one is missing; None when it is not such a node."""
    if isinstance(node, ast.If) and e2e._none_check(node.test):
        return [getattr(node.body[0], "value", None)]
    if isinstance(node, ast.IfExp) and e2e._none_check(node.test):
        return [node.body, node.orelse]
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return [node.values[-1]]
    if isinstance(node, ast.Call) and e2e._call_patch(node) is not None:
        if _environment(node):
            return []
        return [*node.args[1:], *(k.value for k in node.keywords if k.arg == "default")]
    return None


def stands_in(source: str, line: int) -> bool:
    """Return whether a patch shape that starts on `line` of `source` invents a value.

    A call's stand-in that is not a literal (a default passed to `getattr`), and a repair with
    no stand-in to read (`.fillna(...)`, `nan_to_num`), count: what they put there cannot be
    read here.
    """
    for node in ast.walk(ast.parse(source)):
        if getattr(node, "lineno", None) != line:
            continue
        values = _stand_ins(node)
        if values is None:
            continue
        if isinstance(node, ast.Call) and not values and not _environment(node):
            return True
        for v in values:
            if v is None:
                continue
            literal = isinstance(v, (ast.Constant, ast.List, ast.Tuple, ast.Set, ast.Dict))
            if _invents(v) or (isinstance(node, ast.Call) and not literal):
                return True
    return False
