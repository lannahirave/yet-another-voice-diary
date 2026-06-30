param(
    [Parameter(Mandatory = $true)]
    [string]$SourceRoot,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeRoot,

    [Parameter(Mandatory = $true)]
    [string]$AppVersion,

    [Parameter(Mandatory = $true)]
    [string]$LogPath
)

$ErrorActionPreference = "Stop"
$NemoGitRef = "7ccc79b525f205c2c20595a7dfc927051610962c"

function Write-Log {
    param([string]$Message)

    $line = "[$((Get-Date).ToUniversalTime().ToString("o"))] $Message"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
    Add-Content -Encoding UTF8 -Path $LogPath -Value $line
    Write-Host $Message
}

function Write-State {
    param(
        [string]$Status,
        [string]$TorchVariant,
        [string]$Message = ""
    )

    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    $state = [ordered]@{
        status = $Status
        appVersion = $AppVersion
        torchVariant = $TorchVariant
        message = $Message
        logPath = $LogPath
        updatedAt = (Get-Date).ToUniversalTime().ToString("o")
    }
    $state | ConvertTo-Json | Set-Content -Encoding UTF8 -Path (Join-Path $RuntimeRoot "install-state.json")
    Write-Log "[runtime-install] state=$Status torch=$TorchVariant message=$Message"
}

function Resolve-Uv {
    $toolsDir = Join-Path $RuntimeRoot "tools"
    $uvDir = Join-Path $toolsDir "uv"
    $uvExe = Join-Path $uvDir "uv.exe"

    if (Test-Path $uvExe) {
        return $uvExe
    }

    New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
    $env:UV_INSTALL_DIR = $uvDir
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"

    if (Test-Path $uvExe) {
        return $uvExe
    }

    $systemUv = Get-Command uv -ErrorAction SilentlyContinue
    if ($systemUv) {
        return $systemUv.Source
    }

    throw "uv was not installed into $uvDir and no system uv command was found"
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Resolve-CudaTorchIndex {
    if ($env:VOICE_DIARY_FORCE_CPU -eq "1") {
        Write-Log "[runtime-install] CUDA detection skipped by VOICE_DIARY_FORCE_CPU=1"
        return ""
    }

    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $nvidiaSmi) {
        $system32Smi = Join-Path $env:SystemRoot "System32\nvidia-smi.exe"
        if (Test-Path $system32Smi) {
            $nvidiaSmi = [pscustomobject]@{ Source = $system32Smi }
        }
    }
    if (-not $nvidiaSmi -and $env:WINDIR) {
        $windirSmi = Join-Path $env:WINDIR "System32\nvidia-smi.exe"
        if (Test-Path $windirSmi) {
            $nvidiaSmi = [pscustomobject]@{ Source = $windirSmi }
        }
    }
    if (-not $nvidiaSmi) {
        Write-Log "[runtime-install] NVIDIA CUDA not detected: nvidia-smi was not found"
        return ""
    }

    Write-Log "[runtime-install] Found nvidia-smi at $($nvidiaSmi.Source)"
    $smi = & $nvidiaSmi.Source 2>$null | Select-String "CUDA( UMD)? Version" | Select-Object -First 1
    if (-not $smi) {
        Write-Log "[runtime-install] NVIDIA CUDA not detected: nvidia-smi did not report a CUDA Version"
        return ""
    }

    $match = [regex]::Match($smi.Line, "CUDA(?: UMD)? Version:\s+([0-9]+)\.([0-9]+)")
    if (-not $match.Success) {
        Write-Log "[runtime-install] NVIDIA CUDA not detected: could not parse nvidia-smi line '$($smi.Line)'"
        return ""
    }

    $major = [int]$match.Groups[1].Value
    $minor = [int]$match.Groups[2].Value
    if ($major -ge 13 -or ($major -eq 12 -and $minor -ge 9)) {
        Write-Log "[runtime-install] NVIDIA CUDA driver $major.$minor; using PyTorch cu129 wheels"
        return "https://download.pytorch.org/whl/cu129"
    }
    if ($major -eq 12 -and $minor -ge 8) {
        Write-Log "[runtime-install] NVIDIA CUDA driver $major.$minor; using PyTorch cu128 wheels"
        return "https://download.pytorch.org/whl/cu128"
    }
    if ($major -eq 12 -and $minor -ge 6) {
        Write-Log "[runtime-install] NVIDIA CUDA driver $major.$minor; using PyTorch cu126 wheels"
        return "https://download.pytorch.org/whl/cu126"
    }

    Write-Log "[runtime-install] NVIDIA CUDA driver $major.$minor is not supported by the pinned torch 2.8.0 runtime; using CPU wheels"
    return ""
}

function Install-Nemo {
    param(
        [string]$Uv,
        [string]$PythonExe,
        [string]$CudaIndex
    )

    if ($env:VOICE_DIARY_WITH_NEMO -eq "0") {
        Write-Log "[runtime-install] Skipping NeMo Sortformer dependencies by VOICE_DIARY_WITH_NEMO=0"
        return
    }

    Invoke-Step "Installing NeMo Sortformer dependencies" {
        Write-Log "[runtime-install] NeMo git ref=$NemoGitRef"
        Invoke-Native $Uv pip install cython packaging --python $PythonExe
        if ($CudaIndex) {
            Invoke-Native $Uv pip install "nemo_toolkit[asr,cu12] @ git+https://github.com/NVIDIA/NeMo.git@$NemoGitRef" "numba>=0.60" "llvmlite>=0.43" "cuda-bindings<13" --python $PythonExe
        } else {
            Invoke-Native $Uv pip install "nemo_toolkit[asr] @ git+https://github.com/NVIDIA/NeMo.git@$NemoGitRef" "numba>=0.60" "llvmlite>=0.43" --python $PythonExe
        }
    }
}

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Block
    )

    Write-Log "[runtime-install] $Label"
    & $Block
}

$sourceRootPath = (Resolve-Path $SourceRoot).Path
$backendProject = Join-Path $sourceRootPath "backend"
$venvDir = Join-Path $RuntimeRoot "venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"

if (-not (Test-Path (Join-Path $backendProject "pyproject.toml"))) {
    throw "Packaged backend pyproject.toml not found under $backendProject"
}

Write-State -Status "installing" -TorchVariant "unknown"

try {
    Write-Log "[runtime-install] source=$SourceRoot runtime=$RuntimeRoot appVersion=$AppVersion"
    $uv = Resolve-Uv
    $cudaIndex = Resolve-CudaTorchIndex
    $torchVariant = "cpu"
    if ($cudaIndex -match "/whl/(cu[0-9]+)$") {
        $torchVariant = "cuda-$($Matches[1])"
    }

    Invoke-Step "Ensuring managed Python 3.12 is available" {
        Invoke-Native $uv python install 3.12
    }

    Invoke-Step "Creating private Python runtime" {
        Invoke-Native $uv venv $venvDir --python 3.12 --clear
    }

    Invoke-Step "Installing Voice Diary backend dependencies" {
        Invoke-Native $uv pip install "$backendProject[ml]" --python $pythonExe
    }

    Invoke-Step "Removing unsupported optional k2 package when present" {
        & $uv pip uninstall k2 --python $pythonExe | Out-Null
    }

    if ($cudaIndex) {
        Invoke-Step "Installing CUDA PyTorch wheels" {
            Invoke-Native $uv pip install --force-reinstall torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url $cudaIndex --python $pythonExe
        }
    }

    Install-Nemo -Uv $uv -PythonExe $pythonExe -CudaIndex $cudaIndex

    Invoke-Step "Verifying backend runtime imports" {
        if ($env:VOICE_DIARY_WITH_NEMO -eq "0") {
            Invoke-Native $pythonExe -c "import torch; import faster_whisper; import pyannote.audio; import silero_vad; import speechbrain; from backend.providers.devices import normalize_indexed_cuda_device; assert normalize_indexed_cuda_device('cpu') == 'cpu'; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
        } else {
            Invoke-Native $pythonExe -c "import torch; import faster_whisper; import pyannote.audio; import silero_vad; import speechbrain; import nemo.collections.asr.models; from backend.providers.devices import normalize_indexed_cuda_device; assert normalize_indexed_cuda_device('cpu') == 'cpu'; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
        }
    }

    Write-State -Status "ok" -TorchVariant $torchVariant
} catch {
    Write-State -Status "error" -TorchVariant "unknown" -Message $_.Exception.Message
    Write-Log "[runtime-install] ERROR $($_.Exception.Message)"
    throw
}
