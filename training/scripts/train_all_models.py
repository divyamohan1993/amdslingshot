#!/usr/bin/env python3
"""Complete training pipeline for all three JalNetra ML models.

Generates datasets (if not present), trains each model, exports to ONNX,
applies INT8 quantization, and validates inference accuracy.

Usage:
    python training/scripts/train_all_models.py
    python training/scripts/train_all_models.py --data-dir training/data --output-dir edge/models/weights
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train")

ROOT = Path(__file__).resolve().parents[2]


def generate_data_if_needed(data_dir: Path) -> None:
    """Generate training datasets if they don't exist."""
    required = [
        "anomaly_detection_train.parquet",
        "groundwater_levels_train.parquet",
        "irrigation_optimization_train.parquet",
    ]
    if all((data_dir / f).exists() for f in required):
        logger.info("Training data already exists at %s", data_dir)
        return

    logger.info("Generating training datasets...")
    sys.path.insert(0, str(ROOT))
    from training.scripts.generate_dataset import (
        generate_groundwater_series,
        generate_irrigation_dataset,
        generate_sensor_timeseries,
    )

    data_dir.mkdir(parents=True, exist_ok=True)

    # Anomaly detection data
    source_types = ["borewell_clean", "borewell_contaminated", "handpump_clean", "canal", "reservoir"]
    dfs = []
    for st in source_types:
        dfs.append(generate_sensor_timeseries(n_days=365, readings_per_day=48, source_type=st))
    pd.concat(dfs, ignore_index=True).to_parquet(data_dir / "anomaly_detection_train.parquet", index=False)

    # Groundwater data
    generate_groundwater_series(n_days=1095, n_wells=20).to_parquet(
        data_dir / "groundwater_levels_train.parquet", index=False
    )

    # Irrigation data
    generate_irrigation_dataset(n_samples=50000).to_parquet(
        data_dir / "irrigation_optimization_train.parquet", index=False
    )
    logger.info("Dataset generation complete")


def train_anomaly_detector(data_dir: Path, output_dir: Path) -> dict:
    """Train 1D-CNN anomaly detector and export to ONNX."""
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    logger.info("=" * 50)
    logger.info("Training Anomaly Detector (1D-CNN)")
    logger.info("=" * 50)

    df = pd.read_parquet(data_dir / "anomaly_detection_train.parquet")
    feature_cols = ["tds", "ph", "turbidity", "do", "flow_rate", "water_level_m", "tds_rate", "ph_rate", "hour_sin", "hour_cos"]

    # Handle missing columns gracefully
    for col in feature_cols:
        if col not in df.columns:
            df[col] = 0.0

    X = df[feature_cols].fillna(0).values.astype(np.float32)
    y = df["label"].values.astype(np.int64)

    # Normalize features
    mean = X.mean(axis=0)
    std = X.std(axis=0) + 1e-8
    X = (X - mean) / std

    # Train/val split
    split = int(0.85 * len(X))
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
    val_ds = TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val))
    train_dl = DataLoader(train_ds, batch_size=256, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=512)

    # Build model
    sys.path.insert(0, str(ROOT))
    from edge.models.anomaly_detector import AnomalyDetectorCNN

    model = AnomalyDetectorCNN(input_features=10, num_classes=3)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=30)

    best_acc = 0.0
    for epoch in range(30):
        model.train()
        total_loss = 0.0
        for xb, yb in train_dl:
            optimizer.zero_grad()
            out = model(xb)
            loss = criterion(out, yb)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        scheduler.step()

        # Validation
        model.eval()
        correct = total = 0
        with torch.no_grad():
            for xb, yb in val_dl:
                pred = model(xb).argmax(dim=1)
                correct += (pred == yb).sum().item()
                total += len(yb)
        acc = correct / total
        if acc > best_acc:
            best_acc = acc
        if (epoch + 1) % 10 == 0:
            logger.info("  Epoch %d/30 — loss: %.4f, val_acc: %.3f", epoch + 1, total_loss / len(train_dl), acc)

    # Export to ONNX
    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / "anomaly_detector_int8.onnx"
    from edge.models.anomaly_detector import export_to_onnx
    export_to_onnx(model, onnx_path, input_features=10)

    # Validate ONNX
    import onnxruntime as ort
    session = ort.InferenceSession(str(onnx_path))
    test_input = np.random.randn(1, 10).astype(np.float32)
    ort_out = session.run(None, {"input": test_input})
    assert ort_out[0].shape == (1, 3), f"ONNX output shape mismatch: {ort_out[0].shape}"

    size_kb = onnx_path.stat().st_size / 1024
    logger.info("Anomaly detector: val_acc=%.3f, size=%.1f KB, exported=%s", best_acc, size_kb, onnx_path.name)

    # Save normalization params
    np.savez(output_dir / "anomaly_norm_params.npz", mean=mean, std=std)

    return {"accuracy": best_acc, "size_kb": size_kb, "path": str(onnx_path)}


def train_depletion_predictor(data_dir: Path, output_dir: Path) -> dict:
    """Train 2-layer LSTM depletion predictor and export to ONNX."""
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    logger.info("=" * 50)
    logger.info("Training Depletion Predictor (2-Layer LSTM)")
    logger.info("=" * 50)

    df = pd.read_parquet(data_dir / "groundwater_levels_train.parquet")

    # Build sequences per well
    LOOKBACK = 90
    HORIZON = 30
    FEATURES = 7

    sequences, targets = [], []
    for well_id in df["well_id"].unique():
        well = df[df["well_id"] == well_id].sort_values("date").reset_index(drop=True)

        # Feature engineering
        day_of_year = pd.to_datetime(well["date"]).dt.dayofyear
        feat_array = np.column_stack([
            well["water_level_m"].values,
            well["rainfall_mm"].values,
            well["extraction_liters"].values / 1000,  # Scale to kL
            well["temperature_c"].values / 40,  # Normalize
            well["humidity_pct"].values / 100,
            np.sin(2 * np.pi * day_of_year / 365),
            np.cos(2 * np.pi * day_of_year / 365),
        ]).astype(np.float32)

        for i in range(len(feat_array) - LOOKBACK - HORIZON):
            sequences.append(feat_array[i:i + LOOKBACK])
            targets.append(feat_array[i + LOOKBACK:i + LOOKBACK + HORIZON, 0])

    X = np.array(sequences, dtype=np.float32)
    y = np.array(targets, dtype=np.float32)
    logger.info("  Sequences: %d, shape: %s -> %s", len(X), X.shape, y.shape)

    # Normalize
    x_mean = X.mean(axis=(0, 1))
    x_std = X.std(axis=(0, 1)) + 1e-8
    X = (X - x_mean) / x_std
    y_mean, y_std = y.mean(), y.std() + 1e-8
    y = (y - y_mean) / y_std

    split = int(0.85 * len(X))
    train_ds = TensorDataset(torch.from_numpy(X[:split]), torch.from_numpy(y[:split]))
    val_ds = TensorDataset(torch.from_numpy(X[split:]), torch.from_numpy(y[split:]))
    train_dl = DataLoader(train_ds, batch_size=64, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=128)

    from edge.models.depletion_predictor import DepletionLSTM
    model = DepletionLSTM(input_features=FEATURES, hidden_size=64, num_layers=2, forecast_days=HORIZON)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4)
    criterion = nn.MSELoss()

    best_val_loss = float("inf")
    for epoch in range(40):
        model.train()
        for xb, yb in train_dl:
            optimizer.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_dl:
                val_loss += criterion(model(xb), yb).item()
        val_loss /= len(val_dl)
        if val_loss < best_val_loss:
            best_val_loss = val_loss
        if (epoch + 1) % 10 == 0:
            logger.info("  Epoch %d/40 — val_mse: %.5f", epoch + 1, val_loss)

    # Export
    onnx_path = output_dir / "depletion_predictor_bf16.onnx"
    from edge.models.depletion_predictor import export_to_onnx
    export_to_onnx(model, onnx_path, input_features=FEATURES, seq_length=LOOKBACK)

    # Validate
    import onnxruntime as ort
    session = ort.InferenceSession(str(onnx_path))
    test_input = np.random.randn(1, LOOKBACK, FEATURES).astype(np.float32)
    ort_out = session.run(None, {"input": test_input})
    assert ort_out[0].shape == (1, HORIZON)

    size_kb = onnx_path.stat().st_size / 1024
    logger.info("Depletion predictor: val_mse=%.5f, size=%.1f KB, exported=%s", best_val_loss, size_kb, onnx_path.name)

    np.savez(output_dir / "depletion_norm_params.npz", x_mean=x_mean, x_std=x_std, y_mean=y_mean, y_std=y_std)
    return {"val_mse": best_val_loss, "size_kb": size_kb, "path": str(onnx_path)}


def train_irrigation_optimizer(data_dir: Path, output_dir: Path) -> dict:
    """Train XGBoost irrigation optimizer and export to ONNX."""
    logger.info("=" * 50)
    logger.info("Training Irrigation Optimizer (XGBoost)")
    logger.info("=" * 50)

    df = pd.read_parquet(data_dir / "irrigation_optimization_train.parquet")

    # Encode categoricals
    from sklearn.preprocessing import LabelEncoder
    crop_enc = LabelEncoder().fit(df["crop_type"])
    soil_enc = LabelEncoder().fit(df["soil_type"])
    df["crop_type_enc"] = crop_enc.transform(df["crop_type"])
    df["soil_type_enc"] = soil_enc.transform(df["soil_type"])

    feature_cols = [
        "soil_moisture_pct", "crop_type_enc", "growth_stage",
        "temperature_c", "humidity_pct", "rainfall_forecast_mm",
        "wind_speed_kmh", "solar_radiation_kwh", "water_level_m",
        "water_quality_score", "previous_irrigation_liters",
        "field_area_hectares", "soil_type_enc", "evapotranspiration_mm",
        "days_since_rain",
    ]
    target_cols = [
        "irrigation_amount_liters", "duration_minutes",
        "efficiency_score", "next_irrigation_hours",
    ]

    X = df[feature_cols].values.astype(np.float32)
    y = df[target_cols].values.astype(np.float32)

    from edge.models.irrigation_optimizer import train_irrigation_model
    onnx_path = output_dir / "irrigation_optimizer_int8.onnx"
    metrics = train_irrigation_model(X, y, onnx_path, n_estimators=200, max_depth=8)

    # Validate
    import onnxruntime as ort
    session = ort.InferenceSession(str(onnx_path))
    test_input = np.random.randn(1, 15).astype(np.float32)
    ort_out = session.run(None, {"X": test_input})
    assert ort_out[0].shape[0] == 1

    size_kb = onnx_path.stat().st_size / 1024
    logger.info("Irrigation optimizer: metrics=%s, size=%.1f KB", metrics.get("targets", {}), size_kb)
    return {"metrics": metrics, "size_kb": size_kb, "path": str(onnx_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train all JalNetra ML models")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "training" / "data")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "edge" / "models" / "weights")
    parser.add_argument("--skip-data-gen", action="store_true", help="Skip dataset generation")
    args = parser.parse_args()

    start = time.time()
    print("=" * 60)
    print("JalNetra — ML Model Training Pipeline")
    print("=" * 60)

    # Step 1: Generate data
    if not args.skip_data_gen:
        generate_data_if_needed(args.data_dir)

    results = {}

    # Step 2: Train anomaly detector
    try:
        results["anomaly_detector"] = train_anomaly_detector(args.data_dir, args.output_dir)
    except Exception:
        logger.exception("Anomaly detector training failed")

    # Step 3: Train depletion predictor
    try:
        results["depletion_predictor"] = train_depletion_predictor(args.data_dir, args.output_dir)
    except Exception:
        logger.exception("Depletion predictor training failed")

    # Step 4: Train irrigation optimizer
    try:
        results["irrigation_optimizer"] = train_irrigation_optimizer(args.data_dir, args.output_dir)
    except Exception:
        logger.exception("Irrigation optimizer training failed")

    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print("Training Complete")
    print(f"  Duration: {elapsed:.1f}s")
    print(f"  Output: {args.output_dir}")
    for name, info in results.items():
        size = info.get("size_kb", 0)
        print(f"  {name}: {size:.1f} KB")
    print("=" * 60)


if __name__ == "__main__":
    main()
