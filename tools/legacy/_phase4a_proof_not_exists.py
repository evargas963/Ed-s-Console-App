import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_authority import canonical_console_db_path  # noqa: E402

conn = sqlite3.connect(str(canonical_console_db_path()))
n = conn.execute(
    """
    SELECT COUNT(*) FROM snapshots s
    WHERE s.timeframe = '1m'
      AND NOT EXISTS (
        SELECT 1 FROM price_bars_1m p
        WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc
      )
    """
).fetchone()[0]
print("NOT_EXISTS_NO_ANCHOR_COUNT", n)
conn.close()
