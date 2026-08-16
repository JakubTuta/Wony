#!/usr/bin/env bash
# Train a custom wake word for Wony using openWakeWord.
# Run inside WSL: bash /mnt/d/Projekty/Wony/training/train_hey_wony.sh
#
# Trains whatever phrase you set in "What to train" below — "hey wony" is only
# the default. Output: /mnt/d/Projekty/Wony/models/<your_phrase>.onnx
# Time: ~4-6h on an RTX 4060. Safe to interrupt — re-running resumes.
#
#   --fresh   delete previously generated clips/features and start over. Use it
#             whenever you change the phrase or sample counts, so clips from the
#             old settings don't get mixed into the new run.

set -e
trap 'echo "ERROR at line $LINENO: $BASH_COMMAND" >&2' ERR

WORKDIR="/mnt/d/Projekty/Wony/training"
VENV="$HOME/hey_wony_venv"   # WSL home — avoids NTFS symlink issues
WONY_MODELS="/mnt/d/Projekty/Wony/models"

FRESH=0
if [ "${1:-}" = "--fresh" ]; then FRESH=1; fi

# ── What to train ─────────────────────────────────────────────────────────────
# The phrase you say out loud. Two syllables or more works best — very short
# words trigger on everything.
export WAKE_PHRASE="hey wony"

# Optional extra spellings of the SAME phrase, one per line (leave empty for
# ordinary English words). The training clips are synthesized by a TTS engine
# that pronounces text the way English spelling implies, so an invented or
# non-English name can come out sounding nothing like how you actually say it —
# and a model trained on that will never fire on your voice. Extra spellings
# make the clips cover a range of pronunciations instead of one guess. Step 7
# below lets you hear what was generated before the long training starts.
export WAKE_PHRASE_VARIANTS="hey woney
hey woni
hey wany
hay wony"

# Positive samples to synthesize. openWakeWord's docs: 20k minimum, 100k+ is
# usually best — and this is the setting that most affects whether the model
# generalizes from synthetic voices to a real human one.
export N_SAMPLES=100000

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
step() { echo -e "\n${GREEN}▶ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

# File-safe name derived from the phrase: "hey wony" → "hey_wony"
MODEL_NAME=$(echo "$WAKE_PHRASE" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '_' | sed 's/^_//; s/_$//')
export MODEL_NAME

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
echo "Training phrase:   '$WAKE_PHRASE'  →  $MODEL_NAME.onnx"

if [ "$FRESH" = "1" ]; then
  step "Fresh start — deleting previously generated clips and features"
  rm -rf "$WORKDIR/$MODEL_NAME"
fi

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

phrase   = os.environ["WAKE_PHRASE"].strip()
variants = [v.strip() for v in os.environ.get("WAKE_PHRASE_VARIANTS", "").splitlines() if v.strip()]

config["target_phrase"]               = [phrase] + variants
config["model_name"]                  = os.environ["MODEL_NAME"]
config["output_dir"]                  = os.path.abspath("./" + os.environ["MODEL_NAME"])
config["piper_sample_generator_path"] = os.path.abspath("./piper-sample-generator")

# ── Robustness on REAL voice ──────────────────────────────────────────────
# A model trained only on synthetic speech can end up firing on TTS clips but
# not on a human — the fix is more acoustic variety in the positives, plus a
# checkpoint chosen for recall rather than minimum false positives.
config["n_samples"]     = int(os.environ["N_SAMPLES"])
config["n_samples_val"] = max(2000, int(os.environ["N_SAMPLES"]) // 20)
config["steps"]         = 50000
config["max_negative_weight"] = 1000              # less suppression of positives
config["target_false_positives_per_hour"] = 0.5   # allow a more sensitive checkpoint
# augmentation_rounds is deliberately 1: train.py multiplies the clip list by it
# but still passes n_total=<unique clip count> to compute_features_from_generator,
# which stops at n_total rows — so rounds > 1 costs extra augmentation time and
# then throws the extra rounds away. Put the budget into n_samples instead.
config["augmentation_rounds"] = 1
# NOTE: target_accuracy / target_recall are NOT read by auto_train (it selects
# the best checkpoint by recall under target_false_positives_per_hour), so they
# are intentionally omitted.
config["rir_paths"]        = [os.path.abspath("./mit_rirs")]
config["background_paths"] = [os.path.abspath("./background_noise")]
config["false_positive_validation_data_path"] = os.path.abspath("validation_set_features.npy")
config["feature_data_files"] = {
    "ACAV100M_sample": os.path.abspath("openwakeword_features_ACAV100M_2000_hrs_16bit.npy")
}

with open(os.environ["MODEL_NAME"] + ".yaml", "w") as f:
    yaml.dump(config, f)

print("Config written:")
for k in ["target_phrase", "model_name", "output_dir", "n_samples", "steps", "background_paths"]:
    print(f"  {k}: {config[k]}")
PYEOF

CONFIG="$MODEL_NAME.yaml"

# ── 6. Generate synthetic clips ───────────────────────────────────────────────
step "Phase 1/3 — Generating synthetic clips (TTS)"
$PY openwakeword/openwakeword/train.py \
  --training_config "$CONFIG" \
  --generate_clips

POS_DIR="$WORKDIR/$MODEL_NAME/$MODEL_NAME/positive_train"

# ── 6b. Optional: mix in your own recordings ─────────────────────────────────
# train.py's augmentation step simply globs positive_train/*.wav, so dropping
# real recordings in here is all it takes to include them in training.
step "Checking for your own recordings (optional)"

REC_DIR="$WORKDIR/my_recordings"
mkdir -p "$REC_DIR"

# Drop copies added by a previous run first, so re-running never stacks them up.
rm -f "$POS_DIR"/mine_*.wav

REC_COUNT=$(find "$REC_DIR" -type f \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.ogg' -o -iname '*.flac' \) | wc -l)
if [ "$REC_COUNT" -eq 0 ]; then
  echo "No recordings in $REC_DIR — training on synthetic voices only."
  echo "That works. To make the model fit YOUR voice better, see README →"
  echo "'Training a custom wake word' → 'Optional: add your own voice'."
else
  # Aim for roughly 5% of the positives so real speech carries weight without
  # a handful of clips dominating the far larger synthetic set.
  COPIES=$(( N_SAMPLES / 20 / REC_COUNT ))
  if [ "$COPIES" -lt 1 ]; then COPIES=1; fi
  echo "Found $REC_COUNT recording(s) — adding each one $COPIES times."

  # Copy off /mnt/d before opening files one by one — DrvFs (the /mnt/* NTFS
  # bridge) has been observed to reproducibly fail per-file opens on files
  # `find` lists fine. Same reason the venv above lives under $HOME.
  LOCAL_REC="$HOME/.wony_my_recordings"
  rm -rf "$LOCAL_REC"; mkdir -p "$LOCAL_REC"
  find "$REC_DIR" -type f \( -iname '*.wav' -o -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.ogg' -o -iname '*.flac' \) \
    -exec cp {} "$LOCAL_REC/" \;
  copied=$(find "$LOCAL_REC" -type f | wc -l)
  if [ "$copied" -lt "$REC_COUNT" ]; then
    warn "Only copied $copied of $REC_COUNT recordings off /mnt/d — some may still fail below."
  fi

  TMP_REC="$WORKDIR/.my_recordings_16k"
  rm -rf "$TMP_REC"; mkdir -p "$TMP_REC"

  # Normalize to what openWakeWord expects (16 kHz mono 16-bit) and trim silence
  # from both ends: augmentation right-aligns each clip, so leading/trailing
  # silence would shift the phrase away from where the model expects it.
  TRIM="silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05:detection=peak"
  n=0
  while IFS= read -r -d '' f; do
    n=$((n + 1))
    # -nostdin: without it, ffmpeg reads stdin for interactive control — but
    # this loop's process substitution puts the NUL-delimited file list on
    # that same fd, so ffmpeg steals bytes meant for `read` and corrupts it.
    ffmpeg -nostdin -y -i "$f" -ar 16000 -ac 1 -sample_fmt s16 \
        -af "$TRIM,areverse,$TRIM,areverse" \
        "$TMP_REC/rec_$n.wav" -loglevel error \
      || warn "Could not convert $(basename "$f") — skipping it."
  done < <(find "$LOCAL_REC" -type f -print0)

  for f in "$TMP_REC"/*.wav; do
    # Guard against the glob staying literal when every conversion failed.
    if [ ! -e "$f" ]; then
      warn "None of your recordings could be converted — continuing with synthetic clips only."
      break
    fi
    base=$(basename "$f" .wav)
    for c in $(seq 1 "$COPIES"); do
      cp "$f" "$POS_DIR/mine_${base}_$c.wav"
    done
  done
  echo "Mixed in: $(find "$POS_DIR" -name 'mine_*.wav' | wc -l) clips from your recordings."
fi

# ── 6c. Pronunciation check ──────────────────────────────────────────────────
step "Pronunciation check — listen before the long part starts"

SAMPLE_DIR="$WORKDIR/sample_clips"
rm -rf "$SAMPLE_DIR"; mkdir -p "$SAMPLE_DIR"
find "$POS_DIR" -name '*.wav' ! -name 'mine_*' | head -5 | while IFS= read -r f; do
  cp "$f" "$SAMPLE_DIR/"
done
warn "Play the clips in training/sample_clips/ (they open fine in Windows)."
echo "They should sound like how YOU say '$WAKE_PHRASE'. If they sound like a"
echo "different word, press Ctrl+C now, add spellings to WAKE_PHRASE_VARIANTS"
echo "at the top of this script, and re-run with --fresh. Training on clips that"
echo "sound wrong produces a model that never fires on your voice."
echo "Continuing in 60s..."
sleep 60

# ── 7. Augment clips ──────────────────────────────────────────────────────────
step "Phase 2/3 — Augmenting clips with room acoustics + noise"
# --overwrite is REQUIRED: without it train.py skips this whole step whenever
# feature .npy files from an earlier run exist, and then trains on that stale
# data — so changing any setting above appears to do nothing at all.
$PY openwakeword/openwakeword/train.py \
  --training_config "$CONFIG" \
  --augment_clips \
  --overwrite

# ── 8. Train model ────────────────────────────────────────────────────────────
step "Phase 3/3 — Training model (this takes a while)"
# || true: train.py exits non-zero after saving .onnx if onnx_tf isn't installed (tflite step).
# The .onnx is saved before that failure, so we catch it below.
$PY openwakeword/openwakeword/train.py \
  --training_config "$CONFIG" \
  --train_model || true

ONNX=$(find "./$MODEL_NAME" -name "$MODEL_NAME.onnx" 2>/dev/null | head -1)
if [ -z "$ONNX" ]; then
  ONNX=$(find . -name "$MODEL_NAME.onnx" | head -1)
fi
if [ -z "$ONNX" ]; then
  echo "ERROR: Training failed — $MODEL_NAME.onnx not produced. Check output above."
  exit 1
fi
echo "Model saved: $ONNX"

# ── 9. Copy output to Wony repo ───────────────────────────────────────────────
step "Copying model to Wony repo"

cp "$ONNX" "$WONY_MODELS/$MODEL_NAME.onnx"
echo "Copied to $WONY_MODELS/$MODEL_NAME.onnx"

echo ""
echo -e "${GREEN}✓ Done!${NC}"
echo ""
echo "Next steps — in config.yaml set:"
echo "  voice:"
echo "    wake_word:"
echo "      enabled: true"
echo "      phrase: \"$WAKE_PHRASE\""
echo "      model_path: models/$MODEL_NAME.onnx"
echo "      threshold: 0.5"
echo ""
echo "Then check it with: python wony.py doctor"
