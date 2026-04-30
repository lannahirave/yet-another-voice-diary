"""Diarization provider implementations."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import importlib
import inspect
import logging
from types import ModuleType
import sys
from typing import Any, Callable, Optional
import warnings

import numpy as np

from ..config import normalize_diarization_model_id

log = logging.getLogger(__name__)
SORTFORMER_V21_MODEL_ID = "sortformer-v2.1"
SORTFORMER_V21_REPO_ID = "nvidia/diar_streaming_sortformer_4spk-v2.1"


def _is_unloaded_speechbrain_lazy_module(value: object) -> bool:
    type_module = type(value).__module__
    return (
        type_module == "speechbrain.utils.importutils"
        and "LazyModule(" in repr(value)
        and "loaded=False" in repr(value)
    )


def _remove_speechbrain_optional_lazy_imports() -> None:
    """Avoid SpeechBrain optional lazy imports breaking PyAnnote imports."""
    for module_name, module in list(sys.modules.items()):
        if (
            module_name.startswith("speechbrain.")
            and _is_unloaded_speechbrain_lazy_module(module)
        ):
            sys.modules.pop(module_name, None)

    speechbrain = sys.modules.get("speechbrain")
    if speechbrain is None:
        return

    for name, value in list(vars(speechbrain).items()):
        if _is_unloaded_speechbrain_lazy_module(value):
            vars(speechbrain).pop(name, None)


def _ensure_lightning_utilities() -> None:
    """Make ``lightning.pytorch.utilities`` accessible as a module attribute.

    lightning >= 2.4 lazy-loads subpackages.  When
    ``import lightning.pytorch as pl`` runs inside the ``pl_legacy_patch``
    context manager (triggered by PyAnnote checkpoint loading), Python
    may not yet have ``utilities`` registered as a ``pl`` attribute.
    Force the import and pin the attribute so the lookup succeeds.
    """
    try:
        import lightning.pytorch  # noqa: F401
        import lightning.pytorch.utilities as _ut
        import lightning.pytorch as _pl
        _pl.utilities = _ut  # type: ignore[attr-defined]
    except Exception:
        pass


@contextmanager
def _speechbrain_windows_inspect_compat():
    """
    Make SpeechBrain lazy redirects ignore Python inspect on Windows paths.

    SpeechBrain 1.1 guards against accidental optional imports from inspect.py,
    but its path check only matches "/inspect.py". On Windows, inspect reports
    backslash paths, so optional redirects such as k2 can be imported while
    Lightning calls inspect.stack() during PyAnnote model loading.
    """
    try:
        from speechbrain.utils import importutils  # type: ignore[import-untyped]
    except Exception:
        yield
        return

    original: Callable[[Any, int], ModuleType] = importutils.LazyModule.ensure_module
    if getattr(original, "_voice_diary_windows_inspect_compat", False):
        yield
        return

    def ensure_module(self: Any, stacklevel: int) -> ModuleType:
        importer_frame = None
        try:
            importer_frame = inspect.getframeinfo(sys._getframe(stacklevel + 1))
        except AttributeError:
            pass

        if importer_frame is not None:
            normalized = importer_frame.filename.replace("\\", "/")
            if normalized.endswith("/inspect.py"):
                raise AttributeError()

        return original(self, stacklevel)

    setattr(ensure_module, "_voice_diary_windows_inspect_compat", True)
    importutils.LazyModule.ensure_module = ensure_module
    try:
        yield
    finally:
        importutils.LazyModule.ensure_module = original


@contextmanager
def _pyannote_checkpoint_load_compat(model_name: str):
    """Allow trusted PyAnnote 3.1 checkpoints to load under torch>=2.6."""
    if model_name != "pyannote/speaker-diarization-3.1":
        yield
        return

    import torch  # type: ignore[import-untyped]

    original_load = torch.load

    def patched_load(*args, **kwargs):
        kwargs["weights_only"] = False
        return original_load(*args, **kwargs)

    torch.load = patched_load
    try:
        yield
    finally:
        torch.load = original_load


@contextmanager
def _suppress_unused_pyannote_torchcodec_warning():
    """
    Ignore PyAnnote's torchcodec warning for our in-memory waveform path.

    The app always calls the diarization pipeline with:
    ``{"waveform": torch.Tensor, "sample_rate": int}``
    so PyAnnote never needs its built-in file decoding path here.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"\ntorchcodec is not installed correctly so built-in audio decoding will fail\..*",
            category=UserWarning,
        )
        yield


class DiarizationSegment:
    """A diarization segment."""

    def __init__(self, start: float, end: float, speaker: str):
        self.start = start
        self.end = end
        self.speaker = speaker


def _coerce_sortformer_segment(segment: Any) -> Optional[DiarizationSegment]:
    if isinstance(segment, (list, tuple)) and len(segment) >= 3:
        start, end, speaker = segment[0], segment[1], segment[2]
        return DiarizationSegment(float(start), float(end), str(speaker))

    if isinstance(segment, dict):
        try:
            start = segment.get("start", segment.get("begin", segment.get("start_time")))
            end = segment.get("end", segment.get("stop", segment.get("end_time")))
            speaker = segment.get("speaker", segment.get("label", segment.get("speaker_id")))
            if start is None or end is None or speaker is None:
                return None
            return DiarizationSegment(float(start), float(end), str(speaker))
        except Exception:
            return None

    start = getattr(segment, "start", getattr(segment, "begin", None))
    end = getattr(segment, "end", getattr(segment, "stop", None))
    speaker = getattr(
        segment,
        "speaker",
        getattr(segment, "label", getattr(segment, "speaker_id", None)),
    )
    if start is None or end is None or speaker is None:
        return None
    return DiarizationSegment(float(start), float(end), str(speaker))


def _adapt_sortformer_segments(predicted_segments: Any) -> list[DiarizationSegment]:
    adapted: list[DiarizationSegment] = []
    for segment in predicted_segments or []:
        coerced = _coerce_sortformer_segment(segment)
        if coerced is not None:
            adapted.append(coerced)
    return adapted


def _iter_diarization_tracks(diarization: Any):
    """Yield labeled tracks from PyAnnote 3.x Annotation or 4.x DiarizeOutput."""
    annotation = getattr(diarization, "speaker_diarization", diarization)
    if not hasattr(annotation, "itertracks"):
        raise TypeError(
            f"unsupported diarization output type: {type(diarization).__name__}"
        )
    return annotation.itertracks(yield_label=True)


class PyAnnoteDiarizationProvider:
    """PyAnnote-based diarization provider."""

    def __init__(self, model_id: str = "pyannote", *, device: str = "auto"):
        self.model_id = normalize_diarization_model_id(model_id)
        self.device = device
        self._model: Optional[Any] = None
        self._state = "UNLOADED"
        self._error: Optional[str] = None

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load_model(self):
        """Load model lazily."""
        self._state = "LOADING"
        self._error = None
        model_name = (
            "pyannote/speaker-diarization-3.1"
            if self.model_id in {"pyannote", "pyannote-3.1"}
            else self.model_id
        )
        try:
            _remove_speechbrain_optional_lazy_imports()
            # lightning 2.4+ lazy-loads subpackages; force-ensure
            # 'utilities' is available as an attribute on lightning.pytorch
            # before pyannote triggers pl_legacy_patch() which accesses
            # pl.utilities via attribute lookup.
            _ensure_lightning_utilities()
            with _suppress_unused_pyannote_torchcodec_warning():
                from pyannote.audio import Pipeline  # type: ignore[import-untyped]
        except Exception as exc:
            self._error = (
                f"pyannote.audio not installed or could not be loaded: {exc}"
            )
            self._state = "ERROR"
            log.exception("PyAnnote diarization import failed")
            raise RuntimeError(self._error) from exc

        try:
            _remove_speechbrain_optional_lazy_imports()
            _ensure_lightning_utilities()
            speechbrain_compat = (
                _speechbrain_windows_inspect_compat()
                if sys.platform.startswith("win")
                else nullcontext()
            )
            with (
                speechbrain_compat,
                _pyannote_checkpoint_load_compat(model_name),
                _suppress_unused_pyannote_torchcodec_warning(),
            ):
                self._model = Pipeline.from_pretrained(model_name)
        except Exception as exc:
            self._error = (
                f"failed to load diarization model {model_name}: {exc}"
            )
            self._state = "ERROR"
            log.exception("PyAnnote diarization model load failed")
            raise RuntimeError(self._error) from exc

        resolved_device = self._resolve_device()
        if resolved_device != "cpu":
            import torch
            self._model = self._model.to(torch.device(resolved_device))

        self._state = "LOADED"

    def load(self) -> None:
        if self._model is None:
            self._load_model()

    def unload(self) -> None:
        self._model = None
        self._state = "UNLOADED"
        self._error = None

    def segment(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> list[DiarizationSegment]:
        """Segment audio by speaker."""
        if audio.size == 0:
            return []

        if self._model is None:
            self.load()

        import torch  # type: ignore[import-untyped]

        assert self._model is not None
        try:
            waveform = torch.from_numpy(np.asarray(audio, dtype=np.float32)).unsqueeze(0)
            speechbrain_compat = (
                _speechbrain_windows_inspect_compat()
                if sys.platform.startswith("win")
                else nullcontext()
            )
            with speechbrain_compat:
                diarization = self._model(
                    {"waveform": waveform, "sample_rate": sample_rate}
                )
        except Exception as exc:
            self._error = f"diarization inference failed: {exc}"
            self._state = "ERROR"
            log.exception("PyAnnote diarization inference failed")
            raise RuntimeError(self._error) from exc

        return [
            DiarizationSegment(
                start=float(turn.start),
                end=float(turn.end),
                speaker=str(speaker),
            )
            for turn, _, speaker in _iter_diarization_tracks(diarization)
        ]


class NeMoSortformerDiarizationProvider:
    """NeMo Sortformer-based diarization provider.

    This app uses Sortformer in the current utterance-based pipeline, so it is
    invoked on already-closed VAD chunks rather than on the model's native
    live-streaming step API. We still configure the published high-accuracy
    streaming parameters so inference follows NVIDIA's recommended cache sizes.

    NeMo Sortformer requires CUDA; it does not support Apple MPS.
    """

    def __init__(self, model_id: str = SORTFORMER_V21_MODEL_ID, *, device: str = "auto"):
        self.model_id = model_id
        self.device = device
        self._model: Optional[Any] = None
        self._state = "UNLOADED"
        self._error: Optional[str] = None

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        import torch
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _load_model(self) -> None:
        self._state = "LOADING"
        self._error = None

        device = self._resolve_device()
        if device == "mps":
            self._error = "NeMo Sortformer does not support MPS; use PyAnnote for Apple Silicon"
            self._state = "ERROR"
            raise RuntimeError(self._error)

        if self.model_id != SORTFORMER_V21_MODEL_ID:
            self._error = f"unsupported NeMo diarization model_id: {self.model_id}"
            self._state = "ERROR"
            raise RuntimeError(self._error)

        try:
            models_mod = importlib.import_module("nemo.collections.asr.models")
            sortformer_cls = getattr(models_mod, "SortformerEncLabelModel")
        except Exception as exc:
            self._error = (
                "NeMo ASR toolkit is not installed. Install backend with "
                '`pip install -e ".[ml-nemo]"` to enable NVIDIA Streaming '
                f"Sortformer ({exc})"
            )
            self._state = "ERROR"
            log.exception("NeMo Sortformer import failed")
            raise RuntimeError(self._error) from exc

        try:
            self._model = sortformer_cls.from_pretrained(SORTFORMER_V21_REPO_ID)
            self._model.eval()
            modules = getattr(self._model, "sortformer_modules", None)
            if modules is not None:
                modules.chunk_len = 340
                modules.chunk_right_context = 40
                modules.fifo_len = 40
                modules.spkcache_update_period = 300
        except Exception as exc:
            self._error = f"failed to load diarization model {SORTFORMER_V21_REPO_ID}: {exc}"
            self._state = "ERROR"
            log.exception("NeMo Sortformer model load failed")
            raise RuntimeError(self._error) from exc

        self._state = "LOADED"

    def load(self) -> None:
        if self._model is None:
            self._load_model()

    def unload(self) -> None:
        self._model = None
        self._state = "UNLOADED"
        self._error = None

    def segment(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> list[DiarizationSegment]:
        if audio.size == 0:
            return []

        if self._model is None:
            self.load()

        assert self._model is not None
        try:
            predicted = self._model.diarize(
                audio=[np.ascontiguousarray(audio, dtype=np.float32)],
                batch_size=1,
                sample_rate=sample_rate,
            )
        except Exception as exc:
            self._error = f"diarization inference failed: {exc}"
            self._state = "ERROR"
            log.exception("NeMo Sortformer inference failed")
            raise RuntimeError(self._error) from exc

        if not predicted:
            return []
        return _adapt_sortformer_segments(predicted[0])


def create_diarization_provider(
    model_id: str,
    *,
    device: str = "auto",
) -> PyAnnoteDiarizationProvider | NeMoSortformerDiarizationProvider:
    normalized = normalize_diarization_model_id(model_id)
    if normalized in {"pyannote", "pyannote-3.1"}:
        return PyAnnoteDiarizationProvider(model_id=normalized, device=device)
    if normalized == SORTFORMER_V21_MODEL_ID:
        return NeMoSortformerDiarizationProvider(model_id=normalized, device=device)
    raise ValueError(f"unsupported diarization model_id: {model_id}")
