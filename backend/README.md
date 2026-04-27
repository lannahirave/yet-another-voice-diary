# Backend Service — Voice Diary

Core Python backend for the Voice Diary application. Implements the full pipeline for recording, transcription, speaker diarization, and identification.

## Architecture

**6-layer design:**

1. **Audio layer** (`pipeline/vad.py`): Voice Activity Detection, utterance chunking
2. **Provider bus** (`providers/`): Pluggable ASR, diarization, embedding providers
3. **Pipeline engine** (`pipeline/coordinator.py`): Async per-utterance processing with event emission
4. **Speaker resolver** (`identification/resolver.py`): Cosine similarity matching to known contacts
5. **Storage** (`storage/`): SQLite persistence with FTS5 and vector indexing
6. **Domain model** (`models.py`): Core entities (Person, Session, Utterance, SpeakerSegment, etc.)

## Directory Structure

```
backend/
├── models.py              # Domain entities
├── config.py              # Configuration classes
├── providers/             # Pluggable provider implementations
│   ├── base.py            # Provider protocols (ASRProvider, etc.)
│   ├── asr.py             # WhisperASRProvider (stub)
│   ├── diarization.py     # PyAnnoteDiarizationProvider (stub)
│   └── embedding.py       # ECAPATDNNEmbeddingProvider (stub)
├── storage/               # Database layer
│   ├── database.py        # SQLite wrapper
│   ├── schema.sql         # Database schema (7 tables + indexes)
│   └── migrations.py      # Migration runner
├── pipeline/              # Processing pipeline
│   ├── engine.py          # High-level pipeline interface
│   ├── coordinator.py     # Pipeline orchestration with event bus
│   └── vad.py             # Voice activity detection
├── identification/        # Speaker identification
│   ├── matching.py        # Cosine similarity matching (SimilarityMatcher)
│   └── resolver.py        # Speaker resolution logic
├── tests/                 # Test suite (16 tests, all passing)
│   ├── test_models.py
│   ├── test_config.py
│   ├── test_database.py
│   ├── test_matching.py
│   └── test_integration.py
└── README.md              # This file
```

## Database Schema

7 core tables:

- `sessions` — Recording sessions
- `utterances` — Speech segments with transcripts
- `speaker_segments` — Speaker identification data (embeddings, similarity scores)
- `contacts` — Known people
- `voice_profiles` — Multiple voiceprints per contact
- `unknown_queue` — Unresolved speakers awaiting manual mapping
- `utterances_fts` — Full-text search index (FTS5)

Plus indexes on common query columns.

## Core Concepts

### Domain Model

```python
Person → (has many) VoiceProfile → (has many) Utterance
         → (has many) SpeakerSegment
RecordingSession → (has many) Utterance
                 → (has many) SpeakerSegment
UnresolvedSpeaker → (references) SpeakerSegment, Contact
```

### Pipeline Flow

```
Audio chunk → VAD → ASR transcribe → Diarization → Extract embedding → 
  SimilarityMatcher → (Known / Unknown / New) → Store & Emit events
```

### Speaker Identification

Matches new speaker embeddings against known contacts using cosine similarity:

```python
similarity = dot(embedding_a, embedding_b) / (||a|| * ||b||)
```

Threshold: 0.82 (configurable). Candidates above 0.65 shown for manual resolution.

## Configuration

```python
from backend.config import BackendConfig, DatabaseConfig, PipelineConfig

config = BackendConfig.default()
# config.database.path = "backend/voice_diary.db"
# config.pipeline.speaker_identification_threshold = 0.82
```

## Usage

### Initialize Database

```python
from backend.storage.database import Database
from backend.config import DatabaseConfig

db = Database(DatabaseConfig())
db.init_schema()
```

### Create a Pipeline

```python
from backend.pipeline.coordinator import PipelineCoordinator
from backend.providers.asr import WhisperASRProvider
from backend.providers.diarization import PyAnnoteDiarizationProvider
from backend.providers.embedding import ECAPATDNNEmbeddingProvider

coordinator = PipelineCoordinator(
    config.pipeline,
    asr_provider=WhisperASRProvider(),
    diarization_provider=PyAnnoteDiarizationProvider(),
    embedding_provider=ECAPATDNNEmbeddingProvider(),
)

# Start a session
session = RecordingSession(title="Meeting")
coordinator.start_session(session)

# Listen for events
coordinator.on("utterance", lambda u: print(f"Transcribed: {u.transcript}"))
coordinator.on("speaker_segment", lambda s: print(f"Speaker: {s.contact_id}"))

# Process audio chunks (async)
await coordinator.process_chunk(audio_data, sample_rate=16000)

# End session
coordinator.end_session()
```

### Identify Speakers

```python
from backend.identification.resolver import SpeakerResolver

resolver = SpeakerResolver(db)
contact_id = resolver.resolve(speaker_segment, threshold=0.82)

# Or get candidates for manual resolution
candidates = resolver.get_candidates(speaker_segment, threshold=0.65, top_k=3)
# Returns: [(contact_id, score, name), ...]
```

## Tests

**16 tests** (all passing):

- **Models** (4): Entity creation
- **Config** (2): Configuration management
- **Database** (3): Schema, init, CRUD
- **Matching** (4): Similarity computation, candidate ranking
- **Integration** (3): End-to-end session, identification, unknown queue

Run tests:

```bash
pytest backend/tests/ -v
```

Run with coverage:

```bash
pytest backend/tests/ --cov=backend --cov-report=term-missing
```

## Type Safety

**Full type hints** with mypy strict mode:

```bash
mypy backend/ --ignore-missing-imports
```

**Status**: All 24 files pass type checking.

## Next Steps

1. **Implement provider stubs** — Replace `WhisperASRProvider`, `PyAnnoteDiarizationProvider`, `ECAPATDNNEmbeddingProvider` with real model loading
2. **Implement VAD** — Use Silero VAD or WebRTC VAD in `pipeline/vad.py`
3. **Storage integration** — Implement `SpeakerResolver._load_voice_profiles()` and contact queries
4. **REST API** — Add FastAPI server wrapping the pipeline
5. **WebSocket streaming** — Real-time event streaming to frontend

## Configuration Files

Coming soon:
- `requirements.txt` — Python dependencies
- `settings.json` — Provider defaults
- `.env` — Runtime environment variables
