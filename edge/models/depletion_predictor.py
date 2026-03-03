"""
JalNetra — Groundwater Depletion Predictor (2-Layer LSTM)
=========================================================

Predicts 30-day water level forecast from 90-day historical lookback.

Input:  7 features (water_level, rainfall, extraction_rate, temperature,
        humidity, day_sin, day_cos)
Output: 30-day forecast of water levels

Architecture:
    - Input:  (batch, 90, 7) — 90-day lookback, 7 features per timestep
    - Input projection + LayerNorm
    - 2-layer LSTM with 128 hidden units
    - Fully connected decoder: hidden -> 128 -> 64 -> 30 (forecast days)
    - Output: (batch, 30) — predicted water levels for next 30 days

The model captures:
    - Seasonal monsoon recharge cycles
    - Long-term depletion trends from over-extraction
    - Rainfall-level correlation with percolation lag
    - Temperature-driven evapotranspiration effects

Trained on India-WRIS style groundwater data from the data generator.
Designed for INT8 quantized deployment on AMD XDNA NPU via ONNX Runtime
+ Vitis AI EP.

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
from torch.utils.data import DataLoader, TensorDataset, random_split

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model Hyperparameters
# ---------------------------------------------------------------------------

@dataclass
class DepletionLSTMConfig:
    """Hyperparameters for the groundwater depletion LSTM."""
    # Input dimensions
    n_input_features: int = 7
    lookback_days: int = 90
    forecast_days: int = 30
    # LSTM architecture
    hidden_size: int = 128
    n_layers: int = 2
    lstm_dropout: float = 0.2
    # Decoder
    decoder_units: tuple[int, ...] = (128, 64)
    decoder_dropout: float = 0.3
    # Training
    batch_size: int = 128
    learning_rate: float = 5e-4
    weight_decay: float = 1e-4
    epochs: int = 80
    patience: int = 12
    val_split: float = 0.15
    # ONNX
    onnx_opset: int = 17


# ---------------------------------------------------------------------------
# 2-Layer LSTM Architecture
# ---------------------------------------------------------------------------

class DepletionLSTM(nn.Module):
    """2-layer LSTM for groundwater level forecasting.

    Sequence-to-one prediction: encodes a 90-day input sequence through
    two stacked LSTM layers, then decodes the final hidden state into a
    30-day future water level forecast via fully-connected layers.

    Input shape:  (batch, 90, 7)
    Output shape: (batch, 30)
    """

    def __init__(self, config: Optional[DepletionLSTMConfig] = None) -> None:
        super().__init__()
        self.config = config or DepletionLSTMConfig()
        c = self.config

        # Input projection: map 7 raw features to hidden_size
        self.input_proj = nn.Linear(c.n_input_features, c.hidden_size)
        self.input_norm = nn.LayerNorm(c.hidden_size)

        # 2-layer LSTM encoder
        self.lstm = nn.LSTM(
            input_size=c.hidden_size,
            hidden_size=c.hidden_size,
            num_layers=c.n_layers,
            batch_first=True,
            dropout=c.lstm_dropout if c.n_layers > 1 else 0.0,
        )

        # Post-LSTM layer norm for training stability
        self.lstm_norm = nn.LayerNorm(c.hidden_size)

        # Decoder: maps final hidden state -> 30-day forecast
        decoder_layers: list[nn.Module] = []
        in_dim = c.hidden_size
        for units in c.decoder_units:
            decoder_layers.extend([
                nn.Linear(in_dim, units),
                nn.ReLU(),
                nn.Dropout(c.decoder_dropout),
            ])
            in_dim = units
        decoder_layers.append(nn.Linear(in_dim, c.forecast_days))
        self.decoder = nn.Sequential(*decoder_layers)

        # Initialize weights for stable training
        self._init_weights()

    def _init_weights(self) -> None:
        """Xavier/orthogonal initialization for better convergence."""
        for name, param in self.lstm.named_parameters():
            if "weight_ih" in name:
                nn.init.xavier_uniform_(param)
            elif "weight_hh" in name:
                nn.init.orthogonal_(param)
            elif "bias" in name:
                nn.init.zeros_(param)
                # Set forget gate bias to 1 for better long-term memory
                n = param.size(0)
                param.data[n // 4 : n // 2].fill_(1.0)

        for module in self.decoder:
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                nn.init.zeros_(module.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass for the LSTM depletion predictor.

        Args:
            x: Input tensor of shape (batch, lookback_days, n_input_features).
               Features: [water_level, rainfall, extraction_rate, temperature,
                          humidity, day_sin, day_cos]

        Returns:
            Predicted water levels of shape (batch, forecast_days).
        """
        # Input projection: (batch, 90, 7) -> (batch, 90, hidden_size)
        x = self.input_proj(x)
        x = self.input_norm(x)

        # LSTM encoding: (batch, 90, hidden_size) -> (batch, 90, hidden_size)
        lstm_out, (_h_n, _c_n) = self.lstm(x)

        # Use last timestep output (encodes full sequence context)
        last_output = lstm_out[:, -1, :]  # (batch, hidden_size)
        last_output = self.lstm_norm(last_output)

        # Decode to forecast: (batch, hidden_size) -> (batch, 30)
        forecast = self.decoder(last_output)

        return forecast

    def predict_sequence(self, x: torch.Tensor) -> torch.Tensor:
        """Convenience wrapper for inference with gradient disabled.

        Args:
            x: Input tensor of shape (batch, lookback_days, n_input_features).

        Returns:
            Predicted water levels of shape (batch, forecast_days).
        """
        self.eval()
        with torch.no_grad():
            return self.forward(x)


# ---------------------------------------------------------------------------
# Training Pipeline
# ---------------------------------------------------------------------------

@dataclass
class TrainingMetrics:
    """Tracks training metrics across epochs."""
    train_losses: list[float] = field(default_factory=list)
    val_losses: list[float] = field(default_factory=list)
    val_maes: list[float] = field(default_factory=list)
    best_val_loss: float = float("inf")
    best_epoch: int = 0
    total_training_time_s: float = 0.0


def train_depletion_model(
    inputs: np.ndarray,
    targets: np.ndarray,
    config: Optional[DepletionLSTMConfig] = None,
    device: Optional[str] = None,
) -> tuple[DepletionLSTM, TrainingMetrics]:
    """Train the groundwater depletion LSTM end-to-end.

    Training procedure:
    - MSE loss (mean squared error for regression)
    - AdamW optimizer with OneCycleLR scheduling
    - Gradient clipping for LSTM stability
    - Early stopping on validation loss
    - Teacher forcing is not used (direct seq-to-one prediction)

    Args:
        inputs: Input sequences of shape (n_sequences, 90, 7).
        targets: Target water levels of shape (n_sequences, 30).
        config: Model and training hyperparameters.
        device: PyTorch device string. Auto-detects if None.

    Returns:
        Tuple of (trained_model, training_metrics).
    """
    if config is None:
        config = DepletionLSTMConfig()

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    logger.info(
        "Training depletion LSTM on %s with %d sequences "
        "(%d lookback -> %d forecast)",
        device, len(inputs), config.lookback_days, config.forecast_days,
    )

    # --- Prepare data ---
    X = torch.from_numpy(inputs).float()
    y = torch.from_numpy(targets).float()

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

    # --- Initialize model, loss, optimizer ---
    model = DepletionLSTM(config).to(device)
    criterion = nn.MSELoss()

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=config.learning_rate * 10,
        epochs=config.epochs,
        steps_per_epoch=len(train_loader),
        pct_start=0.3,
        anneal_strategy="cos",
    )

    # --- Training loop ---
    metrics = TrainingMetrics()
    best_state: Optional[dict[str, torch.Tensor]] = None
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
            predictions = model(batch_x)
            loss = criterion(predictions, batch_y)
            loss.backward()

            # Gradient clipping essential for LSTM stability
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)

            optimizer.step()
            scheduler.step()

            epoch_loss += loss.item()
            n_batches += 1

        avg_train_loss = epoch_loss / max(n_batches, 1)
        metrics.train_losses.append(avg_train_loss)

        # Validation phase
        model.eval()
        val_loss = 0.0
        val_mae = 0.0
        n_val_batches = 0

        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x = batch_x.to(device, non_blocking=True)
                batch_y = batch_y.to(device, non_blocking=True)
                predictions = model(batch_x)
                loss = criterion(predictions, batch_y)
                val_loss += loss.item()
                val_mae += torch.mean(torch.abs(predictions - batch_y)).item()
                n_val_batches += 1

        avg_val_loss = val_loss / max(n_val_batches, 1)
        avg_val_mae = val_mae / max(n_val_batches, 1)
        metrics.val_losses.append(avg_val_loss)
        metrics.val_maes.append(avg_val_mae)

        if avg_val_loss < metrics.best_val_loss:
            metrics.best_val_loss = avg_val_loss
            metrics.best_epoch = epoch
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        # Logging
        if (epoch + 1) % 5 == 0 or epoch == 0:
            logger.info(
                "Epoch %3d/%d  train_loss=%.4f  val_loss=%.4f  val_mae=%.3fm",
                epoch + 1, config.epochs, avg_train_loss, avg_val_loss, avg_val_mae,
            )

        # Early stopping
        if epoch - metrics.best_epoch >= config.patience:
            logger.info(
                "Early stopping at epoch %d (best: %d)",
                epoch + 1, metrics.best_epoch + 1,
            )
            break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)
        model.to(device)

    metrics.total_training_time_s = time.time() - start_time
    logger.info(
        "Training complete: best_val_loss=%.4f, best_val_mae=%.3fm at epoch %d (%.1fs total)",
        metrics.best_val_loss,
        min(metrics.val_maes) if metrics.val_maes else 0,
        metrics.best_epoch + 1,
        metrics.total_training_time_s,
    )

    return model, metrics


# ---------------------------------------------------------------------------
# ONNX Export
# ---------------------------------------------------------------------------

def export_to_onnx(
    model: DepletionLSTM,
    output_path: str | Path,
    config: Optional[DepletionLSTMConfig] = None,
) -> Path:
    """Export the trained LSTM model to ONNX format with dynamic batch size.

    Uses opset 17+ with dynamic batch dimension. LSTM operations are fully
    supported in ONNX and can be optimized by Vitis AI EP for NPU inference.

    Args:
        model: Trained DepletionLSTM model.
        output_path: Path to save the .onnx file.
        config: Model config for dimensions. Uses model's config if None.

    Returns:
        Path to the saved ONNX file.
    """
    if config is None:
        config = model.config

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model.eval()
    model.cpu()

    # Dummy input matching expected shape: (1, 90, 7)
    dummy_input = torch.randn(1, config.lookback_days, config.n_input_features)

    torch.onnx.export(
        model,
        dummy_input,
        str(output_path),
        export_params=True,
        opset_version=config.onnx_opset,
        do_constant_folding=True,
        input_names=["historical_data"],
        output_names=["water_level_forecast"],
        dynamic_axes={
            "historical_data": {0: "batch_size"},
            "water_level_forecast": {0: "batch_size"},
        },
    )

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    file_hash = _compute_file_hash(output_path)
    logger.info(
        "Exported depletion LSTM ONNX: %s (%.2f MB, sha256=%s)",
        output_path, file_size_mb, file_hash[:16],
    )

    return output_path


# ---------------------------------------------------------------------------
# Preprocessing Utilities
# ---------------------------------------------------------------------------

def preprocess_groundwater_sequence(
    water_levels: np.ndarray,
    rainfall: np.ndarray,
    extraction_rates: np.ndarray,
    temperatures: np.ndarray,
    humidity: np.ndarray,
    day_of_year: np.ndarray,
    norm_stats: Optional[object] = None,
) -> np.ndarray:
    """Preprocess 90 days of raw sensor data into model input.

    Assembles the 7-feature input vector per timestep and computes temporal
    encodings from day-of-year.

    Args:
        water_levels: Daily water level (m), shape (90,).
        rainfall: Daily rainfall (mm), shape (90,).
        extraction_rates: Daily extraction rate (m3/day), shape (90,).
        temperatures: Daily mean temperature (C), shape (90,).
        humidity: Daily relative humidity (%), shape (90,).
        day_of_year: Day of year (1-365), shape (90,).
        norm_stats: Optional NormalizationStats for z-score normalization.

    Returns:
        Model input of shape (1, 90, 7).
    """
    seq_len = len(water_levels)
    features = np.zeros((1, seq_len, 7), dtype=np.float32)

    features[0, :, 0] = water_levels
    features[0, :, 1] = rainfall
    features[0, :, 2] = extraction_rates
    features[0, :, 3] = temperatures
    features[0, :, 4] = humidity
    features[0, :, 5] = np.sin(2 * np.pi * day_of_year / 365.0)
    features[0, :, 6] = np.cos(2 * np.pi * day_of_year / 365.0)

    if norm_stats is not None:
        features = norm_stats.normalize(features)

    return features


def postprocess_depletion_output(
    predicted_levels: np.ndarray,
    critical_level: float = 5.0,
    warning_level: float = 10.0,
) -> dict:
    """Convert model output to a structured depletion forecast.

    Args:
        predicted_levels: Model output of shape (batch, 30) or (30,).
        critical_level: Water level (m) below which borewell may fail.
        warning_level: Water level (m) for early warning.

    Returns:
        Dictionary with depletion forecast results.
    """
    if predicted_levels.ndim == 1:
        predicted_levels = predicted_levels.reshape(1, -1)

    levels = predicted_levels[0]

    # Find days to critical and warning thresholds
    days_to_critical = -1
    days_to_warning = -1

    for i, level in enumerate(levels):
        if level < critical_level and days_to_critical == -1:
            days_to_critical = i
        if level < warning_level and days_to_warning == -1:
            days_to_warning = i

    # Trend analysis
    first_week_avg = float(np.mean(levels[:7]))
    last_week_avg = float(np.mean(levels[-7:]))
    level_change = last_week_avg - first_week_avg

    if level_change > 1.0:
        trend = "rising"       # Water table dropping (depth increasing)
    elif level_change < -1.0:
        trend = "recovering"   # Water table rising (depth decreasing)
    else:
        trend = "stable"

    return {
        "predicted_levels": levels.tolist(),
        "days_to_critical": days_to_critical,
        "days_to_warning": days_to_warning,
        "trend": trend,
        "level_change_m": float(level_change),
        "min_predicted_level": float(np.min(levels)),
        "max_predicted_level": float(np.max(levels)),
        "critical_threshold_m": critical_level,
        "warning_threshold_m": warning_level,
    }


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
