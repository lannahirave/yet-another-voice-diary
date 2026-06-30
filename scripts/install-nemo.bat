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
set "NVIDIA_SMI="
where nvidia-smi >nul 2>nul
if %errorlevel% equ 0 (
    set "NVIDIA_SMI=nvidia-smi"
) else if exist "%SystemRoot%\System32\nvidia-smi.exe" (
    set "NVIDIA_SMI=%SystemRoot%\System32\nvidia-smi.exe"
) else if exist "%WINDIR%\System32\nvidia-smi.exe" (
    set "NVIDIA_SMI=%WINDIR%\System32\nvidia-smi.exe"
)
if defined NVIDIA_SMI (
    for /f "tokens=*" %%a in ('"!NVIDIA_SMI!" 2^>nul ^| findstr /r /c:"CUDA.* Version"') do (
        set "smi_line=%%a"
    )
    if defined smi_line (
        set "smi_without_umd=!smi_line:CUDA UMD Version=!"
        if not "!smi_without_umd!"=="!smi_line!" (
            set "cuda_ver=!smi_line:*CUDA UMD Version: =!"
        ) else (
            set "cuda_ver=!smi_line:*CUDA Version: =!"
        )
        for /f "tokens=1" %%v in ("!cuda_ver!") do set "cuda_ver=%%v"
        for /f "tokens=1,2 delims=." %%m in ("!cuda_ver!") do (
            if %%m geq 13 (
                set "NEMO_CUDA_EXTRA=cu12"
            ) else if "%%m"=="12" (
                if %%n geq 6 (
                    set "NEMO_CUDA_EXTRA=cu12"
                )
            )
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
    uv pip install "nemo_toolkit[asr,!NEMO_CUDA_EXTRA!] @ git+https://github.com/NVIDIA/NeMo.git@7ccc79b525f205c2c20595a7dfc927051610962c" "numba>=0.60" "llvmlite>=0.43" "cuda-bindings<13" --python .venv-ml\Scripts\python.exe
) else (
    echo Installing NeMo from GitHub with [asr] extras CPU-only...
    uv pip install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git@7ccc79b525f205c2c20595a7dfc927051610962c" "numba>=0.60" "llvmlite>=0.43" --python .venv-ml\Scripts\python.exe
)

if !errorlevel! neq 0 (
    echo [ERROR] NeMo installation failed.
    exit /b 1
)

REM k2 is a SpeechBrain optional integration for ASR lattice decoding.
REM On Windows, SpeechBrain's lazy-import guard fails (backslash paths
REM don't match "/inspect.py"), so k2 can be accidentally imported during
REM NeMo loading. Broken native Windows k2 wheels install without the
REM _k2 C extension and raise ModuleNotFoundError. Remove if present.
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
