from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _select_pytorch_cuda_index(cuda_version: str) -> str:
    try:
        major_text, minor_text, *_ = cuda_version.split(".")
        major = int(major_text)
        minor = int(minor_text)
    except ValueError:
        return ""

    if major >= 13 or (major == 12 and minor >= 9):
        return "https://download.pytorch.org/whl/cu129"
    if major == 12 and minor >= 8:
        return "https://download.pytorch.org/whl/cu128"
    if major == 12 and minor >= 6:
        return "https://download.pytorch.org/whl/cu126"
    return ""


def _parse_nvidia_smi_cuda_version(line: str) -> str:
    import re

    match = re.search(r"CUDA(?: UMD)? Version:\s+([0-9]+\.[0-9]+)", line)
    return match.group(1) if match else ""


def test_runtime_installers_do_not_use_floating_nemo_main() -> None:
    checked_paths = [
        "backend/pyproject.toml",
        "scripts/install.bat",
        "scripts/install-nemo.bat",
        "scripts/install.sh",
        "scripts/runtime-install.ps1",
        "scripts/runtime-install.sh",
    ]

    for path in checked_paths:
        text = _read(path)
        assert "NeMo.git@main" not in text
        assert "7ccc79b525f205c2c20595a7dfc927051610962c" in text


def test_runtime_installers_use_python312_safe_nemo_constraints() -> None:
    checked_paths = [
        "backend/pyproject.toml",
        "scripts/install.bat",
        "scripts/install-nemo.bat",
        "scripts/install.sh",
        "scripts/runtime-install.ps1",
        "scripts/runtime-install.sh",
    ]

    for path in checked_paths:
        text = _read(path)
        assert "numba>=0.60" in text
        assert "llvmlite>=0.43" in text


def test_cuda_nemo_installs_pin_cuda_bindings_to_match_cuda_python_12() -> None:
    checked_paths = [
        "scripts/install.bat",
        "scripts/install-nemo.bat",
        "scripts/install.sh",
        "scripts/runtime-install.ps1",
        "scripts/runtime-install.sh",
    ]

    for path in checked_paths:
        assert "cuda-bindings<13" in _read(path)


def test_runtime_installers_select_supported_pytorch_cuda_wheels() -> None:
    runtime_scripts = [
        "scripts/install.bat",
        "scripts/install.sh",
        "scripts/runtime-install.ps1",
        "scripts/runtime-install.sh",
    ]

    for path in runtime_scripts:
        text = _read(path)
        assert "https://download.pytorch.org/whl/cu126" in text
        assert "https://download.pytorch.org/whl/cu128" in text
        assert "https://download.pytorch.org/whl/cu129" in text

    all_script_text = "\n".join(_read(path) for path in runtime_scripts)
    assert "NEMO_CUDA_EXTRA=cu13" not in all_script_text
    assert "[asr,cu13]" not in all_script_text


def test_pytorch_cuda_selection_boundaries_match_installer_policy() -> None:
    assert _select_pytorch_cuda_index("12.5") == ""
    assert _select_pytorch_cuda_index("12.6") == "https://download.pytorch.org/whl/cu126"
    assert _select_pytorch_cuda_index("12.7") == "https://download.pytorch.org/whl/cu126"
    assert _select_pytorch_cuda_index("12.8") == "https://download.pytorch.org/whl/cu128"
    assert _select_pytorch_cuda_index("12.9") == "https://download.pytorch.org/whl/cu129"
    assert _select_pytorch_cuda_index("13.0") == "https://download.pytorch.org/whl/cu129"
    assert _select_pytorch_cuda_index("not-a-version") == ""


def test_nvidia_smi_cuda_version_parser_accepts_standard_and_umd_labels() -> None:
    assert _parse_nvidia_smi_cuda_version("CUDA Version: 12.8") == "12.8"
    assert _parse_nvidia_smi_cuda_version("CUDA UMD Version: 13.3") == "13.3"
    assert _select_pytorch_cuda_index(_parse_nvidia_smi_cuda_version("CUDA UMD Version: 13.3")) == (
        "https://download.pytorch.org/whl/cu129"
    )

    checked_paths = [
        "scripts/install.bat",
        "scripts/install-nemo.bat",
        "scripts/install.sh",
        "scripts/runtime-install.ps1",
        "scripts/runtime-install.sh",
    ]
    for path in checked_paths:
        assert "UMD" in _read(path)


def test_electron_builder_packages_runtime_for_all_desktop_targets() -> None:
    package_json = json.loads(_read("frontend/package.json"))
    build_config = package_json["build"]

    assert build_config["win"]["target"] == "nsis"
    assert build_config["mac"]["target"] == "dmg"
    assert build_config["linux"]["target"] == ["AppImage", "deb"]

    resources = build_config["extraResources"]
    script_resource = next(item for item in resources if item["to"] == "scripts")
    assert "runtime-install.ps1" in script_resource["filter"]
    assert "runtime-install.sh" in script_resource["filter"]

    backend_resource = next(item for item in resources if item["to"] == "backend")
    assert "pyproject.toml" in backend_resource["filter"]
