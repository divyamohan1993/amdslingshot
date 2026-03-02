"""
JalNetra — Water Quality Anomaly Detector (1D-CNN)
===================================================

A 1D Convolutional Neural Network that classifies water quality sensor readings
into three categories: normal, contamination, and sensor_fault.

Architecture:
    - Input:  (batch, 10) sensor features
    - Reshape to (batch, 1, 10) for 1D convolution over feature dimension
    - 3 x Conv1D blocks with BatchNorm, ReLU, Dropout
    - Global Average Pooling
    - 2 x Dense layers with dropout
    - Output: (batch, 3) class probabilities via softmax

Training targets BIS IS 10500:2012 compliance monitoring with CPCB-style data
distributions. Designed for INT8 quantized deployment on AMD XDNA NPU via
ONNX Runtime + Vitis AI EP.

Author: JalNetra / dmj.one
License: MIT
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset, random_split

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model Hyperparameters
# ---------------------------------------------------------------------------

@dataclass
class AnomalyDetectorConfig:
    """Hyperparameters for the anomaly detection 1D-CNN."""
    n_features: int = 10
    n_classes: int = 3
    # Conv blocks
    conv_channels: tuple[int, ...] = (32, 64, 128)
    kernel_sizes: tuple[int, ...] = (3, 3, 3)
    # Dense layers
    dense_units: tuple[int, ...] = (128, 64)
    dropout: float = 0.3
    # Training
    batch_size: int = 256
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    epochs: int = 50
    patience: int = 8          # early stopping patience
    val_split: float = 0.15    # validation fraction
    label_smoothing: float = 0.05
    # ONNX export
    onnx_opset: int = 17


# ---------------------------------------------------------------------------
# 1D-CNN Architecture
# ---------------------------------------------------------------------------

class ConvBlock(nn.Module):
    """Single 1D convolution block: Conv1D -> BatchNorm -> ReLU -> Dropout."""

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        # Padding to preserve sequence length
        padding = kernel_size // 2
        self.conv = nn.Conv1d(in_channels, out_channels, kernel_size, padding=padding)
        self.bn = nn.BatchNorm1d(out_channels)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv(x)
        x = self.bn(x)
        x = F.relu(x)
        x = self.dropout(x)
        return x


class AnomalyDetector(nn.Module):
    """1D-CNN for water quality anomaly classification.

    Takes a flat vector of 10 sensor features and classifies into one of
    three categories: normal (0), contamination (1), sensor_fault (2).

    The model reshapes the input to (batch, 1, n_features) to treat each
    feature as a position in a 1D sequence, then applies successive
    convolutional filters to learn feature interactions.
    """

    def __init__(self, config: Optional[AnomalyDetectorConfig] = None) -> None:
        super().__init__()
        self.config = config or AnomalyDetectorConfig()
        c = self.config

        # Convolutional backbone
        conv_layers: list[nn.Module] = []
        in_ch = 1
        for out_ch, ks in zip(c.conv_channels, c.kernel_sizes):
            conv_layers.append(ConvBlock(in_ch, out_ch, ks, c.dropout * 0.5))
            in_ch = out_ch
        self.conv_backbone = nn.Sequential(*conv_layers)

        # Global average pooling is applied in forward()

        # Classification head
        head_layers: list[nn.Module] = []
        in_dim = c.conv_channels[-1]
        for units in c.dense_units:
            head_layers.extend([
                nn.Linear(in_dim, units),
                nn.ReLU(),
                nn.Dropout(c.dropout),
            ])
            in_dim = units
        head_layers.append(nn.Linear(in_dim, c.n_classes))
        self.classifier = nn.Sequential(*head_layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: Input tensor of shape (batch, n_features) with n_features=10.

        Returns:
            Class probabilities of shape (batch, n_classes) after softmax.
        """
        # Reshape: (batch, 10) -> (batch, 1, 10) for Conv1D
        if x.dim() == 2:
            x = x.unsqueeze(1)

        # Conv backbone: (batch, 1, 10) -> (batch, C, 10)
        x = self.conv_backbone(x)

        # Global average pooling: (batch, C, 10) -> (batch, C)
        x = x.mean(dim=-1)

        # Classification: (batch, C) -> (batch, n_classes)
        logits = self.classifier(x)
        return F.softmax(logits, dim=-1)

    def predict_logits(self, x: torch.Tensor) -> torch.Tensor:
        """Return raw logits (before softmax) for loss computation.

        Args:
            x: Input tensor of shape (batch, n_features).

        Returns:
            Raw logits of shape (batch, n_classes).
        """
        if x.dim() == 2:
            x = x.unsqueeze(1)
        x = self.conv_backbone(x)
        x = x.mean(dim=-1)
        return self.classifier(x)


# ---------------------------------------------------------------------------
# Training Pipeline
# ---------------------------------------------------------------------------

@dataclass
class TrainingMetrics:
    """Tracks training metrics across epochs."""
    train_losses: list[float] = field(default_factory=list)
    val_losses: list[float] = field(default_factory=list)
    val_accuracies: list[float] = field(default_factory=list)
    best_val_accuracy: float = 0.0
    best_epoch: int = 0
    total_training_time_s: float = 0.0


def train_anomaly_detector(
    features: np.ndarray,
    labels: np.ndarray,
    config: Optional[AnomalyDetectorConfig] = None,
    device: Optional[str] = None,
) -> tuple[AnomalyDetector, TrainingMetrics]:
    """Train the anomaly detection model end-to-end.

    Implements a full training loop with:
    - Train/validation split
    - Label smoothing cross-entropy loss
    - AdamW optimizer with cosine annealing LR schedule
    - Early stopping based on validation accuracy
    - Class-weighted loss to handle imbalanced datasets

    Args:
        features: Input features of shape (n_samples, 10).
        labels: Class labels of shape (n_samples,) with values in {0, 1, 2}.
        config: Model and training hyperparameters.
        device: PyTorch device string. Auto-detects if None.

    Returns:
        Tuple of (trained_model, training_metrics).
    """
    if config is None:
        config = AnomalyDetectorConfig()

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info("Training anomaly detector on %s with %d samples", device, len(features))

    # --- Prepare data ---
    X = torch.from_numpy(features).float()
    y = torch.from_numpy(labels).long()

    dataset = TensorDataset(X, y)
    val_size = int(len(dataset) * config.val_split)
    train_size = len(dataset) - val_size
    train_ds, val_ds = random_split(
        dataset, [train_size, val_size],
        generator=torch.Generator().manual_seed(42),
    )

    train_loader = DataLoader(
        train_ds, batch_size=config.batch_size, shuffle=True,
        num_workers=0, pin_memory=(device != "cpu"),
    )
    val_loader = DataLoader(
        val_ds, batch_size=config.batch_size * 2, shuffle=False,
        num_workers=0, pin_memory=(device != "cpu"),
    )

    # --- Compute class weights for imbalanced data ---
    class_counts = np.bincount(labels, minlength=config.n_classes)
    class_weights = 1.0 / (class_counts + 1e-6)
    class_weights = class_weights / class_weights.sum() * config.n_classes
    class_weights_tensor = torch.from_numpy(class_weights).float().to(device)

    # --- Initialize model, loss, optimizer ---
    model = AnomalyDetector(config).to(device)
    criterion = nn.CrossEntropyLoss(
        weight=class_weights_tensor,
        label_smoothing=config.label_smoothing,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=config.epochs, eta_min=1e-6,
    )

    # --- Training loop ---
    metrics = TrainingMetrics()
    best_state = None
    start_time = time.time()

    for epoch in range(config.epochs):
        # Train phase
        model.train()
        epoch_loss = 0.0
        n_batches = 0

        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device, non_blocking=True)
            batch_y = batch_y.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)
            logits = model.predict_logits(batch_x)
            loss = criterion(logits, batch_y)
            loss.backward()

            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)

            optimizer.step()
            epoch_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_train_loss = epoch_loss / max(n_batches, 1)
        metrics.train_losses.append(avg_train_loss)

        # Validation phase
        model.eval()
        val_loss = 0.0
        correct = 0
        total = 0

        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x = batch_x.to(device, non_blocking=True)
                batch_y = batch_y.to(device, non_blocking=True)
                logits = model.predict_logits(batch_x)
                loss = criterion(logits, batch_y)
                val_loss += loss.item()
                preds = logits.argmax(dim=-1)
                correct += (preds == batch_y).sum().item()
                total += batch_y.size(0)

        avg_val_loss = val_loss / max(len(val_loader), 1)
        val_accuracy = correct / max(total, 1)
        metrics.val_losses.append(avg_val_loss)
        metrics.val_accuracies.append(val_accuracy)

        if val_accuracy > metrics.best_val_accuracy:
            metrics.best_val_accuracy = val_accuracy
            metrics.best_epoch = epoch
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        # Logging
        if (epoch + 1) % 5 == 0 or epoch == 0:
            logger.info(
                "Epoch %3d/%d  train_loss=%.4f  val_loss=%.4f  val_acc=%.4f  lr=%.2e",
                epoch + 1, config.epochs, avg_train_loss, avg_val_loss,
                val_accuracy, scheduler.get_last_lr()[0],
            )

        # Early stopping
        if epoch - metrics.best_epoch >= config.patience:
            logger.info("Early stopping at epoch %d (best: %d)", epoch + 1, metrics.best_epoch + 1)
            break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)
        model.to(device)

    metrics.total_training_time_s = time.time() - start_time
    logger.info(
        "Training complete: best_val_acc=%.4f at epoch %d (%.1fs total)",
        metrics.best_val_accuracy, metrics.best_epoch + 1, metrics.total_training_time_s,
    )

    return model, metrics


# ---------------------------------------------------------------------------
# ONNX Export
# ---------------------------------------------------------------------------

def export_to_onnx(
    model: AnomalyDetector,
    output_path: str | Path,
    config: Optional[AnomalyDetectorConfig] = None,
) -> Path:
    """Export the trained model to ONNX format with dynamic batch axis.

    Uses opset 17+ for full operator coverage. The exported model includes
    softmax as the final layer for direct probability output.

    Args:
        model: Trained AnomalyDetector model.
        output_path: Path to save the .onnx file.
        config: Model config for opset version. Uses model's config if None.

    Returns:
        Path to the saved ONNX file.
    """
    if config is None:
        config = model.config

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model.eval()
    model.cpu()

    # Dummy input for tracing
    dummy_input = torch.randn(1, config.n_features)

    torch.onnx.export(
        model,
        dummy_input,
        str(output_path),
        export_params=True,
        opset_version=config.onnx_opset,
        do_constant_folding=True,
        input_names=["sensor_features"],
        output_names=["class_probabilities"],
        dynamic_axes={
            "sensor_features": {0: "batch_size"},
            "class_probabilities": {0: "batch_size"},
        },
    )

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    file_hash = _compute_file_hash(output_path)
    logger.info(
        "Exported anomaly detector ONNX: %s (%.2f MB, sha256=%s)",
        output_path, file_size_mb, file_hash[:16],
    )

    return output_path


# ---------------------------------------------------------------------------
# INT8 Quantization
# ---------------------------------------------------------------------------

def quantize_int8(
    onnx_path: str | Path,
    output_path: Optional[str | Path] = None,
    calibration_data: Optional[np.ndarray] = None,
) -> Path:
    """Quantize the ONNX model to INT8 using onnxruntime quantization.

    Applies static quantization when calibration data is provided, otherwise
    falls back to dynamic quantization. INT8 models run efficiently on AMD
    XDNA NPU via the Vitis AI Execution Provider.

    Args:
        onnx_path: Path to the FP32 ONNX model.
        output_path: Path for the quantized model. Auto-generated if None.
        calibration_data: Representative input data for static quantization,
                          shape (n_samples, 10).

    Returns:
        Path to the quantized ONNX model.
    """
    try:
        from onnxruntime.quantization import (
            CalibrationDataReader,
            QuantFormat,
            QuantType,
            quantize_dynamic,
            quantize_static,
        )
    except ImportError:
        logger.error(
            "onnxruntime-extensions or onnxruntime quantization not available. "
            "Install with: pip install onnxruntime onnxruntime-extensions"
        )
        raise

    onnx_path = Path(onnx_path)
    if output_path is None:
        output_path = onnx_path.with_name(
            onnx_path.stem.replace("_fp32", "") + "_int8.onnx"
        )
    output_path = Path(output_path)

    if calibration_data is not None and len(calibration_data) > 0:
        # Static quantization with calibration data

        class _AnomalyCalibrationReader(CalibrationDataReader):
            """Provides calibration data for static quantization."""

            def __init__(self, data: np.ndarray, batch_size: int = 64) -> None:
                self.data = data.astype(np.float32)
                self.batch_size = batch_size
                self.idx = 0

            def get_next(self) -> Optional[dict[str, np.ndarray]]:
                if self.idx >= len(self.data):
                    return None
                end = min(self.idx + self.batch_size, len(self.data))
                batch = self.data[self.idx:end]
                self.idx = end
                return {"sensor_features": batch}

        # Pre-process model for quantization
        from onnxruntime.quantization import preprocess as quant_preprocess

        preprocessed_path = onnx_path.with_name(onnx_path.stem + "_preprocessed.onnx")
        quant_preprocess.quant_pre_process(
            str(onnx_path), str(preprocessed_path), skip_symbolic_shape=True,
        )

        reader = _AnomalyCalibrationReader(calibration_data[:1000])
        quantize_static(
            model_input=str(preprocessed_path),
            model_output=str(output_path),
            calibration_data_reader=reader,
            quant_format=QuantFormat.QDQ,
            per_channel=True,
            weight_type=QuantType.QInt8,
            activation_type=QuantType.QUInt8,
        )

        # Cleanup preprocessed file
        preprocessed_path.unlink(missing_ok=True)
    else:
        # Dynamic quantization (no calibration data needed)
        quantize_dynamic(
            model_input=str(onnx_path),
            model_output=str(output_path),
            weight_type=QuantType.QInt8,
        )

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    original_size_mb = onnx_path.stat().st_size / (1024 * 1024)
    compression = (1 - file_size_mb / max(original_size_mb, 0.001)) * 100

    logger.info(
        "INT8 quantized: %s (%.2f MB, %.1f%% compression)",
        output_path, file_size_mb, compression,
    )

    return output_path


# ---------------------------------------------------------------------------
# Preprocessing Utilities
# ---------------------------------------------------------------------------

def preprocess_sensor_reading(
    tds: float,
    ph: float,
    turbidity: float,
    dissolved_oxygen: float,
    flow_rate: float,
    water_level: float,
    tds_prev: Optional[float] = None,
    ph_prev: Optional[float] = None,
    timestamp_hour: float = 12.0,
    norm_stats: Optional[object] = None,
) -> np.ndarray:
    """Preprocess a single sensor reading into model input features.

    Computes rate-of-change features and temporal encodings from raw
    sensor values. Optionally applies z-score normalization.

    Args:
        tds: Total Dissolved Solids (mg/L).
        ph: pH value.
        turbidity: Turbidity (NTU).
        dissolved_oxygen: Dissolved Oxygen (mg/L).
        flow_rate: Flow rate (L/min).
        water_level: Groundwater depth (m).
        tds_prev: Previous TDS reading for rate computation.
        ph_prev: Previous pH reading for rate computation.
        timestamp_hour: Hour of day (0-24) for temporal encoding.
        norm_stats: NormalizationStats instance for z-score normalization.

    Returns:
        Feature vector of shape (1, 10) ready for model input.
    """
    # Rate of change (per hour, assuming ~30s sampling interval)
    tds_rate = (tds - tds_prev) * 120.0 if tds_prev is not None else 0.0
    ph_rate = (ph - ph_prev) * 120.0 if ph_prev is not None else 0.0

    # Temporal encoding
    hour_sin = np.sin(2 * np.pi * timestamp_hour / 24.0)
    hour_cos = np.cos(2 * np.pi * timestamp_hour / 24.0)

    features = np.array([[
        tds, ph, turbidity, dissolved_oxygen, flow_rate, water_level,
        tds_rate, ph_rate, hour_sin, hour_cos,
    ]], dtype=np.float32)

    if norm_stats is not None:
        features = norm_stats.normalize(features)

    return features


def postprocess_anomaly_output(probabilities: np.ndarray) -> dict:
    """Convert raw model output probabilities to a structured result.

    Args:
        probabilities: Model output of shape (batch, 3) or (3,).

    Returns:
        Dictionary with anomaly classification results.
    """
    if probabilities.ndim == 1:
        probabilities = probabilities.reshape(1, -1)

    results = []
    anomaly_types = ["normal", "contamination", "sensor_fault"]

    for probs in probabilities:
        idx = int(np.argmax(probs))
        results.append({
            "is_anomaly": idx != 0,
            "anomaly_type": anomaly_types[idx],
            "confidence": float(probs[idx]),
            "probabilities": {
                "normal": float(probs[0]),
                "contamination": float(probs[1]),
                "sensor_fault": float(probs[2]),
            },
        })

    return results[0] if len(results) == 1 else results


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _compute_file_hash(path: Path, algorithm: str = "sha256") -> str:
    """Compute hex digest hash of a file."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
