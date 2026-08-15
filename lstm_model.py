# lstm_model.py — Dual-Stream LSTM Model + Training Pipeline
# ============================================================
# RULE 1: RTH data only, uniform (unweighted) sample weighting — canonical per O-55.
# RULE 2: No gates — train if data exists, save always.
# Supports parallel (raw confluence) and cascade (confluence + XGB preds).

import sys
import json
import time
import logging
import hashlib
import re
import numpy as np
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug
# RC-345/F25 (train-write faucet): LSTM model/meta writers consume the ONE canonical
# ticker-artifact identity so bare 'SPX' and '$SPX' write the same basename the readers expect.
from instrument_identity import ticker_storage_key
from training_cache_policy import (
    EARLY_STOP_ENABLED,
    EARLY_STOP_MIN_DELTA,
    LSTM_EARLY_STOP_PATIENCE,
    LSTM_TRAIN_EPOCHS,
    should_early_stop,
)

log = logging.getLogger("lstm_model")

APP_DIR    = Path(__file__).parent.resolve()
MODELS_DIR = APP_DIR / "models"


class InsufficientLstmSamplesError(ValueError):
    """LSTM dataset build produced too few samples to train.

    Raised by ``_validate_lstm_dataset_shape`` before ``compute_feature_masks``
    so the scheduler gets a clean structured error instead of the downstream
    ``IndexError: tuple index out of range`` on ``X_5m.shape[2]``. The dataset
    emptiness is upstream of training; common cause is a ticker with too few
    RTH days to fill the LSTM sequence window
    (``SEQUENCE_LENGTH + STREAM_5M_LOOKBACK``).

    DATA-PIPELINE-INTEGRITY-CHAIN slice A (2026-05-26): the 2026-05-25
    incident's 9 tuple-index-out-of-range failures all had 12-19 RTH days
    (~460 rows), well below the sequence-build threshold.
    """


def _validate_lstm_dataset_shape(dataset, ticker: Optional[str] = None) -> None:
    """Pre-train guard: raise InsufficientLstmSamplesError on degenerate input.

    A valid LSTMDataset has ``X_5m.shape == (N, STREAM_5M_LOOKBACK, n_features_5m)``
    with ``N >= 1``. An empty ``build_lstm_dataset`` returns ``X_5m`` with
    shape ``(0,)`` (numpy default for empty list), which crashes
    ``compute_feature_masks`` at ``X_5m.shape[2]`` with the tuple-index
    IndexError. This check raises the clean named exception instead so the
    scheduler records a meaningful ``train_failed`` error string and any
    catch-site can act on the exception class.
    """
    n_samples = int(getattr(dataset, "n_samples", 0) or 0)
    n_days = int(getattr(dataset, "n_days", 0) or 0)
    if hasattr(dataset, "y") and dataset.y is not None:
        try:
            n_samples = max(n_samples, len(dataset.y))
        except TypeError:
            pass
    if n_samples == 0:
        raise InsufficientLstmSamplesError(
            "build_lstm_dataset produced 0 samples"
            + (f" for ticker {ticker}" if ticker else "")
            + f" (n_days={n_days}); ticker needs more RTH session coverage "
            "to fill the LSTM sequence window, or skip LSTM for this ticker"
        )
    x5 = getattr(dataset, "X_5m", None)
    if x5 is None or getattr(x5, "ndim", 0) < 3:
        ndim = getattr(x5, "ndim", "?") if x5 is not None else "None"
        shape = getattr(x5, "shape", "?") if x5 is not None else "None"
        raise InsufficientLstmSamplesError(
            f"LSTM dataset X_5m has degenerate shape={shape} ndim={ndim}"
            + (f" for ticker {ticker}" if ticker else "")
            + " (expected 3D: N, STREAM_5M_LOOKBACK, n_features_5m)"
        )


def lstm_model_path(
    ticker: str, model_dir: Path = None, *, ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> Path:
    base = model_dir or MODELS_DIR
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    t = ticker_storage_key(ticker)
    return base / f"lstm_{t}_{hz}.pt"


def lstm_meta_path(
    ticker: str, model_dir: Path = None, *, ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
) -> Path:
    base = model_dir or MODELS_DIR
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    t = ticker_storage_key(ticker)
    return base / f"lstm_{t}_{hz}_meta.json"

EPOCHS          = LSTM_TRAIN_EPOCHS   # canonical 50; env ED_TRAIN_EPOCHS_LSTM overrides (runtime lever)
BATCH_SIZE      = 64
LEARNING_RATE   = 0.001
WEIGHT_DECAY    = 1e-4
DROPOUT         = 0.3
CLIP_GRAD_NORM  = 1.0
VARIANCE_THRESHOLD = 1e-8

LSTM_TORCH_RESUME_SCHEMA = 1


def _lstm_xgb_probs_fp(xgb_probs: Optional[np.ndarray]) -> str:
    if xgb_probs is None or xgb_probs.size == 0:
        return ""
    a = np.ascontiguousarray(xgb_probs, dtype=np.float32)
    return hashlib.sha256(a.tobytes()).hexdigest()


def _persist_lstm_resume_checkpoint(
    *,
    resume_path: Path,
    schema: int,
    data_fp: dict,
    scheduler_cache_key: str,
    architecture: str,
    n_feat_5m: int,
    n_feat_1m: int,
    n_feat_conf: int,
    xgb_probs_fp: str,
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
                "schema": schema,
                "data_fingerprint": dict(_normalize_data_fp(data_fp)),
                "scheduler_cache_key": scheduler_cache_key,
                "architecture": architecture,
                "n_features_5m": n_feat_5m,
                "n_features_1m": n_feat_1m,
                "n_confluence": n_feat_conf,
                "xgb_probs_fp": xgb_probs_fp,
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
        log.warning("LSTM mid-training checkpoint save failed: %s", ex)


# ════════════════════════════════════════════════════════════════════════════════
# MODEL
# ════════════════════════════════════════════════════════════════════════════════

def build_model(n_features_5m: int, n_features_1m: int, n_confluence: int,
                n_classes: int = 3, dropout: float = DROPOUT):
    import torch
    import torch.nn as nn

    class DualStreamLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm_1m = nn.LSTM(
                input_size=n_features_1m,
                hidden_size=32,
                num_layers=1,
                batch_first=True,
                dropout=0,
            )
            self.lstm_5m = nn.LSTM(
                input_size=n_features_5m,
                hidden_size=64,
                num_layers=2,
                batch_first=True,
                dropout=dropout,
            )
            self.lstm_5m_proj = nn.Linear(64, 32)
            self.conf_branch = nn.Sequential(
                nn.Linear(n_confluence, 16),
                nn.ReLU(),
            )
            self.classifier = nn.Sequential(
                nn.Linear(80, 64),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Dropout(dropout),
                nn.Linear(32, n_classes),
            )
            self._init_weights()

        def _init_weights(self):
            for name, param in self.named_parameters():
                if "lstm" in name and "weight_ih" in name:
                    nn.init.xavier_uniform_(param)
                elif "lstm" in name and "weight_hh" in name:
                    nn.init.orthogonal_(param)
                elif "lstm" in name and "bias" in name:
                    nn.init.zeros_(param)
                    n = param.size(0)
                    param.data[n // 4:n // 2].fill_(1.0)
                elif "weight" in name and param.dim() >= 2:
                    nn.init.xavier_uniform_(param)
                elif "bias" in name:
                    nn.init.zeros_(param)

        def forward(self, x_1m, x_5m, x_conf):
            out_1m, _ = self.lstm_1m(x_1m)
            h_1m = out_1m[:, -1, :]
            out_5m, _ = self.lstm_5m(x_5m)
            h_5m = self.lstm_5m_proj(out_5m[:, -1, :])
            h_conf = self.conf_branch(x_conf)
            merged = torch.cat([h_1m, h_5m, h_conf], dim=1)
            return self.classifier(merged)

    model = DualStreamLSTM()
    log.info("Model built: %d parameters", sum(p.numel() for p in model.parameters()))
    return model


# ════════════════════════════════════════════════════════════════════════════════
# MASKING & NORMALIZATION
# ════════════════════════════════════════════════════════════════════════════════

def compute_feature_masks(X_5m, X_1m, X_conf):
    from lstm_data import ENCODED_FEATURES_5M, ENCODED_FEATURES_1M, CONFLUENCE_FEATURES
    diagnostics = {"masked_5m": [], "masked_1m": [], "masked_conf": []}
    mask_5m = np.ones(X_5m.shape[2], dtype=bool)
    for i in range(X_5m.shape[2]):
        if np.var(X_5m[:, :, i]) < VARIANCE_THRESHOLD:
            mask_5m[i] = False
            diagnostics["masked_5m"].append(
                ENCODED_FEATURES_5M[i] if i < len(ENCODED_FEATURES_5M) else f"feature_{i}"
            )
    mask_1m = np.ones(X_1m.shape[2], dtype=bool)
    for i in range(X_1m.shape[2]):
        if np.var(X_1m[:, :, i]) < VARIANCE_THRESHOLD:
            mask_1m[i] = False
            diagnostics["masked_1m"].append(
                ENCODED_FEATURES_1M[i] if i < len(ENCODED_FEATURES_1M) else f"feature_{i}"
            )
    mask_conf = np.ones(X_conf.shape[1], dtype=bool)
    for i in range(X_conf.shape[1]):
        if np.var(X_conf[:, i]) < VARIANCE_THRESHOLD:
            mask_conf[i] = False
            diagnostics["masked_conf"].append(CONFLUENCE_FEATURES[i] if i < len(CONFLUENCE_FEATURES) else f"feature_{i}")
    return mask_5m, mask_1m, mask_conf, diagnostics


def apply_masks(X_5m, X_1m, X_conf, mask_5m, mask_1m, mask_conf):
    return (
        X_5m[:, :, mask_5m],
        X_1m[:, :, mask_1m],
        X_conf[:, mask_conf],
    )


def compute_normalization(X_5m, X_1m, X_conf):
    flat_5m = X_5m.reshape(-1, X_5m.shape[2])
    mean_5m = np.mean(flat_5m, axis=0)
    std_5m = np.std(flat_5m, axis=0)
    std_5m[std_5m < 1e-8] = 1.0
    flat_1m = X_1m.reshape(-1, X_1m.shape[2])
    mean_1m = np.mean(flat_1m, axis=0)
    std_1m = np.std(flat_1m, axis=0)
    std_1m[std_1m < 1e-8] = 1.0
    mean_conf = np.mean(X_conf, axis=0)
    std_conf = np.std(X_conf, axis=0)
    std_conf[std_conf < 1e-8] = 1.0
    return {
        "mean_5m": mean_5m, "std_5m": std_5m,
        "mean_1m": mean_1m, "std_1m": std_1m,
        "mean_conf": mean_conf, "std_conf": std_conf,
    }


def apply_normalization(X_5m, X_1m, X_conf, stats):
    return (
        (X_5m - stats["mean_5m"]) / stats["std_5m"],
        (X_1m - stats["mean_1m"]) / stats["std_1m"],
        (X_conf - stats["mean_conf"]) / stats["std_conf"],
    )


def align_lstm_norm_stats(
    norm_stats: dict,
    mask_5m: np.ndarray,
    mask_1m: np.ndarray,
    mask_conf: np.ndarray,
) -> Optional[dict]:
    """
    Make mean/std vectors match masked tensor widths. Checkpoints may store stats
    either already masked (len == sum(mask)) or full-width (len == len(mask));
    inference always uses the boolean masks from the checkpoint.
    """
    if not norm_stats:
        return norm_stats

    m5 = np.asarray(mask_5m, dtype=bool).reshape(-1)
    m1 = np.asarray(mask_1m, dtype=bool).reshape(-1)
    mc = np.asarray(mask_conf, dtype=bool).reshape(-1)

    def _one(mean_key: str, std_key: str, mask: np.ndarray):
        mean = np.asarray(norm_stats[mean_key], dtype=np.float32).reshape(-1)
        std = np.asarray(norm_stats[std_key], dtype=np.float32).reshape(-1)
        std = np.where(std < 1e-8, 1.0, std)
        n_sel = int(mask.sum())
        if mean.size == mask.size:
            mean = mean[mask]
            std = std[mask]
        elif mean.size != n_sel:
            return None
        if mean.size != n_sel or std.size != n_sel:
            return None
        return mean, std

    r5 = _one("mean_5m", "std_5m", m5)
    r1 = _one("mean_1m", "std_1m", m1)
    rc = _one("mean_conf", "std_conf", mc)
    if r5 is None or r1 is None or rc is None:
        return None
    ma5, sd5 = r5
    ma1, sd1 = r1
    mac, sdc = rc
    return {
        "mean_5m": ma5,
        "std_5m": sd5,
        "mean_1m": ma1,
        "std_1m": sd1,
        "mean_conf": mac,
        "std_conf": sdc,
    }


# ════════════════════════════════════════════════════════════════════════════════
# TRAINING — All data, no validation holdback, exponential decay weights
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class TrainResult:
    approved: bool = True
    val_accuracy: float = 0.0
    n_train: int = 0
    n_params: int = 0
    best_epoch: int = 0
    train_losses: list = field(default_factory=list)
    training_time_sec: float = 0.0
    error: str = ""
    warm_resume_used: bool = False
    warm_resume_detail: str = ""

    def summary(self) -> str:
        if self.error:
            return "ERROR: " + self.error
        return (f"LSTM: {self.n_train} samples, acc={self.val_accuracy*100:.1f}%, "
                f"time={self.training_time_sec:.1f}s")


def train_lstm(
    dataset=None,
    db_path=None,
    ticker: str = None,
    model_dir: Path = None,
    xgb_probs: np.ndarray = None,
    scheduler_cache_key: Optional[str] = None,
    data_fp: Optional[dict] = None,
    architecture: str = "parallel",
    bypass_torch_resume: bool = False,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
):
    """
    Train LSTM on full data with equal/uniform sample weighting (O-55) — every row counts
    the same; no recency decay, no toggle.
    xgb_probs: optional (N, 3) for cascade — concatenated to confluence.
    Optional lstm_{TICKER}_train_resume.pt when keys match (weights only; fresh AdamW).
    """
    import torch
    import torch.nn as nn
    from torch.utils.data import TensorDataset, DataLoader
    from ml_data_common import equal_sample_weights

    result = TrainResult()
    start_time = time.time()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    base_dir = model_dir or MODELS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    if dataset is None:
        from lstm_data import build_lstm_dataset, DB_PATH

        dataset = build_lstm_dataset(
            tickers=[ticker] if ticker else None,
            db_path=db_path or DB_PATH,
            ml_horizon_slug=ml_horizon_slug,
        )

    # DATA-PIPELINE-INTEGRITY-CHAIN slice A (2026-05-26): catch degenerate /
    # empty dataset BEFORE compute_feature_masks tries X_5m.shape[2] and
    # raises the tuple-index IndexError. See the 2026-05-25 incident: 9
    # low-data tickers (12-19 RTH days) all failed at this exact path.
    _validate_lstm_dataset_shape(dataset, ticker=ticker)

    save_ticker = ticker_storage_key(ticker or (dataset.tickers[0] if dataset.tickers else "unknown"))  # RC-345/F25: resume+meta+model identity one authority
    hz = normalize_ml_horizon_slug(getattr(dataset, "ml_horizon_slug", None) or ml_horizon_slug)

    X_conf = dataset.X_conf.copy()
    if xgb_probs is not None and xgb_probs.shape[0] == len(dataset.y) and xgb_probs.shape[1] == 3:
        X_conf = np.hstack([X_conf, xgb_probs.astype(np.float32)])
        log.info("Cascade: added 3 XGB prob features to confluence")

    # Feature masking
    mask_5m, mask_1m, mask_conf, mask_diag = compute_feature_masks(
        dataset.X_5m, dataset.X_1m, X_conf
    )
    X_5m, X_1m, X_conf = apply_masks(dataset.X_5m, dataset.X_1m, X_conf, mask_5m, mask_1m, mask_conf)

    n_feat_5m, n_feat_1m, n_feat_conf = X_5m.shape[2], X_1m.shape[2], X_conf.shape[1]
    result.n_train = len(dataset.y)

    # Workstream B3 — chronological inner holdout. dataset arrays are built day-by-day from
    # ORDER BY ts_utc ASC, so the LAST rows are the most recent: hold them out as a strictly
    # later val tail. Normalization is fit on the TRAIN partition only; best_state/early-stop is
    # selected on val loss (not training loss); reported val_accuracy is out-of-sample. Thin
    # tickers (no holdout) keep the legacy full-data / in-sample path (disclosed; A1/B1-gated).
    from ml_data_common import time_ordered_tail_split

    n_rows = len(dataset.y)
    train_end, n_val = time_ordered_tail_split(n_rows)
    has_holdout = n_val > 0
    val_basis = "time_ordered_tail" if has_holdout else "in_sample_no_holdout"

    norm_fit_5m = X_5m[:train_end] if has_holdout else X_5m
    norm_fit_1m = X_1m[:train_end] if has_holdout else X_1m
    norm_fit_conf = X_conf[:train_end] if has_holdout else X_conf
    norm_stats = compute_normalization(norm_fit_5m, norm_fit_1m, norm_fit_conf)
    X_5m, X_1m, X_conf = apply_normalization(X_5m, X_1m, X_conf, norm_stats)
    X_5m = np.nan_to_num(X_5m, nan=0.0)
    X_1m = np.nan_to_num(X_1m, nan=0.0)
    X_conf = np.nan_to_num(X_conf, nan=0.0)

    from arch_competition.stack_bundle_eval_v1 import (
        ablation_survivors_training_enabled,
        zero_ablated_sequence_channels_for_model,
    )
    from lstm_data import ENCODED_FEATURES_1M, ENCODED_FEATURES_5M, FEATURES_1M, FEATURES_5M

    if ablation_survivors_training_enabled():
        X_5m, X_1m = zero_ablated_sequence_channels_for_model(
            X_5m,
            X_1m,
            mask_5m,
            mask_1m,
            model_family="lstm",
            horizon_slug=hz,
            features_5m=FEATURES_5M,
            features_1m=FEATURES_1M,
            encoded_features_5m=ENCODED_FEATURES_5M,
            encoded_features_1m=ENCODED_FEATURES_1M,
        )
        from arch_competition.stack_bundle_eval_v1 import zero_ablated_lstm_conf_channels

        X_conf = zero_ablated_lstm_conf_channels(X_conf, model_family="lstm", horizon_slug=hz)

    # O-55: equal/uniform sample weights only (all ones). No recency decay, no toggle.
    sample_w = np.asarray(equal_sample_weights(n_rows), dtype=np.float32)

    t5 = torch.tensor(X_5m)
    t1 = torch.tensor(X_1m)
    tc = torch.tensor(X_conf)
    ty = torch.tensor(dataset.y)
    tw = torch.tensor(sample_w)
    full_ds = TensorDataset(t5, t1, tc, ty, tw)
    if has_holdout:
        train_ds = TensorDataset(
            t5[:train_end], t1[:train_end], tc[:train_end], ty[:train_end], tw[:train_end]
        )
        val_ds = TensorDataset(
            t5[train_end:], t1[train_end:], tc[train_end:], ty[train_end:], tw[train_end:]
        )
        val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)
        y_val_np = dataset.y[train_end:]
    else:
        train_ds = full_ds
        val_loader = None
        y_val_np = dataset.y
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)

    model = build_model(n_feat_5m, n_feat_1m, n_feat_conf).to(device)
    result.n_params = sum(p.numel() for p in model.parameters())

    _cls_y = dataset.y[:train_end] if has_holdout else dataset.y
    class_counts = np.bincount(_cls_y, minlength=3).astype(float)
    class_counts[class_counts == 0] = 1.0
    class_weights = 1.0 / class_counts
    class_weights = class_weights / class_weights.sum() * 3.0
    weights_tensor = torch.tensor(class_weights, dtype=torch.float32).to(device)

    criterion = nn.CrossEntropyLoss(weight=weights_tensor)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)

    best_state = None
    best_loss = float("inf")
    start_epoch = 1
    resume_path = base_dir / f"lstm_{save_ticker}_{hz}_train_resume.pt"

    if (
        scheduler_cache_key
        and data_fp is not None
        and not bypass_torch_resume
    ):
        from training_cache import _normalize_data_fp
        from training_cache_policy import (
            LSTM_CHECKPOINT_RESUME_ALLOWED,
            LSTM_RESUME_REQUIRES_SAME_DATA_FINGERPRINT,
            env_disable_torch_resume,
        )

        if LSTM_CHECKPOINT_RESUME_ALLOWED and not env_disable_torch_resume() and resume_path.is_file():
            try:
                blob = torch.load(str(resume_path), map_location="cpu", weights_only=False)
            except Exception:
                blob = None
            if isinstance(blob, dict) and blob.get("schema") == LSTM_TORCH_RESUME_SCHEMA:
                fp_ok = (not LSTM_RESUME_REQUIRES_SAME_DATA_FINGERPRINT) or (
                    _normalize_data_fp(blob.get("data_fingerprint")) == _normalize_data_fp(data_fp)
                )
                key_ok = blob.get("scheduler_cache_key") == scheduler_cache_key
                arch_ok = blob.get("architecture") == architecture
                w5 = int(blob.get("n_features_5m", -1)) == n_feat_5m
                w1 = int(blob.get("n_features_1m", -1)) == n_feat_1m
                wc = int(blob.get("n_confluence", -1)) == n_feat_conf
                xfp = _lstm_xgb_probs_fp(xgb_probs)
                xok = architecture != "cascade" or blob.get("xgb_probs_fp") == xfp
                ne = int(blob.get("next_epoch", 1))
                if fp_ok and key_ok and arch_ok and w5 and w1 and wc and xok and 1 <= ne <= EPOCHS:
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
                        log.warning("LSTM resume load failed, clean train: %s", ex)
                        model = build_model(n_feat_5m, n_feat_1m, n_feat_conf).to(device)
                        optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
                        start_epoch = 1
                        best_loss = float("inf")
                        best_state = None

    epochs_no_improve = 0  # early-stop counter (only meaningful when has_holdout)
    for epoch in range(start_epoch, EPOCHS + 1):
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for batch_5m, batch_1m, batch_conf, batch_y, batch_w in train_loader:
            batch_5m = batch_5m.to(device)
            batch_1m = batch_1m.to(device)
            batch_conf = batch_conf.to(device)
            batch_y = batch_y.to(device)
            batch_w = batch_w.to(device)

            optimizer.zero_grad()
            logits = model(batch_1m, batch_5m, batch_conf)
            loss_per_sample = criterion(logits, batch_y)
            loss = (loss_per_sample * batch_w).sum() / batch_w.sum()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP_GRAD_NORM)
            optimizer.step()

            train_loss += loss.item() * len(batch_y)
            preds = logits.argmax(dim=1)
            train_correct += (preds == batch_y).sum().item()
            train_total += len(batch_y)

        train_loss /= train_total
        train_acc = train_correct / train_total
        result.train_losses.append(train_loss)

        # B3: select best_state on the held-out val tail (not training loss). Thin tickers with
        # no holdout fall back to train-loss selection (in-sample, disclosed).
        if has_holdout:
            model.eval()
            v_loss_sum = 0.0
            v_total = 0
            with torch.no_grad():
                for vb_5m, vb_1m, vb_conf, vb_y, _vw in val_loader:
                    vb_5m = vb_5m.to(device)
                    vb_1m = vb_1m.to(device)
                    vb_conf = vb_conf.to(device)
                    vb_y = vb_y.to(device)
                    v_logits = model(vb_1m, vb_5m, vb_conf)
                    v_loss_sum += float(criterion(v_logits, vb_y).item()) * len(vb_y)
                    v_total += len(vb_y)
            model.train()
            sel_loss = v_loss_sum / max(1, v_total)
        else:
            sel_loss = train_loss

        improved = sel_loss < (best_loss - EARLY_STOP_MIN_DELTA)
        if sel_loss < best_loss:
            best_loss = sel_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            result.best_epoch = epoch
        epochs_no_improve = 0 if improved else epochs_no_improve + 1

        if epoch % 10 == 0 or epoch == 1:
            log.info(
                "Epoch %d/%d: train_loss=%.4f acc=%.3f sel_loss=%.4f (%s)",
                epoch, EPOCHS, train_loss, train_acc, sel_loss, val_basis,
            )

        # Early stop: only on a real held-out val signal (never on in-sample train loss). EPOCHS is
        # the ceiling; best_state (best val epoch) is restored after the loop.
        if should_early_stop(
            enabled=EARLY_STOP_ENABLED,
            has_holdout=has_holdout,
            patience=LSTM_EARLY_STOP_PATIENCE,
            epochs_no_improve=epochs_no_improve,
        ):
            log.info(
                "LSTM early-stop at epoch %d/%d (no val improvement > %.4g for %d epochs; "
                "best_epoch=%d best_sel_loss=%.4f)",
                epoch, EPOCHS, EARLY_STOP_MIN_DELTA, epochs_no_improve,
                result.best_epoch, best_loss,
            )
            break

        if (
            scheduler_cache_key
            and data_fp is not None
            and not bypass_torch_resume
        ):
            from training_cache_policy import TORCH_CHECKPOINT_EVERY_N_EPOCHS

            n = int(TORCH_CHECKPOINT_EVERY_N_EPOCHS)
            if n > 0 and epoch < EPOCHS and (epoch % n == 0):
                _persist_lstm_resume_checkpoint(
                    resume_path=resume_path,
                    schema=LSTM_TORCH_RESUME_SCHEMA,
                    data_fp=data_fp,
                    scheduler_cache_key=scheduler_cache_key,
                    architecture=architecture,
                    n_feat_5m=n_feat_5m,
                    n_feat_1m=n_feat_1m,
                    n_feat_conf=n_feat_conf,
                    xgb_probs_fp=_lstm_xgb_probs_fp(xgb_probs),
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

    # B3: honest out-of-sample accuracy on the held-out tail (full-data in-sample only when no
    # holdout could be carved — disclosed via val_basis).
    eval_loader = (
        val_loader if has_holdout
        else DataLoader(full_ds, batch_size=BATCH_SIZE, shuffle=False)
    )
    with torch.no_grad():
        all_preds = []
        for batch_5m, batch_1m, batch_conf, batch_y, _ in eval_loader:
            batch_5m = batch_5m.to(device)
            batch_1m = batch_1m.to(device)
            batch_conf = batch_conf.to(device)
            logits = model(batch_1m, batch_5m, batch_conf)
            all_preds.extend(logits.argmax(dim=1).cpu().numpy())
    result.val_accuracy = float(np.mean(np.array(all_preds) == y_val_np))

    # Workstream B3+ degeneracy diagnostics on the same eval set (held-out tail when a holdout
    # exists, else in-sample). single_class_collapse marks an all-flat base whose top-line
    # accuracy is just the majority base rate — blocked from promotion by validate_for_promotion.
    from ml_data_common import holdout_class_metrics
    _lstm_cls_names = ["up", "down", "flat"]  # TARGET_CLASSES {up:0,down:1,flat:2}
    lstm_deg = holdout_class_metrics(y_val_np, np.array(all_preds), 3, _lstm_cls_names)
    log.info(
        "LSTM degeneracy: balanced_acc=%s recall=%s%s",
        lstm_deg["balanced_accuracy"], lstm_deg["per_class_recall"],
        "  [SINGLE-CLASS COLLAPSE]" if lstm_deg["single_class_collapse"] else "",
    )

    from lstm_data import STREAM_5M_LOOKBACK
    from training_provenance import build_lstm_provenance

    mp = lstm_model_path(save_ticker, base_dir, ml_horizon_slug=hz)
    mtp = lstm_meta_path(save_ticker, base_dir, ml_horizon_slug=hz)

    meta = {
        "model_type": "dual_stream_lstm",
        "ticker": save_ticker,
        "trained_at": datetime.now().isoformat(),
        "val_accuracy": round(result.val_accuracy, 4),
        "val_basis": val_basis,
        "balanced_accuracy": lstm_deg["balanced_accuracy"],
        "val_per_class_recall": lstm_deg["per_class_recall"],
        "val_single_class_collapse": bool(lstm_deg["single_class_collapse"]),
        "val_predicted_class_names": lstm_deg["predicted_class_names"],
        "n_val": int(n_val),
        "n_train": result.n_train,
        "n_params": result.n_params,
        "best_epoch": result.best_epoch,
        "n_features_5m": n_feat_5m,
        "n_features_1m": n_feat_1m,
        "n_confluence": n_feat_conf,
        "masked_features": mask_diag,
        "training_time_sec": round(result.training_time_sec, 1),
        "sample_weight_mode": "equal",
    }
    from model_contract import contract_metadata_dict, provenance_dict_with_contract

    prov = build_lstm_provenance(save_ticker, dataset, meta, STREAM_5M_LOOKBACK, horizon_slug=hz)
    meta.update(prov.to_dict())
    meta.update(contract_metadata_dict())

    from lstm_data import LSTM_ENCODER_SCHEMA_VERSION, encoded_width_5m, encoded_width_1m

    torch.save({
        "model_state": best_state or model.state_dict(),
        "n_features_5m": n_feat_5m,
        "n_features_1m": n_feat_1m,
        "n_confluence": n_feat_conf,
        "encoder_schema_version": LSTM_ENCODER_SCHEMA_VERSION,
        "encoder_width_5m_pre_mask": encoded_width_5m(),
        "encoder_width_1m_pre_mask": encoded_width_1m(),
        "encoder_feature_names_5m": list(ENCODED_FEATURES_5M),
        "encoder_feature_names_1m": list(ENCODED_FEATURES_1M),
        "sample_weight_mode": "equal",
        "mask_5m": mask_5m.tolist(),
        "mask_1m": mask_1m.tolist(),
        "mask_conf": mask_conf.tolist(),
        "norm_stats": {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in norm_stats.items()},
        "ticker": save_ticker,
        "provenance": provenance_dict_with_contract(prov.to_dict()),
    }, str(mp))
    with open(str(mtp), "w") as f:
        json.dump(meta, f, indent=2)

    if scheduler_cache_key and data_fp is not None:
        _persist_lstm_resume_checkpoint(
            resume_path=resume_path,
            schema=LSTM_TORCH_RESUME_SCHEMA,
            data_fp=data_fp,
            scheduler_cache_key=scheduler_cache_key,
            architecture=architecture,
            n_feat_5m=n_feat_5m,
            n_feat_1m=n_feat_1m,
            n_feat_conf=n_feat_conf,
            xgb_probs_fp=_lstm_xgb_probs_fp(xgb_probs),
            next_epoch=EPOCHS + 1,
            model=model,
            best_state=best_state,
            best_loss=best_loss,
            best_epoch=result.best_epoch,
        )

    log.info("LSTM saved to %s — acc=%.1f%%", mp, result.val_accuracy * 100)
    return result


# ════════════════════════════════════════════════════════════════════════════════
# LOAD
# ════════════════════════════════════════════════════════════════════════════════

def load_lstm(
    model_path: Path = None,
    ticker: str = None,
    model_dir: Path = None,
    *,
    ml_horizon_slug: str = DEFAULT_ML_HORIZON_SLUG,
):
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    path = model_path or (lstm_model_path(ticker, model_dir, ml_horizon_slug=hz) if ticker else None)
    if not path or not path.exists():
        return None, "Model file not found"

    base_dir = model_dir if model_dir is not None else path.parent
    tkr = ticker
    if not tkr:
        name = path.name
        m = re.match(r"^lstm_(.+)_(1c|5c|15c|60c)\.pt$", name, re.I)
        if m:
            tkr = m.group(1)
            hz = normalize_ml_horizon_slug(m.group(2))
    if not tkr:
        return None, "LSTM load requires ticker or lstm_{TICKER}_{horizon}.pt path for contract validation"

    mtp = lstm_meta_path(tkr, base_dir, ml_horizon_slug=hz)
    if not mtp.exists():
        return None, f"LSTM meta missing ({mtp.name}); refusing load"
    try:
        meta = json.loads(mtp.read_text(encoding="utf-8"))
    except Exception as e:
        return None, f"LSTM meta unreadable: {e}"

    from model_contract import validate_artifact_contract

    ok, reason = validate_artifact_contract(meta, "lstm")
    if not ok:
        return None, f"Incompatible model contract: {reason}"

    try:
        import torch
        from lstm_data import assert_lstm_encoder_checkpoint_compatible

        checkpoint = torch.load(str(path), map_location="cpu", weights_only=False)
        try:
            assert_lstm_encoder_checkpoint_compatible(checkpoint)
        except ValueError as exc:
            return None, str(exc)
        model = build_model(
            checkpoint["n_features_5m"],
            checkpoint["n_features_1m"],
            checkpoint["n_confluence"],
        )
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        return model, checkpoint
    except Exception as e:
        return None, str(e)


if __name__ == "__main__":
    import argparse

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
    from db import DB_PATH as _DB_PATH_OBJ

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", type=str, default=None)
    ap.add_argument("--db", type=str, default=str(_DB_PATH_OBJ))
    ap.add_argument("--model-dir", type=str, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="lstm_model", write_capable=False)

    from lstm_data import build_lstm_dataset
    tickers = [ticker_storage_key(args.ticker)] if args.ticker else None  # RC-345/F25
    if not tickers:
        ds = build_lstm_dataset(db_path=args.db)
        tickers = sorted(set(ds.tickers)) if ds.tickers else []

    model_dir = Path(args.model_dir) if args.model_dir else None
    for tkr in tickers:
        result = train_lstm(db_path=args.db, ticker=tkr, model_dir=model_dir)
        print(result.summary())
