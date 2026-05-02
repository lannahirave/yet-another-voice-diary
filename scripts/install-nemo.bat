@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  NeMo Sortformer add-on installer
REM  Run on existing .venv-ml to add NeMo diarization
REM ============================================================

cd /d "%~dp0.." 2>nul

if not exist ".venv-ml\Scripts\python.exe" (
    echo [ERROR] .venv-ml not found. Run install.bat first.
    exit /b 1
)

echo.
echo =============================================
echo   Installing NeMo Sortformer (add-on)
echo =============================================
echo.

REM Check ffmpeg
ffmpeg -version >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] ffmpeg is required. Install from https://ffmpeg.org/
    exit /b 1
)
echo [OK] ffmpeg found

REM Detect CUDA for NeMo extras
set "NEMO_CUDA_EXTRA="
where nvidia-smi >nul 2>nul
if %errorlevel% equ 0 (
    for /f "tokens=*" %%a in ('nvidia-smi 2^>nul ^| findstr /c:"CUDA Version"') do (
        set "smi_line=%%a"
    )
    if defined smi_line (
        set "cuda_ver=!smi_line:*CUDA Version: =!"
        for /f "tokens=1" %%v in ("!cuda_ver!") do set "cuda_ver=%%v"
        for /f "tokens=1 delims=." %%m in ("!cuda_ver!") do (
            if "%%m"=="12" set "NEMO_CUDA_EXTRA=cu12"
            if "%%m"=="13" set "NEMO_CUDA_EXTRA=cu13"
        )
    )
)

echo Installing Cython (NeMo build dependency)...
uv pip install cython packaging --python .venv-ml\Scripts\python.exe
if !errorlevel! neq 0 (
    echo [ERROR] Cython/packaging installation failed.
    exit /b 1
)

if defined NEMO_CUDA_EXTRA (
    echo Installing NeMo from GitHub with [asr,!NEMO_CUDA_EXTRA!] extras...
    uv pip install "nemo_toolkit[asr,!NEMO_CUDA_EXTRA!] @ git+https://github.com/NVIDIA/NeMo.git@main" --python .venv-ml\Scripts\python.exe
) else (
    echo Installing NeMo from GitHub with [asr] extras CPU-only...
    uv pip install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git@main" --python .venv-ml\Scripts\python.exe
)

if !errorlevel! neq 0 (
    echo [ERROR] NeMo installation failed.
    exit /b 1
)

echo Removing optional k2 package if pip resolved it...
uv pip uninstall k2 --python .venv-ml\Scripts\python.exe >nul 2>nul

echo Verifying Windows ML stack with NeMo...
.venv-ml\Scripts\python.exe -X utf8 backend\scripts\verify_windows_install.py --with-nemo
if !errorlevel! neq 0 (
    echo [ERROR] NeMo installed step completed, but the Windows ML stack verification failed.
    exit /b 1
)

echo.
echo [OK] NeMo Sortformer installed.
echo.
echo Verify: .venv-ml\Scripts\python.exe -X utf8 backend\scripts\verify_windows_install.py --with-nemo
echo NOTE:  Set HF_TOKEN before using Sortformer (gated model on HuggingFace Hub)

endlocal
