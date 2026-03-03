"""
JalNetra — Async Inference Engine for ONNX Models on CPU/NPU
=============================================================

Manages all three JalNetra ML models (anomaly detector, depletion predictor,
irrigation optimizer) and provides async wrappers for CPU-bound ONNX Runtime
inference via asyncio.to_thread.

Features:
    - Loads all 3 ONNX models from a configurable directory
    - predict_anomaly: water quality anomaly classification
    - predict_depletion: 30-day groundwater level forecast
    - optimize_irrigation: crop-specific irrigation scheduling
    - Uses asyncio.to_thread for non-blocking CPU-bound inference
    - Per-model latency tracking with percentile statistics
    - Graceful fallback if model files do not exist (returns None/defaults)
    - AMD XDNA NPU support via Vitis AI Execution Provider

Author: JalNetra / dmj.one
License: MIT
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("jalnetra.inference")

# Default model file names
DEFAULT_ANOMALY_MODEL = "anomaly_detector.onnx"
DEFAULT_DEPLETION_MODEL = "depletion_predictor.onnx"
DEFAULT_IRRIGATION_MODEL = "irrigation_optimizer.onnx"
DEFAULT_MODEL_DIR = Path(__file__).parent / "weights"


class AsyncInferenceEngine:
    """Async ONNX Runtime inference engine for all JalNetra ML models.

    Loads anomaly detection, depletion prediction, and irrigation optimization
    ONNX models. All inference methods are async, using asyncio.to_thread to
    offload CPU-bound ONNX Runtime calls without blocking the event loop.

    If a model file does not exist or onnxruntime is not installed, the
    corresponding predict method returns None gracefully.
    """

    def __init__(
        self,
        model_dir: Optional[str | Path] = None,
        anomaly_model_file: str = DEFAULT_ANOMALY_MODEL,
        depletion_model_file: str = DEFAULT_DEPLETION_MODEL,
        irrigation_model_file: str = DEFAULT_IRRIGATION_MODEL,
    ) -> None:
        """Initialize the inference engine.

        Args:
            model_dir: Directory containing ONNX model files. Defaults to
                       edge/models/weights/.
            anomaly_model_file: Filename for the anomaly detector ONNX model.
            depletion_model_file: Filename for the depletion predictor ONNX model.
            irrigation_model_file: Filename for the irrigation optimizer ONNX model.
        """
        self._model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
        self._anomaly_file = anomaly_model_file
        self._depletion_file = depletion_model_file
        self._irrigation_file = irrigation_model_file

        self._anomaly_session: Any = None
        self._depletion_session: Any = None
        self._irrigation_session: Any = None
        self._loaded = False

        self._latency_history: dict[str, list[float]] = {
            "anomaly": [],
            "depletion": [],
            "irrigation": [],
        }

    @property
    def is_loaded(self) -> bool:
        """Whether at least one model has been successfully loaded."""
        return self._loaded

    # ------------------------------------------------------------------
    # Model Loading
    # ------------------------------------------------------------------

    async def load_models(self, model_dir: Optional[Path] = None) -> None:
        """Load all 3 ONNX models asynchronously via asyncio.to_thread.

        Non-blocking model loading suitable for use during application
        startup. Falls back gracefully if model files are missing.

        Args:
            model_dir: Override model directory. Uses constructor default
                       if None.
        """
        directory = model_dir or self._model_dir
        await asyncio.to_thread(self._sync_load, directory)

    def _sync_load(self, model_dir: Path) -> None:
        """Synchronous model loading (runs inside asyncio.to_thread)."""
        try:
            import onnxruntime as ort
        except ImportError:
            logger.warning(
                "onnxruntime not installed -- inference disabled. "
                "Install with: pip install onnxruntime"
            )
            return

        # Configure ONNX Runtime session options
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1

        # Select execution providers: prefer AMD Vitis AI NPU, fallback to CPU
        providers = ["CPUExecutionProvider"]
        available = ort.get_available_providers()
        if "VitisAIExecutionProvider" in available:
            providers.insert(0, "VitisAIExecutionProvider")
            logger.info("AMD XDNA NPU detected -- using VitisAI Execution Provider")

        # Load each model with graceful fallback
        model_specs = [
            ("anomaly", self._anomaly_file, "_anomaly_session"),
            ("depletion", self._depletion_file, "_depletion_session"),
            ("irrigation", self._irrigation_file, "_irrigation_session"),
        ]

        for name, filename, attr in model_specs:
            path = model_dir / filename
            if not path.exists():
                logger.warning("Model file not found, skipping: %s", path)
                continue
            try:
                session = ort.InferenceSession(
                    str(path), opts, providers=providers,
                )
                setattr(self, attr, session)
                size_kb = path.stat().st_size / 1024
                logger.info(
                    "Loaded %s model: %s (%.1f KB)", name, path.name, size_kb,
                )
            except Exception:
                logger.exception("Failed to load %s model from %s", name, path)

        self._loaded = any([
            self._anomaly_session,
            self._depletion_session,
            self._irrigation_session,
        ])

        if self._loaded:
            logger.info("Inference engine ready (model_dir=%s)", model_dir)
        else:
            logger.warning("No models loaded -- all predict methods will return None")

    # ------------------------------------------------------------------
    # Latency Tracking
    # ------------------------------------------------------------------

    def _track_latency(self, model_name: str, elapsed_ms: float) -> None:
        """Record inference latency for a model."""
        history = self._latency_history[model_name]
        history.append(elapsed_ms)
        # Keep bounded history (rolling window of 1000 entries)
        if len(history) > 1000:
            del history[:500]

    def get_latency_stats(self) -> dict[str, dict[str, float]]:
        """Get latency statistics (mean, median, p95, p99, max) per model.

        Returns:
            Dictionary mapping model names to latency stat dictionaries.
        """
        stats: dict[str, dict[str, float]] = {}
        for name, history in self._latency_history.items():
            if history:
                arr = np.array(history)
                stats[name] = {
                    "count": float(len(history)),
                    "mean_ms": float(np.mean(arr)),
                    "p50_ms": float(np.median(arr)),
                    "p95_ms": float(np.percentile(arr, 95)),
                    "p99_ms": float(np.percentile(arr, 99)),
                    "max_ms": float(np.max(arr)),
                }
            else:
                stats[name] = {"count": 0}
        return stats

    # ------------------------------------------------------------------
    # Anomaly Detection Inference
    # ------------------------------------------------------------------

    async def predict_anomaly(
        self,
        features: np.ndarray,
    ) -> Optional[dict[str, Any]]:
        """Run water quality anomaly detection.

        Args:
            features: Sensor features of shape (1, 10) or (10,).
                      Order: [tds, ph, turbidity, dissolved_oxygen, flow_rate,
                              water_level, tds_rate, ph_rate, hour_sin, hour_cos]

        Returns:
            Dictionary with classification result and latency, or None if
            the anomaly model is not loaded.
        """
        if self._anomaly_session is None:
            return None

        features = np.asarray(features, dtype=np.float32).reshape(1, -1)

        # Get the model's expected input name
        input_name = self._anomaly_session.get_inputs()[0].name

        start = time.perf_counter()
        outputs = await asyncio.to_thread(
            self._anomaly_session.run,
            None,
            {input_name: features},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._track_latency("anomaly", elapsed_ms)

        probs = _softmax(outputs[0][0])
        labels = ["normal", "contamination", "sensor_fault"]
        predicted_idx = int(np.argmax(probs))

        return {
            "label": labels[predicted_idx],
            "is_anomaly": predicted_idx != 0,
            "confidence": float(probs[predicted_idx]),
            "probabilities": {
                label: float(p) for label, p in zip(labels, probs)
            },
            "latency_ms": round(elapsed_ms, 2),
        }

    # ------------------------------------------------------------------
    # Depletion Prediction Inference
    # ------------------------------------------------------------------

    async def predict_depletion(
        self,
        sequence: np.ndarray,
    ) -> Optional[dict[str, Any]]:
        """Run groundwater depletion prediction.

        Args:
            sequence: Historical data of shape (1, 90, 7) or (90, 7).
                      Features per timestep: [water_level, rainfall,
                      extraction_rate, temperature, humidity, day_sin, day_cos]

        Returns:
            Dictionary with 30-day forecast, trend analysis, and latency,
            or None if the depletion model is not loaded.
        """
        if self._depletion_session is None:
            return None

        sequence = np.asarray(sequence, dtype=np.float32)
        if sequence.ndim == 2:
            sequence = sequence.reshape(1, *sequence.shape)

        # Get the model's expected input name
        input_name = self._depletion_session.get_inputs()[0].name

        start = time.perf_counter()
        outputs = await asyncio.to_thread(
            self._depletion_session.run,
            None,
            {input_name: sequence},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._track_latency("depletion", elapsed_ms)

        forecast = outputs[0][0].tolist()
        current_level = float(sequence[0, -1, 0])
        min_predicted = min(forecast)
        max_predicted = max(forecast)

        # Trend analysis
        first_week_avg = float(np.mean(forecast[:7]))
        last_week_avg = float(np.mean(forecast[-7:]))
        level_change = last_week_avg - first_week_avg

        if level_change > 1.0:
            trend = "declining"       # depth increasing = water table dropping
        elif level_change < -1.0:
            trend = "recovering"      # depth decreasing = water table rising
        else:
            trend = "stable"

        return {
            "forecast_30d": [round(v, 2) for v in forecast],
            "current_level_m": round(current_level, 2),
            "min_predicted_m": round(min_predicted, 2),
            "max_predicted_m": round(max_predicted, 2),
            "trend": trend,
            "level_change_m": round(level_change, 2),
            "days_to_critical": _days_to_critical(forecast, threshold=5.0),
            "latency_ms": round(elapsed_ms, 2),
        }

    # ------------------------------------------------------------------
    # Irrigation Optimization Inference
    # ------------------------------------------------------------------

    async def optimize_irrigation(
        self,
        features: np.ndarray,
    ) -> Optional[dict[str, Any]]:
        """Run irrigation schedule optimization.

        Args:
            features: Irrigation context features of shape (1, 15) or (15,).
                      See irrigation_optimizer.FEATURE_NAMES for feature order.

        Returns:
            Dictionary with irrigation recommendations and latency,
            or None if the irrigation model is not loaded.
        """
        if self._irrigation_session is None:
            return None

        features = np.asarray(features, dtype=np.float32).reshape(1, -1)

        # Get the model's expected input name
        input_name = self._irrigation_session.get_inputs()[0].name

        start = time.perf_counter()
        outputs = await asyncio.to_thread(
            self._irrigation_session.run,
            None,
            {input_name: features},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._track_latency("irrigation", elapsed_ms)

        result = outputs[0][0]

        liters = float(max(0, result[0]))
        duration = float(max(0, result[1]))
        efficiency = float(np.clip(result[2], 0.0, 1.0))
        next_h = float(np.clip(result[3], 4.0, 336.0))

        # Determine urgency
        if next_h < 12:
            urgency = "immediate"
        elif next_h < 48:
            urgency = "soon"
        elif next_h < 168:
            urgency = "scheduled"
        else:
            urgency = "not_needed"

        return {
            "irrigation_liters": round(liters, 1),
            "duration_minutes": round(duration, 1),
            "efficiency_score": round(efficiency, 3),
            "next_irrigation_hours": round(next_h, 1),
            "urgency": urgency,
            "skip_irrigation": liters < 10.0,
            "latency_ms": round(elapsed_ms, 2),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Release all model sessions and reset state."""
        self._anomaly_session = None
        self._depletion_session = None
        self._irrigation_session = None
        self._loaded = False
        logger.info("Inference engine closed, all model sessions released")


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def _softmax(x: np.ndarray) -> np.ndarray:
    """Numerically stable softmax."""
    e = np.exp(x - np.max(x))
    return e / e.sum()


def _days_to_critical(
    forecast: list[float],
    threshold: float = 5.0,
) -> Optional[int]:
    """Estimate days until water level drops below critical threshold.

    Args:
        forecast: List of predicted water levels (depth in meters).
        threshold: Critical depth threshold in meters.

    Returns:
        Number of days until critical, or None if never reached.
    """
    for i, level in enumerate(forecast):
        if level <= threshold:
            return i + 1
    return None
