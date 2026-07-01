"""Pipeline coordinator tests for diarization-first multi-turn flushing."""
from __future__ import annotations

import asyncio
import threading

import numpy as np

from backend.config import PipelineConfig
from backend.models import RecordingSession, Utterance
from backend.pipeline.coordinator import PipelineCoordinator
from backend.providers.diarization import DiarizationSegment
from backend.providers.vad import SpeechSegment


class FakeASRProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str | None]] = []

    def transcribe(
        self,
        audio: np.ndarray,
        language_hint: str | None = None,
    ) -> Utterance:
        self.calls.append((len(audio), language_hint))
        return Utterance(
            transcript=f"samples:{len(audio)}",
            language=language_hint,
            confidence=1.0,
        )


class SequenceASRProvider:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[int] = []

    def transcribe(
        self,
        audio: np.ndarray,
        language_hint: str | None = None,
    ) -> Utterance:
        self.calls.append(int(len(audio)))
        transcript = self.outputs.pop(0) if self.outputs else f"samples:{len(audio)}"
        return Utterance(
            transcript=transcript,
            language=language_hint,
            confidence=1.0 if transcript else 0.0,
        )


class EmptyASRProvider:
    def transcribe(
        self,
        audio: np.ndarray,
        language_hint: str | None = None,
    ) -> Utterance:
        return Utterance(transcript="", language=language_hint, confidence=0.0)


class FakeDiarizationProvider:
    def __init__(self) -> None:
        self.calls = 0

    def segment(self, audio: np.ndarray) -> list[DiarizationSegment]:
        self.calls += 1
        return []


class FakeEmbeddingProvider:
    def embed(self, audio: np.ndarray) -> np.ndarray:
        return np.zeros(4, dtype=np.float32)


class RecordingEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def embed(self, audio: np.ndarray) -> np.ndarray:
        self.calls.append(int(len(audio)))
        return np.full(4, len(audio), dtype=np.float32)


class BrokenDiarizationProvider:
    def segment(self, audio: np.ndarray) -> list[DiarizationSegment]:
        raise RuntimeError("diarization unavailable")


class BrokenEmbeddingProvider:
    def embed(self, audio: np.ndarray) -> np.ndarray:
        raise RuntimeError("embedding unavailable")


class MultiSpeakerDiarizationProvider:
    def segment(self, audio: np.ndarray) -> list[DiarizationSegment]:
        return [
            DiarizationSegment(start=0.0, end=0.25, speaker="speaker_a"),
            DiarizationSegment(start=0.25, end=0.50, speaker="speaker_b"),
            DiarizationSegment(start=0.50, end=1.00, speaker="speaker_a"),
        ]


class OverlapDiarizationProvider:
    def segment(self, audio: np.ndarray) -> list[DiarizationSegment]:
        return [
            DiarizationSegment(start=0.0, end=0.75, speaker="speaker_a"),
            DiarizationSegment(start=0.25, end=0.50, speaker="speaker_b"),
        ]


class FakeVADProcessor:
    """Buffer-owning VAD: non-zero audio = speech (buffered), zero = flush."""

    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._started = 0
        self._ended = 0
        self._sr: int | None = None

    def reset(self) -> None:
        self._buffer = []
        self._started = 0
        self._ended = 0
        self._sr = None

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> SpeechSegment | None:
        dur = max(1, int(round((len(audio) / sample_rate) * 1000)))
        if self._buffer:
            self._ended += dur
        else:
            self._started = 0
            self._ended = dur

        if bool(np.any(audio)):
            self._buffer.append(audio.copy())
            if self._sr is None:
                self._sr = sample_rate
            return None

        if not self._buffer:
            return None

        concat = np.concatenate(self._buffer)
        duration = self._ended - self._started
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or sample_rate,
            started_ms=self._started,
            ended_ms=self._ended,
            duration_ms=duration,
        )
        self._buffer = []
        self._started = 0
        self._ended = 0
        return seg

    def finalize(self) -> SpeechSegment | None:
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        duration = self._ended - self._started
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or 16000,
            started_ms=self._started,
            ended_ms=self._ended,
            duration_ms=duration,
        )
        self._buffer = []
        self._started = 0
        self._ended = 0
        return seg

    def snapshot(self) -> SpeechSegment | None:
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        return SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or 16000,
            started_ms=self._started,
            ended_ms=self._ended,
            duration_ms=self._ended - self._started,
        )


class ScriptedVADProcessor:
    """VAD whose ``process`` returns a SpeechSegment on False entries."""

    def __init__(self, script: list[bool]) -> None:
        self._script = list(script)
        self._idx = 0
        self._buffer: list[np.ndarray] = []
        self._ended = 0
        self._sr: int | None = None

    def reset(self) -> None:
        self._idx = 0
        self._buffer = []
        self._ended = 0
        self._sr = None

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> SpeechSegment | None:
        dur = max(1, int(round((len(audio) / sample_rate) * 1000)))
        self._ended += dur
        is_speech = self._script[self._idx] if self._idx < len(self._script) else False
        self._idx += 1

        if is_speech:
            self._buffer.append(audio.copy())
            if self._sr is None:
                self._sr = sample_rate
            return None

        if not self._buffer:
            return None

        concat = np.concatenate(self._buffer)
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or sample_rate,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=self._ended,
        )
        self._buffer = []
        self._ended = 0
        return seg

    def finalize(self) -> SpeechSegment | None:
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or 16000,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=self._ended,
        )
        self._buffer = []
        self._ended = 0
        return seg

    def snapshot(self) -> SpeechSegment | None:
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        return SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or 16000,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=self._ended,
        )

    max_utterance_ms: int = 0


# Lower the min utterance floor so unit tests focus on the VAD/coordinator
# boundary, not the floor itself.
_TEST_PIPELINE_CFG = dict(vad_threshold=0.5, vad_min_utterance_ms=5)


def test_process_chunk_buffers_until_silence_boundary() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-1", language_hint="uk")
    coordinator.start_session(session)

    utterances: list[Utterance] = []
    segments: list = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)

    speech = np.ones(1600, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)

    asyncio.run(coordinator.process_chunk(speech, 16000))
    asyncio.run(coordinator.process_chunk(speech, 16000))

    assert utterances == []
    assert segments == []

    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert len(utterances) == 1
    assert len(segments) == 1
    assert utterances[0].session_id == session.id
    assert utterances[0].started_ms == 0
    assert utterances[0].ended_ms == 200
    assert utterances[0].speaker_segment_id == segments[0].id
    assert utterances[0].language == "uk"
    assert utterances[0].transcript == "samples:3200"


def test_process_chunk_emits_turn_rows_and_reuses_segment_for_same_speaker() -> None:
    asr = FakeASRProvider()
    embedding = RecordingEmbeddingProvider()
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        asr,
        MultiSpeakerDiarizationProvider(),
        embedding,
        vad_processor=FakeVADProcessor(),
        source="system",
    )
    session = RecordingSession(id="sess-speakers", language_hint="uk")
    coordinator.start_session(session)

    utterances: list[Utterance] = []
    segments: list = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)

    speech = np.ones(100, dtype=np.float32)
    silence = np.zeros(100, dtype=np.float32)

    asyncio.run(coordinator.process_chunk(speech, 100))
    asyncio.run(coordinator.process_chunk(silence, 100))

    assert len(segments) == 2
    assert embedding.calls == [75, 25]
    assert [call[0] for call in asr.calls] == [25, 25, 50]
    assert len(utterances) == 3
    assert [u.started_ms for u in utterances] == [0, 250, 500]
    assert [u.ended_ms for u in utterances] == [250, 500, 1000]
    assert utterances[0].speaker_segment_id == utterances[2].speaker_segment_id
    assert utterances[1].speaker_segment_id != utterances[0].speaker_segment_id
    assert utterances[0].session_id == session.id


def test_overlap_normalization_prefers_dominant_speaker_without_duplicates() -> None:
    asr = FakeASRProvider()
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        asr,
        OverlapDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
        source="system",
    )
    coordinator.start_session(RecordingSession(id="sess-overlap"))

    utterances: list[Utterance] = []
    segments: list = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)

    speech = np.ones(100, dtype=np.float32)
    silence = np.zeros(100, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 100))
    asyncio.run(coordinator.process_chunk(silence, 100))

    assert len(segments) == 1
    assert len(utterances) == 1
    assert asr.calls == [(75, None)]
    assert utterances[0].started_ms == 0
    assert utterances[0].ended_ms == 750


def test_fake_vad_detects_quiet_microphone_speech_in_pipeline_test() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-quiet")
    coordinator.start_session(session)

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    quiet_speech = np.full(1600, 0.03, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)

    asyncio.run(coordinator.process_chunk(quiet_speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert len(utterances) == 1
    assert utterances[0].session_id == session.id


def test_end_session_flushes_buffered_speech() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-2")
    coordinator.start_session(session)

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    speech = np.ones(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))

    assert utterances == []

    ended_session = coordinator.end_session()

    assert ended_session is not None
    assert ended_session.id == session.id
    assert len(utterances) == 1
    assert utterances[0].started_ms == 0
    assert utterances[0].ended_ms == 100


def test_end_session_drops_sub_min_buffered_speech() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(vad_threshold=0.5, vad_min_utterance_ms=300),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-sub-min-stop")
    coordinator.start_session(session)

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    speech = np.ones(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))

    ended_session = coordinator.end_session()

    assert ended_session is not None
    assert ended_session.id == session.id
    assert utterances == []


def test_empty_asr_result_does_not_emit_blank_utterance_or_unknown_segment() -> None:
    diarization = FakeDiarizationProvider()
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        EmptyASRProvider(),
        diarization,
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    coordinator.start_session(RecordingSession(id="sess-empty-asr"))

    utterances: list[Utterance] = []
    segments: list = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)

    speech = np.ones(1600, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert utterances == []
    assert segments == []
    assert diarization.calls == 1


def test_partial_empty_turn_only_drops_that_turn() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        SequenceASRProvider(["", "hello", "world"]),
        MultiSpeakerDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
        source="system",
    )
    coordinator.start_session(RecordingSession(id="sess-partial", language_hint="uk"))

    utterances: list[Utterance] = []
    segments: list = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)

    speech = np.ones(100, dtype=np.float32)
    silence = np.zeros(100, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 100))
    asyncio.run(coordinator.process_chunk(silence, 100))

    assert len(utterances) == 2
    assert [u.transcript for u in utterances] == ["hello", "world"]
    assert [u.started_ms for u in utterances] == [250, 500]
    assert len(segments) == 2
    assert utterances[0].speaker_segment_id != utterances[1].speaker_segment_id


def test_final_utterance_transcript_is_itn_normalized() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        SequenceASRProvider(["апі"]),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    coordinator.start_session(RecordingSession(id="sess-itn", language_hint="uk"))

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    speech = np.ones(1600, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert [u.transcript for u in utterances] == ["api"]


def test_final_utterance_transcript_skips_itn_when_disabled() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG, itn_enabled=False),
        SequenceASRProvider(["апі"]),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    coordinator.start_session(RecordingSession(id="sess-itn-off", language_hint="uk"))

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    speech = np.ones(1600, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert [u.transcript for u in utterances] == ["апі"]


def test_draft_utterance_transcript_is_itn_normalized() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(
            **_TEST_PIPELINE_CFG,
            draft_enabled=True,
            draft_interval_ms=1,
        ),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    coordinator._build_draft_provider = lambda: SequenceASRProvider(["апі"])  # type: ignore[method-assign]
    coordinator.start_session(RecordingSession(id="sess-draft-itn", language_hint="uk"))

    seen = threading.Event()
    drafts: list[dict] = []

    def on_draft(payload: dict) -> None:
        drafts.append(payload)
        seen.set()

    coordinator.on("draft_utterance", on_draft)

    speech = np.ones(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))

    assert seen.wait(timeout=2.0)
    assert drafts[0]["transcript"] == "api"


def test_draft_utterance_transcript_skips_itn_when_disabled() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(
            **_TEST_PIPELINE_CFG,
            draft_enabled=True,
            draft_interval_ms=1,
            itn_enabled=False,
        ),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    coordinator._build_draft_provider = lambda: SequenceASRProvider(["апі"])  # type: ignore[method-assign]
    coordinator.start_session(RecordingSession(id="sess-draft-itn-off", language_hint="uk"))

    seen = threading.Event()
    drafts: list[dict] = []

    def on_draft(payload: dict) -> None:
        drafts.append(payload)
        seen.set()

    coordinator.on("draft_utterance", on_draft)

    speech = np.ones(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))

    assert seen.wait(timeout=2.0)
    assert drafts[0]["transcript"] == "апі"


def test_pipeline_still_emits_utterance_when_diarization_fails() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        BrokenDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
        source="system",
    )
    coordinator.start_session(RecordingSession(id="sess-diarization-fallback"))

    utterances: list[Utterance] = []
    segments: list = []
    errors: list[dict] = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)
    coordinator.on("error", errors.append)

    speech = np.ones(1600, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert len(utterances) == 1
    assert len(segments) == 1
    assert utterances[0].speaker_segment_id == segments[0].id
    assert utterances[0].speaker_contact_id is None
    assert len(errors) == 1


def test_pipeline_still_emits_utterance_when_embedding_fails() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        BrokenEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    coordinator.start_session(RecordingSession(id="sess-no-embedding"))

    utterances: list[Utterance] = []
    segments: list = []
    errors: list[dict] = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)
    coordinator.on("error", errors.append)

    speech = np.ones(1600, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert len(utterances) == 1
    assert utterances[0].session_id == "sess-no-embedding"
    assert utterances[0].speaker_segment_id is None
    assert utterances[0].speaker_contact_id is None
    assert segments == []
    assert len(errors) == 1


def test_sub_min_utterance_speech_is_discarded() -> None:
    """A speech blip shorter than ``vad_min_utterance_ms`` must not emit ASR work."""
    asr = FakeASRProvider()
    diarization = FakeDiarizationProvider()
    coordinator = PipelineCoordinator(
        PipelineConfig(vad_threshold=0.5, vad_min_utterance_ms=300),
        asr,
        diarization,
        FakeEmbeddingProvider(),
        vad_processor=ScriptedVADProcessor([True, False]),
    )
    coordinator.start_session(RecordingSession(id="sess-blip"))

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    chunk = np.ones(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(chunk, 16000))
    asyncio.run(coordinator.process_chunk(chunk, 16000))

    assert utterances == []
    assert asr.calls == []
    assert diarization.calls == 0


def test_default_min_utterance_filter_discards_speech_below_100ms() -> None:
    asr = FakeASRProvider()
    diarization = FakeDiarizationProvider()
    coordinator = PipelineCoordinator(
        PipelineConfig(vad_threshold=0.5),
        asr,
        diarization,
        FakeEmbeddingProvider(),
        vad_processor=ScriptedVADProcessor([True, False]),
    )
    coordinator.start_session(RecordingSession(id="sess-default-filter-short"))

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    chunk_50ms = np.ones(800, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(chunk_50ms, 16000))
    asyncio.run(coordinator.process_chunk(np.zeros(1, dtype=np.float32), 16000))

    assert utterances == []
    assert asr.calls == []
    assert diarization.calls == 0


def test_default_min_utterance_filter_allows_100ms_speech() -> None:
    asr = FakeASRProvider()
    diarization = FakeDiarizationProvider()
    coordinator = PipelineCoordinator(
        PipelineConfig(vad_threshold=0.5),
        asr,
        diarization,
        FakeEmbeddingProvider(),
        vad_processor=ScriptedVADProcessor([True, False]),
    )
    coordinator.start_session(RecordingSession(id="sess-default-filter-boundary"))

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    chunk_100ms = np.ones(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(chunk_100ms, 16000))
    asyncio.run(coordinator.process_chunk(np.zeros(1, dtype=np.float32), 16000))

    assert len(utterances) == 1
    assert utterances[0].started_ms == 0
    assert utterances[0].ended_ms == 100
    assert asr.calls == [(1600, None)]
    assert diarization.calls == 1


def test_intra_utterance_silence_does_not_split_when_vad_stays_voiced() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(vad_threshold=0.5, vad_min_utterance_ms=5),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=ScriptedVADProcessor([True, True, True, True, False]),
    )
    coordinator.start_session(RecordingSession(id="sess-bridge"))

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    chunk = np.ones(1600, dtype=np.float32)
    for _ in range(4):
        asyncio.run(coordinator.process_chunk(chunk, 16000))
    asyncio.run(coordinator.process_chunk(np.zeros(1600, dtype=np.float32), 16000))

    assert len(utterances) == 1
    assert utterances[0].started_ms == 0
    assert utterances[0].ended_ms == 400


def test_max_utterance_force_flushes_long_monologue() -> None:
    coordinator = PipelineCoordinator(
        PipelineConfig(vad_threshold=0.5, vad_min_utterance_ms=5),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=ScriptedVADProcessor([True] * 6 + [False]),
    )
    coordinator.start_session(RecordingSession(id="sess-monologue"))

    utterances: list[Utterance] = []
    coordinator.on("utterance", utterances.append)

    chunk = np.ones(1600, dtype=np.float32)
    for _ in range(6):
        asyncio.run(coordinator.process_chunk(chunk, 16000))
    asyncio.run(coordinator.process_chunk(np.zeros(1600, dtype=np.float32), 16000))

    assert len(utterances) >= 1
    total = utterances[-1].ended_ms - utterances[0].started_ms
    assert total >= 600
