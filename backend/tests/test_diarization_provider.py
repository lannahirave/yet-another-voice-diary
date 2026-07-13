from __future__ import annotations

from dataclasses import dataclass
import sys
from types import ModuleType, SimpleNamespace
import warnings

import pytest

from backend.providers.diarization import (
    NeMoSortformerDiarizationProvider,
    PyAnnoteDiarizationProvider,
    _iter_diarization_tracks,
    _adapt_sortformer_segments,
    _suppress_torchaudio_backend_deprecation_warning,
    _suppress_unused_pyannote_torchcodec_warning,
    _speechbrain_windows_inspect_compat,
    create_diarization_provider,
)
from backend.providers.compat import suppress_known_ml_warnings


@dataclass
class FakeTurn:
    start: float
    end: float


class FakeAnnotation:
    def __init__(self) -> None:
        self.called = False

    def itertracks(self, *, yield_label: bool):
        self.called = yield_label
        return iter([(FakeTurn(0.1, 0.9), "track", "SPEAKER_00")])


class FakeDiarizeOutput:
    def __init__(self, annotation: FakeAnnotation) -> None:
        self.speaker_diarization = annotation


def test_iter_diarization_tracks_supports_legacy_annotation():
    annotation = FakeAnnotation()

    tracks = list(_iter_diarization_tracks(annotation))

    assert annotation.called is True
    assert tracks[0][2] == "SPEAKER_00"


def test_iter_diarization_tracks_supports_pyannote_four_output_wrapper():
    annotation = FakeAnnotation()

    tracks = list(_iter_diarization_tracks(FakeDiarizeOutput(annotation)))

    assert annotation.called is True
    assert tracks[0][0].start == 0.1


def test_iter_diarization_tracks_rejects_unknown_output():
    with pytest.raises(TypeError, match="unsupported diarization output type"):
        list(_iter_diarization_tracks(object()))


def test_adapt_sortformer_segments_supports_tuples_and_dicts():
    segments = _adapt_sortformer_segments(
        [
            (0.0, 1.2, "spk_0"),
            {"start": 1.2, "end": 2.4, "speaker": 1},
            SimpleNamespace(start=2.4, end=3.5, speaker="spk_2"),
        ]
    )

    assert [(s.start, s.end, s.speaker) for s in segments] == [
        (0.0, 1.2, "spk_0"),
        (1.2, 2.4, "1"),
        (2.4, 3.5, "spk_2"),
    ]


def test_create_diarization_provider_returns_expected_backend():
    assert isinstance(create_diarization_provider("pyannote"), PyAnnoteDiarizationProvider)
    assert isinstance(
        create_diarization_provider("sortformer-v2.1"),
        NeMoSortformerDiarizationProvider,
    )


def test_nemo_sortformer_load_fails_with_actionable_message(monkeypatch):
    provider = NeMoSortformerDiarizationProvider()

    def fail_import():
        raise ModuleNotFoundError("No module named 'nemo'")

    monkeypatch.setattr(
        "backend.providers.diarization.import_nemo_sortformer_class",
        fail_import,
    )

    with pytest.raises(RuntimeError, match=r"\.\[ml-nemo\]"):
        provider.load()

    assert provider._state == "ERROR"
    assert provider._error is not None
    assert "NeMo ASR toolkit is not installed" in provider._error


def test_speechbrain_windows_inspect_compat_ignores_inspect_callers(monkeypatch):
    """Verify the inspect guard prevents lazy module loading from inspect-originated calls.

    Uses a small fake SpeechBrain module so this unit test does not import the
    optional ML runtime or produce third-party extension warnings. The actual
    SpeechBrain integration is exercised by the ML e2e tests.
    """
    class FakeLazyModule:
        def ensure_module(self, stacklevel: int):
            return object()

    fake_importutils = SimpleNamespace(LazyModule=FakeLazyModule)
    fake_utils = ModuleType("speechbrain.utils")
    fake_utils.importutils = fake_importutils  # type: ignore[attr-defined]
    fake_speechbrain = ModuleType("speechbrain")
    fake_speechbrain.utils = fake_utils  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "speechbrain", fake_speechbrain)
    monkeypatch.setitem(sys.modules, "speechbrain.utils", fake_utils)

    lazy = FakeLazyModule()

    monkeypatch.setattr(
        "backend.providers.diarization._called_from_inspect_py",
        lambda: True,
    )

    with _speechbrain_windows_inspect_compat():
        with pytest.raises(AttributeError):
            lazy.ensure_module(1)


def test_suppress_unused_pyannote_torchcodec_warning_filters_only_target_warning():
    with _suppress_unused_pyannote_torchcodec_warning():
        warnings.warn(
            "\ntorchcodec is not installed correctly so built-in audio decoding will fail.\n"
            "* use audio preloaded in-memory as a {'waveform': (channel, time) torch.Tensor, 'sample_rate': int} dictionary;\n",
            UserWarning,
        )

        with pytest.warns(UserWarning, match="different warning"):
            warnings.warn("different warning", UserWarning)


def test_suppress_torchaudio_backend_deprecation_warning_filters_only_target_warning():
    with _suppress_torchaudio_backend_deprecation_warning():
        warnings.warn(
            "torchaudio._backend.list_audio_backends has been deprecated.",
            UserWarning,
        )

        with pytest.warns(UserWarning, match="different warning"):
            warnings.warn("different warning", UserWarning)


def test_suppress_known_ml_warnings_filters_dependency_messages_only():
    with suppress_known_ml_warnings():
        warnings.warn(
            "builtin type SwigPyPacked has no __module__ attribute",
            DeprecationWarning,
        )

        with pytest.warns(UserWarning, match="different warning"):
            warnings.warn("different warning", UserWarning)


def test_import_nemo_sortformer_class_suppresses_torchaudio_warning(monkeypatch):
    class FakeModels:
        SortformerEncLabelModel = object

    def fake_import(name: str):
        assert name == "nemo.collections.asr.models"
        warnings.warn(
            "torchaudio._backend.list_audio_backends has been deprecated.",
            UserWarning,
        )
        return FakeModels

    monkeypatch.setattr(
        "backend.providers.diarization._install_speechbrain_windows_inspect_patch",
        lambda: False,
    )
    monkeypatch.setattr(
        "backend.providers.diarization.importlib.import_module", fake_import
    )

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        from backend.providers.diarization import import_nemo_sortformer_class

        assert import_nemo_sortformer_class() is object

    assert recorded == []
