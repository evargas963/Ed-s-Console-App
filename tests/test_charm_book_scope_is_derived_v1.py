"""RC-288 — the charm book label must be counted, not asserted.

WHY IT MATTERS. This repo computes charm two ways: `compute_net_charm` over ONE selected
expiry (server.py) and `compute_charm_by_strike` over the whole chain (terrain_engine.py).
"Charm" therefore names two different quantities depending on which producer answered, and
the Exposure tab renders them under one heading.

WHAT WAS WRONG. The only book label in the product was the string literal
`"charm_book_scope": "full_chain_banked"`, and `static/exposure.html` carries the SAME
literal as its `||` fallback. A label written identically at both ends of the wire can
never disagree with itself, so it could not detect the one thing it exists for. It was
true on the day it was written and would have stayed "true" forever.

WHAT THIS REPLACED. A 277-line test file, `tests/test_charm_scope_surface_v1.py`, asserted
an elaborate `charm_scope`/`charm_expiry` contract through producer, MarketState, API dict,
Tier-C publisher, light plane and both UI surfaces — for fields that `git log -S` proves
have NEVER existed in any of those files in any commit. Two of its thirteen tests also
demanded the UI withhold a charm direction when unlabeled, which is the charm/Bias
vote-lock the operator revoked under RC-199. It was deleted; this is the honest remainder.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import server as srv  # noqa: E402


def test_a_single_expiry_book_is_named_as_one():
    """The case the constant could never report."""
    got = srv._charm_book_scope([
        {"expirationDate": "2026-08-07", "strikePrice": 640},
        {"expirationDate": "2026-08-07", "strikePrice": 645},
    ])
    assert got.startswith("single_expiry_banked:"), got
    assert "2026-08-07" in got


def test_a_multi_expiry_book_is_the_full_chain():
    assert srv._charm_book_scope([
        {"expirationDate": "2026-08-07"}, {"expirationDate": "2026-08-14"},
    ]) == "full_chain_banked"


def test_an_unreadable_chain_reports_unknown_not_confidence():
    """RC-274: absence must not render as a confident label for a book nobody looked at."""
    for bad in ([], None, "not a list", [{"strikePrice": 1}], [None]):
        assert srv._charm_book_scope(bad) == "unknown", bad


def test_the_label_is_no_longer_a_literal_at_the_producer():
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    assert '"charm_book_scope": "full_chain_banked"' not in src, (
        "the book label is a hardcoded string again — it cannot disagree with itself, so "
        "it cannot detect a change of book")
    assert '"charm_book_scope": _charm_book_scope(' in src


def test_the_expiry_field_alias_is_honoured():
    """Chains reach this code from more than one shape; both name the expiry."""
    assert srv._charm_book_scope([{"expiry": "2026-08-07"}]).startswith(
        "single_expiry_banked:")


# ─────────────────────────────── the deleted specification must stay deleted ────

def test_the_archaeology_file_is_gone():
    assert not (REPO / "tests" / "test_charm_scope_surface_v1.py").exists(), (
        "tests/test_charm_scope_surface_v1.py is back; it specifies charm_scope/"
        "charm_expiry, which have never existed in production, and two of its tests "
        "re-impose the charm vote-lock the operator revoked under RC-199")


def test_charm_scope_still_does_not_exist_in_production(repo_index):
    """The deletion must not be quietly undone by implementing the revoked lock instead.

    TEST_SYSTEM_REHAB_V2 final remediation: the .py half of this scan was an
    independent `git ls-files` + read, redundant with the shared `repo_index`
    observation. Split: .py source comes from `repo_index` (excluding tests/); the
    .html half is a genuinely distinct artifact type repo_index never indexes, kept
    as its OWN narrowly-pathspec'd scan (only 7 tracked .html files repo-wide).
    """
    def _hit(rel: str, text: str) -> bool:
        return "charm_scope" in text and "charm_book_scope" not in text.replace(
            "charm_scope", "charm_book_scope")

    hits = []
    for relpath, text, _tree in repo_index.items():
        rel = relpath.as_posix()
        if rel.startswith("tests/"):
            continue
        if _hit(rel, text):
            hits.append(rel)
    # institutional-scan-ok: non-.py artifact type (html), repo_index cannot serve it;
    # 7 tracked files repo-wide, scoped by an explicit *.html pathspec, not a bare scan.
    html_files = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.html"], cwd=REPO, capture_output=True,
        text=True, check=True).stdout.split("\0")
    for rel in (f for f in html_files if f and not f.startswith("tests/")):
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _hit(rel, text):
            hits.append(rel)
    assert not hits, (
        f"charm_scope appeared in production at {hits}. If the labelled-charm feature is "
        f"genuinely being built, that is an operator decision — RC-199 revoked the vote "
        f"lock and forbade re-encoding it, so this test must be changed deliberately.")
