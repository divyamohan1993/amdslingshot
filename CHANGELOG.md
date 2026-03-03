# Changelog

All notable changes to JalNetra will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-03

### Added
- **Edge Gateway** — FastAPI application with async lifespan, CORS, and WebSocket support
- **REST API** — Endpoints for readings, alerts, nodes, predictions, reports, sync, and health
- **ML Models** — Anomaly Detector (1D-CNN), Depletion Predictor (LSTM), Irrigation Optimiser (XGBoost)
- **Inference Engine** — Async ONNX Runtime wrapper with per-model latency tracking
- **Training Pipeline** — Synthetic data generation and model training scripts
- **React Dashboard** — Real-time monitoring with maps, charts, gauges, and multilingual support
- **Farmer View** — Simplified dashboard for irrigation schedules and water quality alerts
- **WebSocket Streaming** — Live sensor data and alert broadcasting to connected clients
- **Alert Dispatcher** — Multi-channel notifications via SMS, WhatsApp, and voice calls
- **Cloud Sync** — Periodic batch upload to GCP BigQuery for analytics
- **Firmware** — ESP32-S3 sensor node firmware with LoRa 866 MHz communication
- **Docker** — Multi-stage Dockerfile and Docker Compose orchestration (API + Nginx + Certbot)
- **Terraform** — GCP infrastructure as code (VPC, Compute Engine, BigQuery, Cloud Functions)
- **Deployment Scripts** — GCP VM setup, systemd service, Nginx reverse proxy configuration
- **Test Suite** — pytest with async support, API integration tests, model tests, and validators
- **Internationalisation** — i18next with support for 22 Indian languages
- **Documentation** — System design document, hackathon domain docs, and idea briefs

[1.0.0]: https://github.com/divyamohan1993/amdslingshot/releases/tag/v1.0.0
