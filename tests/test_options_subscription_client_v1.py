"""PR214 merge blocker 1B/1C/1D — options contract subscription binding, client side.

Runs Node assertions against the REAL shipped static/js/options_subscription.js
(tests/options_subscription_node.mjs), covering required cases 3-8:
network/non-2xx failure, ok:false, contract mismatch, exact success, the late-A-after-B
race, and the identity-mismatch health refusal. Executing the shipped module is the
point: a source-string presence check could not tell a working rule from a deleted one.

The wiring assertions below are deliberately NARROW and secondary — they only prove
options.html actually ROUTES through those shipped rules (a module can be correct and
still be bypassed). The rules' behavior is proven by the Node harness, never by grep.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_options_subscription_node_script():
    node = shutil.which("node")
    if not node:
        pytest.fail(
            "Node.js is required on PATH for this test (runs "
            "tests/options_subscription_node.mjs). Install Node.js LTS — same "
            "prerequisite as Playwright E2E (see docs/playwright.md)."
        )
    script = ROOT / "tests" / "options_subscription_node.mjs"
    r = subprocess.run(
        [node, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


def test_options_page_routes_selection_through_the_shipped_gate():
    """Narrow wiring check: the page must load the shipped module and use it, rather
    than keep its own inline copy of the rules. Behavior is proven by the Node harness
    above; this only refuses the bypass."""
    html = (ROOT / "static" / "options.html").read_text(encoding="utf-8", errors="replace")
    assert "/static/js/options_subscription.js" in html, (
        "options.html must load the shipped subscription module")
    assert "EdOptionsSubscription.createSubscriptionGate()" in html, (
        "selection must be guarded by the shipped request-generation gate (1C)")
    assert "EdOptionsSubscription.validateSubscriptionAck(" in html, (
        "the subscribe POST acknowledgement must be validated by the shipped rule (1B)")
    assert "EdOptionsSubscription.planeIsBoundToContract(" in html, (
        "health rendering must go through the shipped identity-binding rule (1D)")
    assert "EdOptionsSubscription.subscriptionState(" in html, (
        "the pending -> producer-confirmed transition must go through the shipped rule "
        "(premerge gap 1B)")


def test_options_page_never_claims_subscribed_on_the_post_ack_alone():
    """PR214 premerge gap 1B: a successful POST proves the subscription REQUEST was
    accepted, not that the daemon subscribed. The page must not label that 'subscribed';
    only producer-confirmed state may."""
    html = (ROOT / "static" / "options.html").read_text(encoding="utf-8", errors="replace")
    ack_branch = html.split("verdict.accepted")[-1].split("function pollMicrostructure")[0]
    assert "setSubscriptionState('subscribed'" not in ack_branch, (
        "the POST-acknowledgement branch must not claim 'subscribed' — that word belongs "
        "only to the producer-confirmed path in renderMicrostructure")
    assert "awaiting producer" in ack_branch, (
        "the acknowledgement branch must state that it is awaiting the producer")


def test_options_page_no_longer_silently_swallows_the_subscribe_post():
    """The specific pre-fix defect: `.catch(function(){})` on the subscribe POST made
    every failure mode invisible and let polling start regardless."""
    html = (ROOT / "static" / "options.html").read_text(encoding="utf-8", errors="replace")
    assert "}).catch(function(){});" not in html, (
        "a bare silent catch must not return to the subscription path")
