"""Integration tests for the full pipeline."""
import tempfile
from pathlib import Path

import numpy as np

from backend.config import BackendConfig, DatabaseConfig
from backend.identification.matching import SimilarityMatcher
from backend.models import RecordingSession, Utterance
from backend.pipeline.coordinator import PipelineCoordinator
from backend.providers.vad import SpeechSegment
from backend.storage.database import Database


class FakeASRProvider:
    def transcribe(
        self,
        audio: np.ndarray,
        language_hint: str | None = None,
    ) -> Utterance:
        return Utterance(
            transcript=f"samples:{len(audio)}",
            language=language_hint,
            confidence=1.0,
        )


class FakeDiarizationProvider:
    def segment(self, audio: np.ndarray) -> list[object]:
        return []


class FakeEmbeddingProvider:
    def embed(self, audio: np.ndarray) -> np.ndarray:
        return np.zeros(192, dtype=np.float32)


class FakeVADProcessor:
    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._ended = 0
        self._sr: int | None = None

    def reset(self) -> None:
        self._buffer = []
        self._ended = 0

    def process(
        self, audio: np.ndarray, sample_rate: int
    ) -> SpeechSegment | None:
        dur = max(1, int(round((len(audio) / sample_rate) * 1000)))
        self._ended += dur
        if bool(np.any(audio)):
            self._buffer.append(audio.copy())
            if self._sr is None:
                self._sr = sample_rate
            return None
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        duration = self._ended
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

    def finalize(self) -> SpeechSegment | None:
        if not self._buffer:
            return None
        concat = np.concatenate(self._buffer)
        duration = self._ended
        seg = SpeechSegment(
            audio=np.ascontiguousarray(concat, dtype=np.float32),
            sample_rate=self._sr or 16000,
            started_ms=0,
            ended_ms=self._ended,
            duration_ms=duration,
        )
        self._buffer = []
        self._ended = 0
        return seg


def test_end_to_end_session():
    """Test creating a session, processing audio, and resolving speakers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialize database
        db_config = DatabaseConfig(path=Path(tmpdir) / "test.db")
        db = Database(db_config)
        db.init_schema()

        # Initialize pipeline
        config = BackendConfig.default()
        coordinator = PipelineCoordinator(
            config.pipeline,
            FakeASRProvider(),
            FakeDiarizationProvider(),
            FakeEmbeddingProvider(),
            vad_processor=FakeVADProcessor(),
        )

        # Create a session
        session = RecordingSession(title="Test Session", language_hint="uk")
        coordinator.start_session(session)
        assert coordinator._current_session is not None

        # Mock audio: speech followed by silence so the buffered utterance closes.
        speech = np.ones(16000, dtype=np.float32)
        silence = np.zeros(16000, dtype=np.float32)

        # Track events
        utterances_received = []
        segments_received = []

        coordinator.on("utterance", lambda u: utterances_received.append(u))
        coordinator.on("speaker_segment", lambda s: segments_received.append(s))

        # Process chunk (would be async in real app)
        import asyncio
        asyncio.run(coordinator.process_chunk(speech))
        assert utterances_received == []

        asyncio.run(coordinator.process_chunk(silence))

        # Boundary processing should emit one buffered utterance.
        assert len(utterances_received) > 0
        utterance = utterances_received[0]
        assert utterance.session_id == session.id

        # End session
        ended_session = coordinator.end_session()
        assert ended_session is not None
        assert coordinator._current_session is None

        db.close()

def test_speaker_identification():
    """Test speaker identification with mock embeddings."""
    matcher = SimilarityMatcher()

    # Create a known contact with a voiceprint
    contact_id = "contact_1"
    known_embedding = np.array([1, 0, 0], dtype=np.float32)

    # Test case 1: High similarity match
    test_embedding = np.array([0.95, 0.05, 0], dtype=np.float32)
    match = matcher.find_best_match(
        test_embedding,
        [(contact_id, known_embedding)],
        threshold=0.8
    )
    assert match is not None
    assert match[0] == contact_id
    assert match[1] > 0.9

    # Test case 2: Low similarity - should not match
    test_embedding = np.array([0, 1, 0], dtype=np.float32)
    match = matcher.find_best_match(
        test_embedding,
        [(contact_id, known_embedding)],
        threshold=0.8
    )
    assert match is None


def test_unknown_speaker_queue():
    """Test handling unknown speakers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_config = DatabaseConfig(path=Path(tmpdir) / "test.db")
        db = Database(db_config)
        db.init_schema()

        # Create a person
        person_id = "person_1"
        db.execute(
            "INSERT INTO contacts (id, name, created_at) VALUES (?, ?, ?)",
            (person_id, "Alice", 1234567890)
        )

        # Create an unknown speaker segment
        segment_id = "segment_1"
        unknown_embedding = np.random.randn(192).astype(np.float32)
        db.execute(
            "INSERT INTO speaker_segments (id, session_id, status, embedding) VALUES (?, ?, ?, ?)",
            (segment_id, "session_1", "unknown", unknown_embedding.tobytes())
        )

        # Add to unknown queue
        db.execute(
            "INSERT INTO unknown_queue (id, speaker_segment_id, created_at) VALUES (?, ?, ?)",
            ("queue_1", segment_id, 1234567890)
        )

        # Resolve the unknown speaker
        db.execute(
            """UPDATE unknown_queue
               SET resolved_contact_id = ?, resolved_at = ?
               WHERE id = ?""",
            (person_id, 1234567890, "queue_1")
        )

        # Verify it's resolved
        result = db.fetch_one(
            "SELECT resolved_contact_id FROM unknown_queue WHERE id = ?",
            ("queue_1",)
        )
        assert result is not None
        assert result[0] == person_id

        db.close()
