"""
Unified ablation stack scoring — one contiguous path, wire-row surface only.

All seven layers (xgb, lstm, transformer, meta, monte_carlo, regime, fusion) score
from the same permuted DB row dict. No production ``production_fusion_payload_for_stack``
branch, no ``ml_predict`` ablation forks, no DB history windows for LSTM/TR.
"""
from __future__ import annotations

import json
import logging

from instrument_identity import ticker_storage_key  # RC-345/F25: one canonical per-instrument identity
from pathlib import Path
from typing import Any, Optional

import numpy as np

from arch_competition.encoder_lineage_v2 import (
    ENCODER_SCHEMA_VERSION_V2,
    encode_snapshot_1m_v2,
    encode_snapshot_5m_v2,
    resolve_encoder_lineage,
)
from lstm_data import (
    CONFLUENCE_FEATURES,
    STREAM_1M_LOOKBACK,
    STREAM_5M_LOOKBACK,
    canonical_reference_spot_from_merged_window,
    micro_reference_spot_from_window,
)
from ml_horizon import normalize_ml_horizon_slug

log = logging.getLogger(__name__)


def _pre_mask_encoded_indices(
    raw_members: list[str],
    base_features: tuple[str, ...] | list[str],
    encoded_names: tuple[str, ...] | list[str],
) -> list[int]:
    """Map snapshot column names to pre-variance-mask encoder channel indices."""
    base_set = set(base_features)
    out: list[int] = []
    for raw in raw_members:
        if raw not in base_set:
            continue
        for i, name in enumerate(encoded_names):
            if name == raw or name == f"{raw}__present":
                out.append(i)
    return sorted(set(out))


def _post_mask_channel_indices(pre_indices: list[int], mask: list[bool] | np.ndarray) -> list[int]:
    """Map pre-mask encoder indices to post-variance-mask tensor channels."""
    m = np.asarray(mask, dtype=bool)
    if m.size == 0:
        return list(pre_indices)
    keep = np.flatnonzero(m)
    old_to_new = {int(old): int(new) for new, old in enumerate(keep)}
    return [old_to_new[i] for i in pre_indices if i in old_to_new]


def map_knockout_columns_to_encoder_indices(
    checkpoint: dict,
    knockout_columns: list[str],
    *,
    stream: str,
) -> dict:
    """Map knocked-out snapshot columns to checkpoint encoder channels (FIX 2).

    Offline ablation scores v2 bundles via ``encoder_lineage_v2`` — knockouts must land on
    indices the checkpoint was trained on, not the live v3 registry width.

    stream: ``lstm_5m`` | ``lstm_1m`` | ``transformer_5m``
    """
    enc_ver, names5, names1, err = resolve_encoder_lineage(checkpoint, None)
    if err:
        return {
            "reachable": False,
            "error": err,
            "pre_mask_indices": [],
            "post_mask_indices": [],
            "effective_snapshot_columns": [],
            "stream": stream,
        }

    stream = (stream or "").strip().lower()
    if stream == "lstm_5m":
        if enc_ver == ENCODER_SCHEMA_VERSION_V2:
            from arch_competition.encoder_lineage_v2 import ENCODED_FEATURES_5M_V2, FEATURES_5M_V2

            base_features, encoded_names = FEATURES_5M_V2, ENCODED_FEATURES_5M_V2
        else:
            base_features = tuple(str(x).replace("__present", "") for x in names5 if not str(x).endswith("__present"))
            encoded_names = names5
        mask = checkpoint.get("mask_5m") or [True] * len(encoded_names)
    elif stream == "lstm_1m":
        if enc_ver == ENCODER_SCHEMA_VERSION_V2:
            from arch_competition.encoder_lineage_v2 import ENCODED_FEATURES_1M_V2, FEATURES_1M_V2

            base_features, encoded_names = FEATURES_1M_V2, ENCODED_FEATURES_1M_V2
        else:
            base_features = tuple(str(x).replace("__present", "") for x in names1 if not str(x).endswith("__present"))
            encoded_names = names1
        mask = checkpoint.get("mask_1m") or [True] * len(encoded_names)
    elif stream == "transformer_5m":
        if enc_ver == ENCODER_SCHEMA_VERSION_V2:
            from arch_competition.encoder_lineage_v2 import ENCODED_FEATURES_5M_V2, FEATURES_5M_V2

            base_features, encoded_names = FEATURES_5M_V2, ENCODED_FEATURES_5M_V2
        else:
            base_features = tuple(str(x).replace("__present", "") for x in names5 if not str(x).endswith("__present"))
            encoded_names = names5
        mask = checkpoint.get("feature_mask") or checkpoint.get("mask_5m") or [True] * len(encoded_names)
    else:
        return {
            "reachable": False,
            "error": f"unknown stream {stream!r}",
            "pre_mask_indices": [],
            "post_mask_indices": [],
            "effective_snapshot_columns": [],
            "stream": stream,
        }

    pre = _pre_mask_encoded_indices(knockout_columns, list(base_features), list(encoded_names))
    post = _post_mask_channel_indices(pre, mask)
    effective = sorted({c for c in knockout_columns if c in set(base_features)})

    return {
        "reachable": bool(post),
        "encoder_schema_version": enc_ver,
        "stream": stream,
        "pre_mask_indices": pre,
        "post_mask_indices": post,
        "effective_snapshot_columns": effective,
        "error": None if post else "knockout_columns_do_not_map_to_checkpoint_encoder",
    }


def offline_v2_knockout_snapshot_columns(column: str, model_family: str) -> list[str]:
    """Snapshot columns that perturb offline v2 encode for one atomic feature (ablation placement)."""
    from arch_competition.encoder_lineage_v2 import FEATURES_1M_V2, FEATURES_5M_V2

    fam = (model_family or "").strip().lower()
    if fam == "lstm":
        out: set[str] = set()
        if column in FEATURES_5M_V2:
            out.add(column)
        if column in FEATURES_1M_V2:
            out.add(column)
        return sorted(out)
    if fam == "transformer":
        if column in FEATURES_5M_V2:
            return [column]
    return []


def validate_ablation_scoring_bundle_meta(meta: dict, family: str) -> tuple[bool, str]:
    """Minimal on-disk bundle checks for offline ablation — not production contract drift."""
    if not isinstance(meta, dict):
        return False, "meta is not a dict"
    fam = (family or "").strip().lower()
    if fam == "xgb":
        feats = meta.get("features")
        if not isinstance(feats, list) or not feats:
            return False, "xgb features[] missing"
        imp = meta.get("impute_medians")
        if not isinstance(imp, dict):
            return False, "xgb impute_medians missing"
        if not all(f in imp for f in feats):
            return False, "xgb impute_medians incomplete"
    return True, ""


def _encode_structure_bar_for_checkpoint(
    merged_row: dict,
    ref_spot: float,
    checkpoint: dict,
    *,
    apply_variance_mask: bool = True,
) -> list[float]:
    enc_ver, _n5, _n1, err = resolve_encoder_lineage(checkpoint, None)
    if err:
        raise ValueError(err)
    if enc_ver == ENCODER_SCHEMA_VERSION_V2:
        raw = encode_snapshot_5m_v2(merged_row, ref_spot)
        if apply_variance_mask:
            from arch_competition.encoder_lineage_v2 import apply_checkpoint_variance_mask

            return apply_checkpoint_variance_mask(raw, checkpoint.get("mask_5m"))
        return raw
    from features.lstm_sequence_input import encode_lstm_structure_sequence_bar

    return encode_lstm_structure_sequence_bar(merged_row, ref_spot)


def _encode_micro_bar_for_checkpoint(
    merged_row: dict,
    ref_spot: float,
    checkpoint: dict,
    *,
    apply_variance_mask: bool = True,
) -> list[float]:
    enc_ver, _n5, _n1, err = resolve_encoder_lineage(checkpoint, None)
    if err:
        raise ValueError(err)
    if enc_ver == ENCODER_SCHEMA_VERSION_V2:
        raw = encode_snapshot_1m_v2(merged_row, ref_spot)
        if apply_variance_mask:
            from arch_competition.encoder_lineage_v2 import apply_checkpoint_variance_mask

            return apply_checkpoint_variance_mask(raw, checkpoint.get("mask_1m"))
        return raw
    from features.lstm_sequence_input import encode_lstm_micro_sequence_bar

    return encode_lstm_micro_sequence_bar(merged_row, ref_spot)


def sequence_bundle_lineage_admissible(
    meta: dict | None,
    checkpoint: dict | None,
) -> tuple[bool, str]:
    """True when offline ablation can encode for this sequence checkpoint."""
    _ver, _n5, _n1, err = resolve_encoder_lineage(checkpoint or {}, meta)
    if err:
        return False, err
    return True, ""


def try_load_lstm_offline(ticker: str, hz: str, bundle_dir: Path) -> Optional[tuple[Any, dict]]:
    t = ticker_storage_key(ticker)
    su = normalize_ml_horizon_slug(hz)
    mp = bundle_dir / f"lstm_{t}_{su}.pt"
    mtp = bundle_dir / f"lstm_{t}_{su}_meta.json"
    if not mp.is_file() or not mtp.is_file():
        return None
    try:
        meta = json.loads(mtp.read_text(encoding="utf-8"))
        import torch
        from lstm_model import build_model

        checkpoint = torch.load(str(mp), map_location="cpu", weights_only=False)
        ok, reason = sequence_bundle_lineage_admissible(meta, checkpoint)
        if not ok:
            log.error("LSTM offline load %s/%s: %s", t, su, reason)
            return None
        model = build_model(
            checkpoint["n_features_5m"],
            checkpoint["n_features_1m"],
            checkpoint["n_confluence"],
        )
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        return model, checkpoint
    except Exception as exc:
        log.error("LSTM offline load failed %s/%s: %s", t, su, exc)
        return None


def try_load_transformer_offline(ticker: str, hz: str, bundle_dir: Path) -> Optional[tuple[Any, dict]]:
    t = ticker_storage_key(ticker)
    su = normalize_ml_horizon_slug(hz)
    mp = bundle_dir / f"transformer_{t}_{su}.pt"
    mtp = bundle_dir / f"transformer_{t}_{su}_meta.json"
    if not mp.is_file() or not mtp.is_file():
        return None
    try:
        meta = json.loads(mtp.read_text(encoding="utf-8"))
        import torch
        from transformer_train import build_transformer

        checkpoint = torch.load(str(mp), map_location="cpu", weights_only=False)
        ok, reason = sequence_bundle_lineage_admissible(meta, checkpoint)
        if not ok:
            log.error("Transformer offline load %s/%s: %s", t, su, reason)
            return None
        model = build_transformer(
            checkpoint["n_features"],
            seq_len=checkpoint.get("seq_len", 20),
        )
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        return model, checkpoint
    except Exception as exc:
        log.error("Transformer offline load failed %s/%s: %s", t, su, exc)
        return None


def predict_lstm_offline(
    *,
    ticker: str,
    checkpoint: dict,
    model: Any,
    merged_window: list[dict],
    merged_days: list[dict],
    parallel_runtime: bool,
    xgb_probs_arr: Optional[np.ndarray] = None,
) -> Optional[dict]:
    """LSTM forward using checkpoint lineage encode (v2 or v3)."""
    import torch
    from lstm_model import align_lstm_norm_stats, apply_normalization

    ref_spot = canonical_reference_spot_from_merged_window(merged_window)
    seq_5m = [_encode_structure_bar_for_checkpoint(s, ref_spot, checkpoint) for s in merged_window]
    micro = merged_window[-STREAM_1M_LOOKBACK:]
    # RC-318: single typed-absence producer (None/NaN/non-numeric/<=0 -> validated ref_spot;
    # the old `float(spot or ref)` raised on a non-numeric spot and let NaN through).
    mr = micro_reference_spot_from_window(micro, ref_spot)
    seq_1m = [_encode_micro_bar_for_checkpoint(s, mr, checkpoint) for s in micro]

    X_5m = np.array([seq_5m], dtype=np.float32)
    X_1m = np.array([seq_1m], dtype=np.float32)

    conf_vec = wire_neutral_confluence_vector(
        merged_days, list(CONFLUENCE_FEATURES), checkpoint=checkpoint
    )
    mask_conf = np.array(checkpoint.get("mask_conf", [True] * len(conf_vec)), dtype=bool)
    n_conf_base = len(CONFLUENCE_FEATURES)
    if mask_conf.shape[0] > n_conf_base:
        need = mask_conf.shape[0] - n_conf_base
        if need == 3:
            xa = xgb_probs_arr
            if xa is None:
                xa = np.full(3, 1.0 / 3.0, dtype=np.float32)
            xa = np.asarray(xa, dtype=np.float32).reshape(-1)
            if xa.shape[0] != 3:
                xa = np.full(3, 1.0 / 3.0, dtype=np.float32)
            conf_vec = conf_vec + xa.tolist()
        else:
            log.error(
                "LSTM offline predict %s: unexpected cascade confluence width %d",
                ticker,
                mask_conf.shape[0],
            )
            return None
    X_conf = np.array([conf_vec], dtype=np.float32)

    enc_ver, _, _, err = resolve_encoder_lineage(checkpoint, None)
    if err:
        log.error("LSTM offline predict %s: %s", ticker, err)
        return None

    if enc_ver >= 3:
        mask_5m = np.array(checkpoint.get("mask_5m", [True] * X_5m.shape[2]), dtype=bool)
        mask_1m = np.array(checkpoint.get("mask_1m", [True] * X_1m.shape[2]), dtype=bool)
        X_5m = X_5m[:, :, mask_5m]
        X_1m = X_1m[:, :, mask_1m]
    else:
        mask_5m = np.ones(X_5m.shape[2], dtype=bool)
        mask_1m = np.ones(X_1m.shape[2], dtype=bool)

    X_conf = X_conf[:, mask_conf]

    norm = checkpoint.get("norm_stats", {})
    if norm:
        aligned = align_lstm_norm_stats(norm, mask_5m, mask_1m, mask_conf)
        if aligned is None:
            return None
        X_5m, X_1m, X_conf = apply_normalization(X_5m, X_1m, X_conf, aligned)

    X_5m = np.nan_to_num(X_5m, nan=0.0, posinf=0.0, neginf=0.0)
    X_1m = np.nan_to_num(X_1m, nan=0.0, posinf=0.0, neginf=0.0)
    X_conf = np.nan_to_num(X_conf, nan=0.0, posinf=0.0, neginf=0.0)

    with torch.no_grad():
        logits = model(
            torch.tensor(X_1m, dtype=torch.float32),
            torch.tensor(X_5m, dtype=torch.float32),
            torch.tensor(X_conf, dtype=torch.float32),
        )
        probs = torch.softmax(logits, dim=1).cpu().numpy()[0]

    import ml_predict as mp

    tri = mp._require_direction_probability_triplet(
        {"up": float(probs[0]), "down": float(probs[1]), "flat": float(probs[2])}
    )
    if tri is None:
        return None
    return {"up": tri[0], "down": tri[1], "flat": tri[2]}


def wire_neutral_xgb_feature_values(
    snapshot: dict,
    *,
    feature_names: list[str],
    category_maps: dict,
    impute_medians: dict,
) -> list[float]:
    """Build XGB input vector from row dict keys only — no ``engineer_single_snapshot`` derive."""
    import numpy as np

    values: list[float] = []
    for fn in feature_names:
        if fn.startswith("cat_"):
            raw_col = fn[4:]
            val = snapshot.get(raw_col)
            mapping = category_maps.get(raw_col) or {}
            if val is not None and str(val) in mapping:
                values.append(float(mapping[str(val)]))
            else:
                values.append(float(impute_medians.get(fn, np.nan)))
        else:
            raw = snapshot.get(fn)
            if raw is None:
                values.append(float(impute_medians.get(fn, np.nan)))
            else:
                try:
                    values.append(float(raw))
                except (TypeError, ValueError):
                    values.append(float(impute_medians.get(fn, np.nan)))
    return values


def wire_neutral_xgb_predict_from_row(
    snapshot: dict,
    reg: dict,
    *,
    ticker: str,
) -> Optional[dict]:
    """XGB predict using checkpoint feature list read directly from the permuted DB row."""
    import numpy as np
    from ml_predict import CLASS_NAMES
    from ml_train import (
        apply_xgb_imputation_matrix,
        snapshot_missing_structurally_withheld_wall_distances,
    )

    try:
        spot = snapshot.get("spot")
        if spot is None or float(spot) <= 0:
            return None
    except (TypeError, ValueError):
        return None

    names = list(reg["feature_names"])
    impute = reg["meta"].get("impute_medians") or {}

    # RC-435: wire-neutral ablation must not median-fill withheld OI/vanna distances.
    if snapshot_missing_structurally_withheld_wall_distances(snapshot, names):
        return None
    vals = wire_neutral_xgb_feature_values(
        snapshot,
        feature_names=names,
        category_maps=reg.get("category_maps") or {},
        impute_medians=impute,
    )
    x_mat = apply_xgb_imputation_matrix(
        np.array([vals], dtype=np.float64),
        names,
        impute,
    )
    nfi = getattr(reg["model"], "n_features_in_", None)
    if nfi is not None and x_mat.shape[1] != int(nfi):
        return None
    probs = reg["model"].predict_proba(x_mat)[0]
    return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}


def wire_neutral_confluence_vector(
    merged_days: list[dict],
    conf_features: list[str],
    *,
    checkpoint: dict,
) -> list[float]:
    """Confluence channels from row keys on the eval bar — never ``compute_confluence_features``."""
    last = merged_days[-1] if merged_days else {}
    out: list[float] = []
    for k in conf_features:
        if k in last and last.get(k) is not None:
            try:
                out.append(float(last[k]))
                continue
            except (TypeError, ValueError):
                pass
        out.append(0.0)
    _ = checkpoint
    return out


def predict_transformer_offline(
    *,
    ticker: str,
    checkpoint: dict,
    model: Any,
    merged_window: list[dict],
    parallel_runtime: bool,
) -> Optional[dict]:
    import torch

    ref_spot = canonical_reference_spot_from_merged_window(merged_window)
    seq = [
        _encode_structure_bar_for_checkpoint(
            s, ref_spot, checkpoint, apply_variance_mask=False
        )
        for s in merged_window
    ]
    base = np.array([seq], dtype=np.float32)

    fm = np.asarray(
        checkpoint.get("feature_mask", np.ones(base.shape[2], dtype=bool)),
        dtype=bool,
    )
    if fm.shape[0] == base.shape[2]:
        base = base[:, :, fm]

    base = np.nan_to_num(base, nan=0.0, posinf=0.0, neginf=0.0)
    with torch.no_grad():
        logits = model(torch.tensor(base, dtype=torch.float32))
        probs = torch.softmax(logits, dim=1).cpu().numpy()[0]

    import ml_predict as mp

    tri = mp._require_direction_probability_triplet(
        {"up": float(probs[0]), "down": float(probs[1]), "flat": float(probs[2])}
    )
    if tri is None:
        return None
    return {"up": tri[0], "down": tri[1], "flat": tri[2]}


def _ablation_ticker_bundle_dir(ticker: str) -> Path:
    """Resolve per-ticker bundle leaf for offline ablation (``models/active/SPY``, ``active_5c/SPY``, …)."""
    import ml_predict as mp
    from active_bundle_contract import active_bundle_dir

    hz = mp.get_ml_infer_horizon_slug()
    return active_bundle_dir(ticker, hz, models_dir=Path(mp.MODEL_DIR))


def wire_row_surface_bars(wire_row: dict, count: int) -> list[dict]:
    """Wire row only — replicate for tensor seq_len; never load DB history windows."""
    bar = dict(wire_row)
    return [bar] * max(1, int(count))


def score_unified_ablation_fusion_from_wire_row(
    wire_row: dict,
    *,
    ticker: str,
    target_column: str,
) -> tuple[Optional[list[float]], Optional[int], Optional[str], dict[str, Any]]:
    """Single ablation score path: seven layers from one permuted DB wire row (no production fork)."""
    from types import SimpleNamespace

    import bayesian_fusion
    import ml_predict as mp
    from arch_competition.stack_bundle_eval_v1 import _norm_triplet, _outcome_class_index
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    from features.monte_carlo_stack_input import MonteCarloStackInputError, resolve_monte_carlo_stack_inputs
    from features.replay_signal_input_v1 import signal_input_from_snapshot_row_dict
    from governed_stack_contract import derive_stack_layers_scored, horizon_slug_to_mc_bars, mc_model_direction_inputs
    from mc_fusion_adjustment import fuse_payload_apply_mc_adjustment
    from ml_predict import stack_probs_bundle_key
    from numeric_contract import float_finite_or_none
    from regime_engine import classify_regime
    from rules_engine import compute_rules
    from signals import _unavailable_model_namespace, production_fusion_triplet_from_payload

    ts_utc = wire_row.get("ts_utc")
    if not ts_utc:
        return None, None, "missing_ts_utc", {}
    yt = _outcome_class_index(wire_row.get(target_column))
    if yt is None:
        return None, None, f"missing_or_invalid_outcome:{wire_row.get(target_column)!r}", {}

    try:
        inp = signal_input_from_snapshot_row_dict(wire_row)
    except Exception as e:
        return None, yt, f"signal_input:{type(e).__name__}", {}

    try:
        inf_v1 = build_inference_snapshot_v1_from_db_row(
            ticker=ticker,
            expiry=None,
            as_of_ts=float(ts_utc),
            db_row=wire_row,
        )
    except Exception as e:
        return None, yt, f"inference_snapshot:{type(e).__name__}", {}

    mvp = inf_v1.get("features") or {}
    try:
        rules = compute_rules(inp, mvp_features=mvp)
        regime = classify_regime(inp, rules, mvp_features=mvp)
    except Exception as e:
        return None, yt, f"rules_regime:{type(e).__name__}", {}

    direction_hint = getattr(rules, "signal", "wait") or "wait"
    tku = ticker_storage_key(ticker)
    hz = mp.get_ml_infer_horizon_slug()
    bundle_dir = _ablation_ticker_bundle_dir(tku)

    xgb_p = lstm_p = tr_p = None
    if mp._load_xgb(tku):
        reg = mp._xgb_registry[mp._model_registry_key(tku)]
        xgb_p = wire_neutral_xgb_predict_from_row(wire_row, reg, ticker=tku)

    xgb_arr = None
    if xgb_p:
        xgb_arr = np.asarray(
            [float(xgb_p.get("up", 1 / 3)), float(xgb_p.get("down", 1 / 3)), float(xgb_p.get("flat", 1 / 3))],
            dtype=np.float32,
        )

    lstm_loaded = try_load_lstm_offline(tku, hz, bundle_dir)
    if lstm_loaded:
        lstm_model, lstm_ckpt = lstm_loaded
        merged_window = wire_row_surface_bars(wire_row, STREAM_5M_LOOKBACK)
        merged_days = wire_row_surface_bars(wire_row, 1)
        lstm_p = predict_lstm_offline(
            ticker=tku,
            checkpoint=lstm_ckpt,
            model=lstm_model,
            merged_window=merged_window,
            merged_days=merged_days,
            parallel_runtime=True,
            xgb_probs_arr=xgb_arr,
        )

    tr_loaded = try_load_transformer_offline(tku, hz, bundle_dir)
    if tr_loaded:
        tr_model, tr_ckpt = tr_loaded
        seq_len = int(tr_ckpt.get("seq_len", 20))
        tr_window = wire_row_surface_bars(wire_row, seq_len)
        tr_p = predict_transformer_offline(
            ticker=tku,
            checkpoint=tr_ckpt,
            model=tr_model,
            merged_window=tr_window,
            parallel_runtime=True,
        )

    def _to_out(probs: Optional[dict]) -> Any:
        if not probs:
            return _unavailable_model_namespace()
        fused = mp._model_probs_to_fusion_out(probs, direction_hint)
        return SimpleNamespace(**fused) if fused else _unavailable_model_namespace()

    xgb_out = _to_out(xgb_p)
    lstm_out = _to_out(lstm_p)
    transformer_out = _to_out(tr_p)

    stack_probs = mp._ensemble_parallel_probs(
        tku,
        xgb_p,
        lstm_p,
        tr_p,
        meta_tabular_overlay=dict(wire_row),
    )
    spk = stack_probs_bundle_key()
    ml_bundle: dict[str, Any] = {
        "model_outputs": None,
        spk: stack_probs,
        "movement_head_probs": {},
        "governed_horizon_slug": hz,
        "mc_horizon_bars": horizon_slug_to_mc_bars(hz),
    }

    try:
        _smc = resolve_monte_carlo_stack_inputs(inp, inf_v1)
        _mc_e = None
    except MonteCarloStackInputError as e:
        _smc = None
        _mc_e = e

    try:
        import monte_carlo

        if _mc_e is not None:
            mc_out = monte_carlo.MonteCarloOutput(
                available=False,
                model_version=f"blocked ({_mc_e})",
            )
        else:
            iv = float_finite_or_none(inp.iv_level)
            _mc_regime = getattr(regime, "primary", None) if regime else None
            if _mc_regime == "unknown":
                _mc_regime = None
            _mc_regime_conf = getattr(regime, "confidence", None) if regime else None
            _m_up, _m_dn, _m_conf, _avail_map, _mc_src = mc_model_direction_inputs(
                xgb_out=xgb_out,
                lstm_out=lstm_out,
                transformer_out=transformer_out,
                stack_probs=stack_probs,
            )
            ml_bundle["stack_layer_availability"] = dict(_avail_map)
            ml_bundle["mc_stack_probability_source"] = _mc_src
            ml_bundle["mc_model_prob_up"] = _m_up
            ml_bundle["mc_model_prob_down"] = _m_dn
            ml_bundle["mc_model_confidence"] = _m_conf
            mc_out = monte_carlo.simulate(
                spot=_smc["spot"],
                iv=iv,
                horizon_bars=horizon_slug_to_mc_bars(hz),
                call_gamma_wall=_smc.get("call_gamma_wall"),
                put_gamma_wall=_smc.get("put_gamma_wall"),
                em_upper=_smc.get("em_upper"),
                em_lower=_smc.get("em_lower"),
                regime=_mc_regime,
                regime_confidence=_mc_regime_conf,
                realized_vol=_smc.get("realized_vol"),
                atr=_smc.get("atr"),
                model_prob_up=_m_up,
                model_prob_down=_m_dn,
                model_confidence=_m_conf,
                fusion_dominant=None,
                garch_sigma_bars=_smc.get("garch_sigma_bars"),
            )
    except Exception as e:
        return None, yt, f"monte_carlo:{type(e).__name__}", {}

    _ftc = bayesian_fusion.build_fusion_tick_cache(regime, rules)
    fusion_payload_base = bayesian_fusion.fuse(
        regime,
        xgb_out,
        lstm_out,
        transformer_out,
        mc_out,
        rules,
        signal_layer_v1=inf_v1.get("signal_layer_v1"),
        fusion_tick_cache=_ftc,
    )
    fusion_payload_full = fusion_payload_base
    try:
        fusion_payload_full = fuse_payload_apply_mc_adjustment(
            fusion_payload_base,
            mc_out,
            _smc.get("spot") if _smc else None,
        )
    except Exception:
        fusion_payload_full = fusion_payload_base

    layers_scored = derive_stack_layers_scored(
        xgb_out=xgb_out,
        lstm_out=lstm_out,
        transformer_out=transformer_out,
        mc_out=mc_out,
        ml_bundle=ml_bundle,
        regime=regime,
        fusion_payload=fusion_payload_full,
    )
    audit = {
        "stack_layers_scored": layers_scored,
        "mc_stack_probability_source": ml_bundle.get("mc_stack_probability_source"),
        "scoring_path": "unified_wire_row_only",
    }

    try:
        triplet = _norm_triplet(*production_fusion_triplet_from_payload(fusion_payload_full))
    except (TypeError, ValueError):
        return None, yt, "full_fusion_triplet_invalid", audit
    if triplet is None:
        return None, yt, "full_fusion_triplet_invalid", audit
    return triplet, yt, None, audit
