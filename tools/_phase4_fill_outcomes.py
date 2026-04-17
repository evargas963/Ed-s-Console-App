"""Run fill_outcomes for SPY to populate snapshot labels; Phase 4 production fix."""
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from db import DB_PATH, EdDB
from timeframe_config import CANONICAL_TIMEFRAME


def main() -> None:
    db = EdDB(DB_PATH)
    # Use wall-clock now so ts_utc < now includes recent snapshots needing forward bars.
    db.fill_outcomes("SPY", CANONICAL_TIMEFRAME, time.time())
    print("fill_outcomes done")


if __name__ == "__main__":
    main()
