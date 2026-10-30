"""tools/check_end_to_end.py (AGENTS.md rule 1) on real git repositories: each patch shape a pull
request adds is refused and named; a change with none, a missing value served as missing, a
container started empty and an old block with a line added inside it pass. What counts as a change
of product code (shared with check_fails_before) is read by its code, not its comments."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools import check_end_to_end as cee

TEST = "tests/test_data_path_x.py"
REAL_TEST = {TEST: "def test_x():\n    assert spot({'last': 1.0}) == 1.0\n"}


def _repo(tmp_path: Path, base: dict[str, str]) -> Path:
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    for name, text in base.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    git("add", *base)
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "pr")
    return tmp_path


def _commit(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", *files], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "pr"], cwd=root, check=True, capture_output=True)


BASE = {
    "server.py": "def spot(row):\n    return row['last']\n",
    "static/js/page.js": "function draw(v) { return v; }\n",
    "static/page.html": "<html><body><script>\nvar a = 1;\n</script></body></html>\n",
    TEST: "def test_x():\n    pass\n",
}


def _found(tmp_path, files: dict[str, str]) -> list[str]:
    root = _repo(tmp_path, BASE)
    _commit(root, {**REAL_TEST, **files})
    return cee.violations(root, "main")


def _changed(root: Path) -> list[str]:
    """The product files a PR changes, as check_fails_before counts them."""
    return sorted(
        [f for f in cee.pr_files(root, "main", "AMT") if cee.behavior_change(root, "main", f)]
        + cee.deleted_product(root, "main")
    )


def test_a_patch_is_refused_with_each_violation_named(tmp_path):
    root = _repo(tmp_path, BASE)
    _commit(
        root,
        {
            "server.py": (
                "def spot(row):\n"
                "    try:\n"
                "        return row.get('last', 0) or 0\n"
                "    except Exception:\n"
                "        return None\n"
            ),
            "static/js/page.js": "function draw(v) { return v || 0; }\n",
        },
    )
    text = "\n".join(cee.violations(root, "main"))
    assert "server.py:3: a missing value replaced by a literal (`.get(key, <literal>)`)" in text
    assert "server.py:3: a missing value replaced by a literal (`or <literal>`)" in text
    assert "server.py:4: an except that catches everything" in text
    assert "server.py:4: an except that swallows the error" in text
    assert (
        "static/js/page.js:1: a missing value replaced by a literal, an empty catch, "
        "or a swallowing .catch" in text
    )


def test_a_change_with_no_patch_shape_passes(tmp_path):
    assert (
        _found(
            tmp_path,
            {"server.py": "def spot(row):\n    return row['last'] if row['live'] else None\n"},
        )
        == []
    )


def test_a_test_runner_config_change_alone_passes(tmp_path):
    root = _repo(
        tmp_path,
        {**BASE, "playwright.config.mjs": "export default { use: { trace: 'on-first-retry' } };\n"},
    )
    _commit(
        root, {"playwright.config.mjs": "export default { use: { trace: 'retain-on-failure' } };\n"}
    )
    assert cee.violations(root, "main") == []


def test_a_patch_already_on_main_is_not_counted_against_a_pr_that_does_not_touch_it(tmp_path):
    root = _repo(tmp_path, {**BASE, "server.py": "def spot(row):\n    return row.get('last', 0)\n"})
    _commit(
        root,
        {
            "server.py": "def spot(row):\n    return row.get('last', 0)\n\n\n"
            "def bid(row):\n    return row['bid']\n",
            **REAL_TEST,
        },
    )
    assert cee.violations(root, "main") == []


@pytest.mark.parametrize(
    "path, text, what",
    [
        (
            "static/js/page.js",
            "function draw(v) { return v || []; }\n",
            "a missing value replaced by a literal",
        ),
        (
            "static/js/page.js",
            "function draw(v) { return v || ''; }\n",
            "a missing value replaced by a literal",
        ),
        (
            "static/js/page.js",
            "function draw(v) { v ??= 0; return v; }\n",
            "a missing value replaced by a literal",
        ),
        (
            "static/js/page.js",
            "function draw(p) { return p.catch(() => null); }\n",
            "a swallowing .catch",
        ),
        (
            "static/page.html",
            "<html><body><script>\nvar a = b || 0;\n</script></body></html>\n",
            "a missing value",
        ),
        (
            "server.py",
            "def spot(x):\n    return x if x is not None else 0\n",
            "(a None-check ternary)",
        ),
        (
            "server.py",
            "def spot(x):\n    if x is None:\n        return 0\n    return x\n",
            "(`if x is None:` then a literal)",
        ),
        (
            "server.py",
            "def spot(s):\n    try:\n        x = float(s)\n    except ValueError:\n"
            "        x = 0\n    return x\n",
            "an except that swallows the error",
        ),
        (
            "server.py",
            "def spot(s):\n    try:\n        return float(s)\n    except ValueError:\n"
            "        cleanup(s)\n",
            "an except that swallows the error",
        ),
        (
            "server.py",
            "def spot(s):\n    try:\n        return float(s)\n    except Exception:\n"
            "        pass\n",
            "an except that catches everything",
        ),
        (
            "server.py",
            "from contextlib import suppress\n\n\n"
            "def spot(d):\n    with suppress(KeyError):\n        return d['k']\n",
            "an error swallowed (`contextlib.suppress`)",
        ),
        (
            "server.py",
            "def spot(df):\n    return df.fillna(0)\n",
            "missing data repaired (`.fillna(...)`)",
        ),
        (
            "server.py",
            "def spot(d):\n    return d.get('k', default=0)\n",
            "(`.get(key, <literal>)`)",
        ),
        (
            "server.py",
            "def spot(d):\n    return d.setdefault('k', 0)\n",
            "(`.setdefault(key, <literal>)`)",
        ),
    ],
)
def test_each_patch_shape_a_pr_adds_is_refused(tmp_path, path, text, what):
    found = _found(tmp_path, {path: text})
    assert any(what in v for v in found), found


@pytest.mark.parametrize(
    "text",
    [
        # an except naming specific errors that keeps the reason
        "def spot(d):\n    try:\n        return d['k']\n    except (ValueError, KeyError) as e:\n"
        "        raise RuntimeError('no k') from e\n",
        # a container started empty, to be filled
        "def spot(held, tk, bar):\n    held.setdefault(tk, []).append(bar)\n"
        "    return held.setdefault(tk, {})\n",
        # a missing value served as missing
        "def spot(x):\n    if x is None:\n        return None\n    return x or None\n",
        # an except that logs and carries on: a retry loop, a failed reprice (the operator's ruling)
        "def loop():\n    while True:\n        try:\n            connect()\n"
        "        except OSError as e:\n"
        "            log.info('retrying: %s', e)\n",
        "def reprice(tk):\n    try:\n        publish(tk)\n    except Exception as e:\n"
        "        log.warning('reprice failed for %s: %s', tk, e)\n",
    ],
)
def test_what_is_not_a_patch_passes(tmp_path, text):
    assert _found(tmp_path, {"server.py": text}) == []


def test_a_line_added_inside_an_old_block_does_not_charge_the_block_to_the_pr(tmp_path):
    root = _repo(
        tmp_path,
        {
            **BASE,
            "server.py": (
                "def spot():\n    try:\n        go()\n    except Exception as e:\n"
                "        log(e)\n        raise\n"
            ),
        },
    )
    _commit(
        root,
        {
            "server.py": (
                "def spot():\n    try:\n        go()\n    except Exception as e:\n"
                "        log(e)\n        count()\n        raise\n"
            ),
            **REAL_TEST,
        },
    )
    assert cee.violations(root, "main") == []


def test_a_change_to_comments_and_docstrings_only_is_not_a_product_change(tmp_path):
    """The same code once comments and docstrings are set aside: nothing for a path test to
    cover."""
    root = _repo(
        tmp_path,
        {
            **BASE,
            "server.py": '"""Spot (RC-12, 2026-09-01)."""\n\n\ndef spot(row):\n'
            "    return row['last']  # used to be the bid\n",
            "static/js/page.js": "/* RC-UI-1 */\nfunction draw(v) { return v; }  // 2026-09-13\n",
        },
    )
    _commit(
        root,
        {
            "server.py": '"""Spot."""\n\n\ndef spot(row):\n    return row[\'last\']\n',
            "static/js/page.js": "function draw(v) { return v; }\n",
        },
    )
    assert _changed(root) == []


#: the base's ruff settings, and a PR's that turns the UP rules on
RUFF_BASE = '[tool.ruff]\ntarget-version = "py313"\n'
RUFF_UP = RUFF_BASE + '[tool.ruff.lint]\nselect = ["UP"]\n'
TOOLS_BASE = {**BASE, "pyproject.toml": RUFF_BASE}
OLD_STYLE = (
    "from typing import Optional\n\n\n"
    "def spot(row: Optional[float]) -> Optional[float]:\n    return row\n"
)


def _tool_fixed(root: Path, text: str, config: str = RUFF_UP) -> str | None:
    """ruff's safe fix and format of `text` with `config` in the repository, as a PR's author
    runs them."""
    (root / "pyproject.toml").write_text(config, encoding="utf-8")
    return cee.tool_fixed(root, "server.py", text)


def test_a_change_the_standard_tools_make_alone_is_not_a_product_change(tmp_path):
    """A PR that turns on ruff's UP rules and takes ruff's own fix: ruff check --fix and ruff format
    on the base file give the PR's file exactly, so it is not a product change."""
    root = _repo(tmp_path, {**TOOLS_BASE, "server.py": OLD_STYLE})
    fixed = _tool_fixed(root, OLD_STYLE)
    assert fixed is not None and "float | None" in fixed and fixed != OLD_STYLE
    _commit(root, {"pyproject.toml": RUFF_UP, "server.py": fixed})
    assert _changed(root) == []


def test_the_tools_fix_keeps_a_files_crlf_line_endings_as_they_are(tmp_path):
    """Some product files are CRLF; the text goes to ruff and back as bytes, so no line ending is
    doubled or dropped (on Windows a text pipe turned each CRLF into CR CR LF)."""
    root = _repo(tmp_path, TOOLS_BASE)
    fixed = _tool_fixed(root, OLD_STYLE.replace("\n", "\r\n"))
    assert fixed is not None and "\r\r" not in fixed and fixed.count("\r\n") == fixed.count("\n")


def test_a_hand_edit_on_top_of_the_tools_fix_is_a_product_change(tmp_path):
    """The same PR with one line the tools did not write: it is a product change."""
    root = _repo(tmp_path, {**TOOLS_BASE, "server.py": OLD_STYLE})
    fixed = _tool_fixed(root, OLD_STYLE)
    _commit(
        root,
        {"pyproject.toml": RUFF_UP, "server.py": fixed.replace("return row", "return row or 0.0")},
    )
    assert _changed(root) == ["server.py"]


STR_ENUM = 'from enum import Enum\n\n\nclass Zone(str, Enum):\n    LOW = "low"\n'


def _unsafe_rewrite(text: str) -> str:
    """ruff's own unsafe UP042 fix of `text`, then `ruff format`: the rewrite the operator allows
    no one to take, as ruff writes it."""
    out = text.encode("utf-8")
    for args in (
        ["check", "--fix", "--unsafe-fixes", "--exit-zero", "--quiet", "--select", "UP042"],
        ["format", "--quiet"],
    ):
        out = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                *args,
                "--isolated",
                "--stdin-filename",
                "server.py",
                "-",
            ],
            input=out,
            capture_output=True,
            check=True,
        ).stdout
    return out.decode("utf-8")


def test_a_fix_ruff_marks_unsafe_is_a_product_change_whatever_the_prs_config_asks(tmp_path):
    """A PR whose own pyproject.toml turns ruff's unsafe fixes on, marks one safe, or reaches
    another file that does (`extend`), and commits the unsafe rewrite of `(str, Enum)` to
    `StrEnum`, which changes what str() of a member is: the check judges ruff's own resolved
    settings, so the rewrite is a product change that needs its test."""
    rewritten = _unsafe_rewrite(STR_ENUM)
    assert "StrEnum)" in rewritten
    extra = tmp_path / "extra.toml"
    extra.write_text('unsafe-fixes = true\n[lint]\nextend-safe-fixes = ["UP042"]\n', "utf-8")
    for config in (
        RUFF_BASE + 'unsafe-fixes = true\n[tool.ruff.lint]\nselect = ["UP042"]\n',
        RUFF_BASE + '[tool.ruff.lint]\nselect = ["UP042"]\nextend-safe-fixes = ["UP042"]\n',
        RUFF_BASE + f'extend = "{extra.as_posix()}"\n[tool.ruff.lint]\nselect = ["UP042"]\n',
    ):
        (where := tmp_path / str(len(config))).mkdir()
        root = _repo(where, {**TOOLS_BASE, "server.py": STR_ENUM})
        _commit(root, {"pyproject.toml": config, "server.py": rewritten})
        assert _changed(root) == ["server.py"], config


def test_a_fix_made_for_another_python_than_the_bases_is_a_product_change(tmp_path):
    """A fix ruff calls safe is safe for its target Python only: on 3.14 an annotation is not
    evaluated, so ruff unquotes a forward reference that 3.13, the base's, evaluates at import."""
    forward = 'def f() -> "Later":\n    return None\n\n\nclass Later:\n    pass\n'
    per_file = RUFF_BASE + 'per-file-target-version = {"server.py" = "py314"}\n'
    for base, pr in (
        (RUFF_BASE, RUFF_UP.replace("py313", "py314")),
        (per_file.replace("py314", "py313"), per_file + '[tool.ruff.lint]\nselect = ["UP"]\n'),
    ):
        (where := tmp_path / str(len(pr))).mkdir()
        root = _repo(where, {**BASE, "pyproject.toml": base, "server.py": forward})
        fixed = _tool_fixed(root, forward, pr)
        assert fixed is not None and "-> Later:" in fixed, pr
        _commit(root, {"pyproject.toml": pr, "server.py": fixed})
        assert _changed(root) == ["server.py"], pr


def test_the_tools_fix_reads_the_committed_config_never_the_working_trees(tmp_path):
    """A pyproject.toml changed in the working tree only does not change the verdict."""
    root = _repo(tmp_path, {**TOOLS_BASE, "server.py": OLD_STYLE})
    fixed = _tool_fixed(root, OLD_STYLE)
    _commit(root, {"server.py": fixed})  # the PR commits the rewrite but not the UP selection
    assert _changed(root) == ["server.py"]


def test_a_code_change_beside_comment_changes_is_a_product_change(tmp_path):
    root = _repo(
        tmp_path, {**BASE, "static/js/page.js": "/* RC-UI-1 */\nfunction draw(v) { return v; }\n"}
    )
    _commit(
        root,
        {
            "server.py": "def spot(row):\n    return row['bid']\n",
            "static/js/page.js": "function draw(v) { return v; }\n",
        },
    )
    assert _changed(root) == ["server.py"]


@pytest.mark.parametrize(
    "path, before, after",
    [
        # a template literal nested in ${...} after a brace: its text is the shown string
        ("static/js/page.js", "s = `${ f({}) + `a  b` }`;\n", "s = `${ f({}) + `a b` }`;\n"),
        (
            "static/js/page.js",
            "h = `${ u({}) + `https://a.com/x` }`;\n",
            "h = `${ u({}) + `https://b.com/y` }`;\n",
        ),
        # division after ++, then a string holding //
        (
            "static/js/page.js",
            'x = i++ / 2 + "a/" + "//" + "b";\n',
            'x = i++ / 2 + "a/" + "//" + "c";\n',
        ),
        # a regular expression after ) holding \/\/
        (
            "static/js/page.js",
            "if (u) /^https?:\\/\\//.test(u) && go(1);\n",
            "if (u) /^https?:\\/\\//.test(u) && go(2);\n",
        ),
        # a block comment holding a line break ends the return
        (
            "static/js/page.js",
            "function f(){ return /*\n note */ 1 }\n",
            "function f(){ return 1 }\n",
        ),
        # whitespace a page shows, a comment inside an attribute, a no-break space
        # an encoding line: imported, the strings read otherwise
        ("server.py", 'ARROW = "→"\n', '# -*- coding: latin-1 -*-\nARROW = "→"\n'),
        ("static/page.html", "<pre>a  b</pre>\n", "<pre>a b</pre>\n"),
        ("static/page.html", '<p title="<!-- x -->">a</p>\n', '<p title="">a</p>\n'),
        ("static/page.html", "<p>a b</p>\n", "<p>a b</p>\n"),
    ],
)
def test_a_code_change_a_comment_reader_could_miss_is_a_product_change(
    tmp_path, path, before, after
):
    """The pairs differ in code, though a reader that guesses comments from characters reads them
    the same: each is a change of product code."""
    root = _repo(tmp_path, {**BASE, path: before})
    _commit(root, {path: after})
    assert _changed(root) == [path]


def test_every_python_and_page_code_file_in_the_repo_is_read():
    """Every .py, .js and .mjs product file of this repository reads (code_tree is not None), so a
    cleanup of its comments is judged by its code, never refused as unreadable."""
    root = Path(__file__).resolve().parent.parent
    files = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    product = [f for f in files if cee.is_product(f) and f.endswith(cee.CODE_TREE_SUFFIXES)]
    unread = [
        f for f in product if cee.code_tree(f, (root / f).read_text(encoding="utf-8")) is None
    ]
    assert product and unread == []


def test_a_comment_only_change_to_an_html_page_is_a_product_change(tmp_path):
    root = _repo(tmp_path, {**BASE, "static/page.html": "<!-- RC-UI-1 -->\n<p>a</p>\n"})
    _commit(root, {"static/page.html": "<p>a</p>\n"})
    assert _changed(root) == ["static/page.html"]


@pytest.mark.parametrize(
    "old, new, named",
    [
        ("dead.py", "docs/dead.py", "dead.py"),  # moved out of product paths
        (
            "static/js/page.js",
            "static/js/page2.js",
            "static/js/page.js, static/js/page2.js",
        ),  # renamed, not edited
    ],
)
def test_moving_a_product_file_is_a_product_change(tmp_path, old, new, named):
    root = _repo(tmp_path, {**BASE, "dead.py": "def unused(row):\n    return row['ask']\n"})
    (root / new).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "mv", old, new], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", f"move {old}"], cwd=root, check=True, capture_output=True
    )
    assert _changed(root) == sorted(named.split(", "))


def _git_in(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.mark.parametrize("path", ["static/js/my page.js", "static/js/café.js"])
def test_a_product_file_whose_name_git_quotes_is_still_read(tmp_path, path):
    root = _repo(tmp_path, {**BASE, path: "function draw(v) { return v; }\n"})
    _commit(root, {path: "function draw(v) { return -v; }\n"})
    assert _changed(root) == [path]


@pytest.mark.parametrize("path", ["static/js/page.js", "static/js/my page.js", "static/js/café.js"])
def test_a_patch_after_a_line_starting_with_plus_plus_is_still_refused_at_its_line(tmp_path, path):
    """An added `++ x;` reads in the diff as `+++ x;`: it is a line of the file, not a file header,
    and every name git quotes or ends with a tab is read back as written."""
    root = _repo(tmp_path, {**BASE, path: "var x = 0;\nvar a = 1;\nvar b = 2;\n"})
    _commit(
        root, {**REAL_TEST, path: "var x = 0;\n++ x;\nvar a = 1;\nvar b = 2;\nvar y = v || 0;\n"}
    )
    assert cee.violations(root, "main") == [
        f"{path}:5: a missing value replaced by a literal, an empty catch, or a swallowing .catch"
    ]


def test_a_name_git_quotes_with_raw_characters_is_still_read(tmp_path):
    """With the repository's core.quotePath off, git would put a name's non-ASCII characters inside
    its quotes as they are; the checker asks git for escapes, so the name reads back exactly."""
    path = 'static/js/a"é.js'
    root = _repo(tmp_path, BASE)
    _git_in(root, "config", "core.quotePath", "false")
    _git_in(root, "config", "core.protectNTFS", "false")  # a name Windows cannot hold on disk
    (tmp_path / "blob.txt").write_text("var y = v || 0;\n", encoding="utf-8")
    sha = subprocess.run(
        ["git", "hash-object", "-w", "blob.txt"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git_in(root, "update-index", "--add", "--cacheinfo", f"100644,{sha},{path}")
    _commit(root, REAL_TEST)
    assert cee.violations(root, "main") == [
        f"{path}:1: a missing value replaced by a literal, an empty catch, or a swallowing .catch"
    ]


def test_a_file_name_that_is_not_utf8_fails_the_check_itself(tmp_path):
    """Exit 2 (the check itself failed), never a judgment on a file it could not name."""
    root = _repo(tmp_path, BASE)
    (tmp_path / "blob.txt").write_text("var y = v || 0;\n", encoding="utf-8")
    sha = subprocess.run(
        ["git", "hash-object", "-w", "blob.txt"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--add", "-z", "--index-info"],
        cwd=root,
        check=True,
        capture_output=True,
        input=f"100644 {sha}\t".encode() + b"static/js/a\xff.js\0",
    )
    _commit(root, REAL_TEST)
    run = subprocess.run(
        [sys.executable, str(Path(cee.__file__)), "--base", "main"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2 and "could not be read" in run.stdout + run.stderr, (
        run.stdout + run.stderr
    )


def test_a_patch_moved_into_product_code_is_refused_at_its_line(tmp_path):
    """A file moved from outside product paths into them brings every line it holds into product
    code, so its patch shapes are refused there, edited or not."""
    root = _repo(
        tmp_path, {**BASE, "tools/helper.py": "try:\n    x()\nexcept Exception:\n    pass\n"}
    )
    (root / "app").mkdir()
    _git_in(root, "mv", "tools/helper.py", "app/helper.py")
    _commit(root, REAL_TEST)
    assert cee.violations(root, "main") == [
        "app/helper.py:3: an except that catches everything",
        "app/helper.py:3: an except that swallows the error",
    ]


def test_a_product_file_replaced_by_a_link_is_a_change(tmp_path):
    root = _repo(tmp_path, BASE)
    (tmp_path / "target.txt").write_text("server_impl.py", encoding="utf-8")
    sha = subprocess.run(
        ["git", "hash-object", "-w", "target.txt"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git_in(root, "update-index", "--cacheinfo", f"120000,{sha},server.py")
    _git_in(root, "commit", "-q", "-m", "server.py becomes a link")
    assert _changed(root) == ["server.py"]


def test_crlf_page_code_reaches_the_reader_as_written(tmp_path):
    """A template literal's line breaks are the shown string: CRLF against two line feeds is a
    change."""
    root = _repo(tmp_path, BASE)
    (root / "static/js/page.js").write_bytes(b"var s = `a\r\nb`;\r\n")
    _git_in(root, "commit", "-q", "-am", "crlf")
    _git_in(root, "branch", "-f", "main")
    (root / "static/js/page.js").write_bytes(b"var s = `a\n\nb`;\n")
    _git_in(root, "commit", "-q", "-am", "two line feeds")
    assert _changed(root) == ["static/js/page.js"]


def test_a_patch_after_a_unicode_line_separator_is_refused_at_its_line(tmp_path):
    """git numbers lines by line feed alone; a U+2028 inside a string does not start a line."""
    root = _repo(tmp_path, {**BASE, "server.py": 'T = "a b"\n'})
    _commit(root, {"server.py": 'T = "a b"\nx = y or 0\n'})
    assert cee.violations(root, "main") == [
        "server.py:2: a missing value replaced by a literal (`or <literal>`)"
    ]


def test_a_file_that_is_not_utf8_fails_the_check_itself(tmp_path):
    """Exit 2 (the check itself failed), never a judgment on code it could not read."""
    root = _repo(tmp_path, {**BASE, "calc.py": "x = 1\n"})
    (root / "calc.py").write_bytes(b"# -*- coding: latin-1 -*-\nx = '\xe9'\n")
    subprocess.run(
        ["git", "commit", "-q", "-am", "latin-1"], cwd=root, check=True, capture_output=True
    )
    run = subprocess.run(
        [sys.executable, str(Path(cee.__file__)), "--base", "main"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2, run.stdout + run.stderr


def test_deleting_a_product_file_is_a_product_change(tmp_path):
    root = _repo(tmp_path, {**BASE, "dead.py": "def unused(row):\n    return row['ask']\n"})
    subprocess.run(["git", "rm", "-q", "dead.py"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "remove dead.py"], cwd=root, check=True, capture_output=True
    )
    assert _changed(root) == ["dead.py"]
