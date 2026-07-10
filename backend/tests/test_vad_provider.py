from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

import numpy as np

from backend.providers.vad import (
    FIRERED_ALLOW_PATTERNS,
    FIRERED_REPO_ID,
    FIRERED_REVISION,
    FireRedVADProvider,
    FireRedVadSession,
    create_vad_provider,
)


@dataclass
class _FrameResult:
    frame_idx: int
    is_speech: bool = False
    is_speech_start: bool = False
    is_speech_end: bool = False
    speech_start_frame: int = -1
    speech_end_frame: int = -1


class _FakeEngine:
    def __init__(self, results: dict[int, _FrameResult] | None = None) -> None:
        self.results = results or {}
        self.frames: list[np.ndarray] = []
        self.reset_count = 0
        self.model_caches: dict[str, int] = {}
        self.postprocessor = SimpleNamespace(max_speech_frame=2_000)
        self.config = SimpleNamespace(max_speech_frame=2_000)

    def reset(self) -> None:
        self.reset_count += 1
        self.model_caches = {}

    def detect_frame(self, frame: np.ndarray) -> _FrameResult:
        self.frames.append(frame.copy())
        index = len(self.frames)
        self.model_caches["frames"] = index
        return self.results.get(index, _FrameResult(frame_idx=index))


class _FailingEngine(_FakeEngine):
    def detect_frame(self, frame: np.ndarray) -> _FrameResult:
        raise RuntimeError("fake inference failure")


def _provider(**overrides: int | float) -> FireRedVADProvider:
    values: dict[str, int | float] = {
        "speech_pad_pre_ms": 20,
        "speech_pad_post_ms": 10,
        "min_utterance_ms": 20,
        "min_silence_ms": 20,
        "max_utterance_ms": 8_000,
    }
    values.update(overrides)
    return FireRedVADProvider(**values)


def test_firered_feeds_overlapping_frames_and_scales_pcm16() -> None:
    engine = _FakeEngine()
    session = FireRedVadSession(_provider(), engine)
    audio = np.linspace(-2.0, 2.0, 560, dtype=np.float32)

    assert session.process(audio, 16_000) is None

    assert len(engine.frames) == 2
    assert all(len(frame) == 400 for frame in engine.frames)
    np.testing.assert_allclose(engine.frames[1], np.clip(audio[160:560], -1, 1) * 32767)
    assert engine.frames[0].min() == -32767
    assert engine.frames[1].max() == 32767


def test_firered_load_downloads_only_pinned_streaming_assets(
    monkeypatch, tmp_path: Path
) -> None:
    download_calls: list[dict[str, object]] = []

    hub_module = ModuleType("huggingface_hub")

    def _snapshot_download(**kwargs: object) -> str:
        download_calls.append(kwargs)
        return str(tmp_path)

    hub_module.snapshot_download = _snapshot_download  # type: ignore[attr-defined]

    class _FakeModel:
        def cpu(self) -> "_FakeModel":
            return self

        def eval(self) -> "_FakeModel":
            return self

    detect_module = ModuleType("fireredvad.core.detect_model")
    detect_module.DetectModel = SimpleNamespace(  # type: ignore[attr-defined]
        from_pretrained=lambda _path: _FakeModel()
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub_module)
    monkeypatch.setitem(sys.modules, "fireredvad", ModuleType("fireredvad"))
    monkeypatch.setitem(sys.modules, "fireredvad.core", ModuleType("fireredvad.core"))
    monkeypatch.setitem(sys.modules, "fireredvad.core.detect_model", detect_module)

    provider = _provider()
    provider.load()

    assert provider._state == "LOADED"
    assert download_calls == [
        {
            "repo_id": FIRERED_REPO_ID,
            "revision": FIRERED_REVISION,
            "allow_patterns": list(FIRERED_ALLOW_PATTERNS),
        }
    ]


def test_firered_backdates_onset_and_applies_post_padding() -> None:
    engine = _FakeEngine(
        {
            2: _FrameResult(
                frame_idx=2,
                is_speech=True,
                is_speech_start=True,
                speech_start_frame=1,
            ),
            3: _FrameResult(
                frame_idx=3,
                is_speech_end=True,
                speech_start_frame=1,
                speech_end_frame=3,
            ),
        }
    )
    session = FireRedVadSession(_provider(), engine)
    audio = np.arange(880, dtype=np.float32) / 1_000

    segment = session.process(audio, 16_000)

    assert segment is not None
    assert segment.started_ms == 0
    assert segment.ended_ms == 55
    assert segment.duration_ms == 55
    np.testing.assert_array_equal(segment.audio, audio)


def test_firered_cancels_pending_post_padding_when_speech_restarts() -> None:
    engine = _FakeEngine(
        {
            1: _FrameResult(1, True, True, False, 1),
            2: _FrameResult(2, False, False, True, 1, 2),
            3: _FrameResult(3, True, True, False, 3),
            4: _FrameResult(4, False, False, True, 3, 4),
        }
    )
    session = FireRedVadSession(_provider(speech_pad_post_ms=40), engine)

    segment = session.process(np.ones(1_520, dtype=np.float32), 16_000)

    assert segment is not None
    assert segment.started_ms == 0
    assert segment.duration_ms == 95
    assert len(session._completed) == 0


def test_firered_forced_split_snapshot_finalize_and_reset() -> None:
    class _LongSpeechEngine(_FakeEngine):
        def detect_frame(self, frame: np.ndarray) -> _FrameResult:
            self.frames.append(frame.copy())
            index = len(self.frames)
            if index == 1:
                return _FrameResult(index, True, True, False, 1)
            if index == 800:
                return _FrameResult(index, True, False, True, 1, index)
            return _FrameResult(index, True)

    engine = _LongSpeechEngine()
    session = FireRedVadSession(_provider(), engine)
    session.max_utterance_ms = 8_000

    assert engine.postprocessor.max_speech_frame == 800
    assert session.process(np.ones(64_000, dtype=np.float32), 16_000) is None
    snapshot = session.snapshot()
    assert snapshot is not None
    assert snapshot.duration_ms == 4_000

    segment = session.process(np.ones(64_240, dtype=np.float32), 16_000)
    assert segment is not None
    assert 8_000 <= segment.duration_ms <= 8_020
    assert session.finalize() is None

    session.reset()
    assert session.snapshot() is None
    assert engine.reset_count == 2


def test_firered_sessions_share_weights_but_not_streaming_state() -> None:
    provider = _provider()
    shared_weights = object()
    first_engine = _FakeEngine({1: _FrameResult(1, True, True, False, 1)})
    second_engine = _FakeEngine()
    first_engine.shared_weights = shared_weights
    second_engine.shared_weights = shared_weights
    first = FireRedVadSession(provider, first_engine)
    second = FireRedVadSession(provider, second_engine)

    first.process(np.ones(400, dtype=np.float32), 16_000)
    second.process(np.zeros(400, dtype=np.float32), 16_000)

    assert first_engine.shared_weights is second_engine.shared_weights
    assert first_engine.model_caches is not second_engine.model_caches
    assert first.snapshot() is not None
    assert second.snapshot() is None


def test_firered_load_failure_uses_pass_through_and_reports_error(monkeypatch) -> None:
    provider = _provider(max_utterance_ms=20)

    def _fail_load() -> None:
        provider._error = "download unavailable"
        raise RuntimeError(provider._error)

    monkeypatch.setattr(provider, "load", _fail_load)
    session = provider.create_session()

    segment = session.process(np.ones(320, dtype=np.float32), 16_000)

    assert segment is not None
    assert segment.duration_ms == 20
    assert session.pop_error() == "download unavailable"
    assert session.pop_error() is None


def test_firered_inference_failure_uses_pass_through_and_reports_error() -> None:
    session = FireRedVadSession(_provider(max_utterance_ms=25), _FailingEngine())

    segment = session.process(np.ones(400, dtype=np.float32), 16_000)

    assert segment is not None
    assert segment.duration_ms == 25
    assert "fake inference failure" in (session.pop_error() or "")


def test_vad_factory_keeps_silero_default_and_accepts_firered() -> None:
    assert create_vad_provider().model_id == "silero"
    assert create_vad_provider("firered-stream-vad").model_id == "firered-stream-vad"
