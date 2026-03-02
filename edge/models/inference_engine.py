"""Async ONNX inference engine for JalNetra edge gateway.

Manages all three ML models (anomaly detector, depletion predictor,
irrigation optimizer) and provides async wrappers for CPU-bound inference.
Falls back gracefully when model files or onnxruntime are unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from edge.config import settings

logger = logging.getLogger("jalnetra.inference")


class AsyncInferenceEngine:
    """Load and run ONNX models with async wrappers."""

    def __init__(self) -> None:
        self._anomaly_session: Any | None = None
        self._depletion_session: Any | None = None
        self._irrigation_session: Any | None = None
        self._loaded = False
        self._latency_history: dict[str, list[float]] = {
            "anomaly": [],
            "depletion": [],
            "irrigation": [],
        }

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    async def load_models(self, model_dir: Path | None = None) -> None:
        """Load all ONNX models in a thread executor (non-blocking)."""
        directory = model_dir or settings.jalnetra_model_dir
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_load, directory)

    def _sync_load(self, model_dir: Path) -> None:
        """Synchronous model loading (runs in executor)."""
        try:
            import onnxruntime as ort
        except ImportError:
            logger.warning("onnxruntime not installed — inference disabled")
            return

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1

        providers = ["CPUExecutionProvider"]
        # Try AMD Vitis AI EP first if available
        if "VitisAIExecutionProvider" in ort.get_available_providers():
            providers.insert(0, "VitisAIExecutionProvider")
            logger.info("AMD XDNA NPU detected — using VitisAI EP")

        for name, filename, attr in [
            ("anomaly", settings.anomaly_model_file, "_anomaly_session"),
            ("depletion", settings.depletion_model_file, "_depletion_session"),
            ("irrigation", settings.irrigation_model_file, "_irrigation_session"),
        ]:
            path = model_dir / filename
            if path.exists():
                try:
                    session = ort.InferenceSession(str(path), opts, providers=providers)
                    setattr(self, attr, session)
                    logger.info("Loaded %s model: %s (%.1f KB)", name, path.name, path.stat().st_size / 1024)
                except Exception:
                    logger.exception("Failed to load %s model from %s", name, path)
            else:
                logger.warning("Model file not found: %s", path)

        self._loaded = any([self._anomaly_session, self._depletion_session, self._irrigation_session])

    def _track_latency(self, model_name: str, elapsed_ms: float) -> None:
        history = self._latency_history[model_name]
        history.append(elapsed_ms)
        if len(history) > 1000:
            del history[:500]

    def get_latency_stats(self) -> dict[str, dict[str, float]]:
        """Get latency statistics per model."""
        stats = {}
        for name, history in self._latency_history.items():
            if history:
                arr = np.array(history)
                stats[name] = {
                    "count": len(history),
                    "mean_ms": float(np.mean(arr)),
                    "p50_ms": float(np.median(arr)),
                    "p95_ms": float(np.percentile(arr, 95)),
                    "p99_ms": float(np.percentile(arr, 99)),
                    "max_ms": float(np.max(arr)),
                }
            else:
                stats[name] = {"count": 0}
        return stats

    async def predict_anomaly(
        self,
        features: np.ndarray,
    ) -> dict[str, Any] | None:
        """Run anomaly detection on sensor features.

        Args:
            features: Shape (1, 10) — [tds, ph, turbidity, do, flow_rate,
                      water_level, tds_rate, ph_rate, hour_sin, hour_cos]

        Returns:
            Dict with class probabilities and predicted label, or None.
        """
        if self._anomaly_session is None:
            return None

        features = np.asarray(features, dtype=np.float32).reshape(1, -1)

        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        outputs = await loop.run_in_executor(
            None,
            lambda: self._anomaly_session.run(None, {"input": features}),
        )
        elapsed = (time.perf_counter() - start) * 1000
        self._track_latency("anomaly", elapsed)

        probs = _softmax(outputs[0][0])
        labels = ["normal", "contamination", "sensor_fault"]
        predicted_idx = int(np.argmax(probs))

        return {
            "label": labels[predicted_idx],
            "confidence": float(probs[predicted_idx]),
            "probabilities": {label: float(p) for label, p in zip(labels, probs)},
            "latency_ms": round(elapsed, 2),
        }

    async def predict_depletion(
        self,
        sequence: np.ndarray,
    ) -> dict[str, Any] | None:
        """Run groundwater depletion prediction.

        Args:
            sequence: Shape (1, 90, 7) — 90-day lookback of
                      [water_level, rainfall, extraction, temp, humidity, day_sin, day_cos]

        Returns:
            Dict with 30-day forecast and metadata, or None.
        """
        if self._depletion_session is None:
            return None

        sequence = np.asarray(sequence, dtype=np.float32)
        if sequence.ndim == 2:
            sequence = sequence.reshape(1, *sequence.shape)

        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        outputs = await loop.run_in_executor(
            None,
            lambda: self._depletion_session.run(None, {"input": sequence}),
        )
        elapsed = (time.perf_counter() - start) * 1000
        self._track_latency("depletion", elapsed)

        forecast = outputs[0][0].tolist()
        current_level = float(sequence[0, -1, 0])
        min_predicted = min(forecast)
        trend = "declining" if forecast[-1] > current_level else "stable"

        return {
            "forecast_30d": [round(v, 2) for v in forecast],
            "current_level_m": round(current_level, 2),
            "min_predicted_m": round(min_predicted, 2),
            "trend": trend,
            "days_to_critical": _days_to_critical(forecast, threshold=settings.groundwater_critical_level_m),
            "latency_ms": round(elapsed, 2),
        }

    async def optimize_irrigation(
        self,
        features: np.ndarray,
    ) -> dict[str, Any] | None:
        """Run irrigation optimization.

        Args:
            features: Shape (1, 15) — irrigation context features.

        Returns:
            Dict with irrigation recommendations, or None.
        """
        if self._irrigation_session is None:
            return None

        features = np.asarray(features, dtype=np.float32).reshape(1, -1)

        loop = asyncio.get_running_loop()
        start = time.perf_counter()
        outputs = await loop.run_in_executor(
            None,
            lambda: self._irrigation_session.run(None, {"X": features}),
        )
        elapsed = (time.perf_counter() - start) * 1000
        self._track_latency("irrigation", elapsed)

        result = outputs[0][0]
        return {
            "irrigation_liters": round(float(max(0, result[0])), 1),
            "duration_minutes": round(float(max(0, result[1])), 0),
            "efficiency_score": round(float(np.clip(result[2], 0, 100)), 1),
            "next_irrigation_hours": round(float(max(4, result[3])), 1),
            "latency_ms": round(elapsed, 2),
        }

    async def close(self) -> None:
        """Release model sessions."""
        self._anomaly_session = None
        self._depletion_session = None
        self._irrigation_session = None
        self._loaded = False
        logger.info("Inference engine closed")


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def _days_to_critical(forecast: list[float], threshold: float) -> int | None:
    """Estimate days until water level drops below critical threshold."""
    for i, level in enumerate(forecast):
        if level <= threshold:
            return i + 1
    return None
