import asyncio
import concurrent.futures
import os
import tempfile
import time
import typing

import numpy as np

from helpers.decorators import capture_response
from helpers.logger import logger
from helpers.registry import register_job
from helpers.requirements import Requirement

# Cache the last working loopback device name to skip scanning on repeat calls
_cached_loopback_device: typing.Optional[str] = None


@register_job(
    module_name="shazam",
    requires=Requirement(
        pip_modules=["pyaudiowpatch", "shazamio", "soundfile", "numpy"],
        setup_hint="pip install -r requirements/shazam.txt",
    ),
    summary="Identify the song currently playing",
)
@capture_response
def identify_song() -> str:
    """
    [STANDALONE JOB] Identifies the song currently playing through the computer's
    speakers or headphones by recording a few seconds of system audio and matching
    it against Shazam.

    Use this job when the user wants to:
    - Know the name of the song that is currently playing
    - Find the artist of music they are hearing on this computer
    - Identify what track is playing right now

    Keywords: what song, what's playing, name this song, identify music, shazam,
              who sings this, what is this song, recognize song, what track,
              tell me the song, song name

    Returns:
        str: "<title> by <artist>" or a not-found / error message.
    """
    wav_path = _record_loopback_wav(seconds=5)
    if wav_path is None:
        return "I couldn't capture system audio. Make sure something is playing."
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            track = pool.submit(asyncio.run, _recognize(wav_path)).result()
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass
    if not track:
        return "I couldn't recognize that song. Try again during the chorus."
    return f"This is {track['title']} by {track['artist']}."


def _try_record_device(p: typing.Any, dev: dict, seconds: int) -> typing.Optional[np.ndarray]:
    import pyaudiowpatch as pyaudio

    sr = int(dev["defaultSampleRate"])
    channels = dev["maxInputChannels"]
    frames: typing.List[bytes] = []

    def _cb(in_data, frame_count, time_info, status):
        frames.append(in_data)
        return (in_data, pyaudio.paContinue)

    try:
        with p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=sr,
            frames_per_buffer=512,
            input=True,
            input_device_index=dev["index"],
            stream_callback=_cb,
        ):
            time.sleep(seconds)
    except Exception as e:
        logger.log_error(str(e), f"shazam._try_record_device({dev['name']})")
        return None

    if not frames:
        return None

    raw = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        raw = raw.reshape(-1, channels).mean(axis=1)
    return raw if np.abs(raw).max() >= 1e-4 else None


def _record_loopback_wav(seconds: int) -> typing.Optional[str]:
    global _cached_loopback_device
    try:
        import pyaudiowpatch as pyaudio
        import soundfile as sf

        with pyaudio.PyAudio() as p:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            all_loopbacks = list(p.get_loopback_device_info_generator())

            # Order: cached device first, then default-speaker match, then rest
            def _priority(dev: dict) -> int:
                if _cached_loopback_device and dev["name"] == _cached_loopback_device:
                    return 0
                if default_out["name"] in dev["name"]:
                    return 1
                return 2

            ordered = sorted(all_loopbacks, key=_priority)

            raw = sr = None
            for dev in ordered:
                result = _try_record_device(p, dev, seconds)
                if result is not None:
                    raw = result
                    sr = int(dev["defaultSampleRate"])
                    _cached_loopback_device = dev["name"]
                    break

        if raw is None:
            return None

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        sf.write(tmp.name, raw, sr)
        return tmp.name
    except Exception as e:
        logger.log_error(str(e), "shazam._record_loopback_wav")
        return None


async def _recognize(wav_path: str) -> typing.Optional[typing.Dict[str, str]]:
    try:
        from shazamio import Shazam

        out = await Shazam().recognize(wav_path)
        if not out.get("matches"):
            return None
        track = out.get("track", {})
        return {
            "title": track.get("title", "Unknown title"),
            "artist": track.get("subtitle", "Unknown artist"),
        }
    except Exception as e:
        logger.log_error(str(e), "shazam._recognize")
        return None
