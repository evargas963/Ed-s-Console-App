"""ML-PIPE Item 4 — legacy fleet migration engine (governed, evidence-backed).

Migrates the active serving fleet from unverified (pre-Item-4, manifest-less)
bundles to governed manifest-backed verification WITHOUT fabricating trust:

  * A bundle is never blessed by hashing whatever bytes happen to exist.
  * Every stamped manifest carries machine-checkable provenance naming the
    independent evidence that established the artifact bytes:
      - CANDIDATE : byte-identical to a governed training-output file
                    (models/parallel|cascade|_artifact_archive) — sha256 equality
      - GIT       : byte-identical to the git-HEAD tracked blob (git object id)
      - GIT_EOL   : identical to the git-HEAD blob after CRLF->LF normalization
                    (checkout smudge on tracked *_meta.json text files only)
      - NONE      : no authoritative source — the file may NOT be blessed
  * Bundles whose bytes cannot be independently established are either
    re-promoted from a complete governed candidate (previous bytes preserved in
    a rollback quarantine) or quarantined out of serving entirely.

Classification vocabulary (mission-governed):
  PROVEN_SOURCE_REPROMOTABLE             all files CANDIDATE from one source dir
                                         that carries scheduler_run_manifest.json
  PROVEN_SOURCE_MANIFEST_RECONSTRUCTABLE every file has CANDIDATE/GIT/GIT_EOL evidence
  UNPROVEN_LINEAGE_QUARANTINE_REQUIRED   >=1 file with NO authoritative source
  RETRAIN_REQUIRED                       unproven AND no complete governed candidate
  NOT_ACTIVE                             bundle dir absent / empty

Dry-run is the default; --apply mutates the fleet. Every replacement backs the
replaced bytes into models/_item4_quarantine/<UTC>/ first (rollback evidence).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from active_bundle_contract import (  # noqa: E402
    ArtifactVerificationError,
    bundle_integrity_manifest_path,
    bundle_role_filenames,
    load_bundle_integrity_manifest,
    promote_horizon_bundle_from_candidate,
    verify_artifact_against_manifest,
    write_bundle_integrity_manifest,
)

HORIZON_ROOTS: tuple[tuple[str, str], ...] = (
    ("active", "1c"), ("active_5c", "5c"), ("active_15c", "15c"), ("active_60c", "60c"),
)
CANDIDATE_SOURCE_ROOTS: tuple[str, ...] = (
    "parallel", "cascade", "_artifact_archive/parallel", "_artifact_archive/cascade",
)
QUARANTINE_DIRNAME = "_item4_quarantine"
MIGRATION_STATE_PATH = REPO_ROOT / "reports" / "artifacts" / "ML_ITEM4_MIGRATION_STATE.json"

CLASS_REPROMOTABLE = "PROVEN_SOURCE_REPROMOTABLE"
CLASS_RECONSTRUCTABLE = "PROVEN_SOURCE_MANIFEST_RECONSTRUCTABLE"
CLASS_UNPROVEN = "UNPROVEN_LINEAGE_QUARANTINE_REQUIRED"
CLASS_RETRAIN = "RETRAIN_REQUIRED"
CLASS_NOT_ACTIVE = "NOT_ACTIVE"
CLASS_ALREADY_VERIFIED = "ALREADY_MANIFEST_VERIFIED"

ACTION_REPROMOTE = "REPROMOTE"
ACTION_REPROMOTE_REPLACING_UNPROVEN = "REPROMOTE_REPLACING_UNPROVEN"
ACTION_RECONSTRUCT_MANIFEST = "RECONSTRUCT_MANIFEST"
ACTION_QUARANTINE = "QUARANTINE"
ACTION_NONE = "NONE"


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def build_candidate_index(models_dir: Path) -> dict[str, list[str]]:
    """sha256 -> models/-relative locations for every non-active file under models/."""
    active_names = {r for r, _ in HORIZON_ROOTS}
    index: dict[str, list[str]] = {}
    for p in models_dir.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(models_dir)
        if rel.parts[0] in active_names or rel.parts[0] == QUARANTINE_DIRNAME:
            continue
        try:
            index.setdefault(_sha256_file(p), []).append(rel.as_posix())
        except OSError:
            continue
    return index


def git_tracked_blobs(repo_root: Path) -> dict[str, str]:
    """repo-relative posix path -> git blob oid for tracked files under models/."""
    proc = subprocess.run(
        ["git", "ls-files", "-s", "--", "models/"],
        cwd=repo_root, capture_output=True, text=True, timeout=120,
    )
    out: dict[str, str] = {}
    if proc.returncode != 0:
        return out
    for line in proc.stdout.splitlines():
        try:
            meta, path = line.split("\t", 1)
            out[path] = meta.split()[1]
        except (ValueError, IndexError):
            continue
    return out


def file_evidence(
    path: Path,
    git_rel_key: str,
    candidate_index: dict[str, list[str]],
    tracked_blobs: dict[str, str],
) -> dict[str, Any]:
    """Independent-evidence record for one active artifact file (never blesses)."""
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    locs = candidate_index.get(sha, [])
    if locs:
        return {"evidence": "CANDIDATE", "sha256": sha, "source": locs[0], "all_sources": locs[:4]}
    oid = tracked_blobs.get(git_rel_key)
    if oid:
        if _git_blob_sha1(raw) == oid:
            return {"evidence": "GIT", "sha256": sha, "source": f"git:{oid}"}
        if _git_blob_sha1(raw.replace(b"\r\n", b"\n")) == oid:
            return {"evidence": "GIT_EOL", "sha256": sha, "source": f"git:{oid}"}
    return {"evidence": "NONE", "sha256": sha, "source": None}


def _complete_candidate_dir(models_dir: Path, ticker: str, hz: str) -> Path | None:
    """First candidate source dir holding the complete 7-file bundle + run manifest."""
    required = list(bundle_role_filenames(ticker, hz).values())
    for src in CANDIDATE_SOURCE_ROOTS:
        d = models_dir / src / ticker
        if not d.is_dir():
            continue
        if all((d / n).is_file() for n in required) and (d / "scheduler_run_manifest.json").is_file():
            return d
    return None


def build_fleet_inventory(models_dir: Path, repo_root: Path | None = None) -> dict[str, Any]:
    """Evidence-backed inventory + classification of every active serving bundle."""
    repo_root = repo_root or REPO_ROOT
    candidate_index = build_candidate_index(models_dir)
    tracked = git_tracked_blobs(repo_root)
    # git ls-files paths are repo-relative and the governed models tree is
    # always "models/" at the repo root — the key must NOT depend on where the
    # inspected models_dir physically lives (it may be another worktree's).
    models_rel_prefix = "models"

    bundles: dict[str, Any] = {}
    for root_name, hz in HORIZON_ROOTS:
        root = models_dir / root_name
        if not root.is_dir():
            continue
        for tdir in sorted(root.iterdir()):
            if not tdir.is_dir():
                continue
            t = tdir.name
            roles = bundle_role_filenames(t, hz, include_optional=True)
            required_roles = set(bundle_role_filenames(t, hz))
            files: dict[str, Any] = {}
            src_dirs: set[str] = set()
            for role, name in roles.items():
                ap = tdir / name
                if not ap.is_file():
                    if role in required_roles:
                        files[role] = {"present": False, "required": True}
                    continue
                git_key = (
                    f"{models_rel_prefix}/{root_name}/{t}/{name}" if models_rel_prefix else ""
                )
                ev = file_evidence(ap, git_key, candidate_index, tracked)
                files[role] = {"present": True, "required": role in required_roles,
                               "filename": name, **ev}
            present = [r for r, v in files.items() if v.get("present")]
            manifest_present = bundle_integrity_manifest_path(tdir).is_file()
            evidences = {files[r]["evidence"] for r in present}
            candidate_dir = _complete_candidate_dir(models_dir, t, hz)
            # DRIFT-RECOVERY LOCK (2026-07-12 integration finding): re-promotion
            # copies bytes FROM candidate_dir, so REPROMOTE is byte-preserving
            # ONLY when every present active file equals the candidate_dir file
            # ITSELF — evidence matched against other governed sources (archive
            # snapshots, git blobs) proves provenance but NOT promotion safety.
            # 29 bundles had serving bytes silently replaced under the old rule.
            candidate_byte_identical = False
            if candidate_dir is not None and present:
                candidate_byte_identical = all(
                    (candidate_dir / files[r]["filename"]).is_file()
                    and _sha256_file(candidate_dir / files[r]["filename"]) == files[r]["sha256"]
                    for r in present
                )
            if not present:
                cls = CLASS_NOT_ACTIVE
            elif manifest_present:
                cls = CLASS_ALREADY_VERIFIED
            elif "NONE" in evidences:
                if candidate_dir is not None:
                    cls = CLASS_UNPROVEN  # replaceable through governed re-promotion
                else:
                    cls = CLASS_RETRAIN
            elif candidate_byte_identical:
                for r in present:
                    src_dirs.add(str(candidate_dir))
                cls = CLASS_REPROMOTABLE
            else:
                cls = CLASS_RECONSTRUCTABLE
            bundles[f"{t}:{hz}"] = {
                "ticker": t,
                "horizon": hz,
                "bundle_dir": str(tdir),
                "classification": cls,
                "manifest_present": manifest_present,
                "complete_candidate_dir": str(candidate_dir) if candidate_dir else None,
                "files": files,
            }
    counts: dict[str, int] = {}
    for b in bundles.values():
        counts[b["classification"]] = counts.get(b["classification"], 0) + 1
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "models_dir": str(models_dir),
        "bundle_count": len(bundles),
        "classification_counts": counts,
        "bundles": bundles,
    }


def plan_migration(inventory: dict[str, Any]) -> dict[str, Any]:
    """Per-bundle governed action plan (pure; no filesystem writes)."""
    actions: dict[str, Any] = {}
    for key, b in inventory["bundles"].items():
        cls = b["classification"]
        if cls == CLASS_ALREADY_VERIFIED or cls == CLASS_NOT_ACTIVE:
            action = ACTION_NONE
        elif cls == CLASS_REPROMOTABLE:
            action = ACTION_REPROMOTE
        elif cls == CLASS_UNPROVEN:
            action = (
                ACTION_REPROMOTE_REPLACING_UNPROVEN
                if b.get("complete_candidate_dir")
                else ACTION_QUARANTINE
            )
        elif cls == CLASS_RETRAIN:
            action = ACTION_QUARANTINE
        else:
            action = ACTION_RECONSTRUCT_MANIFEST
        actions[key] = {
            "action": action,
            "classification": cls,
            "bundle_dir": b["bundle_dir"],
            "candidate_dir": b.get("complete_candidate_dir"),
        }
    return {"generated_at_utc": inventory["generated_at_utc"], "actions": actions}


def _backup_bundle(bundle_dir: Path, models_dir: Path, stamp: str) -> str:
    """Copy the entire bundle dir into the rollback quarantine before mutation."""
    dest = models_dir / QUARANTINE_DIRNAME / stamp / bundle_dir.parent.name / bundle_dir.name
    dest.mkdir(parents=True, exist_ok=True)
    for f in bundle_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, dest / f.name)
    return str(dest)


def _reconstruction_provenance(b: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": "RECONSTRUCTED_FROM_INDEPENDENT_EVIDENCE",
        "reconstructed_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence": {
            role: {"evidence": v["evidence"], "source": v["source"], "sha256": v["sha256"]}
            for role, v in b["files"].items()
            if v.get("present")
        },
        "note": (
            "manifest reconstructed from files whose bytes were independently "
            "established (candidate sha256 identity / git-HEAD blob identity / "
            "git blob identity modulo CRLF checkout smudge on tracked JSON metas); "
            "NOT a promotion — see governance/ML_ITEM4_MIGRATION_POLICY.json"
        ),
    }


def _verify_bundle_now(bundle_dir: Path, ticker: str, hz: str) -> list[str]:
    """Post-action verification: every present required artifact must verify."""
    errors: list[str] = []
    try:
        manifest = load_bundle_integrity_manifest(bundle_dir)
    except ArtifactVerificationError as exc:
        return [f"{exc.reason_code}: {exc.detail}"]
    if manifest is None:
        return ["MANIFEST_MISSING: no manifest after migration action"]
    for role, name in bundle_role_filenames(ticker, hz, include_optional=True).items():
        if not (bundle_dir / name).is_file():
            continue
        try:
            verify_artifact_against_manifest(bundle_dir, ticker, hz, role, name, manifest=manifest)
        except ArtifactVerificationError as exc:
            errors.append(f"{role}: {exc.reason_code}: {exc.detail}")
    return errors


def execute_migration(
    inventory: dict[str, Any],
    plan: dict[str, Any],
    models_dir: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Execute (or dry-run) the migration plan; returns per-bundle results."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results: dict[str, Any] = {}
    for key, entry in sorted(plan["actions"].items()):
        action = entry["action"]
        b = inventory["bundles"][key]
        t, hz = b["ticker"], b["horizon"]
        bd = Path(b["bundle_dir"])
        rec: dict[str, Any] = {"action": action, "applied": False, "backup": None, "errors": []}
        if action == ACTION_NONE:
            rec["applied"] = True
            results[key] = rec
            continue
        if not apply:
            results[key] = rec
            continue
        try:
            if action in (ACTION_REPROMOTE, ACTION_REPROMOTE_REPLACING_UNPROVEN):
                rec["backup"] = _backup_bundle(bd, models_dir, stamp)
                active = promote_horizon_bundle_from_candidate(
                    Path(entry["candidate_dir"]), ticker=t, hz=hz, models_dir=models_dir
                )
                manifest = load_bundle_integrity_manifest(active)
                if manifest is not None:
                    manifest["provenance"] = {
                        "method": "REPROMOTED_FROM_GOVERNED_CANDIDATE",
                        "candidate_dir": entry["candidate_dir"],
                        "replaced_unproven_bytes": action == ACTION_REPROMOTE_REPLACING_UNPROVEN,
                        "rollback_backup": rec["backup"],
                        "migrated_at_utc": datetime.now(timezone.utc).isoformat(),
                    }
                    bundle_integrity_manifest_path(active).write_text(
                        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
                    )
                rec["errors"] = _verify_bundle_now(Path(active), t, hz)
            elif action == ACTION_RECONSTRUCT_MANIFEST:
                # allow_missing_required: incomplete legacy bundles get their
                # PRESENT files pinned; missing files stay visible to the
                # completeness contract (bundle remains fail-closed for serving).
                manifest = write_bundle_integrity_manifest(
                    bd, t, hz, allow_missing_required=True
                )
                manifest["provenance"] = _reconstruction_provenance(b)
                manifest["source_lineage"] = {
                    "source_manifest_absent": True,
                    "reconstruction": "see provenance",
                }
                bundle_integrity_manifest_path(bd).write_text(
                    json.dumps(manifest, indent=2, default=str), encoding="utf-8"
                )
                rec["errors"] = _verify_bundle_now(bd, t, hz)
            elif action == ACTION_QUARANTINE:
                rec["backup"] = _backup_bundle(bd, models_dir, stamp)
                for f in list(bd.iterdir()):
                    if f.is_file():
                        f.unlink()
                bd.rmdir()
            rec["applied"] = not rec["errors"]
        except (ArtifactVerificationError, OSError, FileNotFoundError) as exc:
            rec["errors"].append(f"{type(exc).__name__}: {exc}")
        results[key] = rec
    return {"stamp": stamp, "applied": apply, "results": results}


def verify_fleet(models_dir: Path) -> dict[str, Any]:
    """Recompute fleet verification state from the FILESYSTEM (no stored counters).

    Exit contract: ok is True only when every active bundle carries a manifest
    and every present governed artifact verifies against it.
    """
    verified = 0
    failed: dict[str, list[str]] = {}
    legacy: list[str] = []
    total = 0
    for root_name, hz in HORIZON_ROOTS:
        root = models_dir / root_name
        if not root.is_dir():
            continue
        for tdir in sorted(root.iterdir()):
            if not tdir.is_dir() or not any(f.is_file() for f in tdir.iterdir()):
                continue
            total += 1
            t = tdir.name
            key = f"{t}:{hz}"
            if not bundle_integrity_manifest_path(tdir).is_file():
                legacy.append(key)
                continue
            errors = _verify_bundle_now(tdir, t, hz)
            if errors:
                failed[key] = errors
            else:
                verified += 1
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "models_dir": str(models_dir),
        "total_active_bundles": total,
        "verified": verified,
        "legacy_unmanifested": legacy,
        "failed": failed,
        "ok": total == verified,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Drift recovery (ML_PIPE_ITEM_4_POST_MERGE_DRIFT_RECOVERY_AND_REPRODUCIBLE_REPAIR_V1)
#
# The 2026-07-12 integration proof found 29 bundles whose serving bytes had been
# replaced by live candidate-dir bytes although their classification evidence
# came from OTHER governed sources. The recovery (restore pre-migration bytes,
# keep only operator-authorized replacement role-pairs, re-stamp manifests with
# the original evidence) is driven by a COMMITTED record so it is deterministic,
# reviewable, and idempotently re-runnable — never a session-local script.
# ══════════════════════════════════════════════════════════════════════════════

RECOVERY_RECORD_PATH = REPO_ROOT / "reports" / "artifacts" / "ML_ITEM4_DRIFT_RECOVERY_RECORD.json"


def load_recovery_record(path: Path = RECOVERY_RECORD_PATH) -> dict[str, Any]:
    """Fail-closed load of the committed drift-recovery record."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("bundles"), dict):
        raise ValueError("recovery record malformed: missing bundles map")
    for key in ("schema_version", "backup_dir", "mission"):
        if key not in doc:
            raise ValueError(f"recovery record malformed: missing {key!r}")
    return doc


def execute_recovery(
    record: dict[str, Any], models_dir: Path, *, apply: bool = False
) -> dict[str, Any]:
    """Deterministically (re)apply the committed recovery record.

    Per bundle: every restore-file's bytes must come from the named quarantine
    backup and hash-match the record (a file absent from the backup inventory
    is a fail-closed error, never skipped); keep-files (operator-authorized
    replacements) must already hash-match the record; the manifest is
    re-stamped pinning current bytes with the record's evidence. Idempotent:
    a second run restores zero bytes and reproduces identical manifests
    (modulo stamp timestamps).
    """
    backup_root = models_dir / record["backup_dir"]
    results: dict[str, Any] = {}
    for key, entry in sorted(record["bundles"].items()):
        t, hz, root = entry["ticker"], entry["horizon"], entry["root"]
        active = models_dir / root / t
        rec: dict[str, Any] = {"restored": [], "kept_verified": [], "errors": []}
        for name, expected_sha in sorted((entry.get("restore_files") or {}).items()):
            src = backup_root / root / t / name
            if not src.is_file():
                rec["errors"].append(f"{name}: NOT IN BACKUP INVENTORY — fail closed")
                continue
            if _sha256_file(src) != expected_sha:
                rec["errors"].append(f"{name}: backup bytes do not match the record hash")
                continue
            cur = active / name
            if not cur.is_file() or _sha256_file(cur) != expected_sha:
                if apply:
                    active.mkdir(parents=True, exist_ok=True)
                    cur.write_bytes(src.read_bytes())
                rec["restored"].append(name)
        for name, expected_sha in sorted((entry.get("keep_files") or {}).items()):
            cur = active / name
            if not cur.is_file() or _sha256_file(cur) != expected_sha:
                rec["errors"].append(
                    f"{name}: authorized replacement bytes missing or changed on disk"
                )
            else:
                rec["kept_verified"].append(name)
        # migration-ADDED files (no pre-migration backup source, not operator-
        # authorized) return to the pre-migration state by removal — the bytes
        # remain in the governed candidate dirs, so this is non-destructive.
        rec["removed"] = []
        for name, added_sha in sorted((entry.get("remove_files") or {}).items()):
            cur = active / name
            if cur.is_file():
                if _sha256_file(cur) != added_sha:
                    rec["errors"].append(
                        f"{name}: unauthorized-addition bytes differ from record — refusing removal"
                    )
                elif apply:
                    cur.unlink()
                    rec["removed"].append(name)
                else:
                    rec["removed"].append(name)
        if apply and not rec["errors"]:
            manifest = write_bundle_integrity_manifest(
                active, t, hz, allow_missing_required=True
            )
            manifest["provenance"] = {
                "method": "RECONSTRUCTED_FROM_INDEPENDENT_EVIDENCE",
                "drift_recovery": {
                    "record": str(RECOVERY_RECORD_PATH.name),
                    "mission": record["mission"],
                    "backup_dir": record["backup_dir"],
                },
                "original_classification_evidence": entry.get("evidence") or {},
                "authorized_replacements_kept": sorted(entry.get("keep_files") or {}),
            }
            bundle_integrity_manifest_path(active).write_text(
                json.dumps(manifest, indent=2, default=str), encoding="utf-8"
            )
            rec["errors"].extend(_verify_bundle_now(active, t, hz))
        results[key] = rec
    ok = not any(r["errors"] for r in results.values())
    return {"applied": apply, "ok": ok, "results": results}


def verify_recovery(record: dict[str, Any], models_dir: Path) -> dict[str, Any]:
    """Prove current disk state matches the committed recovery record.

    Every restore-file and keep-file must hash-match the record; every touched
    bundle's manifest must carry the record-driven provenance (method, evidence,
    authorized keeps) and verify. Runs read-only.
    """
    errors: list[str] = []
    for key, entry in sorted(record["bundles"].items()):
        t, hz, root = entry["ticker"], entry["horizon"], entry["root"]
        active = models_dir / root / t
        for name, expected_sha in {**(entry.get("restore_files") or {}),
                                   **(entry.get("keep_files") or {})}.items():
            cur = active / name
            if not cur.is_file():
                errors.append(f"{key}/{name}: missing on disk")
            elif _sha256_file(cur) != expected_sha:
                errors.append(f"{key}/{name}: disk bytes differ from recovery record")
        for name in (entry.get("remove_files") or {}):
            if (active / name).is_file():
                errors.append(f"{key}/{name}: unauthorized addition still present on disk")
        try:
            manifest = load_bundle_integrity_manifest(active)
        except ArtifactVerificationError as exc:
            errors.append(f"{key}: manifest {exc.reason_code}")
            continue
        prov = (manifest or {}).get("provenance") or {}
        if prov.get("method") != "RECONSTRUCTED_FROM_INDEPENDENT_EVIDENCE":
            errors.append(f"{key}: manifest provenance method {prov.get('method')!r}")
        if sorted(prov.get("authorized_replacements_kept") or []) != sorted(
            entry.get("keep_files") or {}
        ):
            errors.append(f"{key}: manifest authorized_replacements_kept != record")
        if (prov.get("original_classification_evidence") or {}) != (entry.get("evidence") or {}):
            errors.append(f"{key}: manifest evidence != record evidence")
        verrs = _verify_bundle_now(active, t, hz)
        errors.extend(f"{key}: {e}" for e in verrs)
    return {"ok": not errors, "errors": errors, "bundles_checked": len(record["bundles"])}


def regenerate_migration_state_from_disk(
    models_dir: Path, out_path: Path = MIGRATION_STATE_PATH
) -> dict[str, Any]:
    """Reconcile the committed migration-state artifact with FILESYSTEM truth.

    Counts come from the manifests actually on disk (provenance method), never
    from prior stored counters; fleet verification is recomputed.
    """
    method_counts: dict[str, int] = {}
    for root_name, hz in HORIZON_ROOTS:
        root = models_dir / root_name
        if not root.is_dir():
            continue
        for tdir in sorted(root.iterdir()):
            if not tdir.is_dir():
                continue
            mp = bundle_integrity_manifest_path(tdir)
            if not mp.is_file():
                method_counts["NO_MANIFEST"] = method_counts.get("NO_MANIFEST", 0) + 1
                continue
            doc = json.loads(mp.read_text(encoding="utf-8"))
            m = (doc.get("provenance") or {}).get("method", "NO_PROVENANCE_FIELD")
            method_counts[m] = method_counts.get(m, 0) + 1
    fleet = verify_fleet(models_dir)
    doc = {
        "schema_version": 2,
        "mission": "ML_PIPE_ITEM_4_POST_MERGE_DRIFT_RECOVERY_AND_REPRODUCIBLE_REPAIR_V1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_of_truth": "filesystem recompute (manifest provenance methods + verify_fleet)",
        "manifest_method_counts": method_counts,
        "fleet_verification": {
            "total_active_bundles": fleet["total_active_bundles"],
            "verified": fleet["verified"],
            "legacy_unmanifested_count": len(fleet["legacy_unmanifested"]),
            "failed_count": len(fleet["failed"]),
            "ok": fleet["ok"],
        },
        "recovery_record": RECOVERY_RECORD_PATH.name,
        "historical_note": (
            "schema_version 1 recorded the ORIGINAL 2026-07-12 migration counts "
            "(36 REPROMOTE / 48 RECONSTRUCT / 4 REPLACE-UNPROVEN); the same-day "
            "drift recovery restored 171 unintended byte changes and re-stamped "
            "29 bundles as RECONSTRUCTED — this schema_version 2 document is "
            "regenerated from disk truth and supersedes those counters"
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def write_migration_state(
    inventory: dict[str, Any],
    execution: dict[str, Any] | None,
    fleet: dict[str, Any],
    out_path: Path = MIGRATION_STATE_PATH,
) -> None:
    doc = {
        "schema_version": 1,
        "mission": "ML_PIPE_ITEM_4_LEGACY_FLEET_MIGRATION_AND_STRICT_ENFORCEMENT_V1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification_counts": inventory["classification_counts"],
        "bundle_count": inventory["bundle_count"],
        "execution": (
            {
                "stamp": execution["stamp"],
                "applied": execution["applied"],
                "action_counts": _count_actions(execution),
                "errors": {
                    k: v["errors"] for k, v in execution["results"].items() if v["errors"]
                },
            }
            if execution
            else None
        ),
        "fleet_verification": {
            "total_active_bundles": fleet["total_active_bundles"],
            "verified": fleet["verified"],
            "legacy_unmanifested_count": len(fleet["legacy_unmanifested"]),
            "failed_count": len(fleet["failed"]),
            "ok": fleet["ok"],
        },
        "note": (
            "counters here are a report; verify_fleet() recomputes from the "
            "filesystem every run and is the only trusted source"
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _count_actions(execution: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in execution["results"].values():
        counts[v["action"]] = counts.get(v["action"], 0) + 1
    return counts


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models-dir", default=str(REPO_ROOT / "models"))
    ap.add_argument("--inventory", action="store_true", help="print classification inventory")
    ap.add_argument("--plan", action="store_true", help="print migration plan (dry-run)")
    ap.add_argument("--apply", action="store_true", help="EXECUTE the migration plan")
    ap.add_argument("--verify-fleet", action="store_true", help="recompute fleet verification")
    ap.add_argument("--recover", action="store_true",
                    help="(re)apply the committed drift-recovery record (idempotent)")
    ap.add_argument("--verify-recovery", action="store_true",
                    help="prove disk state matches the committed drift-recovery record")
    ap.add_argument("--regen-state", action="store_true",
                    help="regenerate the migration-state artifact from filesystem truth")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)
    models_dir = Path(args.models_dir)

    if args.recover or args.verify_recovery:
        record = load_recovery_record()
        if args.recover:
            res = execute_recovery(record, models_dir, apply=True)
            restored = sum(len(r["restored"]) for r in res["results"].values())
            print(f"recovery applied: bundles={len(res['results'])} bytes_restored_files={restored} ok={res['ok']}")
            for k, r in res["results"].items():
                for e in r["errors"]:
                    print("ERROR", k, e)
            if not res["ok"]:
                return 1
        ver = verify_recovery(record, models_dir)
        print(f"recovery verification: bundles={ver['bundles_checked']} ok={ver['ok']}")
        for e in ver["errors"][:20]:
            print("MISMATCH", e)
        if not ver["ok"]:
            return 1
        if not args.regen_state:
            return 0
    if args.regen_state:
        doc = regenerate_migration_state_from_disk(models_dir)
        print("state regenerated:", json.dumps(doc["manifest_method_counts"]))
        print("fleet:", json.dumps(doc["fleet_verification"]))
        return 0 if doc["fleet_verification"]["ok"] else 1

    if args.verify_fleet and not (args.inventory or args.plan or args.apply):
        fleet = verify_fleet(models_dir)
        print(json.dumps({k: v for k, v in fleet.items() if k != "failed"}, indent=2))
        for k, errs in fleet["failed"].items():
            print("FAILED", k, errs[:2])
        for k in fleet["legacy_unmanifested"]:
            print("LEGACY", k)
        return 0 if fleet["ok"] else 1

    inventory = build_fleet_inventory(models_dir)
    print("classification_counts:", json.dumps(inventory["classification_counts"]))
    plan = plan_migration(inventory)
    execution = None
    if args.plan or args.apply:
        execution = execute_migration(inventory, plan, models_dir, apply=args.apply)
        print("action_counts:", json.dumps(_count_actions(execution)))
        errs = {k: v["errors"] for k, v in execution["results"].items() if v["errors"]}
        if errs:
            print("ERRORS:")
            for k, e in errs.items():
                print(" ", k, e[:2])
    fleet = verify_fleet(models_dir)
    print(
        f"fleet: total={fleet['total_active_bundles']} verified={fleet['verified']} "
        f"legacy={len(fleet['legacy_unmanifested'])} failed={len(fleet['failed'])} ok={fleet['ok']}"
    )
    if args.apply:
        write_migration_state(inventory, execution, fleet)
        print("migration state ->", MIGRATION_STATE_PATH)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"inventory": inventory, "plan": plan, "execution": execution,
                        "fleet": fleet}, indent=2),
            encoding="utf-8",
        )
    if args.apply and (not fleet["ok"] or any(
        v["errors"] for v in execution["results"].values()
    )):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
