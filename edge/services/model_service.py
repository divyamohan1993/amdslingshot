"""ML model orchestration service - bridges inference engine with API layer.

Orchestrates all ML inference operations for the JalNetra edge gateway:
  - Anomaly detection on each incoming sensor reading
  - BIS IS 10500:2012 threshold checking for immediate compliance alerts
  - Scheduled groundwater depletion forecasting (30-day horizon)
  - 7-day irrigation schedule generation with crop-specific optimization
  - Background tasks for periodic predictions across all active nodes
  - Integration with alert_dispatcher for anomaly -> alert pipeline

All operations are async and designed for the AMD Ryzen AI edge gateway
running ONNX models on XDNA NPU via Vitis AI Execution Provider.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import structlog

from edge.config import BIS_THRESHOLDS, AlertSeverity, settings
from edge.database import Database, db

logger = structlog.get_logger("jalnetra.model_service")


# ---------------------------------------------------------------------------
# BIS IS 10500:2012 threshold checking results
# ---------------------------------------------------------------------------

_ANOMALY_LABELS: dict[int, str] = {
    0: "normal",
    1: "contamination",
    2: "sensor_fault",
}


# ---------------------------------------------------------------------------
# AsyncModelService
# ---------------------------------------------------------------------------

class AsyncModelService:
    """Orchestrates ML inference and threshold-based alerting.

    Bridges the gap between raw sensor data, ML models, and the alert
    system. Processes every incoming reading through a multi-stage pipeline:

    1. BIS IS 10500:2012 threshold evaluation (constant-time)
    2. ML anomaly detection via 1D-CNN (ONNX on NPU)
    3. Alert creation and dispatch for violations
    4. Scheduled depletion forecasting via LSTM
    5. Irrigation optimization for crop-specific water savings

    Usage::

        service = AsyncModelService(database=db)
        await service.start()

        # Process each new reading through the full pipeline
        result = await service.process_reading(reading_dict)

        # Run on-demand predictions
        forecast = await service.run_depletion_prediction("JN-DL-001")
        schedule = await service.generate_irrigation_schedule("JN-DL-001")

        await service.stop()
    """

    # Prediction refresh interval (seconds)
    PREDICTION_INTERVAL_SEC: float = 6 * 3600  # 6 hours
    IRRIGATION_INTERVAL_SEC: float = 24 * 3600  # 24 hours

    # Anomaly confidence thresholds for alert generation
    ANOMALY_WARNING_THRESHOLD: float = 0.70
    ANOMALY_CRITICAL_THRESHOLD: float = 0.90

    def __init__(
        self,
        *,
        database: Database | None = None,
        alert_dispatcher: Any | None = None,
        websocket_manager: Any | None = None,
    ) -> None:
        self._db = database or db
        self._alert_dispatcher = alert_dispatcher
        self._ws_manager = websocket_manager

        # Inference engine (lazy-loaded to handle missing onnxruntime gracefully)
        self._engine: Any | None = None
        self._engine_loaded = False

        # Previous reading cache for rate-of-change features
        self._prev_readings: dict[str, dict[str, Any]] = {}

        # Background tasks
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Load models and start background prediction tasks."""
        if self._running:
            return
        self._running = True

        # Attempt to load inference engine
        await self._load_engine()

        # Start background tasks
        prediction_task = asyncio.create_task(
            self._depletion_prediction_loop(),
            name="model-depletion-predictions",
        )
        irrigation_task = asyncio.create_task(
            self._irrigation_schedule_loop(),
            name="model-irrigation-schedules",
        )
        self._tasks.extend([prediction_task, irrigation_task])

        await logger.ainfo(
            "Model service started",
            engine_loaded=self._engine_loaded,
            model_dir=str(settings.jalnetra_model_dir),
        )

    async def stop(self) -> None:
        """Cancel background tasks and release resources."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await logger.ainfo("Model service stopped")

    async def _load_engine(self) -> None:
        """Attempt to load the ONNX inference engine.

        Gracefully handles missing onnxruntime or model files so the
        service can still function with threshold-only checking.
        """
        try:
            from edge.models.inference_engine import AsyncInferenceEngine

            engine = AsyncInferenceEngine()
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, engine.load_models)
            self._engine = engine
            self._engine_loaded = True
            await logger.ainfo("ONNX inference engine loaded successfully")
        except ImportError:
            await logger.awarning(
                "Inference engine not available (missing onnxruntime or models). "
                "Falling back to threshold-only mode."
            )
        except Exception:
            await logger.aexception("Failed to load inference engine")

    # ------------------------------------------------------------------
    # Process reading - main pipeline
    # ------------------------------------------------------------------

    async def process_reading(
        self,
        reading: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the full inference pipeline on a new sensor reading.

        Pipeline stages:
        1. BIS IS 10500:2012 threshold evaluation
        2. ML anomaly detection (if engine loaded)
        3. Alert creation for any violations
        4. Alert dispatch (if dispatcher configured)

        Args:
            reading: Database reading dict with keys: id, node_id, tds, ph,
                     turbidity, flow_rate, water_level, battery_voltage, timestamp.

        Returns:
            Enriched result dict with:
              - alerts: list of created alert dicts
              - anomaly: ML anomaly detection result (if available)
              - thresholds: threshold evaluation details
        """
        node_id = reading.get("node_id", "unknown")
        result: dict[str, Any] = {
            "alerts": [],
            "anomaly": None,
            "thresholds": {},
        }

        # --- Stage 1: BIS IS 10500:2012 threshold checking ---
        threshold_alerts = self._check_bis_thresholds(reading)
        result["thresholds"] = {
            "violations": len(threshold_alerts),
            "details": threshold_alerts,
        }

        for alert_info in threshold_alerts:
            alert = await self._db.insert_alert(
                node_id=node_id,
                alert_type=alert_info["alert_type"],
                severity=alert_info["severity"],
                message=alert_info["message"],
                reading_id=reading.get("id"),
            )
            result["alerts"].append(alert)

            # Dispatch via alert_dispatcher if available
            await self._dispatch_alert(node_id, alert_info, alert)

        # --- Stage 2: ML anomaly detection ---
        if self._engine_loaded and self._engine is not None:
            try:
                features = self._extract_anomaly_features(reading, node_id)
                anomaly_result = await self._run_anomaly_detection(features)

                if anomaly_result:
                    result["anomaly"] = anomaly_result

                    # Create alert if anomaly confidence is high enough
                    if (
                        anomaly_result.get("label") != "normal"
                        and anomaly_result.get("confidence", 0) > self.ANOMALY_WARNING_THRESHOLD
                    ):
                        severity = (
                            AlertSeverity.CRITICAL
                            if anomaly_result["confidence"] > self.ANOMALY_CRITICAL_THRESHOLD
                            else AlertSeverity.WARNING
                        )
                        alert = await self._db.insert_alert(
                            node_id=node_id,
                            alert_type=f"ml_{anomaly_result['label']}",
                            severity=severity,
                            message=(
                                f"ML anomaly detected: {anomaly_result['label']} "
                                f"(confidence: {anomaly_result['confidence']:.1%})"
                            ),
                            confidence=anomaly_result["confidence"],
                            reading_id=reading.get("id"),
                        )
                        result["alerts"].append(alert)

                        await self._dispatch_alert(
                            node_id,
                            {
                                "alert_type": f"ml_{anomaly_result['label']}",
                                "severity": severity,
                                "message": alert.get("message", ""),
                            },
                            alert,
                        )
            except Exception:
                await logger.aexception(
                    "Anomaly detection failed",
                    node_id=node_id,
                    reading_id=reading.get("id"),
                )

        # Update previous reading cache for rate-of-change features
        self._prev_readings[node_id] = reading

        # Broadcast alert count via WebSocket if any triggered
        if result["alerts"] and self._ws_manager:
            for alert in result["alerts"]:
                try:
                    await self._ws_manager.broadcast_alert(
                        node_id=node_id,
                        severity=alert.get("severity", "info"),
                        message=alert.get("message", ""),
                        alert_id=alert.get("id"),
                    )
                except Exception:
                    pass

        await logger.ainfo(
            "Reading processed",
            node_id=node_id,
            reading_id=reading.get("id"),
            threshold_violations=len(threshold_alerts),
            anomaly=result["anomaly"].get("label") if result["anomaly"] else "skipped",
            alerts_created=len(result["alerts"]),
        )

        return result

    # ------------------------------------------------------------------
    # BIS IS 10500:2012 threshold checking
    # ------------------------------------------------------------------

    def _check_bis_thresholds(
        self, reading: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Check a reading against BIS IS 10500:2012 water quality thresholds.

        This is O(1) constant-time -- checks a fixed number of parameters
        against static threshold ranges defined in edge.config.BIS_THRESHOLDS.

        Returns a list of alert info dicts. Empty list = all parameters OK.
        """
        alerts: list[dict[str, Any]] = []
        th = BIS_THRESHOLDS

        # -- TDS (Total Dissolved Solids) --
        tds = reading.get("tds")
        if tds is not None:
            if th.tds.critical_max is not None and tds > th.tds.critical_max:
                alerts.append({
                    "alert_type": "tds_critical",
                    "severity": AlertSeverity.CRITICAL,
                    "message": (
                        f"TDS critically high: {tds:.0f} {th.tds.unit} "
                        f"(limit: {th.tds.critical_max} {th.tds.unit})"
                    ),
                    "parameter": "tds",
                    "value": tds,
                    "limit": th.tds.critical_max,
                })
            elif th.tds.alert_max is not None and tds > th.tds.alert_max:
                alerts.append({
                    "alert_type": "tds_warning",
                    "severity": AlertSeverity.WARNING,
                    "message": (
                        f"TDS above acceptable limit: {tds:.0f} {th.tds.unit} "
                        f"(limit: {th.tds.acceptable_max} {th.tds.unit})"
                    ),
                    "parameter": "tds",
                    "value": tds,
                    "limit": th.tds.acceptable_max,
                })

        # -- pH --
        ph = reading.get("ph")
        if ph is not None:
            bis_ph = th.ph
            if (
                (bis_ph.critical_min is not None and ph < bis_ph.critical_min)
                or (bis_ph.critical_max is not None and ph > bis_ph.critical_max)
            ):
                alerts.append({
                    "alert_type": "ph_critical",
                    "severity": AlertSeverity.CRITICAL,
                    "message": (
                        f"pH critically out of range: {ph:.2f} "
                        f"(safe range: {bis_ph.critical_min}-{bis_ph.critical_max})"
                    ),
                    "parameter": "ph",
                    "value": ph,
                })
            elif (
                (bis_ph.alert_min is not None and ph < bis_ph.alert_min)
                or (bis_ph.alert_max is not None and ph > bis_ph.alert_max)
            ):
                alerts.append({
                    "alert_type": "ph_warning",
                    "severity": AlertSeverity.WARNING,
                    "message": (
                        f"pH outside acceptable range: {ph:.2f} "
                        f"(acceptable: {bis_ph.acceptable_min}-{bis_ph.acceptable_max})"
                    ),
                    "parameter": "ph",
                    "value": ph,
                })

        # -- Turbidity --
        turbidity = reading.get("turbidity")
        if turbidity is not None:
            if th.turbidity.critical_max is not None and turbidity > th.turbidity.critical_max:
                alerts.append({
                    "alert_type": "turbidity_critical",
                    "severity": AlertSeverity.CRITICAL,
                    "message": (
                        f"Turbidity critically high: {turbidity:.1f} {th.turbidity.unit} "
                        f"(limit: {th.turbidity.critical_max} {th.turbidity.unit})"
                    ),
                    "parameter": "turbidity",
                    "value": turbidity,
                    "limit": th.turbidity.critical_max,
                })
            elif th.turbidity.alert_max is not None and turbidity > th.turbidity.alert_max:
                alerts.append({
                    "alert_type": "turbidity_warning",
                    "severity": AlertSeverity.WARNING,
                    "message": (
                        f"Turbidity above acceptable limit: {turbidity:.1f} {th.turbidity.unit} "
                        f"(limit: {th.turbidity.acceptable_max} {th.turbidity.unit})"
                    ),
                    "parameter": "turbidity",
                    "value": turbidity,
                    "limit": th.turbidity.acceptable_max,
                })

        # -- Dissolved Oxygen --
        do = reading.get("dissolved_oxygen")
        if do is not None:
            if th.dissolved_oxygen.critical_min is not None and do < th.dissolved_oxygen.critical_min:
                alerts.append({
                    "alert_type": "do_critical",
                    "severity": AlertSeverity.CRITICAL,
                    "message": (
                        f"Dissolved oxygen critically low: {do:.1f} {th.dissolved_oxygen.unit} "
                        f"(min: {th.dissolved_oxygen.critical_min} {th.dissolved_oxygen.unit})"
                    ),
                    "parameter": "dissolved_oxygen",
                    "value": do,
                    "limit": th.dissolved_oxygen.critical_min,
                })
            elif th.dissolved_oxygen.alert_min is not None and do < th.dissolved_oxygen.alert_min:
                alerts.append({
                    "alert_type": "do_warning",
                    "severity": AlertSeverity.WARNING,
                    "message": (
                        f"Dissolved oxygen below acceptable level: {do:.1f} {th.dissolved_oxygen.unit} "
                        f"(min: {th.dissolved_oxygen.acceptable_min} {th.dissolved_oxygen.unit})"
                    ),
                    "parameter": "dissolved_oxygen",
                    "value": do,
                    "limit": th.dissolved_oxygen.acceptable_min,
                })

        # -- Water level (depletion risk) --
        water_level = reading.get("water_level")
        if water_level is not None and water_level < settings.groundwater_critical_level_m:
            alerts.append({
                "alert_type": "water_level_critical",
                "severity": AlertSeverity.CRITICAL,
                "message": (
                    f"Groundwater level critically low: {water_level:.1f} m "
                    f"(threshold: {settings.groundwater_critical_level_m} m)"
                ),
                "parameter": "water_level",
                "value": water_level,
                "limit": settings.groundwater_critical_level_m,
            })

        return alerts

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def _extract_anomaly_features(
        self,
        reading: dict[str, Any],
        node_id: str,
    ) -> np.ndarray:
        """Extract 10 features for the anomaly detection 1D-CNN.

        Features match the model's expected input:
        [tds, ph, turbidity, dissolved_oxygen, flow_rate, water_level,
         tds_rate, ph_rate, hour_sin, hour_cos]

        O(1) constant time.
        """
        now = datetime.now(timezone.utc)
        hour_rad = 2 * math.pi * now.hour / 24

        # Compute rate-of-change features from previous reading
        prev = self._prev_readings.get(node_id, {})
        tds_rate = 0.0
        ph_rate = 0.0

        current_tds = reading.get("tds")
        prev_tds = prev.get("tds")
        if current_tds is not None and prev_tds is not None:
            # Rate per hour, assuming ~30s sampling interval
            tds_rate = (current_tds - prev_tds) * 120.0

        current_ph = reading.get("ph")
        prev_ph = prev.get("ph")
        if current_ph is not None and prev_ph is not None:
            ph_rate = (current_ph - prev_ph) * 120.0

        return np.array(
            [[
                reading.get("tds", 0.0),
                reading.get("ph", 7.0),
                reading.get("turbidity", 0.0),
                reading.get("dissolved_oxygen", 7.0),
                reading.get("flow_rate", 0.0),
                reading.get("water_level", 0.0),
                tds_rate,
                ph_rate,
                math.sin(hour_rad),
                math.cos(hour_rad),
            ]],
            dtype=np.float32,
        )

    async def _run_anomaly_detection(
        self, features: np.ndarray
    ) -> dict[str, Any] | None:
        """Run the anomaly detection model on extracted features.

        Returns a dict with label, confidence, and probabilities.
        """
        if self._engine is None:
            return None

        try:
            # Run inference (offloaded to executor for ONNX session)
            loop = asyncio.get_running_loop()
            probabilities = await loop.run_in_executor(
                None, self._engine.predict_anomaly, features
            )

            if probabilities is None:
                return None

            if isinstance(probabilities, np.ndarray):
                if probabilities.ndim == 2:
                    probs = probabilities[0]
                else:
                    probs = probabilities
            else:
                return None

            label_idx = int(np.argmax(probs))
            return {
                "label": _ANOMALY_LABELS.get(label_idx, "unknown"),
                "confidence": float(probs[label_idx]),
                "probabilities": {
                    "normal": float(probs[0]),
                    "contamination": float(probs[1]) if len(probs) > 1 else 0.0,
                    "sensor_fault": float(probs[2]) if len(probs) > 2 else 0.0,
                },
                "is_anomaly": label_idx != 0,
            }
        except Exception:
            await logger.aexception("Anomaly detection inference failed")
            return None

    # ------------------------------------------------------------------
    # Depletion prediction
    # ------------------------------------------------------------------

    async def run_depletion_prediction(
        self, node_id: str
    ) -> dict[str, Any] | None:
        """Generate a 30-day groundwater depletion forecast for a node.

        Fetches the last 90 days of water level readings, builds the
        input sequence, runs the LSTM depletion predictor, and stores
        the result in the predictions table.

        Args:
            node_id: Sensor node identifier.

        Returns:
            Prediction result dict, or None if insufficient data/engine.
        """
        if not self._engine_loaded or self._engine is None:
            await logger.adebug(
                "Skipping depletion prediction (engine not loaded)",
                node_id=node_id,
            )
            return None

        # Fetch last 90 days of readings
        readings = await self._db.list_readings(
            node_id=node_id,
            limit=90 * 48,  # ~48 readings/day at 30s intervals
        )

        if len(readings) < 10:
            await logger.adebug(
                "Insufficient readings for depletion prediction",
                node_id=node_id,
                reading_count=len(readings),
            )
            return None

        # Build input sequence
        sequence = self._build_depletion_sequence(readings)
        if sequence is None:
            return None

        try:
            # Run LSTM prediction
            loop = asyncio.get_running_loop()
            raw_prediction = await loop.run_in_executor(
                None, self._engine.predict_depletion, sequence
            )

            if raw_prediction is None:
                return None

            # Post-process into structured result
            if isinstance(raw_prediction, np.ndarray):
                predicted_levels = raw_prediction.flatten().tolist()
            elif isinstance(raw_prediction, dict):
                predicted_levels = raw_prediction.get("predicted_levels", [])
            else:
                predicted_levels = []

            # Compute days to critical
            days_to_critical = -1
            for i, level in enumerate(predicted_levels):
                if level < settings.groundwater_critical_level_m:
                    days_to_critical = i
                    break

            # Trend analysis
            if len(predicted_levels) >= 14:
                first_week = sum(predicted_levels[:7]) / 7
                last_week = sum(predicted_levels[-7:]) / 7
                change = last_week - first_week
                if change > 1.0:
                    trend = "declining"
                elif change < -1.0:
                    trend = "recovering"
                else:
                    trend = "stable"
            else:
                trend = "unknown"

            prediction = {
                "node_id": node_id,
                "predicted_levels": predicted_levels,
                "days_to_critical": days_to_critical,
                "trend": trend,
                "forecast_days": len(predicted_levels),
                "critical_threshold_m": settings.groundwater_critical_level_m,
            }

            # Store in DB
            await self._db.insert_prediction(
                node_id=node_id,
                prediction_type="depletion",
                days_to_critical=days_to_critical if days_to_critical >= 0 else None,
                trend=trend,
                predicted_values=predicted_levels,
                confidence=0.85,
            )

            # Alert if critical level predicted within 30 days
            if 0 <= days_to_critical <= 30:
                severity = (
                    AlertSeverity.CRITICAL if days_to_critical <= 7
                    else AlertSeverity.WARNING
                )
                alert = await self._db.insert_alert(
                    node_id=node_id,
                    alert_type="depletion_warning",
                    severity=severity,
                    message=(
                        f"Groundwater predicted to reach critical level in "
                        f"{days_to_critical} days (threshold: "
                        f"{settings.groundwater_critical_level_m}m)"
                    ),
                )
                await self._dispatch_alert(
                    node_id,
                    {"alert_type": "depletion_warning", "severity": severity},
                    alert,
                )

            await logger.ainfo(
                "Depletion prediction completed",
                node_id=node_id,
                days_to_critical=days_to_critical,
                trend=trend,
            )
            return prediction

        except Exception:
            await logger.aexception(
                "Depletion prediction failed", node_id=node_id
            )
            return None

    def _build_depletion_sequence(
        self, readings: list[dict[str, Any]]
    ) -> np.ndarray | None:
        """Build a (1, 90, 8) input tensor from historical readings.

        Features per timestep:
        [water_level, rainfall, extraction_rate, temperature,
         humidity, day_sin, day_cos, trend]
        """
        # Subsample to ~1 reading per day (take latest per day)
        daily_readings: dict[str, dict[str, Any]] = {}
        for r in readings:
            ts = r.get("timestamp", "")
            date_key = ts[:10] if len(ts) >= 10 else ts
            daily_readings[date_key] = r

        daily_list = list(daily_readings.values())

        # Need at least some data; pad if less than 90 days
        if len(daily_list) < 5:
            return None

        while len(daily_list) < 90:
            daily_list = daily_list + daily_list[:1]
        daily_list = daily_list[:90]

        features = []
        for i, r in enumerate(daily_list):
            ts = r.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                day_of_year = dt.timetuple().tm_yday
            except (ValueError, AttributeError):
                day_of_year = 180

            day_rad = 2 * math.pi * day_of_year / 365
            features.append([
                r.get("water_level", 10.0),
                0.0,  # rainfall (from external data if available)
                0.0,  # extraction rate (placeholder)
                25.0,  # temperature (from IMD if available)
                60.0,  # humidity (from IMD if available)
                math.sin(day_rad),
                math.cos(day_rad),
                i / 90.0,  # normalized trend indicator
            ])

        return np.array(features, dtype=np.float32).reshape(1, 90, 8)

    # ------------------------------------------------------------------
    # Irrigation schedule generation
    # ------------------------------------------------------------------

    async def generate_irrigation_schedule(
        self,
        node_id: str,
        *,
        crop_type: str = "wheat_rabi",
        soil_type: str = "alluvial",
        field_area_ha: float = 1.0,
        forecast_days: int = 7,
    ) -> dict[str, Any] | None:
        """Generate a 7-day irrigation schedule using the optimization model.

        Creates day-by-day recommendations including irrigation volume,
        duration, efficiency score, and next-irrigation timing based on
        current water conditions, crop type, and weather.

        Args:
            node_id: Sensor node identifier.
            crop_type: Crop identifier (from CROP_DATABASE).
            soil_type: Soil type identifier.
            field_area_ha: Field area in hectares.
            forecast_days: Number of days to schedule (default 7).

        Returns:
            Schedule dict with daily recommendations, or None if unavailable.
        """
        # Get latest readings for current water conditions
        readings = await self._db.list_readings(node_id=node_id, limit=1)
        latest = readings[0] if readings else {}

        # Crop type encoding (matching data_generator.py CROP_DATABASE)
        crop_encoding: dict[str, int] = {
            "rice_kharif": 0, "wheat_rabi": 1, "sugarcane": 2,
            "cotton": 3, "mustard_rabi": 4, "maize_kharif": 5,
            "groundnut": 6, "vegetables_mixed": 7,
        }
        soil_encoding: dict[str, int] = {
            "alluvial": 0, "black": 1, "red": 2,
            "laterite": 3, "sandy": 4, "clay": 5,
        }

        crop_id = crop_encoding.get(crop_type, 1)
        soil_id = soil_encoding.get(soil_type, 0)

        now = datetime.now(timezone.utc)
        today = now.date()
        schedule_days: list[dict[str, Any]] = []

        for day_offset in range(forecast_days):
            schedule_date = today + timedelta(days=day_offset)

            # Build feature vector for irrigation model (15 features)
            features = np.array(
                [[
                    0.30,  # soil_moisture (estimated)
                    float(crop_id),
                    min(day_offset / 30.0, 1.0) * 3,  # growth_stage approximation
                    28.0,  # temperature_c (from IMD if available)
                    55.0,  # humidity_pct
                    0.0,   # rainfall_forecast_mm
                    8.0,   # wind_speed_ms
                    5.5,   # solar_radiation_mj
                    latest.get("water_level", 10.0),
                    0.80,  # water_quality_score
                    200.0,  # previous_irrigation_L
                    field_area_ha,
                    float(soil_id),
                    4.0,   # evapotranspiration_mm
                    3.0,   # days_since_last_rain
                ]],
                dtype=np.float32,
            )

            # Run irrigation model if available
            if self._engine_loaded and self._engine is not None:
                try:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(
                        None, self._engine.optimize_irrigation, features
                    )
                    if result is not None:
                        if isinstance(result, np.ndarray):
                            result = result.flatten()
                            day_schedule = {
                                "date": schedule_date.isoformat(),
                                "irrigation_amount_liters": float(max(0, result[0])),
                                "duration_minutes": float(max(0, result[1])) if len(result) > 1 else 0.0,
                                "efficiency_score": float(min(1.0, max(0, result[2]))) if len(result) > 2 else 0.85,
                                "next_irrigation_hours": float(max(0, result[3])) if len(result) > 3 else 24.0,
                            }
                        elif isinstance(result, dict):
                            day_schedule = {
                                "date": schedule_date.isoformat(),
                                **result,
                            }
                        else:
                            continue
                        schedule_days.append(day_schedule)
                        continue
                except Exception:
                    await logger.aexception(
                        "Irrigation model inference failed",
                        node_id=node_id,
                        date=schedule_date.isoformat(),
                    )

            # Fallback: simple heuristic-based schedule
            schedule_days.append(
                self._heuristic_irrigation_schedule(
                    schedule_date, latest, crop_type, field_area_ha
                )
            )

        # Persist schedules to DB
        for day in schedule_days:
            await self._db.insert_irrigation_schedule(
                node_id=node_id,
                schedule_date=day["date"],
                recommended_hours=day.get("duration_minutes", 60.0) / 60.0,
                crop_type=crop_type,
                water_saved_pct=day.get("efficiency_score", 0.85) * 100,
            )

        schedule = {
            "node_id": node_id,
            "crop_type": crop_type,
            "soil_type": soil_type,
            "field_area_ha": field_area_ha,
            "forecast_days": forecast_days,
            "daily_schedule": schedule_days,
            "total_water_liters": sum(
                d.get("irrigation_amount_liters", 0) for d in schedule_days
            ),
            "avg_efficiency": (
                sum(d.get("efficiency_score", 0) for d in schedule_days)
                / max(len(schedule_days), 1)
            ),
            "generated_at": now.isoformat(),
        }

        await logger.ainfo(
            "Irrigation schedule generated",
            node_id=node_id,
            crop_type=crop_type,
            forecast_days=forecast_days,
            total_water_liters=schedule["total_water_liters"],
        )

        return schedule

    @staticmethod
    def _heuristic_irrigation_schedule(
        date: Any,
        latest_reading: dict[str, Any],
        crop_type: str,
        field_area_ha: float,
    ) -> dict[str, Any]:
        """Simple heuristic irrigation schedule when ML model is unavailable.

        Uses basic crop water requirement estimates from ICAR data.
        """
        # Base water need per hectare per day (liters)
        crop_water_need: dict[str, float] = {
            "rice_kharif": 8000.0,
            "wheat_rabi": 3000.0,
            "sugarcane": 10000.0,
            "cotton": 4500.0,
            "mustard_rabi": 2500.0,
            "maize_kharif": 3500.0,
            "groundnut": 3500.0,
            "vegetables_mixed": 3000.0,
        }

        base_need = crop_water_need.get(crop_type, 3000.0)
        water_level = latest_reading.get("water_level", 10.0)

        # Adjust for water availability
        if water_level < 5.0:
            efficiency_factor = 0.6  # Reduce irrigation when water is scarce
        elif water_level < 10.0:
            efficiency_factor = 0.8
        else:
            efficiency_factor = 1.0

        irrigation_amount = base_need * field_area_ha * efficiency_factor
        duration_minutes = irrigation_amount / 500.0  # ~500 L/min application rate

        return {
            "date": date.isoformat() if hasattr(date, "isoformat") else str(date),
            "irrigation_amount_liters": round(irrigation_amount, 1),
            "duration_minutes": round(min(duration_minutes, 480), 1),
            "efficiency_score": 0.80 * efficiency_factor,
            "next_irrigation_hours": 24.0,
            "method": "heuristic",
        }

    # ------------------------------------------------------------------
    # Alert dispatch integration
    # ------------------------------------------------------------------

    async def _dispatch_alert(
        self,
        node_id: str,
        alert_info: dict[str, Any],
        stored_alert: dict[str, Any],
    ) -> None:
        """Dispatch an alert through the alert_dispatcher if configured."""
        if self._alert_dispatcher is None:
            return

        try:
            from edge.services.alert_dispatcher import AlertSeverity as DispatchSeverity

            severity_str = alert_info.get("severity", "info")
            if isinstance(severity_str, str):
                severity_map = {
                    "info": DispatchSeverity.INFO,
                    "warning": DispatchSeverity.WARNING,
                    "critical": DispatchSeverity.CRITICAL,
                }
                dispatch_severity = severity_map.get(
                    severity_str.lower(), DispatchSeverity.INFO
                )
            else:
                dispatch_severity = DispatchSeverity.WARNING

            await self._alert_dispatcher.dispatch_alert(
                severity=dispatch_severity,
                alert_type=alert_info.get("alert_type", "unknown"),
                node_id=node_id,
                parameters={
                    "node_id": node_id,
                    "message": alert_info.get("message", ""),
                    "alert_db_id": stored_alert.get("id"),
                },
            )
        except Exception:
            await logger.adebug(
                "Alert dispatch skipped",
                node_id=node_id,
                reason="dispatcher not available or error",
            )

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    async def _depletion_prediction_loop(self) -> None:
        """Refresh depletion predictions for all active nodes periodically."""
        await logger.ainfo(
            "Depletion prediction loop started",
            interval_h=self.PREDICTION_INTERVAL_SEC / 3600,
        )
        while self._running:
            try:
                await asyncio.sleep(self.PREDICTION_INTERVAL_SEC)

                nodes = await self._db.list_nodes(status="active")
                success_count = 0
                error_count = 0

                for node in nodes:
                    try:
                        result = await self.run_depletion_prediction(node["id"])
                        if result is not None:
                            success_count += 1
                    except Exception:
                        error_count += 1
                        await logger.aexception(
                            "Depletion prediction failed for node",
                            node_id=node["id"],
                        )

                await logger.ainfo(
                    "Depletion prediction refresh complete",
                    total_nodes=len(nodes),
                    success=success_count,
                    errors=error_count,
                )
            except asyncio.CancelledError:
                break
            except Exception:
                await logger.aexception("Depletion prediction loop error")
                await asyncio.sleep(60)

    async def _irrigation_schedule_loop(self) -> None:
        """Generate fresh irrigation schedules daily for all active nodes."""
        await logger.ainfo(
            "Irrigation schedule loop started",
            interval_h=self.IRRIGATION_INTERVAL_SEC / 3600,
        )
        while self._running:
            try:
                await asyncio.sleep(self.IRRIGATION_INTERVAL_SEC)

                nodes = await self._db.list_nodes(status="active")
                for node in nodes:
                    try:
                        await self.generate_irrigation_schedule(node["id"])
                    except Exception:
                        await logger.aexception(
                            "Irrigation schedule generation failed",
                            node_id=node["id"],
                        )

                await logger.ainfo(
                    "Irrigation schedule refresh complete",
                    nodes_processed=len(nodes),
                )
            except asyncio.CancelledError:
                break
            except Exception:
                await logger.aexception("Irrigation schedule loop error")
                await asyncio.sleep(60)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        """Return current model service statistics."""
        return {
            "running": self._running,
            "engine_loaded": self._engine_loaded,
            "prev_readings_cached": len(self._prev_readings),
            "background_tasks": len(self._tasks),
            "prediction_interval_h": self.PREDICTION_INTERVAL_SEC / 3600,
            "irrigation_interval_h": self.IRRIGATION_INTERVAL_SEC / 3600,
        }
