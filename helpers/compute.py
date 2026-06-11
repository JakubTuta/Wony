"""Central compute-device probe — single source of truth for CUDA/GPU availability."""
import importlib
import os
import sys
import typing


_GPU_FIX_HINT = (
    "GPU not in use. If you have an NVIDIA GPU: "
    "pip install -r requirements/voice.txt, update your GPU driver, "
    "and ensure nvidia-cudnn-cu12 + nvidia-cublas-cu12 are installed. "
    "CPU is a fully supported fallback but is slower."
)


def ctranslate2_cuda_count() -> int:
    """Return number of CUDA devices visible to ctranslate2. 0 on any failure."""
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def onnx_cuda_available() -> bool:
    """True if CUDAExecutionProvider is available in onnxruntime."""
    try:
        import onnxruntime as ort
        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def nvidia_dll_wheels_present() -> bool:
    """True if nvidia-cudnn or nvidia-cublas pip wheels have their bin/ dirs present (Windows)."""
    if sys.platform != "win32":
        return False
    for pkg_name in ("nvidia.cudnn", "nvidia.cublas"):
        try:
            pkg = importlib.import_module(pkg_name)
            pkg_root = next(iter(getattr(pkg, "__path__", [])), None)
            if pkg_root and os.path.isdir(os.path.join(pkg_root, "bin")):
                return True
        except Exception:
            pass
    return False


def compute_status() -> typing.Dict:
    """Return a dict with stt_device, tts_device, cuda_ok, and hint."""
    stt_cuda = ctranslate2_cuda_count() > 0
    tts_cuda = onnx_cuda_available()
    cuda_ok = stt_cuda or tts_cuda

    hint: typing.Optional[str] = None
    if not cuda_ok:
        hint = _GPU_FIX_HINT

    return {
        "stt_device": "GPU" if stt_cuda else "CPU",
        "tts_device": "GPU" if tts_cuda else "CPU",
        "cuda_ok": cuda_ok,
        "hint": hint or "",
    }


def describe_compute() -> typing.List[str]:
    """Return formatted lines for doctor output."""
    st = compute_status()
    lines = ["\n  Compute devices:"]
    stt_label = "GPU (large-v3)" if st["stt_device"] == "GPU" else "CPU (distil-small.en / small)"
    tts_label = "GPU (CUDAExecutionProvider)" if st["tts_device"] == "GPU" else "CPU (CPUExecutionProvider)"
    lines.append(f"    STT (Whisper)  : {stt_label}")
    lines.append(f"    TTS (Kokoro)   : {tts_label}")
    if not st["cuda_ok"]:
        lines.append(f"    ! {_GPU_FIX_HINT}")
    else:
        lines.append("    ✓ CUDA acceleration active.")
    return lines
