# JalNetra — System Design Document
## Edge-AI Water Intelligence for Rural India
### AMD Slingshot 2026 | Theme: Sustainable AI & Green Tech
### Team: dmj.one | Divya Mohan, Kumkum Thakur

---

## Table of Contents

1. Executive Summary
2. Problem Statement
3. Solution Overview
4. System Architecture
5. Hardware Design
6. Software Architecture
7. AI/ML Pipeline
8. Data Sources & APIs
9. Communication Layer
10. Frontend & User Interfaces
11. Deployment & Infrastructure
12. Security & Privacy
13. Cost Analysis
14. Development Roadmap
15. Testing Strategy
16. Scalability Plan
17. AMD Technology Integration
18. Appendices

---

## 1. Executive Summary

JalNetra is an edge-AI water quality and quantity monitoring system designed for rural India. It combines low-cost IoT sensors with AMD Ryzen AI NPU inference to provide real-time water intelligence at the source — borewells, village handpumps, canals, and reservoir outlets — with zero dependency on cloud connectivity.

The system serves three user groups: farmers (irrigation optimization), gram panchayat officials (water quality compliance), and Jal Jeevan Mission administrators (district/state-level monitoring). Alerts are delivered via SMS, WhatsApp, and voice calls in 22 Indian languages using Bhashini API.

**Key metrics:**
- Sub-100ms inference latency on AMD XDNA NPU
- 5–15W edge device power consumption (solar-viable)
- INR 70,000 per village deployment (covers 5 water sources, 500–2000 people)
- 30–40% water savings through AI-optimized irrigation scheduling
- 24/7 continuous monitoring vs current manual testing (2–3 times/year)

---

## 2. Problem Statement

### 2.1 The Crisis

India's water crisis is the single largest infrastructure failure affecting the most human beings:

- **600M+ Indians** face high-to-extreme water stress
- **70% of surface water** is polluted; only 28% of sewage is treated before release
- **200,000+ deaths/year** from waterborne diseases
- **85%+ of freshwater** consumed by agriculture, mostly wasted through flood irrigation
- Groundwater tables are collapsing due to unregulated over-extraction
- Water pollution costs India **USD 6.7–7.7 billion/year** and causes 16% drop in downstream agricultural yields

### 2.2 The Monitoring Gap

The Jal Jeevan Mission (JJM) has installed **15 Cr+ tap connections** under Har Ghar Jal, but:

- **Zero real-time quality monitoring** at most endpoints
- Manual testing happens **2–3 times/year** at best
- Test results take **weeks** to reach decision-makers
- No contamination early-warning system exists
- Farmers have **no visibility** into groundwater levels until borewells run dry

### 2.3 Why Existing Solutions Fail

| Solution | Failure Mode |
|----------|-------------|
| Cloud-based IoT platforms (AWS IoT, Azure IoT) | Require continuous internet — rural India has intermittent 2G/3G at best |
| Lab-grade water testing equipment | Costs INR 2–10 lakh per unit; requires trained operators |
| Manual BIS-standard testing | Infrequent (quarterly), results delayed, no real-time alerts |
| Satellite-based remote sensing | Low resolution, no point-source monitoring, no water quality data |
| Existing smart water meters | Monitor flow only, not quality; designed for urban piped networks |

### 2.4 What JalNetra Solves Differently

Offline-first, solar-powered, on-device AI inference that works where there is no internet, no electricity grid, and no technical expertise. Costs less than a single manual testing cycle while providing 24/7 continuous monitoring.

---

## 3. Solution Overview

### 3.1 Core Capabilities

1. **Real-Time Water Quality Monitoring** — Continuous TDS, pH, turbidity, dissolved oxygen sensing with sub-second anomaly detection
2. **Groundwater Depletion Prediction** — Time-series models predict water table decline 3–6 months ahead
3. **AI-Optimized Irrigation Scheduling** — Crop-specific, soil-aware recommendations reducing water usage 30–40%
4. **Contamination Early Warning** — Instant alerts when quality parameters breach safety thresholds
5. **Multilingual Voice Alerts** — SMS, WhatsApp, and Bhashini TTS voice calls in 22 Indian languages
6. **JJM Compliance Dashboard** — District/state-level aggregation for government monitoring

### 3.2 User Personas

| Persona | Device | Key Actions |
|---------|--------|-------------|
| **Farmer** | Feature phone / basic smartphone | Receives voice/SMS irrigation schedule + contamination alerts |
| **Panchayat Official** | Tablet / smartphone | Views village dashboard, generates JJM compliance reports |
| **JJM District Officer** | Desktop / laptop | Monitors all villages in district, identifies risk zones, exports reports |
| **Field Technician** | Smartphone | Receives maintenance alerts, performs sensor calibration |

---

## 4. System Architecture

### 4.1 Three-Tier Edge-Cloud Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  TIER 1: SENSOR NODES (Per Water Source)                            │
│  ESP32-S3 + LoRa + Sensors → Readings every 30s                    │
│  Power: Battery + Solar (5W panel)                                  │
│  Range: 2–5 km LoRa to Edge Gateway                                │
│  Qty: 5–20 per village                                              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ LoRa (no WiFi/cellular needed)
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TIER 2: EDGE GATEWAY (Per Village)                                 │
│  AMD Ryzen AI Mini-PC (XDNA NPU)                                   │
│  ├── ONNX Runtime + Vitis AI EP (inference)                         │
│  ├── FastAPI server (local API)                                     │
│  ├── SQLite (local storage)                                         │
│  ├── Alert engine (SMS/WhatsApp/Voice)                              │
│  └── React PWA (offline dashboard)                                  │
│  Power: Solar (50W panel + 12V 20Ah battery)                        │
│  Connectivity: Opportunistic 4G when available                      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ Batch sync (when connectivity available)
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TIER 3: CLOUD BACKEND (District/State)                             │
│  GCP Cloud Run (serverless) + BigQuery + Cloud Storage              │
│  ├── Aggregation dashboard (React SPA)                              │
│  ├── Model training pipeline (AMD Developer Cloud MI300X)           │
│  └── Feedback loop for model improvement                            │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Data Flow

```
Sensor Reading (30s interval)
    │
    ▼
ESP32-S3 collects + validates raw ADC values
    │
    ▼
LoRa packet → Edge Gateway LoRa receiver
    │
    ▼
Pre-processing: calibration curves, unit conversion, outlier filtering
    │
    ▼
Feature extraction: rolling averages, rate of change, seasonal adjustment
    │
    ├──► Anomaly Detection Model (ONNX on NPU) → Alert if anomaly
    │
    ├──► Depletion Prediction Model (ONNX on NPU) → Updated forecast
    │
    └──► Irrigation Optimizer (rule-based + ML hybrid) → Schedule update
         │
         ▼
    SQLite insert (local persistence)
         │
         ├──► Dashboard update (WebSocket to PWA)
         │
         ├──► Alert dispatch (if threshold breached)
         │    ├── SMS via MSG91
         │    ├── WhatsApp via Business API
         │    └── Voice call via Bhashini TTS
         │
         └──► Cloud sync queue (deferred until connectivity)
```

---

## 5. Hardware Design

### 5.1 Sensor Node (Tier 1)

**Bill of Materials — Per Node**

| Component | Model | Specification | Cost (INR) | Source |
|-----------|-------|---------------|------------|--------|
| Microcontroller | Heltec WiFi LoRa 32 V3 | ESP32-S3 + SX1262 LoRa + OLED | 1,200 | Robocraze |
| TDS/EC Sensor | DFRobot SEN0244 | Analog, 0–1000 ppm, ±10% | 450 | Amazon.in |
| pH Sensor | DFRobot SEN0161-V2 | Analog, 0–14 pH, ±0.1 | 800 | Robocraze |
| Turbidity Sensor | DFRobot SEN0189 | Analog, 0–3000 NTU | 350 | Amazon.in |
| Flow Meter | YF-S201 | Hall effect, 1–30 L/min | 200 | Amazon.in |
| Ultrasonic Level | JSN-SR04T | Waterproof, 25–450 cm, ±1 cm | 350 | Amazon.in |
| Solar Panel | 6V 3.5W mini panel | Polycrystalline, weatherproof | 250 | Amazon.in |
| Battery | 18650 Li-ion 3.7V 3400mAh x2 | With TP4056 charge controller | 300 | Amazon.in |
| Enclosure | IP67 ABS junction box | 200x120x75mm, cable glands | 250 | Amazon.in |
| Miscellaneous | Wiring, connectors, PCB | Custom PCB via JLCPCB | 150 | JLCPCB |
| **Total per node** | | | **~4,300** | |

**Sensor Node Firmware (ESP32-S3)**

```
Language: C++ (Arduino framework / ESP-IDF)
IDE: PlatformIO
Key libraries:
  - RadioLib (SX1262 LoRa driver)
  - ArduinoJson (payload serialization)
  - ESP32 ADC calibration API
  
Sampling: 30-second intervals (configurable)
Sleep: Deep sleep between readings (~10µA)
Battery life: 6+ months with solar (calculated)
LoRa config: SF7, BW 125kHz, CR 4/5, 868 MHz ISM band (India)
Payload: 32-byte packed binary (sensor ID + 5 readings + timestamp + battery voltage + checksum)
```

**Sensor Node — Firmware Architecture**

```
main.cpp
├── setup()
│   ├── init_sensors()        // Calibrate ADC, warm up pH probe
│   ├── init_lora()           // SX1262 config: freq, SF, BW, TX power
│   └── init_power()          // Solar charge controller, battery monitor
│
├── loop()
│   ├── read_all_sensors()    // TDS, pH, turbidity, flow, level
│   ├── validate_readings()   // Range checks, stuck sensor detection
│   ├── pack_payload()        // 32-byte binary: [nodeID|tds|ph|turb|flow|level|ts|batt|crc]
│   ├── lora_transmit()       // Send to edge gateway, wait for ACK
│   └── deep_sleep(30000)     // 30s sleep, RTC wakeup
│
├── sensors/
│   ├── tds_sensor.h          // ADC → ppm conversion with temperature compensation
│   ├── ph_sensor.h           // ADC → pH with 2-point calibration (4.0 and 7.0 buffers)
│   ├── turbidity_sensor.h    // ADC → NTU lookup table
│   ├── flow_sensor.h         // Pulse counting ISR → L/min
│   └── level_sensor.h        // Ultrasonic ping → cm water depth
│
└── config.h                  // Node ID, LoRa params, calibration offsets, thresholds
```

### 5.2 Edge Gateway (Tier 2)

**Primary Hardware: AMD Ryzen AI Mini-PC**

| Component | Specification | Notes |
|-----------|---------------|-------|
| CPU/NPU | AMD Ryzen 7 7840HS or Ryzen 9 7940HS | XDNA NPU (10–16 TOPS) |
| RAM | 16 GB DDR5 | Sufficient for model + FastAPI + SQLite |
| Storage | 512 GB NVMe SSD | Years of local data retention |
| Form Factor | MinisForum UM790 Pro or equivalent | ~0.5L volume, fanless options available |
| LoRa Receiver | Heltec WiFi LoRa 32 V3 (USB-serial) | Connected via USB to mini-PC |
| 4G Modem | Quectel EC25 Mini PCIe (optional) | For opportunistic cloud sync |
| Power | 12V DC input, 15–45W TDP | Direct from solar charge controller |
| OS | Ubuntu 22.04 LTS or Windows 11 | Ryzen AI SDK supports both |

**Power System — Edge Gateway**

| Component | Specification | Cost (INR) |
|-----------|---------------|------------|
| Solar Panel | 50W 12V monocrystalline | 2,500 |
| Charge Controller | 10A PWM, 12V | 500 |
| Battery | 12V 20Ah lead-acid (or LiFePO4) | 3,000 |
| Inverter | 12V DC → 19V DC (for mini-PC) | 800 |
| Enclosure | IP65 outdoor cabinet, ventilated | 1,500 |

**Power Budget Calculation:**
- Mini-PC average draw: 20W (inference bursts to 45W)
- LoRa receiver: 0.5W
- 4G modem (intermittent): 2W average
- Total: ~22.5W average
- 50W panel × 5 peak sun hours = 250Wh/day
- 22.5W × 24h = 540Wh/day (deficit)
- Solution: Duty cycle the mini-PC — active 12h/day, sleep with LoRa wake = 270Wh/day (viable with 20Ah battery buffer)
- Alternative: 100W panel (INR 4,500) for 24/7 operation

---

## 6. Software Architecture

### 6.1 Edge Gateway Software Stack

```
┌─────────────────────────────────────────┐
│  React PWA (Offline Dashboard)          │ ← Panchayat officials
│  Service Worker + IndexedDB cache       │
├─────────────────────────────────────────┤
│  FastAPI Server (Python 3.11)           │ ← REST API + WebSocket
│  ├── /api/v1/readings      (GET, POST) │
│  ├── /api/v1/alerts        (GET)       │
│  ├── /api/v1/irrigation    (GET)       │
│  ├── /api/v1/predictions   (GET)       │
│  ├── /api/v1/reports       (GET)       │
│  ├── /api/v1/sync          (POST)     │ ← Cloud sync trigger
│  └── /ws/live              (WebSocket) │ ← Real-time dashboard
├─────────────────────────────────────────┤
│  Inference Engine                       │
│  ├── ONNX Runtime 1.18+                │
│  ├── Vitis AI Execution Provider        │ ← Routes to XDNA NPU
│  ├── anomaly_detector.onnx (INT8, 8MB) │
│  ├── depletion_predictor.onnx (BF16, 25MB) │
│  └── irrigation_optimizer.onnx (INT8, 12MB) │
├─────────────────────────────────────────┤
│  Data Layer                             │
│  ├── SQLite 3 (readings, alerts, config)│
│  ├── Alembic (migrations)               │
│  └── SQLModel (ORM)                     │
├─────────────────────────────────────────┤
│  Alert Engine                           │
│  ├── MSG91 SMS API                      │
│  ├── WhatsApp Business API (Meta)       │
│  └── Bhashini TTS → Twilio Voice        │
├─────────────────────────────────────────┤
│  LoRa Receiver Daemon                   │
│  ├── Serial port listener (USB)         │
│  ├── Packet parser + CRC validation     │
│  └── Sensor data ingestion pipeline     │
├─────────────────────────────────────────┤
│  Cloud Sync Agent                       │
│  ├── Connectivity monitor               │
│  ├── Batch uploader (gzip + HTTPS)      │
│  └── Model update downloader            │
├─────────────────────────────────────────┤
│  OS: Ubuntu 22.04 LTS                   │
│  AMD Ryzen AI Software SDK 1.7          │
│  systemd services for all daemons       │
└─────────────────────────────────────────┘
```

### 6.2 Project Structure

```
jalnetra/
├── edge/                          # Edge gateway application
│   ├── pyproject.toml             # Python project config (uv/poetry)
│   ├── alembic/                   # Database migrations
│   │   ├── alembic.ini
│   │   └── versions/
│   ├── jalnetra/
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI app entry point
│   │   ├── config.py              # Pydantic settings (env-based)
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── readings.py        # Sensor readings endpoints
│   │   │   ├── alerts.py          # Alert management endpoints
│   │   │   ├── irrigation.py      # Irrigation schedule endpoints
│   │   │   ├── predictions.py     # Depletion prediction endpoints
│   │   │   ├── reports.py         # JJM compliance reports
│   │   │   ├── sync.py            # Cloud sync endpoints
│   │   │   └── websocket.py       # Live data WebSocket
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── reading.py         # SensorReading SQLModel
│   │   │   ├── alert.py           # Alert SQLModel
│   │   │   ├── node.py            # SensorNode SQLModel
│   │   │   ├── schedule.py        # IrrigationSchedule SQLModel
│   │   │   └── prediction.py      # DepletionPrediction SQLModel
│   │   ├── inference/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py          # ONNX Runtime session manager
│   │   │   ├── anomaly.py         # Anomaly detection pipeline
│   │   │   ├── depletion.py       # Groundwater depletion predictor
│   │   │   ├── irrigation.py      # Irrigation optimizer
│   │   │   └── preprocessor.py    # Feature engineering
│   │   ├── lora/
│   │   │   ├── __init__.py
│   │   │   ├── receiver.py        # Serial port LoRa listener
│   │   │   └── parser.py          # Binary packet parser
│   │   ├── alerts/
│   │   │   ├── __init__.py
│   │   │   ├── dispatcher.py      # Alert routing logic
│   │   │   ├── sms.py             # MSG91 SMS integration
│   │   │   ├── whatsapp.py        # WhatsApp Business API
│   │   │   ├── voice.py           # Bhashini TTS + Twilio voice
│   │   │   └── templates/         # Alert message templates (22 languages)
│   │   ├── sync/
│   │   │   ├── __init__.py
│   │   │   ├── uploader.py        # Batch data uploader
│   │   │   ├── downloader.py      # Model update downloader
│   │   │   └── connectivity.py    # Network status monitor
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── calibration.py     # Sensor calibration utilities
│   │       └── thresholds.py      # BIS/WHO water quality thresholds
│   ├── models_onnx/               # Pre-trained ONNX models
│   │   ├── anomaly_detector_int8.onnx
│   │   ├── depletion_predictor_bf16.onnx
│   │   └── irrigation_optimizer_int8.onnx
│   ├── tests/
│   │   ├── test_inference.py
│   │   ├── test_api.py
│   │   ├── test_lora.py
│   │   └── test_alerts.py
│   └── Dockerfile
│
├── firmware/                      # ESP32-S3 sensor node firmware
│   ├── platformio.ini
│   ├── src/
│   │   ├── main.cpp
│   │   ├── sensors/
│   │   │   ├── tds_sensor.h
│   │   │   ├── ph_sensor.h
│   │   │   ├── turbidity_sensor.h
│   │   │   ├── flow_sensor.h
│   │   │   └── level_sensor.h
│   │   ├── lora/
│   │   │   └── transmitter.h
│   │   ├── power/
│   │   │   └── sleep_manager.h
│   │   └── config.h
│   └── test/
│
├── dashboard/                     # React PWA dashboard
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── FarmerHome.tsx     # Simplified farmer view
│   │   │   ├── PanchayatDashboard.tsx
│   │   │   ├── NodeMap.tsx        # Map with sensor nodes
│   │   │   ├── AlertHistory.tsx
│   │   │   ├── IrrigationSchedule.tsx
│   │   │   ├── DepletionForecast.tsx
│   │   │   └── Reports.tsx
│   │   ├── components/
│   │   │   ├── WaterQualityCard.tsx
│   │   │   ├── SensorStatusBadge.tsx
│   │   │   ├── AlertBanner.tsx
│   │   │   ├── TrendChart.tsx
│   │   │   └── VoiceQueryButton.tsx  # Bhashini voice input
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   ├── useOfflineStorage.ts
│   │   │   └── useBhashini.ts
│   │   ├── services/
│   │   │   ├── api.ts
│   │   │   └── offlineSync.ts
│   │   └── sw.ts                  # Service worker for offline
│   └── public/
│
├── cloud/                         # Cloud backend (Tier 3)
│   ├── functions/                 # GCP Cloud Functions
│   │   ├── ingest/                # Receives batch syncs from edge
│   │   ├── aggregate/             # BigQuery aggregation jobs
│   │   └── notify/                # District-level alert escalation
│   ├── terraform/                 # Infrastructure as code
│   │   ├── main.tf
│   │   ├── bigquery.tf
│   │   ├── cloud_run.tf
│   │   └── variables.tf
│   └── dashboard/                 # District admin dashboard (Next.js)
│
├── training/                      # Model training pipeline
│   ├── notebooks/
│   │   ├── 01_data_collection.ipynb
│   │   ├── 02_anomaly_detection.ipynb
│   │   ├── 03_depletion_prediction.ipynb
│   │   ├── 04_irrigation_optimizer.ipynb
│   │   └── 05_quantization.ipynb
│   ├── scripts/
│   │   ├── train_anomaly.py
│   │   ├── train_depletion.py
│   │   ├── train_irrigation.py
│   │   ├── export_onnx.py
│   │   └── quantize_quark.py      # AMD Quark quantization
│   └── data/
│       └── README.md              # Data source documentation
│
├── deploy/
│   ├── autoconfig.sh              # Zero-intervention edge setup
│   ├── docker-compose.yml
│   └── systemd/
│       ├── jalnetra-api.service
│       ├── jalnetra-lora.service
│       ├── jalnetra-sync.service
│       └── jalnetra-alerts.service
│
├── docs/
│   ├── DESIGN.md                  # This document
│   ├── API.md                     # API reference
│   ├── SENSOR_CALIBRATION.md
│   └── DEPLOYMENT.md
│
├── CLAUDE.md
├── README.md
└── .env.example
```

### 6.3 Key Code — Inference Engine

```python
# jalnetra/inference/engine.py
import onnxruntime as ort
import numpy as np
from pathlib import Path
from jalnetra.config import settings

class InferenceEngine:
    """Manages ONNX Runtime sessions with Vitis AI EP for NPU inference."""
    
    def __init__(self):
        self.models = {}
        self._init_sessions()
    
    def _init_sessions(self):
        """Initialize ONNX Runtime sessions with AMD Vitis AI EP."""
        model_dir = Path(settings.MODEL_DIR)
        
        for model_name, model_file in [
            ("anomaly", "anomaly_detector_int8.onnx"),
            ("depletion", "depletion_predictor_bf16.onnx"),
            ("irrigation", "irrigation_optimizer_int8.onnx"),
        ]:
            session_options = ort.SessionOptions()
            session_options.log_severity_level = 3  # Errors only
            
            # Vitis AI EP options for AMD Ryzen AI NPU
            vai_ep_options = {
                "cache_dir": str(model_dir / "cache"),
                "cache_key": model_name,
                "target": "X2",  # STX/KRK NPU backend (XDNA)
            }
            
            try:
                session = ort.InferenceSession(
                    path_or_bytes=str(model_dir / model_file),
                    sess_options=session_options,
                    providers=["VitisAIExecutionProvider"],
                    provider_options=[vai_ep_options],
                )
                self.models[model_name] = session
                print(f"[NPU] Loaded {model_name} on Vitis AI EP")
            except Exception as e:
                # Fallback to CPU if NPU not available
                print(f"[CPU] Falling back for {model_name}: {e}")
                session = ort.InferenceSession(
                    str(model_dir / model_file),
                    providers=["CPUExecutionProvider"],
                )
                self.models[model_name] = session
    
    def detect_anomaly(self, features: np.ndarray) -> dict:
        """Run anomaly detection on sensor readings.
        
        Args:
            features: Shape (1, 10) — [tds, ph, turbidity, flow, level,
                      tds_rate, ph_rate, turb_rate, hour_of_day, day_of_year]
        
        Returns:
            {"is_anomaly": bool, "confidence": float, "anomaly_type": str}
        """
        session = self.models["anomaly"]
        input_name = session.get_inputs()[0].name
        result = session.run(None, {input_name: features.astype(np.float32)})
        
        probabilities = result[0][0]  # [normal, contamination, sensor_fault]
        anomaly_idx = np.argmax(probabilities)
        
        anomaly_types = ["normal", "contamination", "sensor_fault"]
        return {
            "is_anomaly": anomaly_idx != 0,
            "confidence": float(probabilities[anomaly_idx]),
            "anomaly_type": anomaly_types[anomaly_idx],
        }
    
    def predict_depletion(self, history: np.ndarray) -> dict:
        """Predict groundwater depletion trend.
        
        Args:
            history: Shape (1, 90, 3) — 90 days of [level, rainfall, extraction_rate]
        
        Returns:
            {"days_to_critical": int, "trend": str, "predicted_levels": list}
        """
        session = self.models["depletion"]
        input_name = session.get_inputs()[0].name
        result = session.run(None, {input_name: history.astype(np.float32)})
        
        predicted_levels = result[0][0].tolist()  # Next 30 days
        critical_level = 5.0  # meters — below this, borewell may fail
        
        days_to_critical = next(
            (i for i, level in enumerate(predicted_levels) if level < critical_level),
            -1  # -1 means safe for forecast period
        )
        
        trend = "declining" if predicted_levels[-1] < predicted_levels[0] else "stable"
        
        return {
            "days_to_critical": days_to_critical,
            "trend": trend,
            "predicted_levels": predicted_levels,
        }
    
    def optimize_irrigation(self, context: np.ndarray) -> dict:
        """Generate irrigation schedule.
        
        Args:
            context: Shape (1, 15) — [soil_moisture, crop_type, growth_stage,
                     temperature, humidity, rainfall_forecast_7d, water_level,
                     tds, ph, field_area, soil_type, ...]
        
        Returns:
            {"schedule": list, "water_saved_pct": float}
        """
        session = self.models["irrigation"]
        input_name = session.get_inputs()[0].name
        result = session.run(None, {input_name: context.astype(np.float32)})
        
        # Output: 7-day schedule [hours_per_day] + efficiency score
        schedule = result[0][0][:7].tolist()
        efficiency = float(result[0][0][7])
        
        return {
            "schedule": [
                {"day": i + 1, "hours": round(h, 1)} for i, h in enumerate(schedule)
            ],
            "water_saved_pct": round(efficiency * 100, 1),
        }

# Singleton
engine = InferenceEngine()
```

### 6.4 Key Code — LoRa Receiver

```python
# jalnetra/lora/receiver.py
import serial
import struct
import asyncio
from datetime import datetime, timezone
from jalnetra.lora.parser import parse_packet
from jalnetra.inference.engine import engine
from jalnetra.alerts.dispatcher import dispatch_alert
from jalnetra.models.reading import SensorReading
from jalnetra.config import settings

class LoRaReceiver:
    """Listens on serial port for LoRa packets from sensor nodes."""
    
    PACKET_SIZE = 32
    MAGIC_BYTE = 0xJN  # 0x4A4E
    
    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200):
        self.port = port
        self.baud = baud
        self.serial = None
    
    async def start(self):
        """Main receiver loop."""
        self.serial = serial.Serial(self.port, self.baud, timeout=1)
        print(f"[LoRa] Listening on {self.port}")
        
        while True:
            try:
                data = self.serial.read(self.PACKET_SIZE)
                if len(data) == self.PACKET_SIZE:
                    await self._process_packet(data)
            except serial.SerialException as e:
                print(f"[LoRa] Serial error: {e}, reconnecting...")
                await asyncio.sleep(5)
                self.serial = serial.Serial(self.port, self.baud, timeout=1)
    
    async def _process_packet(self, data: bytes):
        """Parse, validate, infer, and store a sensor packet."""
        packet = parse_packet(data)
        if packet is None:
            return  # CRC failed or invalid
        
        # Store reading
        reading = SensorReading(
            node_id=packet["node_id"],
            tds=packet["tds"],
            ph=packet["ph"],
            turbidity=packet["turbidity"],
            flow_rate=packet["flow"],
            water_level=packet["level"],
            battery_voltage=packet["battery"],
            timestamp=datetime.now(timezone.utc),
        )
        await reading.save()
        
        # Run anomaly detection
        features = reading.to_feature_vector()  # Shape (1, 10)
        anomaly_result = engine.detect_anomaly(features)
        
        if anomaly_result["is_anomaly"]:
            await dispatch_alert(
                node_id=packet["node_id"],
                alert_type=anomaly_result["anomaly_type"],
                confidence=anomaly_result["confidence"],
                reading=reading,
            )
```

### 6.5 Key Code — Alert Dispatcher with Bhashini

```python
# jalnetra/alerts/dispatcher.py
import httpx
from jalnetra.alerts.sms import send_sms
from jalnetra.alerts.whatsapp import send_whatsapp
from jalnetra.alerts.voice import make_voice_call
from jalnetra.config import settings

BHASHINI_API = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"

ALERT_TEMPLATES = {
    "contamination": {
        "en": "ALERT: Water contamination detected at {source}. TDS: {tds} ppm, pH: {ph}. Do NOT drink until cleared. Contact gram panchayat.",
        "hi": "चेतावनी: {source} पर पानी में दूषण पाया गया। TDS: {tds} ppm, pH: {ph}। साफ होने तक न पिएं। ग्राम पंचायत से संपर्क करें।",
    },
    "depletion": {
        "en": "WARNING: Groundwater at {source} may reach critical level in {days} days. Reduce extraction. Shift to drip irrigation.",
        "hi": "चेतावनी: {source} पर भूजल {days} दिनों में गंभीर स्तर पर पहुंच सकता है। निकासी कम करें। ड्रिप सिंचाई अपनाएं।",
    },
}

async def dispatch_alert(node_id: str, alert_type: str, confidence: float, reading):
    """Send multilingual alerts via SMS, WhatsApp, and voice."""
    
    node = await get_node(node_id)
    subscribers = await get_subscribers(node.village_id)
    
    for subscriber in subscribers:
        lang = subscriber.preferred_language or "hi"
        template = ALERT_TEMPLATES.get(alert_type, {}).get(lang, ALERT_TEMPLATES[alert_type]["en"])
        message = template.format(
            source=node.location_name,
            tds=reading.tds,
            ph=reading.ph,
            days=reading.days_to_critical if hasattr(reading, 'days_to_critical') else 'N/A',
        )
        
        # SMS — always send (works on all phones)
        await send_sms(subscriber.phone, message)
        
        # WhatsApp — if subscriber has WhatsApp
        if subscriber.has_whatsapp:
            await send_whatsapp(subscriber.phone, message)
        
        # Voice call — for critical contamination alerts
        if alert_type == "contamination" and confidence > 0.85:
            tts_audio = await bhashini_tts(message, lang)
            await make_voice_call(subscriber.phone, tts_audio)

async def bhashini_tts(text: str, language: str) -> bytes:
    """Convert text to speech using Bhashini API."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            BHASHINI_API,
            headers={
                "Authorization": settings.BHASHINI_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "pipelineTasks": [{
                    "taskType": "tts",
                    "config": {
                        "language": {"sourceLanguage": language},
                        "gender": "female",
                    }
                }],
                "inputData": {
                    "input": [{"source": text}]
                }
            }
        )
        result = response.json()
        # Returns base64 audio — decode to bytes
        import base64
        audio_b64 = result["pipelineResponse"][0]["output"][0]["audio"]
        return base64.b64decode(audio_b64)
```

---

## 7. AI/ML Pipeline

### 7.1 Model Inventory

| Model | Task | Architecture | Input | Output | Size | Quantization | Target |
|-------|------|-------------|-------|--------|------|-------------|--------|
| anomaly_detector | Water quality anomaly detection | 1D-CNN + Dense | (1, 10) features | (1, 3) class probs | 8 MB | INT8 (Quark) | NPU |
| depletion_predictor | Groundwater level forecasting | LSTM (2-layer) | (1, 90, 3) time series | (1, 30) future levels | 25 MB | BF16 | NPU+CPU |
| irrigation_optimizer | Irrigation scheduling | Gradient-boosted trees (ONNX) | (1, 15) context | (1, 8) schedule + efficiency | 12 MB | INT8 (Quark) | NPU |

### 7.2 Training Pipeline

**Infrastructure:** AMD Developer Cloud → Instinct MI300X (192 GB HBM3) → ROCm 7 → PyTorch 2.x

```
Step 1: Data Collection
├── CPCB API → Historical water quality (all India stations, 2015–2025)
├── India-WRIS → Groundwater level observations (40,000+ wells)
├── IMD API → Weather/rainfall data (district-level, daily)
├── data.gov.in → Agricultural crop patterns, soil types
└── Jal Jeevan Mission → Tap connection locations, test results

Step 2: Data Preprocessing
├── Merge by geography (district/block/village) and time
├── Handle missing values (forward fill for time series, median for cross-section)
├── Feature engineering:
│   ├── Rolling averages (7d, 30d, 90d)
│   ├── Rate of change (daily delta, weekly delta)
│   ├── Seasonal decomposition (monsoon/winter/summer)
│   ├── Cross-sensor correlations
│   └── Geographic clusters (similar geology/aquifer)
└── Train/val/test split: 70/15/15 (temporal split, no leakage)

Step 3: Model Training (AMD MI300X via Developer Cloud)
├── Anomaly Detection:
│   ├── Architecture: Conv1D(10→32→64) → Dense(64→32→3)
│   ├── Loss: CrossEntropy (weighted for class imbalance)
│   ├── Labels: Manual annotations + expert rules (BIS IS 10500 thresholds)
│   └── Epochs: 100, early stopping on val loss
├── Depletion Prediction:
│   ├── Architecture: LSTM(input=3, hidden=64, layers=2) → Dense(64→30)
│   ├── Loss: MSE
│   ├── Input: 90-day lookback window
│   └── Target: 30-day forecast
└── Irrigation Optimizer:
    ├── Architecture: XGBoost → export to ONNX via onnxmltools
    ├── Labels: Optimal irrigation from ICRISAT/ICAR field trial data
    └── Features: Crop type, growth stage, soil moisture, weather forecast

Step 4: ONNX Export
├── PyTorch models: torch.onnx.export(model, dummy_input, "model.onnx", opset_version=17)
└── XGBoost: onnxmltools.convert_xgboost(model)

Step 5: Quantization with AMD Quark
├── from quark.onnx import ModelQuantizer, QuantizationConfig
├── config = QuantizationConfig(calibration_method="MinMax", quant_format="INT8")
├── quantizer = ModelQuantizer(config)
├── quantizer.quantize_model("model.onnx", "model_int8.onnx", calibration_data)
└── Validate: accuracy within 1% of FP32 baseline
```

### 7.3 AMD Quark Quantization — Detailed

```python
# training/scripts/quantize_quark.py
from quark.onnx import ModelQuantizer, QuantizationConfig
from quark.onnx.quantization.config import get_default_config
import numpy as np

def quantize_for_ryzen_npu(model_path: str, output_path: str, calibration_data: np.ndarray):
    """Quantize ONNX model using AMD Quark for Ryzen AI NPU deployment."""
    
    config = get_default_config("XINT8")  # INT8 for XDNA NPU
    config.calibration_method = "MinMax"
    config.activation_type = "uint8"
    config.weight_type = "int8"
    
    quantizer = ModelQuantizer(config)
    quantizer.quantize_model(
        model_input=model_path,
        model_output=output_path,
        calibration_data_reader=calibration_data_reader(calibration_data),
    )
    
    print(f"Quantized model saved: {output_path}")
    print(f"Original size: {os.path.getsize(model_path) / 1e6:.1f} MB")
    print(f"Quantized size: {os.path.getsize(output_path) / 1e6:.1f} MB")

def calibration_data_reader(data: np.ndarray):
    """Yields calibration samples for Quark quantization."""
    for i in range(min(len(data), 100)):
        yield {"input": data[i:i+1].astype(np.float32)}
```

### 7.4 Model Retraining Loop

```
Edge Gateway → Collects labeled ground truth (manual tests, farmer feedback)
    │
    ▼
Cloud Sync → Aggregates training data from all deployed villages
    │
    ▼
Monthly Retrain → AMD Developer Cloud (MI300X)
    │
    ├── Retrain with new data
    ├── Validate against holdout set
    ├── Re-quantize with AMD Quark
    └── A/B test new model on 10% of edge gateways
        │
        ▼
    Promote to all gateways if accuracy improves
    (Model update pulled by edge sync agent)
```

---

## 8. Data Sources & APIs

### 8.1 Government Data APIs

| API/Source | URL | Data | Auth | Rate Limit |
|-----------|-----|------|------|------------|
| **CPCB Real-time** | cpcb.nic.in/CAAQM/ | Air/Water quality from monitoring stations | Open | N/A |
| **data.gov.in** | api.data.gov.in/resource/ | 80,000+ datasets: water quality, agriculture, census | API Key (free) | 10,000/day |
| **India-WRIS** | indiawris.gov.in | Groundwater levels, surface water, rainfall | Open | N/A |
| **IMD Weather** | mausam.imd.gov.in | Temperature, rainfall, humidity (district-level) | Open | N/A |
| **API Setu** | apisetu.gov.in | Gateway to all government APIs | OAuth2 | Varies |
| **Bhashini** | dhruva-api.bhashini.gov.in | ASR, Translation, TTS for 22 Indian languages | API Key (free for dev) | 1000/day |

### 8.2 Water Quality Standards (BIS IS 10500:2012)

| Parameter | Acceptable Limit | Alert Threshold | Critical Threshold |
|-----------|-----------------|-----------------|-------------------|
| TDS | ≤500 ppm | >500 ppm | >2000 ppm |
| pH | 6.5–8.5 | <6.0 or >9.0 | <5.5 or >9.5 |
| Turbidity | ≤1 NTU | >5 NTU | >25 NTU |
| Dissolved Oxygen | ≥6 mg/L | <4 mg/L | <2 mg/L |

### 8.3 Communication APIs

| Service | API | Purpose | Cost |
|---------|-----|---------|------|
| **MSG91** | msg91.com/api | SMS delivery (India) | INR 0.20/SMS |
| **WhatsApp Business** | graph.facebook.com | WhatsApp messaging | INR 0.50/message |
| **Twilio Voice** | api.twilio.com | Voice calls | INR 1.50/minute |
| **Bhashini TTS** | dhruva-api.bhashini.gov.in | Text-to-speech (22 languages) | Free (government) |

---

## 9. Communication Layer

### 9.1 LoRa Network Design

```
Configuration:
  Frequency: 865–867 MHz (India ISM band, as per WPC/DOT)
  Spreading Factor: SF7 (fastest, 2–5 km range in rural open terrain)
  Bandwidth: 125 kHz
  Coding Rate: 4/5
  TX Power: 20 dBm (100 mW — within India regulatory limit)
  Duty Cycle: <1% (regulatory compliance)
  Payload: 32 bytes per packet
  Air Time: ~56 ms per packet at SF7

Topology: Star (all sensor nodes → single edge gateway)
  - Simple, reliable, no mesh complexity
  - Gateway has directional antenna for extended range
  - Each node transmits once per 30 seconds
  - ACK from gateway confirms receipt (retry 3x if no ACK)

Capacity Calculation:
  - Max 20 nodes per gateway
  - 20 nodes × 1 packet/30s = 0.67 packets/second
  - Channel capacity at SF7: ~18 packets/second
  - Utilization: 3.7% (well within limits)
```

### 9.2 Cloud Sync Protocol

```
When: Connectivity monitor detects 4G/WiFi
Frequency: Every 6 hours (if connected), or immediate for critical alerts
Protocol: HTTPS POST with gzip-compressed JSON

Payload:
{
  "gateway_id": "JN-DL-001",
  "batch_id": "uuid",
  "readings": [...],        // All readings since last sync
  "alerts": [...],          // All alerts since last sync
  "predictions": [...],     // Latest forecasts
  "device_health": {...},   // Battery, uptime, disk, model versions
  "sync_timestamp": "ISO8601"
}

Size: ~500 KB per 6-hour batch (20 nodes × 720 readings × ~35 bytes)
Endpoint: POST https://api.jalnetra.dmj.one/v1/sync
Auth: mTLS + API key
Retry: Exponential backoff (1s, 2s, 4s, 8s, 16s, 32s, max 5 retries)
Idempotency: batch_id ensures no duplicate ingestion
```

---

## 10. Frontend & User Interfaces

### 10.1 Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | React 19 + TypeScript |
| Build | Vite 6 |
| Styling | Tailwind CSS 4 |
| Charts | Recharts (lightweight, offline-capable) |
| Maps | Leaflet + OpenStreetMap tiles (cached for offline) |
| State | Zustand (lightweight, works with service workers) |
| Offline | Service Worker + IndexedDB (via idb library) |
| PWA | vite-plugin-pwa |
| i18n | react-i18next (22 languages) |

### 10.2 Farmer View (Mobile-First)

```
┌─────────────────────────────┐
│  🟢 Your Water is Safe      │  ← Big status indicator
│  Handpump #3 — Pani Road    │
├─────────────────────────────┤
│  This Week's Irrigation     │
│  ┌───┬───┬───┬───┬───┬───┐ │
│  │Mon│Tue│Wed│Thu│Fri│Sat│ │  ← Visual blocks
│  │2hr│ - │1hr│ - │2hr│ - │ │
│  └───┴───┴───┴───┴───┴───┘ │
│  Water saved: 35% vs flood  │
├─────────────────────────────┤
│  Groundwater Level: 12.3m   │
│  ▓▓▓▓▓▓▓▓░░░░ (65% safe)  │
│  Forecast: Stable 30 days   │
├─────────────────────────────┤
│     🎤 Ask in Hindi          │  ← Bhashini voice query
└─────────────────────────────┘
```

### 10.3 Panchayat Dashboard (Tablet)

```
┌─────────────────────────────────────────────┐
│  JalNetra — [Village Name]     Last: 2m ago │
├──────────────────────┬──────────────────────┤
│  MAP VIEW            │  ALERTS (3 active)   │
│  ┌────────────────┐  │  🔴 Handpump #7:     │
│  │  🟢1  🟢2      │  │     pH 5.2 (LOW)     │
│  │        🔴7     │  │  🟡 Borewell #3:     │
│  │  🟢3   🟢4     │  │     Level declining  │
│  │       🟡5      │  │  🟡 Canal inlet:     │
│  └────────────────┘  │     Turbidity high   │
├──────────────────────┴──────────────────────┤
│  TRENDS (7 days)          [Export Report]   │
│  ┌──────────────────────────────────────┐   │
│  │  TDS ~~~~~~~~~~~/\~~~~  pH ___---__  │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## 11. Deployment & Infrastructure

### 11.1 Edge Gateway — autoconfig.sh

```bash
#!/bin/bash
# JalNetra Edge Gateway — Zero-intervention deploy
# Run on fresh Ubuntu 22.04: curl -sSL install.jalnetra.dmj.one | bash

set -euo pipefail

echo "[1/10] System packages..."
apt-get update && apt-get install -y python3.11 python3.11-venv python3-pip \
    nodejs npm git curl wget ufw fail2ban nginx

echo "[2/10] Firewall..."
ufw default deny incoming && ufw allow 22 && ufw allow 80 && ufw allow 443
ufw --force enable

echo "[3/10] JalNetra application..."
cd /opt
git clone https://github.com/divyamohan1993/amdslingshot.git jalnetra
cd jalnetra/edge

echo "[4/10] Python environment..."
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

echo "[5/10] AMD Ryzen AI SDK..."
# Install ONNX Runtime with Vitis AI EP
pip install onnxruntime-vitisai  # AMD's pre-built wheel

echo "[6/10] Dashboard build..."
cd ../dashboard && npm ci && npm run build
cp -r dist /opt/jalnetra/edge/static/

echo "[7/10] Database..."
cd /opt/jalnetra/edge
alembic upgrade head

echo "[8/10] Systemd services..."
cp deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jalnetra-api jalnetra-lora jalnetra-sync jalnetra-alerts

echo "[9/10] Nginx reverse proxy..."
cat > /etc/nginx/sites-available/jalnetra <<'EOF'
server {
    listen 80;
    location / { proxy_pass http://127.0.0.1:8000; }
    location /ws { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1;
                   proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }
    location /static { alias /opt/jalnetra/edge/static; }
}
EOF
ln -sf /etc/nginx/sites-available/jalnetra /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "[10/10] Health check..."
sleep 5
curl -sf http://localhost/api/v1/health && echo "JalNetra is running!" || echo "FAILED"
```

### 11.2 Cloud Backend — Terraform

```hcl
# cloud/terraform/main.tf
provider "google" {
  project = "jalnetra-prod"
  region  = "asia-south1"  # Mumbai
}

resource "google_cloud_run_v2_service" "api" {
  name     = "jalnetra-api"
  location = "asia-south1"
  template {
    containers {
      image = "gcr.io/jalnetra-prod/api:latest"
      resources { limits = { cpu = "1", memory = "512Mi" } }
    }
    scaling { min_instance_count = 0  max_instance_count = 10 }
  }
}

resource "google_bigquery_dataset" "jalnetra" {
  dataset_id = "jalnetra"
  location   = "asia-south1"
}

resource "google_bigquery_table" "readings" {
  dataset_id = google_bigquery_dataset.jalnetra.dataset_id
  table_id   = "readings"
  schema     = file("schemas/readings.json")
  time_partitioning { type = "DAY" field = "timestamp" }
}
```

---

## 12. Security & Privacy

| Layer | Measure |
|-------|---------|
| Sensor → Edge | LoRa AES-128 encryption (built into SX1262), CRC-16 integrity |
| Edge device | Full disk encryption (LUKS), firewall (UFW), fail2ban |
| Edge → Cloud | mTLS + API key, gzip + HTTPS, certificate pinning |
| Data at rest | SQLite with SQLCipher encryption |
| Dashboard | JWT auth, bcrypt passwords, HTTPS only |
| PII handling | Phone numbers hashed in logs, raw data stays on edge, only aggregated data synced |
| Model security | ONNX model files signed, integrity verified before loading |

---

## 13. Cost Analysis

### 13.1 Per Village — One-Time

| Item | Cost (INR) |
|------|-----------|
| Sensor nodes (5 units × INR 4,300) | 21,500 |
| Edge gateway (AMD Ryzen AI mini-PC) | 35,000 |
| Solar power system (50W panel + battery + controller) | 8,000 |
| LoRa gateway antenna (directional, 5dBi) | 1,500 |
| Installation, cabling, enclosures | 7,000 |
| **Total** | **~73,000** |

### 13.2 Per Village — Annual Recurring

| Item | Cost (INR/year) |
|------|----------------|
| SMS alerts (~100/month × INR 0.20) | 2,400 |
| WhatsApp messages (~50/month × INR 0.50) | 3,000 |
| Voice calls (~10/month × INR 1.50/min × 1 min) | 1,800 |
| GCP Cloud Run + BigQuery | 3,600 |
| Sensor maintenance (replacements, calibration) | 5,000 |
| **Total** | **~15,800** |

### 13.3 Cost Comparison

| Metric | Manual Testing | JalNetra |
|--------|---------------|---------|
| Annual cost per village | INR 45,000–75,000 (3 visits × INR 15K–25K) | INR 15,800 recurring (after INR 73K setup) |
| Monitoring frequency | 2–3 times/year | 24/7 continuous (every 30 seconds) |
| Alert response time | Weeks (lab results) | Seconds (real-time) |
| Coverage | Sample-based (1–2 sources) | All sources (5–20 per village) |
| Break-even | — | 18 months |

---

## 14. Development Roadmap

### Phase 1: MVP Prototype (Weeks 1–4)
- [ ] Sensor node firmware (ESP32-S3 + 3 sensors: TDS, pH, turbidity)
- [ ] LoRa communication (single node → edge gateway)
- [ ] Anomaly detection model (trained on CPCB historical data)
- [ ] AMD Quark quantization → ONNX INT8
- [ ] FastAPI server with SQLite
- [ ] Basic React dashboard (water quality status)
- [ ] SMS alerting via MSG91

### Phase 2: Full Feature Set (Weeks 5–8)
- [ ] All 5 sensor types integrated
- [ ] Multi-node LoRa network (5 nodes)
- [ ] Depletion prediction model (LSTM)
- [ ] Irrigation optimizer (XGBoost → ONNX)
- [ ] Bhashini voice alerts (Hindi + 2 more languages)
- [ ] WhatsApp Business API integration
- [ ] PWA offline support (service worker + IndexedDB)
- [ ] Panchayat dashboard with map view

### Phase 3: Cloud & Scale (Weeks 9–12)
- [ ] GCP Cloud Run backend
- [ ] BigQuery aggregation pipeline
- [ ] District admin dashboard
- [ ] Cloud sync agent (batch upload + model update)
- [ ] Terraform IaC for cloud infra
- [ ] Solar power system integration
- [ ] Field testing at 1 pilot village

### Phase 4: Production Hardening (Weeks 13–16)
- [ ] Security audit (encryption, auth, PII)
- [ ] 22-language alert templates
- [ ] JJM compliance report generator
- [ ] Model retraining pipeline
- [ ] Monitoring + alerting (Prometheus/Grafana on edge)
- [ ] Documentation + deployment guide

---

## 15. Testing Strategy

| Level | Tool | Scope |
|-------|------|-------|
| Unit tests | pytest | Inference engine, packet parser, alert templates, calibration math |
| Integration tests | pytest + httpx | API endpoints, database, WebSocket |
| Hardware-in-loop | PlatformIO Test | ESP32 sensor reading accuracy, LoRa packet delivery |
| Model validation | Custom scripts | Accuracy, latency, memory footprint on NPU vs CPU |
| Load testing | locust | Edge API under 20 concurrent sensor streams |
| Field testing | Manual | Sensor accuracy vs lab-grade equipment, LoRa range, solar endurance |

---

## 16. Scalability Plan

| Scale | Nodes | Infrastructure | Timeline |
|-------|-------|---------------|----------|
| **Pilot** | 1 village, 5 nodes | Single edge gateway, no cloud | Month 1–3 |
| **District** | 50 villages, 250 nodes | 50 edge gateways, GCP Cloud Run | Month 4–6 |
| **State** | 500 villages, 2,500 nodes | Cloud Run auto-scaling, BigQuery | Month 7–12 |
| **National** | 50,000+ villages | Multi-region GCP, Cloudflare CDN, federated model training | Year 2+ |

Each edge gateway operates independently — no dependency between villages. This enables embarrassingly parallel rollout. The only scaling challenge is the cloud aggregation layer, which BigQuery handles natively through partitioning and streaming inserts.

---

## 17. AMD Technology Integration — Summary

| AMD Product | Where Used | Why |
|-------------|-----------|-----|
| **Ryzen AI NPU (XDNA)** | Edge gateway inference | Sub-100ms, 5–15W, enables offline-first |
| **Ryzen AI Software SDK 1.7** | ONNX Runtime + Vitis AI EP | Production-ready NPU deployment framework |
| **AMD Quark** | Model quantization | INT8/BF16 optimization, 7x+ NPU speedup |
| **AMD Instinct MI300X** | Model training (Developer Cloud) | 192 GB HBM3, free cloud access for teams |
| **AMD ROCm 7** | PyTorch training on MI300X | Open GPU computing platform |
| **AMD GAIA SDK** | Edge AI agent orchestration | Local LLM/agent framework for AI PC |

---

## 18. Appendices

### A. Environment Variables (.env)

```env
# Edge Gateway
JALNETRA_NODE_ID=JN-DL-001
JALNETRA_VILLAGE_ID=110001
JALNETRA_LORA_PORT=/dev/ttyUSB0
JALNETRA_LORA_BAUD=115200
JALNETRA_DB_PATH=/opt/jalnetra/data/jalnetra.db
JALNETRA_MODEL_DIR=/opt/jalnetra/edge/models_onnx/

# Alert APIs
MSG91_AUTH_KEY=xxxxx
MSG91_SENDER_ID=JALNET
MSG91_TEMPLATE_ID=xxxxx
WHATSAPP_TOKEN=xxxxx
WHATSAPP_PHONE_ID=xxxxx
TWILIO_ACCOUNT_SID=xxxxx
TWILIO_AUTH_TOKEN=xxxxx
TWILIO_FROM_NUMBER=+91xxxxxxxxxx
BHASHINI_API_KEY=xxxxx

# Cloud Sync
CLOUD_SYNC_URL=https://api.jalnetra.dmj.one/v1/sync
CLOUD_SYNC_API_KEY=xxxxx
CLOUD_SYNC_INTERVAL_HOURS=6

# Dashboard
JALNETRA_SECRET_KEY=xxxxx
JALNETRA_JWT_EXPIRY=3600
```

### B. Database Schema

```sql
CREATE TABLE sensor_nodes (
    id TEXT PRIMARY KEY,
    village_id TEXT NOT NULL,
    location_name TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    source_type TEXT CHECK(source_type IN ('borewell', 'handpump', 'canal', 'reservoir', 'tap')),
    installed_at TEXT NOT NULL,
    last_seen_at TEXT,
    battery_voltage REAL,
    status TEXT DEFAULT 'active'
);

CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES sensor_nodes(id),
    tds REAL,
    ph REAL,
    turbidity REAL,
    flow_rate REAL,
    water_level REAL,
    battery_voltage REAL,
    timestamp TEXT NOT NULL,
    synced INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_readings_node_time ON readings(node_id, timestamp);
CREATE INDEX idx_readings_synced ON readings(synced) WHERE synced = 0;

CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES sensor_nodes(id),
    alert_type TEXT NOT NULL,
    severity TEXT CHECK(severity IN ('info', 'warning', 'critical')),
    message TEXT NOT NULL,
    confidence REAL,
    reading_id INTEGER REFERENCES readings(id),
    acknowledged INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE irrigation_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES sensor_nodes(id),
    schedule_date TEXT NOT NULL,
    recommended_hours REAL,
    crop_type TEXT,
    water_saved_pct REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL REFERENCES sensor_nodes(id),
    prediction_type TEXT NOT NULL,
    days_to_critical INTEGER,
    trend TEXT,
    predicted_values TEXT,  -- JSON array
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    village_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    preferred_language TEXT DEFAULT 'hi',
    has_whatsapp INTEGER DEFAULT 0,
    role TEXT CHECK(role IN ('farmer', 'panchayat', 'technician')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### C. API Reference

```
Base URL: http://<edge-gateway-ip>/api/v1

GET  /health                    → { status: "ok", version: "1.0.0", uptime: 86400 }
GET  /readings?node_id=&last=1h → [SensorReading]
GET  /readings/latest           → { [node_id]: SensorReading }
GET  /alerts?severity=critical  → [Alert]
POST /alerts/:id/acknowledge    → { acknowledged: true }
GET  /irrigation?node_id=       → IrrigationSchedule
GET  /predictions?node_id=      → DepletionPrediction
GET  /nodes                     → [SensorNode]
GET  /reports/jjm?month=2026-03 → PDF report (JJM compliance)
POST /sync                      → Trigger cloud sync
WS   /ws/live                   → Real-time reading stream
```

---

*Document version: 1.0 | Created: March 2026 | Team: dmj.one*
*AMD Slingshot 2026 — Sustainable AI & Green Tech*
