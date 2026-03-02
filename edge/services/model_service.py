"""ML model orchestration service.

Bridges the inference engine with the API layer. Processes new sensor
readings through anomaly detection, runs scheduled depletion predictions,
generates irrigation recommendations, and creates alerts when thresholds
are violated.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np

from edge.config import BIS_THRESHOLDS, AlertSeverity, settings
from edge.database import Database
from edge.models.inference_engine import AsyncInferenceEngine

logger = logging.getLogger("jalnetra.model_service")


class AsyncModelService:
    """Orchestrates ML inference and threshold-based alerting."""

    def __init__(self, db: Database, engine: AsyncInferenceEngine) -> None:
        self._db = db
        self._engine = engine
        self._prediction_task: asyncio.Task[None] | None = None

    async def start_background_tasks(self) -> None:
        """Start periodic prediction refresh."""
        self._prediction_task = asyncio.create_task(
            self._prediction_loop(), name="prediction-refresh"
        )

    async def stop(self) -> None:
        if self._prediction_task and not self._prediction_task.done():
            self._prediction_task.cancel()
            try:
                await self._prediction_task
            except asyncio.CancelledError:
                pass

    # --- Process new reading ---

    async def process_reading(
        self,
        reading: dict[str, Any],
    ) -> dict[str, Any]:
        """Run anomaly detection + threshold checks on a new reading.

        Returns enriched reading with anomaly info and any alerts created.
        """
        result: dict[str, Any] = {"alerts": []}

        # 1. BIS threshold checks (O(1) — constant time)
        threshold_alerts = self._check_thresholds(reading)
        for alert_info in threshold_alerts:
            alert = await self._db.insert_alert(
                node_id=reading.get("node_id", "unknown"),
                alert_type="threshold",
                severity=alert_info["severity"],
                message=alert_info["message"],
                reading_id=reading.get("id"),
            )
            result["alerts"].append(alert)

        # 2. ML anomaly detection
        if self._engine.is_loaded:
            features = self._extract_anomaly_features(reading)
            prediction = await self._engine.predict_anomaly(features)
            if prediction:
                result["anomaly"] = prediction
                if prediction["label"] != "normal" and prediction["confidence"] > 0.7:
                    alert = await self._db.insert_alert(
                        node_id=reading.get("node_id", "unknown"),
                        alert_type=prediction["label"],
                        severity="critical" if prediction["confidence"] > 0.9 else "warning",
                        message=f"ML anomaly detected: {prediction['label']} (confidence: {prediction['confidence']:.1%})",
                        confidence=prediction["confidence"],
                        reading_id=reading.get("id"),
                    )
                    result["alerts"].append(alert)

        return result

    def _check_thresholds(self, reading: dict[str, Any]) -> list[dict[str, str]]:
        """Check reading against BIS IS 10500:2012 thresholds. O(1) complexity."""
        alerts: list[dict[str, str]] = []

        tds = reading.get("tds")
        if tds is not None:
            if BIS_THRESHOLDS.tds.critical_max and tds > BIS_THRESHOLDS.tds.critical_max:
                alerts.append({
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"TDS {tds:.0f} ppm exceeds critical limit (>{BIS_THRESHOLDS.tds.critical_max} ppm)",
                })
            elif BIS_THRESHOLDS.tds.alert_max and tds > BIS_THRESHOLDS.tds.alert_max:
                alerts.append({
                    "severity": AlertSeverity.WARNING,
                    "message": f"TDS {tds:.0f} ppm exceeds acceptable limit (>{BIS_THRESHOLDS.tds.alert_max} ppm)",
                })

        ph = reading.get("ph")
        if ph is not None:
            bis = BIS_THRESHOLDS.ph
            if (bis.critical_min and ph < bis.critical_min) or (bis.critical_max and ph > bis.critical_max):
                alerts.append({
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"pH {ph:.1f} outside critical range ({bis.critical_min}-{bis.critical_max})",
                })
            elif (bis.alert_min and ph < bis.alert_min) or (bis.alert_max and ph > bis.alert_max):
                alerts.append({
                    "severity": AlertSeverity.WARNING,
                    "message": f"pH {ph:.1f} outside acceptable range ({bis.acceptable_min}-{bis.acceptable_max})",
                })

        turbidity = reading.get("turbidity")
        if turbidity is not None:
            if BIS_THRESHOLDS.turbidity.critical_max and turbidity > BIS_THRESHOLDS.turbidity.critical_max:
                alerts.append({
                    "severity": AlertSeverity.CRITICAL,
                    "message": f"Turbidity {turbidity:.1f} NTU exceeds critical limit (>{BIS_THRESHOLDS.turbidity.critical_max})",
                })
            elif BIS_THRESHOLDS.turbidity.alert_max and turbidity > BIS_THRESHOLDS.turbidity.alert_max:
                alerts.append({
                    "severity": AlertSeverity.WARNING,
                    "message": f"Turbidity {turbidity:.1f} NTU exceeds acceptable limit (>{BIS_THRESHOLDS.turbidity.alert_max})",
                })

        return alerts

    def _extract_anomaly_features(self, reading: dict[str, Any]) -> np.ndarray:
        """Extract 10 features for anomaly detector. O(1)."""
        now = datetime.now(timezone.utc)
        hour_rad = 2 * math.pi * now.hour / 24

        return np.array([
            reading.get("tds", 0),
            reading.get("ph", 7.0),
            reading.get("turbidity", 0),
            reading.get("dissolved_oxygen", 7.0),
            reading.get("flow_rate", 0),
            reading.get("water_level", 0),
            reading.get("tds_rate", 0),
            reading.get("ph_rate", 0),
            math.sin(hour_rad),
            math.cos(hour_rad),
        ], dtype=np.float32)

    # --- Depletion prediction ---

    async def run_depletion_prediction(self, node_id: str) -> dict[str, Any] | None:
        """Generate 30-day groundwater depletion forecast for a node."""
        if not self._engine.is_loaded:
            return None

        # Fetch last 90 days of readings
        readings = await self._db.list_readings(node_id=node_id, limit=90 * 48)
        if len(readings) < 10:
            return None

        # Build sequence (subsample to daily if needed)
        sequence = self._build_depletion_sequence(readings)
        if sequence is None:
            return None

        prediction = await self._engine.predict_depletion(sequence)
        if prediction:
            await self._db.insert_prediction(
                node_id=node_id,
                prediction_type="depletion",
                days_to_critical=prediction.get("days_to_critical"),
                trend=prediction.get("trend"),
                predicted_values=prediction.get("forecast_30d"),
                confidence=0.85,
            )
        return prediction

    def _build_depletion_sequence(self, readings: list[dict]) -> np.ndarray | None:
        """Build (1, 90, 7) input tensor from readings. O(n) where n = len(readings)."""
        if len(readings) < 90:
            # Pad with repetition if we don't have enough data
            while len(readings) < 90:
                readings = readings + readings[:1]
            readings = readings[:90]

        features = []
        for r in readings[:90]:
            ts = r.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                day_of_year = dt.timetuple().tm_yday
            except (ValueError, AttributeError):
                day_of_year = 180

            day_rad = 2 * math.pi * day_of_year / 365
            features.append([
                r.get("water_level", 10.0),
                0.0,  # rainfall placeholder
                0.0,  # extraction placeholder
                25.0,  # temperature placeholder
                60.0,  # humidity placeholder
                math.sin(day_rad),
                math.cos(day_rad),
            ])

        return np.array(features, dtype=np.float32).reshape(1, 90, 7)

    # --- Irrigation optimization ---

    async def generate_irrigation_schedule(
        self,
        node_id: str,
        crop_type: str = "wheat_rabi",
        soil_type: str = "loamy",
        field_area_ha: float = 1.0,
    ) -> dict[str, Any] | None:
        """Generate 7-day irrigation schedule."""
        if not self._engine.is_loaded:
            return None

        # Get latest reading for water conditions
        readings = await self._db.list_readings(node_id=node_id, limit=1)
        latest = readings[0] if readings else {}

        features = np.array([
            35.0,  # soil_moisture
            0,     # crop_type encoded
            0.5,   # growth_stage
            28.0,  # temperature
            55.0,  # humidity
            0.0,   # rainfall_forecast
            8.0,   # wind_speed
            5.5,   # solar_radiation
            latest.get("water_level", 10.0),
            80.0,  # water_quality_score
            200.0, # previous_irrigation
            field_area_ha,
            1,     # soil_type encoded
            4.0,   # evapotranspiration
            3,     # days_since_rain
        ], dtype=np.float32)

        result = await self._engine.optimize_irrigation(features)
        if result:
            # Store schedule
            from datetime import timedelta
            today = datetime.now(timezone.utc).date()
            for day_offset in range(7):
                schedule_date = (today + timedelta(days=day_offset)).isoformat()
                await self._db.insert_irrigation_schedule(
                    node_id=node_id,
                    schedule_date=schedule_date,
                    recommended_hours=result["duration_minutes"] / 60,
                    crop_type=crop_type,
                    water_saved_pct=result["efficiency_score"],
                )
        return result

    # --- Background prediction loop ---

    async def _prediction_loop(self) -> None:
        """Refresh predictions every 6 hours."""
        logger.info("Prediction refresh loop started")
        while True:
            try:
                await asyncio.sleep(6 * 3600)
                nodes = await self._db.list_nodes(status="active")
                for node in nodes:
                    try:
                        await self.run_depletion_prediction(node["id"])
                    except Exception:
                        logger.exception("Prediction failed for node %s", node["id"])
                logger.info("Prediction refresh complete for %d nodes", len(nodes))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Prediction loop error")
                await asyncio.sleep(60)
