"""
transformer_train.py — Transformer Model Training Pipeline
===========================================================
RULE 1: RTH data only, uniform (unweighted) sample weighting — canonical per O-55.
RULE 2: No gates — train if data exists, save always.
Supports parallel (raw) and cascade (raw + 6 pred features from XGB+LSTM).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
import time
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Set, Tuple

log = logging.getLogger("transformer_train")

from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug, outcome_column

MODELS_DIR = Path("models")

SEQUENCE_LENGTH  = 20
N_HEADS          = 4
N_ENCODER_LAYERS = 2
D_MODEL          = 64
D_FF             = 128
DROPOUT          = 0.15
BATCH_SIZE       = 64
LEARNING_RATE    = 1e-3
EPOCHS           = 60
N_CLASSES        = 3


def transformer_model_path(
    ticker: str, model_dir: Path = None, *, ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> Path:
    base = model_dir or MODELS_DIR
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    t = str(ticker).strip().upper()
    return base / f"transformer_{t}_{hz}.pt"


def transformer_meta_path(
    ticker: str, model_dir: Path = None, *, ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> Path:
    base = model_dir or MODELS_DIR
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    t = str(ticker).strip().upper()
    return base / f"transformer_{t}_{hz}_meta.json"


@dataclass
class TransformerTrainResult:
    approved: bool = True
    val_accuracy: float = 0.0
    best_epoch: int = 0
    n_train: int = 0
    n_params: int = 0
    n_features: int = 0
    training_time_sec: float = 0.0
    error: str = ""
    warm_resume_used: bool = False
    warm_resume_detail: str = ""

    def summary(self):
        return f"Transformer: {self.n_train} samples, acc={self.val_accuracy*100:.1f}%, time={self.training_time_sec:.1f}s"


# ══════════════════════════════════════════════════════════════════════════════
# MODEL
# ══════════════════════════════════════════════════════════════════════════════

def build_transformer(n_features: int, seq_len: int = SEQUENCE_LENGTH, n_classes: int = N_CLASSES):
    import torch
    import torch.nn as nn

    class PositionalEncoding(nn.Module):
        def __init__(self, d_model, max_len=200):
            super().__init__()
            pe = torch.zeros(max_len, d_model)
            position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
            div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
            pe[:, 0::2] = torch.sin(position * div_term)
            if d_model > 1:
                pe[:, 1::2] = torch.cos(position * div_term[:d_model // 2])
            self.register_buffer('pe', pe.unsqueeze(0))

        def forward(self, x):
            return x + self.pe[:, :x.size(1), :]

    class TransformerClassifier(nn.Module):
        def __init__(self):
            super().__init__()
            self.input_proj = nn.Linear(n_features, D_MODEL)
            self.pos_enc = PositionalEncoding(D_MODEL, max_len=seq_len + 10)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=D_MODEL, nhead=N_HEADS, dim_feedforward=D_FF,
                dropout=DROPOUT, batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=N_ENCODER_LAYERS)
            self.classifier = nn.Sequential(
                nn.Linear(D_MODEL, 32),
                nn.ReLU(),
                nn.Dropout(DROPOUT),
                nn.Linear(32, n_classes),
            )
            self._init_weights()

        def _init_weights(self):
            for name, param in self.named_parameters():
                if 'weight' in name and param.dim() >= 2:
                    nn.init.xavier_uniform_(param)
                elif 'bias' in name:
                    nn.init.zeros_(param)

        def forward(self, x):
            x = self.input_proj(x)
            x = self.pos_enc(x)
            x = self.encoder(x)
            x = x.mean(dim=1)
            return self.classifier(x)

    return TransformerClassifier()


# ══════════════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════════════

def prepare_transformer_data(
    db_path=None,
    ticker: str = None,
    timeframe: str = None,
    min_ts_utc: Optional[float] = None,
    min_snapshots_before_sample: Optional[int] = None,
    allowed_et_dates: Optional[Set[str]] = None,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
):
    from features.training_canonical_input import training_snapshot_for_sequence_encode
    from lstm_data import (
        extract_rth_snapshots,
        TARGET_CLASSES,
        DB_PATH,
        CANONICAL_TIMEFRAME,
        canonical_reference_spot_from_sequence_window_first_bar,
    )
    _tf = timeframe or CANONICAL_TIMEFRAME
    if _tf != CANONICAL_TIMEFRAME:
        raise ValueError(
            f"prepare_transformer_data: canonical timeframe {CANONICAL_TIMEFRAME!r} required; got {_tf!r}"
        )
    _db = Path(db_path) if db_path else DB_PATH
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    label_col = outcome_column(hz)
    tickers = [ticker] if ticker else []
    if not tickers:
        try:
            from scheduler_user_tickers import load_user_scheduler_tickers_or_empty

            tickers = load_user_scheduler_tickers_or_empty()
        except Exception:
            tickers = []
        tickers = [t for t in tickers if t and not str(t).startswith("$")]

    _min_hist = int(min_snapshots_before_sample) if min_snapshots_before_sample is not None else int(SEQUENCE_LENGTH)
    if _min_hist < SEQUENCE_LENGTH:
        _min_hist = SEQUENCE_LENGTH

    from features.lstm_sequence_input import encode_lstm_structure_sequence_bar

    all_X, all_y, all_days, all_tickers = [], [], [], []
    for tkr in tickers:
        days_data = extract_rth_snapshots(
            tkr,
            timeframe=_tf,
            db_path=_db,
            require_outcome=True,
            allowed_et_dates=allowed_et_dates,
            target_column=label_col,
        )
        for day_key, snapshots in sorted(days_data.items()):
            if len(snapshots) < _min_hist:
                continue
            for end_idx in range(_min_hist, len(snapshots)):
                window = snapshots[end_idx - SEQUENCE_LENGTH:end_idx]
                current = window[-1]
                if min_ts_utc is not None:
                    cts = current.get("ts_utc")
                    if cts is None or float(cts) < float(min_ts_utc):
                        continue
                target_str = current.get(label_col)
                if target_str not in TARGET_CLASSES:
                    continue
                try:
                    ref_spot = canonical_reference_spot_from_sequence_window_first_bar(window)
                except ValueError:
                    continue
                seq = [
                    encode_lstm_structure_sequence_bar(
                        training_snapshot_for_sequence_encode(snap), ref_spot
                    )
                    for snap in window
                ]
                all_X.append(seq)
                all_y.append(TARGET_CLASSES[target_str])
                all_days.append(day_key)
                all_tickers.append(tkr)

    if not all_X:
        return None, None, None, None, 0

    X = np.array(all_X, dtype=np.float32)
    y = np.array(all_y, dtype=np.int64)
    days = np.array(all_days)
    tickers_arr = np.array(all_tickers)
    n_features = X.shape[2]
    return X, y, days, tickers_arr, n_features


def _cascade_tensor_fp(probs: Optional[np.ndarray]) -> str:
    if probs is None or probs.size == 0:
        return ""
    a = np.ascontiguousarray(probs, dtype=np.float32)
    return hashlib.sha256(a.tobytes()).hexdigest()


TORCH_RESUME_SCHEMA = 1


def _persist_transformer_resume_checkpoint(
    *,
    resume_path: Path,
    data_fp: dict,
    scheduler_cache_key: str,
    architecture: str,
    n_features: int,
    cascade_tensor_fp: str,
    next_epoch: int,
    model,
    best_state: Optional[dict],
    best_loss: float,
    best_epoch: int,
) -> None:
    import torch
    from training_cache import _normalize_data_fp

    last_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
    try:
        torch.save(
            {
                "schema": TORCH_RESUME_SCHEMA,
                "data_fingerprint": dict(_normalize_data_fp(data_fp)),
                "scheduler_cache_key": scheduler_cache_key,
                "architecture": architecture,
                "n_features": n_features,
                "cascade_tensor_fp": cascade_tensor_fp,
                "next_epoch": int(next_epoch),
                "model_state": last_state,
                "best_state": best_state,
                "best_loss": float(best_loss),
                "best_epoch": int(best_epoch),
                "last_epoch_completed": int(next_epoch) - 1,
            },
            str(resume_path),
        )
    except Exception as ex:
        log.warning("Transformer mid-training checkpoint save failed: %s", ex)


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING — All data, exponential decay
# ══════════════════════════════════════════════════════════════════════════════

def train_transformer(
    db_path=None,
    ticker: str = None,
    model_dir: Path = None,
    xgb_lstm_probs: np.ndarray = None,
    preloaded_sequences: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]] = None,
    min_ts_utc: Optional[float] = None,
    min_snapshots_before_sample: Optional[int] = None,
    allowed_et_dates: Optional[Set[str]] = None,
    scheduler_cache_key: Optional[str] = None,
    data_fp: Optional[dict] = None,
    architecture: str = "parallel",
    bypass_torch_resume: bool = False,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> TransformerTrainResult:
    """
    Train Transformer on full data with equal/uniform sample weighting (O-55) — every row counts
    the same; no recency decay, no toggle.
    xgb_lstm_probs: optional (N, 6) for cascade — [xgb_up, xgb_dn, xgb_fl, lstm_up, lstm_dn, lstm_fl]
    preloaded_sequences: optional (X, y, days, tickers_arr, n_features) from feature cache — skips DB scan.
    Resume: optional transformer_{TICKER}_train_resume.pt when scheduler_cache_key + data_fp match policy
    (fresh AdamW each run; weights may warm-start from blob). Disabled if bypass_torch_resume or env.
    """
    import torch
    import torch.nn as nn
    from torch.utils.data import TensorDataset, DataLoader
    from ml_data_common import equal_sample_weights

    result = TransformerTrainResult()
    start_time = time.time()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    base_dir = model_dir or MODELS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    if preloaded_sequences is not None:
        X, y, days, tickers_arr, n_features = preloaded_sequences
        if X is None or len(y) == 0:
            result.error = "No data"
            return result
    else:
        X, y, days, tickers_arr, n_features = prepare_transformer_data(
            db_path,
            ticker,
            min_ts_utc=min_ts_utc,
            min_snapshots_before_sample=min_snapshots_before_sample,
            allowed_et_dates=allowed_et_dates,
            ml_horizon_slug=ml_horizon_slug,
        )
        if X is None or len(y) == 0:
            result.error = "No data"
            return result

    if xgb_lstm_probs is not None and xgb_lstm_probs.shape[0] == len(y) and xgb_lstm_probs.shape[1] == 6:
        # Append to each timestep (broadcast last bar's preds to all bars)
        extra = xgb_lstm_probs[:, np.newaxis, :]
        extra = np.broadcast_to(extra, (len(y), SEQUENCE_LENGTH, 6))
        X = np.concatenate([X, extra.astype(np.float32)], axis=2)
        n_features = X.shape[2]
        log.info("Cascade: added 6 XGB+LSTM pred features")
    result.n_features = n_features

    # Normalize (after cascade concat if any)
    flat = X.reshape(-1, X.shape[2])
    mean = flat.mean(axis=0)
    std = flat.std(axis=0)
    std[std < 1e-8] = 1.0
    X = (X - mean) / std
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # Feature mask
    var = X.reshape(-1, n_features).var(axis=0)
    feature_mask = var > 1e-8
    X = X[:, :, feature_mask]
    n_features = X.shape[2]
    result.n_features = n_features

    # O-55: equal/uniform sample weights only (all ones). No recency decay, no toggle.
    sample_w = np.asarray(equal_sample_weights(len(y)), dtype=np.float32)

    train_ds = TensorDataset(
        torch.from_numpy(X).float(),
        torch.from_numpy(y).long(),
        torch.from_numpy(sample_w).float(),
    )
    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)

    model = build_transformer(n_features).to(device)
    result.n_params = sum(p.numel() for p in model.parameters())
    result.n_train = len(y)

    from collections import Counter
    train_counts = Counter(y.tolist())
    total = len(y)
    weights = torch.tensor(
        [total / (N_CLASSES * train_counts.get(i, 1)) for i in range(N_CLASSES)],
        dtype=torch.float32
    ).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)

    best_loss = float("inf")
    best_state = None
    start_epoch = 1
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    save_ticker_early = (ticker or (sorted(set(tickers_arr.tolist()))[0] if len(tickers_arr) else "") or "").strip().upper()
    resume_path = (
        (base_dir / f"transformer_{save_ticker_early}_{hz}_train_resume.pt") if save_ticker_early else None
    )

    if (
        resume_path
        and scheduler_cache_key
        and data_fp is not None
        and not bypass_torch_resume
    ):
        from training_cache import _normalize_data_fp
        from training_cache_policy import (
            TRANSFORMER_CHECKPOINT_RESUME_ALLOWED,
            TRANSFORMER_RESUME_REQUIRES_SAME_DATA_FINGERPRINT,
            env_disable_torch_resume,
        )

        if TRANSFORMER_CHECKPOINT_RESUME_ALLOWED and not env_disable_torch_resume() and resume_path.is_file():
            try:
                blob = torch.load(str(resume_path), map_location="cpu", weights_only=False)
            except Exception:
                blob = None
            if isinstance(blob, dict) and blob.get("schema") == TORCH_RESUME_SCHEMA:
                fp_ok = (not TRANSFORMER_RESUME_REQUIRES_SAME_DATA_FINGERPRINT) or (
                    _normalize_data_fp(blob.get("data_fingerprint")) == _normalize_data_fp(data_fp)
                )
                key_ok = blob.get("scheduler_cache_key") == scheduler_cache_key
                arch_ok = blob.get("architecture") == architecture
                nf_ok = int(blob.get("n_features", -1)) == n_features
                cas_fp = _cascade_tensor_fp(xgb_lstm_probs)
                cas_ok = architecture != "cascade" or blob.get("cascade_tensor_fp") == cas_fp
                ne = int(blob.get("next_epoch", 1))
                if fp_ok and key_ok and arch_ok and nf_ok and cas_ok and 1 <= ne <= EPOCHS:
                    try:
                        model.load_state_dict(blob["model_state"])
                        start_epoch = ne
                        best_loss = float(blob.get("best_loss", float("inf")))
                        bs = blob.get("best_state")
                        if isinstance(bs, dict):
                            best_state = bs
                        result.warm_resume_used = True
                        result.warm_resume_detail = f"epochs_{start_epoch}-{EPOCHS}"
                    except Exception as ex:
                        log.warning("Transformer resume load failed, clean train: %s", ex)
                        model = build_transformer(n_features).to(device)
                        optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
                        start_epoch = 1
                        best_loss = float("inf")
                        best_state = None

    for epoch in range(start_epoch, EPOCHS + 1):
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0
        for xb, yb, wb in train_dl:
            xb, yb, wb = xb.to(device), yb.to(device), wb.to(device)
            optimizer.zero_grad()
            logits = model(xb)
            loss_per = criterion(logits, yb)
            loss = (loss_per * wb).sum() / wb.sum()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item() * len(yb)
            train_correct += (logits.argmax(dim=1) == yb).sum().item()
            train_total += len(yb)
        train_acc = train_correct / train_total if train_total else 0
        if train_loss / train_total < best_loss:
            best_loss = train_loss / train_total
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            result.best_epoch = epoch
        if epoch % 10 == 0 or epoch == 1:
            log.info("Epoch %d: loss=%.4f acc=%.1f%%", epoch, train_loss / train_total, train_acc * 100)

        if (
            resume_path
            and scheduler_cache_key
            and data_fp is not None
            and not bypass_torch_resume
        ):
            from training_cache_policy import TORCH_CHECKPOINT_EVERY_N_EPOCHS

            ncp = int(TORCH_CHECKPOINT_EVERY_N_EPOCHS)
            if ncp > 0 and epoch < EPOCHS and (epoch % ncp == 0):
                _persist_transformer_resume_checkpoint(
                    resume_path=resume_path,
                    data_fp=data_fp,
                    scheduler_cache_key=scheduler_cache_key,
                    architecture=architecture,
                    n_features=n_features,
                    cascade_tensor_fp=_cascade_tensor_fp(xgb_lstm_probs),
                    next_epoch=epoch + 1,
                    model=model,
                    best_state=best_state,
                    best_loss=best_loss,
                    best_epoch=result.best_epoch,
                )

    result.training_time_sec = time.time() - start_time

    if best_state:
        model.load_state_dict(best_state)
    model.eval()

    eval_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=False)
    all_preds = []
    with torch.no_grad():
        for xb, yb, _ in eval_dl:
            xb = xb.to(device)
            preds = model(xb).argmax(dim=1)
            all_preds.extend(preds.cpu().numpy())
    result.val_accuracy = float(np.mean(np.array(all_preds) == y))

    save_ticker = ticker or (sorted(set(tickers_arr))[0] if len(tickers_arr) else "unknown")

    from training_provenance import build_transformer_provenance

    meta = {
        "model_type": "transformer_encoder",
        "ticker": save_ticker,
        "trained_at": datetime.now().isoformat(),
        "val_accuracy": round(result.val_accuracy, 4),
        "n_train": result.n_train,
        "n_params": result.n_params,
        "n_features": n_features,
        "training_time_sec": round(result.training_time_sec, 1),
    }
    timestamps = sorted(set(days.tolist())) if days is not None and len(days) else []
    from model_contract import contract_metadata_dict, provenance_dict_with_contract

    prov = build_transformer_provenance(
        save_ticker, timestamps, meta, SEQUENCE_LENGTH, result.n_train, horizon_slug=hz,
    )
    meta.update(prov.to_dict())
    meta.update(contract_metadata_dict())

    # Save norm stats aligned to columns *after* feature_mask (same count as sum(mask))
    # (Older bug: used raw mean when len(mean)==len(mask), saving width mismatch vs inference.)
    mean_masked = np.asarray(mean, dtype=np.float32)[feature_mask]
    std_masked = np.asarray(std, dtype=np.float32)[feature_mask]

    from lstm_data import LSTM_ENCODER_SCHEMA_VERSION, encoded_width_5m

    torch.save({
        "model_state": best_state or model.state_dict(),
        "n_features": n_features,
        "seq_len": SEQUENCE_LENGTH,
        "d_model": D_MODEL,
        "n_heads": N_HEADS,
        "n_encoder_layers": N_ENCODER_LAYERS,
        "d_ff": D_FF,
        "encoder_schema_version": LSTM_ENCODER_SCHEMA_VERSION,
        "encoder_width_5m_pre_mask": encoded_width_5m(),
        "sample_weight_mode": "equal",
        "feature_mask": feature_mask.tolist(),
        "norm_mean": mean_masked.tolist(),
        "norm_std": std_masked.tolist(),
        "ticker": save_ticker,
        "provenance": provenance_dict_with_contract(prov.to_dict()),
    }, str(transformer_model_path(save_ticker, base_dir, ml_horizon_slug=hz)))
    with open(str(transformer_meta_path(save_ticker, base_dir, ml_horizon_slug=hz)), "w") as f:
        json.dump(meta, f, indent=2)

    if resume_path and save_ticker and scheduler_cache_key and data_fp is not None:
        _persist_transformer_resume_checkpoint(
            resume_path=resume_path,
            data_fp=data_fp,
            scheduler_cache_key=scheduler_cache_key,
            architecture=architecture,
            n_features=n_features,
            cascade_tensor_fp=_cascade_tensor_fp(xgb_lstm_probs),
            next_epoch=EPOCHS + 1,
            model=model,
            best_state=best_state,
            best_loss=best_loss,
            best_epoch=result.best_epoch,
        )

    log.info("Transformer saved — acc=%.1f%%", result.val_accuracy * 100)
    return result


if __name__ == "__main__":
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
    from db import DB_PATH as _DB_PATH_OBJ

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", type=str, default=None)
    ap.add_argument("--db", type=str, default=str(_DB_PATH_OBJ))
    ap.add_argument("--model-dir", type=str, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="transformer_train", write_capable=False)

    if args.ticker:
        model_dir = Path(args.model_dir) if args.model_dir else None
        result = train_transformer(db_path=args.db, ticker=args.ticker.upper(), model_dir=model_dir)
    else:
        from lstm_data import build_lstm_dataset
        ds = build_lstm_dataset(db_path=args.db)
        tickers = sorted(set(ds.tickers)) if ds.tickers else []
        model_dir = Path(args.model_dir) if args.model_dir else None
        for tkr in tickers:
            result = train_transformer(db_path=args.db, ticker=tkr, model_dir=model_dir)
            print(result.summary())
    if args.ticker:
        print(result.summary())
