"""Download every AI model the app uses into ``models/`` (run once before building the installer).

    python tools/fetch_models.py            # download what is missing
    python tools/fetch_models.py --check    # only report what is present / missing

After this the application, and the installer built from it, run with no internet:

* ``models/qwen2.5-1.5b-instruct``     the chat model (Apache-2.0)
* ``models/hf/bart-large-cnn``         the summariser (MIT)
* ``models/hf/opus-mt-<src>-<tgt>``    the 12 MarianMT translation pairs (CC-BY-4.0)
* ``models/yolo12n.pt``                person / phone detection (AGPL-3.0)

Only the files needed for inference are fetched (safetensors weights when the repository
has them, otherwise ``pytorch_model.bin``; no TensorFlow / Flax / Rust copies).  Running it
again skips what is already complete.
"""

import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")      # the Xet transfer backend stalls on some networks

import app_paths  # noqa: E402
from assistant.summarizer import BART_MODEL_NAME  # noqa: E402
from assistant.translator import DIRECT_MODELS  # noqa: E402

QWEN_REPO = "Qwen/Qwen2.5-1.5B-Instruct"
QWEN_DIR = os.path.join(app_paths.MODELS_DIR, "qwen2.5-1.5b-instruct")
YOLO_FILE = os.path.join(app_paths.MODELS_DIR, "yolo12n.pt")
YOLO_URL_NAME = "yolo12n.pt"
TOKENIZER_FILES = ["*.json", "*.txt", "*.model", "*.spm", "vocab*", "merges.txt", "LICENSE*", "README.md"]


def folder_size(path):
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, files in os.walk(path) for f in files)


def complete(path):
    has_weights = any(os.path.isfile(os.path.join(path, w)) for w in ("model.safetensors", "pytorch_model.bin"))
    return os.path.isfile(os.path.join(path, "config.json")) and has_weights


def hf_targets():
    """``[(repo_id, local_dir)]`` for every Hugging Face model the app loads."""
    targets = [(QWEN_REPO, QWEN_DIR)]
    for repo in [BART_MODEL_NAME] + sorted(set(DIRECT_MODELS.values())):
        targets.append((repo, os.path.join(app_paths.HF_MODELS_DIR, repo.split("/")[-1])))
    return targets


def download_hf(repo, local_dir):
    from huggingface_hub import model_info, snapshot_download

    files = {s.rfilename for s in model_info(repo).siblings}
    weights = ["model.safetensors"] if "model.safetensors" in files else ["pytorch_model.bin"]
    snapshot_download(repo, local_dir=local_dir, allow_patterns=TOKENIZER_FILES + weights)
    cache = os.path.join(local_dir, ".cache")
    if os.path.isdir(cache):
        shutil.rmtree(cache, ignore_errors=True)       # download bookkeeping, not needed at run time


def download_yolo():
    from ultralytics import YOLO

    os.makedirs(app_paths.MODELS_DIR, exist_ok=True)
    cwd = os.getcwd()
    try:
        os.chdir(app_paths.MODELS_DIR)                 # ultralytics downloads into the working folder
        YOLO(YOLO_URL_NAME)
    finally:
        os.chdir(cwd)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only report, do not download")
    args = parser.parse_args()

    missing = 0
    for repo, local_dir in hf_targets():
        if complete(local_dir):
            print("ok       %-40s %6.0f MB" % (repo, folder_size(local_dir) / 1e6))
            continue
        missing += 1
        if args.check:
            print("MISSING  %s" % repo)
            continue
        print("download %s ..." % repo, flush=True)
        download_hf(repo, local_dir)
        print("         %-40s %6.0f MB" % (repo, folder_size(local_dir) / 1e6))
    if os.path.isfile(YOLO_FILE):
        print("ok       %-40s %6.0f MB" % ("yolo12n.pt", os.path.getsize(YOLO_FILE) / 1e6))
    elif args.check:
        missing += 1
        print("MISSING  yolo12n.pt")
    else:
        download_yolo()
    print("models folder: %.2f GB" % (folder_size(app_paths.MODELS_DIR) / 1e9))
    return 1 if (args.check and missing) else 0


if __name__ == "__main__":
    sys.exit(main())
