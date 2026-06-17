"""Paired test for tools/audit_snapshot_columns.py — locks the cull-verdict matrix.

The whole "no guessing, just facts" cull list rests on classify() never returning
CULL_CANDIDATE for a column that has any writer, any consumer (production OR
tooling), is protected (feature/active-label/infra), or still holds data. These
tests pin that fail-closed-toward-KEEP behavior.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "audit_snapshot_columns", ROOT / "tools" / "audit_snapshot_columns.py"
)
asc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(asc)


def _classify(col, null_pct, *, feature=(), active=(), infra=(), writer=(),
              prod=(), tooling=(), legacy=False):
    return asc.classify(
        col, null_pct,
        feature=set(feature), active_lbl=set(active), infra=set(infra),
        writer=set(writer), prod_consumers=list(prod), tooling_consumers=list(tooling),
        legacy=legacy,
    )[0]


def test_protected_roles_always_keep():
    assert _classify("net_gamma", 0.0, feature={"net_gamma"}) == "KEEP"
    assert _classify("outcome_5c", 50.0, active={"outcome_5c"}) == "KEEP"
    assert _classify("ts_utc", 0.0, infra={"ts_utc"}) == "KEEP"
    # protection wins even if it would otherwise be all-NULL with no writer
    assert _classify("net_gamma", 100.0, feature={"net_gamma"}) == "KEEP"


def test_wired_pending_data_not_cullable():
    # writer present + ~100% NULL -> sentiment/cross-asset trap, never CULL
    assert _classify("sentiment_av", 100.0, writer={"sentiment_av"}) == "WIRED_PENDING_DATA"
    assert _classify("net_vanna", 99.95, writer={"net_vanna"}) == "WIRED_PENDING_DATA"


def test_writer_with_production_consumer_is_live():
    assert _classify("fused_move_prob_1c", 80.0, writer={"fused_move_prob_1c"},
                     prod=["server.py"]) == "KEEP_LIVE"


def test_writer_without_production_consumer_is_review_not_cull():
    v = _classify("pred_move_prob_5c", 70.0, writer={"pred_move_prob_5c"}, tooling=["tools/x.py"])
    assert v == "WRITTEN_NO_CONSUMER"


def test_legacy_label_family_is_review():
    assert _classify("outcome_3c", 60.0, legacy=True) == "LEGACY_LABEL"
    assert _classify("pred_move_prob_13c", 50.0, legacy=True, tooling=["tools/legacy/x.py"]) == "LEGACY_LABEL"


def test_cull_candidate_requires_all_null_zero_writer_zero_consumer():
    # the ONLY path to CULL: all-NULL, no writer, no consumer in any bucket, not protected/legacy
    assert _classify("ghost_col", 100.0) == "CULL_CANDIDATE"
    # a single tooling reference removes cull-safety
    assert _classify("ghost_col", 100.0, tooling=["tools/x.py"]) != "CULL_CANDIDATE"
    # data present (not all-NULL) removes cull-safety -> populated orphan, not CULL
    assert _classify("normalized_from_subminute", 0.0) == "REVIEW_POPULATED_ORPHAN"
    # writer present removes cull-safety
    assert _classify("ghost_col", 100.0, writer={"ghost_col"}) != "CULL_CANDIDATE"


def test_production_consumer_without_writer_is_review():
    assert _classify("mystery", 10.0, prod=["signals.py"]) == "REVIEW"


def test_feature_cone_and_active_labels_extractable():
    # ground-truth anchors load and are non-empty (guards against silent AST/import drift)
    assert len(asc.feature_cone()) > 30
    assert "outcome_5c" in asc.active_outcome_columns()
    assert "valid_dir_60c" in asc.active_outcome_columns()
