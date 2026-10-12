"""Data pipeline for one-step-ahead Appliances forecasting.

Builds supervised windows (input = past L timesteps of all features,
label = Appliances at t+1), with a strictly time-ordered train/test split
and leakage-free normalization. No model training here.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pickle
from sklearn.preprocessing import StandardScaler

# ----------------------------------------------------------------------------
# Paths (resolved relative to the project root, i.e. the parent of src/)
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]

# ----------------------------------------------------------------------------
# Parameters
# ----------------------------------------------------------------------------
DATA_PATH = ROOT / "data" / "A2_data_release.csv"
TARGET_COL = "Appliances"
WINDOW_LEN = 24          # L: number of past timesteps fed to the model
SPLIT_RATIO = 0.8        # first 80% of rows = train, last 20% = test
SEED = 42                # fixed random seed (reproducibility)

OUT_NPZ = ROOT / "artifacts" / "data_windows.npz"
OUT_SCALER = ROOT / "artifacts" / "scaler.pkl"

np.random.seed(SEED)


def load_data(path):
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def make_windows(segment_scaled, target_idx, L):
    """Return (X, y) sliding windows within a single segment.

    X[i] = segment_scaled[i : i+L]           (L x n_features)
    y[i] = segment_scaled[i+L, target_idx]   (next step t+1)
    Windows never leave the segment, so they cannot cross the split boundary.
    """
    n = len(segment_scaled)
    n_samples = n - L
    X = np.empty((n_samples, L, segment_scaled.shape[1]), dtype=np.float32)
    y = np.empty((n_samples,), dtype=np.float32)
    for i in range(n_samples):
        X[i] = segment_scaled[i:i + L]
        y[i] = segment_scaled[i + L, target_idx]
    return X, y


def report_norm(name, raw, scaled, cols, target_col):
    """Print mean/std before vs after normalization for selected columns."""
    check = [target_col] + [c for c in cols if c != target_col][:3]
    idx = [cols.index(c) for c in check]
    print(f"  [{name}]")
    for c, j in zip(check, idx):
        rm, rs = raw[:, j].mean(), raw[:, j].std()
        sm, ss = scaled[:, j].mean(), scaled[:, j].std()
        print(f"    {c:<12} raw mean={rm:9.3f} std={rs:9.3f}"
              f"  |  scaled mean={sm:8.3f} std={ss:8.3f}")


def main():
    df = load_data(DATA_PATH)
    n_rows = len(df)

    feature_cols = [c for c in df.columns if c != "date"]  # date excluded
    target_idx = feature_cols.index(TARGET_COL)

    # 1. Time-ordered split (no shuffle)
    split_idx = int(n_rows * SPLIT_RATIO)
    train_df = df.iloc[:split_idx].reset_index(drop=True)
    test_df = df.iloc[split_idx:].reset_index(drop=True)

    print("=" * 70)
    print("Time ranges")
    print("-" * 70)
    print(f"TRAIN : {train_df['date'].iloc[0]}  ->  {train_df['date'].iloc[-1]}"
          f"  ({len(train_df)} rows)")
    print(f"TEST  : {test_df['date'].iloc[0]}  ->  {test_df['date'].iloc[-1]}"
          f"  ({len(test_df)} rows)")

    # 2. Fit scaler on TRAIN only, then transform both segments
    scaler = StandardScaler()
    scaler.fit(train_df[feature_cols].values)
    train_scaled = scaler.transform(train_df[feature_cols].values)
    test_scaled = scaler.transform(test_df[feature_cols].values)

    # 3./4. Build windows per segment (no boundary crossing, label = t+1)
    X_train, y_train = make_windows(train_scaled, target_idx, WINDOW_LEN)
    X_test, y_test = make_windows(test_scaled, target_idx, WINDOW_LEN)

    print("-" * 70)
    print("Sample counts")
    print("-" * 70)
    print(f"TRAIN raw rows={len(train_df)}  -> windowed samples={len(X_train)}")
    print(f"TEST  raw rows={len(test_df)}  -> windowed samples={len(X_test)}")
    print("-" * 70)
    print(f"X_train {X_train.shape}  y_train {y_train.shape}")
    print(f"X_test  {X_test.shape}   y_test  {y_test.shape}")

    # 5. Mean / std before and after normalization
    print("-" * 70)
    print("Normalization check (mean | std) -- target + first 3 features")
    print("-" * 70)
    report_norm("TRAIN", train_df[feature_cols].values, train_scaled,
                feature_cols, TARGET_COL)
    report_norm("TEST", test_df[feature_cols].values, test_scaled,
                feature_cols, TARGET_COL)

    # Save artifacts
    np.savez(OUT_NPZ, X_train=X_train, y_train=y_train,
             X_test=X_test, y_test=y_test)
    with open(OUT_SCALER, "wb") as f:
        pickle.dump(scaler, f)
    print("-" * 70)
    print(f"Saved {OUT_NPZ} and {OUT_SCALER}")
    print("=" * 70)

    return scaler, (X_train, y_train, X_test, y_test)


if __name__ == "__main__":
    main()

# ----------------------------------------------------------------------------
# Train/test boundary
#   split_idx = int(1000 * 0.8) = 800
#   TRAIN = rows 0..799    : 2016-01-11 17:00:00 -> 2016-01-17 06:10:00
#   TEST  = rows 800..999  : 2016-01-17 06:20:00 -> 2016-01-18 15:30:00
#   Data after row 799 is NEVER used to fit the scaler or build train windows;
#   test windows start only at row 800 within the test segment.
# ----------------------------------------------------------------------------
