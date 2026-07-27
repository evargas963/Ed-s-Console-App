"""
Snapshot Pipeline Verification Script

Verifies:
1. DB schema migration
2. Snapshot insertion
3. Prediction direction persistence
4. DTE / hours_to_expiry computation
5. Monte Carlo metadata persistence
6. Zone tracker restart continuity

Run:
python verify_snapshot_pipeline.py
"""

import sqlite3
import sys

# ---- CONFIG ----
from db import DB_PATH, get_snapshot_sql

TEST_TICKER = "SPY"            # ticker to test
from timeframe_config import CANONICAL_TIMEFRAME
TIMEFRAME = CANONICAL_TIMEFRAME

# ----------------

EXPECTED_COLUMNS = [
    "prediction_direction",
    "prediction_dominant_prob",
    "hours_to_expiry",
    "mc_paths",
    "mc_horizon",
    "mc_vol_source",
    "mc_sigma_value",
    "zone_since_bars_1m",
    "zone_since_bars_5m",
]


def print_header(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def connect_db():
    try:
        conn = sqlite3.connect(str(DB_PATH))
        return conn
    except Exception as e:
        print("[FAIL] DB CONNECTION FAILED:", e)
        sys.exit(1)


def check_schema(conn):
    print_header("CHECKING DB SCHEMA")

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(snapshots);")

    columns = [row[1] for row in cur.fetchall()]

    missing = []
    for col in EXPECTED_COLUMNS:
        if col not in columns:
            missing.append(col)

    if missing:
        print("[FAIL] Missing columns:")
        for m in missing:
            print("   ", m)
        if "zone_since_bars_1m" in missing or "zone_since_bars_5m" in missing:
            print("[HINT] Run the app once to trigger schema migration (db._migrate_schema)")
        conn.close()
        sys.exit(1)

    print("[OK] All expected columns present")
    return columns


def check_latest_snapshot(conn):
    print_header("CHECKING LATEST SNAPSHOT VALUES")

    cur = conn.cursor()

    cur.execute(get_snapshot_sql("verify_snapshot_pipeline.py:88"), (TEST_TICKER, TIMEFRAME))

    row = cur.fetchone()

    if not row:
        print("[FAIL] No snapshot rows found for ticker:", TEST_TICKER)
        return None

    columns = [d[0] for d in cur.description]
    data = dict(zip(columns, row))

    print("Latest snapshot timestamp:", data.get("ts_et"))

    checks = [
        "prediction_direction",
        "prediction_dominant_prob",
        "dte",
        "hours_to_expiry",
        "mc_paths",
        "mc_horizon",
        "mc_vol_source",
        "mc_sigma_value"
    ]

    for field in checks:
        print(f"{field:25} -> {data.get(field)}")

    return data


def check_zone_state(conn):
    """Validate zone recency: execution-layer (1m) and structure-layer (5m) columns.

    Schema must include zone_since_bars_1m and zone_since_bars_5m (enforced by EXPECTED_COLUMNS).
    If check_schema passed, these columns exist.
    """
    print_header("CHECKING ZONE TRACKER STATE")

    cur = conn.cursor()
    cur.execute(get_snapshot_sql("verify_snapshot_pipeline.py:133"), (TEST_TICKER, TIMEFRAME))
    row = cur.fetchone()

    if not row:
        print("[FAIL] No zone state found")
        return

    zone, prev_zone, since, since_1m, since_5m = row
    print("zone:", zone)
    print("prev_zone:", prev_zone)
    print("zone_since_bars (1m alias):", since)
    print("zone_since_bars_1m (execution):", since_1m)
    print("zone_since_bars_5m (structure):", since_5m)

    ok = True
    if since_1m is None:
        print("[WARN] zone_since_bars_1m not populated (execution-layer)")
        ok = False
    if since_5m is None:
        print("[WARN] zone_since_bars_5m not populated (structure-layer)")
        ok = False
    if since is not None and since_1m is not None and since != since_1m:
        print("[WARN] zone_since_bars != zone_since_bars_1m (alias inconsistency)")
        ok = False
    if ok:
        print("[OK] zone tracker present (1m + 5m semantics)")


def check_snapshot_timeframe_canonical(conn):
    """Fail loudly if recent snapshots are not timeframe='1m'.

    Canonical 1m: All new snapshot inserts MUST use timeframe='1m'.
    Legacy 5m rows from before migration are acceptable; recent rows must be 1m.
    """
    print_header("CHECKING SNAPSHOT TIMEFRAME (CANONICAL 1m)")

    cur = conn.cursor()

    # Count by timeframe
    cur.execute(get_snapshot_sql("verify_snapshot_pipeline.py:178"))
    by_tf = dict(cur.fetchall())
    print("Rows by timeframe:", by_tf)

    n_1m = by_tf.get("1m", 0)
    n_5m = by_tf.get("5m", 0)
    n_other = sum(v for k, v in by_tf.items() if k not in ("1m", "5m"))

    if n_other:
        print(f"[FAIL] Non-canonical timeframes present: {by_tf}")
        conn.close()
        sys.exit(1)

    # Most recent row must be 1m — proves live ingestion is writing canonical
    cur.execute(get_snapshot_sql("verify_snapshot_pipeline.py:196"), (TIMEFRAME,))
    latest = cur.fetchone()
    if latest:
        latest_tf = latest[2]
        if latest_tf != "1m":
            print(f"[FAIL] Most recent snapshot has timeframe={latest_tf!r} (expected '1m')")
            print(f"   id={latest[0]} {latest[1]} ts={latest[3]}")
            print("   -> Restart server; db.insert_snapshot now enforces 1m. No new 1m rows yet.")
            conn.close()
            sys.exit(1)

    if n_1m == 0 and (n_5m > 0 or n_other > 0):
        print("[WARN] Snapshots exist but zero rows with timeframe='1m'")
        print("   -> Run server during RTH to accumulate 1m snapshots. db.insert_snapshot enforces 1m.")
    elif n_1m > 0:
        print("[OK] Canonical 1m: recent snapshots use timeframe='1m'")
    if n_5m > 0:
        print(f"[INFO] Legacy 5m rows: {n_5m} (unchanged; new inserts are 1m)")


def check_mc_fields(snapshot):
    print_header("CHECKING MONTE CARLO METADATA")

    if snapshot is None:
        print("[FAIL] Cannot validate MC fields (no snapshot)")
        return

    fields = [
        "mc_paths",
        "mc_horizon",
        "mc_vol_source",
        "mc_sigma_value"
    ]

    for f in fields:
        v = snapshot.get(f)

        if v is None:
            print(f"[WARN] {f} is NULL (MC may not have run)")
        else:
            print(f"[OK] {f} = {v}")


def list_tables(conn):
    """List all tables in the database."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r[0] for r in cur.fetchall()]


def main():
    print_header("STARTING SNAPSHOT PIPELINE VERIFICATION")
    print("DB_PATH:", DB_PATH.resolve())

    # Ensure schema is migrated (adds zone_since_bars_1m, zone_since_bars_5m, etc.)
    try:
        from db import EdDB
        EdDB(DB_PATH)
    except Exception as e:
        print("[WARN] Could not run schema migration:", e)

    conn = connect_db()

    tables = list_tables(conn)
    print("\nTables in database:")
    for t in tables:
        print("  -", t)

    if "snapshots" not in tables:
        print("\n[FAIL] Table 'snapshots' does not exist.")
        print("The live app (db.py) writes to this same file:", DB_PATH.resolve())
        print("If snapshots is missing, the schema may not have been created yet.")
        conn.close()
        sys.exit(1)

    check_schema(conn)

    snapshot = check_latest_snapshot(conn)

    check_snapshot_timeframe_canonical(conn)

    check_zone_state(conn)

    check_mc_fields(snapshot)

    print_header("VERIFICATION COMPLETE")


if __name__ == "__main__":
    main()
