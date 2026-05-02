# Voice Diary - Windows Environment Setup Report

Date: 2026-05-02
System verified: Windows, CUDA 13.2 driver, RTX 3080, Python 3.12, Node v24.11.1

## Supported Windows Path

Use one command from the repository root:

```bat
scripts\install.bat
```

The installer creates a fresh `.venv-ml` and installs the full local desktop stack:

1. Checks prerequisites: `uv`, Node/npm unless `--skip-frontend`, and `ffmpeg` when NeMo is enabled.
2. Detects NVIDIA CUDA with `nvidia-smi`.
3. Creates `.venv-ml` with Python 3.12 when available.
4. Installs backend `[ml,dev]` dependencies with `uv`.
5. Installs CUDA PyTorch `cu126` wheels when CUDA 12.x/13.x is detected; use `--cpu` to force CPU.
6. Removes optional `k2` if it was resolved, because native Windows `k2` can install without `_k2` and break unrelated SpeechBrain/NeMo imports.
7. Installs NeMo Sortformer by default from NVIDIA NeMo GitHub `@main`; use `--no-nemo` to skip.
8. Installs frontend dependencies with `npm ci` when `frontend/package-lock.json` exists, otherwise `npm install`.
9. Seeds the development database unless `--skip-seed` is passed.
10. Runs `backend/scripts/verify_windows_install.py` to verify Python path, Torch/CUDA, core ML imports, device normalization, and NeMo import when enabled.

## Installer Modes

```bat
scripts\install.bat --cpu             REM CPU-only Torch
scripts\install.bat --no-nemo         REM Skip NeMo Sortformer
scripts\install.bat --skip-frontend   REM Skip Node/npm install
scripts\install.bat --skip-seed       REM Skip dev DB seed
scripts\install-nemo.bat              REM Add/repair NeMo in existing .venv-ml
```

If CUDA is detected and CUDA Torch installation fails, the default installer now fails loudly. Rerun with `--cpu` only when a CPU-only environment is intentional.

## Electron Python Resolution

`frontend/electron/python-manager.ts` prefers:

1. `.venv-ml\Scripts\python.exe`
2. `.venv\Scripts\python.exe`
3. system `python`

The supported setup is `.venv-ml`. A missing package in `.venv-ml` is what caused Electron to fail with `ModuleNotFoundError: No module named 'nemo'`.

## NeMo and SpeechBrain Windows Fixes

Root problem: NeMo imports Lightning/Torch, which can call Python `inspect`; on Windows this can trigger SpeechBrain optional lazy imports such as `speechbrain.integrations.k2_fsa`. Broken native `k2` wheels then fail with `ModuleNotFoundError: No module named '_k2'` even though Voice Diary does not use k2.

Current fix:

- `backend/providers/diarization.py` installs a SpeechBrain lazy-import compatibility patch before NeMo/PyAnnote imports.
- `[ml]` no longer includes `k2`.
- Windows install scripts uninstall optional `k2` if a resolver brings it in.
- NeMo verification uses `backend.providers.diarization.import_nemo_sortformer_class()`, matching the app path instead of testing a naive raw import.

## CUDA Device Normalization

SpeechBrain expects indexed CUDA strings such as `cuda:0`, not bare `cuda`. The providers now normalize SpeechBrain/PyAnnote-facing device strings so the warning below does not recur:

```text
Could not parse CUDA device string 'cuda': not enough values to unpack ... Falling back to device 0.
```

Regression coverage is in `backend/e2e-tests/test_nemo_sortformer_import.py`.

## Verification Commands

```bat
.venv-ml\Scripts\python.exe -X utf8 backend\scripts\verify_windows_install.py --with-nemo --expect-cuda
.venv-ml\Scripts\python.exe -m pytest backend\tests\ -v
.venv-ml\Scripts\python.exe -m pytest backend\e2e-tests\test_nemo_sortformer_import.py -v
cd frontend && npm run typecheck
cd frontend && npm run test:unit
```

## Runtime Notes

- `HF_TOKEN` is still required at runtime for gated Hugging Face models, including Sortformer and some PyAnnote assets.
- The `torchcodec` FFmpeg warning is harmless for this app because the pipeline passes in-memory waveform tensors/arrays rather than asking PyAnnote to decode audio files.
- NeMo/OneLogger telemetry notices during import are non-fatal.
