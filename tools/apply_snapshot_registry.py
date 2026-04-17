"""Replace static snapshot SQL literals with db.get_snapshot_sql(keys from _auto_extracted.json)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _ensure_import(text: str) -> str:
    if "get_snapshot_sql" in text and "from db import" in text:
        return text
    if text.lstrip().startswith("from db import get_snapshot_sql"):
        return text
    return "from db import get_snapshot_sql\n\n" + text


def main() -> None:
    reg_path = ROOT / "snapshot_sql" / "_auto_extracted.json"
    reg: dict[str, str] = json.loads(reg_path.read_text(encoding="utf-8"))
    items = sorted(reg.items(), key=lambda kv: -len(kv[1]))
    touched: set[Path] = set()
    for key, sql in items:
        if "FROM snapshots_1m_normalized" in sql:
            continue
        path_s, _lineno = key.rsplit(":", 1)
        path = ROOT / path_s
        if not path.is_file():
            print("missing file", path, file=sys.stderr)
            continue
        body = path.read_text(encoding="utf-8")
        if sql not in body:
            print("SKIP no exact match", key, file=sys.stderr)
            continue
        repl = f"get_snapshot_sql({json.dumps(key)})"
        body = body.replace(sql, repl, 1)
        path.write_text(body, encoding="utf-8")
        touched.add(path)

    for path in sorted(touched):
        body = path.read_text(encoding="utf-8")
        new_body = _ensure_import(body)
        if new_body != body:
            path.write_text(new_body, encoding="utf-8")

    print(f"Touched {len(touched)} files", file=sys.stderr)


if __name__ == "__main__":
    main()
