"""Settings of the local language model (everything runs on this computer)."""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Folder with the downloaded model (Qwen2.5-1.5B-Instruct, Apache-2.0 licence).
try:
    from app_paths import MODELS_DIR as _MODELS_DIR
except ImportError:
    _MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
MODEL_DIR = os.path.join(_MODELS_DIR, "qwen2.5-1.5b-instruct")
MODEL_NAME = "Qwen2.5-1.5B-Instruct"

#: The GPU is used only when at least this much memory is free (weights ~3.1 GB + working room).
MIN_FREE_VRAM_GB = 3.8

MAX_NEW_TOKENS = 700        # longest reply (a full CNN example needs about 600)
MAX_INPUT_TOKENS = 2048     # longest prompt (oldest chat turns are dropped first)
TEMPERATURE = 0.3           # low: factual, steady answers
TOP_P = 0.9
REPETITION_PENALTY = 1.05

IDLE_UNLOAD_SECONDS = 300   # free the memory after this long without a question
