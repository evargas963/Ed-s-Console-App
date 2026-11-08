"""The census of everything in the repository that must reach 0. Read-only on the repository.

    python -m tools.census.census <out dir> [<data dir>]

Run from the checkout with the repository's Python, which also holds tools/census/requirements.txt;
`npm ci --prefix tools/census` holds the other checkers. <data dir> holds the two databases
(default data/); a checkout without them reports so. Writes <out>/census_<date>_<sha>.md (the
report) and <out>/items_<date>_<sha>.txt (every item).

Every section names the AGENTS.md rule it checks and the tool that counts it, and each checker's
own total is compared with what the census read. What no machine counts yet is in hand_found.json;
each candidate's verdict and its reason is in candidate_decisions.json. A checker whose output the
census cannot read stops the census with that error.
"""

import ast
import collections
import datetime as dt
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
from pathlib import Path

import db
import time_et
from tools import check_end_to_end as e2e
from tools import check_integrity

log = logging.getLogger("census")
REPO = Path.cwd()
OUT = Path(sys.argv[1]).resolve()
DATA = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else REPO / "data"
CENSUS = Path(__file__).resolve().parent
LINT = CENSUS / ".lint"  # the commit's tracked files, as locks.yml checks them out (`head`)
HEAD = LINT / "head"
PY = sys.executable


def exe(name):
    """A checker's program: the census's npm tools, then the running Python's scripts, then PATH."""
    for d in (CENSUS / "node_modules" / ".bin", Path(PY).parent):
        for n in (f"{name}.cmd", f"{name}.exe", name):
            if (d / n).exists():
                return str(d / n)
    found = shutil.which(name)
    if found is None:
        log.error("census: %s is not installed; see this module's docstring", name)
        raise SystemExit(1)
    return found


def run(cmd, cwd=REPO, stdout_only=False):
    r = subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    return r.stdout if stdout_only else r.stdout + r.stderr


def git(*a):
    return run(["git", *a])


SHA = git("rev-parse", "--short", "HEAD").strip()
TODAY = dt.datetime.fromtimestamp(time_et.now(), time_et.ET).date().isoformat()
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

rows = collections.OrderedDict()  # (section, category, rule, tool) -> items


def add(section, category, rule, tool, item=None, count=None):
    key = (section, category, rule, tool)
    rows.setdefault(key, [])
    if item is not None:
        rows[key].append(item)
    if count is not None:
        rows[key].append(f"__COUNT__{count}")


def lines_matching(files, patterns, section, rule, tool, skip_comment=False):
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
        for it in rows[key]:
            lines.setdefault(it.split(": ")[0], []).append(it.split(": ", 1)[-1])
        rows[key] = [f"{ln}: {joiner.join(vs)}" for ln, vs in lines.items()]


logging.basicConfig(level=logging.INFO, format="%(message)s")

# =============================================================================================
# A. CODE PATTERNS (rule 1 no patches, rule 3 one producer, rule 13 imports at the top)
# =============================================================================================
log.info("census: A")
S = "A. Code patterns"
for f in [f for f in FILES if f.endswith(e2e.SHAPED_SUFFIXES) and f in TEXT]:
    for line, kind in e2e.shapes(f, TEXT[f]):
        add(
            S,
            f"patch shapes: {lang(f)} {area(f)}",
            "1",
            "check_end_to_end.shapes",
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
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        for pat, kind in OTHER[lang(f)]:
            if re.search(pat, ln):
                add(S, f"patch shapes: {lang(f)} {area(f)}", "1", "regex", f"{f}:{n}: {kind}")
for f in NOT_UTF8:
    add(S, "text files that are not UTF-8", "13", "git grep -I", f)

out = run(
    [
        PY,
        "-m",
        "ruff",
        "check",
        ".",
        "--select",
        "PLC0415",
        "--output-format",
        "concise",
        "--no-cache",
        "--exit-zero",
        "--isolated",
    ]
)
for ln in out.splitlines():
    if m := re.match(r"(.+?):(\d+):\d+: PLC0415", ln):
        f = m.group(1).replace("\\", "/")
        add(S, f"inner imports: {area(f)}", "13", "ruff PLC0415", f"{f}:{m.group(2)}")

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
        if sum(1 for _ in ast.walk(mod)) >= 12:
            key = hashlib.sha1(ast.dump(mod, annotate_fields=False).encode()).hexdigest()
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

WIN = 8
seen = {}
for f in [
    f
    for f in FILES
    if lang(f) and lang(f) not in ("Markdown", "JSON") and "vendor" not in f and f in TEXT
]:
    lines = [(n, re.sub(r"\s+", " ", ln.strip())) for n, ln in enumerate(TEXT[f].splitlines(), 1)]
    lines = [(n, s) for n, s in lines if len(s) > 3 and not s.startswith(("#", "//", '"""'))]
    last_hit = -WIN
    for i in range(len(lines) - WIN + 1):
        h = hashlib.sha1("\n".join(s for _, s in lines[i : i + WIN]).encode()).hexdigest()
        if h in seen and seen[h][0] != (f, i) and i >= last_hit + WIN:
            add(
                S,
                f"copied blocks (8+ lines): {lang(f)} {area(f)}",
                "1",
                "line-window hash",
                f"{f}:{lines[i][0]} = {seen[h][1]}",
            )
            last_hit = i
        seen.setdefault(h, ((f, i), f"{f}:{lines[i][0]}"))


def computes(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.lstrip(
            "_"
        ).startswith(("compute_", "bs_", "pick_")):
            return True
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in ("math", "np", "numpy")
            and node.attr not in ("isfinite", "isnan", "isinf", "pi", "inf", "nan")
        ):
            return True
    return False


for f in [f for f in PRODUCT_PY if computes(trees[f])]:
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
for d in json.loads(out):
    f = Path(d["filename"]).resolve().relative_to(REPO.resolve()).as_posix()
    add(
        S,
        f"ruff {d['code']} (locks.ruff.toml, noqa ignored)",
        "locks/13",
        "ruff",
        f"{f}:{d['location']['row']}: {d['message'][:120]}",
    )
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
ruff_ours = sum(len(v) for k, v in rows.items() if k[1].startswith("ruff ") and "locks" in k[1])
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
out = run(
    [PY, "-m", "ruff", "check", ".", "--output-format", "concise", "--no-cache", "--exit-zero"]
)
for ln in out.splitlines():
    if re.match(r"(.+?):(\d+):\d+: ([A-Z]+\d+)", ln):
        add(S, "ruff findings under pyproject's selection (fail at commit)", "13", "ruff", ln)
for ln in run([PY, "-m", "ruff", "format", "--check", ".", "--no-cache"]).splitlines():
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
# an exemption marker is an opt-out wherever a hand-built check reads it: comments, docstrings,
# and the tool that honors it
lines_matching(
    [f for f in FILES if lang(f) in ("Python", "JavaScript", "HTML", "CSS") and "vendor" not in f],
    [
        (
            r"(?:#|//)\s*[a-z]+(?:-[a-z]+)*-ok\b",
            "exemption markers of hand-built checks (an opt-out the rules forbid)",
        )
    ],
    S,
    "locks",
    "regex",
)
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
out = run([exe("lint-imports"), "--config", "head/locks.imports.toml", "--no-cache"], cwd=LINT)
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
    cfg = LINT / f"pyright_{mode}.json"
    cfg.write_text(
        json.dumps(
            {
                "include": [f"head/{f}" for f in PRODUCT_PY],
                "typeCheckingMode": mode,
                "extraPaths": ["head"],
                "pythonVersion": "3.13",
            }
        ),
        encoding="utf-8",
    )
    out = run(
        [exe("pyright"), "-p", cfg, "--pythonpath", PY, "--outputjson"], cwd=LINT, stdout_only=True
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
    add(S, f"pyright {mode}-mode errors in product code", "12", f"pyright {mode}", count=len(diags))
    key = (S, f"pyright {mode}-mode errors in product code", "12", f"pyright {mode}")
    rows[key] = [
        f"{Path(d['file']).resolve().relative_to(HEAD.resolve()).as_posix()}:"
        f"{d['range']['start']['line'] + 1}: {d['message'].splitlines()[0][:120]}"
        for d in diags
    ]
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
out = run(
    [
        PY,
        "-m",
        "vulture",
        *[f for f in ALL_PY if area(f) in ("product", "tools")],
        "--min-confidence",
        "60",
    ]
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
    if name in routes or (kind == "variable" and (f, name) in param_lines):
        continue  # FastAPI calls a route by its decorator; ruff ARG counts unused parameters
    if kind == "attribute" and conf < 90:
        add(
            S,
            f"vulture: attribute set on another object in {area(f)} (candidates, check "
            "each: a library may read it)",
            "1",
            "vulture",
            item,
        )
    elif conf >= 90 or not named_again:
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
    TEXT[f] for f in FILES if f.endswith((".bat", ".toml", ".yml", ".mjs", ".ps1")) and f in TEXT
)
for f in [f for f in PRODUCT_PY if f not in ENTRY and not f.endswith("__init__.py")]:
    mod = f[:-3].replace("/", ".")
    users = {
        u
        for name, us in imports_of.items()
        if name == mod or name.startswith(mod + ".")
        for u in us
        if u != f
    }
    if not users and mod not in entry_text and Path(f).name not in entry_text:
        add(S, "product modules nothing imports or starts", "1", "ast imports", f)
    elif users and all(area(u) != "product" for u in users):
        add(
            S,
            "product modules only tests or tools import",
            "1",
            "ast imports",
            f"{f} <- {', '.join(sorted(users))[:200]}",
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

for m in re.finditer(r'@app\.(get|post|put|delete|websocket)\("([^"]+)"', TEXT["server.py"]):
    stem = m.group(2).split("{")[0].rstrip("/")
    if stem not in ("", "/favicon.ico") and stem not in page_text:
        tests_naming = sum(1 for f in FILES if area(f) == "tests" and f in TEXT and stem in TEXT[f])
        add(
            S,
            "routes the page never calls",
            "4",
            "regex",
            f"{m.group(1).upper()} {m.group(2)} (tests naming it: {tests_naming})",
        )

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
js_all = "\n".join(
    TEXT[f] for f in FILES if f.endswith((".js", ".mjs", ".json", ".yml", ".html")) and f in TEXT
)
for pj_path in [p for p in FILES if p.endswith("package.json")]:
    manifest = json.loads(TEXT[pj_path])
    for section in [s for s in ("dependencies", "devDependencies") if s in manifest]:
        for dep in [d for d in manifest[section] if js_all.count(d) <= 2]:
            add(S, "JS packages required but never used (check each)", "1", pj_path, dep)
index = TEXT["static/index.html"]
for f in [f for f in PAGE_ALL if f != "static/index.html"]:
    if Path(f).name not in index and Path(f).name not in page_text.replace(index, ""):
        add(S, "page files index.html never loads", "1", "regex", f)

SERVING = (
    "server.py",
    "push_changes.py",
    "live_market_plane.py",
    "liquidity_value_engine.py",
    "terrain_engine.py",
    "confluence_composite.py",
    "liquidity_models.py",
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
for key, f in sorted(served):
    if re.search(rf"(?<!\w){re.escape(key)}(?!\w)", page_text):
        continue
    uses = len(
        re.findall(
            rf"""["']{re.escape(key)}["']|\.{re.escape(key)}\b|"""
            rf"""\b{re.escape(key)}=""",
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
lines_matching(
    PAGE_JS,
    [
        (r"\.sort\(", "page computes: .sort("),
        (r"\.reduce\(", "page computes: .reduce("),
        (
            r"\.toFixed\(|\.toLocaleString\(|Intl\.NumberFormat|\.toPrecision\(",
            "page formats numbers",
        ),
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
    "value-arithmetic": "page computes: math on values (acorn parse)",
    "value-compare": "page computes: compares values to choose (acorn parse)",
    "math-call": "page computes: Math.* calls (acorn parse)",
    "layout-arithmetic": "page layout arithmetic, pixels and positions (reported)",
}
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
    add(S, JS_KIND[d["kind"]], "4", "acorn", f"{d['file']}:{d['line']}: {d['text']}")
lines_matching(
    PAGE_JS,
    [
        (
            r"\bfetch\(|XMLHttpRequest|EventSource|new WebSocket",
            "page transport calls (target: one module)",
        )
    ],
    S,
    "4",
    "regex",
    skip_comment=True,
)
lines_matching(
    PAGE_ALL, [("\u2014", "page draws an em dash where rule 5 says '-'")], S, "5", "regex"
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
    """The innermost function holding `line`, marked when it is a route."""
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
    rows[key] = [
        f"{it} in {enclosing(it.split(':')[0], int(it.split(':')[1]))}" for it in rows[key]
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
            "REST requests to Schwab (reported; checked 2026-11-07: each asks "
            "for what the stream does not send, but STREAM-ONE)",
        )
    ],
    S,
    "3",
    "regex",
    skip_comment=True,
)
HISTORY = re.compile(
    r"\b20\d\d-\d\d-\d\d\b|\boperator \d|\boperator ruled|"
    r"\boperator (?:said|decided|asked)|\bRC-\d+|\bPR ?#?\d+|"
    r"(?<![\w&])#\d{3,}\b|\bincident\b|\bused to\b|\bno longer\b|"
    r"\bpreviously\b|\bwas (?:removed|replaced|changed)",
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
    if area(f) == "product" and length > 80:
        add(S, "product functions over 80 lines", "1", "ast", f"{f}:{n} {name} ({length} lines)")
TICKER = re.compile(
    r"^\$?(?:SPX|SPY|QQQ|IWM|NVDA|TSLA|AMD|META|AAPL|MSFT|AMZN|GOOGL?|NDX|VIX|"
    r"DJI|COMPX|VXN|RVX|RUT|DJX|XSP|OEX)$"
)
for f in PRODUCT_PY:
    for node in ast.walk(trees[f]):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            r = ast.unparse(node.returns)
            if re.match(r"(dict|Dict|list\[dict|tuple\[dict)", r) and not node.name.startswith("_"):
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
                "a ticker typed into code (every ticker treated the same)",
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
            "a ticker typed into page code (every ticker treated the same)",
        )
    ],
    S,
    "7",
    "regex",
    skip_comment=True,
)
for f in [f for f in PRODUCT_PY + PAGE_JS if f in TEXT and TEXT[f].count("\n") > 1000]:
    add(S, "product files over 1,000 lines", "1", "wc", f"{f} ({TEXT[f].count(chr(10)):,} lines)")
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
TEST_FILES = [
    f for f in FILES if area(f) == "tests" and lang(f) in ("Python", "JavaScript") and f in TEXT
]
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
        (r"time\.sleep\(|waitForTimeout\(", "sleeps in tests (timing that can flake)"),
    ],
    S,
    "9/15",
    "regex",
)
for f in [f for f in TEST_FILES if f.endswith(".py")]:
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        if not re.search(r"pytest\.approx\(|\babs=\s*[\d.]|\brel=\s*[\d.]", ln):
            continue
        tols = [float(x) for x in re.findall(r"\b(?:abs|rel)=\s*([\d.]+(?:e-?\d+)?)", ln)]
        if any(t > 1e-6 for t in tols):
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
    """The test asserts, expects a raise, or calls a helper of its file that asserts."""
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
for f in [
    f
    for f in TEST_FILES
    if f.endswith(".py")
    and "def test_" in TEXT[f]
    and not re.search(r"fixtures?[/\\\"']|FIXTURE|captured|real_chains", TEXT[f])
]:
    imported = {n for n, us in imports_of.items() if f in us}
    hits = {
        m for m in imported if m in product_mods or any(m.startswith(p + ".") for p in product_mods)
    }
    if hits:
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
for name in ("ed_console.db", "stream_capture.db"):
    p = DATA / name
    if not p.exists():
        add(
            S,
            "databases not in this checkout: counted on the production machine (reported)",
            "6",
            "db.inventory",
            str(p),
        )
        continue
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
                    "indexes on tables nothing uses",
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
                    "columns no product code names",
                    "1/6",
                    "db.inventory",
                    f"{name}:{t.name}.{c.name}",
                )
            if c.default_sql is not None and "now" in c.default_sql.lower():
                add(
                    S,
                    "columns stamped by SQLite's own clock",
                    "11",
                    "db.inventory",
                    f"{name}:{t.name}.{c.name} DEFAULT {c.default_sql}",
                )
DB_FILES = re.compile(r"(ed_console|stream_capture)\.db(-wal|-shm)?")
for p in (
    [p for p in sorted(DATA.iterdir()) if not DB_FILES.fullmatch(p.name)] if DATA.is_dir() else []
):
    size = (
        sum(x.stat().st_size for x in p.rglob("*") if x.is_file())
        if p.is_dir()
        else p.stat().st_size
    )
    add(
        S,
        "files under data/ that are not the two databases",
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
untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
ignored = git("ls-files", "--others", "--ignored", "--exclude-standard").splitlines()
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
for ln in git("branch", "--format=%(refname:short) %(committerdate:short)").splitlines():
    if not ln.startswith("main "):
        add(S, "local branches", "housekeeping", "git branch", ln)
for ln in git("branch", "-r", "--format=%(refname:short)").splitlines():
    if ln.strip() not in ("origin/main", "origin/HEAD", "origin"):
        add(S, "remote branches", "housekeeping", "git branch -r", ln)
for ln in git("stash", "list").splitlines():
    add(S, "stashes", "housekeeping", "git stash", ln)
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
        if not (REPO / m.group(1)).exists():
            add(
                S,
                "documents naming a file that does not exist",
                "Close the change",
                "regex",
                f"{f}: {m.group(1)}",
            )

# =============================================================================================
# H. GOVERNANCE AND WORK LIST
# =============================================================================================
log.info("census: H")
S = "H. Governance"
for f in ["AGENTS.md", "CLAUDE.md", "docs/DATA_FLOW.md"] + [
    f for f in FILES if f.startswith(".claude/rules/")
]:
    for n, ln in enumerate(TEXT[f].splitlines(), 1):
        for m in re.finditer(r"no machine check[^;|]*", ln):
            add(
                S,
                "requirements with no machine check",
                "ENF-12",
                "regex",
                f"{f}:{n}: {m.group(0)[:110]}",
            )
for m in re.finditer(
    r"^\| ([A-Z][A-Z0-9-]+) \| ([A-Z][A-Z ,0-9:-]*?) \|", TEXT["ACTIVE_PROGRAM.md"], re.M
):
    if m.group(1) != "ID":
        add(S, f"open work rows: {m.group(2).strip()[:30]}", "work list", "regex", m.group(1))
latest = {}
for r_ in json.loads(
    run(
        [
            "gh",
            "run",
            "list",
            "--branch",
            "main",
            "--limit",
            "20",
            "--json",
            "workflowName,conclusion,headSha,createdAt",
        ],
        stdout_only=True,
    )
):
    latest.setdefault(r_["workflowName"], r_)
for wf, r_ in latest.items():
    if r_["conclusion"] not in ("success", "skipped"):
        state = r_["conclusion"] if r_["conclusion"] else "running"
        add(
            S,
            "required CI on main not green",
            "Before saying done",
            "gh run list",
            f"{wf}: {state} at {r_['headSha'][:8]} {r_['createdAt']}",
        )
for f in [f for f in FILES if f.startswith("tools/") and f.endswith(".py")]:
    add(S, "hand-built check tools (replaced by standard tools in SHAPE step 7)", "1", "ls", f)
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


def reconcile(name, own_total, prefix):
    """The census's count of a checker's findings must equal the checker's own total."""
    ours = sum(len(v) for k, v in rows.items() if k[0] == S and k[1].startswith(prefix))
    if own_total == ours:
        add(
            S,
            f"{name}: census count equals its own total (reported)",
            "census",
            name,
            count=own_total,
        )
    else:
        add(
            S,
            f"{name}: findings the census did not read (census error)",
            "census",
            name,
            f"{name} reports {own_total}, the census read {ours}",
        )


def json_findings(cmd, start):
    """A checker's JSON report, which begins at the first `start` character it prints."""
    out = run(cmd, cwd=HEAD)  # Stylelint writes its report to stderr
    return json.JSONDecoder().raw_decode(out[out.index(start) :])[0]


report = json_findings(
    [exe("eslint"), "--config", CENSUS / "eslint.config.mjs", "-f", "json", "."], "["
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
    "ESLint", sum(fr["errorCount"] + fr["warningCount"] for fr in report), "JavaScript: ESLint"
)
report = json_findings(
    [
        exe("stylelint"),
        "static/**/*.css",
        "--config",
        CENSUS / "stylelint.config.json",
        "--config-basedir",
        CENSUS,
        "-f",
        "json",
    ],
    "[",
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
reconcile("Stylelint", sum(len(fr["warnings"]) for fr in report), "CSS: Stylelint")
report = json_findings(
    [
        exe("html-validate"),
        "--config",
        CENSUS / "htmlvalidate.config.json",
        "-f",
        "json",
        *[f for f in FILES if f.endswith(".html")],
    ],
    "[",
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
)
for ln in out.splitlines():
    if m := re.match(r"(.+?):(\d+)(?::\d+)? (MD\d+)/([\w/-]+) (.+)", ln):
        add(
            S,
            f"Markdown: markdownlint {m.group(3)} {m.group(4).split('/')[0]}",
            "13/LINTERS",
            "markdownlint",
            f"{m.group(1)}:{m.group(2)}: {m.group(5)[:110]}",
        )
reconcile(
    "markdownlint", int(re.search(r"Summary: (\d+) error", out).group(1)), "Markdown: markdownlint"
)
tomls = [HEAD / f for f in FILES if f.endswith(".toml")]
for ln in run([exe("taplo"), "lint", *tomls]).splitlines():
    if "ERROR" in ln and "operation failed" not in ln:
        add(S, "TOML: taplo lint errors", "13/LINTERS", "taplo", ln.strip()[:200])
for ln in run([exe("taplo"), "fmt", "--check", *tomls]).splitlines():
    if m := re.search(r'not properly formatted path="([^"]+)"', ln):
        add(S, "TOML: files taplo would format", "13/LINTERS", "taplo", rel(m.group(1)))
out = run(
    [exe("yamllint"), "-c", CENSUS / "yamllint.config.yml", "-f", "parsable", "."],
    cwd=HEAD,
    stdout_only=True,
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
reconcile("yamllint", sum(1 for x in out.splitlines() if x.strip()), "YAML: yamllint")
wfs = [f for f in FILES if f.startswith(".github/workflows/")]
out = run([exe("actionlint"), "-oneline", *wfs], cwd=HEAD, stdout_only=True)
for ln in out.splitlines():
    if m := re.match(r"(.+?):(\d+):\d+: (.+) \[([\w-]+)\]$", ln):
        add(
            S,
            f"Workflows: actionlint {m.group(4)}",
            "13/LINTERS",
            "actionlint",
            f"{rel(m.group(1))}:{m.group(2)}: {m.group(3)[:110]}",
        )
reconcile("actionlint", sum(1 for x in out.splitlines() if x.strip()), "Workflows: actionlint")
add(S, "workflow files actionlint checked (reported)", "13", "actionlint", count=len(wfs))
for f in [f for f in FILES if f.endswith((".bat", ".cmd"))]:
    for ln in run([exe("blinter"), f], cwd=HEAD).splitlines():
        if m := re.match(r"Line (\d+): (.+) \(([A-Z]\d+)\)$", ln.strip()):
            add(
                S,
                f"Batch: Blinter {m.group(3)} {m.group(2)[:50]}",
                "13/LINTERS",
                "blinter",
                f"{f}:{m.group(1)}",
            )
for f in [f for f in FILES if f.endswith((".json", ".webmanifest"))]:
    r = subprocess.run(
        [PY, "-m", "json.tool", "--no-ensure-ascii", HEAD / f],
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
NOT_CODE = (".txt", ".csv", ".png", ".ico", ".pdf", ".example", ".gitignore", ".gitattributes")
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
# I. FOUND BY HAND (no machine count yet; each needs a counting command or the screen)
# =============================================================================================
log.info("census: I")
S = "I. Found by hand"
for found in json.loads((CENSUS / "hand_found.json").read_text(encoding="utf-8"))["items"]:
    add(S, found["category"], "see item", "by hand", found["item"])

# =============================================================================================
# CANDIDATE DECISIONS (candidate_decisions.json): each checked candidate moves to an issue row or a
# reported "checked, not an issue" row with its reason
# =============================================================================================
CANDIDATE = re.compile(r"check each|candidates|\(check\)")
decisions = [
    (d["verdict"], d["category"], re.compile(d["pattern"]), d["reason"])
    for d in json.loads((CENSUS / "candidate_decisions.json").read_text(encoding="utf-8"))[
        "decisions"
    ]
]
for key in [k for k in list(rows) if CANDIDATE.search(k[1])]:
    keep = []
    for it in rows[key]:
        hits = [d for d in decisions if key[1].startswith(d[1]) and d[2].search(it)]
        if not hits:
            keep.append(it)
            continue
        verdict = ": confirmed" if hits[0][0] == "issue" else ": checked, not an issue (reported)"
        add(
            key[0],
            key[1].split(" (")[0] + verdict,
            key[2],
            key[3] + " + by hand",
            f"{it} -- {hits[0][3]}",
        )
    rows[key] = keep
for key in [k for k in list(rows) if not rows[k]]:
    del rows[key]

# =============================================================================================
# REPORT
# =============================================================================================
OUT.mkdir(parents=True, exist_ok=True)
stem = f"{TODAY}_{SHA}"
lines = [
    f"# EdWebConsole census, {TODAY}, {SHA}",
    "",
    "Run from the checkout: `python -m tools.census.census <out dir> [<data dir>]`. Every "
    f"item is in `items_{stem}.txt`. Target: every issue count 0.",
    "",
    "| Section | Category | Rule | Counted by | Count | Kind |",
    "|---|---|---|---|---|---|",
]
items_out = []
totals = collections.Counter()
cands = collections.Counter()
for (sec, cat, rule, counted_by), its in rows.items():
    counted = [int(x[9:]) for x in its if x.startswith("__COUNT__")]
    real = [x for x in its if not x.startswith("__COUNT__")]
    n = counted[0] if counted else len(real)
    kinds = (("(reported)" in cat, "reported"), (bool(CANDIDATE.search(cat)), "candidate"))
    kind = next((k for hit, k in kinds if hit), "issue")
    lines.append(f"| {sec} | {cat} | {rule} | {counted_by} | {n:,} | {kind} |")
    totals[sec] += n if kind == "issue" else 0
    cands[sec] += n if kind == "candidate" else 0
    items_out += [f"\n## {sec} / {cat} ({n}, {kind})", *real]
lines += [
    "",
    "Kind: issue = each item breaks a rule; candidate = each item must be checked by "
    "hand and is an issue or not; reported = a size or a check's own result, no target.",
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
