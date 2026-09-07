"""Ablation-integrity audits (Prove-phase product code).

Extracted from the retired tools/check_fix_everything_we_touch.py under the ED
CONSOLE SLIMMING DIRECTIVE (Commit 1B). These audits enforce the whole-stack
feature-ablation contract and are consumed by the Prove-phase pipeline
(feature_curation_gate -> ml_scheduler / arch_competition.stack_bundle_eval_v1).
Load-bearing runtime truth, not enforcement machinery.

Two extraction transforms (operator-approved, ED CONSOLE SLIMMING 1B):
  * the one governance_gate_cache.cached_check wrapper on the 7x4 grid check was
    unwrapped to call _check_ablation_seven_model_four_horizon_grid_impl()
    directly (the cache basis referenced the now-deleted checker + AGENTS.md);
  * the AGENTS.md prose-marker assertions (the old machine grading its own docs)
    were dropped. Every substantive check -- placement validity, manifest bias,
    ingest purity, code/data assertions -- is preserved byte-for-byte.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# _ZERO_BIAS_AGENTS_MARKERS was removed with the AGENTS.md prose-marker
# assertion it fed (ED CONSOLE SLIMMING 1B) — no substantive check used it.

ZERO_BIAS_FEATURE_MODEL_INGEST_FAMILIES: dict[str, tuple[str, ...]] = {
    "xgb": ("xgb",),
    "lstm": ("lstm_5m", "lstm_1m"),
    "transformer": ("lstm_5m",),
}

ZERO_BIAS_WHOLE_STACK_LAYERS: tuple[str, ...] = ("meta", "monte_carlo", "regime", "fusion")

def check_zero_bias_ablation_contract() -> list[str]:
    """AGENTS § ZERO-BIAS — survivor output is the only placement router (O-56)."""
    errors: list[str] = []
    manifest_path = REPO_ROOT / "reports" / "artifacts" / "feature_ablation_manifest_leaf.json"
    if not manifest_path.is_file():
        errors.append(f"missing {manifest_path} — ZERO-BIAS requires live manifest")
        return errors
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"feature_ablation_manifest_leaf unreadable: {exc}")
        return errors

    method = payload.get("ablation_method") or {}
    primary = str(method.get("primary_pass") or "").lower()
    confirm = str(method.get("confirm_pass") or "").lower()
    if "grouped" in primary or "grouped" in confirm:
        errors.append(
            "manifest ablation_method still grouped — target is atomic per-feature per (model × horizon)"
        )

    model_families = ("xgb", "lstm_5m", "lstm_1m")

    # MODEL COVERAGE — all 7 FULL_STACK layers must be EXPLICITLY accounted (no silent 3-of-7).
    # Feature-consuming base models (ablation_method.models) each map to ingest-checked families;
    # upper-stack layers consume base OUTPUTS (no raw-feature members) → covered by whole-stack scoring.
    try:
        from governed_stack_contract import FULL_STACK_MODEL_LAYERS as _FULL_STACK
    except Exception:
        _FULL_STACK = ("xgb", "lstm", "transformer", "meta", "monte_carlo", "regime", "fusion")
    _feature_models = tuple(method.get("models") or ("xgb", "lstm", "transformer"))
    for _fm in _feature_models:
        _fams = ZERO_BIAS_FEATURE_MODEL_INGEST_FAMILIES.get(_fm)
        if _fams is None:
            errors.append(f"ZERO-BIAS coverage: feature-model {_fm!r} (in ablation_method.models) has NO ingest mapping in the detector — add it; the gate must check every feature-consuming model")
        elif not all(f in model_families for f in _fams):
            errors.append(f"ZERO-BIAS coverage: feature-model {_fm!r} maps to {_fams}, not all ingest-checked")
    _classified = set(_feature_models) | set(ZERO_BIAS_WHOLE_STACK_LAYERS)
    for _layer in _FULL_STACK:
        if _layer not in _classified:
            errors.append(f"ZERO-BIAS coverage: stack layer {_layer!r} unclassified (must be a checked feature-model OR a named whole-stack layer) — no silent omission of any of the 7")

    groups = [g for g in (payload.get("groups") or []) if g.get("disposition") == "ABLATE"]
    if not groups:
        errors.append("ablation manifest has no ABLATE groups")
        return errors

    errors.extend(check_feature_list_no_model_preassignment())

    from tools.build_feature_assignment_matrix_v2 import (
        _registered_ml_columns,
        atomic_column_for_manifest_group,
    )

    registered = _registered_ml_columns()
    live_union = set().union(*registered.values())
    manifest_atomic_cols: set[str] = set()
    reg_atomic_cols: set[str] = set()
    mislabeled_not_wired = 0
    mislabeled_in_cone = 0
    missing_atomic = 0
    db_wire: set[str] = set()
    try:
        from db import DB_PATH as _DBP
        from tools.feature_curation_gate import ablation_db_wire_ablatable_columns

        dbp = _DBP if isinstance(_DBP, Path) else Path(str(_DBP))
        if dbp.is_file():
            db_wire = ablation_db_wire_ablatable_columns(str(dbp))
    except Exception:
        db_wire = set()
    for g in groups:
        col = atomic_column_for_manifest_group(g)
        if not col:
            missing_atomic += 1
            continue
        manifest_atomic_cols.add(col)
        tier = str(g.get("catalog_tier") or "")
        if tier.startswith("REGISTERED"):
            reg_atomic_cols.add(col)
        registered_ml_cone = tier in ("REGISTERED_UNIVERSE", "REGISTERED_CONFLUENCE") and col in live_union
        must_be_in_cone = registered_ml_cone or (bool(db_wire) and col in db_wire)
        if db_wire:
            if (
                g.get("ingest_status") == "in_cone"
                and col not in db_wire
                and not registered_ml_cone
            ):
                mislabeled_in_cone += 1
            if g.get("ingest_status") == "not_wired" and must_be_in_cone:
                mislabeled_not_wired += 1
        elif g.get("ingest_status") == "not_wired" and registered_ml_cone:
            mislabeled_not_wired += 1
    if missing_atomic:
        errors.append(
            f"BIAS: {missing_atomic} ABLATE groups missing atomic_column — one atomic feature per row"
        )
    if mislabeled_in_cone:
        errors.append(
            f"BIAS: {mislabeled_in_cone} in_cone groups are not DB-wire ablatable — "
            f"reconcile manifest ingest_status to ablation_db_wire_ablatable_columns"
        )
    if mislabeled_not_wired:
        errors.append(
            f"BIAS: {mislabeled_not_wired} not_wired groups belong in the ML/DB wire cone — "
            f"ingest_status must be in_cone"
        )
    try:
        import lstm_data

        conf = set(getattr(lstm_data, "CONFLUENCE_FEATURES", []) or [])
        wire_scoring_cols: set[str] = set()
        try:
            from db import DB_PATH as _DBP
            from tools.feature_curation_gate import (
                ablation_db_wire_ablatable_columns,
                ablation_scoring_groups,
            )

            if (_DBP if isinstance(_DBP, Path) else Path(str(_DBP))).is_file():
                dbp_s = str(_DBP)
                wire_scoring_cols = {
                    str(atomic_column_for_manifest_group(g) or "")
                    for g in ablation_scoring_groups(payload, db_path=dbp_s)
                }
                wire = ablation_db_wire_ablatable_columns(dbp_s)
                conf_in_scoring = sorted(c for c in conf if c in wire_scoring_cols)
                if conf_in_scoring:
                    errors.append(
                        f"BIAS: LSTM confluence features in wire scoring groups without DB persistence: "
                        f"{conf_in_scoring}"
                    )
                conf_in_wire = sorted(c for c in conf if c in wire)
                if conf_in_wire:
                    errors.append(
                        f"BIAS: confluence columns on DB wire surface (unexpected): {conf_in_wire}"
                    )
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"could not verify wire-only confluence exclusion: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"could not verify live-feature coverage: {exc}")
    try:
        drift = live_union ^ reg_atomic_cols
        if drift:
            errors.append(
                f"STALE: manifest registered atomic columns differ from live cone by {len(drift)} "
                f"columns — regenerate manifest"
            )
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"could not verify cone staleness: {exc}")

    try:
        db_wire_verify: set[str] = set(db_wire)
        if not db_wire_verify:
            try:
                from db import DB_PATH as _DBP
                from tools.feature_curation_gate import ablation_db_wire_ablatable_columns

                dbp = _DBP if isinstance(_DBP, Path) else Path(str(_DBP))
                if dbp.is_file():
                    db_wire_verify = ablation_db_wire_ablatable_columns(str(dbp))
            except Exception:
                db_wire_verify = set()
        not_ingestible: list[str] = []
        for g in groups:
            tier = str(g.get("catalog_tier") or "")
            if not tier.startswith("REGISTERED"):
                continue
            col = atomic_column_for_manifest_group(g)
            if not col:
                continue
            gid = str(g.get("group_id") or "?")
            if col in db_wire_verify:
                continue
            if col not in live_union:
                not_ingestible.append(f"{gid}:{col}")
        if not_ingestible:
            sample = ", ".join(not_ingestible[:4])
            errors.append(
                f"BIAS: {len(not_ingestible)} registered manifest features not in live ingest cone "
                f"— e.g. {sample}. Regenerate manifest from live code."
            )
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"could not verify registered ingest coverage: {exc}")
    return errors

def check_ablation_agnostic_ingest_contract() -> list[str]:
    """Wire-only ablation ingest — DB identity enrich; scoring groups filtered to DB wire atoms."""
    errors: list[str] = []
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if not gate_py.is_file():
        errors.append("agnostic ingest: missing feature_curation_gate.py")
        return errors
    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
    for required in (
        "ablation_db_wire_ablatable_columns",
        "audit_ablation_ingest_purity",
        "audit_ablation_score_path_bias",
        "ready_for_unbiased_ablation",
        "ready_for_production_path_ablation",
        "DB identity row surface",
        "ABLATION_INGEST_DERIVED_PREFIXES",
    ):
        if required not in gate_text:
            errors.append(f"agnostic ingest: feature_curation_gate.py missing {required!r}")

    enrich_banned = (
        "attach_confluence_feature_columns",
        "engineer_single_snapshot(",
        "build_xgb_pre_engineering_snapshot_for_tick(",
    )
    try:
        import ast

        tree = ast.parse(gate_text, filename=str(gate_py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name != "_enrich_rows_for_whole_stack_ablation":
                continue
            fn_src = ast.get_source_segment(gate_text, node) or ""
            for banned in enrich_banned:
                if banned in fn_src:
                    errors.append(
                        f"agnostic ingest: _enrich_rows_for_whole_stack_ablation must not call {banned!r}"
                    )
    except SyntaxError as exc:
        errors.append(f"agnostic ingest: cannot AST-parse feature_curation_gate.py ({exc})")

    abi_py = REPO_ROOT / "arch_competition" / "ablation_bundle_inference.py"
    if abi_py.is_file():
        abi_text = abi_py.read_text(encoding="utf-8", errors="replace")
        for tok in (
            "wire_neutral_xgb_predict_from_row",
            "wire_neutral_confluence_vector",
            "wire_row_surface_bars",
            "score_unified_ablation_fusion_from_wire_row",
        ):
            if tok not in abi_text:
                errors.append(f"agnostic ingest: ablation_bundle_inference.py missing {tok!r}")

    mp_py = REPO_ROOT / "ml_predict.py"
    if mp_py.is_file():
        mp_text = mp_py.read_text(encoding="utf-8", errors="replace")
        if "overlay_ablation_wire_row_on_sequence_bars" in mp_text:
            errors.append(
                "agnostic ingest: ml_predict.py must not reference overlay_ablation_wire_row_on_sequence_bars"
            )
        if "ablation_wire_row" in mp_text:
            errors.append("agnostic ingest: ml_predict.py must not thread ablation_wire_row")

    if "ablation_db_wire_ablatable_columns" not in gate_text.split("def ablation_scoring_groups", 1)[-1][:800]:
        errors.append(
            "agnostic ingest: ablation_scoring_groups must filter to ablation_db_wire_ablatable_columns"
        )

    return errors

def check_feature_list_no_model_preassignment() -> list[str]:
    """AGENTS § ZERO-BIAS — the feature list is JUST features; NO model may be pre-ordained in it.
    Model x horizon placement is ablation's OUTPUT, derived live from each model's interface — never
    baked into the data. Any feature entry carrying members / member_counts / members_note (model
    pre-assignment) is pre-bias and FAILS the build. The runtime already derives columns from the
    live cone, so these fields are vestigial bias that must be removed from the list itself.
    (This gate exists because 'stripped' was asserted repeatedly while the tags stayed in the data —
    now it's mechanically true or the build is red.)"""
    errors: list[str] = []
    manifest = REPO_ROOT / "reports" / "artifacts" / "feature_ablation_manifest_leaf.json"
    if not manifest.is_file():
        return errors
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"feature-list bias check: manifest unreadable: {exc}")
        return errors
    banned = ("members", "member_counts", "members_note", "horizon_disposition")
    hits = [
        (g.get("group_id"), [k for k in banned if k in g])
        for g in (data.get("groups") or [])
        if any(k in g for k in banned)
    ]
    if hits:
        errors.append(
            f"ZERO-BIAS feature list: {len(hits)}/{len(data.get('groups') or [])} feature entries "
            f"pre-ordain models (e.g. {hits[0][0]} carries {hits[0][1]}). The list must be JUST "
            f"features — strip model/horizon pre-assignment fields in the manifest generator; model x "
            f"horizon placement is ablation's output, derived live, never baked into the data."
        )
    return errors

def check_no_ablation_gate_bypass_in_money_path() -> list[str]:
    """AGENTS § No patches — solid fixes only. Covers the ENTIRE seven-model stack load/score path
    (xgb, lstm, transformer, meta, monte_carlo, regime, fusion + adapters + orchestration), not a
    hand-picked subset. Ablation must NOT relax production gates to force stale/legacy bundles
    through the live path. The ablation-scored-eval flag and any silent
    sequence prefix-slice (live-width -> legacy-checkpoint-width) belong in an OFFLINE scorer, never
    in the inference money-path: a prefix-slice feeds the model the FIRST N live features, which are
    NOT the N it trained on, so LSTM/Transformer knockout scores are semantically wrong while
    preflight reads green. Any such reference in an inference module is a patch -> rejection-grade."""
    errors: list[str] = []
    # The ENTIRE seven-model stack's production load/score path — a gate-relax patch is forbidden across
    # ALL of it, never a hand-picked subset. Every one of xgb, lstm, transformer, meta, monte_carlo,
    # regime, fusion (with its input adapter) + the orchestration/contracts. The offline scorer
    # (arch_competition/**) is the ONLY place legacy-bundle adaptation may live.
    money_path = (
        # xgb
        "xgboost_model.py", "ml_predict.py", "ml_train.py", "features/xgb_model_input.py",
        # lstm
        "lstm_data.py", "lstm_model.py", "features/lstm_sequence_input.py",
        # transformer
        "transformer_model.py", "transformer_train.py",
        # meta (weighted / stacked overlay)
        "prediction_engine.py",
        # monte_carlo
        "monte_carlo.py", "mc_fusion_adjustment.py", "features/monte_carlo_stack_input.py",
        # regime
        "regime_engine.py",
        # fusion
        "bayesian_fusion.py", "fusion_contract.py", "features/fusion_model_input.py",
        # orchestration + contracts
        "signals.py", "rules_engine.py", "model_contract.py", "active_bundle_contract.py",
    )
    # Deprecated gate-relax tokens only — NOT ED_ABLATION_SCORING_PASS / ablation_scoring_pass_active
    # (legitimate offline-scoring pass with thin delegate to arch_competition/**).
    bypass_re = re.compile(
        r"ED_ABLATION_SCORED_EVAL|_is_ablation_scored_eval|check_ablation_scorable_bundle",
        re.IGNORECASE,
    )
    ml_predict_delegate_markers = (
        "ablation_scoring_pass_active",
        "ablation_bundle_inference",
        "validate_ablation_scoring_bundle_meta",
    )
    slice_tokens = ("align_encoded_sequence_to_checkpoint", "[:, :, :pre_w]", "[:,:,:pre_w]")
    for rel in money_path:
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        m = bypass_re.search(text)
        if m:
            errors.append(
                f"PATCH: {rel} references deprecated ablation gate-relax ({m.group(0)!r}) — "
                f"use ED_ABLATION_SCORING_PASS + offline scorer (arch_competition/**) only."
            )
        if rel == "ml_predict.py" and "ablation_scoring_pass_active" in text:
            missing_delegate = [t for t in ml_predict_delegate_markers if t not in text]
            if missing_delegate:
                errors.append(
                    f"PATCH: ml_predict.py uses ablation_scoring_pass_active without offline delegate "
                    f"markers {missing_delegate!r} — production path must stay fail-closed."
                )
        elif rel != "ml_predict.py" and "ablation_scoring_pass_active" in text:
            errors.append(
                f"PATCH: {rel} references ablation_scoring_pass_active outside ml_predict thin-delegate — "
                f"legacy encode belongs in arch_competition/ablation_bundle_inference.py only."
            )
        if any(tok in text for tok in slice_tokens):
            errors.append(
                f"PATCH: {rel} silent-prefix-slices the sequence tensor to a legacy checkpoint width — "
                f"the first N live features are NOT the trained N. Use frozen-lineage encode (trained "
                f"feature names from meta) or fail closed; never silent-slice."
            )
    return errors

def check_ablation_seven_model_four_horizon_grid() -> list[str]:
    """7x4 ablation-grid integrity (whole-stack, no per-model preassignment).

    Extraction (ED CONSOLE SLIMMING 1B, Option B): the former
    governance_gate_cache.cached_check wrapper was removed. Its cache basis named
    the now-deleted enforcement checker and AGENTS.md, and this audit runs only
    inside the infrequent, operator-initiated ablation preflight where a fresh
    recompute beats a cached verdict against a stale basis. The substantive logic
    is unchanged in _check_ablation_seven_model_four_horizon_grid_impl below.
    """
    return _check_ablation_seven_model_four_horizon_grid_impl()

def _check_ablation_seven_model_four_horizon_grid_impl() -> list[str]:
    """AGENTS § Ablation grid — all seven stack models × all four horizons (operator binding).

    Rejects partial grids (feature×horizon-only, base-3-only, missing horizons/models).
    Runs on every pre-commit — spec shape must match operator intent before any scored run.
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from governed_stack_contract import FULL_STACK_MODEL_LAYERS, STAGE3_ABLATION_HORIZONS

    errors: list[str] = []
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if gate_py.is_file():
        gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
        banned_fragments = (
            "feature × horizon only",
            "feature×horizon only",
            "Stage 3 grid: feature × horizon only",
        )
        for frag in banned_fragments:
            if frag in gate_text:
                errors.append(
                    f"feature_curation_gate.py: banned partial-grid doc {frag!r} — "
                    f"grid must be feature × all 7 models × all 4 horizons"
                )

    try:
        from tools.ablation_static_lock_index import get_ablation_static_lock_index
        from tools.feature_curation_gate import (
            ablation_cell_accounting,
            ablation_grid_groups,
            ablation_scoring_groups,
            whole_stack_catalog_cell_target,
            whole_stack_fusion_cell_target,
        )
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"ablation grid: cannot import feature_curation_gate ({exc})")
        return errors

    idx = get_ablation_static_lock_index()
    if idx.gate_import_error:
        errors.append(
            f"ablation grid: cannot import feature_curation_gate ({idx.gate_import_error})"
        )
        return errors

    manifest_path = idx.manifest_path
    if not manifest_path.is_file():
        errors.append(f"ablation grid: missing {manifest_path}")
        return errors

    if idx.manifest_load_error:
        errors.append(f"ablation grid: manifest unreadable: {idx.manifest_load_error}")
        return errors

    if idx.spec_build_error:
        errors.append(f"ablation grid: spec build failed: {idx.spec_build_error}")
        return errors

    manifest = idx.manifest
    enriched = idx.enriched
    specs = idx.specs
    required_models = list(FULL_STACK_MODEL_LAYERS)
    required_horizons = list(STAGE3_ABLATION_HORIZONS)
    captured = ablation_grid_groups(manifest)
    dbp_str = str(idx.db_path) if idx.db_path is not None else None
    scoring = ablation_scoring_groups(manifest, db_path=dbp_str)
    from tools.ablation_static_lock_index import enriched_rows_for_spec_build

    accounting = ablation_cell_accounting(
        manifest, specs, enriched_rows=enriched_rows_for_spec_build(enriched)
    )
    catalog_target = whole_stack_catalog_cell_target(manifest)
    runnable_target = int(accounting.get("runnable_target") or 0)
    catalog_formula = len(captured) * len(required_models) * len(required_horizons)
    scoring_formula = len(scoring) * len(required_models) * len(required_horizons)

    if catalog_target != catalog_formula:
        errors.append(
            f"ablation grid: whole_stack_catalog_cell_target={catalog_target} != "
            f"features({len(captured)})×models({len(required_models)})×"
            f"horizons({len(required_horizons)})={catalog_formula}"
        )
    if whole_stack_fusion_cell_target(manifest) != runnable_target:
        errors.append(
            "ablation grid: whole_stack_fusion_cell_target must equal runnable_target "
            "(enriched row sample required for fidelity-first runnable count)"
        )
    if len(specs) != scoring_formula:
        errors.append(
            f"ablation grid: scoring spec count {len(specs)} != in_cone({len(scoring)})×"
            f"models({len(required_models)})×horizons({len(required_horizons)})={scoring_formula} "
            f"(Stage 3 scores in_cone only; catalog retains not_wired Schwab slots)"
        )
    if accounting.get("runnable_target") != runnable_target:
        errors.append("ablation grid: ablation_cell_accounting runnable_target mismatch")
    if runnable_target > scoring_formula:
        errors.append(
            f"ablation grid: runnable_target={runnable_target} exceeds scoring grid {scoring_formula}"
        )

    if not specs:
        errors.append("ablation grid: zero placement cells — grid is empty")
        return errors

    missing_model_on_spec = [s for s in specs if not s.get("model_family")]
    if missing_model_on_spec:
        errors.append(
            f"ablation grid: {len(missing_model_on_spec)} cells missing model_family — "
            f"every cell must name one of the seven stack models"
        )

    bad_models = sorted(
        {str(s.get("model_family")) for s in specs if s.get("model_family")} - set(required_models)
    )
    if bad_models:
        errors.append(f"ablation grid: unknown model_family values {bad_models!r}")

    have_models = {str(s.get("model_family")) for s in specs if s.get("model_family")}
    missing_models = [m for m in required_models if m not in have_models]
    if missing_models:
        errors.append(
            f"ablation grid: missing stack models on grid axis {missing_models!r} — "
            f"all seven required: {required_models}"
        )

    have_hz = {str(s.get("horizon_slug")) for s in specs if s.get("horizon_slug")}
    missing_hz = [h for h in required_horizons if h not in have_hz]
    if missing_hz:
        errors.append(
            f"ablation grid: missing horizons on grid axis {missing_hz!r} — "
            f"all four required: {required_horizons}"
        )

    expected_triples: set[tuple[str, str, str]] = set()
    for g in scoring:
        gid = str(g["group_id"])
        for model in required_models:
            for hz in required_horizons:
                expected_triples.add((gid, model, hz))

    spec_triples = {
        (str(s.get("group_id")), str(s.get("model_family")), str(s.get("horizon_slug")))
        for s in specs
        if s.get("group_id") and s.get("model_family") and s.get("horizon_slug")
    }
    missing_triples = expected_triples - spec_triples
    if missing_triples:
        sample = ", ".join(f"{gid}@{model}/{hz}" for gid, model, hz in sorted(missing_triples)[:4])
        errors.append(
            f"ablation grid: missing {len(missing_triples)} (feature×model×horizon) cells "
            f"(e.g. {sample})"
        )

    silent_empty = [
        s for s in specs
        if not s.get("group_columns") and s.get("grid_skip_reason") is None
    ]
    if silent_empty:
        errors.append(
            f"ablation grid: {len(silent_empty)} cells have empty group_columns without "
            f"grid_skip_reason — every non-scorable cell must document why (not_wired, no_model_interface, …)"
        )

    return errors

def check_ablation_equal_layer_consumers() -> list[str]:
    """FIX-1: each stack model resolves its own knockout columns — no base-entry union for upper layers."""
    errors: list[str] = []
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if not gate_py.is_file():
        errors.append("ablation equal-layer: missing tools/feature_curation_gate.py")
        return errors
    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
    banned_fragments = (
        "_whole_stack_group_columns_all_entry_points",
        "no_stack_entry_columns",
        "_ablation_in_cone_fallback_columns",
        "registry gaps use fallback",
    )
    for frag in banned_fragments:
        if frag in gate_text:
            errors.append(
                f"ablation equal-layer: feature_curation_gate.py still references banned "
                f"registry/fallback bias {frag!r} — use fidelity-first unified knockouts"
            )
    required_markers = (
        "_ablation_atomic_knockout_column_candidates",
        "_whole_stack_knockout_columns",
        "audit_ablation_row_fidelity",
        "ablation_scoring_groups",
        "knockout_resolution",
    )
    for marker in required_markers:
        if marker not in gate_text:
            errors.append(
                f"ablation fidelity: feature_curation_gate.py missing required marker {marker!r}"
            )

    contract_py = REPO_ROOT / "governed_stack_contract.py"
    if contract_py.is_file():
        ctext = contract_py.read_text(encoding="utf-8", errors="replace")
        for marker in (
            "stack_layer_ablation_snapshot_columns",
            "REGIME_LAYER_SNAPSHOT_COLUMNS",
            "FUSION_OVERLAY_SNAPSHOT_COLUMNS",
            "atomic_column_consumed_by_stack_layer",
        ):
            if marker not in ctext:
                errors.append(f"ablation equal-layer: governed_stack_contract.py missing {marker!r}")

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from governed_stack_contract import FULL_STACK_MODEL_LAYERS, STACK_AUTHORITY_LAYERS
        from tools.ablation_static_lock_index import get_ablation_static_lock_index
        from tools.feature_curation_gate import ablation_row_fidelity_sample_active
    except Exception as exc:  # pragma: no cover
        errors.append(f"ablation equal-layer: import failed ({exc})")
        return errors

    idx = get_ablation_static_lock_index()
    if idx.gate_import_error:
        errors.append(f"ablation equal-layer: import failed ({idx.gate_import_error})")
        return errors

    if not idx.manifest_path.is_file():
        return errors

    if idx.manifest_load_error or idx.spec_build_error:
        errors.append(
            f"ablation equal-layer: manifest/spec build failed: "
            f"{idx.manifest_load_error or idx.spec_build_error}"
        )
        return errors

    specs = idx.specs
    fidelity_active = ablation_row_fidelity_sample_active(idx.enriched)

    multi_base_upper = [
        s
        for s in specs
        if s.get("model_family") in STACK_AUTHORITY_LAYERS
        and len(s.get("stack_entry_layers") or []) > 1
    ]
    if multi_base_upper:
        sample = multi_base_upper[0]
        errors.append(
            f"ablation equal-layer: {len(multi_base_upper)} upper-layer cells list multiple "
            f"stack_entry_layers (e.g. {sample.get('group_id')}@{sample.get('model_family')} "
            f"layers={sample.get('stack_entry_layers')!r}) — one layer per cell only"
        )

    wrong_entry = [
        s
        for s in specs
        if s.get("group_columns")
        and s.get("stack_entry_layers")
        and s.get("model_family") not in (s.get("stack_entry_layers") or [])
    ]
    if wrong_entry:
        sample = wrong_entry[0]
        errors.append(
            f"ablation equal-layer: cell {sample.get('group_id')}@{sample.get('model_family')} "
            f"has columns but stack_entry_layers={sample.get('stack_entry_layers')!r} "
            f"≠ [model_family]"
        )

    in_cone = [
        s
        for s in specs
        if s.get("ingest_status") == "in_cone" and s.get("model_family") in FULL_STACK_MODEL_LAYERS
    ]
    regime_fusion_scorable = [
        s for s in in_cone if s.get("model_family") in ("regime", "fusion", "meta") and s.get("group_columns")
    ]
    if fidelity_active and not regime_fusion_scorable:
        errors.append(
            "ablation equal-layer: zero in_cone regime/fusion/meta cells with group_columns — "
            "upper-layer registries may be empty or miswired"
        )

    preplacement = [
        s
        for s in specs
        if s.get("ingest_status") == "in_cone"
        and str(s.get("grid_skip_reason") or "") == "no_model_interface"
    ]
    if preplacement:
        sample = preplacement[0]
        errors.append(
            f"ablation ZERO-BIAS: {len(preplacement)} in_cone cells use banned pre-placement "
            f"skip no_model_interface (e.g. {sample.get('group_id')}@{sample.get('model_family')})"
        )

    runnable_by_model: dict[str, int] = {}
    for s in specs:
        if s.get("runnable"):
            mf = str(s.get("model_family") or "")
            runnable_by_model[mf] = runnable_by_model.get(mf, 0) + 1
    counts = [runnable_by_model.get(m, 0) for m in FULL_STACK_MODEL_LAYERS]
    if fidelity_active and len(set(counts)) > 1:
        errors.append(
            f"ablation ZERO-BIAS: unequal runnable counts per model (pre-placement) — {runnable_by_model}"
        )

    ng_cells = [
        s for s in specs
        if s.get("group_id") == "reg__atomic__net_gamma"
        and s.get("horizon_slug") == "1c"
    ]
    if (
        fidelity_active
        and ng_cells
        and not all(s.get("runnable") for s in ng_cells if s.get("ingest_status") == "in_cone")
    ):
        errors.append(
            "ablation ZERO-BIAS: reg__atomic__net_gamma must be runnable on all seven models @1c"
        )

    return errors

def check_ablation_full_stack_non_negotiable() -> list[str]:
    """Non-negotiable ablation integrity — 7 models × 4 horizons; no partial-ready escape hatches.

    Binds operator rule (2026-06-06): partial grids, cell gating, and XGB-only ready are
    rejection-grade. Agents and CI must pass this on every run via pre-commit or
    ``python tools/feature_curation_gate.py --ablation-audit``.
    """
    errors: list[str] = []
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if not gate_py.is_file():
        errors.append("ablation integrity: missing tools/feature_curation_gate.py")
        return errors
    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")

    required_gate_markers = (
        'result["ready"] = bool(result["ready_for_unbiased_ablation"])',
        "ready_for_unbiased_ablation",
        "audit_ablation_ingest_purity",
        "ingest_purity",
        "audit_ablation_score_path_bias",
        "score_path_bias",
        "ABLATION_SCORING_PASS_ENV",
        "probe_whole_stack_seven_layers",
        "audit_ablation_placement_validity",
        "placement_validity",
        "audit_ablation_row_fidelity",
        "row_fidelity",
        "ablation_scoring_groups",
        "all seven stack models",
        "--ablation-audit",
        "--ablation-integrity",
        "build_ablation_experiment_integrity",
        "experiment_integrity",
        'if not pf["ready"]:',
    )
    for marker in required_gate_markers:
        if marker not in gate_text:
            errors.append(f"ablation integrity: feature_curation_gate.py missing {marker!r}")

    banned_gate_fragments = (
        "whole_stack_cell_gated",
        "per_model_cell_gated",
        'ready_for_xgb_per_model"] or result["ready_for_whole_stack"]',
        "XGB per-model ablation (--ablation-include-o56) can run now",
        "stack_probe_skipped",
        "check_ablation_scorable_bundle",
        "align_encoded_sequence_to_checkpoint",
        "ED_ABLATION_SCORED_EVAL",
    )
    for frag in banned_gate_fragments:
        if frag in gate_text:
            errors.append(
                f"ablation integrity: feature_curation_gate.py banned partial-path fragment {frag!r}"
            )

    offline_modules = (
        "arch_competition/ablation_bundle_inference.py",
        "arch_competition/encoder_lineage_v2.py",
    )
    for rel in offline_modules:
        p = REPO_ROOT / rel
        if not p.is_file():
            errors.append(f"ablation integrity: missing offline scorer {rel}")
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if rel.endswith("ablation_bundle_inference.py"):
            for tok in (
                "try_load_lstm_offline",
                "try_load_transformer_offline",
                "predict_lstm_offline",
                "predict_transformer_offline",
                "validate_ablation_scoring_bundle_meta",
                "score_unified_ablation_fusion_from_wire_row",
                "wire_row_surface_bars",
            ):
                if tok not in src:
                    errors.append(f"ablation integrity: {rel} missing {tok!r}")
        if rel.endswith("encoder_lineage_v2.py"):
            for tok in ("resolve_encoder_lineage", "encode_snapshot_5m_v2", "ENCODED_FEATURES_5M_V2"):
                if tok not in src:
                    errors.append(f"ablation integrity: {rel} missing {tok!r}")

    mp_py = REPO_ROOT / "ml_predict.py"
    if mp_py.is_file():
        mp_text = mp_py.read_text(encoding="utf-8", errors="replace")
        if "ablation_scoring_pass_active" not in mp_text:
            errors.append("ablation integrity: ml_predict.py missing ablation_scoring_pass_active for bundle load")
        if "live_ablation_experiment_active" not in mp_text:
            errors.append("ablation integrity: ml_predict.py missing live_ablation_experiment_active for pre-train cards")
        if "resolve_experiment_bundle_dir" not in mp_text:
            errors.append("ablation integrity: ml_predict.py missing resolve_experiment_bundle_dir")
        if "validate_ablation_scoring_bundle_meta" not in mp_text:
            errors.append("ablation integrity: ml_predict.py missing validate_ablation_scoring_bundle_meta")
        if "try_load_lstm_offline" in mp_text or "predict_lstm_offline" in mp_text:
            errors.append(
                "ablation integrity: ml_predict.py must not delegate LSTM/TR scoring — "
                "use arch_competition/ablation_bundle_inference.py unified scorer only"
            )
        if "overlay_ablation_wire_row_on_sequence_bars" in mp_text or "ablation_wire_row" in mp_text:
            errors.append("ablation integrity: ml_predict.py must not thread ablation_wire_row or DB window overlay")
        if "ED_ABLATION_SCORED_EVAL" in mp_text:
            errors.append("ablation integrity: ml_predict.py must not reference ED_ABLATION_SCORED_EVAL")

    sbe_py = REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py"
    if sbe_py.is_file():
        sbe_text = sbe_py.read_text(encoding="utf-8", errors="replace")
        for tok in ("def whole_stack_cell_gated", "def per_model_cell_gated"):
            if tok in sbe_text:
                errors.append(
                    f"ablation integrity: stack_bundle_eval_v1.py still defines cell gating ({tok}) — "
                    f"full 2632-cell grid must never skip scored cells"
                )
        if "ED_ABLATION_SCORING_PASS" not in sbe_text:
            errors.append("ablation integrity: stack_bundle_eval_v1.py missing ED_ABLATION_SCORING_PASS")
        if "LIVE_ABLATION_EXPERIMENT_ENV" not in sbe_text:
            errors.append("ablation integrity: stack_bundle_eval_v1.py missing LIVE_ABLATION_EXPERIMENT_ENV")

    return errors

def audit_ablation_placement_validity(
    *,
    tickers: list[str] | None = None,
    horizons: list[str] | None = None,
    offline_probe: bool = True,
) -> dict:
    """Valid (feature × model × horizon) placement — not grid cardinality alone.

    Ablation scores **offline v2 bundles** under ED_ABLATION_SCORING_PASS — not live production
    serving. Fails when:
      * offline LSTM/TR won't load under ablation pass (bundle/scorer broken)
      * knockout columns resolve for lstm/transformer but do not map to checkpoint encoder indices
      * map_knockout_columns_to_encoder_indices (FIX 2) missing
    """
    import os

    errors: list[str] = []
    stats: dict = {}
    probe_tickers = tickers if tickers is not None else ["SPY"]
    probe_horizons = horizons if horizons is not None else ["1c"]
    stats["offline_probe_tickers"] = probe_tickers
    stats["offline_probe_horizons"] = probe_horizons

    abi = REPO_ROOT / "arch_competition" / "ablation_bundle_inference.py"
    if not abi.is_file() or "map_knockout_columns_to_encoder_indices" not in abi.read_text(
        encoding="utf-8", errors="replace"
    ):
        errors.append(
            "placement validity: ablation_bundle_inference.py missing "
            "map_knockout_columns_to_encoder_indices (FIX 2)"
        )

    if offline_probe:
        prev_ablation = os.environ.get("ED_ABLATION_SCORING_PASS")
        os.environ["ED_ABLATION_SCORING_PASS"] = "1"
        try:
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from active_bundle_contract import active_bundle_dir
            from arch_competition.ablation_bundle_inference import (
                map_knockout_columns_to_encoder_indices,
                try_load_lstm_offline,
                try_load_transformer_offline,
            )

            offline_failures: list[str] = []
            reference_checkpoint: dict | None = None
            for t in probe_tickers:
                for hz in probe_horizons:
                    bundle = active_bundle_dir(t, hz, models_dir=REPO_ROOT / "models")
                    if not bundle.is_dir():
                        offline_failures.append(f"missing bundle {t}/{hz}")
                        continue
                    lstm_loaded = try_load_lstm_offline(t, hz, bundle)
                    tr_loaded = try_load_transformer_offline(t, hz, bundle)
                    if lstm_loaded is None:
                        offline_failures.append(f"offline lstm {t}/{hz}")
                    elif reference_checkpoint is None:
                        reference_checkpoint = lstm_loaded[1]
                    if tr_loaded is None:
                        offline_failures.append(f"offline transformer {t}/{hz}")
            stats["offline_load_failures"] = offline_failures
            if offline_failures:
                sample = ", ".join(offline_failures[:6])
                errors.append(
                    f"placement validity: offline ablation loads failed (e.g. {sample}) — "
                    f"scorer must load v2 bundles under ED_ABLATION_SCORING_PASS"
                )

            manifest_path = (
                REPO_ROOT / "reports" / "artifacts" / "feature_ablation_manifest_leaf.json"
            )
            if reference_checkpoint is not None and manifest_path.is_file():
                from tools.feature_curation_gate import (
                    _atomic_column_for_group,
                    ablation_scoring_groups,
                    build_ablation_enriched_row_sample,
                    load_ablation_manifest,
                    _whole_stack_knockout_columns,
                )

                manifest = load_ablation_manifest(manifest_path)
                dbp = REPO_ROOT / "data" / "ed_console.db"
                enriched = (
                    build_ablation_enriched_row_sample(
                        db_path=str(dbp), manifest=manifest, tickers=probe_tickers
                    )
                    if dbp.is_file()
                    else []
                )
                groups = ablation_scoring_groups(manifest)
                lstm_noop: list[str] = []
                tr_noop: list[str] = []
                lstm_scorable = 0
                tr_scorable = 0
                lstm_variance_masked = 0
                tr_variance_masked = 0
                from arch_competition.ablation_bundle_inference import (
                    offline_v2_knockout_snapshot_columns,
                )

                for g in groups:
                    col = _atomic_column_for_group(g)
                    if not col:
                        continue
                    from tools.ablation_static_lock_index import enriched_rows_for_spec_build

                    if not _whole_stack_knockout_columns(
                        g, enriched_rows_for_spec_build(enriched)
                    ):
                        continue
                    lstm_cols = offline_v2_knockout_snapshot_columns(col, "lstm")
                    if lstm_cols:
                        from arch_competition.encoder_lineage_v2 import (
                            FEATURES_1M_V2,
                            FEATURES_5M_V2,
                        )

                        has_pre = has_post = False
                        cols_5m = [c for c in lstm_cols if c in FEATURES_5M_V2]
                        cols_1m = [c for c in lstm_cols if c in FEATURES_1M_V2]
                        if cols_5m:
                            m5 = map_knockout_columns_to_encoder_indices(
                                reference_checkpoint, cols_5m, stream="lstm_5m"
                            )
                            has_pre = has_pre or bool(m5.get("pre_mask_indices"))
                            has_post = has_post or bool(m5.get("post_mask_indices"))
                        if cols_1m:
                            m1 = map_knockout_columns_to_encoder_indices(
                                reference_checkpoint, cols_1m, stream="lstm_1m"
                            )
                            has_pre = has_pre or bool(m1.get("pre_mask_indices"))
                            has_post = has_post or bool(m1.get("post_mask_indices"))
                        if has_post:
                            lstm_scorable += 1
                        elif has_pre:
                            lstm_variance_masked += 1
                        else:
                            lstm_noop.append(col)
                    tr_cols = offline_v2_knockout_snapshot_columns(col, "transformer")
                    if tr_cols:
                        mapped = map_knockout_columns_to_encoder_indices(
                            reference_checkpoint, tr_cols, stream="transformer_5m"
                        )
                        if mapped.get("post_mask_indices"):
                            tr_scorable += 1
                        elif mapped.get("pre_mask_indices"):
                            tr_variance_masked += 1
                        else:
                            tr_noop.append(col)
                stats["captured_cone_atoms"] = len(groups)
                stats["lstm_scorable_atoms"] = lstm_scorable
                stats["transformer_scorable_atoms"] = tr_scorable
                stats["lstm_variance_masked_atoms"] = lstm_variance_masked
                stats["transformer_variance_masked_atoms"] = tr_variance_masked
                stats["lstm_noop_knockout_atoms"] = len(lstm_noop)
                stats["transformer_noop_knockout_atoms"] = len(tr_noop)
                if lstm_noop:
                    errors.append(
                        f"placement validity: {len(lstm_noop)}/{lstm_scorable} scorable lstm cells "
                        f"have knockouts that do not map to checkpoint encoder indices "
                        f"(e.g. {lstm_noop[:4]})"
                    )
                if tr_noop:
                    errors.append(
                        f"placement validity: {len(tr_noop)}/{tr_scorable} scorable transformer cells "
                        f"have knockouts that do not map to checkpoint encoder indices "
                        f"(e.g. {tr_noop[:4]})"
                    )
        except Exception as exc:
            errors.append(f"placement validity: offline probe failed: {type(exc).__name__}: {exc}")
        finally:
            if prev_ablation is None:
                os.environ.pop("ED_ABLATION_SCORING_PASS", None)
            else:
                os.environ["ED_ABLATION_SCORING_PASS"] = prev_ablation

    return {"ok": not errors, "errors": errors, "stats": stats}

def check_graphrag_fidelity_ablation_contract() -> list[str]:
    """GraphRAG fidelity-first ablation — unified knockouts, row-fidelity preflight, no registry fallback."""
    errors: list[str] = []
    gate_py = REPO_ROOT / "tools" / "feature_curation_gate.py"
    if not gate_py.is_file():
        errors.append("GraphRAG fidelity: missing feature_curation_gate.py")
        return errors
    gate_text = gate_py.read_text(encoding="utf-8", errors="replace")
    for banned in (
        "_ablation_in_cone_fallback_columns",
        "registry gaps use fallback",
    ):
        if banned in gate_text:
            errors.append(
                f"GraphRAG fidelity: feature_curation_gate.py still contains banned bias {banned!r}"
            )
    for required in (
        "audit_ablation_row_fidelity",
        "audit_ablation_ingest_purity",
        "build_ablation_enriched_row_sample",
        "ablation_scoring_groups",
        "_enrich_rows_for_whole_stack_ablation",
        "ablation_db_wire_ablatable_columns",
        'result["ingest_purity"]',
        'result["ready_for_unbiased_ablation"]',
        "knockout_resolution",
    ):
        if required not in gate_text:
            errors.append(
                f"GraphRAG fidelity: feature_curation_gate.py missing required {required!r}"
            )
    blank_slate_fn_names = frozenset(
        {
            "_enrich_rows_for_whole_stack_ablation",
            "_whole_stack_knockout_columns",
            "_ablation_atomic_knockout_column_candidates",
            "build_ablation_enriched_row_sample",
            "audit_ablation_row_fidelity",
        }
    )
    blank_slate_banned_calls = (
        "engineer_single_snapshot(",
        "build_xgb_pre_engineering_snapshot_for_tick(",
        "xgb_engineered_members_to_raw_snapshot(",
        "_merge_engineered_feature_surface(",
        "attach_confluence_feature_columns",
    )
    try:
        import ast

        tree = ast.parse(gate_text, filename=str(gate_py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in blank_slate_fn_names:
                continue
            fn_src = ast.get_source_segment(gate_text, node) or ""
            for banned in blank_slate_banned_calls:
                if banned in fn_src:
                    errors.append(
                        f"GraphRAG fidelity: {node.name} must not call XGB-biased "
                        f"enrichment/knockout {banned.rstrip('(')!r}"
                    )
    except SyntaxError as exc:
        errors.append(f"GraphRAG fidelity: cannot AST-parse feature_curation_gate.py ({exc})")
    sbe_py = REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py"
    if sbe_py.is_file():
        sbe_text = sbe_py.read_text(encoding="utf-8", errors="replace")
        for banned_branch in (
            'if af == "meta" and knockout_cols',
            "apply_ablation_knockout_columns(clean_row, permuted_row",
            "elif af in FEATURE_ABLATION_ML_STACK_LAYERS",
        ):
            if banned_branch in sbe_text:
                errors.append(
                    f"GraphRAG fidelity: stack_bundle_eval_v1.py still has per-layer knockout "
                    f"branch {banned_branch!r} — one permuted row through full stack only"
                )
        if "Single ablation score path: seven layers from one permuted DB wire row" not in sbe_text:
            if "Score one row through the unified ablation stack" not in sbe_text:
                errors.append(
                    "GraphRAG fidelity: stack_bundle_eval_v1.py missing unified wire-row ablation scorer doc"
                )
    return errors

def run_ablation_integrity_audit(
    *,
    db_path: str | None = None,
    tickers: list[str] | None = None,
    runtime: bool = True,
) -> dict:
    """Static contract + optional runtime preflight — agent/operator gate before scored ablation."""
    static_errors: list[str] = []
    static_errors.extend(check_ablation_seven_model_four_horizon_grid())
    static_errors.extend(check_ablation_equal_layer_consumers())
    static_errors.extend(check_ablation_full_stack_non_negotiable())
    static_errors.extend(check_no_ablation_gate_bypass_in_money_path())
    static_errors.extend(check_feature_list_no_model_preassignment())
    static_errors.extend(check_zero_bias_ablation_contract())
    static_errors.extend(check_graphrag_fidelity_ablation_contract())
    static_errors.extend(check_ablation_agnostic_ingest_contract())

    out: dict = {
        "audit": "ablation_full_stack_non_negotiable",
        "static_ok": not static_errors,
        "static_errors": static_errors,
    }

    if runtime:
        dbp = Path(db_path) if db_path else REPO_ROOT / "data" / "ed_console.db"
        out["db_path"] = str(dbp)
        if dbp.is_file():
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            from tools.feature_curation_gate import (
                load_ablation_manifest,
                run_ablation_preflight,
                whole_stack_fusion_cell_target,
            )

            manifest_path = REPO_ROOT / "reports" / "artifacts" / "feature_ablation_manifest_leaf.json"
            manifest = load_ablation_manifest(manifest_path)
            pf = run_ablation_preflight(manifest, db_path=str(dbp), tickers=tickers or [])
            placement = audit_ablation_placement_validity()
            out["preflight"] = pf
            out["placement_validity"] = placement
            out["whole_stack_cell_target"] = whole_stack_fusion_cell_target(manifest)
            preflight_ok = bool(pf.get("ready_for_unbiased_ablation"))
            placement_ok = bool(placement.get("ok"))
            out["runtime_ok"] = preflight_ok and placement_ok
            if pf.get("ready") and not pf.get("ready_for_unbiased_ablation"):
                out["runtime_ok"] = False
                static_errors.append(
                    "runtime: preflight ready != ready_for_unbiased_ablation — "
                    "partial-ready / production-path-only escape hatch"
                )
            if pf.get("ready_for_production_path_ablation") and not pf.get("ready_for_unbiased_ablation"):
                out["production_path_only"] = True
            if preflight_ok and not placement_ok:
                static_errors.append(
                    "runtime: preflight ready but placement_validity failed — "
                    "grid cardinality / ablation-env probe is not valid placement"
                )
                static_errors.extend(placement.get("errors") or [])
        else:
            out["runtime_ok"] = False
            out["runtime_skip"] = f"database missing: {dbp}"

    out["static_ok"] = not static_errors
    out["static_errors"] = static_errors
    out["ok"] = out["static_ok"] and (not runtime or bool(out.get("runtime_ok")))
    return out

