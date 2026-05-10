"""Synonym YAML — V3 G3 (inherited)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import ROOT


def load_synonyms(path: Path | None = None) -> dict[str, Any]:
    p = path or (ROOT / "governance" / "schwab_field_synonyms.yaml")
    if not p.is_file():
        return {"version": 1, "entries": []}
    try:
        import yaml  # type: ignore
    except ImportError:
        return {"version": 1, "entries": [], "_error": "PyYAML not installed; synonyms skipped"}
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def expand_tokens_with_synonyms(tokens: list[str], syn: dict[str, Any]) -> list[str]:
    entries = syn.get("entries") or []
    if not isinstance(entries, list):
        return list(tokens)
    code_to_cf: dict[str, str] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        code = e.get("code_token") or e.get("from")
        cf = e.get("canonical_field") or e.get("to")
        if code and cf:
            code_to_cf[str(code).lower()] = str(cf)
    out = list(tokens)
    for t in tokens:
        extra = code_to_cf.get(str(t).lower())
        if extra:
            out.append(extra)
    return out
