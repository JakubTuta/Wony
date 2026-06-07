"""
Download Kokoro TTS model files to models/.

Run once after initial setup:
    python scripts/download_kokoro.py

Files are skipped if already present. Use --force to re-download.
"""

import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = [
    "kokoro-v1.0.onnx",
    "voices-v1.0.bin",
]


def _progress(block: int, block_size: int, total: int) -> None:
    downloaded = block * block_size
    if total > 0:
        pct = min(100, downloaded * 100 // total)
        mb = downloaded / 1_048_576
        total_mb = total / 1_048_576
        print(f"\r  {pct:3d}%  {mb:.1f} / {total_mb:.1f} MB", end="", flush=True)


def main() -> None:
    force = "--force" in sys.argv or "-f" in sys.argv
    models_dir = os.path.join(ROOT, "models")
    os.makedirs(models_dir, exist_ok=True)

    for name in FILES:
        dest = os.path.join(models_dir, name)
        if not force and os.path.exists(dest):
            print(f"  skip (exists)  models/{name}")
            continue
        url = BASE_URL + name
        print(f"  downloading    models/{name}  ({url})")
        try:
            urllib.request.urlretrieve(url, dest, reporthook=_progress)
            print()  # newline after progress
            print(f"  done           models/{name}")
        except Exception as e:
            print(f"\n  ERROR          models/{name}: {e}")
            sys.exit(1)

    print("\nAll Kokoro model files ready.")


if __name__ == "__main__":
    main()
