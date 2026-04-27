"""Speaker embedding provider implementations."""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

log = logging.getLogger(__name__)


def _patch_speechbrain_hf_compat() -> None:
    """Patch two huggingface_hub API breaks in newer versions.

    1. use_auth_token kwarg removed — SpeechBrain passes it; newer hub rejects it.
    2. RemoteEntryNotFoundError raised instead of requests.HTTPError on 404 —
       SpeechBrain's fetching.py catches HTTPError and converts to ValueError so
       interfaces.py can silently skip the optional custom.py module.  With newer
       hub that conversion never happens and the 404 propagates as an unhandled
       RemoteEntryNotFoundError.

    SpeechBrain caches the hf_hub_download reference at import time, so both the
    huggingface_hub module attribute and speechbrain.utils.fetching.hf_hub_download
    must be patched.
    """
    try:
        import inspect
        import huggingface_hub

        orig = huggingface_hub.hf_hub_download
        needs_auth_patch = "use_auth_token" not in inspect.signature(orig).parameters

        def _compat(*args: object, use_auth_token: object = None, **kwargs: object) -> object:
            try:
                return orig(*args, **kwargs)
            except Exception as exc:
                # Newer huggingface_hub raises RemoteEntryNotFoundError on 404 instead
                # of requests.exceptions.HTTPError.  SpeechBrain catches the latter to
                # gracefully skip the optional custom.py file; re-raise as HTTPError so
                # that existing except-clause in fetching.py fires.
                exc_type = type(exc).__name__
                if "EntryNotFoundError" in exc_type or "RemoteEntryNotFound" in exc_type:
                    from requests.exceptions import HTTPError
                    raise HTTPError(f"404 Client Error: {exc}") from exc
                raise

        # Always install on both references regardless of auth-token state so that
        # the RemoteEntryNotFoundError → HTTPError conversion is always active.
        huggingface_hub.hf_hub_download = _compat  # type: ignore[assignment]

        import speechbrain.utils.fetching as _sb_fetching  # type: ignore[import-untyped]

        _sb_fetching.hf_hub_download = _compat  # type: ignore[assignment]
    except Exception:
        pass


class ECAPATDNNEmbeddingProvider:
    """SpeechBrain ECAPA-TDNN speaker embedding provider.

    The real model is loaded lazily. Missing dependencies or model failures are
    surfaced as runtime errors with full backend tracebacks; fake embeddings are
    not generated in production code.
    """

    def __init__(self, model_id: str = "ecapa"):
        self.model_id = model_id
        self._model: Optional[Any] = None
        self._state = "UNLOADED"
        self._error: Optional[str] = None

    def _load_model(self):
        """Load model lazily."""
        self._state = "LOADING"
        self._error = None
        model_name = (
            "speechbrain/spkrec-ecapa-voxceleb"
            if self.model_id in {"ecapa", "ecapa-tdnn"}
            else self.model_id
        )
        try:
            import torch  # type: ignore[import-untyped]
            from speechbrain.inference import SpeakerRecognition  # type: ignore[import-untyped]
        except Exception as exc:
            self._error = (
                f"speechbrain/torch not installed or could not be loaded: {exc}"
            )
            self._state = "ERROR"
            log.exception("SpeechBrain embedding import failed")
            raise RuntimeError(self._error) from exc

        _patch_speechbrain_hf_compat()

        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            self._model = SpeakerRecognition.from_hparams(
                source=model_name,
                savedir=f"backend/pretrained_models/{model_name.replace('/', '_')}",
                run_opts={"device": device},
            )
        except Exception as exc:
            self._error = f"failed to load embedding model {model_name}: {exc}"
            self._state = "ERROR"
            log.exception("SpeechBrain embedding model load failed")
            raise RuntimeError(self._error) from exc

        self._state = "LOADED"

    def load(self) -> None:
        if self._model is None:
            self._load_model()

    def unload(self) -> None:
        self._model = None
        self._state = "UNLOADED"
        self._error = None

    def embed(self, audio: np.ndarray) -> np.ndarray:
        """Extract speaker embedding."""
        audio = np.asarray(audio, dtype=np.float32)
        if audio.size == 0:
            return np.zeros(192, dtype=np.float32)

        if self._model is None:
            self.load()

        import torch  # type: ignore[import-untyped]

        assert self._model is not None
        try:
            with torch.no_grad():
                waveform = torch.from_numpy(audio).unsqueeze(0)
                embedding = self._model.encode_batch(waveform).squeeze().detach().cpu().numpy()
        except Exception as exc:
            self._error = f"speaker embedding inference failed: {exc}"
            self._state = "ERROR"
            log.exception("SpeechBrain embedding inference failed")
            raise RuntimeError(self._error) from exc

        return self._normalize(np.asarray(embedding, dtype=np.float32))

    @staticmethod
    def _normalize(embedding: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(embedding))
        if norm == 0.0 or not np.isfinite(norm):
            return np.zeros_like(embedding, dtype=np.float32)
        return (embedding / norm).astype(np.float32)
