"""Enable GitHub branch protection with required status checks (hardening keystone, 2026-06-03).

Makes CI *block* merges instead of being advisory — the keystone that gives every other gate teeth.
Self-contained (stdlib urllib; no `gh`/requests needed).

Run once (token needs repo admin):
    GITHUB_TOKEN=<pat> python tools/set_branch_protection.py            # protects the default branch
    GITHUB_TOKEN=<pat> python tools/set_branch_protection.py --branch main --repo evargas963/Ed-s-Console-App

The required checks are the CI check-run names; adjust to the exact contexts GitHub shows on a PR if
they differ from the job names below.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_REPO = "evargas963/Ed-s-Console-App"
# Required CI checks (job names from the workflows). A merge is blocked unless all pass.
REQUIRED_CHECKS = ["pytest-full", "hardening", "schwab-csv-first", "schwab-v4-closure"]


def _api(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GH_REPO", DEFAULT_REPO))
    ap.add_argument("--branch", default=os.environ.get("GH_BRANCH", ""))
    ap.add_argument("--checks", default=",".join(REQUIRED_CHECKS),
                    help="comma list of required status-check contexts")
    a = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("ERROR: set GITHUB_TOKEN (a PAT with repo admin) and re-run.", file=sys.stderr)
        return 2

    branch = a.branch
    if not branch:
        status, body = _api("GET", f"https://api.github.com/repos/{a.repo}", token)
        if status != 200:
            print(f"ERROR resolving default branch ({status}): {body}", file=sys.stderr)
            return 1
        branch = json.loads(body).get("default_branch", "main")

    checks = [c.strip() for c in a.checks.split(",") if c.strip()]
    payload = {
        "required_status_checks": {"strict": True, "contexts": checks},
        "enforce_admins": True,
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "restrictions": None,
        "allow_force_pushes": False,
        "allow_deletions": False,
    }
    url = f"https://api.github.com/repos/{a.repo}/branches/{branch}/protection"
    status, body = _api("PUT", url, token, payload)
    if status in (200, 201):
        print(f"OK: branch protection set on {a.repo}@{branch}; required checks: {checks}")
        return 0
    print(f"FAILED ({status}): {body}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
