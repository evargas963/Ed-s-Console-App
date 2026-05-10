"""Vendor path registry — V3 G1.1 (inherited)."""

from __future__ import annotations

from pathlib import Path

from .paths import ROOT


def load_vendor_prefixes(path: Path | None = None) -> list[str]:
    p = path or (ROOT / "governance" / "schwab_vendor_paths.yaml")
    if not p.is_file():
        return []
    try:
        import yaml  # type: ignore
    except ImportError:
        return []
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entries = data.get("entries") or []
    out: list[str] = []
    for e in entries:
        if isinstance(e, dict) and e.get("path"):
            out.append(str(e["path"]).replace("\\", "/").rstrip("/"))
    return out


def path_is_vendored(rel_posix: str, prefixes: list[str]) -> bool:
    rl = rel_posix.replace("\\", "/")
    for pre in prefixes:
        if rl == pre or rl.startswith(pre + "/"):
            return True
    return False
