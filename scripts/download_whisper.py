"""
Download the faster-whisper (STT) model to the Hugging Face cache.

Run once after initial setup (setup.py does this automatically for the
"Voice I/O" feature):
    python scripts/download_whisper.py

Picks the same model faster-whisper would pick at runtime (see
helpers/compute.py:stt_device + helpers/recognizer.py:_build_model) — GPU
machines get large-v3, CPU-only machines get distil-small.en (English) or
small. Downloading here means the runtime path can load with
local_files_only=True and never touch the network again.
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _has_nvidia_gpu() -> bool:
    return shutil.which("nvidia-smi") is not None


def _language() -> str:
    """Best-effort read of assistant.language from config.yaml (falls back to 'en')."""
    try:
        from helpers.config import Config
        Config.load()
        return str(Config.get("assistant.language", "en")).lower()
    except Exception:
        return "en"


def main() -> None:
    from faster_whisper import WhisperModel

    gpu = _has_nvidia_gpu()
    language = _language()

    if gpu:
        # distil-large-v3 is English-only; non-English languages need the
        # full multilingual large-v3 — mirrors helpers/recognizer.py.
        if language.startswith("en"):
            model_size, device, compute_type = "distil-large-v3", "cuda", "float16"
        else:
            model_size, device, compute_type = "large-v3", "cuda", "float16"
    elif language.startswith("en"):
        model_size, device, compute_type = "distil-small.en", "cpu", "int8"
    else:
        model_size, device, compute_type = "small", "cpu", "int8"

    print(f"  Downloading STT model '{model_size}' ({device}/{compute_type})...")
    print("  (this can take a few minutes on the first run — model is ~0.5-1.5 GB)")
    try:
        WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        print(f"  ERROR downloading '{model_size}': {e}")
        if gpu:
            print("  Falling back to CPU model download so voice mode still has something cached...")
            try:
                fallback = "distil-small.en" if language.startswith("en") else "small"
                WhisperModel(fallback, device="cpu", compute_type="int8")
            except Exception as e2:
                print(f"  ERROR downloading fallback '{fallback}': {e2}")
                sys.exit(1)
        else:
            sys.exit(1)

    print(f"  done           STT model '{model_size}' cached.")


if __name__ == "__main__":
    main()
