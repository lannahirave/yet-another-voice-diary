"""Provider device-string normalization helpers."""
from __future__ import annotations


def normalize_indexed_cuda_device(device: str) -> str:
    """Return an indexed CUDA device string for libraries that require it."""
    if device == "cuda":
        return "cuda:0"
    return device
