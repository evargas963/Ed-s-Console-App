import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

merged: dict[str, str] = {}
for name in (
    "snapshot_sql/_auto_extracted.json",
    "snapshot_sql/registry_full_a.json",
    "snapshot_sql/registry_full_b.json",
    "snapshot_sql/registry_full_c.json",
):
    p = ROOT / name
    if p.exists():
        merged.update(json.loads(p.read_text(encoding="utf-8")))

keys_needed: set[str] = set()
for p in ROOT.rglob("*.py"):
    if "__pycache__" in str(p):
        continue
    if p.name in ("fix_mangled_get_snapshot_sql.py", "verify_registry_coverage.py"):
        continue
    t = p.read_text(encoding="utf-8")
    for m in re.finditer(r'get_snapshot_sql\("([^"]+)"\)', t):
        keys_needed.add(m.group(1))

missing = sorted(keys_needed - merged.keys())
print("merged", len(merged), "needed", len(keys_needed), "missing", len(missing))
for k in missing:
    print("MISSING", k)
