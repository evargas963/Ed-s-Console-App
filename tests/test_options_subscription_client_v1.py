"""PR214 merge blocker 1B/1C/1D — options contract subscription binding, client side.

Runs Node assertions against the REAL shipped static/js/options_subscription.js
(tests/options_subscription_node.mjs), covering required cases 3-8:
network/non-2xx failure, ok:false, contract mismatch, exact success, the late-A-after-B
race, and the identity-mismatch health refusal. Executing the shipped module is the
point: a source-string presence check could not tell a working rule from a deleted one.
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
