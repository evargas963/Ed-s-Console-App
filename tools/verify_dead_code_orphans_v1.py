"""RC-100: prove a delete candidate is ORPHANED before anything is removed.

WHY A LIST IS NOT PROOF. RC-64 is this repo's precedent: an "unused" variable was deleted and it
took `orb_l` with it, which WAS used, in money-path liquidity_value_engine.py. A Wave-A listing is
a hypothesis; zero inbound references measured across the whole tree is evidence. Deletion is
irreversible, so the evidence comes first.

It also encodes the FENCE. The Wave-1 audit contradicts itself — it lists SQL-anchored
`tools/_diag_*` and `tools/_issue16_*` under Wave A while its own do_not_casually_delete section
protects them, and the operator repeated that protection. When a source disagrees with itself, the
conservative branch wins and the disagreement is recorded rather than silently resolved.

  python tools/verify_dead_code_orphans_v1.py            # evidence table
  python tools/verify_dead_code_orphans_v1.py --json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = (".venv", ".git", "node_modules", "__pycache__", "worktrees")
TEXT_SUFFIX = (".py", ".md", ".yaml", ".yml", ".json", ".bat", ".ps1", ".cfg", ".toml",
               ".mdc", ".html", ".txt")

#: Wave-A candidates from reports/repo_wide_adversarial_audit_wave1.json, MINUS the fenced ones.
CANDIDATES: list[str] = [
    "tools/_tmp_ablation_status.py",
    "tools/_ablation_progress_snapshot.py",
    "tools/_enumerate_all_defs.py",
    "tools/_phase_b_index_html_cleanup.py",
    "tools/_section11_register_snippet.py",
    "tools/_sweep3_apply_silent_pass_logging.py",
    "tools/_converge_interior_gaps_v1.py",
    "tools/emit_operator_trust_backtrack_reports.py",
    "tools/_phase4_fill_outcomes.py",
    "tools/_phase4_bar_check.py",
    "tools/_phase4_snapshot_detail.py",
    "tools/_phase4a_proof_not_exists.py",
    "tools/_phase4a_quantify_anchor_miss.py",
    "tools/_phase4b_audits.py",
]   # the tools/_build_section*_inventory.py builders and _section11_register_snippet.py were
    # DELETED 2026-09-06 (bedrock step 3): the 2026-05 derivation audit they built is carried
    # by the crosswalk register and computation_registry.json; nothing executed them.

#: Listed in Wave A but protected by the SAME audit's do_not_casually_delete list and by the
#: operator. Never deleted by this tool; reported so the contradiction stays visible.
FENCED: list[str] = [
    "tools/_diag_extract_compare.py",
    "tools/_issue16_schema_diff.py",
]


def _corpus() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in REPO.rglob("*"):
        sp = str(p).replace("\\", "/")
        if any(d in sp for d in SKIP_DIRS) or not p.is_file():
            continue
        if p.suffix.lower() not in TEXT_SUFFIX:
            continue
        try:
            out[sp] = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return out


#: A mention is not a dependency, and the difference decides whether deletion is safe.
#:   CODE      - an import or a subprocess invocation. Deleting BREAKS something. Hard keep.
#:   TEST      - a test names it. Hard keep.
#:   PROVENANCE- a governance ledger, closure doc or report records that this tool RAN. Deleting
#:               does not break execution, but it leaves a DANGLING POINTER - the identical class
#:               as the 8 phantom RC ids found under RC-99, where a citation resolved to nothing
#:               and taught the reader to stop following citations. The audit's own fence says the
#:               same thing about mega inventories: retire the tool WITH its audit, not before.
#:   NOISE     - this verifier, or the Wave-1 audit that proposed the deletion. Circular; ignored.
def _classify(referrer: str, stem: str, text: str) -> str:
    r = referrer.lower()
    if r.endswith("verify_dead_code_orphans_v1.py") or "repo_wide_adversarial_audit" in r:
        return "NOISE"
    if r.startswith("tests/") or "/tests/" in r:
        return "TEST"
    if r.endswith(".py"):
        if re.search(r"^\s*(?:from|import)\s+[\w.]*" + re.escape(stem) + r"\b", text, re.M) \
           or re.search(re.escape(stem) + r"\.py", text):
            return "CODE"
        return "CODE"
    return "PROVENANCE"


def audit() -> dict:
    corpus = _corpus()
    root = str(REPO).replace("\\", "/")
    out: dict[str, dict] = {}
    missing = []
    for rel in CANDIDATES:
        p = REPO / rel
        if not p.exists():
            missing.append(rel)
            continue
        stem = p.stem
        buckets: dict[str, list[str]] = {"CODE": [], "TEST": [], "PROVENANCE": [], "NOISE": []}
        for sp, text in corpus.items():
            if sp == f"{root}/{rel}":
                continue                     # a file referencing itself proves nothing
            if not re.search(r"\b" + re.escape(stem) + r"\b", text):
                continue
            rel_ref = sp.replace(root + "/", "")
            buckets[_classify(rel_ref, stem, text)].append(rel_ref)
        out[rel] = buckets
    deletable = [r for r, b in out.items() if not b["CODE"] and not b["TEST"] and not b["PROVENANCE"]]
    blocked_code = [r for r, b in out.items() if b["CODE"] or b["TEST"]]
    blocked_prov = [r for r, b in out.items()
                    if not b["CODE"] and not b["TEST"] and b["PROVENANCE"]]
    return {"scanned_files": len(corpus), "detail": out,
            "deletable_now": deletable,
            "blocked_by_code_or_test": blocked_code,
            "blocked_by_provenance": blocked_prov,
            "already_absent": missing,
            "fenced": {f: (REPO / f).exists() for f in FENCED}}


def main(argv: list[str]) -> int:
    rep = audit()
    if "--json" in argv:
        print(json.dumps(rep, indent=2))
        return 0
    print(f"\nscanned {rep['scanned_files']} text files. A MENTION is not a DEPENDENCY.\n")
    print(f"DELETABLE NOW — no code, test or provenance reference ({len(rep['deletable_now'])})")
    for r in rep["deletable_now"]:
        print(f"   {r}")
    print(f"\nBLOCKED by CODE or TEST — deleting breaks something ({len(rep['blocked_by_code_or_test'])})")
    for r in rep["blocked_by_code_or_test"]:
        b = rep["detail"][r]
        print(f"   {r}\n      code={b['CODE'][:3]} test={b['TEST'][:3]}")
    print(f"\nBLOCKED by PROVENANCE — deleting leaves a dangling pointer "
          f"({len(rep['blocked_by_provenance'])})")
    print("   Retire the tool WITH the artifact that records it, never before (RC-99 class).")
    for r in rep["blocked_by_provenance"]:
        print(f"   {r}\n      recorded in: {rep['detail'][r]['PROVENANCE'][:3]}")
    print(f"\nALREADY ABSENT ({len(rep['already_absent'])})")
    for r in rep["already_absent"]:
        print(f"   {r}")
    print("\nFENCED — in Wave A but protected by the same audit and by the operator")
    for f, exists in rep["fenced"].items():
        print(f"   {f}  present={exists}  (NOT deleted)")
    if "--check" in argv:
        # RC-106: "always exits 0 — not a lock." With --check this IS a lock: provably
        # deletable dead code (no code, test or provenance referrer, not fenced) fails loud.
        if rep["deletable_now"]:
            print(f"\nCHECK FAIL: {len(rep['deletable_now'])} provably-dead file(s) above are "
                  f"deletable NOW and still present. Delete them or show the referrer.")
            return 2
        print("\nCHECK PASS: no provably-deletable dead code.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
