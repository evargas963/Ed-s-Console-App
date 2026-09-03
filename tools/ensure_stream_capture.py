"""Host watchdog: keep the canonical Schwab stream-capture daemon running.

Scheduled every few minutes. Opens no Schwab session. Duration is always 0
(the finite 405-minute task is the defect this replaces).
"""
from __future__ import annotations

import json
import sys

from app.market_data.stream_watchdog import ensure_stream_capture_running


def main() -> int:
    result = ensure_stream_capture_running()
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("action") in ("already_running", "started") else 1


if __name__ == "__main__":
    sys.exit(main())
