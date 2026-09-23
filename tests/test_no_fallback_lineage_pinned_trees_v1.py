"""tools/reconcile_no_fallback_inventory_lineage.py used to derive its per-removal
DELETED_FILE vs EXPRESSION_REMOVED_OR_RESHAPED classification -- and its
`file_exists_now` evidence field -- from `Path.exists()` against the LIVE working tree.
Pinning PRIOR_REF/CURRENT_REF for the candidate comparison did not fix this: a file this
session (or any later one) adds, deletes, or restores at the same path would silently
flip that classification even though neither pinned git ref changed at all. That defeats
the tool's own stated purpose -- "FROZEN HISTORICAL PROOF, not a live invariant."

These tests prove the fix: classification and evidence are derived from
`git cat-file -e <ref>:<path>` against the pinned CURRENT_REF tree, never from the
working tree, so a working-tree mutation cannot change the generated report.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.reconcile_no_fallback_inventory_lineage as lineage

# A real DELETED_FILE case from the frozen report: absent at CURRENT_REF, and (checked
# below) also genuinely absent from the live working tree today -- the mutation test
# below creates it live and proves the classification does not move.
_DELETED_AT_CURRENT_REF = "tools/legacy/horizon_7/_phase4e_dataset_adequacy_v1.py"


def test_file_exists_at_ref_reads_the_pinned_tree_not_cwd():
    # A file real in CURRENT_REF's tree (this tool itself, since CURRENT_REF postdates
    # its own creation) must read True from the ref, independent of whether it happens to
    # also be present on disk right now.
    assert lineage._file_exists_at_ref(lineage.CURRENT_REF, "tools/fallback_discovery.py") is True
    # A path that never existed at any point in this repo's history must read False.
    assert lineage._file_exists_at_ref(lineage.CURRENT_REF, "no/such/path/ever.py") is False


def test_removal_classification_ignores_a_file_the_working_tree_adds_back(tmp_path):
    """MUTATION CONTROL: create the DELETED_FILE example live, on disk, at the exact
    repo-relative path the frozen report says is absent from CURRENT_REF. The
    classification must still say DELETED_FILE -- it is a fact about the pinned tree,
    not about whatever this session's working copy currently contains."""
    live_path = lineage.REPO / _DELETED_AT_CURRENT_REF
    assert not live_path.exists(), (
        f"test precondition failed: {_DELETED_AT_CURRENT_REF} already exists live -- "
        "pick a different DELETED_FILE example from the frozen report")

    classification, _reason = lineage._removal_classification({"file": _DELETED_AT_CURRENT_REF})
    assert classification == "DELETED_FILE"

    live_path.parent.mkdir(parents=True, exist_ok=True)
    live_path.write_text("# resurrected on disk by this mutation test, never committed\n",
                          encoding="utf-8")
    try:
        # The live filesystem now has this file. A tool reading Path.exists() would flip
        # to EXPRESSION_REMOVED_OR_RESHAPED here; the pinned-tree fix must not move at all.
        classification_after, _reason_after = lineage._removal_classification(
            {"file": _DELETED_AT_CURRENT_REF})
        assert classification_after == "DELETED_FILE", (
            "MUTATION CONTROL FAILED TO BITE: classification changed when the working "
            "tree gained a file at this path -- the pinned-tree fix regressed")
        assert lineage._file_exists_at_ref(lineage.CURRENT_REF, _DELETED_AT_CURRENT_REF) is False, (
            "file_exists_at_ref must stay False for the pinned ref regardless of the "
            "live working tree")
    finally:
        live_path.unlink()
        # Clean up any directories this test created, if now empty.
        for d in (live_path.parent, live_path.parent.parent):
            try:
                d.rmdir()
            except OSError:
                pass   # not empty / pre-existing -- leave it alone


def test_removal_classification_never_consults_path_exists(monkeypatch):
    """MUTATION CONTROL, the opposite direction: force _file_exists_at_ref (the pinned-
    tree answer) to say a file is ABSENT while the real live file plainly exists on disk
    right next to this test. _removal_classification must still follow the pinned-tree
    answer (DELETED_FILE), proving it no longer calls Path.exists()/REPO-relative
    filesystem checks at all -- the live filesystem's own True is never consulted."""
    present_and_live = "tools/fallback_discovery.py"
    assert (lineage.REPO / present_and_live).exists(), (
        "test precondition: the file must be live right now")

    def fake_absent(ref, path):
        assert ref == lineage.CURRENT_REF
        assert path == present_and_live
        return False   # pinned tree says absent, even though the live file exists

    monkeypatch.setattr(lineage, "_file_exists_at_ref", fake_absent)
    classification, _reason = lineage._removal_classification({"file": present_and_live})
    assert classification == "DELETED_FILE", (
        "MUTATION CONTROL FAILED TO BITE: classification must follow the pinned-tree "
        "answer, never fall back to checking the live filesystem itself")
