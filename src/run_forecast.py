"""Generalizable one-step-ahead forecasting pipeline.

Runs on ANY time range of the dataset (or any similar CSV) without code changes.
Strict time-series protocol: time-ordered splits, no shuffling, scaler fit on
the training portion only, and windows that never cross split boundaries.

Paths are resolved relative to the project root (parent of src/), so the script
can be run from anywhere. Outputs go to results/<outdir>/.

Usage:
  python src/run_forecast.py --csv data/A2_data_release.csv --model lstm --tag lstm
  python src/run_forecast.py --csv data/A2_periodB.csv --model transformer \
      --start 2016-01-18 --end 2016-01-29 --tag periodB_trans
"""

from pathlib import Path
import argparse
import json
import math
import time
from copy import deepcopy

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------------
# Paths / fixed training protocol (shared by both models)
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]

SEED = 42
LR = 1e-3
MAX_EPOCHS = 200
PATIENCE = 15
BATCH_SIZE = 32
VAL_RATIO = 0.2          # last 20% of the train segment is validation
HIDDEN_SIZE = 64
NUM_LAYERS = 2
DROPOUT = 0.1
D_MODEL = 64
NHEAD = 4


# ============================================================================
# Data handling
# ============================================================================
def resolve_path(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


def load_and_clean(csv_path, start, end):
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]
    if "date" not in df.columns:
        raise ValueError("CSV must contain a 'date' column")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if start is not None or end is not None:
        mask = pd.Series(True, index=df.index)
        if start is not None:
            mask &= df["date"] >= pd.to_datetime(start)
        if end is not None:
            mask &= df["date"] <= pd.to_datetime(end)
        df = df[mask].reset_index(drop=True)
        print(f"[filter] date range -> {len(df)} rows")

    diffs = df["date"].diff().dropna()
    if len(diffs):
        print(f"[info] inferred sampling interval: {diffs.mode().iloc[0]}")

    # missing values: ffill first, then linear interpolation
    n_before = int(df.isna().sum().sum())
    df = df.ffill()
    df = df.interpolate(method="linear", limit_direction="both")
    n_fixed = n_before - int(df.isna().sum().sum())
    print(f"[clean] missing cells fixed (ffill+interp): {n_fixed}")

    df = df.dropna().reset_index(drop=True)
    print(f"[clean] rows remaining after dropping NaN: {len(df)}")
    return df


def make_windows(segment_scaled, target_idx, L):
    n = len(segment_scaled)
    X = np.empty((n - L, L, segment_scaled.shape[1]), dtype=np.float32)
    y = np.empty((n - L,), dtype=np.float32)
    for i in range(n - L):
        X[i] = segment_scaled[i:i + L]
        y[i] = segment_scaled[i + L, target_idx]
    return X, y


def inverse_target(scaled, mean, scale):
    return np.asarray(scaled) * scale + mean


def compute_metrics(y_true, y_pred):
    mse = float(np.mean((y_true - y_pred) ** 2))
    return {"MSE": mse,
            "MAE": float(np.mean(np.abs(y_true - y_pred))),
            "RMSE": float(np.sqrt(mse))}


# ============================================================================
# Models
# ============================================================================
class LSTMForecaster(nn.Module):
    def __init__(self, input_size):
        super().__init__()
        self.lstm = nn.LSTM(input_size, HIDDEN_SIZE, NUM_LAYERS,
                            batch_first=True, dropout=DROPOUT)
        self.fc = nn.Linear(HIDDEN_SIZE, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :]).squeeze(-1)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=512):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x):
        return x + self.pe[:, :x.size(1)]


class TransformerForecaster(nn.Module):
    def __init__(self, input_size, max_len):
        super().__init__()
        self.input_proj = nn.Linear(input_size, D_MODEL)
        self.pos_enc = PositionalEncoding(D_MODEL, max(max_len, 2))
        layer = nn.TransformerEncoderLayer(
            d_model=D_MODEL, nhead=NHEAD, dropout=DROPOUT,
            dim_feedforward=4 * D_MODEL, batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, num_layers=NUM_LAYERS)
        self.fc = nn.Linear(D_MODEL, 1)

    def forward(self, x):
        h = self.pos_enc(self.input_proj(x))
        h = self.encoder(h)
        return self.fc(h[:, -1, :]).squeeze(-1)


def build_model(name, input_size, window):
    torch.manual_seed(SEED)
    if name == "lstm":
        return LSTMForecaster(input_size)
    return TransformerForecaster(input_size, window)


# ============================================================================
# Training
# ============================================================================
def train_with_early_stopping(model, X_tr, y_tr, X_val, y_val):
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    loader = DataLoader(TensorDataset(torch.from_numpy(X_tr), torch.from_numpy(y_tr)),
                        batch_size=BATCH_SIZE, shuffle=True)
    X_val_t, y_val_t = torch.from_numpy(X_val), torch.from_numpy(y_val)

    best_val, best_epoch = float("inf"), -1
    best_state = deepcopy(model.state_dict())
    train_hist, val_hist = [], []
    no_improve = 0

    t0 = time.perf_counter()
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        running = 0.0
        for xb, yb in loader:
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimizer.step()
            running += loss.item() * xb.size(0)
        train_hist.append(running / len(X_tr))

        model.eval()
        with torch.no_grad():
            val_loss = criterion(model(X_val_t), y_val_t).item()
        val_hist.append(val_loss)

        if val_loss < best_val - 1e-6:
            best_val, best_epoch = val_loss, epoch
            best_state = deepcopy(model.state_dict())
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= PATIENCE:
                break
    elapsed = time.perf_counter() - t0

    model.load_state_dict(best_state)
    return model, best_epoch, best_val, train_hist, val_hist, elapsed


# ============================================================================
# Main
# ============================================================================
def parse_args():
    p = argparse.ArgumentParser(description="Generalizable forecasting pipeline")
    p.add_argument("--csv", default="data/A2_data_release.csv",
                   help="path to CSV data (relative to project root)")
    p.add_argument("--target", default="Appliances", help="target column")
    p.add_argument("--window", type=int, default=24, help="look-back steps")
    p.add_argument("--test-ratio", type=float, default=0.2, help="test fraction")
    p.add_argument("--model", choices=["lstm", "transformer"], default="lstm")
    p.add_argument("--start", default=None, help="filter start date (inclusive)")
    p.add_argument("--end", default=None, help="filter end date (inclusive)")
    p.add_argument("--tag", default=None, help="output file tag")
    p.add_argument("--outdir", default="results/forecast",
                   help="output directory (relative to project root)")
    return p.parse_args()


def main():
    args = parse_args()
    tag = args.tag or args.model
    csv_path = resolve_path(args.csv)
    outdir = resolve_path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = load_and_clean(csv_path, args.start, args.end)
    n = len(df)
    if args.target not in df.columns:
        raise ValueError(f"target '{args.target}' not in columns: {list(df.columns)}")

    feature_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                    if c != "date"]
    target_idx = feature_cols.index(args.target)
    print(f"[data] {csv_path.name} shape={df.shape}  features={len(feature_cols)}  target='{args.target}'")

    # ---- time-ordered splits ---------------------------------------------
    test_start = int(n * (1.0 - args.test_ratio))
    train_seg = df.iloc[:test_start].reset_index(drop=True)
    test_seg = df.iloc[test_start:].reset_index(drop=True)
    val_start = int(len(train_seg) * (1.0 - VAL_RATIO))
    sub_train = train_seg.iloc[:val_start].reset_index(drop=True)
    sub_val = train_seg.iloc[val_start:].reset_index(drop=True)

    print("=" * 70)
    print("Splits (time ordered, no shuffle)")
    print("-" * 70)
    for nm, seg in [("SUB-TRAIN", sub_train), ("VAL", sub_val), ("TEST", test_seg)]:
        print(f"{nm:<10}: {seg['date'].iloc[0]} -> {seg['date'].iloc[-1]} ({len(seg)} rows)")

    # ---- scaler fit on SUB-TRAIN only ------------------------------------
    scaler = StandardScaler().fit(sub_train[feature_cols].values)
    tr_s = scaler.transform(sub_train[feature_cols].values)
    val_s = scaler.transform(sub_val[feature_cols].values)
    te_s = scaler.transform(test_seg[feature_cols].values)

    X_tr, y_tr = make_windows(tr_s, target_idx, args.window)
    X_val, y_val = make_windows(val_s, target_idx, args.window)
    X_te, y_te = make_windows(te_s, target_idx, args.window)
    print(f"[windows] train={X_tr.shape} val={X_val.shape} test={X_te.shape}")

    mean, scale = scaler.mean_[target_idx], scaler.scale_[target_idx]
    y_true = inverse_target(y_te, mean, scale)
    y_naive = inverse_target(X_te[:, -1, target_idx], mean, scale)
    naive_m = compute_metrics(y_true, y_naive)

    # ---- train ------------------------------------------------------------
    model = build_model(args.model, X_tr.shape[2], args.window)
    n_params = sum(p.numel() for p in model.parameters())
    print("-" * 70)
    print(f"[model] {args.model}  params={n_params}")
    model, best_epoch, best_val, tr_h, val_h, elapsed = \
        train_with_early_stopping(model, X_tr, y_tr, X_val, y_val)
    print(f"[train] best_epoch={best_epoch}  best_val_loss={best_val:.6f}  time={elapsed:.2f}s")

    # ---- evaluate in original scale --------------------------------------
    model.eval()
    with torch.no_grad():
        pred = model(torch.from_numpy(X_te)).numpy()
    y_pred = inverse_target(pred, mean, scale)
    m = compute_metrics(y_true, y_pred)

    print("-" * 70)
    print(f"{'model':<20}{'MSE':>13}{'MAE':>11}{'RMSE':>11}")
    print(f"{args.model:<20}{m['MSE']:>13.3f}{m['MAE']:>11.3f}{m['RMSE']:>11.3f}")
    print(f"{'naive persistence':<20}{naive_m['MSE']:>13.3f}{naive_m['MAE']:>11.3f}{naive_m['RMSE']:>11.3f}")

    # ---- save artifacts ---------------------------------------------------
    metrics = {"tag": tag, "model": args.model, "target": args.target,
               "csv": csv_path.name, "window": args.window,
               "test_ratio": args.test_ratio, "n_params": n_params,
               "best_epoch": best_epoch, "best_val_loss": best_val,
               "train_time_sec": round(elapsed, 2),
               "split": {
                   "sub_train": [str(sub_train['date'].iloc[0]), str(sub_train['date'].iloc[-1]), len(sub_train)],
                   "val": [str(sub_val['date'].iloc[0]), str(sub_val['date'].iloc[-1]), len(sub_val)],
                   "test": [str(test_seg['date'].iloc[0]), str(test_seg['date'].iloc[-1]), len(test_seg)]},
               "metrics": m, "naive": naive_m}
    with open(outdir / f"metrics_{tag}.json", "w") as f:
        json.dump(metrics, f, indent=2)

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(y_true, label="True", color="black", lw=1.5)
    ax.plot(y_pred, label=args.model, color="#1f77b4", lw=1.2)
    ax.plot(y_naive, label="naive persistence", color="orange", lw=1.0, alpha=0.7)
    ax.set_title(f"{args.model} one-step prediction vs truth (test)")
    ax.set_xlabel("test window index")
    ax.set_ylabel(f"{args.target} (original scale)")
    ax.legend(); ax.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(outdir / f"pred_{tag}.png", dpi=130); plt.close(fig)

    ep = range(1, len(tr_h) + 1)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(ep, tr_h, label="train loss", color="#2ca02c")
    ax.plot(ep, val_h, label="val loss", color="crimson")
    ax.axvline(best_epoch, color="black", ls="--", lw=1, label=f"best epoch={best_epoch}")
    ax.set_title(f"{args.model} train / val loss")
    ax.set_xlabel("epoch"); ax.set_ylabel("MSE loss (normalized)")
    ax.legend(); ax.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(outdir / f"loss_{tag}.png", dpi=130); plt.close(fig)

    print(f"[saved] {outdir}/metrics_{tag}.json, pred_{tag}.png, loss_{tag}.png")
    print("=" * 70)


if __name__ == "__main__":
    main()
