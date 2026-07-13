"""Compatibility helpers for warnings emitted by pinned ML dependencies."""
from __future__ import annotations

from contextlib import contextmanager
import warnings
from collections.abc import Iterator


@contextmanager
def suppress_known_ml_warnings() -> Iterator[None]:
    """Suppress narrowly identified dependency warnings during model loading.

    These warnings originate in the pinned SpeechBrain/TorchAudio and
    CTranslate2 stacks. Keep the filter scoped to the import or model-load
    boundary so unrelated application warnings remain visible.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"builtin type (?:SwigPyPacked|SwigPyObject|swigvarlink) has no __module__ attribute",
            category=DeprecationWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r"Python 3\.14 will, by default, filter extracted tar archives.*",
            category=DeprecationWarning,
            module=r"nemo\.core\.connectors\.save_restore_connector",
        )
        warnings.filterwarnings(
            "ignore",
            message=r"torchaudio\._backend\.list_audio_backends has been deprecated\..*",
            category=UserWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=(
                r"Module 'speechbrain\.pretrained' was deprecated, redirecting to "
                r"'speechbrain\.inference'\..*"
            ),
            category=UserWarning,
        )
        yield
