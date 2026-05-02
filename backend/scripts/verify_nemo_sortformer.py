"""Verify NeMo Sortformer imports after SpeechBrain is already loaded."""
from __future__ import annotations

import speechbrain  # noqa: F401

from backend.providers.diarization import import_nemo_sortformer_class


def main() -> None:
    sortformer_cls = import_nemo_sortformer_class()
    print(f"NeMo Sortformer import: OK ({sortformer_cls.__name__})")


if __name__ == "__main__":
    main()
