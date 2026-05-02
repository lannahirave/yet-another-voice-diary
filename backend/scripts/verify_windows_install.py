"""Verify the Windows full-install environment used by Electron."""
from __future__ import annotations

import argparse
import importlib.util
import sys
import warnings
from pathlib import Path


def _print(message: str) -> None:
    print(message, flush=True)


def _expected_python(root: Path) -> Path:
    return root / ".venv-ml" / "Scripts" / "python.exe"


def _verify_python(root: Path) -> None:
    expected = _expected_python(root).resolve()
    actual = Path(sys.executable).resolve()
    _print(f"Python: {actual}")
    if actual != expected:
        raise RuntimeError(f"expected installer Python {expected}, got {actual}")


def _verify_torch(*, expect_cuda: bool) -> None:
    import torch  # type: ignore[import-untyped]

    cuda_available = torch.cuda.is_available()
    _print(
        "Torch: "
        f"{torch.__version__} CUDA={cuda_available} runtime={torch.version.cuda}"
    )
    if expect_cuda and not cuda_available:
        raise RuntimeError("CUDA PyTorch was expected but torch.cuda.is_available() is false")


def _verify_core_imports() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"\ntorchcodec is not installed correctly so built-in audio decoding will fail\..*",
            category=UserWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r"torchaudio\._backend\.list_audio_backends has been deprecated\..*",
            category=UserWarning,
        )
        import faster_whisper  # noqa: F401
        import pyannote.audio  # noqa: F401
        import silero_vad  # noqa: F401
        import speechbrain  # noqa: F401

    _print("Core ML imports: OK")


def _verify_device_normalization() -> None:
    from backend.providers.devices import normalize_indexed_cuda_device

    if normalize_indexed_cuda_device("cuda") != "cuda:0":
        raise RuntimeError("CUDA device normalization failed")
    if normalize_indexed_cuda_device("cpu") != "cpu":
        raise RuntimeError("CPU device normalization failed")
    _print("Device normalization: OK")


def _warn_k2() -> None:
    if importlib.util.find_spec("k2") is not None:
        _print(
            "WARNING: optional package k2 is installed. Voice Diary does not need it "
            "on Windows; broken k2 wheels can reintroduce SpeechBrain import noise."
        )


def _verify_nemo() -> None:
    from backend.providers.diarization import import_nemo_sortformer_class

    sortformer_cls = import_nemo_sortformer_class()
    _print(f"NeMo Sortformer import: OK ({sortformer_cls.__name__})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-nemo", action="store_true")
    parser.add_argument("--expect-cuda", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    _verify_python(root)
    _verify_torch(expect_cuda=args.expect_cuda)
    _verify_core_imports()
    _verify_device_normalization()
    _warn_k2()
    if args.with_nemo:
        _verify_nemo()


if __name__ == "__main__":
    main()
