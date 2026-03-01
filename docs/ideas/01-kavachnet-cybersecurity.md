# KavachNet — AI-Powered Cyber Threat Shield for Bharat's Digital Citizens

**Theme:** AI + Cybersecurity & Privacy
**Tagline:** "Protecting 300M first-time internet users from digital fraud — in their own language, on their own device."

---

## 1. Problem Statement

India has 300M+ UPI users, with 50M+ added yearly — mostly first-time internet users in Tier 2/3 cities and rural India. These users are the #1 target for:

- **UPI fraud:** ₹2,145 Cr lost in FY2024 across 13.7L reported cases (RBI Annual Report 2024)
- **SMS/WhatsApp phishing:** Fake KYC, lottery, loan scams in Hindi, Tamil, Telugu, Bengali
- **Fake apps:** Cloned banking/government apps on sideloaded APKs
- **QR code scams:** Fraudulent QR codes at shops replacing merchant codes
- **Social engineering:** Impersonation calls claiming to be bank/police/government officials

Existing solutions (Norton, McAfee, Google Safe Browsing) are English-only, cloud-dependent, subscription-based, and completely miss vernacular phishing patterns. **There is no cybersecurity product designed for India's vernacular-first, low-literacy, mobile-first population.**

---

## 2. Solution Overview

**KavachNet** is an on-device AI cybersecurity agent that runs locally on AMD Ryzen AI-powered devices (laptops/PCs) and Android phones, providing:

1. **Real-time SMS/WhatsApp message scanning** — Detects phishing in 10+ Indian languages
2. **UPI transaction anomaly detection** — Flags suspicious payment requests before confirmation
3. **Fake app detection** — Vision AI that compares app UI screenshots against known legitimate apps
4. **QR code verification** — Scans and validates merchant QR codes against registered UPI IDs
5. **Voice call fraud detection** — Real-time speech analysis detecting social engineering patterns
6. **Plain-language threat alerts** — Explains threats in the user's language with audio narration

All processing happens **on-device** via AMD Ryzen AI NPU — no data leaves the phone/PC.

---

## 3. Architecture

### 3.1 High-Level System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    USER DEVICE (Android / PC)            │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ SMS/WhatsApp  │  │  UPI Intent  │  │  QR Scanner  │  │
│  │  Listener     │  │  Interceptor │  │  Module      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                  │          │
│  ┌──────▼─────────────────▼──────────────────▼───────┐  │
│  │              KavachNet AI Engine                   │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │  AMD Ryzen AI NPU / ONNX Runtime            │  │  │
│  │  │  ┌─────────┐ ┌──────────┐ ┌──────────────┐ │  │  │
│  │  │  │ Phishing│ │ Anomaly  │ │ Vision       │ │  │  │
│  │  │  │ Detector│ │ Detector │ │ Comparator   │ │  │  │
│  │  │  │ (NLP)   │ │ (Tabular)│ │ (CNN)        │ │  │  │
│  │  │  └─────────┘ └──────────┘ └──────────────┘ │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │                               │
│  ┌──────────────────────▼────────────────────────────┐  │
│  │           Alert & Explanation Engine               │  │
│  │    (Multilingual TTS + Plain-language explainer)   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │        Threat Intel Sync (Daily, Encrypted)       │──┼──► Cloud: Threat DB
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Component Breakdown

| Component | Model/Tech | Size | Runtime |
|---|---|---|---|
| **Phishing NLP Detector** | Fine-tuned IndicBERT (multilingual) quantized via AMD Quark | ~50MB INT4 | Ryzen AI NPU via ONNX Runtime |
| **UPI Anomaly Detector** | XGBoost ensemble + rule engine | ~5MB | CPU |
| **Fake App Vision Comparator** | MobileNetV3 + SSIM perceptual hash | ~15MB INT8 | NPU |
| **QR Code Validator** | ZXing decoder + UPI ID regex + NPCI merchant registry lookup | <1MB | CPU |
| **Voice Fraud Detector** | Whisper-small (quantized) + intent classifier | ~150MB INT4 | NPU + iGPU hybrid |
| **Alert Engine** | Gemma3 4B VLM (quantized) for explanation + Coqui TTS | ~2.5GB INT4 | NPU via Ryzen AI SDK 1.7 |
| **Threat Intel DB** | SQLite local + daily delta sync | ~20MB | CPU |

### 3.3 Data Flow — SMS Phishing Detection

```
SMS Received
    │
    ▼
Accessibility Service captures text
    │
    ▼
Language Detection (fastText, <1ms)
    │
    ▼
IndicBERT Phishing Classifier (NPU, ~15ms)
    │
    ├── SAFE → No action
    │
    └── SUSPICIOUS (confidence > 0.7)
            │
            ▼
        Gemma3 4B generates plain-language explanation
        in detected language ("This message claims to be
        from SBI but the link goes to sbi-kyc-update.xyz
        which is not a real SBI website")
            │
            ▼
        Overlay alert + optional TTS audio narration
            │
            ▼
        User chooses: Block / Report / Ignore
            │
            ▼
        Anonymous threat hash → cloud sync (no PII)
```

---

## 4. Technology Stack

### 4.1 On-Device (Primary)

| Layer | Technology |
|---|---|
| **AI Runtime** | AMD Ryzen AI Software SDK 1.7 + ONNX Runtime with Vitis AI EP |
| **Quantization** | AMD Quark (INT4/INT8 quantization for all models) |
| **Local LLM** | Gemma3 4B via AMD GAIA framework |
| **NPU Orchestration** | XDNA NPU driver + hybrid NPU/iGPU scheduling |
| **Mobile Runtime** | ONNX Runtime Mobile + NNAPI delegate (for Android ARM) |
| **Language** | Kotlin (Android), Python + C++ (PC agent via GAIA) |
| **Local DB** | SQLite with SQLCipher encryption |
| **TTS** | Coqui TTS (Indian language voices) or Android native TTS |

### 4.2 Cloud Backend (Minimal — threat intel only)

| Layer | Technology |
|---|---|
| **API** | FastAPI on GCP e2-micro (free tier) |
| **Threat DB** | PostgreSQL (Supabase free tier) |
| **Threat Feed Ingestion** | CERT-In advisories, PhishTank, OpenPhish, RBI fraud alerts |
| **CDN/Proxy** | Cloudflare (DDoS + caching for delta sync API) |
| **CI/CD** | GitHub Actions |

### 4.3 Training Pipeline (One-time / periodic)

| Step | Tool |
|---|---|
| **Dataset** | Hindi/Tamil/Telugu/Bengali phishing SMS from Spam SMS Dataset India + synthetic augmentation |
| **Base Model** | AI4Bharat IndicBERT-v2 |
| **Fine-tuning** | AMD Developer Cloud (MI300X, ROCm 7, PyTorch) |
| **Quantization** | AMD Quark → INT4 ONNX |
| **Validation** | 10K real phishing samples from CERT-In + crowdsourced |
| **Export** | ONNX model → bundled in APK/installer |

---

## 5. Real Indian APIs & Data Sources Used

| Source | What It Provides | Access |
|---|---|---|
| **CERT-In (cert-in.org.in)** | Indian cyber threat advisories, vulnerability alerts | Public RSS/scrape |
| **RBI DAKSH Portal** | UPI fraud complaint data patterns | Public reports |
| **NPCI UPI Directory** | Registered merchant UPI IDs for QR validation | Developer API |
| **PhishTank** | Known phishing URLs (global + Indian) | Free API |
| **data.gov.in** | Cyber crime statistics by state/district | Open API |
| **Telecom Regulatory Authority (TRAI)** | DND registry, spam caller database | Reporting API |
| **Google Safe Browsing API** | URL reputation check (fallback, cloud) | Free tier (10K/day) |
| **Indian SMS Spam Dataset** | Training data for vernacular phishing detection | Kaggle / academic |
| **AI4Bharat IndicNLP** | Pretrained Indian language models | Open source |

---

## 6. AMD Technology Leverage

| AMD Tech | How KavachNet Uses It |
|---|---|
| **Ryzen AI NPU (XDNA)** | All inference runs on NPU — phishing detection in <20ms, zero battery drain on CPU/GPU |
| **AMD Quark** | INT4 quantization of IndicBERT and Gemma3 — 7x faster than CPU, fits in NPU memory |
| **AMD GAIA** | PC agent framework — KavachNet runs as a GAIA agent on Windows/Linux Ryzen AI PCs |
| **Ryzen AI SDK 1.7** | Gemma3 4B VLM support for generating threat explanations in Indian languages |
| **AMD Developer Cloud** | MI300X for training phishing detection models on large Indian language datasets |
| **ROCm 7** | PyTorch training of IndicBERT fine-tunes on MI300X |
| **ONNX Runtime + Vitis AI EP** | Production inference path — NPU-optimized execution |
| **Hybrid NPU + iGPU** | Voice fraud detection uses both — Whisper on iGPU, intent classifier on NPU |

---

## 7. Scale & Impact

| Metric | Value |
|---|---|
| **Target users** | 300M+ UPI users, 500M+ smartphone users in India |
| **Fraud prevented** | Estimated ₹500-1000 Cr/year if 10% adoption |
| **Languages supported** | Hindi, Tamil, Telugu, Bengali, Kannada, Malayalam, Marathi, Gujarati, Odia, Punjabi |
| **Latency** | <50ms end-to-end (message received → alert shown) |
| **Privacy** | Zero data exfiltration — all AI runs on-device |
| **Offline capability** | 100% functional offline (threat DB syncs daily when connected) |
| **Device requirements** | Android 10+ (NNAPI) or any Ryzen AI PC |

---

## 8. Unique Differentiators (Why This Wins)

1. **First vernacular-first cybersecurity product for India** — Nothing like this exists
2. **On-device = privacy by design** — No cloud dependency, no data collection, no subscription
3. **Audio explanations for low-literacy users** — "This message is fake because..." spoken in their language
4. **UPI-native** — Understands Indian payment flows, not just generic phishing
5. **Uses every AMD advantage** — NPU for speed, GAIA for agent framework, Quark for quantization, Developer Cloud for training
6. **Scalable from campus to nation** — Start with 1 college campus, scale to national deployment via partnerships with banks/NPCI

---

## 9. Prototype Scope (MVP for Submission)

For the March 1 submission deadline, the working prototype includes:

1. **Android app** with SMS phishing detection in Hindi + English
2. **QR code scanner** that validates against known UPI merchant patterns
3. **PC agent** (via AMD GAIA) that monitors clipboard and browser for phishing URLs
4. **Demo:** Live detection of 5 real phishing patterns (fake SBI KYC, lottery scam, loan scam, electricity bill scam, Aadhaar update scam)
5. **Benchmarks:** Inference latency on Ryzen AI NPU vs CPU comparison

### MVP Tech Stack

```
Android App:
  - Kotlin + Jetpack Compose
  - ONNX Runtime Mobile
  - IndicBERT-phishing (INT8, 50MB)
  - SQLite threat DB

PC Agent:
  - AMD GAIA framework
  - Python + ONNX Runtime
  - Ryzen AI NPU inference
  - Gemma3 4B for explanations

Training:
  - AMD Developer Cloud (MI300X)
  - PyTorch + ROCm 7
  - AMD Quark quantization
```

---

## 10. Evaluation Criteria Alignment

| Criterion | How KavachNet Scores |
|---|---|
| **Innovation** | First on-device, multilingual cyber shield for India's vernacular internet users. Novel combination of IndicBERT + UPI fraud patterns + AMD NPU |
| **Feasibility** | Working prototype with real phishing detection. All models fit on-device. No expensive infrastructure needed |
| **Impact** | 300M+ potential users. ₹2,145 Cr annual fraud. Protects most vulnerable digital citizens |
| **Presentation** | Live demo: scan a real phishing SMS → see alert in Hindi with audio explanation |
| **Responsible AI** | Privacy-first (on-device), no data collection, explains every decision to the user, no false-positive blocking (user always decides) |

---

## 11. Team Skill Requirements

| Role | Skills Needed |
|---|---|
| **ML Engineer** | PyTorch, ONNX, NLP fine-tuning, AMD ROCm/Quark experience |
| **Mobile Developer** | Kotlin, Android Accessibility APIs, ONNX Runtime Mobile |
| **Security Researcher** | Indian phishing pattern analysis, UPI protocol knowledge, CERT-In familiarity |

---

## Sources

- RBI Annual Report 2024 — UPI fraud statistics
- CERT-In (https://cert-in.org.in/) — Indian cyber threat advisories
- NPCI (https://www.npci.org.in/) — UPI ecosystem documentation
- AI4Bharat IndicBERT (https://ai4bharat.iitm.ac.in/) — Indian language NLP models
- AMD Ryzen AI SDK 1.7 (https://ryzenai.docs.amd.com/) — NPU inference documentation
- AMD GAIA (https://github.com/amd/gaia) — AI PC agent framework
- AMD Quark (https://www.amd.com/en/developer/resources/technical-articles/2025/ai-inference-acceleration-on-ryzen-ai-with-quark.html)
- PhishTank (https://phishtank.org/) — Phishing URL database
- TRAI DND (https://trai.gov.in/) — Telecom spam regulation
