import re
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

keys = set()
for p in ROOT.rglob("*.py"):
    if "__pycache__" in str(p):
        continue
    if p.name.startswith("fix_mangled") or p.name.startswith("fix_get_snapshot"):
        continue
    t = p.read_text(encoding="utf-8")
    for m in re.finditer(r'get_snapshot_sql\("([^"]+)"\)', t):
        keys.add(m.group(1))

reg_path = ROOT / "snapshot_sql/_auto_extracted.json"
reg = json.loads(reg_path.read_text(encoding="utf-8"))
missing = sorted(keys - reg.keys())
print("total keys", len(keys))
print("in file", len(reg))
print("missing", len(missing))
for k in missing:
    print(k)
