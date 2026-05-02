from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import warnings

import pytest

from backend.providers.diarization import (
    NeMoSortformerDiarizationProvider,
    PyAnnoteDiarizationProvider,
    _iter_diarization_tracks,
    _adapt_sortformer_segments,
    _suppress_unused_pyannote_torchcodec_warning,
    _speechbrain_windows_inspect_compat,
    create_diarization_provider,
)


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

    Uses ``k2_integration`` as the module name because k2 is the canonical
    real-world example of a SpeechBrain optional integration that breaks on
    Windows when accidentally loaded (see ``_remove_speechbrain_optional_lazy_imports``).
    """
    pytest.importorskip("speechbrain")
    from speechbrain.utils import importutils

    lazy = importutils.LazyModule(
        "speechbrain.k2_integration",
        "definitely_missing_optional_module",
        None,
    )

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
