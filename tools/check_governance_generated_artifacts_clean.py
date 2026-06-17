#!/usr/bin/env python3
"""Check-only verification — generated governance JSON must match sources.

Never writes artifacts. Regeneration is explicit via documented builder commands.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# When none of these are newer than the artifact, skip expensive rebuild/compare.
_PERSISTENCE_SOURCE_PATHS: tuple[Path, ...] = (
    REPO / "db.py",
    REPO / "calibration" / "writer.py",
    REPO / "tools" / "audit_persistence_consumers.py",
)
_HYGIENE_BUILDER = REPO / "tools" / "build_repo_hygiene_inventory.py"
_CHECK_STACK_BUILDER = REPO / "tools" / "build_check_stack_inventory.py"
_PRECOMMIT_AUDIT_BUILDER = REPO / "tools" / "audit_precommit_performance.py"
_PRECOMMIT_CFG = REPO / ".pre-commit-config.yaml"

# Pre-push fast path — mtime-gated; no full-repo hygiene walk unless force_deep.
PREPUSH_GENERATED_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "governance/artifacts/persistence_consumer_map.json",
        "python tools/audit_persistence_consumers.py",
        "persistence_consumer_map",
    ),
    (
        "governance/artifacts/CHECK_STACK_INVENTORY.json",
        "python tools/build_check_stack_inventory.py",
        "check_stack_inventory",
    ),
    (
        "governance/artifacts/PRECOMMIT_PERFORMANCE_AUDIT.json",
        "python tools/audit_precommit_performance.py --write",
        "precommit_performance_audit",
    ),
)

# Full-repo walk — explicit deep verify / regeneration only (not default pre-push).
DEEP_HYGIENE_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "governance/artifacts/REPO_HYGIENE_INVENTORY.json",
        "python tools/build_repo_hygiene_inventory.py",
        "repo_hygiene_inventory",
    ),
    (
        "governance/artifacts/REPO_HYGIENE_BACKLOG.json",
        "python tools/build_repo_hygiene_inventory.py",
        "repo_hygiene_backlog",
    ),
)

GENERATED_ARTIFACT_SPECS: tuple[tuple[str, str, str], ...] = (
    PREPUSH_GENERATED_ARTIFACT_SPECS + DEEP_HYGIENE_ARTIFACT_SPECS
)


def _stable_json(obj: Any, *, strip_keys: tuple[str, ...] = ("generated_at", "generated_at_utc")) -> str:
    def _scrub(o: Any) -> Any:
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k in strip_keys:
                    out[k] = "stable"
                else:
                    out[k] = _scrub(v)
            return out
        if isinstance(o, list):
            return [_scrub(v) for v in o]
        return o

    return json.dumps(_scrub(obj), indent=2, sort_keys=True) + "\n"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_needs_deep_check(artifact: Path, builder: Path) -> bool:
    """True when artifact missing or builder newer than artifact (cheap staleness probe)."""
    if not artifact.is_file():
        return True
    if not builder.is_file():
        return False
    return builder.stat().st_mtime > artifact.stat().st_mtime


def _any_source_newer_than(sources: tuple[Path, ...], artifact: Path) -> bool:
    if not artifact.is_file():
        return True
    art_mtime = artifact.stat().st_mtime
    for src in sources:
        if src.is_file() and src.stat().st_mtime > art_mtime:
            return True
    return False


def _persistence_needs_check() -> bool:
    path = REPO / "governance" / "artifacts" / "persistence_consumer_map.json"
    return _any_source_newer_than(_PERSISTENCE_SOURCE_PATHS, path)


def _check_stack_needs_check() -> bool:
    path = REPO / "governance" / "artifacts" / "CHECK_STACK_INVENTORY.json"
    sources = (_CHECK_STACK_BUILDER, _PRECOMMIT_CFG)
    return _any_source_newer_than(sources, path)


def _precommit_audit_needs_check() -> bool:
    path = REPO / "governance" / "artifacts" / "PRECOMMIT_PERFORMANCE_AUDIT.json"
    sources = (_PRECOMMIT_AUDIT_BUILDER, _PRECOMMIT_CFG)
    return _any_source_newer_than(sources, path)


def _check_persistence_consumer_map(*, force_deep: bool = False) -> list[str]:
    path = REPO / "governance" / "artifacts" / "persistence_consumer_map.json"
    if not force_deep and not _persistence_needs_check():
        return []
    if not path.is_file():
        return [f"{path.relative_to(REPO).as_posix()}: missing"]
    try:
        from tools.audit_persistence_consumers import (
            MAP_PATH,
            _serialize,
            _strip_generated_at,
            build_map,
        )
    except ImportError as exc:
        return [f"persistence_consumer_map: cannot import audit tool ({exc})"]
    if MAP_PATH != path:
        return [f"persistence map path mismatch: {MAP_PATH} vs {path}"]
    try:
        new_text = _serialize(build_map(stable_time=True))
        on_disk = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"persistence_consumer_map: read/build failed ({exc})"]
    if _strip_generated_at(on_disk) != _strip_generated_at(new_text):
        return [
            "governance/artifacts/persistence_consumer_map.json is stale vs sources — "
            "run: python tools/audit_persistence_consumers.py"
        ]
    return []


def _check_repo_hygiene_inventory(*, force_deep: bool = False) -> list[str]:
    path = REPO / "governance" / "artifacts" / "REPO_HYGIENE_INVENTORY.json"
    if not force_deep and not _artifact_needs_deep_check(path, _HYGIENE_BUILDER):
        return []
    if not path.is_file():
        return [f"{path.relative_to(REPO).as_posix()}: missing"]
    from tools.build_repo_hygiene_inventory import build_inventory

    expected = build_inventory()
    on_disk = _read_json(path)
    if _stable_json(expected) != _stable_json(on_disk):
        return [
            "governance/artifacts/REPO_HYGIENE_INVENTORY.json is stale — "
            "run: python tools/build_repo_hygiene_inventory.py"
        ]
    return []


def _check_repo_hygiene_backlog(*, force_deep: bool = False) -> list[str]:
    path = REPO / "governance" / "artifacts" / "REPO_HYGIENE_BACKLOG.json"
    if not force_deep and not _artifact_needs_deep_check(path, _HYGIENE_BUILDER):
        return []
    if not path.is_file():
        return [f"governance/artifacts/REPO_HYGIENE_BACKLOG.json: missing"]
    from tools.build_repo_hygiene_inventory import build_backlog, build_inventory

    inv = build_inventory()
    expected = build_backlog(inv)
    on_disk = _read_json(path)
    if _stable_json(expected) != _stable_json(on_disk):
        return [
            "governance/artifacts/REPO_HYGIENE_BACKLOG.json is stale — "
            "run: python tools/build_repo_hygiene_inventory.py"
        ]
    return []


def _check_check_stack_inventory(*, force_deep: bool = False) -> list[str]:
    path = REPO / "governance" / "artifacts" / "CHECK_STACK_INVENTORY.json"
    if not force_deep and not _check_stack_needs_check():
        return []
    if not path.is_file():
        return [f"{path.relative_to(REPO).as_posix()}: missing"]
    from tools.build_check_stack_inventory import build_inventory

    expected = build_inventory()
    on_disk = _read_json(path)
    if _stable_json(expected) != _stable_json(on_disk):
        return [
            "governance/artifacts/CHECK_STACK_INVENTORY.json is stale — "
            "run: python tools/build_check_stack_inventory.py"
        ]
    return []


def _check_precommit_performance_audit(*, force_deep: bool = False) -> list[str]:
    path = REPO / "governance" / "artifacts" / "PRECOMMIT_PERFORMANCE_AUDIT.json"
    if not force_deep and not _precommit_audit_needs_check():
        return []
    if not path.is_file():
        return [f"{path.relative_to(REPO).as_posix()}: missing"]
    from tools.audit_precommit_performance import build_audit

    expected = build_audit(measure=False)
    on_disk = _read_json(path)
    if _stable_json(expected) != _stable_json(on_disk):
        return [
            "governance/artifacts/PRECOMMIT_PERFORMANCE_AUDIT.json is stale — "
            "run: python tools/audit_precommit_performance.py --write"
        ]
    return []


_CHECK_DISPATCH: dict[str, Callable[..., list[str]]] = {
    "persistence_consumer_map": _check_persistence_consumer_map,
    "repo_hygiene_inventory": _check_repo_hygiene_inventory,
    "repo_hygiene_backlog": _check_repo_hygiene_backlog,
    "check_stack_inventory": _check_check_stack_inventory,
    "precommit_performance_audit": _check_precommit_performance_audit,
}


def check_governance_generated_artifacts_clean(*, force_deep: bool = False) -> list[str]:
    """Compare on-disk generated artifacts to in-memory/check-only rebuilds."""
    errors: list[str] = []
    seen_checks: set[str] = set()
    specs = PREPUSH_GENERATED_ARTIFACT_SPECS + (
        DEEP_HYGIENE_ARTIFACT_SPECS if force_deep else ()
    )
    for _rel, _regen, check_key in specs:
        if check_key in seen_checks:
            continue
        seen_checks.add(check_key)
        fn = _CHECK_DISPATCH.get(check_key)
        if fn is None:
            errors.append(f"generated-artifacts clean: unknown check {check_key!r}")
            continue
        if check_key in ("repo_hygiene_inventory", "repo_hygiene_backlog"):
            errors.extend(fn(force_deep=True))
        else:
            errors.extend(fn(force_deep=force_deep))
    return errors


def regeneration_commands() -> list[str]:
    """Distinct explicit regen commands (verification never runs these)."""
    return sorted({regen for _rel, regen, _key in GENERATED_ARTIFACT_SPECS})


def main() -> int:
    import os

    force_deep = os.environ.get("ED_PREPUSH_DEEP_ARTIFACT_CHECK", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    errs = check_governance_generated_artifacts_clean(force_deep=force_deep)
    if errs:
        print("check_governance_generated_artifacts_clean: FAIL\n- " + "\n- ".join(errs))
        return 1
    print("check_governance_generated_artifacts_clean: PASS (check-only; no files written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
