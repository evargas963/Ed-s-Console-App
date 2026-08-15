"""Plus-player lock helpers (RC-205/RC-208).

Catalog lists ENFORCED attributes only. soft_partial is forbidden (not a lock).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CATALOG_REL = "governance/plus_player_attributes.json"

_PATH_TOKEN = re.compile(
    r"(?:^|[\s`\"'(])((?:[\w.-]+/)+[\w.-]+\.(?:py|md|html|js|ts|tsx|jsx|css|sql|json))"
)

#: Minimum IDs that must remain ENFORCED in the catalog (core continuum).
CORE_ENFORCED_IDS = frozenset({
    "RES-01", "RES-14", "RES-15",
    "EVI-01", "EVI-04", "EVI-05", "EVI-07", "EVI-08", "EVI-09", "EVI-10",
    "COR-01", "COR-02", "COR-03", "COR-07", "COR-08",
    "CMP-01", "CMP-10",
    "DAT-02", "DAT-07", "DAT-14",
    "TST-01", "TST-02", "TST-03",
    "OBS-01", "OBS-02",
    "INS-02", "INS-08", "INS-10",
    "RSK-01", "RSK-06",
})


def catalog_path() -> Path:
    return REPO / CATALOG_REL


def load_catalog() -> dict:
    p = catalog_path()
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("attributes"), list):
        raise ValueError(f"{CATALOG_REL} missing attributes list")
    return data


def research_path_resolves(research: str) -> bool:
    r = (research or "").strip()
    if not r:
        return False
    if "http://" in r or "https://" in r:
        return True
    for m in _PATH_TOKEN.finditer(r):
        rel = m.group(1).replace("\\", "/")
        if (REPO / rel).is_file():
            return True
    first = r.split()[0].strip("`\"'")
    if "/" in first and (REPO / first.replace("\\", "/")).is_file():
        return True
    return False


def catalog_completeness_violations(data: dict | None = None) -> list[str]:
    try:
        data = data if data is not None else load_catalog()
    except (OSError, ValueError, json.JSONDecodeError) as e:
        return [f"catalog unreadable: {e}"]
    attrs = data.get("attributes") or []
    by_id = {a.get("id"): a for a in attrs if isinstance(a, dict)}
    out: list[str] = []
    for a in attrs:
        aid = a.get("id")
        enf = a.get("enforcement")
        enforcer = str(a.get("enforcer") or "").strip()
        if enf == "soft_partial":
            out.append(f"{aid}: soft_partial forbidden (RC-208) — enforce or remove from catalog")
            continue
        if enf != "enforced":
            out.append(f"{aid}: enforcement must be 'enforced', got {enf!r}")
        if not enforcer or enforcer.startswith("soft:"):
            out.append(f"{aid}: enforcer must be a real CHECK/guard, not soft:")
    for aid in sorted(CORE_ENFORCED_IDS):
        if aid not in by_id:
            out.append(f"missing CORE enforced attribute {aid}")
    return out
