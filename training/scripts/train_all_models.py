#!/usr/bin/env python3
"""
JalNetra — Complete ML Model Training Pipeline
================================================

Generates datasets (if not present), trains all three JalNetra ML models,
exports to ONNX format, validates inference, and saves weights.

Models trained:
    1. Anomaly Detector   (1D-CNN)  -- water quality classification
    2. Depletion Predictor (LSTM)   -- 30-day groundwater level forecast
    3. Irrigation Optimizer (XGBoost) -- crop-specific water scheduling

Usage:
    python training/scripts/train_all_models.py
    python training/scripts/train_all_models.py --data-dir training/data --output-dir edge/models/weights
    python training/scripts/train_all_models.py --skip-data-gen --models anomaly depletion

Author: JalNetra / dmj.one
License: MIT
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_all")

# Project root: two levels up from training/scripts/
ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Data Generation
# ---------------------------------------------------------------------------

def generate_data_if_needed(data_dir: Path) -> None:
    """Generate training datasets using the data_generator module if missing.

    Checks for the existence of numpy .npz files for all three model
    datasets. If any are missing, generates all of them from the
    data_generator module.

    Args:
        data_dir: Directory to store generated data files.
    """
    required_files = [
        "anomaly_features.npz",
        "depletion_sequences.npz",
        "irrigation_features.npz",
    ]

    if all((data_dir / f).exists() for f in required_files):
        logger.info("Training data already exists at %s", data_dir)
        return

    logger.info("Generating training datasets...")
    data_dir.mkdir(parents=True, exist_ok=True)

    # Ensure project root is on sys.path for imports
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from edge.models.data_generator import (
        generate_water_quality_data,
        generate_groundwater_data,
        generate_irrigation_data,
        WaterQualityConfig,
        GroundwaterConfig,
        IrrigationConfig,
    )

    # 1. Water quality anomaly data
    logger.info("[1/3] Generating water quality anomaly data...")
    wq_config = WaterQualityConfig(n_samples=50_000, seed=42)
    wq_features, wq_labels = generate_water_quality_data(wq_config)
    np.savez(
        data_dir / "anomaly_features.npz",
        features=wq_features,
        labels=wq_labels,
    )
    logger.info(
        "  Anomaly data: %d samples, %d features, %d classes",
        len(wq_features), wq_features.shape[1], len(np.unique(wq_labels)),
    )

    # 2. Groundwater depletion time-series
    logger.info("[2/3] Generating groundwater depletion sequences...")
    gw_config = GroundwaterConfig(n_sequences=5_000, seed=42)
    gw_inputs, gw_targets = generate_groundwater_data(gw_config)
    np.savez(
        data_dir / "depletion_sequences.npz",
        inputs=gw_inputs,
        targets=gw_targets,
    )
    logger.info(
        "  Depletion data: %d sequences, input shape %s, target shape %s",
        len(gw_inputs), gw_inputs.shape[1:], gw_targets.shape[1:],
    )

    # 3. Irrigation optimization data
    logger.info("[3/3] Generating irrigation optimization data...")
    irr_config = IrrigationConfig(n_samples=30_000, seed=42)
    irr_features, irr_targets = generate_irrigation_data(irr_config)
    np.savez(
        data_dir / "irrigation_features.npz",
        features=irr_features,
        targets=irr_targets,
    )
    logger.info(
        "  Irrigation data: %d samples, %d features, %d targets",
        len(irr_features), irr_features.shape[1], irr_targets.shape[1],
    )

    logger.info("Dataset generation complete -> %s", data_dir)


# ---------------------------------------------------------------------------
# Model 1: Anomaly Detector (1D-CNN)
# ---------------------------------------------------------------------------

def train_and_export_anomaly(data_dir: Path, output_dir: Path) -> dict:
    """Train the 1D-CNN anomaly detector and export to ONNX.

    Args:
        data_dir: Directory containing anomaly_features.npz.
        output_dir: Directory to save ONNX model and weights.

    Returns:
        Dictionary with training results and model path.
    """
    logger.info("=" * 60)
    logger.info("MODEL 1: Anomaly Detector (1D-CNN)")
    logger.info("=" * 60)

    # Ensure project root is on sys.path
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from edge.models.anomaly_detector import (
        AnomalyDetector,
        AnomalyDetectorConfig,
        train_anomaly_detector,
        export_to_onnx,
    )

    # Load data
    data = np.load(data_dir / "anomaly_features.npz")
    features = data["features"]
    labels = data["labels"]
    logger.info("Loaded anomaly data: %d samples", len(features))

    # Train
    config = AnomalyDetectorConfig(
        epochs=50,
        batch_size=256,
        learning_rate=1e-3,
        patience=8,
    )
    model, metrics = train_anomaly_detector(features, labels, config=config)

    logger.info(
        "Anomaly detector trained: best_val_acc=%.4f at epoch %d (%.1fs)",
        metrics.best_val_accuracy, metrics.best_epoch + 1,
        metrics.total_training_time_s,
    )

    # Export to ONNX
    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / "anomaly_detector.onnx"
    export_to_onnx(model, onnx_path, config=config)

    # Validate ONNX inference
    _validate_onnx(
        onnx_path,
        input_name="sensor_features",
        test_input=np.random.randn(1, config.n_features).astype(np.float32),
        expected_shape=(1, config.n_classes),
        model_name="anomaly_detector",
    )

    # Save PyTorch weights
    import torch
    weights_path = output_dir / "anomaly_detector.pt"
    torch.save(model.state_dict(), str(weights_path))

    size_kb = onnx_path.stat().st_size / 1024
    return {
        "model": "anomaly_detector",
        "best_val_accuracy": metrics.best_val_accuracy,
        "best_epoch": metrics.best_epoch + 1,
        "training_time_s": metrics.total_training_time_s,
        "onnx_path": str(onnx_path),
        "onnx_size_kb": size_kb,
    }


# ---------------------------------------------------------------------------
# Model 2: Depletion Predictor (2-Layer LSTM)
# ---------------------------------------------------------------------------

def train_and_export_depletion(data_dir: Path, output_dir: Path) -> dict:
    """Train the 2-layer LSTM depletion predictor and export to ONNX.

    Args:
        data_dir: Directory containing depletion_sequences.npz.
        output_dir: Directory to save ONNX model and weights.

    Returns:
        Dictionary with training results and model path.
    """
    logger.info("=" * 60)
    logger.info("MODEL 2: Depletion Predictor (2-Layer LSTM)")
    logger.info("=" * 60)

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from edge.models.depletion_predictor import (
        DepletionLSTM,
        DepletionLSTMConfig,
        train_depletion_model,
        export_to_onnx,
    )

    # Load data
    data = np.load(data_dir / "depletion_sequences.npz")
    inputs = data["inputs"]
    targets = data["targets"]

    # The data generator produces 8-feature sequences; we use the first 7
    # (water_level, rainfall, extraction_rate, temperature, humidity,
    #  day_sin, day_cos), dropping the 8th (trend indicator)
    if inputs.shape[2] > 7:
        logger.info(
            "Trimming input features from %d to 7 (dropping trend column)",
            inputs.shape[2],
        )
        inputs = inputs[:, :, :7]

    logger.info(
        "Loaded depletion data: %d sequences, input %s, target %s",
        len(inputs), inputs.shape[1:], targets.shape[1:],
    )

    # Train
    config = DepletionLSTMConfig(
        n_input_features=7,
        lookback_days=90,
        forecast_days=30,
        hidden_size=128,
        n_layers=2,
        epochs=80,
        batch_size=128,
        learning_rate=5e-4,
        patience=12,
    )
    model, metrics = train_depletion_model(inputs, targets, config=config)

    logger.info(
        "Depletion predictor trained: best_val_loss=%.4f at epoch %d (%.1fs)",
        metrics.best_val_loss, metrics.best_epoch + 1,
        metrics.total_training_time_s,
    )

    # Export to ONNX
    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / "depletion_predictor.onnx"
    export_to_onnx(model, onnx_path, config=config)

    # Validate ONNX inference
    _validate_onnx(
        onnx_path,
        input_name="historical_data",
        test_input=np.random.randn(
            1, config.lookback_days, config.n_input_features,
        ).astype(np.float32),
        expected_shape=(1, config.forecast_days),
        model_name="depletion_predictor",
    )

    # Save PyTorch weights
    import torch
    weights_path = output_dir / "depletion_predictor.pt"
    torch.save(model.state_dict(), str(weights_path))

    size_kb = onnx_path.stat().st_size / 1024
    return {
        "model": "depletion_predictor",
        "best_val_loss": metrics.best_val_loss,
        "best_epoch": metrics.best_epoch + 1,
        "training_time_s": metrics.total_training_time_s,
        "onnx_path": str(onnx_path),
        "onnx_size_kb": size_kb,
    }


# ---------------------------------------------------------------------------
# Model 3: Irrigation Optimizer (XGBoost)
# ---------------------------------------------------------------------------

def train_and_export_irrigation(data_dir: Path, output_dir: Path) -> dict:
    """Train the XGBoost irrigation optimizer and export to ONNX.

    Args:
        data_dir: Directory containing irrigation_features.npz.
        output_dir: Directory to save ONNX model and weights.

    Returns:
        Dictionary with training results and model path.
    """
    logger.info("=" * 60)
    logger.info("MODEL 3: Irrigation Optimizer (XGBoost)")
    logger.info("=" * 60)

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from edge.models.irrigation_optimizer import (
        IrrigationOptimizerConfig,
        train_irrigation_model,
        export_to_onnx,
        save_model_pickle,
    )

    # Load data
    data = np.load(data_dir / "irrigation_features.npz")
    features = data["features"]
    targets = data["targets"]
    logger.info(
        "Loaded irrigation data: %d samples, %d features, %d targets",
        len(features), features.shape[1], targets.shape[1],
    )

    # Train
    config = IrrigationOptimizerConfig(
        n_estimators=500,
        max_depth=8,
        learning_rate=0.05,
        early_stopping_rounds=30,
    )
    model, metrics = train_irrigation_model(features, targets, config=config)

    logger.info(
        "Irrigation optimizer trained in %.1fs",
        metrics.total_training_time_s,
    )
    for target_name, mae in metrics.target_maes.items():
        rmse = metrics.target_rmses.get(target_name, 0)
        r2 = metrics.target_r2s.get(target_name, 0)
        logger.info("  %s: MAE=%.3f, RMSE=%.3f, R2=%.4f", target_name, mae, rmse, r2)

    # Export to ONNX via skl2onnx
    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / "irrigation_optimizer.onnx"

    try:
        export_to_onnx(model, onnx_path, config=config)
        onnx_exported = True
    except ImportError:
        logger.warning(
            "skl2onnx not available -- saving pickle fallback instead. "
            "Install with: pip install skl2onnx"
        )
        onnx_exported = False

    # Always save pickle as backup
    pkl_path = output_dir / "irrigation_optimizer.pkl"
    save_model_pickle(model, pkl_path)

    # Validate ONNX if exported
    if onnx_exported and onnx_path.exists():
        _validate_onnx(
            onnx_path,
            input_name="irrigation_features",
            test_input=np.random.randn(1, config.n_features).astype(np.float32),
            expected_shape=None,  # MultiOutput shape varies by converter
            model_name="irrigation_optimizer",
        )

    size_kb = onnx_path.stat().st_size / 1024 if onnx_path.exists() else 0
    return {
        "model": "irrigation_optimizer",
        "target_maes": metrics.target_maes,
        "target_rmses": metrics.target_rmses,
        "target_r2s": metrics.target_r2s,
        "training_time_s": metrics.total_training_time_s,
        "onnx_path": str(onnx_path) if onnx_exported else None,
        "pkl_path": str(pkl_path),
        "onnx_size_kb": size_kb,
    }


# ---------------------------------------------------------------------------
# ONNX Validation Utility
# ---------------------------------------------------------------------------

def _validate_onnx(
    onnx_path: Path,
    input_name: str,
    test_input: np.ndarray,
    expected_shape: Optional[tuple[int, ...]],
    model_name: str,
) -> bool:
    """Validate that an ONNX model loads and produces correct output shape.

    Args:
        onnx_path: Path to the ONNX model file.
        input_name: Name of the input tensor in the ONNX graph.
        test_input: Dummy input tensor for inference test.
        expected_shape: Expected output shape, or None to skip shape check.
        model_name: Model name for logging.

    Returns:
        True if validation passed, False otherwise.
    """
    try:
        import onnxruntime as ort

        session = ort.InferenceSession(str(onnx_path))

        # Use the actual input name from the model if available
        actual_input_name = session.get_inputs()[0].name
        if actual_input_name != input_name:
            logger.info(
                "  ONNX input name mismatch: expected '%s', got '%s' (using actual)",
                input_name, actual_input_name,
            )
            input_name = actual_input_name

        outputs = session.run(None, {input_name: test_input})

        if expected_shape is not None:
            actual_shape = outputs[0].shape
            if actual_shape != expected_shape:
                logger.error(
                    "  %s ONNX output shape mismatch: expected %s, got %s",
                    model_name, expected_shape, actual_shape,
                )
                return False

        logger.info(
            "  %s ONNX validation PASSED (output shape: %s)",
            model_name, outputs[0].shape,
        )
        return True

    except ImportError:
        logger.warning(
            "  onnxruntime not installed -- skipping ONNX validation for %s",
            model_name,
        )
        return False
    except Exception:
        logger.exception("  %s ONNX validation FAILED", model_name)
        return False


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point with argparse CLI."""
    parser = argparse.ArgumentParser(
        description="Train all JalNetra ML models end-to-end",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python training/scripts/train_all_models.py
  python training/scripts/train_all_models.py --data-dir training/data --output-dir edge/models/weights
  python training/scripts/train_all_models.py --models anomaly depletion
  python training/scripts/train_all_models.py --skip-data-gen
        """,
    )

    parser.add_argument(
        "--data-dir",
        type=Path,
        default=ROOT / "training" / "data",
        help="Directory for training data (default: training/data)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "edge" / "models" / "weights",
        help="Directory for model weights and ONNX files (default: edge/models/weights)",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=["anomaly", "depletion", "irrigation"],
        default=["anomaly", "depletion", "irrigation"],
        help="Which models to train (default: all three)",
    )
    parser.add_argument(
        "--skip-data-gen",
        action="store_true",
        help="Skip dataset generation (assumes data already exists)",
    )

    args = parser.parse_args()

    start_time = time.time()

    print("=" * 60)
    print("JalNetra -- Complete ML Model Training Pipeline")
    print("=" * 60)
    print(f"  Data directory:   {args.data_dir}")
    print(f"  Output directory: {args.output_dir}")
    print(f"  Models to train:  {', '.join(args.models)}")
    print("=" * 60)

    # Step 1: Generate data if needed
    if not args.skip_data_gen:
        generate_data_if_needed(args.data_dir)
    else:
        logger.info("Skipping data generation (--skip-data-gen)")

    results: dict[str, dict] = {}

    # Step 2: Train anomaly detector
    if "anomaly" in args.models:
        try:
            results["anomaly_detector"] = train_and_export_anomaly(
                args.data_dir, args.output_dir,
            )
        except Exception:
            logger.exception("Anomaly detector training FAILED")
            results["anomaly_detector"] = {"model": "anomaly_detector", "error": True}

    # Step 3: Train depletion predictor
    if "depletion" in args.models:
        try:
            results["depletion_predictor"] = train_and_export_depletion(
                args.data_dir, args.output_dir,
            )
        except Exception:
            logger.exception("Depletion predictor training FAILED")
            results["depletion_predictor"] = {"model": "depletion_predictor", "error": True}

    # Step 4: Train irrigation optimizer
    if "irrigation" in args.models:
        try:
            results["irrigation_optimizer"] = train_and_export_irrigation(
                args.data_dir, args.output_dir,
            )
        except Exception:
            logger.exception("Irrigation optimizer training FAILED")
            results["irrigation_optimizer"] = {"model": "irrigation_optimizer", "error": True}

    # Summary
    total_time = time.time() - start_time

    print("\n" + "=" * 60)
    print("Training Pipeline Complete")
    print("=" * 60)
    print(f"  Total duration: {total_time:.1f}s")
    print(f"  Output directory: {args.output_dir}")
    print()

    for name, info in results.items():
        if info.get("error"):
            print(f"  {name}: FAILED (see logs)")
        else:
            size = info.get("onnx_size_kb", 0)
            train_time = info.get("training_time_s", 0)
            onnx_path = info.get("onnx_path", "N/A")
            print(f"  {name}:")
            print(f"    ONNX size:     {size:.1f} KB")
            print(f"    Training time: {train_time:.1f}s")
            print(f"    ONNX path:     {onnx_path}")

            # Print model-specific metrics
            if "best_val_accuracy" in info:
                print(f"    Val accuracy:  {info['best_val_accuracy']:.4f}")
            if "best_val_loss" in info:
                print(f"    Val loss:      {info['best_val_loss']:.6f}")
            if "target_maes" in info:
                for target, mae in info["target_maes"].items():
                    print(f"    {target} MAE: {mae:.3f}")

    print("=" * 60)

    # Exit with error code if any model failed
    if any(info.get("error") for info in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
