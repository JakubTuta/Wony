#!/usr/bin/env bash
# Train "Hey Wony" custom wake word using openWakeWord.
# Run inside WSL: bash /mnt/d/Projekty/Wony/training/train_hey_wony.sh
#
# Output: /mnt/d/Projekty/Wony/models/hey_wony.onnx
# Time:   ~1-2h on RTX 4060

set -e
trap 'echo "ERROR at line $LINENO: $BASH_COMMAND" >&2' ERR

WORKDIR="/mnt/d/Projekty/Wony/training"
VENV="$HOME/hey_wony_venv"   # WSL home — avoids NTFS symlink issues
WONY_MODELS="/mnt/d/Projekty/Wony/models"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { echo -e "\n${GREEN}▶ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

# ── 0. Preflight ──────────────────────────────────────────────────────────────
step "Preflight checks"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null \
  && echo "GPU detected." \
  || warn "No GPU detected — training will be slow on CPU."
python3 --version || { echo "python3 not found"; exit 1; }

# Install system tools upfront so set -e doesn't bite us mid-step
sudo apt-get update -qq
sudo apt-get install -y -qq unzip ffmpeg

mkdir -p "$WORKDIR" "$WONY_MODELS"
cd "$WORKDIR"
echo "Working directory: $WORKDIR"

# ── Create venv (solves externally-managed-environment on Ubuntu 23.04+) ──────
# piper-phonemize has no Python 3.12 wheel — use 3.11
PY311=$(which python3.11 2>/dev/null || true)
if [ -z "$PY311" ]; then
  step "Installing Python 3.11 (deadsnakes PPA)"
  sudo apt-get install -y -qq software-properties-common
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3.11 python3.11-venv python3.11-distutils python3.11-dev
  PY311=$(which python3.11)
fi

# Recreate venv if it's not Python 3.11
VENV_VER=$("$VENV/bin/python3" --version 2>/dev/null || echo "none")
if [[ "$VENV_VER" != *"3.11"* ]]; then
  step "Creating virtual environment (Python 3.11)"
  rm -rf "$VENV"
  "$PY311" -m venv "$VENV"
fi

# All commands below use the venv
PY="$VENV/bin/python3"
PIP="$VENV/bin/pip"

$PIP install -q --upgrade pip

# ── 1. Install dependencies ───────────────────────────────────────────────────
step "Installing dependencies"

# CUDA-enabled PyTorch (RTX 4060 / cu121) — install first so other deps pick it up
$PIP install -q torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# Piper TTS sample generator
if [ ! -f "piper-sample-generator/generate_samples.py" ]; then
  rm -rf piper-sample-generator
  git clone --branch v2.0.0 --depth 1 https://github.com/rhasspy/piper-sample-generator
fi
if [ ! -f "piper-sample-generator/models/en_US-libritts_r-medium.pt" ]; then
  wget -q --show-progress -O piper-sample-generator/models/en_US-libritts_r-medium.pt \
    'https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt'
fi
$PIP install -q \
  "https://github.com/rhasspy/piper-phonemize/releases/download/v1.1.0/piper_phonemize-1.1.0-cp311-cp311-manylinux_2_28_x86_64.whl" \
  webrtcvad

# openWakeWord
if [ ! -d "openwakeword" ]; then
  git clone https://github.com/dscripka/openwakeword
fi
$PIP install -q -e ./openwakeword

# Download required ONNX feature models (download_models() API inconsistent across versions)
OWW_MODELS="openwakeword/openwakeword/resources/models"
mkdir -p "$OWW_MODELS"
for MODEL in melspectrogram.onnx embedding_model.onnx; do
  if [ ! -f "$OWW_MODELS/$MODEL" ]; then
    wget -q --show-progress \
      "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/$MODEL" \
      -O "$OWW_MODELS/$MODEL"
  fi
done

# Training + audio deps (no tensorflow — only needed for optional tflite, not onnx)
$PIP install -q \
  mutagen==1.47.0 \
  torchinfo==1.8.0 \
  torchmetrics==1.2.0 \
  speechbrain==0.5.14 \
  audiomentations==0.33.0 \
  torch-audiomentations==0.11.0 \
  acoustics==0.2.6 \
  "scipy<1.15" \
  pronouncing==0.2.0 \
  "numpy<2" \
  "pyarrow>=12,<14" \
  "datasets==2.14.6" \
  deep-phonemizer==0.0.19 \
  soundfile soxr librosa \
  onnx

echo "Dependencies installed."

# ── 2. Download Room Impulse Responses ───────────────────────────────────────
step "Downloading MIT Room Impulse Responses"
mkdir -p mit_rirs

$PY - <<'PYEOF'
import os, datasets, librosa, scipy.io.wavfile, numpy as np

output_dir = "./mit_rirs"
if len(os.listdir(output_dir)) > 0:
    print(f"RIRs already present ({len(os.listdir(output_dir))} files), skipping.")
else:
    # Non-streaming load — downloads and decodes audio locally via soundfile
    ds = datasets.load_dataset(
        "davidscripka/MIT_environmental_impulse_responses",
        split="train"
    )
    for i, row in enumerate(ds):
        arr = row['audio']['array']
        sr  = row['audio']['sampling_rate']
        path = (row['audio'].get('path') or '')
        name = path.split('/')[-1] if path else f'rir_{i:05d}.wav'
        if not name.endswith('.wav'):
            name = f'rir_{i:05d}.wav'
        if sr != 16000:
            arr = librosa.resample(arr, orig_sr=sr, target_sr=16000)
        scipy.io.wavfile.write(
            f"{output_dir}/{name}", 16000,
            (arr * 32767).astype(np.int16)
        )
    print(f"RIRs saved: {len(os.listdir(output_dir))} files")
PYEOF

# ── 3. Download background noise ─────────────────────────────────────────────
step "Downloading background noise (ESC-50 + MUSAN)"

# Download archives first
mkdir -p background_noise
if [ ! -f "esc50.zip" ]; then
  wget -q --show-progress https://github.com/karoldvl/ESC-50/archive/master.zip -O esc50.zip
fi
if [ ! -d "ESC-50-master/audio" ]; then
  rm -rf ESC-50-master
  unzip -q esc50.zip
fi
if [ ! -f "musan.tar.gz" ]; then
  wget -q --show-progress http://www.openslr.org/resources/17/musan.tar.gz -O musan.tar.gz
fi
if [ ! -d "musan/noise" ]; then
  tar -xzf musan.tar.gz
fi

# Convert using Python — avoids bash path-passing issues on NTFS/WSL
$PY - <<'PYEOF'
import os, subprocess, glob

os.makedirs("background_noise", exist_ok=True)
noise_count = len(os.listdir("background_noise"))
if noise_count >= 100:
    print(f"Background noise already present ({noise_count} files), skipping.")
else:
    workdir = os.path.abspath(".")

    def convert(src, dst):
        if os.path.exists(dst):
            return
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", dst, "-loglevel", "error"],
            capture_output=True, text=True
        )
        if r.returncode != 0:
            print(f"  skip {os.path.basename(src)}: {r.stderr.strip()[:120]}")

    esc_files = glob.glob(os.path.join(workdir, "ESC-50-master", "audio", "*.wav"))
    print(f"Converting {len(esc_files)} ESC-50 files...")
    for f in esc_files:
        convert(f, os.path.join(workdir, "background_noise", os.path.basename(f)))
    print(f"  ESC-50 done. Total: {len(os.listdir('background_noise'))} files")

    musan_files = (
        glob.glob(os.path.join(workdir, "musan", "noise", "**", "*.wav"), recursive=True) +
        glob.glob(os.path.join(workdir, "musan", "music", "**", "*.wav"), recursive=True)
    )
    print(f"Converting {len(musan_files)} MUSAN files...")
    for f in musan_files:
        convert(f, os.path.join(workdir, "background_noise", "musan_" + os.path.basename(f)))
    print(f"Background noise total: {len(os.listdir('background_noise'))} files")
PYEOF

# ── 4. Download pre-computed features ────────────────────────────────────────
step "Downloading pre-computed features"

if [ ! -f "openwakeword_features_ACAV100M_2000_hrs_16bit.npy" ]; then
  wget --show-progress \
    'https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy'
else
  echo "ACAV100M features already present, skipping."
fi

if [ ! -f "validation_set_features.npy" ]; then
  wget --show-progress \
    'https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/validation_set_features.npy'
else
  echo "Validation features already present, skipping."
fi

# ── 5. Write training config ──────────────────────────────────────────────────
step "Writing training config"

$PY - <<'PYEOF'
import os, yaml

config = yaml.load(
    open("openwakeword/examples/custom_model.yml").read(),
    yaml.Loader
)

config["target_phrase"]             = ["hey wony", "hey wany", "hey woney"]
config["model_name"]                = "hey_wony"
config["output_dir"]                = os.path.abspath("./hey_wony")
config["piper_sample_generator_path"] = os.path.abspath("./piper-sample-generator")
config["n_samples"]       = 30000
config["n_samples_val"]   = 2000
config["steps"]           = 50000
config["target_accuracy"] = 0.7
config["target_recall"]   = 0.5
config["rir_paths"]        = [os.path.abspath("./mit_rirs")]
config["background_paths"] = [os.path.abspath("./background_noise")]
config["false_positive_validation_data_path"] = os.path.abspath("validation_set_features.npy")
config["feature_data_files"] = {
    "ACAV100M_sample": os.path.abspath("openwakeword_features_ACAV100M_2000_hrs_16bit.npy")
}

with open("hey_wony.yaml", "w") as f:
    yaml.dump(config, f)

print("Config written:")
for k in ["target_phrase", "model_name", "output_dir", "n_samples", "steps", "background_paths"]:
    print(f"  {k}: {config[k]}")
PYEOF

# ── 6. Generate synthetic clips ───────────────────────────────────────────────
step "Phase 1/3 — Generating synthetic clips (TTS)"
$PY openwakeword/openwakeword/train.py \
  --training_config hey_wony.yaml \
  --generate_clips

# ── 7. Augment clips ──────────────────────────────────────────────────────────
step "Phase 2/3 — Augmenting clips with room acoustics + noise"
$PY openwakeword/openwakeword/train.py \
  --training_config hey_wony.yaml \
  --augment_clips

# ── 8. Train model ────────────────────────────────────────────────────────────
step "Phase 3/3 — Training model (this takes a while)"
# || true: train.py exits non-zero after saving .onnx if onnx_tf isn't installed (tflite step).
# The .onnx is saved before that failure, so we catch it below.
$PY openwakeword/openwakeword/train.py \
  --training_config hey_wony.yaml \
  --train_model || true

ONNX_OUT=$(find ./hey_wony -name "hey_wony.onnx" 2>/dev/null | head -1)
if [ -z "$ONNX_OUT" ]; then
  echo "ERROR: Training failed — hey_wony.onnx not produced. Check output above."
  exit 1
fi
echo "Model saved: $ONNX_OUT"

# ── 9. Copy output to Wony repo ───────────────────────────────────────────────
step "Copying model to Wony repo"

ONNX=$(find ./hey_wony -name "hey_wony.onnx" 2>/dev/null | head -1)
[ -z "$ONNX" ] && ONNX=$(find . -name "hey_wony.onnx" | head -1)
if [ -z "$ONNX" ]; then
  echo "ERROR: hey_wony.onnx not found — check training output above."
  exit 1
fi

cp "$ONNX" "$WONY_MODELS/hey_wony.onnx"
echo "Copied to $WONY_MODELS/hey_wony.onnx"

echo ""
echo -e "${GREEN}✓ Done!${NC}"
echo ""
echo "Next steps — in config.yaml set:"
echo "  voice:"
echo "    wake_word:"
echo "      enabled: true"
echo "      model_path: models/hey_wony.onnx"
echo "      threshold: 0.5"
