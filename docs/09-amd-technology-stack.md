# AMD Ryzen AI Slingshot - AMD Technology Stack & Developer Tools

## Hardware Access for Participants

| Hardware | Details |
|---|---|
| **AMD Instinct MI300X GPUs** | 192GB GPU memory, up to 8-GPU configurations. Hands-on access provided to shortlisted teams. |
| **AMD Developer Cloud** | Free cloud access. Managed, zero-setup Jupyter environment with MI300X GPUs. GitHub-based login, preconfigured ROCm and Docker. Normally $1.99/hr for 1x MI300X, $15.92/hr for 8x MI300X. |
| **AMD Ryzen AI NPU** | Neural Processing Unit built on AMD XDNA™ architecture. Available in Ryzen AI-powered PCs. |

## AMD Developer Tools & SDKs

### AMD ROCm (v7+)
- Open software platform for GPU computing
- Supports PyTorch, TensorFlow, ONNX Runtime
- Works on Instinct and Radeon GPUs
- Link: https://www.amd.com/en/products/software/rocm.html

### AMD Ryzen AI Software SDK (v1.7.0, Released Feb 2026)
- Tools and runtime libraries for AI inference on Ryzen AI NPU (XDNA architecture)
- Supports ONNX Runtime with Vitis AI Execution Provider
- C++ and Python APIs
- Key features in 1.7:
  - Mixture-of-Experts (MoE) GPTOSS model support
  - Gemma3 4B vision-language model (VLM) support
  - 16K token context for LLMs on iGPU + NPU (hybrid)
  - Unified installer for LLM, VLM, and Stable Diffusion
  - BF16 inference latency improvements
- Link: https://www.amd.com/en/developer/resources/ryzen-ai-software.html
- Docs: https://ryzenai.docs.amd.com/

### AMD GAIA (v0.15, Jan 2026)
- Open-source SDK for building AI PC agents
- Runs local LLMs on Windows PCs optimized for Ryzen AI hardware
- Leverages AMD XDNA NPU for efficient, privacy-focused local inference
- Supports CPU and GPU execution as well
- Repositioned as framework and SDK for building AI PC agents
- GitHub: https://github.com/amd/gaia

### AMD Quark
- Cross-platform deep learning quantization toolkit
- Supports PyTorch and ONNX models
- ONNX-to-ONNX workflow delivers near-lossless accuracy
- 7x+ faster NPU inference vs CPU execution
- Link: https://www.amd.com/en/developer/resources/technical-articles/2025/ai-inference-acceleration-on-ryzen-ai-with-quark.html

### Vitis AI Execution Provider
- Execution provider for ONNX Runtime
- Intelligently routes workloads to NPU
- Optimizes for performance with lower power consumption
- Included in ONNX Runtime via AMD Ryzen AI Software SDK

### TurnkeyML & Lemonade
- TurnkeyML: No-code CLIs and low-code APIs for ONNX ecosystem
- Export and optimize ONNX models for CNNs and Transformers
- Lemonade: Serve and benchmark LLMs on CPU, GPU, and NPU

### ROCm AI Developer Hub
- Tutorials, blogs, open-source projects, self-learning courses
- AI development with ROCm
- Link: https://www.amd.com/en/developer/resources/rocm-hub/dev-ai.html

## Ryzen AI Software Stack Architecture

The Ryzen AI LLM software stack is available through three development interfaces:

1. **High-level Python APIs** — Quick prototyping and experimentation
2. **Native OnnxRuntime GenAI (OGA) libraries** — Production-ready inference
3. **Server Interface** — API-based model serving

All three interfaces leverage the **Lemonade SDK**, which is multi-vendor open-source software for getting started with LLMs on OGA or llama.cpp.

## Key Frameworks Supported

- PyTorch
- TensorFlow
- ONNX Runtime
- Hugging Face libraries
- llama.cpp
- ROS2 (Robotics)

## Ryzen AI Embedded (Announced Jan 2026)

AMD P100 and X100 Series processors:
- AMD "Zen 5" CPU cores
- RDNA 3.5 GPU for real-time visualization
- XDNA 2 NPU for energy-efficient AI acceleration
- All on a single chip with unified software stack

## Technology Recommendations for Slingshot Projects

While **no specific AMD technology mandates are enforced**, using AMD hardware/software likely gives an edge:

- **On-device/edge computing** and **low-power inference** are encouraged across multiple themes
- **Privacy-first / offline fallback** approaches are valued
- **Low-resource and edge-first designs** for everyday devices are called out
- Several themes implicitly favor AMD Ryzen AI-powered local inference

## Sources

- AMD Developer Cloud: https://www.amd.com/en/developer/resources/cloud-access/amd-developer-cloud.html
- AMD ROCm: https://www.amd.com/en/products/software/rocm.html
- AMD Ryzen AI Software: https://www.amd.com/en/developer/resources/ryzen-ai-software.html
- ROCm AI Developer Hub: https://www.amd.com/en/developer/resources/rocm-hub/dev-ai.html
- AMD Ryzen AI Software 1.7 Release: https://www.amd.com/en/developer/resources/technical-articles/2026/amd-ryzen-ai-software-1-7-release.html
- GitHub RyzenAI-SW: https://github.com/amd/RyzenAI-SW
- AMD Ryzen AI Docs: https://ryzenai.docs.amd.com/
