"""tools/check_end_to_end.py (AGENTS.md "Fix at the source", First gate, Four eyes) on real git
repositories: each patch shape a pull request adds is refused and named; an end-to-end change, a
missing value served as missing, a container started empty and an old block with a line added
inside it pass; a product change's description needs its wiring and both reviews, and the real
PR template left unfilled is refused."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_end_to_end as cee  # noqa: E402

BODY = ("Wiring: LAST_PRICE, docs/schwab_fields.csv row streaming.LevelOneEquity.LAST_PRICE.\n"
        "Schwab → screen: the daemon's quote.\nDeleted: the old queue.\nEnd-to-end test: tests/test_data_path_x.py\n"
        "Architecture review: PASS, LAST_PRICE is Schwab's field.\n"
        "Correctness review: PASS, tests/test_data_path_x.py run, 1 passed.\n")
TEMPLATE = (Path(__file__).resolve().parent.parent / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
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


BASE = {"server.py": "def spot(row):\n    return row['last']\n",
        "static/js/page.js": "function draw(v) { return v; }\n",
        "static/page.html": "<html><body><script>\nvar a = 1;\n</script></body></html>\n",
        TEST: "def test_x():\n    pass\n"}


def _found(tmp_path, files: dict[str, str], body: str = BODY) -> list[str]:
    root = _repo(tmp_path, BASE)
    _commit(root, {**REAL_TEST, **files})
    return cee.violations(root, "main", body)


def test_a_patch_with_no_end_to_end_test_is_refused_with_each_violation_named(tmp_path):
    root = _repo(tmp_path, BASE)
    _commit(root, {
        "server.py": ("def spot(row):\n"
                      "    try:\n"
                      "        return row.get('last', 0) or 0\n"
                      "    except Exception:\n"
                      "        return None\n"),
        "static/js/page.js": "function draw(v) { return v || 0; }\n"})
    found = cee.violations(root, "main", "Fixed it.")
    assert found[0].startswith("product code changed")
    text = "\n".join(found)
    assert "server.py:3: a missing value replaced by a literal (`.get(key, <literal>)`)" in text
    assert "server.py:3: a missing value replaced by a literal (`or <literal>`)" in text
    assert "server.py:4: an except that catches everything" in text
    assert "server.py:4: an except that swallows the error" in text
    assert "static/js/page.js:1: a missing value replaced by a literal, an empty catch, or a swallowing .catch" in text
    assert found[-6:] == ["the PR description lacks: Architecture review:",
                          "the PR description lacks: Correctness review:",
                          "the PR description lacks: Deleted:", "the PR description lacks: End-to-end test:",
                          "the PR description lacks: Schwab → screen:", "the PR description lacks: Wiring:"]


def test_an_end_to_end_change_passes(tmp_path):
    assert _found(tmp_path, {"server.py": "def spot(row):\n    return row['last'] if row['live'] else None\n"}) == []


def test_a_patch_already_on_main_is_not_counted_against_a_pr_that_does_not_touch_it(tmp_path):
    root = _repo(tmp_path, {**BASE, "server.py": "def spot(row):\n    return row.get('last', 0)\n"})
    _commit(root, {"server.py": "def spot(row):\n    return row.get('last', 0)\n\n\ndef bid(row):\n    return row['bid']\n",
                   **REAL_TEST})
    assert cee.violations(root, "main", BODY) == []


@pytest.mark.parametrize("path, text, what", [
    ("static/js/page.js", "function draw(v) { return v || []; }\n", "a missing value replaced by a literal"),
    ("static/js/page.js", "function draw(v) { return v || ''; }\n", "a missing value replaced by a literal"),
    ("static/js/page.js", "function draw(v) { v ??= 0; return v; }\n", "a missing value replaced by a literal"),
    ("static/js/page.js", "function draw(p) { return p.catch(() => null); }\n", "a swallowing .catch"),
    ("static/page.html", "<html><body><script>\nvar a = b || 0;\n</script></body></html>\n", "a missing value"),
    ("server.py", "def spot(x):\n    return x if x is not None else 0\n", "(a None-check ternary)"),
    ("server.py", "def spot(x):\n    if x is None:\n        return 0\n    return x\n", "(`if x is None:` then a literal)"),
    ("server.py", "def spot(s):\n    try:\n        x = float(s)\n    except ValueError:\n        x = 0\n    return x\n",
     "an except that swallows the error"),
    ("server.py", "def spot(s):\n    try:\n        return float(s)\n    except ValueError:\n        cleanup(s)\n",
     "an except that swallows the error"),
    ("server.py", "def spot(s):\n    try:\n        return float(s)\n    except Exception:\n        pass\n",
     "an except that catches everything"),
    ("server.py", "from contextlib import suppress\n\n\ndef spot(d):\n    with suppress(KeyError):\n        return d['k']\n",
     "an error swallowed (`contextlib.suppress`)"),
    ("server.py", "def spot(df):\n    return df.fillna(0)\n", "missing data repaired (`.fillna(...)`)"),
    ("server.py", "def spot(d):\n    return d.get('k', default=0)\n", "(`.get(key, <literal>)`)"),
    ("server.py", "def spot(d):\n    return d.setdefault('k', 0)\n", "(`.setdefault(key, <literal>)`)"),
])
def test_each_patch_shape_a_pr_adds_is_refused(tmp_path, path, text, what):
    found = _found(tmp_path, {path: text})
    assert any(what in v for v in found), found


@pytest.mark.parametrize("text", [
    # an except naming specific errors that keeps the reason
    "def spot(d):\n    try:\n        return d['k']\n    except (ValueError, KeyError) as e:\n"
    "        raise RuntimeError('no k') from e\n",
    # a container started empty, to be filled
    "def spot(held, tk, bar):\n    held.setdefault(tk, []).append(bar)\n    return held.setdefault(tk, {})\n",
    # a missing value served as missing
    "def spot(x):\n    if x is None:\n        return None\n    return x or None\n",
    # an except that logs and carries on: a retry loop, a failed reprice (the operator's ruling)
    "def loop():\n    while True:\n        try:\n            connect()\n        except OSError as e:\n"
    "            log.info('retrying: %s', e)\n",
    "def reprice(tk):\n    try:\n        publish(tk)\n    except Exception as e:\n"
    "        log.warning('reprice failed for %s: %s', tk, e)\n",
])
def test_what_is_not_a_patch_passes(tmp_path, text):
    assert _found(tmp_path, {"server.py": text}) == []


def test_a_line_added_inside_an_old_block_does_not_charge_the_block_to_the_pr(tmp_path):
    root = _repo(tmp_path, {**BASE, "server.py": (
        "def spot():\n    try:\n        go()\n    except Exception as e:\n        log(e)\n        raise\n")})
    _commit(root, {"server.py": (
        "def spot():\n    try:\n        go()\n    except Exception as e:\n        log(e)\n        count()\n        raise\n"),
        **REAL_TEST})
    assert cee.violations(root, "main", BODY) == []


def test_a_comment_added_to_a_path_test_is_not_an_end_to_end_test(tmp_path):
    root = _repo(tmp_path, BASE)
    _commit(root, {"server.py": "def spot(row):\n    return row['last'] if row['live'] else None\n",
                   TEST: "def test_x():\n    pass\n# covers spot\n"})
    assert cee.violations(root, "main", BODY)[0].startswith("product code changed")


def test_a_required_section_left_empty_is_refused(tmp_path):
    body = "Schwab → screen: the quote.\nDeleted:\nEnd-to-end test: tests/test_data_path_x.py\n"
    assert _found(tmp_path, {}, body) == ["the PR description's Deleted: is empty"]


PRODUCT_CHANGE = {"server.py": "def spot(row):\n    return row['last'] if row['live'] else None\n"}
PR_SECTIONS = ("Wiring:", "Schwab → screen:", "Deleted:", "End-to-end test:",
               "Architecture review:", "Correctness review:")


def test_a_product_change_needs_its_wiring_and_both_reviews(tmp_path):
    body = "Schwab → screen: the quote.\nDeleted: the old queue.\nEnd-to-end test: tests/test_data_path_x.py\n"
    assert _found(tmp_path, PRODUCT_CHANGE, body) == [
        "the PR description lacks: Architecture review:", "the PR description lacks: Correctness review:",
        "the PR description lacks: Wiring:"]


def test_a_change_with_no_product_code_needs_no_wiring_or_reviews(tmp_path):
    body = "Schwab → screen: none.\nDeleted: none.\nEnd-to-end test: none, no product code.\n"
    assert _found(tmp_path, {"docs/x.md": "a document\n"}, body) == []


def test_the_real_template_left_unfilled_is_refused_section_by_section(tmp_path):
    """GitHub puts the template's text, its hint comments and headings included, in a new PR's
    description; a hint is not content and a heading ends the section above it."""
    found = _found(tmp_path, PRODUCT_CHANGE, TEMPLATE)
    assert sorted(found) == sorted(f"the PR description's {s} is empty" for s in PR_SECTIONS)


def test_the_real_template_filled_in_passes(tmp_path):
    filled = TEMPLATE
    for s in PR_SECTIONS:
        filled = filled.replace(s, f"{s} {BODY.split(s, 1)[1].splitlines()[0]}")
    assert _found(tmp_path, PRODUCT_CHANGE, filled) == []


def test_the_net_lines_are_what_git_counts(tmp_path):
    root = _repo(tmp_path, BASE)
    _commit(root, {"server.py": "def spot(row):\n    return row['last']\n\n\ndef bid(row):\n    return row['bid']\n"})
    assert cee.net_lines(root, "main") == "1 file changed, 4 insertions(+)"


ROOT = Path(__file__).resolve().parent.parent
#: the dead-code deletions of 251b945c (cleanup/dead-code-deletions), as git diffed them from main 26ddc457
DELETIONS = ROOT / "tests" / "fixtures" / "real_dead_code_deletions_251b945c.patch"
COVERING = "tests/test_stream_spine_v1.py::test_writer_batches_into_stream_capture_db"


def _real_repo(tmp_path: Path, commit: str, paths: list[str]) -> Path:
    """A repository whose base is `paths` exactly as they are in this repository's `commit`."""
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("config", "core.autocrlf", "false")
    for p in paths:
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_bytes(subprocess.run(["git", "show", f"{commit}:{p}"], cwd=ROOT,
                                                  capture_output=True, check=True).stdout)
    git("add", *paths)
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "pr")
    return tmp_path


def deletions_pr(tmp_path: Path, *leave_out: str) -> Path:
    """251b945c's product deletions and two of its test changes (an edit of test_liquidity_engine.py,
    a deletion in test_options_order_flow_semantics_v1.py), applied to main 26ddc457, less the
    changes to `leave_out`. The liquidity and spine tests' own modules are there so that they run."""
    root = _real_repo(tmp_path, "26ddc457", ["schwab_client.py", "server.py", "stream_spine.py",
                                             "liquidity_value_engine.py", "liquidity_models.py", "time_et.py",
                                             "instrument_identity.py", "numeric_contract.py",
                                             "db_authority.py", "runtime_layout.py",
                                             "tests/test_liquidity_engine.py",
                                             "tests/test_options_order_flow_semantics_v1.py",
                                             "tests/test_stream_spine_v1.py"])
    subprocess.run(["git", "apply", *(f"--exclude={p}" for p in leave_out), str(DELETIONS)],
                   cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-am", "deletions"], cwd=root, check=True, capture_output=True)
    return root


def _body(e2e: str) -> str:
    return BODY.replace("End-to-end test: tests/test_data_path_x.py", f"End-to-end test: {e2e}")


def test_real_deletions_naming_an_existing_covering_test_pass(tmp_path):
    assert cee.product_numstat(deletions_pr(tmp_path), "main") == {
        "schwab_client.py": 0, "server.py": 0, "stream_spine.py": 0}
    assert cee.violations(tmp_path, "main", _body(f"{COVERING} covers CaptureWriter.")) == []


@pytest.mark.parametrize("e2e, refused", [
    ("the existing tests cover it.", "names no existing test by node id"),
    ("tests/test_stream_spine_v1.py::test_never_written", "tests/test_stream_spine_v1.py::test_never_written does not exist on HEAD"),
    ("tests/test_not_a_file_v1.py::test_x", "tests/test_not_a_file_v1.py::test_x does not exist on HEAD"),
])
def test_real_deletions_without_an_existing_test_named_are_refused(tmp_path, e2e, refused):
    found = cee.violations(deletions_pr(tmp_path), "main", _body(e2e))
    assert len(found) == 1 and refused in found[0], found


def test_a_real_product_change_that_adds_lines_still_needs_a_new_end_to_end_line(tmp_path):
    """#459's d965484b adds and removes lines in instrument_identity.py: naming existing tests is not
    enough; an end-to-end path test must gain a real line."""
    root = _real_repo(tmp_path, "93fca283", ["instrument_identity.py", "tests/test_stream_spine_v1.py"])
    (root / "instrument_identity.py").write_bytes(subprocess.run(
        ["git", "show", "d965484b:instrument_identity.py"], cwd=ROOT, capture_output=True, check=True).stdout)
    subprocess.run(["git", "commit", "-q", "-am", "pr"], cwd=root, check=True, capture_output=True)
    found = cee.violations(root, "main", _body(COVERING))
    assert found == ["product code changed (instrument_identity.py) but no end-to-end path test "
                     "(tests/test_data_path_*.py or tests/e2e/*.spec.js) gained a real line"]
