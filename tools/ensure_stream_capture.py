"""Host watchdog: keep the canonical Schwab stream-capture daemon running.

Scheduled every 1 minute (the producer freshness TTL is 30s; a 5-minute
tick left a dead daemon dark for most of a session). Opens no Schwab
session. Duration is always 0.
"""
from __future__ import annotations

import argparse
import json
import sys

from app.market_data.stream_watchdog import ensure_stream_capture_running


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None, help="stream_capture.db path (passed through)")
    args = ap.parse_args()
    result = ensure_stream_capture_running(db_path=args.db)
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("action") in ("already_running", "started") else 1


if __name__ == "__main__":
    sys.exit(main())
