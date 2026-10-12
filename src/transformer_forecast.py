"""Transformer encoder for the same one-step-ahead Appliances task.

Splits, scaling and early-stopping protocol are IDENTICAL to train_lstm_v2.py
so the two models can be compared fairly.

Input : A2_data_release.csv, metrics_v2.json (LSTM + naive results)
Output: metrics_transformer.json, transformer_pred.png, transformer_loss.png
"""

import json
import math
import time
from copy import deepcopy
from pathlib import Path

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
# Parameters (identical data protocol to train_lstm_v2.py)
# ----------------------------------------------------------------------------
# Paths resolved relative to the project root (parent of src/)
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "A2_data_release.csv"
TARGET_COL = "Appliances"
TARGET_IDX = 0
WINDOW_LEN = 24
TEST_RATIO = 0.8         # first 800 rows = train segment, last 200 = test
VAL_RATIO = 0.8          # within train: 640 sub-train, 160 validation

SEED = 42
D_MODEL = 64
NHEAD = 4
NUM_LAYERS = 2
DROPOUT = 0.1
LR = 1e-3
MAX_EPOCHS = 200
PATIENCE = 15
BATCH_SIZE = 32

IN_LSTM_METRICS = ROOT / "results" / "lstm_v2" / "metrics_v2.json"
OUT_DIR = ROOT / "results" / "transformer"
OUT_METRICS = OUT_DIR / "metrics_transformer.json"
OUT_PRED = OUT_DIR / "transformer_pred.png"
OUT_LOSS = OUT_DIR / "transformer_loss.png"
OUT_DIR.mkdir(parents=True, exist_ok=True)

np.random.seed(SEED)
torch.manual_seed(SEED)


class PositionalEncoding(nn.Module):
    """Fixed sinusoidal positional encoding (adds order information)."""

    def __init__(self, d_model, max_len=512):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))  # (1, max_len, d_model)

    def forward(self, x):
        return x + self.pe[:, :x.size(1)]


class TransformerForecaster(nn.Module):
    def __init__(self, input_size, d_model=D_MODEL, nhead=NHEAD,
                 num_layers=NUM_LAYERS, dropout=DROPOUT, max_len=WINDOW_LEN):
        super().__init__()
        self.input_proj = nn.Linear(input_size, d_model)
        self.pos_enc = PositionalEncoding(d_model, max_len)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dropout=dropout,
            dim_feedforward=4 * d_model, batch_first=True)
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.fc = nn.Linear(d_model, 1)

    def forward(self, x):
        h = self.input_proj(x)
        h = self.pos_enc(h)
        h = self.encoder(h)
        return self.fc(h[:, -1, :]).squeeze(-1)


def load_data(path):
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def make_windows(segment_scaled, target_idx, L):
    n = len(segment_scaled)
    X = np.empty((n - L, L, segment_scaled.shape[1]), dtype=np.float32)
    y = np.empty((n - L,), dtype=np.float32)
    for i in range(n - L):
        X[i] = segment_scaled[i:i + L]
        y[i] = segment_scaled[i + L, target_idx]
    return X, y


def inverse_target(scaled, mean, scale):
    return scaled * scale + mean


def metrics(y_true, y_pred):
    mse = float(np.mean((y_true - y_pred) ** 2))
    return {"MSE": mse,
            "MAE": float(np.mean(np.abs(y_true - y_pred))),
            "RMSE": float(np.sqrt(mse))}


def train_with_early_stopping(X_tr, y_tr, X_val, y_val):
    torch.manual_seed(SEED)
    model = TransformerForecaster(X_tr.shape[2])
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    loader = DataLoader(TensorDataset(torch.from_numpy(X_tr), torch.from_numpy(y_tr)),
                        batch_size=BATCH_SIZE, shuffle=True)
    X_val_t = torch.from_numpy(X_val)
    y_val_t = torch.from_numpy(y_val)

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
        train_loss = running / len(X_tr)

        model.eval()
        with torch.no_grad():
            val_loss = criterion(model(X_val_t), y_val_t).item()
        train_hist.append(train_loss)
        val_hist.append(val_loss)

        if val_loss < best_val - 1e-6:
            best_val, best_epoch = val_loss, epoch
            best_state = deepcopy(model.state_dict())
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= PATIENCE:
                print(f"  early stop at epoch {epoch} (best epoch {best_epoch})")
                break
    elapsed = time.perf_counter() - t0

    model.load_state_dict(best_state)
    n_params = sum(p.numel() for p in model.parameters())
    return model, best_epoch, best_val, train_hist, val_hist, elapsed, n_params


def main():
    df = load_data(DATA_PATH)
    n = len(df)
    feature_cols = [c for c in df.columns if c != "date"]

    # ---- Identical time-ordered splits -----------------------------------
    test_start = int(n * TEST_RATIO)
    train_seg = df.iloc[:test_start].reset_index(drop=True)
    test_seg = df.iloc[test_start:].reset_index(drop=True)
    val_start = int(len(train_seg) * VAL_RATIO)
    sub_train = train_seg.iloc[:val_start].reset_index(drop=True)
    sub_val = train_seg.iloc[val_start:].reset_index(drop=True)

    print("=" * 70)
    print("Splits (identical to train_lstm_v2.py)")
    print("-" * 70)
    print(f"SUB-TRAIN : {sub_train['date'].iloc[0]} -> {sub_train['date'].iloc[-1]} ({len(sub_train)} rows)")
    print(f"VAL       : {sub_val['date'].iloc[0]} -> {sub_val['date'].iloc[-1]} ({len(sub_val)} rows)")
    print(f"TEST      : {test_seg['date'].iloc[0]} -> {test_seg['date'].iloc[-1]} ({len(test_seg)} rows)")

    scaler = StandardScaler().fit(sub_train[feature_cols].values)
    tr_s = scaler.transform(sub_train[feature_cols].values)
    val_s = scaler.transform(sub_val[feature_cols].values)
    te_s = scaler.transform(test_seg[feature_cols].values)

    X_tr, y_tr = make_windows(tr_s, TARGET_IDX, WINDOW_LEN)
    X_val, y_val = make_windows(val_s, TARGET_IDX, WINDOW_LEN)
    X_te, y_te = make_windows(te_s, TARGET_IDX, WINDOW_LEN)
    print(f"windows: train={X_tr.shape} val={X_val.shape} test={X_te.shape}")

    mean, scale = scaler.mean_[TARGET_IDX], scaler.scale_[TARGET_IDX]
    y_true = inverse_target(y_te, mean, scale)
    y_naive = inverse_target(X_te[:, -1, TARGET_IDX], mean, scale)

    variants = {"A_all_features": list(range(X_tr.shape[2])),
                "B_univariate": [TARGET_IDX]}
    results, histories = {}, {}

    for name, cols in variants.items():
        print("-" * 70)
        print(f"Variant {name} (input_size={len(cols)})")
        Xtr, Xval, Xte = X_tr[:, :, cols], X_val[:, :, cols], X_te[:, :, cols]
        model, best_epoch, best_val, tr_h, val_h, elapsed, n_params = \
            train_with_early_stopping(Xtr, y_tr, Xval, y_val)
        with torch.no_grad():
            pred = model(torch.from_numpy(Xte)).numpy()
        y_pred = inverse_target(pred, mean, scale)
        m = metrics(y_true, y_pred)

        results[name] = {"best_epoch": best_epoch, "best_val_loss": best_val,
                         "n_params": n_params, "train_time_sec": round(elapsed, 2), **m}
        histories[name] = {"train": tr_h, "val": val_h, "best_epoch": best_epoch,
                           "y_pred": y_pred}
        print(f"  params={n_params}  time={elapsed:.2f}s")
        print(f"  best_epoch={best_epoch}  best_val_loss={best_val:.6f}")
        print(f"  test: MSE={m['MSE']:.3f} MAE={m['MAE']:.3f} RMSE={m['RMSE']:.3f}")

    best_name = min(results, key=lambda k: results[k]["best_val_loss"])
    print("=" * 70)
    print(f"Best Transformer config: {best_name}")

    # ---- Load LSTM + naive results for the comparison table ---------------
    with open(IN_LSTM_METRICS, "r") as f:
        lstm = json.load(f)
    lstm_uni = lstm["variants"]["B_univariate"]
    lstm_all = lstm["variants"]["A_all_features"]
    naive_m = lstm["naive"]

    print("-" * 70)
    print(f"{'model':<26}{'MSE':>13}{'MAE':>11}{'RMSE':>11}")
    rows = [
        ("Transformer (univar)", results["B_univariate"]),
        ("Transformer (all feat)", results["A_all_features"]),
        ("LSTM (univar)", lstm_uni),
        ("LSTM (all feat)", lstm_all),
        ("naive persistence", naive_m),
    ]
    for label, r in rows:
        print(f"{label:<26}{r['MSE']:>13.3f}{r['MAE']:>11.3f}{r['RMSE']:>11.3f}")

    out = {"best_config": best_name,
           "transformer": results,
           "lstm": {"A_all_features": lstm_all, "B_univariate": lstm_uni},
           "naive": naive_m}
    with open(OUT_METRICS, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved {OUT_METRICS}")

    # ---- Plots for best Transformer config -------------------------------
    h = histories[best_name]
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(y_true, label="True", color="black", lw=1.5)
    ax.plot(h["y_pred"], label=f"Transformer ({best_name})", color="#d62728", lw=1.2)
    ax.plot(y_naive, label="naive persistence", color="orange", lw=1.0, alpha=0.7)
    ax.set_title(f"Transformer one-step prediction vs truth (test, best={best_name})")
    ax.set_xlabel("test window index")
    ax.set_ylabel("Appliances (Wh)")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_PRED, dpi=130)
    plt.close(fig)

    ep = range(1, len(h["train"]) + 1)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(ep, h["train"], label="train loss", color="#2ca02c")
    ax.plot(ep, h["val"], label="val loss", color="crimson")
    ax.axvline(h["best_epoch"], color="black", ls="--", lw=1,
               label=f"best epoch={h['best_epoch']}")
    ax.set_title(f"Transformer train / val loss (best={best_name})")
    ax.set_xlabel("epoch")
    ax.set_ylabel("MSE loss (normalized)")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_LOSS, dpi=130)
    plt.close(fig)
    print(f"Saved {OUT_PRED}, {OUT_LOSS}")
    print("=" * 70)

    return results


if __name__ == "__main__":
    main()
