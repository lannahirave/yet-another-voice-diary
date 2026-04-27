"""Base provider protocols."""
from typing import Optional, Protocol

import numpy as np

from ..models import Utterance


class ASRProvider(Protocol):
    """Automatic Speech Recognition provider."""

    def transcribe(
        self,
        audio: np.ndarray,
        language_hint: Optional[str] = None
    ) -> Utterance:
        """Transcribe audio to text."""
        ...


class DiarizationProvider(Protocol):
    """Speaker diarization provider."""

    class Segment:
        """A diarization segment."""
        start: float
        end: float
        speaker: str

    def segment(self, audio: np.ndarray) -> list["DiarizationProvider.Segment"]:
        """Segment audio by speaker."""
        ...


class EmbeddingProvider(Protocol):
    """Speaker embedding provider."""

    def embed(self, audio: np.ndarray) -> np.ndarray:
        """Extract speaker embedding from audio."""
        ...
