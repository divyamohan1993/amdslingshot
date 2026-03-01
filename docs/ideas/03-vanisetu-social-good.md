# VaniSetu — On-Device Real-Time Speech-to-Speech Translation Bridge for India

**Theme:** AI for Social Good
**Tagline:** "Breaking India's language barrier — real-time voice translation across 22 languages, running entirely on your device."

---

## 1. Problem Statement

India has 22 officially recognized languages, 121 languages spoken by 10,000+ people, and **over 500 million citizens who do not speak Hindi.** This creates catastrophic real-world barriers:

- **Healthcare:** A Tamil-speaking patient in a Delhi hospital cannot explain symptoms to a Hindi-speaking doctor. Misdiagnosis due to language barriers kills people. India has only 1 doctor per 1,000 people — they cannot all learn 22 languages
- **Government services:** A Bengali migrant worker in Mumbai cannot navigate Marathi government offices, courts, or police stations. 60%+ internal migrants face language barriers accessing services (UNESCO India report)
- **Education:** Students from non-Hindi states attending national institutions struggle with Hindi-medium instruction. IIT/AIIMS dropouts cite language as a major factor
- **Justice system:** 70%+ of undertrial prisoners cannot effectively communicate with lawyers due to language mismatch. Courtrooms in India operate in English/Hindi, while most accused speak neither
- **Emergency services:** 112 emergency helpline receives calls in 20+ languages but operators typically speak only 2-3 languages. Response delays due to language have documented fatal consequences
- **Commerce:** Small traders lose business across state borders due to language. Estimated ₹50,000 Cr/year in lost cross-state commerce due to language friction (CII estimate)

**Existing solutions fail because:**
- Google Translate requires internet (India has 50%+ areas with poor connectivity)
- Cloud translation sends sensitive conversations (medical, legal) to third-party servers
- Text translation doesn't help illiterate populations (25%+ of rural India)
- No existing product does real-time speech-to-speech for Indian languages on-device

---

## 2. Solution Overview

**VaniSetu** (वाणीसेतु — "Voice Bridge") is an on-device, real-time speech-to-speech translation system that:

1. **Listens** to a speaker in Language A (e.g., Tamil)
2. **Transcribes** the speech to text using on-device ASR
3. **Translates** the text to Language B (e.g., Hindi)
4. **Speaks** the translation aloud in Language B with natural prosody
5. **All on-device** — zero internet required, zero data sent to cloud

The entire pipeline runs on AMD Ryzen AI NPU in <2 seconds end-to-end latency, enabling natural conversation flow.

### Target Use Cases (Priority Order)

| Use Case | Setting | Languages Needed | Impact |
|---|---|---|---|
| **Hospital consultation** | OPD/ward | Patient's language ↔ Doctor's language | Prevents misdiagnosis, saves lives |
| **Police station FIR** | Thana | Complainant's language ↔ Officer's language | Ensures accurate complaint registration |
| **Court proceedings** | District court | Accused/witness language ↔ Court language | Constitutional right to fair trial |
| **Government counter** | Any govt office | Citizen's language ↔ Official's language | Accessible public services |
| **Emergency 112 calls** | Remote | Caller's language ↔ Operator's language | Faster emergency response |
| **Classroom** | School/college | Student's language ↔ Instruction language | Inclusive education |

---

## 3. Architecture

### 3.1 High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   VANISETU ON-DEVICE PIPELINE                   │
│                   (AMD Ryzen AI PC / Laptop)                    │
│                                                                 │
│  ┌───────────┐     ┌──────────────┐     ┌───────────────────┐  │
│  │ Microphone│────▶│ Voice Activity│────▶│ ASR Engine        │  │
│  │ Input     │     │ Detection    │     │ (Whisper-medium   │  │
│  │ (Speaker A)│     │ (Silero VAD) │     │  quantized INT4)  │  │
│  └───────────┘     └──────────────┘     └────────┬──────────┘  │
│                                                   │             │
│                                          Source text (Lang A)   │
│                                                   │             │
│                                         ┌─────────▼──────────┐ │
│                                         │ Language Detector   │ │
│                                         │ (fastText, <1ms)   │ │
│                                         └─────────┬──────────┘ │
│                                                   │             │
│                                         ┌─────────▼──────────┐ │
│                                         │ Translation Engine  │ │
│                                         │ (IndicTrans2        │ │
│                                         │  quantized INT4)    │ │
│                                         └─────────┬──────────┘ │
│                                                   │             │
│                                         Target text (Lang B)   │
│                                                   │             │
│                                         ┌─────────▼──────────┐ │
│                                         │ TTS Engine          │ │
│                                         │ (IndicVoices/VITS   │ │
│                                         │  quantized INT8)    │ │
│                                         └─────────┬──────────┘ │
│                                                   │             │
│  ┌───────────┐                          ┌─────────▼──────────┐ │
│  │ Speaker   │◀─────────────────────────│ Audio Output       │ │
│  │ Output    │                          │ (Natural voice,    │ │
│  │ (Lang B)  │                          │  Lang B prosody)   │ │
│  └───────────┘                          └────────────────────┘ │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              AMD Ryzen AI NPU (XDNA)                    │   │
│  │  Whisper → NPU | IndicTrans2 → NPU | TTS → NPU+iGPU   │   │
│  │  Orchestrated via ONNX Runtime + Vitis AI EP            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Conversation UI (Electron/Tauri)            │   │
│  │  - Dual-panel transcript (both languages side by side)   │   │
│  │  - One-tap language pair selection                        │   │
│  │  - Medical/Legal/General domain toggle                    │   │
│  │  - Conversation export (PDF/text for records)            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Model Pipeline Detail

| Stage | Model | Original Size | Quantized Size | Quantization | Runtime | Latency |
|---|---|---|---|---|---|---|
| **Voice Activity Detection** | Silero VAD v5 | 2MB | 2MB | Already tiny | CPU | <1ms |
| **Language Detection** | fastText lid.176.ftz | 917KB | 917KB | Already tiny | CPU | <1ms |
| **Speech Recognition (ASR)** | Whisper-medium (multilingual) | 1.5GB | ~400MB | INT4 via AMD Quark | NPU | ~300ms for 10s audio |
| **Translation** | AI4Bharat IndicTrans2-1B (indic-indic + indic-en) | 4GB | ~1.2GB | INT4 via AMD Quark | NPU | ~200ms for 50 tokens |
| **Text-to-Speech** | AI4Bharat IndicVoices / VITS multilingual | 800MB | ~250MB | INT8 via AMD Quark | NPU + iGPU | ~400ms for 50 tokens |
| **Domain Glossary** | SQLite lookup (medical/legal terms) | 5MB | 5MB | N/A | CPU | <1ms |
| **Total on-device** | — | ~6.3GB | **~1.9GB** | — | — | **<1.5s e2e** |

### 3.3 Conversation Flow

```
Doctor (Hindi): "आपको कब से बुखार है?"
    │
    ▼ [Microphone captures]
    ▼ [Silero VAD detects speech end]
    ▼ [fastText: Hindi detected]
    ▼ [Whisper-medium ASR: "आपको कब से बुखार है?"]
    ▼ [IndicTrans2: Hindi → Tamil: "உங்களுக்கு எப்போதிலிருந்து காய்ச்சல்?"]
    ▼ [IndicVoices TTS: Tamil audio generated]
    ▼ [Speaker plays Tamil translation]

Patient (Tamil): "மூன்று நாளாக காய்ச்சல், தலைவலி இருக்கு"
    │
    ▼ [Same pipeline, Tamil → Hindi]
    ▼ [Speaker plays: "तीन दिन से बुखार है, सिरदर्द है"]

    [Both sides see transcript on screen in both languages]
    [Medical terms highlighted with domain glossary matches]
```

---

## 4. Technology Stack

### 4.1 On-Device (Primary — everything runs here)

| Layer | Technology |
|---|---|
| **AI Runtime** | AMD Ryzen AI Software SDK 1.7 + ONNX Runtime with Vitis AI EP |
| **Quantization** | AMD Quark (INT4 for Whisper + IndicTrans2, INT8 for TTS) |
| **Agent Framework** | AMD GAIA (manages model loading, pipeline orchestration) |
| **NPU Scheduling** | Ryzen AI hybrid NPU + iGPU (ASR/Translation on NPU, TTS on iGPU) |
| **ASR** | OpenAI Whisper-medium (multilingual, fine-tuned on Indian accents) |
| **Translation** | AI4Bharat IndicTrans2-1B (supports all 22 scheduled languages) |
| **TTS** | AI4Bharat IndicVoices / VITS-based multilingual Indian TTS |
| **Language Detection** | fastText lid.176.ftz |
| **VAD** | Silero VAD v5 |
| **Desktop App** | Tauri 2.0 (Rust backend + React frontend) — lightweight, <50MB installer |
| **Audio** | PortAudio (cross-platform audio I/O) |
| **Local Storage** | SQLite (conversation history, domain glossaries) |
| **UI Framework** | React 19 + Tailwind CSS 4 |

### 4.2 Mobile Companion (Android — limited feature set)

| Layer | Technology |
|---|---|
| **Runtime** | ONNX Runtime Mobile + NNAPI |
| **Models** | Whisper-small (INT8) + IndicTrans2-200M (INT8) + VITS-small |
| **Total Size** | ~600MB on-device |
| **Latency** | ~3s end-to-end (slower than PC, still usable) |
| **Framework** | Kotlin + Jetpack Compose |
| **Use Case** | Emergency/field use where PC unavailable |

### 4.3 Training & Fine-Tuning (AMD Developer Cloud)

| Task | Technology |
|---|---|
| **ASR Fine-tuning** | Whisper-medium fine-tuned on Indian accent dataset (IIT Madras ASR Challenge data) on MI300X |
| **Translation Training** | IndicTrans2 further fine-tuned on medical/legal domain parallel corpora |
| **TTS Training** | IndicVoices fine-tuned for natural prosody on AMD Developer Cloud |
| **Quantization** | AMD Quark — all models quantized for Ryzen AI NPU deployment |
| **Framework** | PyTorch 2.5 + ROCm 7 |
| **Hardware** | AMD Instinct MI300X (192GB GPU memory — fits all models for training) |

### 4.4 Cloud (Minimal — only for model updates & analytics)

| Layer | Technology |
|---|---|
| **Model Registry** | GCP Cloud Storage (model version hosting) |
| **Analytics** | PostHog (self-hosted, usage telemetry — no conversation data) |
| **Feedback API** | FastAPI on GCP e2-micro |
| **CDN** | Cloudflare (model download distribution) |

---

## 5. Real Indian Language Resources & APIs Used

| Resource | What It Provides | Access |
|---|---|---|
| **AI4Bharat IndicTrans2** | State-of-the-art translation for all 22 Indian scheduled languages | Open source (MIT license) |
| **AI4Bharat IndicVoices** | TTS voices for 22 Indian languages with natural prosody | Open source |
| **AI4Bharat IndicNLP** | Pretrained Indian language embeddings and tokenizers | Open source |
| **IIT Madras Indian Language ASR Data** | Transcribed speech data for Whisper fine-tuning (Hindi, Tamil, Telugu, etc.) | Academic/open |
| **Bhashini (bhashini.gov.in)** | Government of India's language translation platform — parallel corpora and benchmarks | Public API |
| **NPTEL Lectures** | Multilingual educational audio for ASR training data | Public |
| **All India Radio Archives** | Diverse accent/dialect speech data across India | Public |
| **Indian Judiciary Corpus** | Legal terminology parallel corpus (English ↔ Hindi ↔ regional) | Open academic datasets |
| **SNOMED-CT Indian Medical Terms** | Standardized medical terminology in Indian languages | WHO/NHA India |
| **DigiLocker API (via API Setu)** | Verify user identity for institutional deployment | Government API |

---

## 6. AMD Technology Leverage

| AMD Tech | How VaniSetu Uses It |
|---|---|
| **Ryzen AI NPU (XDNA)** | Entire inference pipeline (ASR + Translation + TTS) runs on NPU — <1.5s latency, minimal battery drain |
| **AMD Quark** | INT4 quantization shrinks 6.3GB model stack to 1.9GB — fits entirely in NPU memory, 7x faster than CPU |
| **AMD GAIA** | Desktop agent framework — VaniSetu runs as a GAIA agent, managing model lifecycle and audio pipeline |
| **Ryzen AI SDK 1.7** | Hybrid NPU + iGPU scheduling — ASR/Translation on NPU while TTS uses iGPU for parallel execution |
| **AMD Developer Cloud (MI300X)** | Fine-tuning Whisper on Indian accent data + IndicTrans2 on domain-specific corpora. MI300X's 192GB fits all models simultaneously |
| **ROCm 7 + PyTorch** | Training pipeline for all three models (ASR, Translation, TTS) |
| **ONNX Runtime + Vitis AI EP** | Production inference path with NPU optimization |
| **16K Token Context (SDK 1.7)** | Long conversation context — translator remembers context from earlier in the conversation for better translations |

---

## 7. Scale & Impact

| Metric | Value |
|---|---|
| **Target users** | 500M+ Indians who face language barriers daily |
| **Languages** | All 22 Indian scheduled languages (Phase 1: Hindi, Tamil, Telugu, Bengali, Kannada, Malayalam, Marathi, Gujarati) |
| **Translation directions** | 22 × 21 = 462 language pairs (IndicTrans2 supports all) |
| **End-to-end latency** | <1.5 seconds (PC), <3 seconds (mobile) |
| **Privacy** | 100% on-device — zero conversation data sent anywhere |
| **Offline** | Fully functional without internet |
| **Device requirement** | Any AMD Ryzen AI PC (2024+) or Android 12+ phone |
| **Installation size** | ~2GB (all models + app) |
| **Healthcare impact** | Prevents misdiagnosis for 100M+ migrant patients who see doctors speaking a different language |
| **Justice impact** | 70%+ undertrials can finally communicate effectively with lawyers |

---

## 8. Unique Differentiators (Why This Wins)

1. **First on-device speech-to-speech for Indian languages** — Google Translate requires internet and doesn't do real-time speech-to-speech for most Indian language pairs
2. **Privacy is non-negotiable** — Medical conversations and legal proceedings MUST stay on-device. Cloud translation is a privacy violation in these contexts
3. **Works offline** — 50%+ of Indian government offices, rural hospitals, and district courts have unreliable internet. VaniSetu works everywhere
4. **Domain-aware translation** — Medical and legal glossaries ensure "blood pressure" translates correctly in medical context vs general conversation
5. **Constitutional significance** — Article 348 allows regional languages in courts, but no tool exists to make this real. VaniSetu enables it
6. **Maximum AMD advantage** — Three heavy models (ASR + NMT + TTS) running in parallel on NPU is exactly what Ryzen AI was designed for
7. **AI4Bharat ecosystem** — Built entirely on India's own open-source language AI stack, not foreign models

---

## 9. Prototype Scope (MVP for Submission)

For the March 1 submission deadline:

1. **Desktop app** (Tauri) with Hindi ↔ Tamil real-time speech-to-speech translation
2. **Live demo:** Doctor-patient conversation simulation — Hindi-speaking doctor, Tamil-speaking patient, real-time translated audio with transcript
3. **4 language pairs working:** Hindi↔Tamil, Hindi↔Telugu, Hindi↔Bengali, English↔Hindi
4. **Medical domain glossary** loaded (500 common terms)
5. **Benchmarks:** NPU vs CPU latency comparison showing real-time capability
6. **Dual-panel transcript UI** with both languages side by side

### MVP Tech Stack

```
Desktop App:
  - Tauri 2.0 (Rust + React 19)
  - ONNX Runtime with Vitis AI EP
  - AMD GAIA agent framework

Models (all quantized via AMD Quark):
  - Whisper-medium INT4 (~400MB) — ASR
  - IndicTrans2-1B INT4 (~1.2GB) — Translation
  - VITS multilingual INT8 (~250MB) — TTS
  - Silero VAD + fastText LID (~3MB)

Training:
  - AMD Developer Cloud (MI300X)
  - PyTorch 2.5 + ROCm 7
  - Indian accent ASR data from IIT Madras
  - Medical parallel corpora from SNOMED-CT India

Total on-device: ~1.9GB models + ~50MB app = ~2GB
```

---

## 10. Evaluation Criteria Alignment

| Criterion | How VaniSetu Scores |
|---|---|
| **Innovation** | First on-device, real-time, speech-to-speech Indian language translator. Novel pipeline of 3 AI models running in parallel on AMD NPU |
| **Feasibility** | All models exist and are open source (Whisper, IndicTrans2, IndicVoices). Quantization via Quark proven. Pipeline architecture is straightforward |
| **Impact** | 500M+ Indians face language barriers. Direct life-saving impact in healthcare. Constitutional right enablement in courts. Commerce enablement across state borders |
| **Presentation** | Live demo: two people speak different Indian languages, VaniSetu translates in real-time. Viscerally compelling |
| **Responsible AI** | Zero data collection. On-device only. Domain glossaries prevent dangerous mistranslation of medical/legal terms. Confidence scores shown for uncertain translations |

---

## 11. Team Skill Requirements

| Role | Skills Needed |
|---|---|
| **ML Engineer** | PyTorch, ASR (Whisper), NMT (IndicTrans2), TTS, ONNX, AMD ROCm/Quark |
| **Systems Developer** | Rust (Tauri), audio pipeline (PortAudio), real-time systems, ONNX Runtime integration |
| **UI/UX Designer** | React, accessibility-first design, multilingual UI, doctor/patient workflow design |

---

## 12. Scaling Roadmap

| Phase | Scope | Timeline |
|---|---|---|
| **MVP** | 4 language pairs, desktop only, medical domain | March 2026 |
| **Phase 1** | 8 languages, Android app, legal domain added | June 2026 |
| **Phase 2** | All 22 languages, institutional deployment (hospitals, courts, govt offices) | Dec 2026 |
| **Phase 3** | Embedded device (Ryzen AI Embedded P100) for kiosk deployment in govt offices | 2027 |
| **Phase 4** | Government partnership — integrate with Bhashini, 112 helpline, e-Courts | 2027-28 |

---

## Sources

- AI4Bharat IndicTrans2 (https://ai4bharat.iitm.ac.in/indic-trans2)
- AI4Bharat IndicVoices (https://ai4bharat.iitm.ac.in/)
- Bhashini — Government of India (https://bhashini.gov.in/)
- OpenAI Whisper (https://github.com/openai/whisper)
- AMD Ryzen AI SDK 1.7 (https://ryzenai.docs.amd.com/)
- AMD GAIA (https://github.com/amd/gaia)
- AMD Quark (https://www.amd.com/en/developer/resources/technical-articles/2025/ai-inference-acceleration-on-ryzen-ai-with-quark.html)
- Census of India — Language Data (https://censusindia.gov.in/)
- Article 348, Constitution of India — Language provisions in courts
- UNESCO India — Internal Migration and Language Barriers Report
- IIT Madras ASR Challenge (https://asr-challenge.iitm.ac.in/)
- Silero VAD (https://github.com/snakers4/silero-vad)
