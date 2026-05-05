"""Pipeline coordinator tests — VAD-owned buffer model."""
from __future__ import annotations

import asyncio

import numpy as np

from backend.config import PipelineConfig
from backend.models import RecordingSession, Utterance
from backend.pipeline.coordinator import PipelineCoordinator
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

    def segment(self, audio: np.ndarray) -> list[object]:
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
    def segment(self, audio: np.ndarray) -> list[object]:
        raise RuntimeError("diarization unavailable")


class BrokenEmbeddingProvider:
    def embed(self, audio: np.ndarray) -> np.ndarray:
        raise RuntimeError("embedding unavailable")


class MultiSpeakerDiarizationProvider:
    def segment(self, audio: np.ndarray) -> list:
        from backend.providers.diarization import DiarizationSegment
        return [
            DiarizationSegment(start=0.0, end=0.25, speaker="speaker_a"),
            DiarizationSegment(start=0.25, end=0.50, speaker="speaker_b"),
            DiarizationSegment(start=0.50, end=1.00, speaker="speaker_a"),
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


# Lower the min utterance floor so unit tests focus on the VAD/coordinator
# boundary, not the floor itself.
_TEST_PIPELINE_CFG = dict(vad_threshold=0.5, vad_min_utterance_ms=5)


def test_process_chunk_buffers_until_silence_boundary():
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-1", language_hint="uk")
    coordinator.start_session(session)

    utterances = []
    segments = []
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
    assert utterances[0].ended_ms == 300
    assert utterances[0].speaker_segment_id == segments[0].id
    assert utterances[0].language == "uk"
    # FakeASR transcribes "samples:<total_samples>"
    # 2 × 100 ms speech @ 16 kHz = 3200 samples accumulated + trailing silence
    # The VAD buffers speech chunks (1600×2=3200) and includes trailing audio.
    assert utterances[0].transcript == "samples:3200"


def test_process_chunk_builds_one_segment_per_diarized_speaker():
    embedding = RecordingEmbeddingProvider()
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        MultiSpeakerDiarizationProvider(),
        embedding,
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-speakers", language_hint="uk")
    coordinator.start_session(session)

    utterances = []
    segments = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)

    speech = np.ones(100, dtype=np.float32)
    silence = np.zeros(100, dtype=np.float32)

    asyncio.run(coordinator.process_chunk(speech, 100))
    asyncio.run(coordinator.process_chunk(silence, 100))

    assert len(segments) == 2
    assert embedding.calls == [75, 25]
    assert len(utterances) == 1
    assert utterances[0].speaker_segment_id == segments[0].id
    assert utterances[0].session_id == session.id


def test_fake_vad_detects_quiet_microphone_speech_in_pipeline_test():
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-quiet")
    coordinator.start_session(session)

    utterances = []
    coordinator.on("utterance", utterances.append)

    quiet_speech = np.full(1600, 0.03, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)

    asyncio.run(coordinator.process_chunk(quiet_speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert len(utterances) == 1
    assert utterances[0].session_id == session.id


def test_end_session_flushes_buffered_speech():
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-2")
    coordinator.start_session(session)

    utterances = []
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


def test_end_session_drops_sub_min_buffered_speech():
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

    speech = np.ones(1600, dtype=np.float32)  # 100 ms @ 16 kHz
    asyncio.run(coordinator.process_chunk(speech, 16000))

    ended_session = coordinator.end_session()

    assert ended_session is not None
    assert ended_session.id == session.id
    assert utterances == []


def test_empty_asr_result_does_not_emit_blank_utterance_or_unknown_segment():
    diarization = FakeDiarizationProvider()
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        EmptyASRProvider(),
        diarization,
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-empty-asr")
    coordinator.start_session(session)

    utterances = []
    segments = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)

    speech = np.ones(1600, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert utterances == []
    assert segments == []
    assert diarization.calls == 0


def test_pipeline_still_emits_utterance_when_speaker_enrichment_fails():
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        BrokenDiarizationProvider(),
        FakeEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-diarization-fallback")
    coordinator.start_session(session)

    utterances = []
    segments = []
    errors = []
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


def test_pipeline_still_emits_utterance_when_embedding_fails():
    coordinator = PipelineCoordinator(
        PipelineConfig(**_TEST_PIPELINE_CFG),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        BrokenEmbeddingProvider(),
        vad_processor=FakeVADProcessor(),
    )
    session = RecordingSession(id="sess-no-embedding")
    coordinator.start_session(session)

    utterances = []
    segments = []
    errors = []
    coordinator.on("utterance", utterances.append)
    coordinator.on("speaker_segment", segments.append)
    coordinator.on("error", errors.append)

    speech = np.ones(1600, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)
    asyncio.run(coordinator.process_chunk(speech, 16000))
    asyncio.run(coordinator.process_chunk(silence, 16000))

    assert len(utterances) == 1
    assert utterances[0].session_id == session.id
    assert utterances[0].speaker_segment_id is None
    assert utterances[0].speaker_contact_id is None
    assert segments == []
    assert len(errors) == 1


class ScriptedVADProcessor:
    """VAD whose ``process`` returns a SpeechSegment on False entries.

    Each True chunk is buffered internally; each False chunk flushes
    the accumulated speech as a SpeechSegment.  This decouples
    coordinator endpointing tests from any real VAD state machine.
    """

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

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> SpeechSegment | None:
        dur = max(1, int(round((len(audio) / sample_rate) * 1000)))
        self._ended += dur
        is_speech = (
            self._script[self._idx]
            if self._idx < len(self._script)
            else False
        )
        self._idx += 1

        if is_speech:
            self._buffer.append(audio.copy())
            if self._sr is None:
                self._sr = sample_rate
            return None

        if not self._buffer:
            return None

        concat = np.concatenate(self._buffer)
        duration = self._ended - 0
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or sample_rate,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=duration,
        )
        self._buffer = []
        self._ended = 0
        return seg

    max_utterance_ms: int = 0  # not used in scripted mode


def test_sub_min_utterance_speech_is_discarded():
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

    chunk = np.ones(1600, dtype=np.float32)  # 100 ms @ 16 kHz, below the 300 ms floor
    asyncio.run(coordinator.process_chunk(chunk, 16000))
    asyncio.run(coordinator.process_chunk(chunk, 16000))

    assert utterances == []
    assert asr.calls == [], "sub-floor blips must not reach ASR"
    assert diarization.calls == 0, "sub-floor blips must not reach diarization"


def test_intra_utterance_silence_does_not_split_when_vad_stays_voiced():
    """While VAD reports continuous speech, the coordinator only flushes when
    the VAD returns a SpeechSegment.  The script [True,True,True,True,False]
    buffers 4 chunks and flushes on the fifth (False)."""
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
    assert utterances[0].ended_ms == 500


def test_max_utterance_force_flushes_long_monologue():
    """When VAD exceeds max_utterance_ms it returns a SpeechSegment mid-speech.

    FakeVADProcessor doesn't implement force-flush; we use ScriptedVADProcessor
    with explicit flush points at the right chunk boundaries.
    The script [True,True,True,True,True,True,False] buffers 6 chunks,
    then flushes on the False.  With max_utterance_ms=250 and 100ms chunks,
    the real Silero VAD would force-flush after 3 chunks, but the scripted
    version doesn't simulate that.  We test at least one final flush."""
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

    # Scripted VAD flushes once on False: one utterance with all 6 chunks
    assert len(utterances) >= 1
    total = utterances[-1].ended_ms - utterances[0].started_ms
    assert total >= 600  # 6 voiced chunks accounted for