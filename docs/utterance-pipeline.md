# Utterance Pipeline: VAD, Diarization & Frontend Flow

How raw audio becomes timestamped, speaker-labeled text utterances that appear
in the UI in near-real-time.

---

## 1. End-to-End Flow

```
WebSocket PCM 16kHz float32 → Silero VAD → Speech Buffer (rising/falling edges)
  → On silence: flush → ASR (faster-whisper) → Diarization (PyAnnote 3.1)
  → Speaker Embedding (ECAPA-TDNN) → Speaker Resolution → WebSocket JSON → UI
```

**All segmentation is backend-only.** The frontend appends incoming
`{"type":"utterance"}` JSON messages to a React state array — no client-side
splitting, merging, or deduplication.

---

## 2. VAD (Voice Activity Detection)

**File:** `backend/providers/vad.py` (356 lines, moved from `backend/pipeline/vad.py`)

**Model:** [silero-vad](https://github.com/snakers4/silero-vad) via the
`silero_vad` package.  **Bypasses** ``VADIterator`` and drives the raw model
directly to obtain per-frame speech probabilities — this is necessary because
`VADIterator` only supports a single threshold, but we need dual-threshold
hysteresis (Vexa pattern).

The VAD is now a **first-class provider** matching the ASR / diarization /
embedding pattern.  A single `SileroVADProvider` singleton holds the loaded
model and global config; per-connection `VadSession` objects carry independent
LSTM state, frame buffers, hysteresis counters, and preroll ring buffers.

### Dual-Threshold Hysteresis

| Parameter | Default | Description |
|---|---|---|
| `vad_threshold` (onset) | 0.60 | Speech starts when per-frame probability ≥ onset |
| `vad_negative_threshold` (offset) | 0.45 | Speech continues until probability drops below offset for `vad_min_silence_ms` |
| `vad_min_silence_ms` | 300 | Sub-offset silence required to trigger post-pad window |

The gap 0.60 → 0.45 is the **hysteresis band** — it absorbs wavering
borderline speech (hesitations, thinking pauses) and prevents rapid toggling
that causes phantom utterance boundaries.

### Asymmetric Padding

| Parameter | Default | Description |
|---|---|---|
| `vad_speech_pad_pre_ms` | 300 | Audio before speech onset (preroll ring buffer) |
| `vad_speech_pad_post_ms` | 400 | Trailing audio after speech end (VAD delays `is_speech=False` signal) |

Padding handled internally: preroll extracted from a ring buffer of recent
chunks on speech start, returned to the coordinator via `VADSegment.preroll_audio`.
Post-pad implemented as a delayed `is_speech=False` signal — the VAD stays
"voiced" for 400ms after probability drops below offset.

### Frame Buffering

Silero requires **fixed 512-sample frames** at 16 kHz (32 ms each). WebSocket
chunks can be variable-length, so the `VadSession` maintains a `_frame_buffer`
that accumulates partial frames and drains them in fixed-size windows.  Leftover
samples are kept for the next `process()` call.

### Degraded Mode (VAD resilience)

If the Silero model crashes (NaN tensor, CUDA glitch, memory pressure) the
session enters **degraded mode**: every subsequent chunk returns
`is_speech=True`.  The coordinator's max-utterance gate (10 s) still
force-flushes, so the user gets 10 s chunks transcribed.  The recording
doesn't die — transcription quality degrades but survives.  Matches Vexa's
"fall back to sending raw audio unfiltered" pattern.

### Configuration Summary

| Parameter | Default | File |
|---|---|---|
| `vad_threshold` (onset) | `0.60` | `config.py:53` |
| `vad_negative_threshold` (offset) | `0.45` | `config.py:61` |
| `vad_min_silence_ms` | `300` | `config.py:69` |
| `vad_speech_pad_pre_ms` | `300` | `config.py:76` |
| `vad_speech_pad_post_ms` | `400` | `config.py:83` |
| `vad_model_id` | `"silero"` | `config.py:147` |

---

## 3. Utterance Splitting State Machine

**File:** `backend/pipeline/coordinator.py:555-632`

The coordinator drives a state machine on each `process_chunk()` call:

### Rising Edge (silence → speech)
- Buffer opens, audio appended to `_audio_buffer`
- `_buffer_started_ms` recorded

### During Speech
- Audio appended, `_buffered_speech_ms` accumulates

### Falling Edge (speech → silence)
1. **Min-utterance gate:** If `_buffered_speech_ms < vad_min_utterance_ms`
   (300ms default), the buffer is **discarded** — suppresses coughs, clicks,
   mic bumps.
2. **Valid utterance:** If ≥ 300ms, buffer is flushed → full inference pipeline
   (ASR + diarization + embedding).
3. The falling-edge chunk **is included** in the buffer so Silero's trailing
   speech-pad is preserved.

### Monologue Guard (force-split)
If `_buffered_speech_ms ≥ vad_max_utterance_ms` (10s default), force-flush
while keeping the speaker marked as voiced. This bounds memory usage and ASR
latency for long monologues. **Trade-off:** force-splits at the VAD boundary
without regard for sentence structure — may cut mid-word.

### Rising Edge Preroll

On speech start (silence → speech), the coordinator checks
`VADSegment.preroll_audio` — audio from the preceding silence window
accumulated by the VAD's ring buffer.  This preroll is prepended to the
utterance buffer so Whisper has co-articulation context for the first phoneme.

### End-of-Session Flush

`end_session()` (coordinator.py:144-168): Only flushes if
`_buffered_speech_ms ≥ vad_min_utterance_ms`. Prevents trailing noise (key
release, breath, terminal click at 256-512ms) from polluting the unknown queue.

**Historical note:** A prior version of `end_session()` always flushed,
bypassing the min-utterance gate. This produced 256ms "utterances" with
Whisper hallucinations (".", "Thanks.") that became junk `speaker_segments` in
the unknown queue — documented in
`docs/voice-recognition-review.md:137-159`.

### Timeline Tracking

- `_session_elapsed_ms`: cumulative clock per session
- `_buffer_started_ms` / `_buffer_ended_ms`: absolute offsets of buffered span
- `_buffered_speech_ms`: total speech duration within the buffer
- Timestamps are session-relative (0 = session start), not wall-clock

### Configuration

| Parameter | Default | Effect |
|-----------|---------|--------|
| `vad_min_utterance_ms` | `300` | Floor — shorter utterances discarded (noise filter) |
| `vad_max_utterance_ms` | `30_000` | Ceiling — force-split monologues |

---

## 4. Inference Pipeline (per utterance)

**File:** `backend/pipeline/coordinator.py:248-445`

When an utterance is flushed, it undergoes sequential inference in a dedicated
`ThreadPoolExecutor` (max_workers=1 to avoid thread-safety issues with ML
models):

### Step 1: ASR (faster-whisper)
**File:** `backend/providers/asr.py` (343 lines)

- Primary: `faster-whisper` (CTranslate2)
- Fallback: HuggingFace `transformers` pipeline
- Returns transcript, language, confidence
- **On failure:** empty transcript, error emitted — pipeline continues
- **Empty transcript after ASR:** utterance discarded, buffer reset

### Step 2: Diarization (PyAnnote 3.1)
**File:** `backend/providers/diarization.py` (531 lines)

- Default model: `pyannote/speaker-diarization-3.1`
- Alternative: `nvidia/diar_streaming_sortformer_4spk-v2.1` (CUDA only)
- Runs on **closed VAD segments** (utterance-level), not continuous stream
- Returns `(start, end, speaker_label)` segments
- Supports overlapping speech natively (PyAnnote 3.1)
- **On failure or empty output:** entire audio treated as single `"speaker-0"`
- **Sortformer note:** the model supports live streaming, but here it's used
  on already-closed utterances only — simplifies the pluggable provider
  interface

### Step 3: Speaker Grouping
**File:** `backend/pipeline/coordinator.py:208-244`

Diarization segments are grouped by speaker label. Audio is sliced per speaker
and concatenated — each speaker group gets one embedding.

### Step 4: Embedding (ECAPA-TDNN)
**File:** `backend/providers/embedding.py` (179 lines)

- Model: `speechbrain/spkrec-ecapa-voxceleb` (192-dim, L2-normalized)
- Empty audio → `np.zeros(192)` (sentinel, cosine = 0 against anything)
- Audio < 1.5s produces unstable embeddings (genuine cosine can drop to
  0.45–0.55 even for same speaker)
- **On failure:** segment skipped, error emitted

### Step 5: Speaker Resolution
**File:** `backend/identification/resolver.py` (243 lines)

- Cosine similarity against all enrolled `voice_profiles`
- Threshold: `speaker_identification_threshold` (default 0.82, but real
  ECAPA same-speaker scores center at 0.65–0.80 — see
  `docs/voice-recognition-review.md:191-220`)
- Matched → `contact_id` set, `status='identified'`
- Unmatched → placed in `unknown_queue` for manual resolution

### Step 6: Emit

`_attach_and_emit()` (coordinator.py:429-445): Metadata (session_id,
timestamps, source) attached to `Utterance`, emitted as `"utterance"` event.
`SpeakerSegment` objects emit as `"speaker_segment"` events.

---

## 5. WebSocket Transport to Frontend

**File:** `backend/api/routers/audio_ws.py` (392 lines)

### Protocol

- Client → Server: binary `float32` PCM chunks at 16 kHz
- Server → Client: JSON messages
  - `{"type": "utterance", "data": {...}}`
  - `{"type": "speaker_segment", "data": {...}}`
  - `{"type": "error", "message": "..."}`

### Per-Connection Isolation

Each WebSocket gets its own `PipelineCoordinator`. Provider singletons (ASR,
diarization, embedding) are shared across all connections, but inference runs
in a shared thread pool (max_workers=1).

### Callbacks

1. **`on_utt`** (line 172): Persists to SQLite via `SessionRepo.create_utterance()`,
   enqueues `UtteranceOut` JSON to `asyncio.Queue`.

2. **`on_seg`** (line 176): Runs `SpeakerResolver.resolve()`, persists segment,
   enqueues to unknown queue if unmatched, then sends JSON.

3. **`_on_error_client`** (line 227): Forwards to WebSocket queue and persists
   to `pipeline_errors` table.

### Sender Task

Background `asyncio.Task` drains the queue and calls `ws.send_json()`. Final
drain after `end_session()` ensures trailing utterances are sent before closing.

### Dual Streams (Mic + System)

The frontend opens **two independent WebSockets**:
- `ws://.../ws/audio?track=mic` — microphone capture
- `ws://.../ws/audio?track=system` — system audio loopback (via `getDisplayMedia`)

Each runs through the same server pipeline but with `source` tracking
(migration `003_audio_source`). Voice profiles are scoped by `source`.

---

## 6. Frontend Flow

**Files:** `frontend/src/api/websocket.ts`, `frontend/src/components/CurrentSession.tsx`

### Connection

1. `AudioWebSocket` class (`websocket.ts:31`) wraps native `WebSocket`,
   parameterized by `track`.
2. On `connect(sessionId)`: opens `ws://127.0.0.1:8765/ws/audio?track=<track>`,
   sends `{"type":"start","session_id":"..."}`, awaits `{"type":"started"}`.
3. Routes incoming messages by `msg.type` and emits typed events.

### Live Utterance Handling

In `CurrentSession.tsx`:
- `ws.on('utterance', data => setUtterances(prev => [...prev, {...}]))`
- Raw `started_ms` → `"M:SS"` string formatting inline (duplicated from the
  adapter; this is a known DRY violation)
- `useState<Utterance[]>` in `App.tsx` holds all live utterances
- Rendered via `@tanstack/react-virtual` virtualizer for efficient scrolling

### Speaker Labels

- **Known contact:** Shows name in assigned color with avatar
- **Unknown:** Shows "Unknown" in muted italic, with "Identify" button
- **Identify picker:** Calls `GET /utterances/{id}/candidates` (cosine-ranked)
  and resolves via `POST /utterances/{id}/identify`
- **Optimistic updates:** `patchSessionUtterances()` immediately updates all
  utterances sharing the same `speaker_segment_id`

### History Browsing

`AllSessions.tsx` uses `useSessionUtterancesQuery` (React Query) via REST
`GET /sessions/{id}/utterances`. Goes through `adaptUtterance()` adapter
(properly maps `ApiUtterance` → `Utterance` domain type).

---

## 7. Configuration Summary

All values from `backend/config.py`, `PipelineConfig` dataclass (lines 42-98).

| Parameter | Default | Runtime Mutable? | Effect |
|-----------|---------|-------------------|--------|
| `vad_threshold` | `0.60` | No | Speech onset probability — sensitivity |
| `vad_negative_threshold` | `0.45` | No | Speech offset — lower = less eager to end |
| `vad_min_silence_ms` | `300` | No | Gap between utterances (lower = more splits, better diarization) |
| `vad_speech_pad_pre_ms` | `300` | No | Preroll before speech onset (Whisper co-articulation) |
| `vad_speech_pad_post_ms` | `400` | No | Trailing audio after speech end (delayed `is_speech=False`) |
| `vad_min_utterance_ms` | `300` | No | Minimum utterance length (noise filter) |
| `vad_max_utterance_ms` | `10_000` | No | Maximum before forced split (was 30s; 10s improves diarization) |
| `speaker_identification_threshold` | `0.5` | Yes (`POST /config/threshold`) | Cosine floor for auto-matching |
| `vad_model_id` | `"silero"` | No | VAD backend selection (provider) |
| `chunk_duration_ms` | `100` | No | Expected WebSocket chunk duration (reference) |
| `unload_models_after_stop` | `False` | No | Free RAM after recording (adds 3-10s next warm-up) |

**Persistence:** `~/.voice-diary/config.json`, loaded at startup.
VAD thresholds require app restart to change.

---

## 8. Graceful Degradation

Per `AGENTS.md`, the pipeline continues when any component fails:

| Component | Failure Mode |
|-----------|-------------|
| ASR | Empty transcript, error emitted |
| Diarization | Treated as single-speaker `"speaker-0"` |
| Embedding | Segment skipped, error emitted |
| Empty ASR transcript | Utterance discarded, buffer reset |
| VAD | **Exception raised** (lightweight, no fallback) |

---

## 9. Key File Index

| File | Lines | Role |
|------|-------|------|
| `backend/pipeline/coordinator.py` | 632 | Core state machine: buffering, endpointing, inference dispatch |
| `backend/pipeline/vad.py` | 192 | Silero VAD wrapper: frame buffering, VADIterator lifecycle |
| `backend/providers/asr.py` | 343 | Whisper ASR (faster-whisper with Transformers fallback) |
| `backend/providers/diarization.py` | 531 | PyAnnote 3.1 + NeMo Sortformer providers |
| `backend/providers/embedding.py` | 179 | ECAPA-TDNN speaker embeddings via SpeechBrain |
| `backend/config.py` | 176 | PipelineConfig, ProviderConfig, BackendConfig |
| `backend/models.py` | 80 | Domain models: Utterance, SpeakerSegment, etc. |
| `backend/api/routers/audio_ws.py` | 392 | WebSocket endpoint: binary audio in → JSON utterances out |
| `backend/identification/resolver.py` | 243 | Speaker identification via cosine similarity |
| `backend/identification/matching.py` | 35 | `find_best_match` — single highest cosine |
| `backend/storage/session_repo.py` | 327 | SQLite persistence for sessions, utterances, segments |
| `frontend/src/api/websocket.ts` | 146 | `AudioWebSocket` class — WebSocket client |
| `frontend/src/types/api.ts` | 14-26 | `ApiUtterance` type (mirrors `backend/api/schemas.py`) |
| `frontend/src/api/adapters.ts` | 60-71 | `adaptUtterance()` API → domain mapper |
| `frontend/src/components/CurrentSession.tsx` | — | Live recording view — WebSocket handlers, virtualized list |

---

## 10. Known Issues & Trade-offs

1. **30s force-split may cut mid-word** — no sentence-boundary awareness.
2. **300ms min-utterance drops short backchannels** ("yes!", "no!") — fine
   for meetings, less so for conversational use.
3. **ECAPA needs 1.5-3s for stable embeddings** — short utterances produce
   unreliable speaker vectors (cosine 0.45–0.75 for same speaker).
4. **Diarization runs on pre-segmented VAD chunks** — Sortformer's streaming
   capability is unused; all diarization is utterance-scoped.
5. **Live WebSocket utterances skip `adaptUtterance()`** — `msToTime()`
   formatting is duplicated inline in `CurrentSession.tsx`.
6. **Default identification threshold (0.82) is aggressive** — real ECAPA
   same-speaker scores center at 0.55–0.80 in single-mic audio.
   Runtime-adjustable via `POST /config/threshold`.
7. **VAD thresholds not runtime-mutable** — require app restart.
8. **No score fusion or top-k voting** — identification uses only the single
   best cosine match.
