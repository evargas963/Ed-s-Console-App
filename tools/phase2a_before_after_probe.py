"""One-shot before/after: the pre-change process on :8000 vs the tree's code, same ids.

Read-only. Written as a file rather than a -c one-liner so the exact command that produced
the numbers can be re-run verbatim.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.phase2a_inprocess_sample_v1 import CONSOLE_DB, _body, _ReadOnlyDBHandle  # noqa: E402
from tools.phase2a_live_sample_v1 import _levels_side, _liquidity_side  # noqa: E402


def _fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310 - local console
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    base = "http://127.0.0.1:8000"
    old_a, _ = _levels_side(_fetch(f"{base}/api/levels?ticker=SPY"))
    old_b, _ = _liquidity_side(_fetch(f"{base}/api/liquidity-snapshot?ticker=SPY&snapshot=live"))

    import server as srv
    srv.get_db = lambda *a, **k: _ReadOnlyDBHandle(CONSOLE_DB)  # type: ignore[assignment]
    new_payload = _body(srv.get_levels(ticker="SPY"))
    new_a, _ = _levels_side(new_payload)
    new_b, _ = _liquidity_side(_body(srv.get_liquidity_snapshot(
        ticker="SPY", date=None, snapshot="live", expiry=None, fusion=True)))

    print()
    print(f"{'id':16}{'OLD /levels':>13}{'OLD /liq':>13}   "
          f"{'NEW /levels':>13}{'NEW /liq':>13}   verdict")
    for k in sorted(set(old_a) | set(old_b) | set(new_a) | set(new_b)):
        was = "DIVERGED" if (k in old_a and k in old_b and old_a[k] != old_b[k]) else "agreed"
        if k in new_a and k in new_b:
            now = "AGREE" if new_a[k] == new_b[k] else "DIVERGE"
        else:
            now = "absent both"
        print(f"{k:16}{old_a.get(k, ''):>13}{old_b.get(k, ''):>13}   "
              f"{new_a.get(k, ''):>13}{new_b.get(k, ''):>13}   {was} -> {now}")
    print()
    print("families_absent on the new payload (absence must be declared, not implied):")
    for f in new_payload.get("families_absent") or []:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
