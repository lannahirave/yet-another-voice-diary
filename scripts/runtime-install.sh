#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT=""
RUNTIME_ROOT=""
APP_VERSION=""
LOG_PATH=""
NEMO_GIT_REF="7ccc79b525f205c2c20595a7dfc927051610962c"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source-root)
            SOURCE_ROOT="$2"
            shift 2
            ;;
        --runtime-root)
            RUNTIME_ROOT="$2"
            shift 2
            ;;
        --app-version)
            APP_VERSION="$2"
            shift 2
            ;;
        --log-path)
            LOG_PATH="$2"
            shift 2
            ;;
        *)
            echo "[runtime-install] Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

if [[ -z "$SOURCE_ROOT" || -z "$RUNTIME_ROOT" || -z "$APP_VERSION" || -z "$LOG_PATH" ]]; then
    echo "[runtime-install] --source-root, --runtime-root, --app-version, and --log-path are required" >&2
    exit 1
fi

log() {
    mkdir -p "$(dirname "$LOG_PATH")"
    local line="[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $1"
    echo "$line" >>"$LOG_PATH"
    echo "$1"
}

write_state() {
    local status="$1"
    local torch_variant="$2"
    local message="${3:-}"
    mkdir -p "$RUNTIME_ROOT"
    cat >"$RUNTIME_ROOT/install-state.json" <<EOF
{
  "status": "$status",
  "appVersion": "$APP_VERSION",
  "torchVariant": "$torch_variant",
  "message": "$message",
  "logPath": "$LOG_PATH",
  "updatedAt": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF
    log "[runtime-install] state=$status torch=$torch_variant message=$message"
}

resolve_uv() {
    local tools_dir="$RUNTIME_ROOT/tools"
    local uv_dir="$tools_dir/uv"
    local uv_bin="$uv_dir/uv"

    if [[ -x "$uv_bin" ]]; then
        echo "$uv_bin"
        return 0
    fi

    mkdir -p "$uv_dir"
    UV_INSTALL_DIR="$uv_dir" sh -c "$(curl -LsSf https://astral.sh/uv/install.sh)"

    if [[ -x "$uv_bin" ]]; then
        echo "$uv_bin"
        return 0
    fi

    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return 0
    fi

    echo "[runtime-install] uv was not installed into $uv_dir and no system uv command was found" >&2
    exit 1
}

resolve_cuda_torch_index() {
    if [[ "${VOICE_DIARY_FORCE_CPU:-0}" = "1" ]]; then
        log "[runtime-install] CUDA detection skipped by VOICE_DIARY_FORCE_CPU=1" >&2
        return 0
    fi

    local nvidia_smi=""
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia_smi="$(command -v nvidia-smi)"
    elif [[ -x "/usr/bin/nvidia-smi" ]]; then
        nvidia_smi="/usr/bin/nvidia-smi"
    elif [[ -x "/usr/local/bin/nvidia-smi" ]]; then
        nvidia_smi="/usr/local/bin/nvidia-smi"
    fi

    if [[ -z "$nvidia_smi" ]]; then
        log "[runtime-install] NVIDIA CUDA not detected: nvidia-smi was not found" >&2
        return 0
    fi

    log "[runtime-install] Found nvidia-smi at $nvidia_smi" >&2
    local cuda_version
    cuda_version="$("$nvidia_smi" 2>/dev/null | grep -E "CUDA( UMD)? Version" | sed -E 's/.*CUDA( UMD)? Version: //' | awk '{print $1}' || true)"
    local cuda_major="${cuda_version%%.*}"
    local cuda_minor="${cuda_version#*.}"
    cuda_minor="${cuda_minor%%.*}"

    if [[ "$cuda_major" =~ ^[0-9]+$ && "$cuda_minor" =~ ^[0-9]+$ && ( "$cuda_major" -ge 13 || ( "$cuda_major" -eq 12 && "$cuda_minor" -ge 9 ) ) ]]; then
        log "[runtime-install] NVIDIA CUDA driver $cuda_major.$cuda_minor; using PyTorch cu129 wheels" >&2
        echo "https://download.pytorch.org/whl/cu129"
    elif [[ "$cuda_major" =~ ^[0-9]+$ && "$cuda_minor" =~ ^[0-9]+$ && "$cuda_major" -eq 12 && "$cuda_minor" -ge 8 ]]; then
        log "[runtime-install] NVIDIA CUDA driver $cuda_major.$cuda_minor; using PyTorch cu128 wheels" >&2
        echo "https://download.pytorch.org/whl/cu128"
    elif [[ "$cuda_major" =~ ^[0-9]+$ && "$cuda_minor" =~ ^[0-9]+$ && "$cuda_major" -eq 12 && "$cuda_minor" -ge 6 ]]; then
        log "[runtime-install] NVIDIA CUDA driver $cuda_major.$cuda_minor; using PyTorch cu126 wheels" >&2
        echo "https://download.pytorch.org/whl/cu126"
    elif [[ -n "$cuda_major" ]]; then
        log "[runtime-install] NVIDIA CUDA driver $cuda_version is not supported by the pinned torch 2.8.0 runtime; using CPU wheels" >&2
    else
        log "[runtime-install] NVIDIA CUDA not detected: nvidia-smi did not report a CUDA Version" >&2
    fi
}

install_nemo() {
    if [[ "${VOICE_DIARY_WITH_NEMO:-1}" = "0" ]]; then
        step "Skipping NeMo Sortformer dependencies by VOICE_DIARY_WITH_NEMO=0"
        return 0
    fi

    step "Installing NeMo Sortformer dependencies"
    log "[runtime-install] NeMo git ref=$NEMO_GIT_REF"
    "$UV_BIN" pip install cython packaging --python "$PYTHON_EXE"
    if [[ -n "${CUDA_INDEX:-}" ]]; then
        "$UV_BIN" pip install "nemo_toolkit[asr,cu12] @ git+https://github.com/NVIDIA/NeMo.git@$NEMO_GIT_REF" "numba==0.65.1" "llvmlite==0.47.0" "cuda-bindings<13" --python "$PYTHON_EXE"
    else
        "$UV_BIN" pip install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git@$NEMO_GIT_REF" "numba==0.65.1" "llvmlite==0.47.0" --python "$PYTHON_EXE"
    fi
}

step() {
    log "[runtime-install] $1"
}

SOURCE_ROOT="$(cd "$SOURCE_ROOT" && pwd)"
BACKEND_PROJECT="$SOURCE_ROOT/backend"
VENV_DIR="$RUNTIME_ROOT/venv"
PYTHON_EXE="$VENV_DIR/bin/python"

if [[ ! -f "$BACKEND_PROJECT/pyproject.toml" ]]; then
    echo "[runtime-install] Packaged backend pyproject.toml not found under $BACKEND_PROJECT" >&2
    exit 1
fi

write_state "installing" "unknown"
log "[runtime-install] source=$SOURCE_ROOT runtime=$RUNTIME_ROOT appVersion=$APP_VERSION"

if ! {
    UV_BIN="$(resolve_uv)"
    CUDA_INDEX="$(resolve_cuda_torch_index)"
    TORCH_VARIANT="cpu"
    if [[ -n "$CUDA_INDEX" ]]; then
        TORCH_VARIANT="cuda-${CUDA_INDEX##*/}"
    elif [[ "$(uname -s)" = "Darwin" ]]; then
        TORCH_VARIANT="macos-default"
    fi

    step "Ensuring managed Python 3.12 is available"
    "$UV_BIN" python install 3.12

    step "Creating private Python runtime"
    "$UV_BIN" venv "$VENV_DIR" --python 3.12 --clear

    step "Installing Voice Diary backend dependencies"
    "$UV_BIN" pip install "${BACKEND_PROJECT}[ml]" --python "$PYTHON_EXE"

    if [[ -n "$CUDA_INDEX" ]]; then
        step "Installing CUDA PyTorch wheels"
        "$UV_BIN" pip install --force-reinstall torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 \
            --index-url "$CUDA_INDEX" --python "$PYTHON_EXE"
    fi

    install_nemo

    step "Verifying backend runtime imports"
    if [[ "${VOICE_DIARY_WITH_NEMO:-1}" = "0" ]]; then
        "$PYTHON_EXE" -c "import torch; import faster_whisper; import pyannote.audio; import silero_vad; import speechbrain; from backend.providers.devices import normalize_indexed_cuda_device; assert normalize_indexed_cuda_device('cpu') == 'cpu'; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
    else
        "$PYTHON_EXE" -c "import torch; import faster_whisper; import pyannote.audio; import silero_vad; import speechbrain; import nemo.collections.asr.models; from backend.providers.devices import normalize_indexed_cuda_device; assert normalize_indexed_cuda_device('cpu') == 'cpu'; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
    fi
}; then
    write_state "error" "unknown" "runtime bootstrap failed"
    exit 1
fi

write_state "ok" "$TORCH_VARIANT"
