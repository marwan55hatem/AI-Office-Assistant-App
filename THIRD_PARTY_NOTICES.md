# Third-party notices

Each model, library and service keeps its own licence or terms.

## AI models in the desktop installer

| model | used for | licence |
|---|---|---|
| facebook/bart-large-cnn (Meta) | summaries | MIT |
| Helsinki-NLP/opus-mt-* (12 pairs, University of Helsinki) | translation | CC-BY-4.0 — attribution: "OPUS-MT, Tiedemann & Thottingal, EAMT 2020" |
| YOLO12n (Ultralytics) | person/phone detection | **AGPL-3.0** |
| assistant/intent_model.pt | chat intent classifier | this project (MIT) |

Version 1 also bundled Qwen2.5-1.5B-Instruct (Apache-2.0); version 2 no longer ships it.

## Online services

| service | used for | terms |
|---|---|---|
| Groq, model `openai/gpt-oss-120b` (Apache-2.0 weights) | general and document questions in AI Chat | Groq's terms of service and privacy policy |
| Resend (or SMTP / SendGrid, chosen by the operator) | e-mail | the provider's terms |
| GitHub Releases | installer downloads | GitHub's terms |

## Desktop app libraries

| library | licence |
|---|---|
| Python 3.12 | PSF |
| PyQt5 / Qt 5.15 (incl. QtWebSockets) | **GPL-3.0** (PyQt5) / LGPL-3.0 (Qt) |
| PyTorch, torchvision | BSD-3-Clause |
| NVIDIA CUDA runtime (in the torch wheel) | NVIDIA CUDA EULA (redistributable components) |
| transformers, huggingface_hub, safetensors | Apache-2.0 |
| sentencepiece | Apache-2.0 |
| ultralytics | **AGPL-3.0** |
| OpenCV | Apache-2.0 |
| NumPy | BSD-3-Clause |
| PyMuPDF | **AGPL-3.0** (or commercial) |
| httpx, keyring | BSD-3-Clause / MIT |
| pywin32 | PSF |
| PyInstaller bootloader | GPL-2.0 with bootloader exception |

## Online service (backend) libraries

FastAPI (MIT), Starlette (BSD-3-Clause), Uvicorn (BSD-3-Clause), SQLAlchemy (MIT), Alembic (MIT),
psycopg 3 (LGPL-3.0), Pydantic (MIT), argon2-cffi (MIT), PyJWT (MIT), httpx (BSD-3-Clause),
PostgreSQL (PostgreSQL licence).

## Website libraries

Next.js (MIT), React (MIT), IBM Plex Mono / IBM Plex Sans Arabic (SIL OFL 1.1), Manrope (SIL OFL 1.1);
development only: Playwright (Apache-2.0), axe-core (MPL-2.0), Vitest (MIT), Testing Library (MIT),
ESLint (MIT), TypeScript (Apache-2.0).

## What this means

PyQt5, ultralytics and PyMuPDF are copyleft (GPL/AGPL). Distributing the desktop app is fine for this
non-commercial university project as long as the source code is available to its users (it is public on
GitHub). A **commercial, closed-source** release would need commercial licences for PyQt5, Ultralytics
and PyMuPDF, or replacements (e.g. PySide6 — LGPL, a different detector, pypdf).
