"""
Record yourself saying the wake word, for training/my_recordings/.

    python training/record_wake_word.py
    python training/record_wake_word.py "hey wony" --count 20

Uses the same VAD capture Wony itself uses for commands (helpers.mic), so
each clip is auto-trimmed to the speech (silence before/after dropped) with
no editing needed — say the phrase after the prompt, then stop; a short
pause ends the clip automatically. Run this from the Wony repo's own
Python (the "Voice I/O" feature's dependencies must be installed), not the
WSL/Colab training environment — it wants your real microphone, and setup.py
already gave the venv here access to it.

Saved clips are picked up automatically by train_hey_wony.sh, or upload them
to Colab's my_recordings/ folder for train_hey_wony.ipynb.
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUTDIR_DEFAULT = os.path.join(ROOT, "training", "my_recordings")


def _default_phrase() -> str:
    try:
        from helpers.config import Config
        Config.load()
        phrase = str(Config.get("voice.wake_word.phrase", "") or "").strip()
        return phrase or "hey wony"
    except Exception:
        return "hey wony"


def _safe_stem(phrase: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_") or "wake_word"


def _next_index(outdir: str, stem: str) -> int:
    existing = [f for f in os.listdir(outdir) if f.startswith(stem + "_") and f.endswith(".wav")]
    nums = [int(m.group(1)) for f in existing if (m := re.match(rf"{re.escape(stem)}_(\d+)\.wav$", f))]
    return max(nums, default=0) + 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("phrase", nargs="?", default=None, help="Wake phrase to record (default: voice.wake_word.phrase from config.yaml)")
    parser.add_argument("--count", type=int, default=15, help="Number of clips to record (default: 15)")
    parser.add_argument("--outdir", default=OUTDIR_DEFAULT, help="Where to save clips (default: training/my_recordings)")
    args = parser.parse_args()

    try:
        import soundfile as sf
        from helpers import mic
    except ImportError as e:
        print(f"Missing dependency ({e}). This needs the Voice I/O feature installed —"
              " run 'python setup.py', select it, and try again.")
        sys.exit(1)

    phrase = args.phrase or _default_phrase()
    stem = _safe_stem(phrase)
    os.makedirs(args.outdir, exist_ok=True)

    print(f"Recording '{phrase}' — {args.count} clips into {args.outdir}")
    print("Press Enter, then say the phrase. It stops automatically after you go quiet.")
    print("Ctrl+C at any point to stop early and keep what you've recorded so far.\n")

    saved = 0
    index = _next_index(args.outdir, stem)
    try:
        while saved < args.count:
            input(f"[{saved + 1}/{args.count}] Enter to record, then say '{phrase}'... ")
            audio = mic.record_until_silence(max_seconds=4.0, start_timeout=5.0, silence_ms=500)
            if audio is None or len(audio) == 0:
                print("  Didn't catch anything — try again.")
                continue

            duration = len(audio) / 16000.0
            if duration < 0.3:
                print(f"  Too short ({duration:.2f}s) — try again, a bit slower.")
                continue

            path = os.path.join(args.outdir, f"{stem}_{index}.wav")
            sf.write(path, audio, 16000, subtype="PCM_16")
            print(f"  Saved {os.path.basename(path)} ({duration:.2f}s)")
            index += 1
            saved += 1
    except KeyboardInterrupt:
        print()

    print(f"\nDone — {saved} clip(s) in {args.outdir}.")
    if saved:
        print("Next: run training/train_hey_wony.sh (WSL) or upload this folder's clips")
        print("to my_recordings/ in train_hey_wony.ipynb (Colab), then train as usual.")


if __name__ == "__main__":
    main()
