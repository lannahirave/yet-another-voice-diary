"""Pipeline coordinator buffering tests."""
from __future__ import annotations

import asyncio

import numpy as np

from backend.config import PipelineConfig
from backend.models import RecordingSession, Utterance
from backend.pipeline.coordinator import PipelineCoordinator
from backend.pipeline.vad import VADSegment
from backend.providers.diarization import DiarizationSegment


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
    def segment(self, audio: np.ndarray) -> list[DiarizationSegment]:
        return [
            DiarizationSegment(start=0.0, end=0.25, speaker="speaker_a"),
            DiarizationSegment(start=0.25, end=0.50, speaker="speaker_b"),
            DiarizationSegment(start=0.50, end=1.00, speaker="speaker_a"),
        ]


class FakeVADProcessor:
    def reset(self) -> None:
        pass

    def process(self, audio: np.ndarray, sample_rate: int) -> VADSegment:
        return VADSegment(0, int(len(audio) / sample_rate * 1000), bool(np.any(audio)))


# Production defaults require ≥300 ms of speech before an utterance is emitted.
# These coordinator tests drive the FakeVADProcessor with 100 ms blips; lower the
# floor so the unit tests focus on the buffering/edge logic, not the floor itself.
_TEST_PIPELINE_CFG = dict(vad_threshold=0.5, vad_min_utterance_ms=50)


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
    # Endpoint includes the falling-edge silence chunk so Silero's trailing
    # speech-pad is preserved for the ASR slice (2 × 100 ms speech + 100 ms tail).
    assert utterances[0].ended_ms == 300
    assert utterances[0].speaker_segment_id == segments[0].id
    assert utterances[0].language == "uk"
    assert utterances[0].transcript == "samples:4800"


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
    """VAD whose ``is_speech`` is driven by an explicit script of booleans.

    Decouples coordinator endpointing tests from any real VAD state machine —
    the test specifies, chunk by chunk, whether the VAD currently classifies
    the audio as speech or silence.
    """

    def __init__(self, script: list[bool]) -> None:
        self._script = list(script)
        self._idx = 0

    def reset(self) -> None:
        self._idx = 0

    def process(self, audio: np.ndarray, sample_rate: int) -> VADSegment:
        is_speech = self._script[self._idx] if self._idx < len(self._script) else False
        self._idx += 1
        return VADSegment(0, int(len(audio) / sample_rate * 1000), is_speech)


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
    """While VAD reports continuous speech, brief intra-utterance lulls don't flush."""
    coordinator = PipelineCoordinator(
        PipelineConfig(vad_threshold=0.5, vad_min_utterance_ms=50),
        FakeASRProvider(),
        FakeDiarizationProvider(),
        FakeEmbeddingProvider(),
        # VAD stays voiced across an internal lull (Silero's own debounce);
        # the coordinator must not break the utterance on those chunks.
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
    """A continuous voiced span beyond ``vad_max_utterance_ms`` is split deterministically."""
    coordinator = PipelineCoordinator(
        # 250 ms cap → 100 ms chunks force-flush after the third voiced chunk.
        PipelineConfig(
            vad_threshold=0.5,
            vad_min_utterance_ms=50,
            vad_max_utterance_ms=250,
        ),
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

    # Two force-flushes at 300 ms each (3 voiced chunks crossed the 250 ms cap),
    # plus a final flush on the falling edge for the last 0–2 chunks.
    assert len(utterances) >= 2
    total = utterances[-1].ended_ms - utterances[0].started_ms
    assert total >= 600  # all 6 voiced chunks plus trailing chunk are accounted for


def test_accelerator_snapshot_reports_cuda_and_mps_sections():
    snapshot = PipelineCoordinator._accelerator_snapshot()

    assert set(snapshot) == {"cuda", "mps"}
    assert isinstance(snapshot["cuda"]["available"], bool)
    assert isinstance(snapshot["mps"]["built"], bool)
    assert isinstance(snapshot["mps"]["available"], bool)
