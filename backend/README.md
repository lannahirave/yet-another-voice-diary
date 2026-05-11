# Backend — Voice Diary API

FastAPI service for the Voice Diary desktop meeting recorder. Provides REST and WebSocket endpoints for audio streaming, automatic speech recognition (ASR), speaker diarization, voice embedding, and speaker identification.

## Architecture

```
WebSocket → VAD (Silero) → ASR (faster-whisper) → Diarization (PyAnnote/Sortformer)
         → Embedding (ECAPA-TDNN) → Cosine Matching → Speaker Resolution
         → SQLite Persistence (FTS5 + BLOB embeddings)
```

## Directory Structure

```
backend/
  api/              FastAPI application, deps, schemas, routers (7 modules)
  providers/        ML model wrappers (ASR, diarization, embedding)
  pipeline/         Real-time audio coordinator, VAD, endpointing
  identification/   Cosine matching, resolver, embedding clustering
  storage/          SQLite schema, repositories, migrations
  tests/            Unit tests (84 tests, ~20 MB .venv)
  e2e-tests/        E2E tests with real ML models (8 test files, needs .venv-ml)
  scripts/          Dev DB seeder, score histogram, DB wiper
  config.py         Dataclass config + JSON persistence
  models.py         Domain model dataclasses
  run.py            Uvicorn entry point (127.0.0.1:8765)
  pyproject.toml    Build system + dependency groups
```

## Quick Start

```bash
# Dev environment (no ML models, ~20 MB)
pip install -e "./backend[dev]"
python -m backend.run

# ML environment (includes torch, faster-whisper, ~3 GB)
cd web_app/backend
pip install -e ".[ml]"
cd ..
python -m backend.run
```

## API Overview

### Sessions (`/sessions`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/sessions` | List all sessions |
| POST | `/sessions` | Create session |
| GET | `/sessions/{id}` | Get session detail |
| PATCH | `/sessions/{id}` | Update title, ended_at, notes |
| DELETE | `/sessions/{id}` | Delete (cascade utterances + segments) |
| GET | `/sessions/{id}/utterances` | Utterances for session |
| POST | `/sessions/{id}/utterances` | Create utterance |
| GET | `/sessions/utterances/{id}/candidates` | Candidate contacts for one utterance's voiceprint |
| POST | `/sessions/utterances/{id}/identify` | Assign speaker + session-scoped cascade |

### Contacts (`/contacts`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/contacts` | List with profile_count, session_count, confidence |
| POST | `/contacts` | Create contact |
| GET | `/contacts/{id}` | Single contact |
| PATCH | `/contacts/{id}` | Update name/notes |
| DELETE | `/contacts/{id}` | Delete (cascade voice_profiles, nullify segments) |
| GET | `/contacts/{id}/utterances` | Utterances attributed to contact |
| POST | `/contacts/{id}/merge` | Merge source into target |

### Unknown Queue (`/unknown-queue`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/unknown-queue` | Clustered unresolved items; `?q=` search, `?session_id=` filter, `?limit=&offset=` pagination |
| GET | `/unknown-queue/count` | Lightweight `SELECT COUNT(*)` for badge |
| POST | `/unknown-queue/resolve` | Batch resolve with cascade auto-identification (batched 100 at a time) |
| POST | `/unknown-queue/skip` | Batch skip (re-queue by bumping timestamp) |
| POST | `/unknown-queue/{id}/resolve` | Legacy single-item resolve |
| POST | `/unknown-queue/{id}/skip` | Legacy single-item skip |

### Search (`/search`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/search?q=...&language=...&limit=50` | FTS5 full-text search with snippet highlighting |

### Config (`/config`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/config` | Full runtime config (VAD, threshold, providers status) |
| POST | `/config/threshold` | Set speaker identification threshold (0.0–1.0) |
| POST | `/config/unload-after-stop` | Toggle per-session model unloading |
| POST | `/config/preload-on-start` | Toggle preload models on app startup |
| GET | `/config/storage` | DB path, size, existence |
| POST | `/config/provider/{kind}` | Switch provider model (auto-unloads old) |

### Models (`/models`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/models/status` | Provider states (UNLOADED/LOADING/LOADED/ERROR) |
| POST | `/models/{kind}/load` | Start background load (daemon thread, non-blocking) |
| POST | `/models/{kind}/unload` | Unload model (409 if LOADING) |
| GET | `/models/{kind}/download-progress` | SSE stream of load progress |

### Audio WebSocket (`/ws/audio`)
```
Client: binary float32 PCM 16kHz chunks
Server: JSON events — utterance, speaker_segment, error

Query params:
  ?track=mic      (default) microphone audio
  ?track=system   system audio loopback
```

## Core Pipeline (`pipeline/coordinator.py`)

The real-time audio processing flows through a state machine in `PipelineCoordinator.process_chunk()`:

```
Audio Chunk (~100ms, float32, mono 16kHz)
  │
  ▼
VAD (Silero) — sustained is_speech boolean per chunk
  │
  ▼
Endpointing State Machine:
  ├─ Rising edge → start buffering
  ├─ Speech → continue buffering
  ├─ Falling edge → flush if speech ≥ 300ms, discard otherwise
  └─ Force flush at 30s monologue cap
  │
  ▼
Per-Utterance Flush:
  ├─ ASR: faster-whisper large-v3-turbo (int8 CPU / fp16 CUDA)
  ├─ Diarization: PyAnnote 3.1 (with Windows/SpeechBrain compatibility patches)
  ├─ Speaker grouping: slice audio by diarized time ranges
  ├─ Embedding: ECAPA-TDNN 192-dim per speaker group
  └─ Emit: "utterance" + "speaker_segment" events
```

### Graceful Degradation
- VAD fails → chunk skipped, no error propagated
- Diarization fails → full-utterance embedding (ungrouped), error event emitted
- Embedding fails → segment skipped, error event emitted
- ASR empty → utterance silently dropped
- Session-end sub-300ms tail → discarded (prevents junk embeddings)

## Provider Architecture

All providers follow the same pattern:
```
__init__(model_id) → _load_model() → load() → unload()
```

### ASR (`providers/asr.py`)
- **Backend:** faster-whisper (primary) with HuggingFace Transformers fallback
- **Model:** `large-v3-turbo` (809M params, 8x decode speedup)
- **Device:** CUDA auto-detect → fp16; CPU → int8
- **Fallback:** If faster-whisper not installed, falls back to Transformers pipeline

### Diarization (`providers/diarization.py`)
- **Primary:** PyAnnote `pyannote/speaker-diarization-3.1`
- **Alternative:** NeMo Sortformer v2.1 (`nvidia/diar_streaming_sortformer_4spk-v2.1`)
- **Compatibility patches:** Windows SpeechBrain inspect workaround, torch>=2.6 checkpoint fix, huggingface_hub auth token compatibility, torchcodec warning suppression

### Embedding (`providers/embedding.py`)
- **Model:** SpeechBrain ECAPA-TDNN (`speechbrain/spkrec-ecapa-voxceleb`)
- **Output:** 192-dim float32, L2-normalized
- **Compatibility:** huggingface_hub `use_auth_token` removal patch, `RemoteEntryNotFoundError` → `HTTPError` conversion

### VAD (`pipeline/vad.py`)
- **Model:** Silero VAD via `silero_vad.VADIterator`
- **Mode:** Stateful LSTM streaming — maintains temporal context across calls
- **Frame sizes:** 512 samples @ 16kHz, 256 @ 8kHz

## Identification Layer (`identification/`)

### Matching (`matching.py`)
- `SimilarityMatcher.cosine_similarity(a, b)` — L2-normalized dot product with zero-guards
- `find_best_match(query, candidates, threshold=0.82)` — linear scan, returns best above threshold
- `find_candidates(query, candidates, threshold=0.65, top_k=3)` — sorted top-k by score

### Resolver (`resolver.py`)
- Source-scoped identity: mic-track segments only match mic-enrolled profiles (migration `003_audio_source`)
- Embedding-space metadata: filters by `model_id` + `embedding_dim` (migration `004`)
- `resolve()` — strict (exact source + model_id + dim match)
- `get_candidates()` — includes cross-model fallback for UI suggestions, deduplicates by contact

### Clustering (`clustering.py`)
- Greedy single-pass centroid clustering for unknown-queue grouping
- Order-dependent but acceptable for small queue sizes
- Cascade-re-identification after every resolve keeps clusters current

## Storage Layer (`storage/`)

### Schema (7 tables + 1 virtual)
| Table | Purpose |
|-------|---------|
| `sessions` | Recording sessions |
| `utterances` | Speech segments with transcripts |
| `speaker_segments` | Per-speaker diarization segments with embedding blobs |
| `contacts` | Known people |
| `voice_profiles` | Multiple voiceprints per contact |
| `unknown_queue` | Unresolved speaker segments |
| `utterances_fts` | FTS5 full-text search (content-synced to utterances) |
| `schema_migrations` | Migration tracking |

### Migrations (5 total, all idempotent)
| ID | What it adds |
|----|-------------|
| 001 (schema.sql) | All tables + FTS5 + indexes |
| 002 (fts_migration.py) | AFTER INSERT/UPDATE/DELETE triggers for FTS5 sync |
| 003 (source_migration.py) | `source` column on 4 tables + indexes |
| 004 (voice_profile_metadata_migration.py) | `model_id` + `embedding_dim` on voice_profiles + backfill |
| 005 (speaker_segment_diarization_model_migration.py) | `diarization_model_id` on speaker_segments + backfill |

All column-adding migrations check `PRAGMA table_info` before `ALTER TABLE ADD COLUMN`.

### Repositories
All accept raw `sqlite3.Connection` (not `Database` wrapper).
- `SessionRepo` — session CRUD + utterance/segment creation
- `ContactRepo` — contact CRUD + merge + voice-profile confidence (mean pairwise cosine)
- `QueueRepo` — enqueue, resolve (with optional voice-profile creation), skip
- `SearchRepo` — FTS5 query sanitization + snippet highlighting

## Configuration (`config.py`)

Three dataclasses persisted to `~/.voice-diary/config.json`:
- `DatabaseConfig` — SQLite path
- `PipelineConfig` — VAD thresholds, speaker identification threshold, chunk duration, unload-on-stop
- `ProviderConfig` — model IDs + preload-on-start toggle

`BackendConfig` is the composition root. `save()` / `load()` use JSON. On load, invalid diarization model IDs are auto-corrected and the config is re-saved.

## Tests

### Unit Tests (`tests/`) — 84 tests, 17 files
- API tests: sessions, contacts, search, WS audio, models lifecycle
- Provider tests: ASR aliases, diarization backends, VAD
- Pipeline tests: buffering, endpointing, graceful degradation, multi-speaker
- Resolver tests: source scoping, model_id/dim filtering, cross-model fallback, dedup
- Repo tests: confidence computation, embedding-space isolation
- Config tests: save/load roundtrip, normalization

### E2E Tests (`e2e-tests/`) — 8 test files
- Requires `.venv-ml` with `[ml]` extras + `HF_TOKEN`
- Model lifecycle: load/inference/unload/reload for all 3 models
- Pipeline: full WS stream with real audio → transcript verification
- Dual-track: mic + system source separation
- Config: threshold persistence, provider switching, user-home leak regression test

```bash
# Unit tests (fast, no ML deps)
python -m pytest backend/tests/ -v

# E2E tests (requires .venv-ml)
python -m pytest backend/e2e-tests/ -v
```

## Scripts

| Script | Purpose |
|--------|---------|
| `score_histogram.py` | Cosine-similarity distribution analysis (SAME vs DIFF, threshold suggestion) |
| `clear_db.py` | Wipe all user data, preserve schema, VACUUM (with safety prompt) |

## Dependencies

**Core:** `numpy`, `fastapi`, `uvicorn`, `pydantic`, `websockets`
**Dev:** `pytest`, `pytest-cov`, `pytest-asyncio`, `httpx`, `mypy`
**ML (optional):** `faster-whisper`, `torch==2.8.0`, `torchaudio==2.8.0`, `speechbrain`, `silero-vad`, `pyannote.audio==4.0.3`, `transformers>=4.40`
**ML-NeMo (optional):** `nemo_toolkit[asr]`

## Recent Additions

### Inline utterance identification
- `GET /sessions/utterances/{id}/candidates` — returns top 3 contacts from stored embedding (no ML loading)
- `POST /sessions/utterances/{id}/identify` — assigns contact to speaker_segment, creates voice_profile, session-scoped cascade
- Concurrency protection: idempotent on same contact, 409 on different contact

### Queue pagination, search, count
- `GET /unknown-queue?limit=20&offset=0` — paginated clusters
- `GET /unknown-queue?q=...&session_id=...` — server-side search across all items
- `GET /unknown-queue/count` — lightweight count for Sidebar badge
- `_cascade_identify()` batched at 100 items per iteration
- `list_unresolved_with_extras()` accepts optional `limit`, `q`, `session_id` filters
- All queries sorted `DESC` (most recent first)

### Model preload on startup
- `ProviderConfig.preload_on_start` toggle in config
- `_startup_preload()` in `create_app()` spawns daemon threads per provider
- `POST /config/preload-on-start` and Settings UI toggle

### Dev audio capture disabled by default
- `_dev_audio_enabled()` now requires explicit `VOICE_DIARY_SAVE_DEV_AUDIO=1`; no longer auto-enabled in `NODE_ENV=development`
- Capped at 5 minutes per track to prevent unbounded memory

### Lightning 2.4+ compatibility
- `_ensure_lightning_utilities()` force-pins `lightning.pytorch.utilities` as module attribute
- Pre-import of `lightning.pytorch.utilities` before PyAnnote loads
