# JalNetra — AI-Powered Water Quality & Scarcity Early Warning System for India

**Theme:** Sustainable AI & Green Tech
**Tagline:** "Predicting water crises before they hit — block by block, village by village, across 6 lakh+ habitations."

---

## 1. Problem Statement

India is the world's most water-stressed major economy:

- **600M+ Indians** face high-to-extreme water stress (NITI Aayog Composite Water Management Index)
- **70% of surface water** is polluted beyond safe drinking standards (CPCB)
- **21 major cities** will run out of groundwater by 2030 (NITI Aayog)
- **200,000 deaths/year** from inadequate access to safe water (WaterAid India)
- **Over 85% of freshwater** goes to agriculture — with zero real-time optimization
- **Only 28% of sewage** is treated before release into water bodies
- **Rural India** has 18.7 Cr rural households, many relying on single-source water (handpump/borewell) with no contamination monitoring

**The core problem:** India has no real-time, block-level water quality + availability prediction system that warns communities and administrators BEFORE a crisis hits. Current monitoring is manual, sporadic (quarterly testing), and data reaches decision-makers weeks late.

---

## 2. Solution Overview

**JalNetra** (जलनेत्र — "Water Eye") is an AI-powered early warning system that predicts water quality degradation and scarcity at **block/panchayat granularity** across India, using:

1. **Satellite imagery analysis** — NDWI (water body extent), NDVI (crop stress = water stress proxy), land surface temperature
2. **Government sensor data** — CPCB real-time water quality stations, IMD rainfall, CWC reservoir levels
3. **Crowdsourced reports** — Citizens report dry taps, discolored water, illness clusters via WhatsApp/SMS bot
4. **Historical pattern learning** — 10 years of seasonal water data to predict future stress
5. **Actionable alerts** — Block-level warnings to district collectors, PHE departments, and citizens in local language

**Output:** A dashboard + alert system that says "Block X in District Y will face drinking water contamination in 14 days based on upstream industrial discharge + declining reservoir + no rainfall forecast" — with recommended actions.

---

## 3. Architecture

### 3.1 High-Level System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        DATA INGESTION LAYER                      │
│                                                                  │
│  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐ ┌────────┐  │
│  │Sentinel-2│ │CPCB Water│ │IMD      │ │CWC       │ │Crowd-  │  │
│  │Satellite │ │Quality   │ │Rainfall │ │Reservoir │ │sourced │  │
│  │(ESA)     │ │Stations  │ │API      │ │Levels    │ │Reports │  │
│  └────┬─────┘ └────┬─────┘ └────┬────┘ └────┬─────┘ └───┬────┘  │
│       │            │            │            │           │        │
│  ┌────▼────────────▼────────────▼────────────▼───────────▼────┐  │
│  │              Apache Kafka / Redis Streams                  │  │
│  │              (Event ingestion + buffering)                 │  │
│  └────────────────────────┬───────────────────────────────────┘  │
└───────────────────────────┼──────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────┐
│                     AI PROCESSING LAYER                          │
│                  (AMD Developer Cloud - MI300X)                   │
│                                                                  │
│  ┌────────────────┐ ┌─────────────────┐ ┌─────────────────────┐ │
│  │ Satellite CV    │ │ Time-Series     │ │ Crowdsource NLP     │ │
│  │ Pipeline        │ │ Forecaster      │ │ Processor           │ │
│  │                 │ │                 │ │                     │ │
│  │ U-Net water     │ │ Temporal Fusion │ │ IndicBERT           │ │
│  │ body segment.   │ │ Transformer     │ │ complaint classifier│ │
│  │ + NDWI/NDVI     │ │ (14-day ahead   │ │ + entity extraction │ │
│  │ computation     │ │ water quality   │ │ (location, symptom, │ │
│  │                 │ │ + level pred.)  │ │  water source)      │ │
│  └───────┬─────────┘ └───────┬─────────┘ └──────────┬──────────┘ │
│          │                   │                       │           │
│  ┌───────▼───────────────────▼───────────────────────▼────────┐  │
│  │              Risk Scoring Engine                            │  │
│  │   Combines all signals → block-level risk score (0-100)    │  │
│  │   + confidence interval + contributing factors              │  │
│  └────────────────────────┬───────────────────────────────────┘  │
└───────────────────────────┼──────────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────────┐
│                      ALERT & DELIVERY LAYER                      │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Admin         │  │ Citizen      │  │ WhatsApp/SMS           │ │
│  │ Dashboard     │  │ Web App      │  │ Alert Bot              │ │
│  │ (District     │  │ (Block-level │  │ (Vernacular warnings   │ │
│  │ Collector,    │  │ water risk   │  │  to registered         │ │
│  │ PHE Dept,     │  │ map + tips)  │  │  citizens/sarpanches)  │ │
│  │ NITI Aayog)   │  │              │  │                        │ │
│  └──────────────┘  └──────────────┘  └────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Component Breakdown

| Component | Model/Tech | Details |
|---|---|---|
| **Satellite CV Pipeline** | U-Net (ResNet50 backbone) quantized via AMD Quark | Segments water bodies from Sentinel-2 imagery (10m resolution), computes NDWI/NDVI, detects shrinkage trends |
| **Time-Series Forecaster** | Temporal Fusion Transformer (TFT) | Predicts water quality parameters (pH, BOD, DO, coliform) and reservoir levels 14 days ahead. Trained on 10 years of CPCB + CWC data |
| **Crowdsource NLP** | Fine-tuned IndicBERT-v2 | Classifies citizen complaints (dry tap / bad smell / discoloration / illness) and extracts location + water source entities from Hindi/regional language messages |
| **Risk Scoring Engine** | Gradient-boosted ensemble (XGBoost) | Fuses satellite, sensor, weather, and crowdsource signals into a 0-100 risk score per block with confidence intervals |
| **Alert Generator** | Gemma3 4B (quantized, on Ryzen AI NPU) | Generates plain-language alert text in Hindi/English with specific recommended actions for administrators |
| **Dashboard** | Next.js 15 + Mapbox GL JS | Real-time heatmap of India at block level, drill-down to individual water sources |

### 3.3 Data Flow — Predictive Alert Generation

```
Every 6 hours:
    │
    ├── Sentinel-2 imagery (5-day revisit, cached) → U-Net segmentation
    ├── CPCB API pull (real-time station data, 1800+ stations)
    ├── IMD API pull (rainfall forecast, district-level)
    ├── CWC API pull (reservoir levels, 130 major reservoirs)
    └── Crowdsource complaints (WhatsApp bot, last 6 hours)
            │
            ▼
    Feature vector per block:
    [water_body_area_change, ndwi_trend, rainfall_7d, rainfall_forecast_14d,
     reservoir_level_pct, reservoir_trend, ph_latest, bod_latest, do_latest,
     coliform_latest, quality_trend_30d, complaint_count_7d,
     complaint_severity_avg, temperature_forecast, population_density,
     irrigation_demand_estimate, industrial_discharge_proximity]
            │
            ▼
    TFT → 14-day water quality forecast
    XGBoost → Risk score (0-100)
            │
            ├── Score < 30 → Green (safe)
            ├── Score 30-60 → Yellow (watch) → Dashboard update
            ├── Score 60-80 → Orange (warning) → SMS to sarpanch + PHE
            └── Score > 80 → Red (critical) → SMS to DC + PHE + citizens
                    │
                    ▼
            Gemma3 4B generates alert:
            "चेतावनी: ब्लॉक [X], जिला [Y] में अगले 10 दिनों में
            पेयजल में कोलीफॉर्म स्तर खतरनाक हो सकता है।
            कारण: ऊपरी धारा में औद्योगिक निर्वहन + वर्षा की कमी।
            सुझाव: वैकल्पिक जल स्रोत तैयार करें, क्लोरीनेशन बढ़ाएं।"
```

---

## 4. Technology Stack

### 4.1 AI & ML

| Layer | Technology |
|---|---|
| **Training** | AMD Developer Cloud (MI300X, ROCm 7, PyTorch 2.5) |
| **Satellite CV** | U-Net with ResNet50 backbone, rasterio, GDAL |
| **Time-Series** | Temporal Fusion Transformer (PyTorch Forecasting) |
| **NLP** | AI4Bharat IndicBERT-v2, fine-tuned for complaint classification |
| **Risk Scoring** | XGBoost 2.0 |
| **Quantization** | AMD Quark (INT8 for U-Net, INT4 for Gemma3) |
| **Edge Inference** | AMD Ryzen AI NPU + ONNX Runtime with Vitis AI EP |
| **Alert LLM** | Gemma3 4B via AMD GAIA (on-device for demo) |

### 4.2 Backend

| Layer | Technology |
|---|---|
| **API Server** | FastAPI (Python 3.12) |
| **Task Queue** | Celery + Redis |
| **Event Stream** | Redis Streams (Kafka at scale) |
| **Database** | PostgreSQL 16 + PostGIS (geospatial queries) |
| **Time-Series DB** | TimescaleDB (PostgreSQL extension) |
| **Object Storage** | Cloudflare R2 (satellite imagery cache) |
| **Hosting** | GCP e2-standard-4 (MVP), auto-scale later |
| **CDN/Proxy** | Cloudflare |

### 4.3 Frontend

| Layer | Technology |
|---|---|
| **Web Dashboard** | Next.js 15 (App Router) + TypeScript |
| **Maps** | Mapbox GL JS (block-level choropleth heatmap) |
| **Charts** | Recharts (time-series visualizations) |
| **Mobile** | PWA (installable, works offline with cached risk map) |
| **Deployment** | Vercel |

### 4.4 Alerting

| Channel | Technology |
|---|---|
| **WhatsApp** | WhatsApp Business API (via Gupshup/Twilio) |
| **SMS** | Twilio / MSG91 (Indian SMS gateway) |
| **Email** | Resend |
| **Push** | Web Push API (PWA) |

---

## 5. Real Indian APIs & Data Sources Used

| Source | What It Provides | Access Method |
|---|---|---|
| **CPCB Real-Time Water Quality** (cpcb.nic.in) | pH, BOD, DO, coliform, conductivity from 1800+ monitoring stations | Web scraping + ENVIS API |
| **Central Water Commission (CWC)** | Daily reservoir storage levels for 130+ major reservoirs | cwc.gov.in public data |
| **India Meteorological Department (IMD)** | Rainfall actuals + 7-day forecast, district-level | mausam.imd.gov.in API |
| **Sentinel-2 (ESA Copernicus)** | 10m resolution multispectral satellite imagery, 5-day revisit | Copernicus Open Access Hub (free) |
| **data.gov.in** | Historical water quality data, groundwater levels, habitation-wise water source data | Open API |
| **Jal Jeevan Mission Dashboard** (ejalshakti.gov.in) | Habitation-level tap water connection status, water source mapping | Public dashboard data |
| **India WRIS (Water Resources Info System)** | River basin data, groundwater maps, well monitoring | india-wris.nrsc.gov.in |
| **ISRO Bhuvan** | Indian satellite imagery, LULC maps | bhuvan.nrsc.gov.in API |
| **National Water Quality Sub-Mission** | Water testing lab results, contamination hotspots | data.gov.in |
| **Census 2011 + projected 2026 population** | Block-level population density for impact estimation | census.gov.in |

---

## 6. AMD Technology Leverage

| AMD Tech | How JalNetra Uses It |
|---|---|
| **AMD Developer Cloud (MI300X)** | Training U-Net on 50K+ Sentinel-2 tiles, TFT on 10 years of daily water quality data from 1800 stations |
| **ROCm 7 + PyTorch** | Full training pipeline — satellite CV, time-series forecasting, NLP fine-tuning |
| **AMD Quark** | Quantize U-Net (INT8) and Gemma3 (INT4) for edge deployment |
| **Ryzen AI NPU** | Demo: run inference on a Ryzen AI laptop — satellite tile analysis + alert generation locally |
| **AMD GAIA** | Package the alert generator as a local AI agent for district collector laptops (offline-capable) |
| **Ryzen AI SDK 1.7** | Gemma3 4B for generating vernacular alert text on-device |
| **ONNX Runtime + Vitis AI EP** | NPU-accelerated inference for satellite image processing on edge |

---

## 7. Scale & Impact

| Metric | Value |
|---|---|
| **Target coverage** | 6,00,000+ habitations across 700+ districts |
| **People affected** | 600M+ in water-stressed regions |
| **Prediction horizon** | 14 days ahead (water quality + scarcity) |
| **Spatial granularity** | Block-level (~6,600 blocks in India) |
| **Alert latency** | <1 hour from data ingestion to alert delivery |
| **Languages** | Hindi, English, Tamil, Telugu, Kannada, Marathi, Bengali, Gujarati |
| **Offline capability** | District admin dashboard works offline with last-synced risk map |
| **Cost** | <₹5,000/month cloud infra for MVP (GCP + Vercel + Cloudflare free tiers) |

---

## 8. Unique Differentiators (Why This Wins)

1. **First block-level predictive water quality system for India** — Current systems are reactive (test after contamination), JalNetra is predictive (warns 14 days before)
2. **Fuses 5 real data sources** — Satellite + government sensors + weather + crowdsource + historical. No single source is reliable alone; fusion makes it robust
3. **Crowdsource validation loop** — Citizens report ground truth via WhatsApp, closing the satellite-to-ground gap
4. **Government-ready** — Designed for Jal Jeevan Mission integration, outputs match district administration workflows
5. **Scalable from 1 block to all of India** — Same pipeline, just more data. No architecture changes needed
6. **AMD edge story** — District collectors get an offline-capable AI agent on Ryzen AI laptops for field visits where there's no internet

---

## 9. Prototype Scope (MVP for Submission)

For the March 1 submission deadline:

1. **Working dashboard** showing real-time water quality risk map for 3 pilot districts (one water-stressed from each zone: North, South, West)
2. **Live CPCB + IMD data ingestion** — Real data flowing, not mocked
3. **Trained TFT model** showing 14-day predictions vs actuals for historical data (backtesting)
4. **Satellite analysis** — Before/after water body shrinkage detection for one drought-affected district
5. **WhatsApp bot** — Send "water quality [district]" → get risk score + plain-language summary
6. **On-device demo** — Alert generation running on Ryzen AI NPU via GAIA

### MVP Architecture

```
Data Pipeline:
  - Python scrapers (CPCB, IMD, CWC) → Redis Streams → PostgreSQL+TimescaleDB
  - Sentinel-2 tiles cached in Cloudflare R2

AI Models:
  - TFT trained on AMD Developer Cloud (MI300X, ROCm 7)
  - U-Net trained on Sentinel-2 water body dataset
  - Models quantized via AMD Quark → ONNX

Frontend:
  - Next.js 15 dashboard on Vercel
  - Mapbox GL JS risk heatmap
  - WhatsApp bot via Gupshup sandbox

Edge Demo:
  - AMD GAIA agent on Ryzen AI laptop
  - Runs risk scoring + alert generation offline
```

---

## 10. Evaluation Criteria Alignment

| Criterion | How JalNetra Scores |
|---|---|
| **Innovation** | First predictive (not reactive) water quality system at block granularity. Multi-source fusion approach is novel for India |
| **Feasibility** | All data sources are real and accessible. Models are proven architectures. MVP demonstrable in 4 weeks |
| **Impact** | 600M+ water-stressed Indians. Direct integration path with Jal Jeevan Mission (government mandate) |
| **Presentation** | Live dashboard with real data. "Zoom into any block in India, see water risk for next 14 days" |
| **Responsible AI** | Confidence intervals on every prediction. Human-in-the-loop (admin decides action). No automated water shutoffs |

---

## 11. Team Skill Requirements

| Role | Skills Needed |
|---|---|
| **ML Engineer** | PyTorch, satellite imagery (rasterio/GDAL), time-series forecasting, AMD ROCm |
| **Backend Developer** | FastAPI, PostgreSQL/PostGIS, Redis, data pipeline design |
| **Frontend Developer** | Next.js, Mapbox GL JS, data visualization, PWA |

---

## Sources

- NITI Aayog Composite Water Management Index (https://niti.gov.in/writereaddata/files/document_publication/2018-05-18-Water-Index-Report_vS8-compressed.pdf)
- CPCB Water Quality Monitoring (https://cpcb.nic.in/)
- Central Water Commission (https://cwc.gov.in/)
- India Meteorological Department (https://mausam.imd.gov.in/)
- Jal Jeevan Mission Dashboard (https://ejalshakti.gov.in/)
- Copernicus Sentinel-2 (https://scihub.copernicus.eu/)
- India WRIS (https://india-wris.nrsc.gov.in/)
- ISRO Bhuvan (https://bhuvan.nrsc.gov.in/)
- data.gov.in Water APIs (https://data.gov.in/)
- AMD Developer Cloud (https://www.amd.com/en/developer/resources/cloud-access/amd-developer-cloud.html)
