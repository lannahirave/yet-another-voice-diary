"""ElevenLabs Scribe ASR provider (API-based, no local model)."""
from __future__ import annotations

import io
import logging
import wave
from typing import Optional

import numpy as np

from ..models import Utterance

log = logging.getLogger(__name__)

ELEVENLABS_S2T_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_MODEL_ID = "scribe_v1"


class ElevenLabsASRProvider:
    """ElevenLabs Scribe speech-to-text via HTTP API."""

    model_id: str = "elevenlabs-scribe"

    def __init__(self, api_token: str = "") -> None:
        self.api_token = api_token
        self._model: bool = False
        self._state = "LOADED" if api_token else "UNLOADED"
        self._error: Optional[str] = None
        self.device = "cloud"

        # Blocklist fields (set by pipeline coordinator before transcribe)
        self.blocklist_enabled: bool = False
        self._blocklists: dict[str, set[str]] = {}
        self._blocklists_loaded: bool = False

    # ---- model lifecycle ----

    def load(self) -> None:
        if self.api_token:
            self._state = "LOADED"
            self._error = None
        else:
            self._state = "UNLOADED"
            self._error = "API token not configured"

    def unload(self) -> None:
        self._state = "UNLOADED"
        self._error = None

    # ---- inference ----

    def transcribe(
        self,
        audio: np.ndarray,
        language_hint: Optional[str] = None,
    ) -> Utterance:
        """Send audio to ElevenLabs Scribe and return an Utterance."""
        if audio.size == 0:
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if float(np.sqrt(np.mean(np.square(audio)))) < 1e-4:
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        if not self.api_token:
            self._state = "UNLOADED"
            self._error = "API token not configured"
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        try:
            import requests
        except ImportError:
            self._state = "ERROR"
            self._error = "requests library not installed"
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        wav_bytes = _encode_wav(audio)
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"model_id": ELEVENLABS_MODEL_ID}
        if language_hint:
            data["language_code"] = language_hint.lower()

        headers = {"xi-api-key": self.api_token}

        try:
            resp = requests.post(
                ELEVENLABS_S2T_URL,
                headers=headers,
                files=files,
                data=data,
                timeout=30,
            )
        except requests.RequestException as exc:
            self._state = "ERROR"
            self._error = f"ElevenLabs API request failed: {exc}"
            log.exception("ElevenLabs API request failed")
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        if not resp.ok:
            self._state = "ERROR"
            self._error = f"ElevenLabs API error {resp.status_code}: {resp.text[:500]}"
            log.error("ElevenLabs API error %d: %s", resp.status_code, resp.text[:500])
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        try:
            body = resp.json()
        except Exception as exc:
            self._error = f"ElevenLabs API bad JSON response: {exc}"
            log.exception("ElevenLabs API bad JSON response")
            return Utterance(transcript="", language=language_hint, confidence=0.0)

        self._state = "LOADED"
        self._error = None

        transcript = str(body.get("text", ""))
        detected_lang: Optional[str] = body.get("language_code") or language_hint

        return Utterance(
            transcript=transcript,
            language=detected_lang,
            confidence=float(body.get("confidence", 0.0)),
        )


def _encode_wav(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Encode float32 mono audio as 16-bit PCM WAV bytes."""
    audio_int16 = (audio * 32767).clip(-32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return buf.getvalue()
