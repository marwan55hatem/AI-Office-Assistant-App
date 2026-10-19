# Third-party notices

The installer bundles the following models and libraries. Each keeps its own licence.

## AI models

| model | used for | licence |
|---|---|---|
| Qwen2.5-1.5B-Instruct (Alibaba Cloud) | AI Chat | Apache-2.0 |
| facebook/bart-large-cnn (Meta) | summaries | MIT |
| Helsinki-NLP/opus-mt-* (12 pairs, University of Helsinki) | translation | CC-BY-4.0 — attribution: "OPUS-MT, Tiedemann & Thottingal, EAMT 2020" |
| YOLO12n (Ultralytics) | person/phone detection | **AGPL-3.0** |
| assistant/intent_model.pt | chat intent classifier | this project (MIT) |

## Libraries

| library | licence |
|---|---|
| Python 3.12 | PSF |
| PyQt5 / Qt 5.15 | **GPL-3.0** (PyQt5) / LGPL-3.0 (Qt) |
| PyTorch, torchvision | BSD-3-Clause |
| NVIDIA CUDA runtime (in the torch wheel) | NVIDIA CUDA EULA (redistributable components) |
| transformers, huggingface_hub, safetensors | Apache-2.0 |
| sentencepiece | Apache-2.0 |
| ultralytics | **AGPL-3.0** |
| OpenCV | Apache-2.0 |
| NumPy | BSD-3-Clause |
| PyMuPDF | **AGPL-3.0** (or commercial) |
| pywin32 | PSF |
| PyInstaller bootloader | GPL-2.0 with bootloader exception |

## What this means

PyQt5, ultralytics and PyMuPDF are copyleft (GPL/AGPL). Distributing the installed application is fine for
this non-commercial university project as long as the source code is available to its users (it is
included with the project). A **commercial, closed-source** release would need commercial licences for
PyQt5, Ultralytics and PyMuPDF, or replacements (e.g. PySide6 — LGPL, a different detector, pypdf).
