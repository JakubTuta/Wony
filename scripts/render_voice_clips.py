"""
Render fixed TTS phrases to WAV files in voice/bot/.

Run this after initial setup or whenever you change voice settings
(voice.rate, voice.volume, voice.tts_voice_index in config.yaml):

    python scripts/render_voice_clips.py

The rendered WAVs are used by Audio.play_cached() for near-zero-latency
playback of common phrases (e.g. the "Yes?" wake-word acknowledgement).
"""

import os
import sys

# Allow running from project root or from scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> None:
    from helpers.audio import CACHED_CLIPS, TTS_Engine

    engine = TTS_Engine()

    total = len(CACHED_CLIPS)
    rendered = 0
    skipped = 0

    force = "--force" in sys.argv or "-f" in sys.argv

    for text, path in CACHED_CLIPS.items():
        abs_path = os.path.join(ROOT, path)
        if not force and os.path.exists(abs_path):
            print(f"  skip (exists)  {path}")
            skipped += 1
            continue

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        try:
            engine.save_text_to_file(text, abs_path)
            print(f"  rendered       {path}  ({text!r})")
            rendered += 1
        except Exception as e:
            print(f"  ERROR          {path}  ({text!r}): {e}")

    print(f"\nDone: {rendered} rendered, {skipped} skipped (pass --force to re-render all).")


if __name__ == "__main__":
    main()
