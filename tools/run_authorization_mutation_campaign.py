#!/usr/bin/env python3
"""Canonical, independently reproducible mutation campaign for the mission
authorization system (tools/mission_authorization.py) and the operator-path
privacy guard (tools/check_private_paths.py).

PREDECLARED DETECTION RULE (fixed before any execution; enforced by code):
  * a mutation is DETECTED only when at least one test named in its
    predeclared detector map fails under the mutation;
  * DETECTED_BY_PRIMARY_LAYER when any expected_primary test fails;
  * DETECTED_BY_APPROVED_EARLIER_LAYER when only approved_earlier_layer
    tests fail;
  * failures OUTSIDE the predeclared map never count toward detection —
    they are recorded as unrelated_failures and, absent any predeclared
    failure, the mutation is SURVIVED;
  * INVALID_MUTATION when the mutation target no longer matches the source;
  * restoration must be byte-exact (sha256 preimage == post-restore);
  * the clean baseline (both detector suites) must pass before the first
    mutation and after the last restoration.

Layered-defense honesty: some parser mutations (A11-A14) disable one layer of
canonicalize_remote while sibling layers still refuse the same input with a
DIFFERENT reason; the coarse refusal tests therefore stay green and the
predeclared primary detector is the layer-specific reason battery
(test_canonicalize_remote_rejection_reasons_are_layer_specific). This is
recorded per-mutation in layered_defense_note rather than hidden.

Usage:
  python tools/run_authorization_mutation_campaign.py --run
      run the full campaign; write deterministic JSON evidence to
      reports/scoreboard_forensic/authorization_mutation_campaign.json
  python tools/run_authorization_mutation_campaign.py --run --out <path>
      write the evidence elsewhere (independent reproduction)
  python tools/run_authorization_mutation_campaign.py --verify
      drift lock: retained evidence must match current definitions sha,
      declare 22 mutations, zero survivors, exact restoration
  python tools/run_authorization_mutation_campaign.py --markdown
      concise Markdown table from the retained evidence

Scope locks: mutates ONLY the two governance tools above (never Lane-B, never
calibration/), touches no git history, performs no remote operation.

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — governance mutation reproducibility only.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH = "tools/mission_authorization.py"
GUARD = "tools/check_private_paths.py"
T_AUTH = "tests/test_mission_authorization.py"
T_PRIV = "tests/test_operator_path_privacy.py"
EVIDENCE = ROOT / "reports" / "scoreboard_forensic" / "authorization_mutation_campaign.json"

_REASON_BATTERY = "test_canonicalize_remote_rejection_reasons_are_layer_specific"

# Each definition: id, file, pairs [(old, new, occurrence)], invariant,
# selector, expected_primary, approved_earlier_layer, layered_defense_note.
MUTATIONS: tuple[dict, ...] = (
    {"id": "A1-branch-check-removed", "file": AUTH,
     "pairs": [['if branch != contract["authorized_branch"]:',
                'if False and branch != contract["authorized_branch"]:', 0]],
     "invariant": "a checked-out branch is never authorization; wrong/detached branch refuses",
     "selector": T_AUTH,
     "expected_primary": ["test_detached_head_fails_branch_binding"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A2-remote-identity-comparison-removed", "file": AUTH,
     "pairs": [["elif origin_canon != auth_canon:", "elif False:", 0]],
     "invariant": "origin must canonicalize to the authorized repository identity",
     "selector": T_AUTH,
     "expected_primary": ["test_wrong_repository_remote_fails_closed",
                          "test_lookalike_host_and_wrong_owner_fail"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A3-binding-missing-accepted", "file": AUTH,
     "pairs": [["if binding is None:", "if False and binding is None:", 0]],
     "invariant": "absent clone identity or lease fails closed (MISSING)",
     "selector": T_AUTH,
     "expected_primary": ["test_missing_local_secrets_fail_closed",
                          "test_copied_contract_in_another_clone_fails_closed",
                          "test_copied_lease_only_fails_closed",
                          "test_second_worktree_of_same_clone_fails_without_own_authorization",
                          "test_missing_clone_identity_fails_closed",
                          "test_environment_override_cannot_replace_lease"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A4-binding-mismatch-accepted", "file": AUTH,
     "pairs": [['elif binding != contract["authorization_binding_sha256"]:',
                "elif False:", 0]],
     "invariant": "a binding digest differing from the tracked pin fails closed (MISMATCH)",
     "selector": T_AUTH,
     "expected_primary": ["test_wrong_binding_sha_fails_closed",
                          "test_copied_contract_AND_lease_in_another_clone_fails_closed"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A5-legacy-private-path-field-accepted", "file": AUTH,
     "pairs": [["if LEGACY_PRIVATE_PATH_FIELD in doc:",
                "if False and LEGACY_PRIVATE_PATH_FIELD in doc:", 0]],
     "invariant": "contracts carrying authorized_worktree are refused at load",
     "selector": T_AUTH,
     "expected_primary": ["test_legacy_private_path_contract_refused"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A6-expiry-check-removed", "file": AUTH,
     "pairs": [['if float(doc["expires_at_epoch"]) < time.time():', "if False:", 0]],
     "invariant": "expired authorizations refuse",
     "selector": T_AUTH,
     "expected_primary": ["test_expired_authorization_fails"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A7-overlap-binding-collision-removed", "file": AUTH,
     "pairs": [["errors.append(f\"authorization binding collision with {other.get('mission_id')}\")",
                "pass", 0]],
     "invariant": "two active contracts sharing one binding digest collide",
     "selector": T_AUTH,
     "expected_primary": ["test_branch_and_worktree_collision_detected"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A8-legacy-weak-lease-field-accepted", "file": AUTH,
     "pairs": [["if LEGACY_WEAK_BINDING_FIELD in doc:",
                "if False and LEGACY_WEAK_BINDING_FIELD in doc:", 0]],
     "invariant": "contracts carrying the copyable lease-only pin are refused at load",
     "selector": T_AUTH,
     "expected_primary": ["test_legacy_weak_lease_only_contract_refused"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A9-clone-identity-dropped-from-binding", "file": AUTH,
     "pairs": [['ip.read_bytes() + b"|" + mission_id.encode("utf-8") + b"|" + lp.read_bytes()',
                'mission_id.encode("utf-8") + b"|" + lp.read_bytes()', 0]],
     "invariant": "the binding digest must include the clone identity nonce, else a copied lease authorizes another clone",
     "selector": T_AUTH,
     "expected_primary": ["test_copied_contract_AND_lease_in_another_clone_fails_closed"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A10-credential-rejection-removed", "file": AUTH,
     "pairs": [["if password:", "if False:", 0],
               ['if scheme == "https" and username:', "if False:", 0]],
     "invariant": "credential-bearing remotes refuse (both userinfo layers)",
     "selector": T_AUTH,
     "expected_primary": ["test_credential_bearing_origin_refused_without_leaking_it",
                          "test_contract_with_credential_remote_refused_at_load",
                          _REASON_BATTERY],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A11-file-scheme-check-removed", "file": AUTH,
     "pairs": [['if u.lower().startswith("file://"):', "if False:", 0]],
     "invariant": "file:// remotes refuse with the file:// reason",
     "selector": T_AUTH,
     "expected_primary": [_REASON_BATTERY],
     "approved_earlier_layer": [],
     "layered_defense_note": ("test_file_and_local_path_remotes_refused stays green: the "
                              "scheme allowlist and host-required layers still refuse "
                              "file:/// inputs with a different reason; the layer-specific "
                              "reason battery is the predeclared detector")},
    {"id": "A12-scheme-allowlist-removed", "file": AUTH,
     "pairs": [['if scheme not in ("https", "ssh"):', "if False:", 0]],
     "invariant": "only https/ssh schemes canonicalize",
     "selector": T_AUTH,
     "expected_primary": [_REASON_BATTERY],
     "approved_earlier_layer": [],
     "layered_defense_note": ("http:// then canonicalizes (no other layer refuses it); "
                              "only the reason battery exercises an http input")},
    {"id": "A13-local-path-check-removed", "file": AUTH,
     "pairs": [['if re.match(r"^[A-Za-z]:[\\\\/]", u) or u.startswith(("/", "\\\\", "./", "../", "~")):',
                "if False:", 0]],
     "invariant": "local filesystem remotes refuse with the local-filesystem reason",
     "selector": T_AUTH,
     "expected_primary": [_REASON_BATTERY],
     "approved_earlier_layer": [],
     "layered_defense_note": ("relative-path inputs still refuse via the SCP-form parser "
                              "(different reason); the reason battery is the predeclared "
                              "detector for the layer-specific message")},
    {"id": "A14-port-check-removed", "file": AUTH,
     "pairs": [['if port not in (None, 443 if scheme == "https" else 22):', "if False:", 0]],
     "invariant": "non-default ports refuse",
     "selector": T_AUTH,
     "expected_primary": [_REASON_BATTERY],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A15-git-suffix-strip-removed", "file": AUTH,
     "pairs": [['if p.lower().endswith(".git"):', "if False:", 0]],
     "invariant": ".git-suffixed and bare forms canonicalize identically",
     "selector": T_AUTH,
     "expected_primary": ["test_canonicalize_remote_equivalences",
                          "test_remote_normalization_tolerates_git_suffix_slash_and_case"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A16-owner-repo-lowercase-removed", "file": AUTH,
     "pairs": [['return f"{host}/{owner.lower()}/{repo.lower()}", "ok"',
                'return f"{host}/{owner}/{repo}", "ok"', 0]],
     "invariant": "owner/repo case never splits repository identity",
     "selector": T_AUTH,
     "expected_primary": ["test_canonicalize_remote_equivalences",
                          "test_remote_normalization_tolerates_git_suffix_slash_and_case",
                          "test_https_ssh_and_scp_forms_are_equivalent"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A17-refusal-echoes-raw-remote", "file": AUTH,
     "pairs": [['errors.append(f"origin remote refused: {origin_why} (fail closed)")',
                'errors.append(f"origin remote refused: {remote}: {origin_why} (fail closed)")', 0]],
     "invariant": "refusal messages never echo the raw remote URL (credential privacy)",
     "selector": T_AUTH,
     "expected_primary": ["test_credential_bearing_origin_refused_without_leaking_it"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "A18-clone-identity-silently-replaced", "file": AUTH,
     "pairs": [["    if not p.is_file():", "    if True:", 1]],
     "invariant": "an existing clone identity is never silently replaced",
     "selector": T_AUTH,
     "expected_primary": ["test_clone_identity_is_stable_across_ceremonies"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "G1-windows-pattern-removed", "file": GUARD,
     "pairs": [['("windows_user_home", re.compile(r"[A-Za-z]:[\\\\/]+Users[\\\\/]+[A-Za-z0-9_.-]+", re.IGNORECASE)),',
                "", 0]],
     "invariant": "windows operator-home paths are always detected",
     "selector": T_PRIV,
     "expected_primary": ["test_private_path_patterns_catch_all_required_forms",
                          "test_guard_reports_synthetic_violation"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "G2-allowlist-line-binding-removed", "file": GUARD,
     "pairs": [["return any(rel.startswith(prefix) and marker in line",
                "return any(rel.startswith(prefix)", 0]],
     "invariant": "an allowlist row only excuses its exact marker line",
     "selector": T_PRIV,
     "expected_primary": ["test_allowlist_binds_line_and_file"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "G3-allowlist-file-binding-removed", "file": GUARD,
     "pairs": [["return any(rel.startswith(prefix) and marker in line",
                "return any(marker in line", 0]],
     "invariant": "an allowlist row only excuses files under its prefix",
     "selector": T_PRIV,
     "expected_primary": ["test_allowlist_binds_line_and_file"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
    {"id": "G4-fail-open-empty-violations", "file": GUARD,
     "pairs": [['violations.append(f"{rel}:{i}: {label}: {line.strip()[:160]}")', "pass", 0]],
     "invariant": "the detector must REPORT hits; a silenced reporter fails adversarial coverage",
     "selector": T_PRIV,
     "expected_primary": ["test_guard_reports_synthetic_violation"],
     "approved_earlier_layer": [], "layered_defense_note": ""},
)

for _m in MUTATIONS:  # scope lock: never Lane-B, never calibration/
    assert _m["file"] in (AUTH, GUARD), _m["id"]


def definitions_sha256() -> str:
    """Drift lock: canonical digest of the mutation definitions + detector map."""
    return hashlib.sha256(
        json.dumps(MUTATIONS, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _replace_nth(src: str, old: str, new: str, n: int) -> str:
    idx = -1
    for _ in range(n + 1):
        idx = src.index(old, idx + 1)
    return src[:idx] + new + src[idx + len(old):]


# The retained-evidence drift-lock test validates the file this campaign is in
# the middle of regenerating; it is a meta-test, not a mutation detector, and is
# explicitly deselected from campaign-internal pytest runs (it still runs in CI
# and every normal suite invocation).
_META_TEST_DESELECT = (
    f"{T_AUTH}::test_authorization_mutation_campaign_evidence_current"
)


def _pytest_failures(selector: str) -> tuple[int, list[str]]:
    with tempfile.TemporaryDirectory() as td:
        xml = Path(td) / "r.xml"
        r = subprocess.run(
            [sys.executable, "-m", "pytest", selector, "-q", f"--junitxml={xml}",
             "--deselect", _META_TEST_DESELECT],
            cwd=ROOT, capture_output=True, text=True, timeout=900,
        )
        failed: list[str] = []
        if xml.is_file():
            for tc in ET.parse(xml).getroot().iter("testcase"):
                if tc.find("failure") is not None or tc.find("error") is not None:
                    failed.append(tc.get("name", "").split("[")[0])
        return r.returncode, sorted(set(failed))


def _local_secret_state() -> dict:
    out: dict = {}
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    cd = Path(common) if Path(common).is_absolute() else ROOT / common
    ip = cd.resolve() / "ed_clone_identity"
    out["clone_identity_sha256"] = (
        hashlib.sha256(ip.read_bytes()).hexdigest() if ip.is_file() else None)
    gd = Path(subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip())
    out["leases"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(gd.glob("ed_mission_lease_*"))
    }
    return out


def run_campaign(out_path: Path) -> int:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    secrets_before = _local_secret_state()
    base_auth_exit, base_auth_failed = _pytest_failures(T_AUTH)
    base_priv_exit, base_priv_failed = _pytest_failures(T_PRIV)
    baseline_before_ok = base_auth_exit == 0 and base_priv_exit == 0
    rows = []
    for m in MUTATIONS:
        target = ROOT / m["file"]
        orig = target.read_bytes()
        pre_sha = hashlib.sha256(orig).hexdigest()
        src = orig.decode("utf-8")
        valid = True
        try:
            for old, new, n in m["pairs"]:
                src = _replace_nth(src, old, new, n)
        except ValueError:
            valid = False
        if not valid:
            rows.append({**m, "classification": "INVALID_MUTATION", "material": False,
                         "exit_code": None, "actual_failed_tests": [],
                         "unrelated_failures": [], "exact_match_to_expected": False,
                         "preimage_sha256": pre_sha, "mutated_sha256": None,
                         "restored_sha256": pre_sha, "restoration_exact": True})
            continue
        target.write_text(src, encoding="utf-8", newline="")
        mut_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        exit_code, failed = _pytest_failures(m["selector"])
        target.write_bytes(orig)
        post_sha = hashlib.sha256(target.read_bytes()).hexdigest()
        prim, early = set(m["expected_primary"]), set(m["approved_earlier_layer"])
        hits_prim = sorted(set(failed) & prim)
        hits_early = sorted(set(failed) & early)
        unrelated = sorted(set(failed) - prim - early)
        if hits_prim:
            cls = "DETECTED_BY_PRIMARY_LAYER"
        elif hits_early:
            cls = "DETECTED_BY_APPROVED_EARLIER_LAYER"
        else:
            cls = "SURVIVED"
        rows.append({**m,
                     "classification": cls,
                     "material": cls.startswith("DETECTED"),
                     "exit_code": exit_code,
                     "actual_failed_tests": failed,
                     "unrelated_failures": unrelated,
                     "exact_match_to_expected": set(failed) == prim,
                     "preimage_sha256": pre_sha, "mutated_sha256": mut_sha,
                     "restored_sha256": post_sha,
                     "restoration_exact": post_sha == pre_sha})
    end_auth_exit, _ = _pytest_failures(T_AUTH)
    end_priv_exit, _ = _pytest_failures(T_PRIV)
    secrets_after = _local_secret_state()
    summary = {}
    for r in rows:
        summary[r["classification"]] = summary.get(r["classification"], 0) + 1
    evidence = {
        "schema": "AUTHORIZATION_MUTATION_CAMPAIGN",
        "schema_version": 1,
        "base_sha": head,
        "definitions_sha256": definitions_sha256(),
        "detection_rule": ("a mutation is DETECTED only when a predeclared detector test "
                           "fails; primary beats approved-earlier-layer; failures outside "
                           "the predeclared map are recorded as unrelated and never count; "
                           "restoration must be byte-exact; baseline green before and after"),
        "baseline": {
            "before": {"auth_exit": base_auth_exit, "priv_exit": base_priv_exit,
                       "failed": sorted(base_auth_failed + base_priv_failed),
                       "exit_code": max(base_auth_exit, base_priv_exit)},
            "after": {"auth_exit": end_auth_exit, "priv_exit": end_priv_exit,
                      "exit_code": max(end_auth_exit, end_priv_exit)},
        },
        "local_secret_preservation": {
            "before": secrets_before, "after": secrets_after,
            "unchanged": secrets_before == secrets_after,
        },
        "mutation_total": len(rows),
        "summary": {k: summary.get(k, 0) for k in
                    ("DETECTED_BY_PRIMARY_LAYER", "DETECTED_BY_APPROVED_EARLIER_LAYER",
                     "SURVIVED", "INVALID_MUTATION")},
        "mutations": rows,
    }
    out_path.write_text(json.dumps(evidence, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8", newline="")
    ok = (baseline_before_ok and evidence["baseline"]["after"]["exit_code"] == 0
          and all(r["material"] and r["restoration_exact"] for r in rows)
          and evidence["local_secret_preservation"]["unchanged"])
    print(f"campaign written: {out_path}")
    print(f"summary: {evidence['summary']}  baseline_ok={baseline_before_ok}  "
          f"secrets_unchanged={evidence['local_secret_preservation']['unchanged']}")
    return 0 if ok else 1


def verify() -> int:
    if not EVIDENCE.is_file():
        print("verify: FAIL — retained evidence missing")
        return 1
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    problems = []
    if ev.get("definitions_sha256") != definitions_sha256():
        problems.append("mutation definitions/detector map drifted from retained evidence")
    if ev.get("mutation_total") != len(MUTATIONS):
        problems.append("mutation count drifted")
    if ev.get("summary", {}).get("SURVIVED") != 0 or ev.get("summary", {}).get("INVALID_MUTATION") != 0:
        problems.append("retained evidence records survivors/invalid mutations")
    for r in ev.get("mutations", []):
        if not r.get("restoration_exact"):
            problems.append(f"{r.get('id')}: restoration not byte-exact")
    if problems:
        print("verify: FAIL")
        for p in problems:
            print(" -", p)
        return 1
    print(f"verify: PASS (definitions match; {ev['mutation_total']} mutations, "
          f"0 survived, 0 invalid, restorations exact)")
    return 0


def markdown() -> int:
    ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    print("| id | class | detectors that fired | unrelated | restored |")
    print("|---|---|---|---|---|")
    for r in ev["mutations"]:
        fired = ", ".join(t for t in r["actual_failed_tests"]
                          if t in set(r["expected_primary"]) | set(r["approved_earlier_layer"]))
        print(f"| {r['id']} | {r['classification']} | {fired} | "
              f"{', '.join(r['unrelated_failures']) or '-'} | "
              f"{'yes' if r['restoration_exact'] else 'NO'} |")
    print(f"\nsummary: {ev['summary']}")
    return 0


def main(argv: list[str]) -> int:
    if "--markdown" in argv:
        return markdown()
    if "--verify" in argv:
        return verify()
    if "--run" in argv:
        out = EVIDENCE
        if "--out" in argv:
            out = Path(argv[argv.index("--out") + 1])
        return run_campaign(out)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
