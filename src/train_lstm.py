"""Train an LSTM for one-step-ahead Appliances forecasting.

Input : data_windows.npz (X_train, y_train, X_test, y_test), scaler.pkl
Output: lstm_model.pt, metrics.json, lstm_pred.png, lstm_loss.png
"""

import json
import pickle
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------------
SEED = 42
HIDDEN_SIZE = 64
NUM_LAYERS = 2
DROPOUT = 0.1
LR = 1e-3
EPOCHS = 50
BATCH_SIZE = 32

# Paths resolved relative to the project root (parent of src/)
ROOT = Path(__file__).resolve().parents[1]
TARGET_IDX = 0          # Appliances is the first feature column (0-indexed)
IN_NPZ = ROOT / "artifacts" / "data_windows.npz"
IN_SCALER = ROOT / "artifacts" / "scaler.pkl"
OUT_DIR = ROOT / "results" / "lstm_v1_broken"
OUT_MODEL = OUT_DIR / "lstm_model.pt"
OUT_METRICS = OUT_DIR / "metrics.json"
OUT_PRED = OUT_DIR / "lstm_pred.png"
OUT_LOSS = OUT_DIR / "lstm_loss.png"
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
        out, _ = self.lstm(x)          # (B, L, H)
        last = out[:, -1, :]           # last time step
        return self.fc(last).squeeze(-1)


def inverse_target(scaled, scaler):
    """Inverse-normalize the target column back to original (Wh) scale."""
    mean = scaler.mean_[TARGET_IDX]
    scale = scaler.scale_[TARGET_IDX]
    return scaled * scale + mean


def metrics(y_true, y_pred):
    mse = float(np.mean((y_true - y_pred) ** 2))
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(mse))
    return {"MSE": mse, "MAE": mae, "RMSE": rmse}


def main():
    # ---- Load data --------------------------------------------------------
    data = np.load(IN_NPZ)
    X_train, y_train = data["X_train"], data["y_train"]
    X_test, y_test = data["X_test"], data["y_test"]
    with open(IN_SCALER, "rb") as f:
        scaler = pickle.load(f)

    input_size = X_train.shape[2]
    print(f"X_train {X_train.shape}  X_test {X_test.shape}  input_size={input_size}")

    train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)

    X_test_t = torch.from_numpy(X_test)
    y_test_t = torch.from_numpy(y_test)

    # ---- Model / optimizer ------------------------------------------------
    model = LSTMForecaster(input_size)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    # ---- Training ---------------------------------------------------------
    train_losses, test_losses = [], []
    for epoch in range(1, EPOCHS + 1):
        model.train()
        running = 0.0
        for xb, yb in train_loader:
            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            running += loss.item() * xb.size(0)
        train_loss = running / len(train_ds)

        model.eval()
        with torch.no_grad():
            test_loss = criterion(model(X_test_t), y_test_t).item()

        train_losses.append(train_loss)
        test_losses.append(test_loss)
        if epoch == 1 or epoch % 10 == 0:
            print(f"epoch {epoch:3d}/{EPOCHS}  train_loss={train_loss:.6f}  test_loss={test_loss:.6f}")

    torch.save(model.state_dict(), OUT_MODEL)

    # ---- Evaluation in original (Wh) scale --------------------------------
    model.eval()
    with torch.no_grad():
        pred_scaled = model(X_test_t).numpy()

    y_true = inverse_target(y_test, scaler)
    y_pred = inverse_target(pred_scaled, scaler)

    # Naive persistence: last step of the input window is the t+1 prediction
    last_scaled = X_test[:, -1, TARGET_IDX]
    y_naive = inverse_target(last_scaled, scaler)

    lstm_m = metrics(y_true, y_pred)
    naive_m = metrics(y_true, y_naive)

    print("=" * 60)
    print("Test metrics (original Wh scale)")
    print("-" * 60)
    print(f"{'metric':<8}{'LSTM':>14}{'naive':>14}")
    for k in ["MSE", "MAE", "RMSE"]:
        print(f"{k:<8}{lstm_m[k]:>14.3f}{naive_m[k]:>14.3f}")

    with open(OUT_METRICS, "w") as f:
        json.dump({"lstm": lstm_m, "naive": naive_m}, f, indent=2)
    print(f"Saved {OUT_METRICS}, {OUT_MODEL}")

    # ---- Plot: prediction vs truth ---------------------------------------
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(y_true, label="True", color="black", lw=1.5)
    ax.plot(y_pred, label="LSTM prediction", color="#1f77b4", lw=1.2)
    ax.set_title("LSTM one-step prediction vs truth (test set)")
    ax.set_xlabel("test window index")
    ax.set_ylabel("Appliances (Wh)")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_PRED, dpi=130)
    plt.close(fig)

    # ---- Plot: loss curves ------------------------------------------------
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(range(1, EPOCHS + 1), train_losses, label="train loss", color="#2ca02c")
    ax.plot(range(1, EPOCHS + 1), test_losses, label="test loss", color="crimson")
    ax.set_title("Training / test loss per epoch (MSE, scaled)")
    ax.set_xlabel("epoch")
    ax.set_ylabel("MSE loss (normalized)")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_LOSS, dpi=130)
    plt.close(fig)
    print(f"Saved {OUT_PRED}, {OUT_LOSS}")

    return lstm_m, naive_m


if __name__ == "__main__":
    main()
