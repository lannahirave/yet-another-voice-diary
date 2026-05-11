#!/usr/bin/env bash
set -euo pipefail

# ============================================================
#  Voice Diary - Unified Installer (Linux / macOS)
#
#  Default: full install with ML, CUDA Torch when available,
#           NeMo Sortformer, frontend dependencies, DB seed,
#           and post-install verification.
#
#  Usage:
#    bash scripts/install.sh [--cpu] [--no-nemo] [--skip-frontend] [--skip-seed]
# ============================================================

WITH_NEMO=1
FORCE_CPU=0
SKIP_FRONTEND=0
SKIP_SEED=0
EXPECT_CUDA=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cpu)
            FORCE_CPU=1
            shift
            ;;
        --no-nemo)
            WITH_NEMO=0
            shift
            ;;
        --skip-frontend)
            SKIP_FRONTEND=1
            shift
            ;;
        --skip-seed)
            SKIP_SEED=1
            shift
            ;;
        --help|-h)
            echo
            echo "Voice Diary Linux/macOS installer"
            echo
            echo "Usage:"
            echo "  bash scripts/install.sh [--cpu] [--no-nemo] [--skip-frontend] [--skip-seed]"
            echo
            echo "Options:"
            echo "  --cpu             Force CPU-only PyTorch even when NVIDIA CUDA is present."
            echo "  --no-nemo         Skip NeMo Sortformer dependencies."
            echo "  --skip-frontend   Skip frontend npm dependency installation."
            echo "  --skip-seed       Skip development database seeding."
            echo
            exit 0
            ;;
        *)
            echo "[ERROR] Unknown option: $1"
            echo "Run bash scripts/install.sh --help for supported options."
            exit 1
            ;;
    esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f "backend/pyproject.toml" ]; then
    echo "[ERROR] Project root not found. Run this script from the repo root."
    exit 1
fi

TOTAL=4
if [ "$SKIP_FRONTEND" -eq 0 ]; then
    TOTAL=$((TOTAL + 1))
fi
if [ "$SKIP_SEED" -eq 0 ]; then
    TOTAL=$((TOTAL + 1))
fi
STEP=1

echo
echo "============================================="
echo "  Voice Diary - Unified Installer (Linux/macOS)"
echo "  Mode: full local environment"
if [ "$WITH_NEMO" -eq 1 ]; then
    echo "  NeMo: enabled"
else
    echo "  NeMo: skipped"
fi
if [ "$FORCE_CPU" -eq 1 ]; then
    echo "  Torch: CPU forced"
fi
echo "============================================="
echo

# ============================================================
#  1. Check prerequisites
# ============================================================
echo "[$STEP/$TOTAL] Checking prerequisites..."
STEP=$((STEP + 1))

if ! command -v uv &>/dev/null; then
    echo "[ERROR] uv is not installed."
    echo "  Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "  [OK] uv $(uv --version | cut -d' ' -f2)"

if [ "$SKIP_FRONTEND" -eq 0 ]; then
    if ! command -v node &>/dev/null; then
        echo "[ERROR] Node.js is not installed. Install from https://nodejs.org/"
        exit 1
    fi
    echo "  [OK] node $(node --version)"

    if ! command -v npm &>/dev/null; then
        echo "[ERROR] npm not found (should come with Node.js)"
        exit 1
    fi
    echo "  [OK] npm $(npm --version)"
else
    echo "  [SKIP] Node/npm checks skipped by --skip-frontend"
fi

if [ "$WITH_NEMO" -eq 1 ]; then
    if ! command -v ffmpeg &>/dev/null; then
        echo "[ERROR] ffmpeg is required for NeMo Sortformer."
        echo "  Install: sudo apt-get install ffmpeg  (or brew install ffmpeg on macOS)"
        exit 1
    fi
    echo "  [OK] ffmpeg found"
fi

# ============================================================
#  2. Detect CUDA (skip if --cpu)
# ============================================================
echo
echo "[$STEP/$TOTAL] Detecting GPU / CUDA..."
STEP=$((STEP + 1))

CUDA_INDEX=""
CUDA_LABEL="CPU-only"
CUDA_VERSION=""
NEMO_CUDA_EXTRA=""

if [ "$FORCE_CPU" -eq 1 ]; then
    echo "  CPU-only mode requested by --cpu"
elif command -v nvidia-smi &>/dev/null; then
    CUDA_VERSION=$(nvidia-smi 2>/dev/null | grep "CUDA Version" | sed 's/.*CUDA Version: //' | awk '{print $1}')

    if [ -n "${CUDA_VERSION:-}" ]; then
        cuda_major=$(echo "$CUDA_VERSION" | cut -d'.' -f1)

        if [ "$cuda_major" = "12" ]; then
            CUDA_INDEX="https://download.pytorch.org/whl/cu126"
            CUDA_LABEL="CUDA $CUDA_VERSION (using cu126 wheels)"
            NEMO_CUDA_EXTRA="cu12"
            echo "  [OK] NVIDIA GPU detected - driver CUDA $CUDA_VERSION"
            [ "$cuda_major" != "6" ] && echo "        CUDA $CUDA_VERSION driver - cu126 wheels are backward-compatible"
        elif [ "$cuda_major" = "13" ]; then
            CUDA_INDEX="https://download.pytorch.org/whl/cu126"
            CUDA_LABEL="CUDA $CUDA_VERSION (using cu126 wheels)"
            NEMO_CUDA_EXTRA="cu13"
            echo "  [OK] NVIDIA GPU detected - driver CUDA $CUDA_VERSION"
            echo "        CUDA 13.x driver - cu126 wheels are backward-compatible"
        else
            echo "  [WARN] CUDA $CUDA_VERSION is not supported by torch 2.8.0."
            echo "         Installing CPU-only PyTorch. GPU acceleration will NOT be available."
        fi
    else
        echo "  No NVIDIA GPU found - installing CPU-only PyTorch"
    fi
else
    echo "  No NVIDIA GPU found - installing CPU-only PyTorch"
fi

# ============================================================
#  3. Set up Python environment (.venv-ml)
# ============================================================
echo
echo "[$STEP/$TOTAL] Setting up Python environment (.venv-ml)..."
STEP=$((STEP + 1))

if [ -d ".venv-ml" ]; then
    echo "  Removing existing .venv-ml..."
    rm -rf ".venv-ml"
fi

echo "  Creating virtual environment..."
if ! uv venv .venv-ml --python 3.12 2>/dev/null; then
    echo "  [WARN] Python 3.12 not found, trying default Python..."
    if ! uv venv .venv-ml; then
        echo "[ERROR] Failed to create .venv-ml. Make sure Python >=3.11 is installed."
        exit 1
    fi
fi
echo "  [OK] Virtual environment created"

echo "  Installing backend with [ml,dev] extras..."
(
    cd backend
    uv pip install -e ".[ml,dev]" --python ../.venv-ml/bin/python
)
echo "  [OK] Backend dependencies installed"

if [ -n "${CUDA_INDEX:-}" ]; then
    echo "  Replacing CPU torch with CUDA build from $CUDA_INDEX..."
    if uv pip install --force-reinstall torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 \
        --index-url "$CUDA_INDEX" --python .venv-ml/bin/python; then
        echo "  [OK] CUDA PyTorch installed"
        EXPECT_CUDA=1
    else
        echo "[ERROR] CUDA torch install failed."
        echo "        Try manually: uv pip install torch==2.8.0 --index-url $CUDA_INDEX --python .venv-ml/bin/python"
        echo "        Or rerun bash scripts/install.sh --cpu for a CPU-only environment."
        exit 1
    fi
fi

# ============================================================
#  4. Install NeMo
# ============================================================
if [ "$WITH_NEMO" -eq 1 ]; then
    echo
    echo "[$STEP/$TOTAL] Installing NeMo Sortformer diarization..."
    STEP=$((STEP + 1))

    echo "  Installing Cython (NeMo build dependency)..."
    uv pip install cython packaging --python .venv-ml/bin/python

    if [ -n "${NEMO_CUDA_EXTRA:-}" ]; then
        echo "  Installing NeMo from GitHub with [asr,$NEMO_CUDA_EXTRA] extras..."
        uv pip install "nemo_toolkit[asr,$NEMO_CUDA_EXTRA] @ git+https://github.com/NVIDIA/NeMo.git@main" --python .venv-ml/bin/python
    else
        echo "  Installing NeMo from GitHub with [asr] extras (CPU-only)..."
        uv pip install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git@main" --python .venv-ml/bin/python
    fi

    if [ $? -ne 0 ]; then
        echo "[ERROR] NeMo installation failed."
        exit 1
    fi
    echo "  [OK] NeMo Sortformer installed"
fi

# ============================================================
#  5. Install frontend
# ============================================================
if [ "$SKIP_FRONTEND" -eq 0 ]; then
    echo
    echo "[$STEP/$TOTAL] Installing frontend dependencies..."
    STEP=$((STEP + 1))

    (
        cd frontend
        if [ -f "package-lock.json" ]; then
            echo "  package-lock.json found - using npm ci"
            npm ci
        else
            echo "  package-lock.json not found - using npm install"
            npm install
        fi
    )
    echo "  [OK] Frontend dependencies installed"
fi


# ============================================================
#  6. Verify installation
# ============================================================
echo
echo "[$STEP/$TOTAL] Verifying installation..."

VERIFY_ARGS=""
if [ "$EXPECT_CUDA" -eq 1 ]; then
    VERIFY_ARGS="$VERIFY_ARGS --expect-cuda"
fi
if [ "$WITH_NEMO" -eq 1 ]; then
    VERIFY_ARGS="$VERIFY_ARGS --with-nemo"
fi

.venv-ml/bin/python backend/scripts/verify_unix_install.py $VERIFY_ARGS
if [ $? -ne 0 ]; then
    echo "[ERROR] Installation verification failed."
    echo "        Electron would not be able to use the full backend feature set."
    exit 1
fi

# ============================================================
#  Summary
# ============================================================
echo
echo "============================================="
echo "  Installation Complete!"
echo "============================================="
echo
echo "  Environment:  .venv-ml"
echo "  Torch:        $CUDA_LABEL"
if [ "$WITH_NEMO" -eq 1 ]; then
    echo "  NeMo:         installed and import-verified"
else
    echo "  NeMo:         skipped"
fi
echo
echo "  Quick start:"
echo "    cd frontend && npm run electron:dev"
echo
echo "  Backend only:"
echo "    .venv-ml/bin/python -m backend.run"
echo
echo "  Frontend only:"
echo "    cd frontend && npm run dev"
echo
echo "  Verify later:"
if [ "$WITH_NEMO" -eq 1 ]; then
    echo "    .venv-ml/bin/python backend/scripts/verify_unix_install.py --with-nemo"
else
    echo "    .venv-ml/bin/python backend/scripts/verify_unix_install.py"
fi
echo "    .venv-ml/bin/python -m pytest backend/tests/ -v"
echo "    cd frontend && npm run typecheck"
echo
echo "  HF_TOKEN is required at runtime for gated Hugging Face models:"
echo "    export HF_TOKEN=hf_your_token_here"
echo "============================================="
