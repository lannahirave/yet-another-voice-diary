"""Tests for domain models."""
import numpy as np

from backend.models import Person, RecordingSession, SpeakerSegment, Utterance


def test_person_creation():
    """Test creating a person."""
    person = Person(name="Alice", notes="Test contact")
    assert person.name == "Alice"
    assert person.notes == "Test contact"
    assert person.id is not None


def test_session_creation():
    """Test creating a recording session."""
    session = RecordingSession(title="Meeting 1", language_hint="uk")
    assert session.title == "Meeting 1"
    assert session.language_hint == "uk"
    assert session.ended_at is None


def test_utterance_creation():
    """Test creating an utterance."""
    utterance = Utterance(
        transcript="Hello world",
        language="en",
        confidence=0.95,
    )
    assert utterance.transcript == "Hello world"
    assert utterance.language == "en"
    assert utterance.confidence == 0.95


def test_speaker_segment_creation():
    """Test creating a speaker segment."""
    embedding = np.random.randn(192).astype(np.float32)
    segment = SpeakerSegment(embedding=embedding, sim_score=0.85)
    assert segment.embedding.shape == (192,)
    assert segment.sim_score == 0.85
    assert segment.status == "unknown"
