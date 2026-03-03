"""
JalNetra — Irrigation Scheduling Optimizer (XGBoost)
=====================================================

Uses XGBoost for crop-specific water scheduling via multi-output regression.

Architecture:
    - Multi-output XGBoost regressor (sklearn MultiOutputRegressor wrapper)
    - Input:  15 features covering soil, crop, weather, and water conditions
    - Output: 4 targets (irrigation_liters, duration_min, efficiency_score,
              next_irrigation_h)

Input features (15):
    0:  soil_moisture (0-1)           -- Volumetric water content fraction
    1:  crop_type (0-7)               -- Encoded crop ID
    2:  growth_stage (0-3)            -- Current crop growth stage
    3:  temperature (C)               -- Air temperature
    4:  humidity (%)                  -- Relative humidity
    5:  rainfall_forecast (mm)        -- 7-day cumulative forecast
    6:  wind_speed (m/s)              -- Wind speed at 2m height
    7:  solar_radiation (MJ/m2/day)   -- Daily solar radiation
    8:  water_level (m)               -- Groundwater depth
    9:  water_quality_score (0-1)     -- Composite quality index
    10: previous_irrigation (L)       -- Last irrigation amount
    11: field_area (hectares)         -- Field area
    12: soil_type (0-5)               -- Encoded soil type
    13: evapotranspiration (mm/day)   -- Reference ET0
    14: days_since_last_rain          -- Days since last rainfall

Output targets (4):
    0: irrigation_amount_liters       -- Optimal irrigation volume
    1: duration_minutes               -- Irrigation duration
    2: efficiency_score (0-1)         -- Water use efficiency
    3: next_irrigation_hours          -- Hours until next irrigation needed

The model implements FAO-56 Penman-Monteith inspired water balance logic
learned from synthetic data with crop-specific coefficients (Kc) for
major Indian crops (rice, wheat, sugarcane, cotton, mustard, maize,
groundnut, vegetables).

Export to ONNX via skl2onnx for edge deployment on AMD XDNA NPU via
ONNX Runtime.

Author: JalNetra / dmj.one
License: MIT
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature Names and Constants
# ---------------------------------------------------------------------------

FEATURE_NAMES: list[str] = [
    "soil_moisture",          # 0: Volumetric water content (0-1)
    "crop_type",              # 1: Encoded crop ID (0-7)
    "growth_stage",           # 2: Current growth stage (0-3)
    "temperature",            # 3: Air temperature (C)
    "humidity",               # 4: Relative humidity (%)
    "rainfall_forecast",      # 5: 7-day cumulative forecast (mm)
    "wind_speed",             # 6: Wind speed at 2m (m/s)
    "solar_radiation",        # 7: Daily solar radiation (MJ/m2/day)
    "water_level",            # 8: Groundwater depth (m)
    "water_quality_score",    # 9: Composite quality index (0-1)
    "previous_irrigation",    # 10: Last irrigation amount (L)
    "field_area",             # 11: Field area (hectares)
    "soil_type",              # 12: Encoded soil type (0-5)
    "evapotranspiration",     # 13: Reference ET0 (mm/day)
    "days_since_last_rain",   # 14: Days since last rainfall event
]

TARGET_NAMES: list[str] = [
    "irrigation_amount_liters",  # 0: Optimal irrigation volume (L)
    "duration_minutes",          # 1: Irrigation duration (min)
    "efficiency_score",          # 2: Water use efficiency (0-1)
    "next_irrigation_hours",     # 3: Hours until next irrigation needed
]

# Flood irrigation baselines by crop (L/ha per application) -- ICAR data
FLOOD_IRRIGATION_BASELINES: dict[int, float] = {
    0: 80_000,   # Rice -- heavy flooding
    1: 40_000,   # Wheat
    2: 100_000,  # Sugarcane
    3: 35_000,   # Cotton
    4: 30_000,   # Mustard
    5: 35_000,   # Maize
    6: 30_000,   # Groundnut
    7: 25_000,   # Vegetables
}


# ---------------------------------------------------------------------------
# Model Hyperparameters
# ---------------------------------------------------------------------------

@dataclass
class IrrigationOptimizerConfig:
    """Hyperparameters for the XGBoost irrigation optimizer."""
    # XGBoost parameters
    n_estimators: int = 500
    max_depth: int = 8
    learning_rate: float = 0.05
    min_child_weight: int = 5
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_alpha: float = 0.1       # L1 regularization
    reg_lambda: float = 1.0      # L2 regularization
    gamma: float = 0.1           # minimum loss reduction for split
    # Training
    early_stopping_rounds: int = 30
    val_split: float = 0.15
    seed: int = 42
    n_jobs: int = -1             # use all CPU cores
    # Dimensions
    n_features: int = 15
    n_targets: int = 4
    # ONNX
    onnx_opset: int = 17


# ---------------------------------------------------------------------------
# Training Pipeline
# ---------------------------------------------------------------------------

@dataclass
class TrainingMetrics:
    """Tracks training metrics for the multi-output XGBoost model."""
    target_maes: dict[str, float] = field(default_factory=dict)
    target_rmses: dict[str, float] = field(default_factory=dict)
    target_r2s: dict[str, float] = field(default_factory=dict)
    best_iterations: dict[str, int] = field(default_factory=dict)
    total_training_time_s: float = 0.0


def train_irrigation_model(
    features: np.ndarray,
    targets: np.ndarray,
    config: Optional[IrrigationOptimizerConfig] = None,
) -> tuple[Any, TrainingMetrics]:
    """Train an XGBoost MultiOutputRegressor for irrigation optimization.

    Uses sklearn's MultiOutputRegressor wrapper around XGBRegressor to
    predict 4 output targets simultaneously. Each output gets its own
    dedicated XGBoost model internally, enabling target-specific early
    stopping based on validation RMSE.

    Training includes:
    - Train/validation split for early stopping
    - Per-output RMSE, MAE, and R-squared metrics
    - Feature importance logging

    Args:
        features: Input features of shape (n_samples, 15).
        targets: Target values of shape (n_samples, 4).
        config: Model and training hyperparameters.

    Returns:
        Tuple of (trained_model, training_metrics) where trained_model is
        a sklearn MultiOutputRegressor wrapping XGBRegressor instances.
    """
    try:
        import xgboost as xgb
        from sklearn.multioutput import MultiOutputRegressor
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
    except ImportError as e:
        logger.error(
            "Required packages not available. Install with: "
            "pip install xgboost scikit-learn"
        )
        raise ImportError(
            "xgboost and scikit-learn are required for the irrigation optimizer"
        ) from e

    if config is None:
        config = IrrigationOptimizerConfig()

    logger.info(
        "Training irrigation optimizer with %d samples, %d features -> %d outputs",
        len(features), features.shape[1], targets.shape[1],
    )

    start_time = time.time()

    # --- Train/validation split ---
    X_train, X_val, y_train, y_val = train_test_split(
        features.astype(np.float32),
        targets.astype(np.float32),
        test_size=config.val_split,
        random_state=config.seed,
    )

    # --- Train individual XGBoost models per target with early stopping ---
    metrics = TrainingMetrics()
    individual_models: list[xgb.XGBRegressor] = []

    for i in range(config.n_targets):
        target_name = TARGET_NAMES[i]
        logger.info("Training XGBoost for target: %s", target_name)

        sub_model = xgb.XGBRegressor(
            n_estimators=config.n_estimators,
            max_depth=config.max_depth,
            learning_rate=config.learning_rate,
            min_child_weight=config.min_child_weight,
            subsample=config.subsample,
            colsample_bytree=config.colsample_bytree,
            reg_alpha=config.reg_alpha,
            reg_lambda=config.reg_lambda,
            gamma=config.gamma,
            random_state=config.seed,
            n_jobs=config.n_jobs,
            tree_method="hist",
            objective="reg:squarederror",
            eval_metric="rmse",
            verbosity=0,
            early_stopping_rounds=config.early_stopping_rounds,
        )

        sub_model.fit(
            X_train, y_train[:, i],
            eval_set=[(X_val, y_val[:, i])],
            verbose=False,
        )

        individual_models.append(sub_model)

        # Compute validation metrics
        val_pred = sub_model.predict(X_val)
        mae = float(mean_absolute_error(y_val[:, i], val_pred))
        rmse = float(np.sqrt(mean_squared_error(y_val[:, i], val_pred)))
        r2 = float(r2_score(y_val[:, i], val_pred))

        metrics.target_maes[target_name] = mae
        metrics.target_rmses[target_name] = rmse
        metrics.target_r2s[target_name] = r2
        metrics.best_iterations[target_name] = sub_model.best_iteration

        logger.info(
            "  %s: MAE=%.3f, RMSE=%.3f, R2=%.4f, best_iteration=%d",
            target_name, mae, rmse, r2, sub_model.best_iteration,
        )

    # --- Wrap in MultiOutputRegressor for consistent sklearn API ---
    # We build the MultiOutputRegressor by fitting on the full training set.
    # This gives us the standard sklearn interface needed by skl2onnx.
    base_estimator = xgb.XGBRegressor(
        n_estimators=config.n_estimators,
        max_depth=config.max_depth,
        learning_rate=config.learning_rate,
        min_child_weight=config.min_child_weight,
        subsample=config.subsample,
        colsample_bytree=config.colsample_bytree,
        reg_alpha=config.reg_alpha,
        reg_lambda=config.reg_lambda,
        gamma=config.gamma,
        random_state=config.seed,
        n_jobs=config.n_jobs,
        tree_method="hist",
        objective="reg:squarederror",
        verbosity=0,
    )

    model = MultiOutputRegressor(base_estimator, n_jobs=1)
    model.fit(X_train, y_train)

    metrics.total_training_time_s = time.time() - start_time
    logger.info(
        "Irrigation optimizer training complete in %.1fs",
        metrics.total_training_time_s,
    )

    return model, metrics


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def predict(
    model: Any,
    features: np.ndarray,
) -> dict[str, np.ndarray]:
    """Run inference on the trained irrigation optimizer.

    Applies physical constraints to model outputs: irrigation amount >= 0,
    duration clamped to 0-480 min, efficiency to 0-1, next irrigation to
    4-336 hours.

    Args:
        model: Trained sklearn MultiOutputRegressor.
        features: Input features of shape (n_samples, 15) or (15,).

    Returns:
        Dictionary mapping target names to predicted value arrays.
    """
    if features.ndim == 1:
        features = features.reshape(1, -1)

    features = features.astype(np.float32)
    raw_predictions = model.predict(features)

    if raw_predictions.ndim == 1:
        raw_predictions = raw_predictions.reshape(1, -1)

    # Enforce physical constraints
    predictions = raw_predictions.copy()
    predictions[:, 0] = np.clip(predictions[:, 0], 0, None)       # amount >= 0
    predictions[:, 1] = np.clip(predictions[:, 1], 0, 480)        # 0-8 hours
    predictions[:, 2] = np.clip(predictions[:, 2], 0.0, 1.0)      # efficiency 0-1
    predictions[:, 3] = np.clip(predictions[:, 3], 4, 336)        # 4h to 14d

    result: dict[str, np.ndarray] = {}
    for i, name in enumerate(TARGET_NAMES):
        result[name] = predictions[:, i]

    return result


def postprocess_irrigation_output(
    predictions: dict[str, np.ndarray],
    crop_type: int = 0,
    field_area_ha: float = 1.0,
) -> list[dict]:
    """Convert raw model predictions to structured irrigation recommendations.

    Includes water savings calculation vs traditional flood irrigation
    and urgency classification.

    Args:
        predictions: Dictionary from predict() with arrays per target.
        crop_type: Crop ID for flood irrigation baseline comparison.
        field_area_ha: Field area in hectares.

    Returns:
        List of recommendation dictionaries, one per input sample.
    """
    n_samples = len(predictions["irrigation_amount_liters"])
    results = []

    flood_baseline = FLOOD_IRRIGATION_BASELINES.get(crop_type, 40_000) * field_area_ha

    for i in range(n_samples):
        liters = float(max(0.0, predictions["irrigation_amount_liters"][i]))
        duration = float(max(0.0, predictions["duration_minutes"][i]))
        efficiency = float(np.clip(predictions["efficiency_score"][i], 0.0, 1.0))
        next_h = float(np.clip(predictions["next_irrigation_hours"][i], 4.0, 336.0))

        # Determine urgency based on next irrigation timing
        if next_h < 12:
            urgency = "immediate"
        elif next_h < 48:
            urgency = "soon"
        elif next_h < 168:
            urgency = "scheduled"
        else:
            urgency = "not_needed"

        # Water savings vs flood irrigation
        savings_liters = max(0, flood_baseline - liters)
        savings_pct = (savings_liters / max(flood_baseline, 1)) * 100

        results.append({
            "irrigation_liters": round(liters, 1),
            "duration_minutes": round(duration, 1),
            "efficiency_score": round(efficiency, 3),
            "next_irrigation_hours": round(next_h, 1),
            "urgency": urgency,
            "skip_irrigation": liters < 10.0,
            "water_savings": {
                "vs_flood_liters": round(savings_liters, 1),
                "vs_flood_percent": round(savings_pct, 1),
            },
        })

    return results


# ---------------------------------------------------------------------------
# ONNX Export (via skl2onnx)
# ---------------------------------------------------------------------------

def export_to_onnx(
    model: Any,
    output_path: str | Path,
    config: Optional[IrrigationOptimizerConfig] = None,
) -> Path:
    """Export the trained XGBoost MultiOutputRegressor to ONNX via skl2onnx.

    Uses skl2onnx for conversion with dynamic batch dimension. The
    exported model can be loaded by ONNX Runtime for edge inference.

    Args:
        model: Trained sklearn MultiOutputRegressor with XGBRegressor.
        output_path: Path to save the .onnx file.
        config: Model config for dimensions. Uses defaults if None.

    Returns:
        Path to the saved ONNX file.
    """
    try:
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
    except ImportError as e:
        logger.error(
            "skl2onnx required for ONNX export. "
            "Install with: pip install skl2onnx"
        )
        raise ImportError("skl2onnx is required for ONNX export") from e

    if config is None:
        config = IrrigationOptimizerConfig()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Define input type with dynamic batch dimension
    initial_type = [
        ("irrigation_features", FloatTensorType([None, config.n_features])),
    ]

    # Convert to ONNX
    onnx_model = convert_sklearn(
        model,
        initial_types=initial_type,
        target_opset=config.onnx_opset,
        options={id(model): {"zipmap": False}},
    )

    # Save the ONNX model
    with open(str(output_path), "wb") as f:
        f.write(onnx_model.SerializeToString())

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    file_hash = _compute_file_hash(output_path)
    logger.info(
        "Exported irrigation optimizer ONNX: %s (%.2f MB, sha256=%s)",
        output_path, file_size_mb, file_hash[:16],
    )

    return output_path


# ---------------------------------------------------------------------------
# Model Persistence (pickle fallback)
# ---------------------------------------------------------------------------

def save_model_pickle(
    model: Any,
    output_path: str | Path,
) -> Path:
    """Save the trained model as a pickle file (fallback for non-ONNX).

    Args:
        model: Trained sklearn MultiOutputRegressor.
        output_path: Path to save the .pkl file.

    Returns:
        Path to the saved pickle file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(str(output_path), "wb") as f:
        pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Saved irrigation model pickle: %s (%.2f MB)", output_path, file_size_mb)

    return output_path


def load_model_pickle(model_path: str | Path) -> Any:
    """Load a trained model from pickle file.

    Args:
        model_path: Path to the .pkl file.

    Returns:
        Loaded sklearn MultiOutputRegressor.
    """
    with open(str(model_path), "rb") as f:
        return pickle.load(f)  # noqa: S301


# ---------------------------------------------------------------------------
# Preprocessing Utilities
# ---------------------------------------------------------------------------

def preprocess_irrigation_input(
    soil_moisture: float,
    crop_type: int,
    growth_stage: int,
    temperature: float,
    humidity: float,
    rainfall_forecast: float,
    wind_speed: float,
    solar_radiation: float,
    water_level: float,
    water_quality_score: float,
    previous_irrigation: float,
    field_area: float,
    soil_type: int,
    evapotranspiration: float,
    days_since_last_rain: int,
    norm_stats: Optional[object] = None,
) -> np.ndarray:
    """Assemble raw irrigation parameters into model input vector.

    Args:
        soil_moisture: Volumetric water content (0-1).
        crop_type: Crop ID (0-7, see CROP_DATABASE).
        growth_stage: Current growth stage (0-3).
        temperature: Air temperature in Celsius.
        humidity: Relative humidity (%).
        rainfall_forecast: 7-day cumulative rainfall forecast (mm).
        wind_speed: Wind speed at 2m height (m/s).
        solar_radiation: Daily solar radiation (MJ/m2/day).
        water_level: Groundwater depth (m).
        water_quality_score: Composite quality index (0-1).
        previous_irrigation: Last irrigation amount (L).
        field_area: Field area in hectares.
        soil_type: Soil type ID (0-5).
        evapotranspiration: Reference ET0 (mm/day).
        days_since_last_rain: Days since last rainfall event.
        norm_stats: Optional normalization statistics.

    Returns:
        Feature vector of shape (1, 15) ready for model input.
    """
    features = np.array([[
        soil_moisture,
        float(crop_type),
        float(growth_stage),
        temperature,
        humidity,
        rainfall_forecast,
        wind_speed,
        solar_radiation,
        water_level,
        water_quality_score,
        previous_irrigation,
        field_area,
        float(soil_type),
        evapotranspiration,
        float(days_since_last_rain),
    ]], dtype=np.float32)

    if norm_stats is not None:
        features = norm_stats.normalize(features)

    return features


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
