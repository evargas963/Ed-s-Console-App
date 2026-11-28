"""The census of everything in the repository that must reach 0. Read-only on the repository.

    python -m tools.census.census <out dir> [--repo <checkout>] [--coverage <coverage.json>]
        [--page-coverage <dir>] [--machine [--data <dir>]]

Run from the checkout with the repository's Python, which also holds tools/census/requirements.txt;
`npm ci --prefix tools/census` holds the other checkers. --repo is the checkout counted (default
the one it runs from), so a pull request's base is counted by the head's census: one ruler before
and after. --coverage is coverage.py's JSON report of the commit's pytest run (pytest.yml), whose
statements and branches no test runs are counted; --page-coverage the lines of the page's scripts
each browser test worker ran (tests/e2e/fixtures/test.js), whose code lines no test runs are
counted. --machine
counts what only the working machine holds: its database (--data, default <repo>/data), its
branches, stashes and worktrees, and the files on its disk git does not hold; a clone (CI's)
reports those rows as not counted, never as 0. Writes
<out>/census_<date>_<sha>.md (the report) and <out>/items_<date>_<sha>.txt (every item);
`python -m tools.census.compare <before.md> <after.md>` prints what changed.

Every section names the AGENTS.md rule it checks and the tool that counts it, and each checker's
own total is compared with what the census read. What no machine counts yet is a row of the work
list, ACTIVE_PROGRAM.md, counted with the open work rows; each candidate's verdict, and each issue
at its row's design target, with its reason is in decisions.json. A checker whose output the
census cannot read stops the census with that error.
"""

import argparse
import ast
import bisect
import collections
import copy
import csv
import dataclasses
import datetime as dt
import functools
import hashlib
import io
import json
import logging
import re
import shutil
import subprocess
import sys
import tarfile
import tokenize
from http import HTTPStatus
from pathlib import Path

import db
import time_et
from tools import check_end_to_end as e2e
from tools import check_integrity, check_one_reader, check_tests_serve_app
from tools.census import command, copied_blocks, python_literals

log = logging.getLogger("census")
ARGS = argparse.ArgumentParser(description="The census of everything that must reach 0.")
ARGS.add_argument("out", type=Path)
ARGS.add_argument("--repo", type=Path, default=Path.cwd())
ARGS.add_argument("--data", type=Path)
ARGS.add_argument("--coverage", type=Path)
ARGS.add_argument("--page-coverage", type=Path)
ARGS.add_argument("--machine", action="store_true")
_args = ARGS.parse_args()
REPO = _args.repo.resolve()
OUT = _args.out.resolve()
DATA = (_args.data if _args.data else REPO / "data").resolve()
MACHINE = _args.machine
#: the rows only the working machine can count; a clone has none of them to see
NOT_HERE = "counted on the working machine (--machine), not in a clone (reported)"
CENSUS = Path(__file__).resolve().parent
LINT = CENSUS / ".lint"  # the commit's tracked files, as locks.yml checks them out (`head`)
HEAD = LINT / "head"
PY = sys.executable


def exe(name):
    """Return a checker's program.

    It is looked for in the census's npm tools, then the running Python's scripts, then PATH.
    """
    for d in (CENSUS / "node_modules" / ".bin", Path(PY).parent):
        for n in (f"{name}.cmd", f"{name}.exe", name):
            if (d / n).exists():
                return str(d / n)
    found = shutil.which(name)
    if found is None:
        log.error("census: %s is not installed; see this module's docstring", name)
        raise SystemExit(1)
    return found


run = functools.partial(command.run, cwd=REPO)


def git(*a):
    return run(["git", *a])


SHA = git("rev-parse", "--short", "HEAD").strip()
NOW = time_et.now()
TODAY = dt.datetime.fromtimestamp(NOW, time_et.ET).date().isoformat()
blobs = {}
for row in git("ls-files", "-s").splitlines():
    meta, path = row.split("\t", 1)
    blobs[path] = meta.split()[1]
FILES = sorted(blobs)
TEXT_FILES = set(git("grep", "-I", "-l", "-e", "", "--", ".").splitlines())
TEXT = {}
NOT_UTF8 = []
for f in FILES:
    if f in TEXT_FILES:
        raw = (REPO / f).read_bytes()
        TEXT[f] = raw.decode("utf-8", errors="replace")
        if "\ufffd" in TEXT[f] and b"\xef\xbf\xbd" not in raw:
            NOT_UTF8.append(f)
OUTSIDE = (
    "research",
    "reports",
    "docs",
    "governance",
    "verification",
    "release",
    "arch_competition",
    "v2_decision",
    "features",
    "planes",
    "models",
)
LANG = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".html": "HTML",
    ".css": "CSS",
    ".bat": "Batch",
    ".cmd": "Batch",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".md": "Markdown",
    ".ps1": "PowerShell",
}


def area(f):
    top = f.split("/")[0]
    kinds = (
        ("vendor" in f, "vendored"),
        (f.startswith("tests/"), "tests"),
        (f.startswith(("tools/", "scripts/")), "tools"),
        (f.startswith((".github/", ".claude/", ".cursor/")), "CI/hooks"),
        (top in OUTSIDE, top),
    )
    return next((name for hit, name in kinds if hit), "product")


def lang(f):
    return LANG.get(Path(f).suffix)


PRODUCT_PY = [f for f in FILES if f.endswith(".py") and area(f) == "product" and f in TEXT]
PAGE_JS = [
    f
    for f in FILES
    if f.startswith("static/") and f.endswith((".js", ".mjs")) and "vendor" not in f
]
PAGE_ALL = [f for f in FILES if f.startswith("static/") and "vendor" not in f and f in TEXT]
ALL_PY = [f for f in FILES if f.endswith(".py") and f in TEXT]
page_text = "\n".join(TEXT[f] for f in PAGE_ALL)


@dataclasses.dataclass
class Row:
    """One category of the census: the rule it checks, what counts it, and its items.

    A check declares its row before it looks, so a row with no items is a check that ran and found
    0; `counted` is a count a tool gave whole, its items elsewhere.
    """

    rule: str
    tool: str
    items: list = dataclasses.field(default_factory=list)
    counted: int | None = None

    @property
    def count(self) -> int:
        return self.counted if self.counted is not None else len(self.items)


rows: dict[tuple[str, str], Row] = {}  # (section, category) -> its row, in the order checked


def add(section, category, rule, tool, item=None, count=None):
    """Declare `category` (a check that ran) and add `item` to it, or give its whole `count`."""
    row = rows.setdefault((section, category), Row(rule, tool))
    if item is not None:
        row.items.append(item)
    if count is not None:
        row.counted = count


def lines_matching(files, patterns, section, rule, tool, skip_comment=False):
    for _pat, cat in patterns:
        add(section, cat, rule, tool)
    for f in [f for f in files if f in TEXT]:
        for n, ln in enumerate(TEXT[f].splitlines(), 1):
            s = ln.strip()
            if skip_comment and s.startswith(("#", "//", "*")):
                continue
            for pat, cat in patterns:
                if re.search(pat, ln):
                    add(section, cat, rule, tool, f"{f}:{n}: {s[:140]}")


def by_line(category_start, joiner):
    """One item per source line for a category whose finder reports each value on a line."""
    for key in [k for k in rows if k[1].startswith(category_start)]:
        lines = collections.OrderedDict()
        for it in rows[key].items:
            lines.setdefault(it.split(": ")[0], []).append(it.split(": ", 1)[-1])
        rows[key].items = [f"{ln}: {joiner.join(vs)}" for ln, vs in lines.items()]


logging.basicConfig(level=logging.INFO, format="%(message)s")

# =============================================================================================
# A. CODE PATTERNS (rule 1 no patches, rule 3 one producer, rule 13 imports at the top)
# =============================================================================================
log.info("census: A")
S = "A. Code patterns"
SHAPED = [f for f in FILES if f.endswith(e2e.SHAPED_SUFFIXES) and f in TEXT]
SWALLOW = re.compile(r"except|swallow|suppress|silenced|thrown away|let pass")


#: what a JS `||`/`??` reads when it is the program's own setting, not a value Schwab or the server
#: sent: a DOM attribute, size or input, a stored preference, the environment, a constant table
JS_SETTING = re.compile(
    r"getAttribute\(|clientWidth|\.value\b|\bsget\(|process\.env|\b[A-Z][A-Z0-9_]*\["
)


def js_fallback(text, m):
    """Return whether a check_end_to_end JS literal match puts a value where one is missing.

    It does when its literal is a value of the data's kind: an empty list that flows on (a missing
    list read as none), a number or boolean in place of a value sent (not the program's own
    setting, not a running total's 0), or a string that reads as data (a date, a count, a price,
    a symbol). It does not when the literal is rule 5's '-' or a label ending in it, text for a
    person, '' or null (nothing drawn), an empty object or a list only read through (the result
    still missing), or a word of the page's own (a tab, class, colour, glyph, file name).
    """
    lit = re.sub(r"^(\|\||\?\?)=?\s*", "", m.group(0))
    after = text[m.end() :]
    before = text[text.rfind("\n", 0, m.start()) + 1 : m.start()]
    if lit == "[]":
        return not re.match(r"\s*\)\s*(\[|\.forEach\()", after)
    if lit[0] in "'\"":
        return bool(re.match(r"[+-]?\d|\$?[A-Z]{1,6}$", lit[1:-1]))
    if lit in ("{}", "null"):
        return False
    return not (JS_SETTING.search(before) or (lit == "0" and re.match(r"\s*\)\s*\+", after)))


def patch_kind(f, line, kind):
    """Return whether a patch shape is a fallback, a swallow, or a literal that is neither.

    A fallback puts an invented value where one is missing; a swallow throws an error away.
    check_end_to_end gives JS one label for all three: a JS line holding a catch is a swallow, one
    with a literal js_fallback reads as a value a fallback, and the rest is reported apart. A
    Python literal that invents nothing (python_literals.stands_in) is reported apart too.
    """
    if f.endswith(".py"):
        if SWALLOW.search(kind):
            return "swallows"
        return "fallbacks" if python_literals.stands_in(TEXT[f], line) else NOT_FALLBACK
    text = TEXT[f]
    ln = text.splitlines()[line - 1]
    if SWALLOW.search(ln) or "catch" in ln:
        return "swallows"
    starts = [m for m in e2e.JS_PATCH.finditer(text) if text.count("\n", 0, m.start()) + 1 == line]
    return "fallbacks" if any(js_fallback(text, m) for m in starts) else NOT_FALLBACK


NOT_FALLBACK = "literals that are not fallbacks ('-', text, '', read through, a setting)"
for f in SHAPED:
    for what in ("fallbacks", "swallows"):
        add(S, f"{what}: {lang(f)} {area(f)}", "1", "check_end_to_end.shapes + js_fallback")
for f in SHAPED:
    for line, kind in e2e.shapes(f, TEXT[f]):
        what = patch_kind(f, line, kind)
        add(
            S,
            f"{what}: {lang(f)} {area(f)}" + (" (reported)" if what == NOT_FALLBACK else ""),
            "1",
            "check_end_to_end.shapes + js_fallback",
            f"{f}:{line}: {kind}",
        )
OTHER = {
    "CSS": [(r"var\(--[\w-]+\s*,", "var() with a fallback value")],
    "Batch": [(r"2>\s*nul", "error output thrown away"), (r"(?i)if not defined", "a default set")],
    "YAML": [
        (r"continue-on-error:\s*true", "a failing step let pass"),
        (r"\|\|\s*true", "a failing command let pass"),
    ],
    "PowerShell": [(r"(?i)-ErrorAction\s+SilentlyContinue", "an error silenced")],
}
for f in [f for f in FILES if lang(f) in OTHER and f in TEXT]:
    for what in ("fallbacks", "swallows"):
        add(S, f"{what}: {lang(f)} {area(f)}", "1", "regex")
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        for pat, kind in OTHER[lang(f)]:
            if re.search(pat, ln):
                what = "swallows" if SWALLOW.search(kind) else "fallbacks"
                add(S, f"{what}: {lang(f)} {area(f)}", "1", "regex", f"{f}:{n}: {kind}")
add(S, "text files that are not UTF-8", "13", "git grep -I")
for f in NOT_UTF8:
    add(S, "text files that are not UTF-8", "13", "git grep -I", f)
for f in ALL_PY:
    add(S, f"duplicate function groups: {area(f)}", "1", "ast body hash")
add(S, "second readers of a Schwab field", "3", "tools.check_one_reader --list")
add(S, "identical files (extra copies)", "1", "git blob")
add(S, "product modules doing math (target: one Calculators part)", "shape", "ast")

for ln in run([PY, "-m", "tools.check_one_reader", "--list"]).splitlines():
    if "modules:" in ln:
        add(S, "second readers of a Schwab field", "3", "tools.check_one_reader --list", ln.strip())

by_blob = collections.defaultdict(list)
for f, b in blobs.items():
    by_blob[b].append(f)
for fs in by_blob.values():
    if len(fs) > 1 and (REPO / fs[0]).exists() and (REPO / fs[0]).stat().st_size > 0:
        add(S, "identical files (extra copies)", "1", "git blob", " = ".join(sorted(fs)))

trees = {f: ast.parse(TEXT[f]) for f in ALL_PY}
#: the fewest syntax nodes a function body (its docstring set aside) has to count as a copy: a
#: smaller one (a return of one name, a call passed on) reads alike in unrelated functions
COPIED_BODY_NODES = 12
bodies = collections.defaultdict(list)
func_index = []  # (file, line, name, length, node)
for f, tree in trees.items():
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        func_index.append((f, node.lineno, node.name, node.end_lineno - node.lineno + 1, node))
        body = node.body
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            body = body[1:]
        mod = ast.Module(body=body, type_ignores=[])
        if sum(1 for _ in ast.walk(mod)) >= COPIED_BODY_NODES:
            key = hashlib.sha1(
                ast.dump(mod, annotate_fields=False).encode(), usedforsecurity=False
            ).hexdigest()
            bodies[(key, ast.dump(node.args, annotate_fields=False))].append(
                f"{f}:{node.lineno} {node.name}"
            )
for fs in bodies.values():
    if len(fs) > 1:
        add(
            S,
            f"duplicate function groups: {area(fs[0].split(':')[0])}",
            "1",
            "ast body hash",
            " = ".join(fs),
        )

compared = [
    f
    for f in FILES
    if lang(f) and lang(f) not in ("Markdown", "JSON") and "vendor" not in f and f in TEXT
]
for f in compared:
    add(S, f"copied blocks (8+ lines): {lang(f)} {area(f)}", "1", "line-window hash")
for at, first in copied_blocks.copied(
    {f: (TEXT[f], copied_blocks.import_lines(trees[f]) if f in trees else set()) for f in compared}
):
    f = at.rpartition(":")[0]
    add(
        S,
        f"copied blocks (8+ lines): {lang(f)} {area(f)}",
        "1",
        "line-window hash",
        f"{at} = {first}",
    )


class _Unnamed(ast.NodeTransformer):
    """A formula with its names set aside.

    Two functions computing the same thing from differently named inputs read the same.
    """

    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id="_", ctx=ast.Load()), node)


def _own_nodes(fn):
    """`fn`'s nodes, not those of a function defined inside it (that one is counted itself)."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(n))


#: the fewest expressions (names, numbers, calls, operations; not the parser's load and operator
#: markers) an arithmetic has to count as a formula: below it, a sum of two items or of two calls
#: reads alike in unrelated code
FORMULA_EXPRESSIONS = 9
#: the fewest keys a dict literal has to count as an answer built by hand
ANSWER_KEYS = 3
FORMULA = "the same formula in more than one function: Python product (one producer, rule 3)"
ANSWER = (
    "the same answer built by hand in more than one function: Python product "
    f"(dict literals with the same {ANSWER_KEYS}+ keys; one producer, rule 3)"
)
add(S, FORMULA, "3", f"ast: arithmetic of {FORMULA_EXPRESSIONS}+ expressions, names set aside")
add(S, ANSWER, "3", "ast: dict literal key sets")
formulas = collections.defaultdict(set)
answers = collections.defaultdict(set)
for f in PRODUCT_PY:
    for fn in ast.walk(trees[f]):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        where = f"{f}:{fn.lineno} {fn.name}"
        for n in _own_nodes(fn):
            # `|` is a type union or a set or dict merge, not a formula
            if (
                isinstance(n, ast.BinOp)
                and not isinstance(n.op, ast.BitOr)
                and sum(isinstance(e, ast.expr) for e in ast.walk(n)) >= FORMULA_EXPRESSIONS
            ):
                shape = ast.dump(_Unnamed().visit(copy.deepcopy(n)), annotate_fields=False)
                formulas[shape].add(where)
            elif isinstance(n, ast.Dict) and len(n.keys) >= ANSWER_KEYS:
                keys = [k.value for k in n.keys if isinstance(k, ast.Constant)]
                if len(keys) == len(n.keys) and all(isinstance(k, str) for k in keys):
                    answers[tuple(sorted(keys))].add(where)
for shape, where in formulas.items():
    if len({w.split(" ")[1] for w in where}) > 1:
        add(S, FORMULA, "3", "ast", " = ".join(sorted(where)))
for keys, where in answers.items():
    if len(where) > 1:
        add(S, ANSWER, "3", "ast", f"{{{', '.join(keys)}}}: " + " = ".join(sorted(where)))


#: where the program's math lives: the Calculators part, and the one formatter rounding a number
#: as the screen shows it (AGENTS.md "The shape" and rule 13)
MATH_HOMES = ("calc/", "numeric_contract.py")


def computes(tree):
    """Return whether a module does math: a pricing or computing function, or a math call."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.lstrip(
            "_"
        ).startswith(("compute_", "bs_")):
            return True
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in ("math", "np", "numpy")
            and node.attr not in ("isfinite", "isnan", "isinf", "pi", "inf", "nan")
        ):
            return True
    return False


for f in [f for f in PRODUCT_PY if not f.startswith(MATH_HOMES) and computes(trees[f])]:
    add(S, "product modules doing math (target: one Calculators part)", "shape", "ast", f)

# =============================================================================================
# B. STANDARD LINTERS over the whole repository
# =============================================================================================
log.info("census: B")
S = "B. Linters"
out = run(
    [
        PY,
        "-m",
        "ruff",
        "check",
        ".",
        "--config",
        "locks.ruff.toml",
        "--ignore-noqa",
        "--output-format",
        "json",
        "--no-cache",
        "--exit-zero",
    ],
    stdout_only=True,
)
locked = set()
for d in json.loads(out):
    f = Path(d["filename"]).resolve().relative_to(REPO.resolve()).as_posix()
    locked.add((f, d["location"]["row"], d["code"]))
    add(
        S,
        f"ruff {d['code']} (locks.ruff.toml, noqa ignored)",
        "locks/13",
        "ruff",
        f"{f}:{d['location']['row']}: {d['message'][:120]}",
    )
# bandit's security rules as ruff holds them (S), the bank's standard (Standard of care 11):
# every one, over the files locks.ruff.toml reads; a finding locks counts already is counted there
out = run(
    [
        *(PY, "-m", "ruff", "check", ".", "--config", "locks.ruff.toml", "--select", "S"),
        *("--ignore-noqa", "--output-format", "json", "--no-cache", "--exit-zero"),
    ],
    stdout_only=True,
)
for d in json.loads(out):
    f = Path(d["filename"]).resolve().relative_to(REPO.resolve()).as_posix()
    if (f, d["location"]["row"], d["code"]) not in locked:
        add(
            S,
            f"ruff {d['code']} (bandit's security rules, noqa ignored)",
            "Standard of care 11",
            "ruff S",
            f"{f}:{d['location']['row']}: {d['message'][:120]}",
        )
# what ruff holds of PEP 8's names (pep8-naming) and of a module's private names reached from
# outside it (SLF001; .claude/rules/tests.md: a test never pins a private helper), over the files
# locks.ruff.toml reads; a function's size (pylint's returns, branches, arguments and statements)
# is counted and reported, never judged (AGENTS.md, Fix what you find); a bare number compared
# (PLR2004) is checked by hand, an expected value in an assert being a test's own data
out = run(
    [
        *(PY, "-m", "ruff", "check", ".", "--config", "locks.ruff.toml"),
        *("--select", "N,PLR0911,PLR0912,PLR0913,PLR0915,PLR2004,SLF001", "--ignore-noqa"),
        *("--output-format", "json", "--no-cache", "--exit-zero"),
    ],
    stdout_only=True,
)
SIZE_RULES = {"PLR0911", "PLR0912", "PLR0913", "PLR0915"}
for d in json.loads(out):
    f = Path(d["filename"]).resolve().relative_to(REPO.resolve()).as_posix()
    code = d["code"]
    if code in SIZE_RULES:
        cat = f"ruff {code}: a function's size, noqa ignored (reported)"
    elif code == "PLR2004":
        cat = f"ruff {code}: a bare number compared, noqa ignored (check each)"
    else:
        cat = f"ruff {code}: names and private reach, noqa ignored"
    add(S, cat, "13", "ruff", f"{f}:{d['location']['row']}: {d['message'][:120]}")
stats = run(
    [
        PY,
        "-m",
        "ruff",
        "check",
        ".",
        "--config",
        "locks.ruff.toml",
        "--ignore-noqa",
        "--statistics",
        "--no-cache",
        "--exit-zero",
    ],
    stdout_only=True,
)
ruff_own = sum(int(m.group(1)) for m in re.finditer(r"(?m)^\s*(\d+)\s+[A-Z]+\d+", stats))
ruff_ours = sum(r.count for k, r in rows.items() if k[1].startswith("ruff ") and "locks" in k[1])
if ruff_own == ruff_ours:
    add(
        S,
        "ruff (locks): census count equals ruff's own total (reported)",
        "census",
        "ruff",
        count=ruff_own,
    )
else:
    add(
        S,
        "ruff (locks): findings the census did not read (census error)",
        "census",
        "ruff",
        f"ruff reports {ruff_own}, the census read {ruff_ours}",
    )
add(S, "ruff findings under pyproject's selection (fail at commit)", "13", "ruff")
add(S, "files ruff format would change", "13", "ruff format")
add(S, "import-linter: broken contracts / forbidden imports", "10", "lint-imports")
out = run(
    [PY, "-m", "ruff", "check", ".", "--output-format", "concise", "--no-cache", "--exit-zero"]
)
for ln in out.splitlines():
    if re.match(r"(.+?):(\d+):\d+: ([A-Z]+\d+)", ln):
        add(S, "ruff findings under pyproject's selection (fail at commit)", "13", "ruff", ln)
for ln in run([PY, "-m", "ruff", "format", "--check", ".", "--no-cache"], ok=(0, 1)).splitlines():
    if ln.startswith("Would reformat"):
        add(S, "files ruff format would change", "13", "ruff format", ln)
# a suppression is a comment: Python's comments as its tokenizer reads them; in the other
# languages the text after a comment opener on the line
SUPPRESSIONS = [
    (r"^#\s*noqa|\s#\s*noqa", "noqa comments"),
    (r"#\s*type:\s*ignore", "type: ignore comments"),
    (r"#\s*fmt:\s*(off|skip)", "format suppressions"),
    (r"#\s*pragma:\s*no cover", "coverage exclusions"),
    (r"eslint-disable|@ts-ignore|stylelint-disable", "JS/CSS lint suppressions"),
    (r"#\s*pyright:\s*ignore", "pyright ignores"),
]
# an exemption marker is an opt-out wherever a hand-built check reads it: a marker a tool names is
# counted in comments, docstrings and the tool that honors it; one no tool names opts nothing out
# (a test's input that a guard refuses whatever text it carries)
MARKER = r"(?:#|//)\s*([a-z]+(?:-[a-z]+)*-ok)\b"
MARKERS = "exemption markers of hand-built checks (an opt-out the rules forbid)"
READ_BY_TOOLS = "\n".join(TEXT[f] for f in FILES if f.startswith("tools/") and f in TEXT)
add(S, MARKERS, "locks", "regex")
for f in [
    f
    for f in FILES
    if lang(f) in ("Python", "JavaScript", "HTML", "CSS") and "vendor" not in f and f in TEXT
]:
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        if any(m.group(1) in READ_BY_TOOLS for m in re.finditer(MARKER, ln)):
            add(S, MARKERS, "locks", "regex", f"{f}:{n}: {ln.strip()[:140]}")
for _pat, cat in SUPPRESSIONS:
    add(S, cat, "locks", "tokenize")
for f in [f for f in ALL_PY if "vendor" not in f]:
    for tok in tokenize.generate_tokens(io.StringIO(TEXT[f]).readline):
        if tok.type == tokenize.COMMENT:
            for pat, cat in SUPPRESSIONS:
                if re.search(pat, tok.string):
                    add(S, cat, "locks", "tokenize", f"{f}:{tok.start[0]}: {tok.string[:120]}")
for f in [
    f for f in FILES if lang(f) in ("JavaScript", "HTML", "CSS") and "vendor" not in f and f in TEXT
]:
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        opener = re.search(r"//|/\*|<!--", ln)
        for pat, cat in SUPPRESSIONS:
            if opener and re.search(pat, ln[opener.start() :]):
                add(S, cat, "locks", "regex", f"{f}:{n}: {ln.strip()[:120]}")
if LINT.exists():
    shutil.rmtree(LINT)
HEAD.mkdir(parents=True)
archive = subprocess.run(
    ["git", "archive", "--format=tar", "HEAD"], cwd=REPO, capture_output=True, check=True
).stdout
tarfile.open(fileobj=io.BytesIO(archive)).extractall(HEAD, filter="data")
out = run(
    [exe("lint-imports"), "--config", "head/locks.imports.toml", "--no-cache"], cwd=LINT, ok=(0, 1)
)
for ln in out.splitlines():
    if "BROKEN" in ln or re.match(r"^-?\s*\S+ -> \S+", ln.strip()):
        add(
            S,
            "import-linter: broken contracts / forbidden imports",
            "10",
            "lint-imports",
            ln.strip(),
        )
kept = re.search(r"Contracts: (\d+) kept, (\d+) broken", out)
if kept is None:
    log.error("census: import-linter printed no contract count:\n%s", out[-2000:])
    raise SystemExit(1)
add(S, "import-linter contracts kept (reported)", "10", "lint-imports", count=int(kept.group(1)))
for mode in ("basic", "strict"):
    # the repository's own pyright settings (pyproject.toml: its files and its Python), so the
    # count is the required check's; only the mode is the census's. The type stubs are named
    # because pyright looks for them beside the config it is given, and they are in the tree
    cfg = LINT / f"pyright_{mode}.json"
    cfg.write_text(
        json.dumps(
            {
                "extends": "head/pyproject.toml",
                "stubPath": "head/typings",
                "typeCheckingMode": mode,
            }
        ),
        encoding="utf-8",
    )
    out = run(
        [exe("pyright"), "-p", cfg, "--pythonpath", PY, "--outputjson"],
        cwd=LINT,
        stdout_only=True,
        ok=(0, 1),  # errors reported 1; a fatal, configuration or command error 2, 3, 4
    )
    pj = json.JSONDecoder().raw_decode(out[out.index("{") :])[0]
    diags = [d for d in pj["generalDiagnostics"] if d["severity"] == "error"]
    add(
        S,
        f"pyright {mode}: files checked (reported)",
        "12",
        f"pyright {mode}",
        count=pj["summary"]["filesAnalyzed"],
    )
    add(S, f"pyright {mode}-mode errors in product code", "12", f"pyright {mode}")
    for d in diags:
        add(
            S,
            f"pyright {mode}-mode errors in product code",
            "12",
            f"pyright {mode}",
            f"{Path(d['file']).resolve().relative_to(HEAD.resolve()).as_posix()}:"
            f"{d['range']['start']['line'] + 1}: {d['message'].splitlines()[0][:120]}",
        )
    if pj["summary"]["errorCount"] == len(diags):
        add(
            S,
            f"pyright {mode}: census count equals its own total (reported)",
            "census",
            "pyright",
            count=len(diags),
        )
    else:
        add(
            S,
            f"pyright {mode}: findings the census did not read (census error)",
            "census",
            "pyright",
            f"pyright reports {pj['summary']['errorCount']}, the census read {len(diags)}",
        )

# =============================================================================================
# C. DEAD AND UNUSED CODE (rule 1: an existing piece that has no job is removed)
# =============================================================================================
log.info("census: C")
S = "C. Dead code"
for a in ("product", "tools", "tests"):
    add(S, f"vulture: unused code in {a}", "1", "vulture")
    add(
        S,
        f"vulture: attribute set on another object in {a} (candidates, check each: a library "
        "may read it)",
        "1",
        "vulture",
    )
for cat, tool in (
    ("page functions nothing calls", "regex"),
    ("CSS custom properties nothing uses", "regex"),
    ("CSS classes no page or script uses", "regex"),
    ("Python packages required that nothing imports, needs or runs", "requirements + pip show"),
    ("JS packages required but never used (check each)", "package.json"),
    ("page files index.html never loads", "regex"),
    ("keys built that nothing reads: no page, no other code", "ast+regex"),
):
    add(S, cat, "1", tool)
VULTURE = [PY, "-m", "vulture", "--min-confidence", "60"]
# the tests apart, so a product function only a test calls is still unused; pytest calls a test,
# a test class, a hook and a fixture by its name, and http.server a handler's do_<METHOD>
# vulture's exit codes: none found 0, unused code found 3; invalid input 1, a bad command 2
out = run([*VULTURE, *[f for f in ALL_PY if area(f) in ("product", "tools")]], ok=(0, 3)) + run(
    [
        *(*VULTURE, "--ignore-names", "test_*,Test*,pytest_*,do_*"),
        *("--ignore-decorators", "@pytest.fixture"),
        *[f for f in ALL_PY if area(f) == "tests"],
    ],
    ok=(0, 3),
)
routes = {
    m.group(1)
    for m in re.finditer(
        r"@app\.\w+\([^\n]*\)\s*\n(?:\s*[@#][^\n]*\n|\s*\n)*"
        r"\s*(?:async )?def (\w+)",
        TEXT["server.py"],
    )
}
param_lines = {
    (f, a.arg)
    for f, t in trees.items()
    for n in ast.walk(t)
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    for a in [
        *n.args.posonlyargs,
        *n.args.args,
        *n.args.kwonlyargs,
        *([n.args.vararg] if n.args.vararg else []),
        *([n.args.kwarg] if n.args.kwarg else []),
    ]
}
py_all_text = "\n".join(TEXT[f] for f in ALL_PY if area(f) in ("product", "tools", "tests"))
#: methods marked @override (PEP 698): the base class's caller is their use, which vulture
#: cannot see
overrides = {
    (f, n.name)
    for f, t in trees.items()
    for n in ast.walk(t)
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    and any(
        (isinstance(d, ast.Name) and d.id == "override")
        or (isinstance(d, ast.Attribute) and d.attr == "override")
        for d in n.decorator_list
    )
}
#: vulture's confidence in an unused import (vulture.core); unreachable code and an unused argument
#: are 100%, every other kind its default 60%, a guess a library's own reads may disprove
VULTURE_SURE = 90
for ln in out.splitlines():
    m = re.match(r"(.+?):(\d+): unused (\w+) '(\w+)' \((\d+)% confidence", ln)
    if m is None:
        continue
    f = m.group(1).replace("\\", "/")
    kind, name, conf = m.group(3), m.group(4), int(m.group(5))
    item = f"{f}:{m.group(2)}: unused {kind} '{name}' ({conf}%)"
    named_again = (
        re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", page_text)
        or len(re.findall(rf"\b{re.escape(name)}\b", py_all_text)) > 1
    )
    if (
        name in routes
        or (kind == "variable" and (f, name) in param_lines)
        or (f, name) in overrides
    ):
        continue  # FastAPI calls a route by its decorator; ruff ARG counts unused parameters
    if kind == "attribute" and conf < VULTURE_SURE:
        add(
            S,
            f"vulture: attribute set on another object in {area(f)} (candidates, check "
            "each: a library may read it)",
            "1",
            "vulture",
            item,
        )
    elif conf >= VULTURE_SURE or not named_again:
        add(S, f"vulture: unused code in {area(f)}", "1", "vulture", item)

imports_of = collections.defaultdict(set)
for f, tree in trees.items():
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imports_of[a.name].add(f)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports_of[node.module].add(f)
            for a in node.names:
                imports_of[f"{node.module}.{a.name}"].add(f)
ENTRY = {"server.py", "launch.py", "reauth_schwab.py"}
entry_text = "\n".join(
    TEXT[f]
    for f in FILES
    if (lang(f) == "Batch" or f.endswith((".toml", ".yml", ".mjs", ".ps1"))) and f in TEXT
)
for f in [f for f in PAGE_JS if f in TEXT]:
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        for m in re.finditer(
            r"(?<!\()\bfunction\s+([A-Za-z_$][\w$]*)\s*\(|"
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?"
            r"(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)",
            ln,
        ):
            name = next(g for g in m.groups() if g)
            if len(re.findall(rf"(?<![\w$]){re.escape(name)}(?![\w$])", page_text)) <= 1:
                add(S, "page functions nothing calls", "1", "regex", f"{f}:{n} {name}")

css_text = "\n".join(TEXT[f] for f in PAGE_ALL if f.endswith(".css"))
markup_js = "\n".join(TEXT[f] for f in PAGE_ALL if not f.endswith(".css"))
for prop in sorted(set(re.findall(r"(--[\w-]+)\s*:", page_text))):
    if not re.search(rf"var\(\s*{re.escape(prop)}\b|['\"]{re.escape(prop)}['\"]", page_text):
        add(S, "CSS custom properties nothing uses", "1", "regex", prop)
css_no_comments = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
for cls in sorted(set(re.findall(r"\.([a-zA-Z][\w-]*)(?=[\s,:{.\[>+~)])", css_no_comments))):
    built = any(
        re.search(
            rf"""['"`\s]{re.escape(cls[: i + 1])}['"`]\s*\+|"""
            rf"""{re.escape(cls[: i + 1])}\$\{{""",
            markup_js,
        )
        for i, ch in enumerate(cls)
        if ch == "-"
    )
    if not built and not re.search(rf"(?<![\w-]){re.escape(cls)}(?![\w-])", markup_js):
        add(S, "CSS classes no page or script uses", "1", "regex", f".{cls}")

IMPORT_NAME = {
    "python-dotenv": "dotenv",
    "python-dateutil": "dateutil",
    "scikit-learn": "sklearn",
    "beautifulsoup4": "bs4",
    "pyyaml": "yaml",
    "schwab-py": "schwab",
    "python-multipart": "multipart",
    "uvicorn[standard]": "uvicorn",
    "import-linter": "importlinter",
    "pytest-xdist": "xdist",
    "pytest-timeout": "pytest_timeout",
    "pytest-asyncio": "pytest_asyncio",
}
CLI = {
    "import-linter": "lint-imports",
    "pytest-xdist": " -n ",
    "pytest-cov": "--cov",
    "ruff": "ruff",
    "pytest": "pytest",
    "uvicorn": "uvicorn",
}
top_imports = {name.split(".")[0] for name in imports_of}
ci_text = "\n".join(
    TEXT[x]
    for x in FILES
    if x in TEXT
    and (x.startswith(".github/") or x in ("Makefile", "pyproject.toml", ".pre-commit-config.yaml"))
)
for req in [
    r
    for r in ("requirements.txt", "requirements-dev.txt", "tools/census/requirements.txt")
    if r in TEXT
]:
    for ln in TEXT[req].splitlines():
        pkg = re.split(r"[<>=!~;\s\[]", ln.strip(), maxsplit=1)[0]
        if not pkg or pkg.startswith(("#", "-")):
            continue
        mod = (
            IMPORT_NAME[pkg.lower()]
            if pkg.lower() in IMPORT_NAME
            else pkg.lower().replace("-", "_")
        )
        cli = CLI[pkg.lower()] if pkg.lower() in CLI else pkg
        needed_by = re.search(
            r"(?m)^Required-by: (.+)$", run([PY, "-m", "pip", "show", pkg], stdout_only=True)
        )
        census_runs = req.startswith("tools/census/")
        if not (
            mod in top_imports or needed_by or cli in ci_text or cli in entry_text or census_runs
        ):
            add(
                S,
                "Python packages required that nothing imports, needs or runs",
                "1",
                "requirements + pip show",
                f"{req}: {pkg}",
            )
#: what a JavaScript package is used by: every text file but the manifests and their locks, which
#: name every package they hold (a script, a config or a workflow that runs it names it), and the
#: manifest's own scripts
js_used = "\n".join(
    t for f, t in TEXT.items() if not f.endswith(("package.json", "package-lock.json"))
)
for pj_path in [p for p in FILES if p.endswith("package.json")]:
    manifest = json.loads(TEXT[pj_path])
    scripts = "\n".join(manifest.get("scripts", {}).values())
    for section in [s for s in ("dependencies", "devDependencies") if s in manifest]:
        for dep in [d for d in manifest[section] if d not in js_used and d not in scripts]:
            add(S, "JS packages required but never used (check each)", "1", pj_path, dep)
index = TEXT["static/index.html"]
for f in [f for f in PAGE_ALL if f != "static/index.html"]:
    if Path(f).name not in index and Path(f).name not in page_text.replace(index, ""):
        add(S, "page files index.html never loads", "1", "regex", f)

SERVING = (
    "server.py",
    "live_market_plane.py",
    "calc/liquidity_value_engine.py",
    "calc/terrain_engine.py",
    "calc/confluence_composite.py",
    "calc/liquidity_models.py",
)
served = {
    (k.value, f)
    for f in SERVING
    if f in trees
    for node in ast.walk(trees[f])
    if isinstance(node, ast.Dict)
    for k in node.keys
    if isinstance(k, ast.Constant)
    and isinstance(k.value, str)
    and re.fullmatch(r"[a-z][a-z0-9_]{2,}", k.value)
}
all_product_py = "\n".join(TEXT[f] for f in PRODUCT_PY)
#: a key the page names or a procedure (a skill) checks is read
key_readers = page_text + "\n".join(TEXT[f] for f in FILES if f.endswith("SKILL.md") and f in TEXT)
for key, f in sorted(served):
    if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", key_readers):
        continue
    uses = len(
        re.findall(
            rf"""["']{re.escape(key)}["']|\.{re.escape(key)}\b|"""
            rf"""\b{re.escape(key)}=|\b{re.escape(key)}: """,
            all_product_py,
        )
    )
    if uses <= sum(1 for k2, _ in served if k2 == key):
        add(
            S,
            "keys built that nothing reads: no page, no other code",
            "1",
            "ast+regex",
            f"{f}: {key}",
        )

# =============================================================================================
# D. AGENTS.md RULES with a pattern a machine can find
# =============================================================================================
log.info("census: D")
S = "D. Rules"
#: the page's drawing modules (AGENTS.md rule 4, eslint.config.mjs DRAWING): their arithmetic is
#: where a value is placed and how long it is drawn, and they order what they draw
DRAWING = ("static/js/ed-draw.js", "static/js/ed-tv-chart.js")
lines_matching(
    [f for f in PAGE_JS if f not in DRAWING],
    [
        (r"\.sort\(", "page computes: .sort("),
        (r"\.reduce\(", "page computes: .reduce("),
    ],
    S,
    "4",
    "regex",
    skip_comment=True,
)
#: the drawing module writes the pixels and percents it places things by as text; a number the
#: screen shows is formatted on the server (AGENTS.md rule 13), so the chart's axis price counts
lines_matching(
    [f for f in PAGE_JS if f != "static/js/ed-draw.js"],
    [
        (
            r"\.toFixed\(|\.toLocaleString\(|Intl\.NumberFormat|\.toPrecision\(",
            "page formats numbers",
        ),
    ],
    S,
    "4",
    "regex",
    skip_comment=True,
)
lines_matching(
    PAGE_JS,
    [
        (
            r"\bDate\.now\(|new Date\(|\.getTime\(\)|performance\.now\(",
            "page reads the clock or does date math",
        ),
    ],
    S,
    "4",
    "regex",
    skip_comment=True,
)
JS_KIND = {
    # a parse sees `+` and `<`, not whether a call returns text or what a comparison chooses:
    # each item is read by hand
    "value-arithmetic": "page computes: math on values (acorn parse; check each)",
    "value-compare": "page computes: compares values to choose (acorn parse; check each)",
    "math-call": "page computes: Math.* calls (acorn parse)",
    "layout-arithmetic": "page layout arithmetic, pixels and positions (reported)",
}
for cat in JS_KIND.values():
    add(S, cat, "4", "acorn")
ROUNDING = "a value rounded to digits in product Python (rounding only on screen)"
FORMATTED = "a date, time or number formatted outside its one formatter: Python product (ENF-11)"
#: State is the one in-memory store (docs/ARCHITECTURE.md): a container, or an object of the
#: module's own class, made at a module's top level outside state/ is a table that never changes
#: or state a call may change unseen by its caller
HELD_OUTSIDE_STATE = "values a module holds at its top level, outside state/ (check each)"
#: size is counted and never judged (AGENTS.md, Fix what you find): a long function or file is a
#: prompt to ask whether it does one thing, and no code is reshaped only to meet a count
#: the lengths past which a product function and a product file are listed, each a count for a
#: person to read, never a gate (AGENTS.md: size is not a rule)
LONG_FUNCTION_LINES, LONG_FILE_LINES = 80, 1000
LONG_FUNCTIONS = f"product functions over {LONG_FUNCTION_LINES} lines (reported)"
LONG_FILES = f"product files over {LONG_FILE_LINES:,} lines (reported)"
CONTAINERS = {"dict", "list", "set", "defaultdict", "deque", "OrderedDict", "Counter"}
for cat, rule, tool in (
    (FORMATTED, "13", "ast"),
    ("clock time typed in code", "8", "ast"),
    ("prose in code: history, dates, PRs, incidents", "1", "regex"),
    (LONG_FUNCTIONS, "1", "ast"),
    ("public functions returning a plain dict, not a typed record", "12", "ast"),
    ("global statements (module state changed at run time)", "11", "ast"),
    (HELD_OUTSIDE_STATE, "11", "ast"),
    ("a ticker typed into code (every ticker treated the same; check each)", "7", "ast"),
    (LONG_FILES, "1", "wc"),
    ("computing functions not in docs/derived_register.md (check each)", "First gate 2", "ast"),
    (ROUNDING, "5", "ast"),
):
    add(S, cat, rule, tool)
parsed = subprocess.run(
    ["node", str(CENSUS / "census_js.mjs"), *PAGE_JS],
    cwd=REPO,
    capture_output=True,
    text=True,
    encoding="utf-8",
    check=True,
)
for ln in parsed.stdout.splitlines():
    d = json.loads(ln)
    kind = "layout-arithmetic" if Path(d["file"]).as_posix() in DRAWING else d["kind"]
    add(S, JS_KIND[kind], "4", "acorn", f"{d['file']}:{d['line']}: {d['text']}")
#: an em dash standing where a value is drawn (rule 5 draws '-'): a string that is only the dash,
#: an element whose text is only the dash, or an element's text that ends in one after a label;
#: a dash inside a sentence is prose, not a value
lines_matching(
    PAGE_ALL,
    [
        (
            "(['\"`])\u2014\\1|>\\s*\u2014\\s*<|>[^<>]*\\s\u2014\\s*<",
            "page draws an em dash where rule 5 says '-'",
        )
    ],
    S,
    "5",
    "regex",
)
CLOCK = re.compile(r"(?<![\d.:\[])(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?![\d:\]])")


def called_name(call):
    func = call.func
    return (
        func.attr
        if isinstance(func, ast.Attribute)
        else (func.id if isinstance(func, ast.Name) else "")
    )


for f in PRODUCT_PY:
    docs = {
        id(n.body[0].value)
        for n in ast.walk(trees[f])
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    for node in ast.walk(trees[f]):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docs
            and CLOCK.search(node.value)
            and not re.fullmatch(r"[%\w\s:./-]*%[HIM][^\n]*", node.value)
        ):
            add(
                S, "clock time typed in code", "8", "ast", f"{f}:{node.lineno}: {node.value[:80]!r}"
            )
        if (
            isinstance(node, ast.Call)
            and called_name(node) == "time"
            and len(node.args) >= 2
            and all(isinstance(a, ast.Constant) and isinstance(a.value, int) for a in node.args[:2])
        ):
            add(
                S, "clock time typed in code", "8", "ast", f"{f}:{node.lineno}: {ast.unparse(node)}"
            )
        parts = (
            [node.left, *node.comparators]
            if isinstance(node, ast.Compare)
            else [node.left, node.right]
            if isinstance(node, ast.BinOp)
            else []
        )
        if any(
            isinstance(p, ast.Attribute) and p.attr in ("hour", "minute") for p in parts
        ) and any(isinstance(p, ast.Constant) and isinstance(p.value, int) for p in parts):
            add(
                S, "clock time typed in code", "8", "ast", f"{f}:{node.lineno}: {ast.unparse(node)}"
            )
        # round(x, ndigits) drops digits from a value; round(x) alone is an index or a count
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "round"
            and len(node.args) + len(node.keywords) == 2
        ):
            add(S, ROUNDING, "5", "ast", f"{f}:{node.lineno}: {ast.unparse(node)[:100]}")
        # one formatter per format (rule 13): a date or a time is written by time_et, a number
        # to set digits or with thousands by numeric_contract
        if (
            f != "time_et.py" and isinstance(node, ast.Call) and called_name(node) == "strftime"
        ) or (
            f != "numeric_contract.py"
            and isinstance(node, ast.FormattedValue)
            and node.format_spec is not None
            and re.search(r"\.\d+[fe%]|,", ast.unparse(node.format_spec))
        ):
            add(S, FORMATTED, "13", "ast", f"{f}:{node.lineno}: {ast.unparse(node)[:100]}")
by_line("clock time typed in code", " | ")
lines_matching(
    PAGE_JS,
    [
        (
            r"""['"`][^'"`]*(?<![\d.:\[])(?:[01]?\d|2[0-3]):[0-5]\d(?![\d:\]])[^'"`]*['"`]""",
            "clock time typed in page code",
        ),
        (r"\.get(?:UTC)?(?:Hours|Minutes)\(\)\s*[<>=!]=?\s*\d", "clock time typed in page code"),
    ],
    S,
    "8",
    "regex",
    skip_comment=True,
)
lines_matching(
    [f for f in PRODUCT_PY if f != "time_et.py"],
    [
        (
            r"\b(?:datetime|dt)\.(?:datetime\.)?(?:now|utcnow|today)\(|\bdate\.today\(",
            "clock read outside time_et.py",
        ),
        (
            r"\btime\.(?:time|monotonic|perf_counter|time_ns|monotonic_ns)\(",
            "clock read outside time_et.py",
        ),
        (r"\btime_et\.(?:now|elapsed)", "clock taken (must be an entry point; check each)"),
    ],
    S,
    "11",
    "regex",
    skip_comment=True,
)


def enclosing(f, line):
    """Return the innermost function holding `line`, marked when it is a route."""
    holders = sorted(
        (
            n
            for n in ast.walk(trees[f])
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.lineno <= line <= n.end_lineno
        ),
        key=lambda n: n.lineno,
    )
    names = [
        n.name + (" [route]" if any("app." in ast.unparse(d) for d in n.decorator_list) else "")
        for n in holders
    ]
    return names[-1] if names else "<module>"


for key in [k for k in rows if k[1].startswith("clock taken")]:
    rows[key].items = [
        f"{it} in {enclosing(it.split(':')[0], int(it.split(':')[1]))}" for it in rows[key].items
    ]
lines_matching(
    PRODUCT_PY,
    [
        (
            r"^\s*(import sqlite3|from sqlite3)",
            "modules using sqlite3 (target: Recorder and startup loader)",
        )
    ],
    S,
    "6",
    "regex",
)
lines_matching(
    PRODUCT_PY,
    [
        (
            r"(?:client\(\)|\bclient)\.(get_quotes?|get_option_chain|"
            r"get_price_history\w*|get_market_hours?|get_movers|"
            r"get_instruments?|get_option_expiration_chain)\s*\(",
            "REST requests to Schwab (each for what the stream does not send)",
        )
    ],
    S,
    "3",
    "regex",
    skip_comment=True,
)
# history: a date, a work item, a pull request, an incident, or what code once was; "no longer"
# and "the operator asked" describe today's behavior (a contract no longer held, the pan the
# person at the screen asked for), so they are not history
HISTORY = re.compile(
    r"\b20\d\d-\d\d-\d\d\b|\boperator 20\d\d|\boperator ruled|\bRC-\d+|\bPR ?#?\d+|"
    r"(?<![\w&])#\d{3,}\b|\bincident\b|\bused to\b|\bpreviously\b|"
    r"\bwas (?:removed|replaced|changed)",
    re.I,
)
for f in [f for f in PRODUCT_PY + PAGE_JS if f in TEXT]:
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        s = ln.strip()
        comment = s.startswith(("#", "//", "*")) or "  # " in ln or " // " in ln
        if comment and HISTORY.search(s):
            add(
                S,
                "prose in code: history, dates, PRs, incidents",
                "1",
                "regex",
                f"{f}:{n}: {s[:140]}",
            )
for f, n, name, length, _node in func_index:
    if area(f) == "product" and length > LONG_FUNCTION_LINES:
        add(S, LONG_FUNCTIONS, "1", "ast", f"{f}:{n} {name} ({length} lines)")
for f in [f for f in PRODUCT_PY if not f.startswith("state/")]:
    made = CONTAINERS | {n.name for n in trees[f].body if isinstance(n, ast.ClassDef)}
    for node in trees[f].body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        called = isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
        if isinstance(value, (ast.Dict, ast.List, ast.Set)) or (called and value.func.id in made):
            add(S, HELD_OUTSIDE_STATE, "11", "ast", f"{f}:{node.lineno} {ast.unparse(node)[:100]}")
TICKER = re.compile(
    r"^\$?(?:SPX|SPY|QQQ|IWM|NVDA|TSLA|AMD|META|AAPL|MSFT|AMZN|GOOGL?|NDX|VIX|"
    r"DJI|COMPX|VXN|RVX|RUT|DJX|XSP|OEX)$"
)
#: where Schwab's own dicts are read: Feed's folder (docs/ARCHITECTURE.md §1) and the two root
#: modules every part takes a Schwab field through. A frame or a contract there is Schwab's JSON
#: as received, each shape checked where it is read (rule 2), not a record of ours
FEED = ("feed/", "option_contract.py", "numeric_contract.py")
#: a return annotation that is a record held as a plain dict, alone or in a list or tuple: a bare
#: dict, or one keyed by `str` whose values are anything (`Any`) or plain values of several kinds,
#: the fixed field names a TypedDict types (PEP 589). A dict whose values are all of one named type
#: or one container (dict[str, LookBack], dict[str, list[str]]), or whose key may be None, maps a
#: ticker, a service or an expiry to its value (mypy: dict[K, V]), and is not a record.
SCALAR = r"(?:float|int|str|bool|None)"
RECORD_AS_DICT = (
    rf"(?:(?:list|tuple)\[)?(?:dict|Dict)(?:\[str, (?:Any|{SCALAR}(?: \| {SCALAR})*)\]|$|\]| \|)"
)
for f in PRODUCT_PY:
    for node in ast.walk(trees[f]):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            r = ast.unparse(node.returns)
            # A map keyed by strike or expiry (dict[float, ...]) is a map too.
            if (
                re.match(RECORD_AS_DICT, r)
                and not node.name.startswith("_")
                and not f.startswith(FEED)
            ):
                add(
                    S,
                    "public functions returning a plain dict, not a typed record",
                    "12",
                    "ast",
                    f"{f}:{node.lineno} {node.name} -> {r}",
                )
        if isinstance(node, ast.Global):
            add(
                S,
                "global statements (module state changed at run time)",
                "11",
                "ast",
                f"{f}:{node.lineno} global {', '.join(node.names)}",
            )
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and TICKER.match(node.value)
        ):
            add(
                S,
                "a ticker typed into code (every ticker treated the same; check each)",
                "7",
                "ast",
                f"{f}:{node.lineno}: {node.value!r}",
            )
by_line("a ticker typed", ", ")
lines_matching(
    PAGE_JS,
    [
        (
            r"""["'](?:\$?SPX|SPY|QQQ|IWM|NVDA|TSLA|AMD|META|AAPL|MSFT|AMZN|GOOGL?|NDX|VIX)["']""",
            "a ticker typed into page code (every ticker treated the same; check each)",
        )
    ],
    S,
    "7",
    "regex",
    skip_comment=True,
)
for f in [f for f in PRODUCT_PY + PAGE_JS if f in TEXT and TEXT[f].count("\n") > LONG_FILE_LINES]:
    add(S, LONG_FILES, "1", "wc", f"{f} ({TEXT[f].count(chr(10)):,} lines)")
register = TEXT["docs/derived_register.md"]
for f, n, name, _length, _node in func_index:
    if (
        area(f) == "product"
        and name.lstrip("_").startswith(("compute_", "bs_", "pick_"))
        and name not in register
    ):
        add(
            S,
            "computing functions not in docs/derived_register.md (check each)",
            "First gate 2",
            "ast",
            f"{f}:{n} {name}",
        )

# =============================================================================================
# E. TESTS (rules 9, 14, 15; requirement: real data only)
# =============================================================================================
log.info("census: E")
S = "E. Tests"
#: a test of product code no Schwab value reaches (a page's connection, the operator's watchlist)
#: is marked so (AGENTS.md rule 9, the operator's decision) and listed by name, reported
NO_SCHWAB_VALUE = "pytestmark = pytest.mark.no_schwab_value"
NO_SCHWAB_VALUE_ROW = "tests of product code no Schwab value reaches, marked so (reported)"
TEST_FILES = [
    f for f in FILES if area(f) == "tests" and lang(f) in ("Python", "JavaScript") and f in TEXT
]
for cat, rule, tool in (
    (
        "loose tolerances in tests (above one part in a million; each needs its reason)",
        "9/15",
        "regex",
    ),
    ("test functions with no assert of their own (check each)", "14", "ast"),
    ("tests of product code that use no captured Schwab data", "9", "ast"),
    ("rails: production and credentials guarded, no Schwab data needed (reported)", "9", "ast"),
    (NO_SCHWAB_VALUE_ROW, "9", "ast"),
    ("fixtures no test names", "1", "regex"),
):
    add(S, cat, rule, tool)
lines_matching(
    TEST_FILES,
    [
        (
            r"monkeypatch\.|mock\.patch|@patch\b|patch\.object|unittest\.mock|MagicMock|\bMock\(",
            "patching lines in tests",
        ),
        (
            r"\bclass\s+\w*(Fake|Stub|Dummy|StandIn|Mock)\w*|\bdef\s+_?(fake|stub|dummy)_\w*",
            "stand-ins in tests",
        ),
        (
            check_integrity.MARKERS.pattern,
            "skip or deferred-work markers (check_integrity's own definition)",
        ),
    ],
    S,
    "9/15",
    "regex",
)
# a test that assigns over a name of a product module it imported (`calc.spot = ...`, or setattr)
# patches the code it tests as surely as a patching tool; an object's state set as the program sets
# it (`ofs.FEED.on_tick = ...`) is not a module's name
ASSIGNED_OVER = "tests that assign over a product module's name (a patch, rule 9)"
add(S, ASSIGNED_OVER, "9", "ast")
PRODUCT_TOPS = {f.split("/")[0].removesuffix(".py") for f in PRODUCT_PY}
for f in [f for f in TEST_FILES if f in trees]:
    bound = set()  # the names the test binds to the product: each module or name it imports
    for node in ast.walk(trees[f]):
        if isinstance(node, ast.Import):
            bound |= {
                a.asname or a.name.split(".")[0]
                for a in node.names
                if a.name.split(".")[0] in PRODUCT_TOPS
            }
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None  # a relative import names no module
            and node.module.split(".")[0] in PRODUCT_TOPS
        ):
            bound |= {a.asname or a.name for a in node.names}
    for node in ast.walk(trees[f]):
        if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            owners = [t.value for t in targets if isinstance(t, ast.Attribute)]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
        ):
            owners = node.args[:1]
        else:
            continue
        if any(isinstance(o, ast.Name) and o.id in bound for o in owners):
            add(S, ASSIGNED_OVER, "9", "ast", f"{f}:{node.lineno}: {ast.unparse(node)[:120]}")


# a test waits on its cause, or polls for it with a deadline (tests.shared_helpers.until): a sleep
# outside a poll's loop, but a yield (sleep(0)), is a fixed wait (Fowler, "Eradicating
# Non-Determinism in Tests"); a child program's own code, a string to the test, is not the test's.
# A sleep whose time is the condition tested (an idle connection, a slow consumer) stays, labeled
# INDUCED on its line (.claude/rules/tests.md): each is listed, reported, not a fixed wait
def spans_of(lines):
    """Return line numbers, in order, written as runs: `3, 7-9`."""
    spans = []
    for n in lines:
        if spans and n == spans[-1][1] + 1:
            spans[-1][1] = n
        else:
            spans.append([n, n])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in spans)


UNRUN = "statements no test runs (coverage.py, pytest.yml's run of this commit)"
#: a side of an `if`, a loop or a `match` no test takes (pytest.yml's `--cov-branch`), each
#: `from->to` as coverage.py names it, a negative `to` leaving the function
UNTAKEN = "branches no test takes (coverage.py, pytest.yml's run of this commit)"
if _args.coverage is None:
    add(S, f"{UNRUN}: not counted, no coverage report given (reported)", "14", "coverage.py")
else:
    measured = json.loads(_args.coverage.read_text(encoding="utf-8"))["files"]
    with_branches = all("missing_branches" in cov for cov in measured.values())
    if not with_branches:
        add(
            S, f"{UNTAKEN}: not counted, the report has no branches (reported)", "14", "coverage.py"
        )
    missed = {UNRUN: collections.Counter(), UNTAKEN: collections.Counter()}
    for a in ("product", "tools"):
        for cat in (UNRUN, UNTAKEN) if with_branches else (UNRUN,):
            add(S, f"{cat}: Python {a}", "14", "coverage.py")
    for f, cov in sorted(measured.items()):
        if f not in TEXT:
            continue
        if cov["missing_lines"]:
            missed[UNRUN][area(f)] += len(cov["missing_lines"])
            add(
                S,
                f"{UNRUN}: Python {area(f)}",
                "14",
                "coverage.py",
                f"{f}: {len(cov['missing_lines'])} of {cov['summary']['num_statements']}: "
                + spans_of(cov["missing_lines"]),
            )
        if with_branches and cov["missing_branches"]:
            missed[UNTAKEN][area(f)] += len(cov["missing_branches"])
            add(
                S,
                f"{UNTAKEN}: Python {area(f)}",
                "14",
                "coverage.py",
                f"{f}: {len(cov['missing_branches'])} of {cov['summary']['num_branches']}: "
                + ", ".join(f"{src}->{dst}" for src, dst in cov["missing_branches"]),
            )
    for cat, by_area in missed.items():
        for a, n in by_area.items():
            add(S, f"{cat}: Python {a}", "14", "coverage.py", count=n)
# the page's own scripts as Chromium ran them in the browser tests (tests/e2e/fixtures/test.js):
# a line with code holding no character V8 ran; a comment line is not code
PAGE_UNRUN = "page lines no browser test runs (V8 coverage, pytest.yml's browser tests)"
if _args.page_coverage is None:
    add(S, f"{PAGE_UNRUN}: not counted, no page coverage given (reported)", "14", "V8")
else:
    ran = collections.defaultdict(set)
    for p in sorted(_args.page_coverage.glob("*.json")):
        for f, lines in json.loads(p.read_text(encoding="utf-8")).items():
            ran[f] |= set(lines)
    add(S, PAGE_UNRUN, "14", "V8")
    missed_total = 0
    for f in PAGE_JS:
        code = {
            n
            for n, ln in enumerate(TEXT[f].splitlines(), 1)
            if ln.strip() and not ln.strip().startswith(("//", "/*", "*"))
        }
        missed = sorted(code - ran[f])
        missed_total += len(missed)
        if missed:
            add(S, PAGE_UNRUN, "14", "V8", f"{f}: {len(missed)} of {len(code)}: {spans_of(missed)}")
    add(S, PAGE_UNRUN, "14", "V8", count=missed_total)
# mutation testing (mutmut, .github/workflows/mutation.yml, every Saturday on main): a mistake put
# in a Calculator that no test catches shows a test too weak. Read from the newest run of main
# that finished: each module's score, and every mutant that survived
MUTANTS = "mutants no test kills (mutmut, the newest Mutation run of main)"
SCORES = "mutation scores by module (mutmut, the newest Mutation run of main) (reported)"
finished = json.loads(
    run(
        [
            *("gh", "run", "list", "--workflow", "mutation.yml", "--branch", "main"),
            *("--status", "completed", "--limit", "1", "--json", "databaseId,headSha"),
        ],
        stdout_only=True,
        again=command.GITHUB_WAITS,
    )
)
if not finished:
    add(S, f"{MUTANTS}: not counted, no run of main has finished (reported)", "14", "mutmut")
else:
    measured = LINT / "mutation"
    if measured.exists():
        shutil.rmtree(measured)
    run(
        [
            *("gh", "run", "download", finished[0]["databaseId"], "--pattern", "mutmut-*"),
            *("--dir", measured),
        ],
        again=command.GITHUB_WAITS,
    )
    add(S, MUTANTS, "14", "mutmut")
    add(S, SCORES, "14", "mutmut")
    of_run = f"run {finished[0]['databaseId']}, {finished[0]['headSha'][:8]}"
    for stats in sorted(measured.glob("mutmut-*/mutmut-cicd-stats.json")):
        module = stats.parent.name.removeprefix("mutmut-")
        s = json.loads(stats.read_text(encoding="utf-8"))
        add(
            S,
            SCORES,
            "14",
            "mutmut",
            f"{module}: {s['killed']} killed, {s['survived']} survived, {s['no_tests']} with no "
            f"test, {s['timeout']} timed out ({of_run})",
        )
        survivors = stats.parent / "survivors.txt"
        for line in survivors.read_text(encoding="utf-8").splitlines():
            if line.strip().endswith(": survived"):
                add(
                    S,
                    MUTANTS,
                    "14",
                    "mutmut",
                    f"{module}: {line.strip().removesuffix(': survived')}",
                )
FIXED_WAITS = "fixed waits in tests: a sleep that is not a poll's interval (timing that can flake)"
INDUCED_WAITS = "sleeps labeled INDUCED, their time the condition tested (reported)"
add(S, FIXED_WAITS, "9/15", "ast")
add(S, INDUCED_WAITS, "9/15", "ast")
for f, t in trees.items():
    if area(f) != "tests":
        continue
    polled = {id(c) for w in ast.walk(t) if isinstance(w, ast.While) for c in ast.walk(w)}
    lines = TEXT[f].splitlines()
    for c in ast.walk(t):
        if (
            isinstance(c, ast.Call)
            and ast.unparse(c.func).split(".")[-1] == "sleep"
            and id(c) not in polled
            and not (c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == 0)
        ):
            row = INDUCED_WAITS if "INDUCED" in lines[c.lineno - 1] else FIXED_WAITS
            add(S, row, "9/15", "ast", f"{f}:{c.lineno}: {ast.unparse(c)}")
#: pytest.approx's default relative tolerance, one part in a million
PYTEST_APPROX_REL = 1e-6
for f in [f for f in TEST_FILES if f.endswith(".py")]:
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        if not re.search(r"pytest\.approx\(|\babs=\s*[\d.]|\brel=\s*[\d.]", ln):
            continue
        tols = [float(x) for x in re.findall(r"\b(?:abs|rel)=\s*([\d.]+(?:e-?\d+)?)", ln)]
        if any(t > PYTEST_APPROX_REL for t in tols):
            add(
                S,
                "loose tolerances in tests (above one part in a million; each needs its reason)",
                "9/15",
                "regex",
                f"{f}:{n}: {ln.strip()[:120]}",
            )
        else:
            add(
                S,
                "tight tolerances in tests, pytest's default or tighter (reported)",
                "9",
                "regex",
                f"{f}:{n}",
            )
helpers_that_check = {
    (f, n.name)
    for f, t in trees.items()
    if area(f) == "tests"
    for n in ast.walk(t)
    if isinstance(n, ast.FunctionDef)
    and not n.name.startswith("test_")
    and any(isinstance(x, ast.Assert) for x in ast.walk(n))
}


def checks(f, node):
    """Return whether the test asserts, expects a raise, or calls its file's helper that asserts."""
    return any(
        isinstance(x, ast.Assert)
        or (
            isinstance(x, ast.Call)
            and isinstance(x.func, ast.Name)
            and (f, x.func.id) in helpers_that_check
        )
        or (
            isinstance(x, ast.Attribute)
            and (x.attr in ("raises", "warns", "fail") or x.attr.startswith(("assert", "check")))
        )
        or (isinstance(x, ast.Name) and x.id.startswith(("assert", "check")))
        for x in ast.walk(node)
    )


for f, n, name, _length, node in func_index:
    if area(f) == "tests" and name.startswith("test_") and not checks(f, node):
        add(
            S,
            "test functions with no assert of their own (check each)",
            "14",
            "ast",
            f"{f}:{n} {name}",
        )
all_tests = "\n".join(TEXT[f] for f in TEST_FILES)
product_mods = {f[:-3].replace("/", ".") for f in PRODUCT_PY}
CAPTURED = r"fixtures?[/\\\"']|FIXTURE|captured|real_chains|real_\w+\.json"


def test_module(node):
    """Return the file of the test module an import statement takes names from, or None."""
    if not isinstance(node, ast.ImportFrom) or node.module is None:
        return None
    if not node.module.startswith("tests."):
        return None
    path = f"{node.module.replace('.', '/')}.py"
    return path if path in trees else None


@functools.cache
def captured_names(f):
    """Return the top-level names of test module `f` that hold or read captured Schwab data.

    A name whose own code reads a fixture, one imported from a test module where it does, or one
    that uses such a name of the same module.
    """
    tops = {}
    found = set()
    for node in trees[f].body:
        named = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        names = [node.name] if isinstance(node, named) else []
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
        for name in names:
            tops[name] = node
        if (source := test_module(node)) and source != f:
            found |= {a.asname or a.name for a in node.names} & captured_names(source)
    found |= {n for n, node in tops.items() if re.search(CAPTURED, ast.unparse(node))}
    while True:
        more = {
            n
            for n, node in tops.items()
            if n not in found
            and any(isinstance(x, ast.Name) and x.id in found for x in ast.walk(node))
        }
        if not more:
            return found
        found |= more


def uses_captured_data(f):
    """Return whether test file `f` reads a fixture, or imports a test module's name that does."""
    if re.search(CAPTURED, TEXT[f]):
        return True
    return any(
        (source := test_module(node)) and {a.name for a in node.names} & captured_names(source)
        for node in ast.walk(trees[f])
    )


for f in [
    f
    for f in TEST_FILES
    if f.endswith(".py") and "def test_" in TEXT[f] and not uses_captured_data(f)
]:
    imported = {n for n, us in imports_of.items() if f in us}
    hits = {
        m for m in imported if m in product_mods or any(m.startswith(p + ".") for p in product_mods)
    }
    if check_tests_serve_app.RAIL in TEXT[f]:
        # a rail guards production or the credentials, not an app value (.claude/rules/tests.md)
        add(
            S,
            "rails: production and credentials guarded, no Schwab data needed (reported)",
            "9",
            "ast",
            f,
        )
    elif NO_SCHWAB_VALUE in TEXT[f]:
        add(S, NO_SCHWAB_VALUE_ROW, "9", "ast", f)
    elif hits:
        add(
            S,
            "tests of product code that use no captured Schwab data",
            "9",
            "ast",
            f"{f} (imports {', '.join(sorted(hits))[:120]})",
        )
    else:
        add(S, "tests of tools and guards, no Schwab data needed (reported)", "9", "ast", f)
for f in [f for f in FILES if f.startswith("tests/fixtures/")]:
    if not any(x in all_tests for x in (Path(f).name, Path(f).stem, Path(f).parent.name)):
        add(S, "fixtures no test names", "1", "regex", f)
add(
    S,
    "test Python and JS lines (reported)",
    "size",
    "wc",
    count=sum(TEXT[f].count("\n") for f in TEST_FILES),
)
add(
    S,
    "product Python lines (reported)",
    "size",
    "wc",
    count=sum(TEXT[f].count("\n") for f in PRODUCT_PY),
)
add(
    S,
    "page JS lines (reported)",
    "size",
    "wc",
    count=sum(TEXT[f].count("\n") for f in PAGE_JS if f in TEXT),
)
add(
    S,
    "test functions (reported)",
    "size",
    "ast",
    count=sum(1 for f, _, n, _, _ in func_index if area(f) == "tests" and n.startswith("test_")),
)

# =============================================================================================
# F. DATABASES (Standard of care: records stand; one Recorder; nothing kept without a job)
# =============================================================================================
log.info("census: F")
S = "F. Databases"
# a column named only where its table is created is written and read by nothing
product_use = re.sub(r"(?is)CREATE TABLE IF NOT EXISTS \w+ \(.*?\n\s*\);", "", all_product_py)
product_use = re.sub(r"(?is)CREATE (?:UNIQUE )?INDEX[^;]*;", "", product_use)
if not MACHINE:
    add(S, f"the database, its tables and data/: {NOT_HERE}", "6", "db.inventory")
for name in ("ed.db",) if MACHINE else ():
    p = DATA / name
    for cat, rule in (
        (f"tables no product code reads or writes ({name})", "1/6"),
        (f"indexes on tables nothing uses ({name})", "1/6"),
        (f"columns no product code names ({name})", "1/6"),
        (f"columns stamped by SQLite's own clock ({name})", "11"),
    ):
        add(S, cat, rule, "db.inventory")
    for t in db.inventory(p):
        named = re.search(
            rf"""(?i)\b(?:from|into|update|table(?:\s+if\s+not\s+exists)?|join)"""
            rf"""\s+["'`]?{re.escape(t.name)}\b|["']{re.escape(t.name)}["']""",
            all_product_py,
        )
        if not named:
            add(
                S,
                f"tables no product code reads or writes ({name})",
                "1/6",
                "db.inventory",
                f"{t.name} ({t.rows:,} rows)",
            )
            for i in t.indexes:
                add(
                    S,
                    f"indexes on tables nothing uses ({name})",
                    "1/6",
                    "db.inventory",
                    f"{name}:{i} on {t.name}",
                )
            continue
        add(
            S, "tables in use (reported)", "6", "db.inventory", f"{name}:{t.name} ({t.rows:,} rows)"
        )
        for c in t.columns:
            if not re.search(rf"\b{re.escape(c.name)}\b", product_use):
                add(
                    S,
                    f"columns no product code names ({name})",
                    "1/6",
                    "db.inventory",
                    f"{name}:{t.name}.{c.name}",
                )
            if c.default_sql is not None and "now" in c.default_sql.lower():
                add(
                    S,
                    f"columns stamped by SQLite's own clock ({name})",
                    "11",
                    "db.inventory",
                    f"{name}:{t.name}.{c.name} DEFAULT {c.default_sql}",
                )
#: the database, SQLite's two files beside it, and the program's lock (program_lock.owner_lock_path)
DB_FILES = re.compile(r"ed\.(db(-wal|-shm)?|lock)")
if MACHINE:
    add(S, "files under data/ that are not the database", "6", "ls")
for p in [p for p in sorted(DATA.iterdir()) if not DB_FILES.fullmatch(p.name)] if MACHINE else []:
    size = (
        sum(x.stat().st_size for x in p.rglob("*") if x.is_file())
        if p.is_dir()
        else p.stat().st_size
    )
    add(
        S,
        "files under data/ that are not the database",
        "6",
        "ls",
        f"data/{p.name}{'/' if p.is_dir() else ''} ({size / 1e9:.2f} GB)",
    )

# =============================================================================================
# G. REPOSITORY STATE (production checkout == origin/main; nothing left lying around)
# =============================================================================================
log.info("census: G")
S = "G. Repository"
# every file on disk that git does not hold, one by one (tracked files are the rest of the census)
THIRD_PARTY = re.compile(
    r"(^|/)(\.venv|node_modules)/|__pycache__/|\.pyc$|"
    r"(^|/)\.(mypy|pytest|ruff)_cache/|^tools/census/\.lint/"
)
RUNTIME = re.compile(
    r"^(\.env|\.runtime/|logs/|test-results/|schwab_token\.json|"
    r"\.claude/(settings\.local\.json|launch\.json|scheduled_tasks\.lock|"
    r"worktrees/)|\.cursor/cache/)"
)
for cat, rule, tool in (
    ("remote branches", "housekeeping", "git branch -r"),
    ("open pull requests", "housekeeping", "gh pr list"),
    ("tracked data, logs or binaries outside tests/fixtures", "1", "git ls-files"),
    ("documents naming a file that does not exist", "Close the change", "regex"),
    *(
        (
            (
                "tracked code importing a file git does not hold (runs unreviewed)",
                "Authority",
                "ast",
            ),
            ("worktrees", "housekeeping", "git worktree"),
            ("local branches", "housekeeping", "git branch"),
            ("stashes", "housekeeping", "git stash"),
        )
        if MACHINE
        else ()
    ),
):
    add(S, cat, rule, tool)
if not MACHINE:
    add(
        S,
        f"worktrees, local branches, stashes and files on disk git does not hold: {NOT_HERE}",
        "housekeeping",
        "git",
    )
if MACHINE:
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    ignored = git("ls-files", "--others", "--ignored", "--exclude-standard").splitlines()
    add(
        S,
        "files on disk git does not hold, all of them, by extension below (reported)",
        "Authority",
        "git ls-files",
        count=sum(
            1
            for p in untracked + ignored
            if not THIRD_PARTY.search(p) and not p.startswith("data/") and not RUNTIME.search(p)
        ),
    )
    loose_py = []
    for kind, paths in (("untracked", untracked), ("ignored", ignored)):
        for p in [p for p in paths if not THIRD_PARTY.search(p) and not p.startswith("data/")]:
            if RUNTIME.search(p):
                add(S, "runtime files the program or tools keep (reported)", "Authority", "git", p)
            else:
                add(
                    S,
                    f"files on disk git does not hold ({kind}), extension '{Path(p).suffix}'",
                    "Authority",
                    "git ls-files",
                    p,
                )
                loose_py += [p] if p.endswith(".py") else []
    add(
        S,
        "packages and caches on disk, not ours (reported)",
        "size",
        "git ls-files",
        count=sum(1 for p in ignored if THIRD_PARTY.search(p)),
    )
    loose_mods = {p[:-3].replace("/", ".") for p in loose_py} | {Path(p).stem for p in loose_py}
    for name, users in imports_of.items():
        for f in [u for u in users if name in loose_mods]:
            add(
                S,
                "tracked code importing a file git does not hold (runs unreviewed)",
                "Authority",
                "ast",
                f"{f}: {name}",
            )
    for ln in git("worktree", "list").splitlines()[1:]:
        add(S, "worktrees", "housekeeping", "git worktree", ln.split()[0] + " " + ln.split()[-1])
    for ln in git(
        "for-each-ref", "refs/heads", "--format=%(refname:short) %(committerdate:short)"
    ).splitlines():
        if not ln.startswith("main "):
            add(S, "local branches", "housekeeping", "git branch", ln)
    for ln in git("stash", "list").splitlines():
        add(S, "stashes", "housekeeping", "git stash", ln)
# GitHub's own branches, asked of it, not the tracking refs a checkout has kept
for ln in git("ls-remote", "--heads", "origin").splitlines():
    if ln.split("\t")[1] != "refs/heads/main":
        add(
            S,
            "remote branches",
            "housekeeping",
            "git ls-remote",
            ln.split("\t")[1].replace("refs/heads/", "origin/"),
        )
# every dependency pinned to one version, and none with a known vulnerability: pip-audit over
# every requirements file, npm audit over every lockfile (the bank's standard, Standard of care 11)
UNPINNED = "dependencies not pinned to one version"
VULNERABLE = "dependencies with a known vulnerability (pip-audit, npm audit)"
for cat in (UNPINNED, VULNERABLE):
    add(S, cat, "Standard of care 11", "pip-audit + npm audit")
pinned = []
for f in [f for f in FILES if re.fullmatch(r"(.*/)?requirements[\w-]*\.txt", f)]:
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        req = ln.split("#")[0].strip()
        if req.startswith("-") or not req:
            continue
        if "==" in req:
            pinned.append(req)
        else:
            add(S, UNPINNED, "Standard of care 11", "requirements", f"{f}:{n}: {req}")
(LINT / "pinned.txt").write_text("\n".join(sorted(set(pinned))) + "\n", encoding="utf-8")
# a package installed only because a pinned one needs it is pinned nowhere: the next install may
# take another version (pip-audit: "fully hash your pinned dependencies"; pip-tools' pip-compile)
TRANSITIVE = "dependencies installed but pinned in no requirements file (taken as a library needs)"
add(S, TRANSITIVE, "Standard of care 11", "pip freeze")
named = {re.split(r"[=<>!~\[ ]", p)[0].lower().replace("_", "-") for p in pinned}
for ln in run([PY, "-m", "pip", "freeze"], stdout_only=True).splitlines():
    if "==" in ln and ln.split("==")[0].lower().replace("_", "-") not in named:
        add(S, TRANSITIVE, "Standard of care 11", "pip freeze", ln)
audit = run(
    [PY, "-m", "pip_audit", "--disable-pip", "--no-deps", "-r", LINT / "pinned.txt", "-f", "json"],
    stdout_only=True,
    ok=(0, 1),  # a known vulnerability found 1
)
for dep in json.loads(audit)["dependencies"]:
    for v in dep["vulns"]:
        add(
            S,
            VULNERABLE,
            "Standard of care 11",
            "pip-audit",
            f"{dep['name']}=={dep['version']}: {v['id']} (fixed in {', '.join(v['fix_versions'])})",
        )
for f in [f for f in FILES if f.endswith("package-lock.json")]:
    out = run(
        [exe("npm"), "audit", "--package-lock-only", "--json"],
        cwd=(HEAD / f).parent,
        stdout_only=True,
        ok=(0, 1),  # a known vulnerability found 1
    )
    for name, v in json.loads(out)["vulnerabilities"].items():
        add(
            S,
            VULNERABLE,
            "Standard of care 11",
            "npm audit",
            f"{f}: {name} ({v['severity']}): "
            + "; ".join(x["title"] if isinstance(x, dict) else f"through {x}" for x in v["via"])[
                :150
            ],
        )
for pr in json.loads(
    run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,title,isDraft,updatedAt",
        ],
        stdout_only=True,
        again=command.GITHUB_WAITS,
    )
):
    add(
        S,
        "open pull requests",
        "housekeeping",
        "gh pr list",
        f"#{pr['number']} {'DRAFT ' if pr['isDraft'] else ''}{pr['updatedAt'][:10]} "
        f"{pr['title'][:100]}",
    )
for f in [f for f in FILES if area(f) in OUTSIDE and area(f) != "docs"]:
    add(S, f"tracked files outside the program: {area(f)}/", "1", "git ls-files", f)
for f in [
    f
    for f in FILES
    if f.endswith((".log", ".xlsx", ".pkl", ".joblib", ".db", ".parquet", ".zip"))
    and not f.startswith("tests/fixtures/")
]:
    add(S, "tracked data, logs or binaries outside tests/fixtures", "1", "git ls-files", f)
for f in [f for f in FILES if f.endswith(".md") and f in TEXT]:
    for m in re.finditer(
        r"`([\w./-]+/[\w.-]+\.(?:py|js|mjs|md|toml|yml|json|bat|css|html))`", TEXT[f]
    ):
        named = m.group(1)
        # a path git ignores is a file of the machine's own (the agent's settings, a log), named
        # for what it is wherever it is not
        ignored_by_git = run(
            ["git", "check-ignore", "--no-index", named], stdout_only=True, ok=(0, 1)
        )  # ignored 0, not ignored 1
        if not (REPO / named).exists() and not ignored_by_git:
            add(
                S,
                "documents naming a file that does not exist",
                "Close the change",
                "regex",
                f"{f}: {named}",
            )


@functools.cache
def bound(f):
    """Return the names module `f` binds at its top: what `module.name` can mean."""
    names = set()
    stack = list(trees[f].body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names |= {a.name.split(".")[0] for a in node.names if a.asname is None}
            names |= {a.asname for a in node.names if a.asname is not None}
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names |= {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
        else:
            stack += [c for c in ast.iter_child_nodes(node) if isinstance(c, ast.stmt)]
    return names


# each module by its dotted name and, where no other module shares it, by its last part, as the
# rules write `check_locks.FREE`
MODULES = {f[:-3].replace("/", ".").removesuffix(".__init__"): f for f in trees}
stems = collections.Counter(m.rsplit(".", 1)[-1] for m in MODULES)
MODULES |= {
    m.rsplit(".", 1)[-1]: f for m, f in list(MODULES.items()) if stems[m.rsplit(".", 1)[-1]] == 1
}
CODE_NAME = re.compile(r"`([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)(?:\([^`]*\))?`")
#: a name ending in a tracked file's suffix (`launch.py`, `config.yml`) is a file, checked above
SUFFIXES = {Path(f).suffix[1:] for f in FILES}
add(S, "documents naming code that does not exist", "Close the change", "ast")
for f in [f for f in FILES if f.endswith(".md") and f in TEXT]:
    for m in CODE_NAME.finditer(TEXT[f]):
        parts = m.group(1).split(".")
        # the longest leading part that is a module; the next part is a name it binds or a module
        mod = next(
            (
                ".".join(parts[:i])
                for i in range(len(parts) - 1, 0, -1)
                if ".".join(parts[:i]) in MODULES
            ),
            None,
        )
        if mod is None or parts[-1] in SUFFIXES:
            continue
        name = parts[len(mod.split("."))]
        if name not in bound(MODULES[mod]) and f"{mod}.{name}" not in MODULES:
            add(
                S,
                "documents naming code that does not exist",
                "Close the change",
                "ast",
                f"{f}: {m.group(1)}",
            )

# =============================================================================================
# M. THE RUNNING PROGRAM (Standard of care 7: nothing disappears silently, no error is hidden)
# =============================================================================================
log.info("census: M")
S = "M. The running program"
FAILURE = re.compile(r"(?i)\b(error|exception|failed|refused|ended|dropping|stalled|timed out)\b")
#: the daemon's line for each REST request it sent (feed.schwab_client), its answer's code and the
#: Central times it was sent and answered
REQUEST_LINE = re.compile(
    r"REQUEST \w+ (?P<path>\S+).*? -> (?P<code>\d{3}) \(sent (?P<sent>\d\d:\d\d:\d\d\.\d+) CT, "
    r"answered (?P<answered>\d\d:\d\d:\d\d\.\d+) CT\)(?P<rest>.*)"
)
#: the reference Akamai, Schwab's edge, gives a request it blocks (its 403 page's "Reference #")
AKAMAI_REFERENCE = re.compile(r"Reference\s*#\s*([\w.]+)")
if not MACHINE:
    add(S, f"the program's log: {NOT_HERE}", "7", "the daemon's log")
else:
    # the newest day's log (runtime_layout.daemon_log_path), each kind of failure once with its
    # count: a traceback's last line, or a line that says a failure; the once-a-minute status
    # line ("alive | ...") reports counts ("0 failed"), each failure logged on its own line
    newest = sorted((REPO / "logs").glob("stream_capture.????-??-??.log"))[-1]
    KINDS = f"failures in the program's log, by kind ({newest.name}; each explained or fixed)"
    add(S, KINDS, "7", "the daemon's log")
    kinds = collections.Counter()
    for ln in newest.read_text(encoding="utf-8", errors="replace").splitlines():
        stamped = re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+ (.*)", ln)
        said = stamped.group(1) if stamped else ln
        last_line = not stamped and re.match(r"[\w.]+(Error|Exception|Refused)\b", ln)
        if last_line or (stamped and FAILURE.search(said) and not said.startswith("alive |")):
            kinds[re.sub(r"\d+(\.\d+)?", "#", said)[:110]] += 1
    for said, n in kinds.most_common():
        add(S, KINDS, "7", "the daemon's log", f"{n:,} x {said}")
    # the record of the newest regular session that has ended, its window Schwab's /markets
    # answer (time_et.record_markets): each watchlist ticker's minutes with no quote received
    # (Standard of care 6 and 7), Schwab's quote time to its receipt and the stream's longest
    # silences (Standard of care 5: how live the screen is gets measured)
    ED = DATA / "ed.db"
    ended = [
        s
        for s in [
            time_et.record_markets(json.loads(a))
            for (a,) in db.stored_rows(
                ED,
                "stream_markets_raw",
                "SELECT native_json FROM stream_markets_raw WHERE status = 200 AND date <= ? "
                "ORDER BY date, ts_recv",
                TODAY,
            )
        ]
        if s.is_open and s.regular and s.regular[-1][1].timestamp() <= NOW
    ]
    start, end = ended[-1].regular[0][0].timestamp(), ended[-1].regular[-1][1].timestamp()
    ((listed,),) = db.stored_rows(
        ED,
        "stream_watchlist",
        "SELECT tickers_json FROM stream_watchlist WHERE ts_recv <= ? ORDER BY ts_recv DESC "
        "LIMIT 1",
        end,
    )
    day = ended[-1].day
    GAPS = f"minutes of the {day} regular session with no quote received for a watchlist ticker"
    DELAY = f"the stream's delay on {day}, Schwab's quote time to receipt, by ticker (reported)"
    SILENT = f"the stream's ten longest silences in the {day} regular session (reported)"
    add(S, GAPS, "6/7", "ed.db stream_quotes_raw")
    heard = collections.defaultdict(set)
    delays = collections.defaultdict(list)
    silences = []
    before = start
    for sym, at, sent in db.stored_rows(
        ED,
        "stream_quotes_raw",
        "SELECT symbol, ts_recv, schwab_ts FROM stream_quotes_raw WHERE ts_recv >= ? AND "
        "ts_recv < ? ORDER BY ts_recv",
        start,
        end,
    ):
        heard[sym].add(int((at - start) // 60))
        if sent is not None:
            delays[sym].append(at - sent / 1000)
        silences.append((at - before, before))
        before = at
    silences.append((end - before, before))
    for sym in json.loads(listed):
        missed = sorted(set(range(int((end - start) // 60))) - heard[sym])
        for m in missed:
            add(
                S,
                GAPS,
                "6/7",
                "ed.db stream_quotes_raw",
                f"{sym} {time_et.ct_time(start + 60 * m)}",
            )
        took = sorted(delays[sym])
        if took:
            add(
                S,
                DELAY,
                "5",
                "ed.db stream_quotes_raw",
                f"{sym}: {len(took):,} quotes, median {took[len(took) // 2]:.3f} s, 99th "
                f"percentile {took[int(len(took) * 0.99)]:.3f} s, worst {took[-1]:.3f} s",
            )
    for gap, began in sorted(silences, reverse=True)[:10]:
        add(S, SILENT, "5", "ed.db stream_quotes_raw", f"{gap:.1f} s from {time_et.ct_time(began)}")
    # what Schwab's REST was asked in that session and how it answered, from the daemon's own
    # line for each request in that day's log: how many a minute and of each endpoint, and each
    # answer that was not 200 with the requests in flight when it was sent and those sent in the
    # minute before (rule 3: the next is sent as each answer is taken)
    RATES = f"REST requests in the {day} regular session, a minute and by endpoint (reported)"
    REFUSED = f"REST answers other than 200 in the {day} regular session (reported)"
    add(S, RATES, "3", "the daemon's log")
    add(S, REFUSED, "3", "the daemon's log")
    asked = []
    for m in REQUEST_LINE.finditer(
        (REPO / "logs" / f"stream_capture.{day}.log").read_text(encoding="utf-8", errors="replace")
    ):
        sent, answered = (
            dt.datetime.fromisoformat(f"{day}T{m[k]}").replace(tzinfo=time_et.CT).timestamp()
            for k in ("sent", "answered")
        )
        if start <= sent < end:
            asked.append(
                (
                    sent,
                    answered,
                    int(m["code"]),
                    m["path"].rsplit("/", 1)[-1],
                    AKAMAI_REFERENCE.search(m["rest"]),
                )
            )
    asked.sort()
    sends, answers = [a[0] for a in asked], sorted(a[1] for a in asked)
    flying = [i - bisect.bisect_right(answers, s) for i, s in enumerate(sends)]
    if not asked:
        add(S, RATES, "3", "the daemon's log", "no request in the session")
    else:
        minutes = sorted(collections.Counter(int((s - start) // 60) for s in sends).values())
        tens = collections.Counter(int((s - start) // 10) for s in sends)
        add(
            S,
            RATES,
            "3",
            "the daemon's log",
            f"{len(asked):,} requests: a minute, median {minutes[len(minutes) // 2]} and most "
            f"{minutes[-1]}; in 10 s, most {max(tens.values())}; most in flight {max(flying)}",
        )
    for endpoint, n in collections.Counter(a[3] for a in asked).most_common():
        add(S, RATES, "3", "the daemon's log", f"{endpoint}: {n:,}")
    for (sent, _answered, code, endpoint, ref), now_flying in zip(asked, flying, strict=True):
        if code != HTTPStatus.OK:
            before = bisect.bisect_left(sends, sent) - bisect.bisect_left(sends, sent - 60)
            said = (
                f"{code} {endpoint} sent {time_et.ct_time(sent)}: {now_flying} in flight, "
                f"{before} sent in the 60 s before"
            )
            if ref:
                said += f", Akamai reference {ref[1]}"
            add(S, REFUSED, "3", "the daemon's log", said)

# =============================================================================================
# H. GOVERNANCE AND WORK LIST
# =============================================================================================
log.info("census: H")
S = "H. Governance"
for cat, rule, tool in (
    ("requirements with no machine check", "ENF-12", "regex"),
    ("required CI on main not green", "Before saying done", "gh run list"),
    (
        "hand-built check tools (each until a standard tool does its job: STANDARD-CHECKS)",
        "1",
        "ls",
    ),
):
    add(S, cat, rule, tool)
#: a work item, `- ID (STATE...): ...`
WORK_ITEM = re.compile(r"^- ([A-Za-z][\w -]*?) \(([A-Z ]+)[^)]*\):", re.M)
WORK = [m.groups() for m in WORK_ITEM.finditer(TEXT["ACTIVE_PROGRAM.md"])]
add(
    S,
    "open work rows, every status, by status below (reported)",
    "work list",
    "ACTIVE_PROGRAM.md",
    count=len(WORK),
)
for f in ["AGENTS.md", "CLAUDE.md", "docs/DATA_FLOW.md"] + [
    f for f in FILES if f.startswith(".claude/rules/")
]:
    # read across line breaks: a wrapped paragraph may break the phrase, or the work item that
    # builds its check (ENF-12, STANDARD-CHECKS, CENSUS), between two lines
    for m in re.finditer(
        r"no\s+machine\s+check(?:[\s,—–-]+(?:ENF-\d+|[A-Z]{2,}(?:-[A-Z]+)*\b))?", TEXT[f]
    ):
        line = TEXT[f].count("\n", 0, m.start()) + 1
        add(
            S,
            "requirements with no machine check",
            "ENF-12",
            "regex",
            f"{f}:{line}: {' '.join(m.group(0).split())[:110]}",
        )
for item, status in WORK:
    add(S, f"open work rows: {status.strip()}", "work list", "ACTIVE_PROGRAM.md", item)
# each workflow's newest finished run on main: a run still going has no result yet, and the
# census's own run and the suites started with it on the same commit are still going
latest = {}
for r_ in json.loads(
    run(
        [
            "gh",
            "run",
            "list",
            "--branch",
            "main",
            "--status",
            "completed",
            "--limit",
            "20",
            "--json",
            "workflowName,conclusion,headSha,createdAt",
        ],
        stdout_only=True,
        again=command.GITHUB_WAITS,
    )
):
    latest.setdefault(r_["workflowName"], r_)
for wf, r_ in latest.items():
    if r_["conclusion"] not in ("success", "skipped"):
        add(
            S,
            "required CI on main not green",
            "Before saying done",
            "gh run list",
            f"{wf}: {r_['conclusion']} at {r_['headSha'][:8]} {r_['createdAt']}",
        )
# a package's __init__.py makes its folder importable; it is no tool
for f in [f for f in FILES if f.startswith("tools/") and f.endswith(".py") and "__init__" not in f]:
    add(
        S,
        "hand-built check tools (each until a standard tool does its job: STANDARD-CHECKS)",
        "1",
        "ls",
        f,
    )
for f in [f for f in FILES if f.startswith((".claude/", ".cursor/"))]:
    add(S, "agent configuration files (reported)", "size", "ls", f)

# =============================================================================================
# J. EVERY OTHER LANGUAGE: each with its standard checker, recommended settings (configs beside
# this file), over every tracked file, run on the commit copy in .lint/head
# =============================================================================================
log.info("census: J")
S = "J. Other languages"


def rel(p):
    p = str(p).replace("\\", "/")
    h = str(HEAD).replace("\\", "/")
    return p[len(h) + 1 :] if p.lower().startswith(h.lower()) else p.removeprefix("./")


def reconcile(name, own_total, prefix, tool):
    """Record whether the census's count of a checker's findings equals the checker's own total.

    The two must be equal. The row carries the checker's tool name, so it also shows the checker
    ran: a rule of it with no row found nothing.
    """
    ours = sum(r.count for k, r in rows.items() if k[0] == S and k[1].startswith(prefix))
    if own_total == ours:
        add(
            S,
            f"{name}: census count equals its own total (reported)",
            "census",
            tool,
            count=own_total,
        )
    else:
        add(
            S,
            f"{name}: findings the census did not read (census error)",
            "census",
            tool,
            f"{name} reports {own_total}, the census read {ours}",
        )


for cat, tool in (
    ("files Prettier cannot parse", "prettier"),
    ("TOML: taplo lint errors", "taplo"),
    ("TOML: files taplo would format", "taplo"),
    ("JSON files that do not parse", "json.tool"),
    ("files no installed checker reads (checked by hand)", "none"),
    ("tracked files of a kind no check reads", "git ls-files"),
):
    add(S, cat, "13/LINTERS", tool)


def json_findings(name, cmd, ok):
    """Return a checker's JSON report, written to a file by the checker's own output option.

    A Node tool's report sent through a pipe can lose its end when the tool exits (seen in CI: html-
    validate's cut at 15,992 characters). `cmd` holds `{out}` where the report file goes; `ok` the
    tool's exit codes when it ran (run).
    """
    report_file = LINT / f"{name}.json"
    run([str(c).replace("{out}", str(report_file)) for c in cmd], cwd=HEAD, ok=ok)
    return json.loads(report_file.read_text(encoding="utf-8"))


report = json_findings(
    "eslint",
    [exe("eslint"), "--config", CENSUS / "eslint.config.mjs", "-f", "json", "-o", "{out}", "."],
    ok=(0, 1),  # findings 1; a fatal or configuration error 2
)
for fr in report:
    for msg in fr["messages"]:
        rule = msg["ruleId"] if msg["ruleId"] else "parse error"
        add(
            S,
            f"JavaScript: ESLint {rule}",
            "13/LINTERS",
            "eslint recommended",
            f"{rel(fr['filePath'])}:{msg['line']}: {msg['message'][:110]}",
        )
reconcile(
    "ESLint",
    sum(fr["errorCount"] + fr["warningCount"] for fr in report),
    "JavaScript: ESLint",
    "eslint recommended",
)
report = json_findings(
    "stylelint",
    [
        exe("stylelint"),
        "static/**/*.css",
        "--config",
        CENSUS / "stylelint.config.json",
        "--config-basedir",
        CENSUS,
        "-f",
        "json",
        "-o",
        "{out}",
    ],
    ok=(0, 2),  # findings 2; a fatal error 1, a bad command 64, a bad configuration 78
)
for fr in report:
    for w in fr["warnings"]:
        add(
            S,
            f"CSS: Stylelint {w['rule']}",
            "13/LINTERS",
            "stylelint standard",
            f"{rel(fr['source'])}:{w['line']}: {w['text'][:110]}",
        )
reconcile(
    "Stylelint",
    sum(len(fr["warnings"]) for fr in report),
    "CSS: Stylelint",
    "stylelint standard",
)
report = json_findings(
    "html-validate",
    [
        exe("html-validate"),
        "--config",
        CENSUS / "htmlvalidate.config.json",
        "-f",
        "json={out}",
        *[f for f in FILES if f.endswith(".html")],
    ],
    ok=(0, 1),  # findings 1
)
for fr in report:
    for msg in fr["messages"]:
        add(
            S,
            f"HTML: html-validate {msg['ruleId']}",
            "13/LINTERS",
            "html-validate recommended",
            f"{rel(fr['filePath'])}:{msg['line']}: {msg['message'][:110]}",
        )
reconcile(
    "html-validate",
    sum(fr["errorCount"] + fr["warningCount"] for fr in report),
    "HTML: html-validate",
    "html-validate recommended",
)
PRETTIER_KINDS = (
    "js",
    "mjs",
    "css",
    "html",
    "json",
    "jsonc",
    "md",
    "mdc",
    "yml",
    "yaml",
    "webmanifest",
)
add(
    S,
    "files Prettier checked (reported)",
    "13",
    "prettier",
    count=sum(
        1
        for f in FILES
        if f.rsplit(".", 1)[-1] in PRETTIER_KINDS
        and not f.startswith(("static/vendor/", "tests/fixtures/"))
        and not f.endswith("package-lock.json")
    ),
)
for ln in run(
    [
        exe("prettier"),
        "--list-different",
        "**/*.{js,mjs,css,html,json,jsonc,md,mdc,yml,yaml,webmanifest}",
        "!static/vendor/**",
        "!tests/fixtures/**",
        "!**/package-lock.json",
    ],
    cwd=HEAD,
    ok=(0, 1, 2),  # files to format 1; a file it cannot parse 2, each its own [error] line below
).splitlines():
    if ln.startswith("[error]"):
        add(S, "files Prettier cannot parse", "13/LINTERS", "prettier", ln[:200])
    elif ln.strip():
        add(
            S,
            f"files Prettier would format: {Path(ln.strip()).suffix}",
            "13/LINTERS",
            "prettier",
            ln.strip(),
        )
out = run(
    [
        exe("markdownlint-cli2"),
        "--config",
        CENSUS / ".markdownlint-cli2.jsonc",
        "**/*.md",
        "**/*.mdc",
        "#node_modules",
        "#static/vendor",
    ],
    cwd=HEAD,
    ok=(0, 1),  # findings 1; a failure 2
)
# each finding as markdownlint-cli2 0.24 prints it: "<file>:<line>[:<col>] error MD026/<name> ..."
for ln in out.splitlines():
    if m := re.match(r"(.+?):(\d+)(?::\d+)? error (MD\d+)/([\w/-]+) (.+)", ln):
        add(
            S,
            f"Markdown: markdownlint {m.group(3)} {m.group(4).split('/')[0]}",
            "13/LINTERS",
            "markdownlint",
            f"{m.group(1)}:{m.group(2)}: {m.group(5)[:110]}",
        )
reconcile(
    "markdownlint",
    int(re.search(r"Summary: (\d+) issues? in", out).group(1)),
    "Markdown: markdownlint",
    "markdownlint",
)
tomls = [HEAD / f for f in FILES if f.endswith(".toml")]
add(S, "TOML files taplo checked (reported)", "13", "taplo", count=len(tomls))
for ln in run([exe("taplo"), "lint", *tomls], ok=(0, 1)).splitlines():
    if "ERROR" in ln and "operation failed" not in ln:
        add(S, "TOML: taplo lint errors", "13/LINTERS", "taplo", ln.strip()[:200])
for ln in run([exe("taplo"), "fmt", "--check", *tomls], ok=(0, 1)).splitlines():
    if m := re.search(r'not properly formatted path="([^"]+)"', ln):
        add(S, "TOML: files taplo would format", "13/LINTERS", "taplo", rel(m.group(1)))
out = run(
    [exe("yamllint"), "-c", CENSUS / "yamllint.config.yml", "-f", "parsable", "."],
    cwd=HEAD,
    stdout_only=True,
    ok=(0, 1),  # an error found 1
)
for ln in out.splitlines():
    if m := re.match(r"(.+?):(\d+):\d+: \[(\w+)\] (.+) \(([\w-]+)\)$", ln):
        add(
            S,
            f"YAML: yamllint {m.group(5)}",
            "13/LINTERS",
            "yamllint",
            f"{rel(m.group(1))}:{m.group(2)}: {m.group(4)[:110]}",
        )
reconcile("yamllint", sum(1 for x in out.splitlines() if x.strip()), "YAML: yamllint", "yamllint")
wfs = [f for f in FILES if f.startswith(".github/workflows/")]
out = run([exe("actionlint"), "-oneline", *wfs], cwd=HEAD, stdout_only=True, ok=(0, 1))
for ln in out.splitlines():
    if m := re.match(r"(.+?):(\d+):\d+: (.+) \[([\w-]+)\]$", ln):
        add(
            S,
            f"Workflows: actionlint {m.group(4)}",
            "13/LINTERS",
            "actionlint",
            f"{rel(m.group(1))}:{m.group(2)}: {m.group(3)[:110]}",
        )
reconcile(
    "actionlint",
    sum(1 for x in out.splitlines() if x.strip()),
    "Workflows: actionlint",
    "actionlint",
)
add(S, "workflow files actionlint checked (reported)", "13", "actionlint", count=len(wfs))
BATCH = [f for f in FILES if lang(f) == "Batch"]
# SQL is a language of the repository too: each statement written in a Python string, which no
# SQL checker reads (sqlfluff reads .sql files)
SQL = re.compile(r"\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|PRAGMA|WITH|REPLACE)\s")
for a in ("product", "tools", "tests"):
    add(S, f"SQL statements in Python strings, read by no SQL checker: {a}", "13/LINTERS", "ast")
for f in [f for f in ALL_PY if "vendor" not in f]:
    for node in ast.walk(trees[f]):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and SQL.match(node.value):
            add(
                S,
                f"SQL statements in Python strings, read by no SQL checker: {area(f)}",
                "13/LINTERS",
                "ast",
                f"{f}:{node.lineno}: {' '.join(node.value.split())[:100]}",
            )
add(S, "batch files Blinter checked (reported)", "13", "blinter", count=len(BATCH))
for f in BATCH:
    # Blinter's own report: each finding with its one line, a finding seen twice twice
    # an issue at or above Blinter's --fail-on level (security, its default) exits 1
    report = json.loads(
        run([exe("blinter"), f, "--format", "json"], cwd=HEAD, stdout_only=True, ok=(0, 1))
    )
    for issue in report["issues"]:
        add(
            S,
            f"Batch: Blinter {issue['code']} {issue['name'][:50]}",
            "13/LINTERS",
            "blinter",
            f"{f}:{issue['line']}",
        )
for f in [f for f in FILES if f.endswith((".json", ".webmanifest"))]:
    r = subprocess.run(
        # UTF-8 mode: the child prints non-ASCII text, which Windows' console encoding cannot hold
        [PY, "-X", "utf8", "-m", "json.tool", "--no-ensure-ascii", HEAD / f],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode:
        add(S, "JSON files that do not parse", "13", "json.tool", f"{f}: {r.stderr.strip()[:150]}")
for f in [f for f in FILES if Path(f).name == "Makefile" or f.endswith((".mk", ".sh", ".ps1"))]:
    add(S, "files no installed checker reads (checked by hand)", "LINTERS", "none", f)
COVERED = (
    ".py",
    ".pyi",  # the type stubs: ruff, pyright and mypy's stubtest in `hardening` read them
    ".js",
    ".mjs",
    ".css",
    ".html",
    ".json",
    ".jsonc",
    ".webmanifest",
    ".md",
    ".mdc",
    ".yml",
    ".yaml",
    ".toml",
    ".bat",
    ".cmd",
)
#: data and text, not code; `.gz` is captured Schwab data kept compressed (tests/fixtures)
NOT_CODE = (
    ".txt",
    ".csv",
    ".gz",
    ".png",
    ".ico",
    ".pdf",
    ".example",
    ".gitignore",
    ".gitattributes",
)
for f in [
    f
    for f in FILES
    if not f.endswith(COVERED + NOT_CODE) and Path(f).name not in ("Makefile", "LICENSE")
]:
    add(S, "tracked files of a kind no check reads", "everything", "git ls-files", f)
add(
    S,
    "tracked data and text files, read by no code checker (reported)",
    "size",
    "git ls-files",
    count=sum(1 for f in FILES if f.endswith(NOT_CODE)),
)

# =============================================================================================
# K. WIRING AND NOISE (the first rule: Schwab -> program -> page; every value has one producer;
# code that serves no route, Schwab field or registered derived value has no job)
# =============================================================================================
log.info("census: K")
S = "K. Wiring and noise"
METHODS = ("get", "post", "put", "delete", "patch", "websocket")
routes = []  # (file, line, method, path, function)
for f in PRODUCT_PY:
    for node in ast.walk(trees[f]):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            routes += [
                (f, node.lineno, d.func.attr.upper(), d.args[0].value, node)
                for d in node.decorator_list
                if isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in METHODS
                and d.args
                and isinstance(d.args[0], ast.Constant)
                and isinstance(d.args[0].value, str)
            ]
add(S, "routes the program serves (reported)", "3", "ast", count=len(routes))
for cat in (
    "a route registered twice (one producer)",
    "routes nothing but tests names (candidates: unneeded)",
    "a product function more than one route calls (candidates: one producer)",
):
    add(S, cat, "3", "ast")
twice = collections.Counter((m, p) for _f, _n, m, p, _fn in routes)
for (m, p), n in twice.items():
    if n > 1:
        add(S, "a route registered twice (one producer)", "3", "ast", f"{m} {p} ({n} times)")
CALLERS = {
    f: TEXT[f]
    for f in FILES
    if f in TEXT and area(f) in ("product", "tools") and lang(f) in ("Python", "JavaScript", "HTML")
}
CALLERS.update({f: TEXT[f] for f in FILES if lang(f) == "Batch" and f in TEXT})
for f, n, m, p, _fn in routes:
    if p == "/" or not p.startswith(("/api", "/ws")):
        continue
    stem_path = p.split("{")[0]
    said = re.compile(re.escape(stem_path) + ("" if stem_path.endswith("/") else r"(?![\w-])"))
    if not any(said.search(t) for c, t in CALLERS.items() if c != f):
        add(
            S,
            "routes nothing but tests names (candidates: unneeded)",
            "3",
            "ast",
            f"{f}:{n} {m} {p}",
        )
defined = {
    node.name
    for f in PRODUCT_PY
    for node in ast.walk(trees[f])
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}
route_names = {fn.name for *_x, fn in routes}
by_callee = collections.defaultdict(set)
for f, n, m, p, fn in routes:
    for c in ast.walk(fn):
        if (
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Name)  # `x.get(...)` is a method, not a product function
            and (name := c.func.id) in defined - route_names
        ):
            by_callee[name].add(f"{m} {p}")
for name, served in sorted(by_callee.items()):
    if len(served) > 1:
        add(
            S,
            "a product function more than one route calls (candidates: one producer)",
            "3",
            "ast",
            f"{name}: {', '.join(sorted(served))}",
        )

MODULES = {f.removesuffix(".py").removesuffix("/__init__").replace("/", "."): f for f in PRODUCT_PY}
#: the modules a root runs with `python -m`: named in a batch file's line, or in an entry point's
#: command, a list such as ["-m", "app.market_data.schwab.streaming.capture_main"] (launch.py)
RUN_BY_M = {
    m
    for f in FILES
    if lang(f) == "Batch" and f in TEXT
    for m in re.findall(r"-m\s+([\w.]+)", TEXT[f])
} | {
    b.value
    for f in ENTRY
    if f in trees
    for n in ast.walk(trees[f])
    if isinstance(n, (ast.List, ast.Tuple))
    for a, b in zip(n.elts, n.elts[1:], strict=False)
    if isinstance(a, ast.Constant) and a.value == "-m" and isinstance(b, ast.Constant)
}
ROOTS = ENTRY | {MODULES[m] for m in RUN_BY_M if m in MODULES}
reached, todo = set(), [f for f in ROOTS if f in trees]
while todo:
    f = todo.pop()
    if f in reached:
        continue
    reached.add(f)
    pkg = f.removesuffix(".py").replace("/", ".").rsplit(".", 1)[0]
    for node in ast.walk(trees[f]):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` names no module: its package is the importing file's, `level` up
            parts = pkg.split(".")[: len(pkg.split(".")) - node.level + 1] if node.level else []
            if node.module is not None:
                parts.append(node.module)
            base = ".".join(parts)
            names = [base, *(f"{base}.{a.name}" for a in node.names)]
        for name in names:
            parts = name.strip(".").split(".")
            todo += [
                MODULES[".".join(parts[:k])]
                for k in range(1, len(parts) + 1)
                if ".".join(parts[:k]) in MODULES
            ]
add(
    S,
    f"product Python files the program loads, of {len(PRODUCT_PY)} (reported)",
    "1",
    "ast imports",
    count=len(reached & set(PRODUCT_PY)),
)
add(S, "product Python files the program never loads (not on the wire)", "1", "ast imports")
for f in sorted(set(PRODUCT_PY) - reached):
    add(
        S,
        "product Python files the program never loads (not on the wire)",
        "1",
        "ast imports",
        f"{f} ({TEXT[f].count(chr(10))} lines)",
    )
GUARDS = sorted(
    {
        m
        for f in FILES
        if f.startswith(".claude/") and f.endswith(".json") and f in TEXT
        for m in re.findall(r"tools/[\w/]+\.py", TEXT[f])
    }
)
add(
    S,
    "agent guards and hooks, lines: they restrain the agent and serve no screen (reported)",
    "size",
    "wc",
    count=sum(TEXT[g].count("\n") for g in GUARDS if g in TEXT),
)

WORK_PY = [
    (r"\bhasattr\(", "a type guessed at run time (`hasattr`)"),
    (r"except\s*\(?\s*(ImportError|ModuleNotFoundError)", "an import worked around"),
    (r"\bsys\.platform\b|\bos\.name\s*==", "a platform special case"),
    (r"\btime\.sleep\(", "timing worked around (`time.sleep`)"),
]
WORK_JS = [
    (r"\?\.", "a missing object read as undefined (`?.`)"),
    (r"typeof\s+[\w.$]+\s*[!=]==?\s*['\"]undefined['\"]", "a value guessed present (`typeof`)"),
    (r"\bsetTimeout\([^)]*,\s*\d+\s*\)", "timing worked around (`setTimeout` with a delay)"),
]
NAMED = re.compile(
    r"(?i)(#|//|/\*|\*).*\b(workaround|hack|kludge|temporar(y|ily)|for now|band-?aid|shim|"
    r"legacy|backward[- ]compat\w*)\b"
)
for f in [f for f in FILES if lang(f) in ("Python", "JavaScript", "HTML") and f in TEXT]:
    if "vendor" in f:
        continue
    # a pattern finds the shape, not whether the platform or a source requires it: each item is
    # read by hand, with its line of code, so a verdict matches only the code it was given for
    cat = f"workarounds: {lang(f)} {area(f)} (check each)"
    add(S, cat, "1", "regex")
    pats = WORK_PY if f.endswith(".py") else WORK_JS
    if area(f) == "tests":
        pats = [p for p in pats if "timing" not in p[1]]  # tests' sleeps: section E
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        code = ln.strip()[:120]
        for pat, kind in pats:
            if re.search(pat, ln):
                add(S, cat, "1", "regex", f"{f}:{n}: {kind}: {code}")
        if NAMED.search(ln):
            add(S, cat, "1", "regex", f"{f}:{n}: named a workaround by its author: {code}")
by_line("workarounds: ", "; ")

#: each read is judged by its code (decisions.json): a record of ours whose keys nothing
#: guarantees is an issue; a boundary's input read by name and checked there is not
DICT_READ = (
    "dict reads with .get by a field's name outside the Feed (check each: a dict whose keys "
    "nothing guarantees, rule 12)"
)


def field_key(node: ast.Call) -> bool:
    """Tell whether a `.get` reads a field by its name written in the code (text, or a constant).

    That dict is used as a record whose keys nothing guarantees (PEP 589: a TypedDict's fixed
    keys). A `.get` by any other key (a strike, a ticker, an id) looks it up in a map, where a key
    not held is not known.
    """
    key = node.args[0]
    if isinstance(key, ast.Constant):
        return isinstance(key.value, str)
    return isinstance(key, ast.Name) and key.id.isupper()


add(S, DICT_READ, "12", "ast")
for f in [f for f in PRODUCT_PY if not f.startswith(FEED)]:
    #: a route's decorator (`@app.get(path)`) and a queue's `get()` read no dict
    routes = {
        id(d)
        for fn in ast.walk(trees[f])
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        for d in fn.decorator_list
    }
    for node in ast.walk(trees[f]):
        if (
            isinstance(node, ast.Call)
            and called_name(node) == "get"
            and isinstance(node.func, ast.Attribute)
            and node.args
            and id(node) not in routes
            and field_key(node)
        ):
            add(S, DICT_READ, "12", "ast", f"{f}:{node.lineno}: {ast.unparse(node)[:120]}")

# the First gate's question 1: each key read in Schwab's spelling is a field on Schwab's list
# (docs/schwab_fields.csv: every field Schwab has sent); one the list lacks is our own name dressed
# as Schwab's, or a field Schwab never sent, which is never received
UNLISTED = (
    "keys read in Schwab's spelling that the field list does not hold (candidates, check each: "
    "our name, or a field Schwab never sent)"
)
LISTED = {
    row["canonical_field"].rsplit(".", 1)[-1]
    for row in csv.DictReader(io.StringIO(TEXT[check_one_reader.FIELDS_CSV]))
}
add(S, UNLISTED, "First gate 1", "check_one_reader.keys_read")
for f in PRODUCT_PY:
    for k in sorted(check_one_reader.keys_read(TEXT[f])):
        if check_one_reader.SCHWAB_SPELLING.fullmatch(k) and k not in LISTED:
            add(S, UNLISTED, "First gate 1", "check_one_reader.keys_read", f"{f}: {k}")

out = run(
    [
        PY,
        "-m",
        "ruff",
        "check",
        ".",
        "--isolated",
        "--select",
        "C901",
        "--config",
        "lint.mccabe.max-complexity = 0",
        "--output-format",
        "concise",
        "--no-cache",
        "--exit-zero",
    ]
)
#: ruff's mccabe max-complexity when none is set (McCabe's own suggested limit)
MCCABE_DEFAULT = 10
scores = collections.defaultdict(list)
for ln in out.splitlines():
    if m := re.match(r"(.+?):(\d+):\d+: C901 `(.+?)` is too complex \((\d+) > 0\)", ln):
        f = m.group(1).replace("\\", "/")
        scores[area(f)].append((int(m.group(4)), f"{f}:{m.group(2)} {m.group(3)}"))
for a, fs in sorted(scores.items()):
    add(
        S,
        f"complexity, McCabe, {a}: total (reported)",
        "1",
        "ruff C901",
        count=sum(s for s, _ in fs),
    )
    over = f"complexity, McCabe, {a}: functions over {MCCABE_DEFAULT}, ruff's default (reported)"
    add(S, over, "1", "ruff C901")
    for s, it in sorted(fs, reverse=True):
        if s > MCCABE_DEFAULT:
            add(
                S,
                over,
                "1",
                "ruff C901",
                f"{it} ({s})",
            )

out = run(
    [
        PY,
        "-m",
        "ruff",
        "check",
        ".",
        "--isolated",
        "--select",
        "D",
        "--ignore",
        "D1",  # a missing docstring: one is written only where it does work (operator 2026-11-08)
        "--config",
        'lint.pydocstyle.convention = "pep257"',
        "--output-format",
        "concise",
        "--no-cache",
        "--exit-zero",
    ]
)
for ln in out.splitlines():
    if m := re.match(r"(.+?):(\d+):\d+: (D\d+) (.*)", ln):
        f = m.group(1).replace("\\", "/")
        add(
            S,
            f"docstrings not as PEP 257 writes them: {area(f)}",
            "13",
            "ruff D (pep257)",
            f"{f}:{m.group(2)}: {m.group(3)} {m.group(4)[:100]}",
        )

# =============================================================================================
# L. FLAKY AND BROWSER TESTS (a test that passes and fails on the same code; Playwright's own)
# =============================================================================================
log.info("census: L")
S = "L. Flaky and browser tests"
FLAKY = "CI workflows that failed and passed on one commit (last 1,000 runs)"
add(S, FLAKY, "9/15", "gh run list")
runs = json.loads(
    run(
        [
            "gh",
            "run",
            "list",
            "--limit",
            "1000",
            "--json",
            "headSha,workflowName,conclusion,attempt,databaseId,event",
        ],
        stdout_only=True,
        again=command.GITHUB_WAITS,
    )
)
# A push's runs judge its commit alone. A pull request's judge GitHub's test merge of it with main
# (Locks its description too), so two runs on one head judge two inputs once either moves; a
# re-run repeats its own run's.
seen_runs = collections.defaultdict(set)
for r in runs:
    if r["event"] == "push":
        seen_runs[(r["headSha"][:8], r["workflowName"])].add(r["conclusion"])
    if r["attempt"] > 1 and r["conclusion"] == "success":
        add(
            S,
            FLAKY,
            "9/15",
            "gh run list",
            f"{r['headSha'][:8]} {r['workflowName']}: passed on re-run {r['databaseId']}",
        )
for (sha, wf), ends in sorted(seen_runs.items()):
    if {"success", "failure"} <= ends:
        add(S, FLAKY, "9/15", "gh run list", f"{sha} {wf}: failed and passed")
E2E = [f for f in FILES if f.startswith("tests/e2e/") and f.endswith((".js", ".mjs")) and f in TEXT]
lines_matching(
    E2E,
    [
        (r"waitForTimeout\(", "Playwright: fixed waits (`waitForTimeout`)"),
        (
            r"fulfill\(.*(JSON\.stringify\(\s*[\[{]|json:\s*[\[{]|body:\s*['\"`])",
            "Playwright: hand-built route answers, not captured Schwab data",
        ),
        (
            r"\btest(\.describe)?\.(skip|fixme|fail|only)\(",
            "Playwright: skipped, expected-fail or only",
        ),
    ],
    S,
    "9/15",
    "regex",
    skip_comment=True,
)
lines_matching(
    [f for f in FILES if Path(f).name.startswith("playwright.config")],
    [(r"retries:\s*[1-9]", "Playwright: retries (a failure re-run until it passes)")],
    S,
    "9/15",
    "regex",
)

# =============================================================================================
# DECISIONS (decisions.json): each item checked by hand once. A candidate moves to an issue row or
# to a reported "checked, not an issue" row with its reason; an issue at its row's design target,
# set by the rule its reason names, moves to that reported row, so every issue left is work. A
# banned name that a check in D judges line by line (the clock taken, sqlite3 in product code) is
# counted there, once.
# =============================================================================================
CANDIDATE = re.compile(r"check each|candidates|\(check\)")
REPORTED = ": checked, not an issue (reported)"
TID251 = ("B. Linters", "ruff TID251 (locks.ruff.toml, noqa ignored)")
add(*TID251, "locks/13", "ruff")
judged = {
    it.split(": ")[0]
    for k, row in rows.items()
    if k[1].startswith(("clock taken", "modules using sqlite3"))
    for it in row.items
}
for it in [it for it in rows[TID251].items if it.split(": ")[0] in judged]:
    rows[TID251].items.remove(it)
    add(TID251[0], "TID251 lines judged in D, counted there (reported)", "locks/13", "ruff", it)
# each line left is judged by its statement and the function that holds it
for i, it in enumerate(rows[TID251].items):
    f, n = it.split(":")[0], int(it.split(":")[1])
    line = TEXT[f].splitlines()[n - 1].strip()[:100]
    rows[TID251].items[i] = f"{it} | {line} in {enclosing(f, n)}"
decisions = [
    (d["verdict"], d["category"], re.compile(d["pattern"]), d["reason"])
    for d in json.loads((CENSUS / "decisions.json").read_text(encoding="utf-8"))["decisions"]
]
for key in [
    k for k in list(rows) if CANDIDATE.search(k[1]) or any(k[1].startswith(d[1]) for d in decisions)
]:
    row = rows[key]
    for verdict in (": confirmed", REPORTED) if CANDIDATE.search(key[1]) else (REPORTED,):
        add(key[0], key[1].split(" (")[0] + verdict, row.rule, row.tool + " + by hand")
    keep = []
    for it in row.items:
        hits = [d for d in decisions if key[1].startswith(d[1]) and d[2].search(it)]
        if not hits:
            keep.append(it)
            continue
        verdict = ": confirmed" if hits[0][0] == "issue" else REPORTED
        add(
            key[0],
            key[1].split(" (")[0] + verdict,
            row.rule,
            row.tool + " + by hand",
            f"{it} -- {hits[0][3]}",
        )
    row.items = keep

# =============================================================================================
# REPORT
# =============================================================================================
OUT.mkdir(parents=True, exist_ok=True)
stem = f"{TODAY}_{SHA}"
lines = [
    f"# EdWebConsole census, {TODAY}, {SHA}",
    "",
    "Run from the checkout: `python -m tools.census.census <out dir> [<data dir>]`. Every "
    f"item is in `items_{stem}.txt`. Target: every issue count 0; an item at its row's design "
    "target is reported with the rule that sets it.",
    "",
    "| Section | Category | Rule | Counted by | Count | Kind |",
    "|---|---|---|---|---|---|",
]
items_out = []
totals = collections.Counter()
cands = collections.Counter()
for (sec, cat), row in rows.items():
    n = row.count
    kinds = (("(reported)" in cat, "reported"), (bool(CANDIDATE.search(cat)), "candidate"))
    kind = next((k for hit, k in kinds if hit), "issue")
    lines.append(f"| {sec} | {cat} | {row.rule} | {row.tool} | {n:,} | {kind} |")
    totals[sec] += n if kind == "issue" else 0
    cands[sec] += n if kind == "candidate" else 0
    items_out += [f"\n## {sec} / {cat} ({n}, {kind})", *row.items]
lines += [
    "",
    "Kind: issue = each item breaks a rule, above its row's design target; candidate = each item "
    "must be checked by hand and is an issue or not; reported = a size, a check's own result or "
    "an item at its design target, no target.",
    "",
    "## Totals by section",
    "",
    "| Section | Issues | Candidates to check |",
    "|---|---|---|",
    *[f"| {s} | {totals[s]:,} | {cands[s]:,} |" for s in dict.fromkeys(k[0] for k in rows)],
    f"| ALL | {sum(totals.values()):,} | {sum(cands.values()):,} |",
]
(OUT / f"census_{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
(OUT / f"items_{stem}.txt").write_text("\n".join(items_out) + "\n", encoding="utf-8")
log.info(
    "census: %s issues, %s candidates; %s",
    f"{sum(totals.values()):,}",
    f"{sum(cands.values()):,}",
    OUT / f"census_{stem}.md",
)
