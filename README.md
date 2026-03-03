# JalNetra

**Edge-AI Water Intelligence for Rural India**

JalNetra is an edge-AI water quality and quantity monitoring system built for the [AMD Ryzen AI Slingshot 2026](https://amdslingshot.in/) hackathon under the **Sustainable AI & Green Tech** theme. It combines low-cost IoT sensors with AMD Ryzen AI NPU inference to deliver real-time water intelligence at the source — borewells, village handpumps, canals, and reservoir outlets — with zero dependency on cloud connectivity.

**Team:** [dmj.one](https://dmj.one) | Divya Mohan, Kumkum Thakur

---

## Highlights

- **Sub-100 ms inference** on AMD XDNA NPU via ONNX Runtime
- **5-15 W edge device** power consumption (solar-viable)
- **INR 70,000** per village deployment (covers 5 water sources, 500-2,000 people)
- **30-40 % water savings** through AI-optimised irrigation scheduling
- **24/7 continuous monitoring** versus current manual testing (2-3 times/year)
- **22 Indian languages** for alerts via SMS, WhatsApp, and voice (Bhashini API)

---

## Architecture

```
┌────────────────┐   LoRa 866 MHz   ┌──────────────────────┐
│  Sensor Nodes  │ ───────────────►  │   Edge Gateway       │
│  (ESP32-S3 +   │                   │   (AMD Ryzen AI)     │
│   SX1262)      │                   │                      │
└────────────────┘                   │  FastAPI + ONNX RT   │
                                     │  SQLite (local)      │
                                     │  React Dashboard     │
                                     └──────────┬───────────┘
                                                │  Periodic sync
                                                ▼
                                     ┌──────────────────────┐
                                     │  GCP Cloud           │
                                     │  (BigQuery, Cloud    │
                                     │   Functions, GCS)    │
                                     └──────────────────────┘
```

| Layer | Stack |
|-------|-------|
| **Firmware** | ESP32-S3 (Heltec WiFi LoRa 32 V3), PlatformIO, Arduino, LoRa 866 MHz |
| **Edge API** | Python 3.11+, FastAPI, ONNX Runtime, XGBoost, scikit-learn, aiosqlite |
| **Dashboard** | React 19, TypeScript, Vite, Tailwind CSS, Recharts, Leaflet, Zustand |
| **Cloud** | GCP (Terraform), BigQuery, Cloud Functions, Cloud Storage |
| **DevOps** | Docker, Docker Compose, Nginx, Certbot, systemd, Makefile |

---

## Repository Structure

```
amdslingshot/
├── edge/                  # Edge gateway (FastAPI application)
│   ├── api/               #   REST endpoints (readings, alerts, nodes, predictions, reports)
│   ├── models/            #   ML models (anomaly detection, depletion, irrigation)
│   ├── services/          #   Background services (LoRa, cloud sync, WebSocket)
│   ├── tests/             #   pytest test suite
│   └── utils/             #   Validators, structured logging
├── dashboard/             # React dashboard (Vite + TypeScript)
│   ├── src/components/    #   UI components (SensorCard, MapView, TrendChart, etc.)
│   ├── src/pages/         #   Page views (Dashboard, Alerts, Predictions, FarmerView)
│   ├── src/hooks/         #   Custom React hooks (WebSocket, readings, alerts)
│   └── src/services/      #   API client and WebSocket service
├── training/              # ML model training pipeline
│   ├── scripts/           #   Dataset generation and training scripts
│   └── notebooks/         #   Jupyter notebooks for data exploration
├── firmware/              # ESP32-S3 sensor node firmware (PlatformIO)
├── cloud/                 # GCP cloud infrastructure
│   ├── terraform/         #   Infrastructure as code
│   └── functions/         #   Cloud Functions for data ingestion
├── deploy/                # Deployment configuration
│   ├── nginx/             #   Reverse proxy config
│   ├── scripts/           #   GCP VM setup and deploy scripts
│   └── systemd/           #   systemd service unit
├── docs/                  # Hackathon domain documentation and idea briefs
├── Dockerfile             # Multi-stage production build
├── docker-compose.yml     # Full-stack orchestration
├── Makefile               # Development workflow commands
├── pyproject.toml         # Python project metadata and tool config
└── requirements.txt       # Python production dependencies
```

---

## Getting Started

### Prerequisites

- **Python** 3.11 or later
- **Node.js** 22 or later (for the dashboard)
- **Docker** and **Docker Compose** (for containerised deployment)
- **PlatformIO** (for firmware development)

### Local Development

```bash
# Clone the repository
git clone https://github.com/divyamohan1993/amdslingshot.git
cd amdslingshot

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
make install          # production deps
make dev              # + development/test deps

# Copy environment config
cp .env.example .env  # edit values as needed

# Run the edge gateway (development mode with hot-reload)
make run
# API available at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

### Dashboard

```bash
cd dashboard
npm install
npm run dev
# Dashboard available at http://localhost:5173
```

### Docker

```bash
# Build and start all services (API + Nginx + Certbot)
make docker-build
make docker-up

# View logs
make docker-logs

# Stop
make docker-down
```

---

## ML Pipeline

JalNetra uses three ML models that run on-device via ONNX Runtime:

| Model | Purpose | Algorithm |
|-------|---------|-----------|
| **Anomaly Detector** | Flag abnormal water quality readings in real time | Isolation Forest / Autoencoder |
| **Depletion Predictor** | Forecast groundwater level trends | XGBoost regression |
| **Irrigation Optimiser** | Recommend optimal irrigation schedules | Multi-objective optimisation |

### Training

```bash
# Generate synthetic training data
make generate-data

# Train all models and export ONNX weights
make train
```

---

## Testing

```bash
# Run the full test suite
make test

# Run fast tests (skip slow / model tests)
make test-fast

# Lint and type-check
make lint

# Auto-format
make format
```

---

## Deployment

### GCP VM

```bash
# Provision infrastructure with Terraform
make deploy-terraform

# Set up a GCP VM and deploy
make deploy-gcp
```

### Manual

See [`deploy/scripts/`](deploy/scripts/) for setup scripts and the [`deploy/systemd/`](deploy/systemd/) directory for the systemd service unit.

---

## API Reference

Once the server is running, interactive API documentation is available at:

- **Swagger UI** — `http://localhost:8000/docs`
- **ReDoc** — `http://localhost:8000/redoc`

### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/api/v1/readings` | List sensor readings |
| `POST` | `/api/v1/readings` | Submit a new reading |
| `GET` | `/api/v1/alerts` | List active alerts |
| `GET` | `/api/v1/nodes` | List registered sensor nodes |
| `GET` | `/api/v1/predictions` | Get AI predictions |
| `GET` | `/api/v1/reports` | Generate reports |
| `POST` | `/api/v1/sync` | Trigger cloud sync |
| `WS` | `/ws/live` | Real-time sensor data stream |

---

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `JALNETRA_ENV` | Environment (`production`, `staging`, `development`) | `production` |
| `JALNETRA_SECRET_KEY` | JWT signing key | — |
| `JALNETRA_DATABASE_URL` | SQLite connection string | `sqlite+aiosqlite:///app/data/jalnetra.db` |
| `JALNETRA_MODEL_DIR` | Path to ONNX model weights | `/app/models` |
| `JALNETRA_LOG_LEVEL` | Logging level | `info` |
| `JALNETRA_MAX_SENSORS` | Max connected sensor nodes | `100` |

---

## Makefile Commands

Run `make help` for the full list.

| Command | Description |
|---------|-------------|
| `make install` | Install production dependencies |
| `make dev` | Install development dependencies |
| `make run` | Start dev server with hot-reload |
| `make run-prod` | Start production server |
| `make test` | Run pytest suite |
| `make test-fast` | Run tests (skip slow/model) |
| `make lint` | Ruff + mypy |
| `make format` | Auto-format code |
| `make generate-data` | Generate training datasets |
| `make train` | Train ML models |
| `make docker-build` | Build Docker images |
| `make docker-up` | Start Docker stack |
| `make docker-down` | Stop Docker stack |
| `make deploy-gcp` | Deploy to GCP VM |
| `make deploy-terraform` | Apply Terraform |
| `make clean` | Remove generated files |

---

## Documentation

Detailed hackathon documentation is in the [`docs/`](docs/) directory:

- [About AMD Slingshot](docs/01-about.md)
- [Eligibility](docs/02-eligibility.md)
- [Themes](docs/03-themes.md)
- [Evaluation Criteria](docs/04-evaluation-criteria.md)
- [Prizes](docs/05-prizes.md)
- [Timeline](docs/06-timeline.md)
- [Campus Days](docs/07-campus-days.md)
- [FAQs](docs/08-faqs.md)
- [AMD Technology Stack](docs/09-amd-technology-stack.md)
- [Past Winners Reference](docs/10-past-winners-reference.md)

### Idea Briefs

- [KavachNet — AI Cybersecurity](docs/ideas/01-kavachnet-cybersecurity.md)
- [JalNetra — Green Tech](docs/ideas/02-jalnetra-green-tech.md)
- [VaniSetu — Social Good](docs/ideas/03-vanisetu-social-good.md)

### System Design

- [JalNetra System Design Document](JalNetra%20-%20System%20Design%20Document.md)

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Acknowledgements

- **AMD** for the Ryzen AI Slingshot 2026 hackathon and XDNA NPU technology
- **Hack2Skill** for the event platform
- **Jal Jeevan Mission** data and inspiration
- **Bhashini API** for multilingual support in 22 Indian languages
