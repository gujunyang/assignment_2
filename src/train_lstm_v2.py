"""Improved LSTM training with a proper time-ordered validation split,
early stopping, and a comparison of two input variants:
  A. all 28 features
  B. univariate (Appliances history only)

Input : A2_data_release.csv, scaler is re-fit on the training portion only
Output: metrics_v2.json, lstm_pred_v2.png, lstm_loss_v2.png
"""

import json
import pickle
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
# Parameters
# ----------------------------------------------------------------------------
# Paths resolved relative to the project root (parent of src/)
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "A2_data_release.csv"
TARGET_COL = "Appliances"
TARGET_IDX = 0
WINDOW_LEN = 24
TEST_RATIO = 0.8          # global split: first 80% train segment, last 20% test
VAL_RATIO = 0.8           # within train: first 80% sub-train, last 20% val

SEED = 42
HIDDEN_SIZE = 64
NUM_LAYERS = 2
DROPOUT = 0.1
LR = 1e-3
MAX_EPOCHS = 200
PATIENCE = 15
BATCH_SIZE = 32

OUT_DIR = ROOT / "results" / "lstm_v2"
OUT_METRICS = OUT_DIR / "metrics_v2.json"
OUT_PRED = OUT_DIR / "lstm_pred_v2.png"
OUT_LOSS = OUT_DIR / "lstm_loss_v2.png"
OUT_DIR.mkdir(parents=True, exist_ok=True)

np.random.seed(SEED)
torch.manual_seed(SEED)


class LSTMForecaster(nn.Module):
    def __init__(self, input_size, hidden_size=HIDDEN_SIZE,
                 num_layers=NUM_LAYERS, dropout=DROPOUT):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                            batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :]).squeeze(-1)


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
    model = LSTMForecaster(X_tr.shape[2])
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    loader = DataLoader(TensorDataset(torch.from_numpy(X_tr), torch.from_numpy(y_tr)),
                        batch_size=BATCH_SIZE, shuffle=True)
    X_val_t = torch.from_numpy(X_val)
    y_val_t = torch.from_numpy(y_val)

    best_val = float("inf")
    best_epoch = -1
    best_state = deepcopy(model.state_dict())
    train_hist, val_hist = [], []
    epochs_no_improve = 0

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
            best_val = val_loss
            best_epoch = epoch
            best_state = deepcopy(model.state_dict())
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= PATIENCE:
                print(f"  early stop at epoch {epoch} (best epoch {best_epoch})")
                break

    model.load_state_dict(best_state)   # roll back to best weights
    return model, best_epoch, best_val, train_hist, val_hist


def main():
    df = load_data(DATA_PATH)
    n = len(df)
    feature_cols = [c for c in df.columns if c != "date"]

    # ---- Time-ordered splits (no shuffle) --------------------------------
    test_start = int(n * TEST_RATIO)                 # 800
    train_seg = df.iloc[:test_start].reset_index(drop=True)
    test_seg = df.iloc[test_start:].reset_index(drop=True)

    val_start = int(len(train_seg) * VAL_RATIO)      # 640
    sub_train = train_seg.iloc[:val_start].reset_index(drop=True)
    sub_val = train_seg.iloc[val_start:].reset_index(drop=True)

    print("=" * 70)
    print("Splits (time ordered, test never used for training/selection)")
    print("-" * 70)
    print(f"SUB-TRAIN : {sub_train['date'].iloc[0]} -> {sub_train['date'].iloc[-1]} ({len(sub_train)} rows)")
    print(f"VAL       : {sub_val['date'].iloc[0]} -> {sub_val['date'].iloc[-1]} ({len(sub_val)} rows)")
    print(f"TEST      : {test_seg['date'].iloc[0]} -> {test_seg['date'].iloc[-1]} ({len(test_seg)} rows)")

    # ---- Scaler fit on SUB-TRAIN only ------------------------------------
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

    # ---- Naive persistence baseline --------------------------------------
    y_naive = inverse_target(X_te[:, -1, TARGET_IDX], mean, scale)
    naive_m = metrics(y_true, y_naive)

    variants = {"A_all_features": list(range(X_tr.shape[2])),
                "B_univariate": [TARGET_IDX]}
    results, histories = {}, {}

    for name, cols in variants.items():
        print("-" * 70)
        print(f"Variant {name}  (input_size={len(cols)})")
        Xtr, Xval, Xte = X_tr[:, :, cols], X_val[:, :, cols], X_te[:, :, cols]
        model, best_epoch, best_val, tr_h, val_h = train_with_early_stopping(
            Xtr, y_tr, Xval, y_val)

        with torch.no_grad():
            pred = model(torch.from_numpy(Xte)).numpy()
        y_pred = inverse_target(pred, mean, scale)
        m = metrics(y_true, y_pred)

        results[name] = {"best_epoch": best_epoch, "best_val_loss": best_val, **m}
        histories[name] = {"train": tr_h, "val": val_h, "best_epoch": best_epoch,
                           "y_pred": y_pred}
        print(f"  best_epoch={best_epoch}  best_val_loss={best_val:.6f}")
        print(f"  test: MSE={m['MSE']:.3f} MAE={m['MAE']:.3f} RMSE={m['RMSE']:.3f}")

    # ---- Best configuration (lowest val loss) ----------------------------
    best_name = min(results, key=lambda k: results[k]["best_val_loss"])
    print("=" * 70)
    print(f"Best configuration: {best_name}")
    print("-" * 70)
    print(f"{'metric':<8}{'A':>14}{'B':>14}{'naive':>14}")
    for k in ["MSE", "MAE", "RMSE"]:
        print(f"{k:<8}{results['A_all_features'][k]:>14.3f}"
              f"{results['B_univariate'][k]:>14.3f}{naive_m[k]:>14.3f}")

    out = {"best_config": best_name,
           "variants": results,
           "naive": naive_m}
    with open(OUT_METRICS, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Saved {OUT_METRICS}")

    # ---- Plots for the best configuration --------------------------------
    h = histories[best_name]
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(y_true, label="True", color="black", lw=1.5)
    ax.plot(h["y_pred"], label=f"LSTM ({best_name})", color="#1f77b4", lw=1.2)
    ax.plot(y_naive, label="naive persistence", color="orange", lw=1.0, alpha=0.7)
    ax.set_title(f"LSTM one-step prediction vs truth (test, best={best_name})")
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
    ax.set_title(f"Train / val loss (best={best_name})")
    ax.set_xlabel("epoch")
    ax.set_ylabel("MSE loss (normalized)")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_LOSS, dpi=130)
    plt.close(fig)
    print(f"Saved {OUT_PRED}, {OUT_LOSS}")
    print("=" * 70)

    return results, naive_m


if __name__ == "__main__":
    main()
