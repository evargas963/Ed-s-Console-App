"""RC-527: the spelling of a repo-relative path has ONE owner, and the consumers use it.

WHY THIS FILE EXISTS (ported from #221's RC-508 control). Call sites hand-rolled the
repo-relative spelling, and the idiom they copied was `str.lstrip("./")`, which strips
CHARACTERS rather than a prefix and therefore eats the leading dot of every `.github` /
`.claude` / `.cursor` path. Re-measured 2026-09-06 on ac3f78fb: three sites still carried it —
the credential firewall keyed `.github/workflows/hardening.yml` as
`github/workflows/hardening.yml` (a silent over-block the moment a dot-prefixed skip entry
exists), the closure check's extractor mangled the same path (RC-526), and the chart-intent
lock answered False for the `.cursor/rules/` class its own docstring gates.

This file is a CONTROL, not a new mechanism: it adds no gate, no registry and no hook. It
asserts a property of code that already exists — one producer, and the consumers consume it.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pretooluse_guard import normalize_repo_relative as N  # noqa: E402

#: The required surface, plus the shapes the bug produced. Literal pairs, derived from the
#: contract rather than recomputed from the implementation's own primitives.
CASES: tuple[tuple[str, str], ...] = (
    # dot-prefixed control surfaces — the class the bug destroyed
    (".github/workflows/hardening.yml", ".github/workflows/hardening.yml"),
    (".claude/settings.json", ".claude/settings.json"),
    (".cursor/rules/00-always.mdc", ".cursor/rules/00-always.mdc"),
    (".github", ".github"),
    # explicit relative prefix — the case `lstrip("./")` was actually written for
    ("./tools/x.py", "tools/x.py"),
    ("./.github/x.yml", ".github/x.yml"),
    # ordinary nested paths
    ("tools/x.py", "tools/x.py"),
    ("a/b/c/d.py", "a/b/c/d.py"),
    # windows separators, including on a dot-prefixed path
    ("tools\\x.py", "tools/x.py"),
    (".github\\workflows\\h.yml", ".github/workflows/h.yml"),
    ("a\\b\\c.py", "a/b/c.py"),
    # already normalised — must be a no-op
    ("static/index.html", "static/index.html"),
    # redundant and dot segments
    ("a//b/./c.py", "a/b/c.py"),
    ("a/../b.py", "b.py"),
    # foreign / escaping — preserved, NOT judged here (classify_path owns that question)
    ("../outside/y.py", "../outside/y.py"),
    ("../../x.py", "../../x.py"),
    # malformed / empty
    ("", ""),
    (".", ""),
    ("./", ""),
    ("   tools/x.py   ", "tools/x.py"),
)


def test_the_authority_answers_every_required_shape():
    wrong = [(raw, N(raw), want) for raw, want in CASES if N(raw) != want]
    assert wrong == [], f"normalisation disagrees with the contract: {wrong}"


def test_normalisation_is_idempotent():
    """A canonical form that changes on a second pass is not canonical."""
    unstable = [raw for raw, _ in CASES if N(N(raw)) != N(raw)]
    assert unstable == [], f"not idempotent for: {unstable}"


def test_a_leading_dot_is_never_eaten():
    """The single property every one of the defects violated."""
    for raw in (".github/x.yml", ".claude/y.json", ".cursor/rules/z.mdc", ".env"):
        assert N(raw).startswith("."), (raw, N(raw))
        assert N(raw) == raw, (raw, N(raw))


def test_the_consumers_agree_with_the_authority():
    """Every materially connected consumer must route through the one owner, not re-derive it.

    Behavioural, not structural: each consumer is driven with the shapes the bug produced and
    must give the answer the authority implies.
    """
    from tools.check_credential_leak import _norm_path as cred
    from tools.check_institutional_correctness import _norm_rel_path as gate

    for raw, want in CASES:
        assert cred(raw) == want, (raw, cred(raw), want)
        assert gate(raw) == want, (raw, gate(raw), want)


def test_no_module_reintroduces_the_character_stripping_idiom(repo_index):
    """ONE FAUCET, structurally: the idiom that caused the defects may not come back.

    `lstrip`/`strip` with a dot-or-slash argument strips CHARACTERS from the left, which is
    never what a path wants.

    Matched by AST, not by text, so a docstring that names the bad idiom in order to explain
    the defect is not an offender (the use-versus-mention error this repository has already
    been bitten by — RC-186, RC-253). Sourced from the shared `repo_index` corpus, so this is
    not a new independent repo scan.
    """
    offenders = []
    scanned = 0
    for rel, _text, tree in sorted(repo_index.items()):
        if rel.parts[0] not in ("tools", "governance"):
            continue
        scanned += 1
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("lstrip", "strip")
                    and len(node.args) == 1
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                continue
            arg = node.args[0].value
            if arg and set(arg) <= {".", "/"}:
                offenders.append(f"{rel.as_posix()}:{node.lineno}")
    assert scanned > 40, "corpus too small to be a real check"
    assert offenders == [], (
        "character-stripping path normalisation is back — use "
        "pretooluse_guard.normalize_repo_relative: " + ", ".join(offenders))


def test_the_authority_has_exactly_one_definition(repo_index):
    """No second module may define its own `normalize_repo_relative`."""
    definers = []
    for rel, _text, tree in sorted(repo_index.items()):
        if rel.parts[0] not in ("tools", "governance"):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "normalize_repo_relative":
                definers.append(rel.as_posix())
    assert definers == ["tools/pretooluse_guard.py"], definers
