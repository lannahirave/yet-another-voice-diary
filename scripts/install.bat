@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  Voice Diary - Unified Installer (Windows)
REM
REM  Default: full install with ML, CUDA Torch when available,
REM           NeMo Sortformer, frontend dependencies, DB seed,
REM           and post-install verification.
REM
REM  Usage:
REM    scripts\install.bat [--cpu] [--no-nemo] [--skip-frontend] [--skip-seed]
REM ============================================================

set "WITH_NEMO=1"
set "FORCE_CPU=0"
set "SKIP_FRONTEND=0"
set "SKIP_SEED=0"
set "EXPECT_CUDA=0"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--cpu" (
    set "FORCE_CPU=1"
    shift
    goto parse_args
)
if /i "%~1"=="--no-nemo" (
    set "WITH_NEMO=0"
    shift
    goto parse_args
)
if /i "%~1"=="--skip-frontend" (
    set "SKIP_FRONTEND=1"
    shift
    goto parse_args
)
if /i "%~1"=="--skip-seed" (
    set "SKIP_SEED=1"
    shift
    goto parse_args
)
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-h" goto usage
echo [ERROR] Unknown option: %~1
goto usage_error

:usage
echo.
echo Voice Diary Windows installer
echo.
echo Usage:
echo   scripts\install.bat [--cpu] [--no-nemo] [--skip-frontend] [--skip-seed]
echo.
echo Options:
echo   --cpu             Force CPU-only PyTorch even when NVIDIA CUDA is present.
echo   --no-nemo         Skip NeMo Sortformer dependencies.
echo   --skip-frontend   Skip frontend npm dependency installation.
echo   --skip-seed       Skip development database seeding.
echo.
exit /b 0

:usage_error
echo Run scripts\install.bat --help for supported options.
exit /b 1

:args_done

REM Navigate to project root (one level above this script's directory).
cd /d "%~dp0.." 2>nul
if !errorlevel! neq 0 (
    echo [ERROR] Cannot navigate to project root from %~dp0
    exit /b 1
)
if not exist "backend\pyproject.toml" (
    echo [ERROR] Project root not found. Run this script from the repo root.
    exit /b 1
)

set /a TOTAL=4
if "%SKIP_FRONTEND%"=="0" set /a TOTAL+=1
if "%SKIP_SEED%"=="0" set /a TOTAL+=1
set /a STEP=1

echo.
echo =============================================
echo   Voice Diary - Unified Installer (Windows)
echo   Mode: full local environment
if "%WITH_NEMO%"=="1" (
    echo   NeMo: enabled
) else (
    echo   NeMo: skipped
)
if "%FORCE_CPU%"=="1" echo   Torch: CPU forced
echo =============================================
echo.

REM ============================================================
REM  1. Check prerequisites
REM ============================================================
echo [!STEP!/%TOTAL%] Checking prerequisites...
set /a STEP+=1

uv --version >nul 2>nul
if !errorlevel! neq 0 (
    echo [ERROR] uv is not installed.
    echo   Install: powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    exit /b 1
)
for /f "tokens=2" %%v in ('uv --version 2^>nul') do echo   [OK] uv %%v

if "%SKIP_FRONTEND%"=="0" (
    node --version >nul 2>nul
    if !errorlevel! neq 0 (
        echo [ERROR] Node.js is not installed. Install from https://nodejs.org/
        exit /b 1
    )
    for /f "tokens=*" %%v in ('node --version 2^>nul') do echo   [OK] node %%v

    call npm --version >nul 2>nul
    if !errorlevel! neq 0 (
        echo [ERROR] npm not found. It should be installed with Node.js.
        exit /b 1
    )
    for /f "tokens=*" %%v in ('call npm --version 2^>nul') do echo   [OK] npm %%v
) else (
    echo   [SKIP] Node/npm checks skipped by --skip-frontend
)

if "%WITH_NEMO%"=="1" (
    ffmpeg -version >nul 2>nul
    if !errorlevel! neq 0 (
        echo [ERROR] ffmpeg is required for NeMo Sortformer. Install it and add it to PATH.
        echo   Windows builds: https://ffmpeg.org/download.html
        exit /b 1
    )
    echo   [OK] ffmpeg found
)

REM ============================================================
REM  2. Detect CUDA
REM ============================================================
echo.
echo [!STEP!/%TOTAL%] Detecting GPU / CUDA...
set /a STEP+=1

set "CUDA_INDEX="
set "CUDA_LABEL=CPU-only"
set "CUDA_VERSION="
set "NEMO_CUDA_EXTRA="
set "smi_line="

if "%FORCE_CPU%"=="1" (
    echo   CPU-only mode requested by --cpu
) else (
    where nvidia-smi >nul 2>nul
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%a in ('nvidia-smi 2^>nul ^| findstr /c:"CUDA Version"') do (
            set "smi_line=%%a"
        )
        if defined smi_line (
            set "CUDA_VERSION=!smi_line:*CUDA Version: =!"
            for /f "tokens=1" %%v in ("!CUDA_VERSION!") do set "CUDA_VERSION=%%v"
        )
    )

    if defined CUDA_VERSION (
        for /f "tokens=1,2 delims=." %%a in ("!CUDA_VERSION!") do (
            set "cuda_major=%%a"
            set "cuda_minor=%%b"
        )

        if "!cuda_major!"=="12" (
            set "CUDA_INDEX=https://download.pytorch.org/whl/cu126"
            set "CUDA_LABEL=CUDA !CUDA_VERSION! (using cu126 wheels)"
            set "NEMO_CUDA_EXTRA=cu12"
            echo   [OK] NVIDIA GPU detected - driver CUDA !CUDA_VERSION!
            if not "!cuda_minor!"=="6" (
                echo         CUDA !CUDA_VERSION! driver - cu126 wheels are backward-compatible
            )
        ) else if "!cuda_major!"=="13" (
            set "CUDA_INDEX=https://download.pytorch.org/whl/cu126"
            set "CUDA_LABEL=CUDA !CUDA_VERSION! (using cu126 wheels)"
            set "NEMO_CUDA_EXTRA=cu13"
            echo   [OK] NVIDIA GPU detected - driver CUDA !CUDA_VERSION!
            echo         CUDA 13.x driver - cu126 wheels are backward-compatible
        ) else (
            echo   [WARN] CUDA !CUDA_VERSION! is not supported by torch 2.8.0.
            echo          Installing CPU-only PyTorch. GPU acceleration will NOT be available.
        )
    ) else (
        echo   No NVIDIA GPU found - installing CPU-only PyTorch
    )
)

REM ============================================================
REM  3. Set up Python environment (.venv-ml)
REM ============================================================
echo.
echo [!STEP!/%TOTAL%] Setting up Python environment (.venv-ml)...
set /a STEP+=1

if exist ".venv-ml" (
    echo   Removing existing .venv-ml...
    rmdir /s /q ".venv-ml" 2>nul
    if exist ".venv-ml" (
        echo [ERROR] Failed to remove old .venv-ml. Close any programs using it.
        exit /b 1
    )
)

echo   Creating virtual environment...
uv venv .venv-ml --python 3.12
if !errorlevel! neq 0 (
    echo   [WARN] Python 3.12 not found, trying default Python...
    uv venv .venv-ml
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create .venv-ml. Make sure Python ^>=3.11 is installed.
        exit /b 1
    )
)
echo   [OK] Virtual environment created

echo   Installing backend with [ml,dev] extras...
pushd backend
uv pip install -e ".[ml,dev]" --python ..\.venv-ml\Scripts\python.exe
set "INSTALL_ERR=!errorlevel!"
popd
if !INSTALL_ERR! neq 0 (
    echo [ERROR] Backend dependency installation failed.
    exit /b 1
)
echo   [OK] Backend dependencies installed

REM k2 is a SpeechBrain optional integration for ASR lattice decoding.
REM On Windows, SpeechBrain's lazy-import guard fails (backslash paths
REM don't match "/inspect.py"), so k2 can be accidentally imported during
REM NeMo/PyAnnote loading. Broken native Windows k2 wheels install without
REM the _k2 C extension and raise ModuleNotFoundError. This app does not
REM use k2, so remove it if pip resolved it transitively.
echo   Removing optional k2 package if pip resolved it...
uv pip uninstall k2 --python .venv-ml\Scripts\python.exe >nul 2>nul
echo   [OK] Optional k2 package is not required for this Windows app

if defined CUDA_INDEX (
    echo   Replacing CPU torch with CUDA build from !CUDA_INDEX!...
    uv pip install --force-reinstall torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 ^
        --index-url "!CUDA_INDEX!" --python .venv-ml\Scripts\python.exe
    if !errorlevel! neq 0 (
        echo [ERROR] CUDA torch install failed.
        echo        Try manually: uv pip install torch==2.8.0 --index-url !CUDA_INDEX! --python .venv-ml\Scripts\python.exe
        echo        Or rerun scripts\install.bat --cpu for a CPU-only environment.
        exit /b 1
    ) else (
        echo   [OK] CUDA PyTorch installed
        set "EXPECT_CUDA=1"
    )
)

if "%WITH_NEMO%"=="1" (
    echo   Installing NeMo Sortformer dependencies...
    uv pip install cython packaging --python .venv-ml\Scripts\python.exe
    if !errorlevel! neq 0 (
        echo [ERROR] Cython installation failed.
        exit /b 1
    )

    if defined NEMO_CUDA_EXTRA (
        echo   Installing NeMo from GitHub with [asr,!NEMO_CUDA_EXTRA!] extras...
        uv pip install "nemo_toolkit[asr,!NEMO_CUDA_EXTRA!] @ git+https://github.com/NVIDIA/NeMo.git@main" --python .venv-ml\Scripts\python.exe
    ) else (
        echo   Installing NeMo from GitHub with [asr] extras...
        uv pip install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git@main" --python .venv-ml\Scripts\python.exe
    )
    if !errorlevel! neq 0 (
        echo [ERROR] NeMo installation failed.
        exit /b 1
    )
    echo   [OK] NeMo Sortformer installed
)

REM ============================================================
REM  4. Install frontend
REM ============================================================
if "%SKIP_FRONTEND%"=="0" (
    echo.
    echo [!STEP!/%TOTAL%] Installing frontend dependencies...
    set /a STEP+=1

    pushd frontend
    if exist "package-lock.json" (
        echo   package-lock.json found - using npm ci
        call npm ci
    ) else (
        echo   package-lock.json not found - using npm install
        call npm install
    )
    set "NPM_ERR=!errorlevel!"
    popd
    if !NPM_ERR! neq 0 (
        echo [ERROR] Frontend dependency installation failed.
        exit /b 1
    )
    echo   [OK] Frontend dependencies installed
)


REM ============================================================
REM  5. Verify installation
REM ============================================================
echo.
echo [!STEP!/%TOTAL%] Verifying installation...

set "VERIFY_ARGS="
if "%EXPECT_CUDA%"=="1" set "VERIFY_ARGS=!VERIFY_ARGS! --expect-cuda"
if "%WITH_NEMO%"=="1" (
    set "VERIFY_ARGS=!VERIFY_ARGS! --with-nemo"
)

.venv-ml\Scripts\python.exe -X utf8 backend\scripts\verify_windows_install.py !VERIFY_ARGS!
if !errorlevel! neq 0 (
    echo [ERROR] Installation verification failed.
    echo        Electron would not be able to use the full backend feature set.
    exit /b 1
)

REM ============================================================
REM  Summary
REM ============================================================
echo.
echo =============================================
echo   Installation Complete!
echo =============================================
echo.
echo   Environment:  .venv-ml
echo   Torch:        !CUDA_LABEL!
if "%WITH_NEMO%"=="1" (
    echo   NeMo:         installed and import-verified
) else (
    echo   NeMo:         skipped
)
echo.
echo   Quick start:
echo     cd frontend ^&^& npm run electron:dev
echo.
echo   Backend only:
echo     .venv-ml\Scripts\python.exe -m backend.run
echo.
echo   Frontend only:
echo     cd frontend ^&^& npm run dev
echo.
echo   Verify later:
if "%WITH_NEMO%"=="1" (
    echo     .venv-ml\Scripts\python.exe -X utf8 backend\scripts\verify_windows_install.py --with-nemo
) else (
    echo     .venv-ml\Scripts\python.exe -X utf8 backend\scripts\verify_windows_install.py
)
echo     .venv-ml\Scripts\python.exe -m pytest backend\tests\ -v
echo     cd frontend ^&^& npm run typecheck
echo.
echo   HF_TOKEN is required at runtime for gated Hugging Face models:
echo     set HF_TOKEN=hf_your_token_here
echo =============================================

endlocal
