"""RC-527: the spelling of a repo-relative path has ONE owner, and the consumers use it.

WHY THIS FILE EXISTS (ported from #221's row 508 control). Call sites hand-rolled the
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
    (".env", ".env"),
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
    # foreign / escaping — preserved, NOT judged here (is_production_path owns that question)
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


def test_the_consumers_agree_with_the_authority():
    """Every materially connected consumer must route through the one owner, not re-derive it.

    Behavioural, not structural: each consumer is driven with the shapes the bug produced and
    must give the answer the authority implies.
    """
    from tools.check_credential_leak import _norm_path as cred

    for raw, want in CASES:
        assert cred(raw) == want, (raw, cred(raw), want)
