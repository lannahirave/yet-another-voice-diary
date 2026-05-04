# VAD Improvement Plan — Thesis-Grade Analysis

> From conversation with competitor pipeline analysis (`docs/competitor-pipeline-analysis.md`)
> and Voice Diary utterance pipeline (`docs/utterance-pipeline.md`).


## Current State

Voice Diary's VAD pipeline (`backend/pipeline/vad.py:192` lines,
`backend/pipeline/coordinator.py:632` lines) uses **Silero VAD** via
`silero_vad.VADIterator` with a single threshold and a coordinator-level
state machine.

| Parameter | Current Value | Where |
|---|---|---|
| `vad_threshold` | 0.5 | `config.py:53` |
| `vad_min_silence_ms` | 500ms | `config.py:56` |
| `vad_speech_pad_ms` | 200ms | `config.py:64` |
| `vad_min_utterance_ms` | 300ms | `config.py:71` |
| `vad_max_utterance_ms` | 30,000ms (30s) | `config.py:80` |

**Key architectural detail:** The utterance buffering logic is split across
two files:
- `vad.py` — frame buffering (512-sample windows), Silero VADIterator lifecycle
- `coordinator.py` — audio buffer (`_buffered_audio`), timestamps, min/max gates

All three competitors (Meetily, Vexa, OpenOats) consolidate buffer management
inside their VAD layer, returning complete `SpeechSegment` objects.


## 2.1 VAD Hysteresis — Dual Onset/Offset Thresholds

### Current Implementation

`vad.py:120-126` creates a Silero `VADIterator` with a **single threshold**:

```python
VADIterator(model, threshold=0.5, min_silence_duration_ms=500, speech_pad_ms=200)
```

Silero uses this one value for BOTH starting and stopping speech detection:
- Probability >= 0.5 → speech starts
- Probability < 0.5 → speech ends (after 500ms of sustained silence)

### Problem

A single threshold creates **rapid toggling** on borderline audio. Consider a
speaker hesitating:

> "So, uhhh... [probability wavers between 0.48 and 0.52 during thinking pause] ...I think we should..."

Each probability cross at 0.5 triggers a state change. The coordinator
opens/closes the buffer multiple times, producing tiny garbage utterances or
discarding them. The user hears a pause; the VAD sees confusion.

### How Competitors Solve This

**Meetily** (`vad.rs:43-44`) — dual thresholds:
```
positive_speech_threshold = 0.50   ← speech starts here
negative_speech_threshold = 0.35   ← speech ends here (after 400ms silence)
```

Once speech starts at 0.50, it stays "in speech" until probability drops to
0.35. The gap (0.50 → 0.35) is the **hysteresis band** — it absorbs wavering
at borderline probabilities. The user's "uhhh..." stays a single utterance.

**Vexa** (`vad.ts:29-32`) — same pattern at 0.60/0.45:
```
threshold = 0.60          ← onset (higher = conservative start)
negThreshold = 0.45       ← offset (onset - 0.15, min 0.01)
```

Vexa is more conservative (harder to start, harder to stop), which makes sense
for noisy meeting audio with multiple speakers.

### Implementation Plan

Silero's `VADIterator` only accepts a single `threshold` parameter — it does
not support dual thresholds. We must bypass `VADIterator` and call the raw
model to get per-frame probabilities:

```python
# Today: self._iterator(torch.from_numpy(frame).float())  ← opaque start/end events
# After: prob = self._model(torch.from_numpy(frame).float(), self.sample_rate).item()
#         Apply custom hysteresis state machine on raw probability
```

The raw model returns a float probability (0.0–1.0). We maintain our own state:

```
_is_voiced=False, prob >= onset (0.50):
    → set _is_voiced=True, emit speech start

_is_voiced=True, prob < offset (0.35):
    → start counting silence frames
    → after min_silence_ms of sustained sub-offset:
        → set _is_voiced=False, emit speech end

_is_voiced=True, offset ≤ prob < onset:
    → still in speech (hysteresis band), continue buffering
```

New config field:
```python
vad_negative_threshold: float = 0.35  # offset (NEW)
```

### Trade-offs

- **Loses `VADIterator` convenience** — must implement silence counting,
  frame accumulation, and state transitions manually (~40 lines)
- **Same runtime cost** — the raw model is the same ONNX op underneath
- **Better endpointer quality** — fewer false edges, smoother boundaries
- **Parameter tuning** — 0.35 offset is correct for our use case (validated
  by Meetily's data), but may need per-microphone adjustment

### Literature Support

Hysteresis is standard in production VAD systems. Silero's own documentation
acknowledges the limitation of single-threshold VADIterator and recommends
dual-threshold for streaming applications. Picovoice's real-time VAD uses
similar hysteresis. The pattern is also used in WebRTC's VAD (though its
underlying model differs).


## 2.2 Tighter Endpointing — Reduce min_silence

### Current

`config.py:56` — `vad_min_silence_ms: int = 500`

500ms of continuous silence must elapse before VAD declares speech-end.

### Why 500ms Is Too High

500ms is ~3-4 syllables of silence — the gap between **paragraphs** in
formal speech. But in real conversation, people pause for ~200-300ms between
sentences, and less in heated/overlapping exchanges. 500ms forces
multi-sentence paragraphs into single utterances.

Example:
> "I went to the store. [280ms breath] They were out of milk. [310ms pause]
> So I got oat milk instead."

- **500ms min_silence:** ONE utterance. PyAnnote must untangle 3 sentences.
  Diarization gets one shot at speaker attribution. Any speaker change during
  the [280ms] or [310ms] gaps is invisible.
- **300ms min_silence:** THREE utterances. Each gets independent diarization.
  Better speaker tracking. The 280ms pause becomes a boundary.

### What Competitors Use

| Project | min_silence / redemption |
|---|---|
| Meetily | 400ms |
| Vexa | 250ms |
| OpenOats | ~200-300ms (FluidAudio default) |
| **Voice Diary** | 500ms (highest of all) |

### The Change

```
config.py:56: vad_min_silence_ms: int = 500 → 300
```

### Trade-offs

- **More utterances** → more ASR + diarization + embedding calls
- But each utterance is **shorter**, so total CPU is roughly net neutral for
  ASR (faster-whisper scales with audio length)
- PyAnnote diarization **does** add per-utterance overhead (~1-2s per call
  for pipeline setup/teardown). For a session with 50 utterances instead of
  30, that's ~20-40s of additional diarization CPU.
- **Risk:** a 280ms intra-sentence pause could split mid-thought if the
  probability transiently dips. The **hysteresis from 2.1 mitigates this** —
  once speech is active, a brief probability dip inside the hysteresis band
  (0.35-0.50) won't trigger the silence counter.

### Parallel Design Consideration

If we want tighter splits for better diarization but worry about mid-sentence
splits, we could use a **two-tier silence threshold**:

1. During active speech with hysteresis engaged: 500ms silence to split
2. After hysteresis disengages (probability dropped below offset): 300ms
   silence to split

This gives us "don't split mid-sentence" protection while still allowing
tighter boundaries between turns. However, this adds complexity for marginal
gain — the hysteresis band already provides this protection at the probability
level, making a two-tier silence duration redundant.


## 2.3 Wider Speech Padding

### Current

`config.py:64` — `vad_speech_pad_ms: int = 200`

200ms of audio padding on BOTH sides of detected speech. Captures
co-articulation for Whisper phoneme disambiguation.

### Why 200ms Is Too Little

200ms = ~6 phonemes at normal speech rate. It captures the "attack" of a word
but not the full pre-utterance context. Whisper's transformer architecture
benefits from 300-500ms of context on each side to properly resolve the first
and last phonemes of an utterance.

### What Competitors Use

| Project | Pre-speech | Post-speech | Total |
|---|---|---|---|
| Meetily | 300ms | 400ms | **700ms** |
| OpenOats | 512ms | VAD natural | ~500ms+ |
| Voice Diary | 200ms | 200ms | **400ms** (lowest) |

### The Change

```
config.py:64: vad_speech_pad_ms: int = 200 → 350
```

New total: 350ms × 2 = 700ms (matches Meetily).

### Trade-offs

- **~700 additional samples per utterance** (11,200 float32 = 0.07 MB).
  Completely negligible for memory and latency.
- **Looser timestamps** — the padded boundary extends beyond the actual speech
  onset/offset. If tight timestamps are needed, use ASR word-level timestamps
  (faster-whisper provides these), not VAD boundaries.
- **No latency impact** — padding is pre-buffered (preroll from previous
  chunk), not waited for.


## 2.4 Shorter Max Utterance When Diarization Is On

### Current

`config.py:80` — `vad_max_utterance_ms: int = 30000` (30 seconds)

`coordinator.py:622-632`: When `_buffered_speech_ms` reaches 30s, force-flush
mid-speech. Speaker stays voiced, next chunk continues buffering a fresh
utterance.

### Why 10s Is Better When PyAnnote Is Active

PyAnnote processes the **entire utterance audio** to find speaker change
points and cluster segments. A 30-second utterance could contain:

```
[Speaker A: 8s] [Speaker B: 12s] [Speaker A: 10s] = 30s, 2 change points
```

PyAnnote must find 2 transitions and cluster 3 segments from 30s of audio.
With a 10-second cap:

```
[Speaker A: 8s] [Speaker B: 2s] → FLUSH at 10s → 1 change point, 2 speakers
[Speaker B: 10s] → FLUSH at 10s → 1 speaker, trivial
[Speaker A: 10s] → FLUSH at 10s → 1 speaker, trivial
```

Simpler segmentation → higher diarization accuracy. The embedding extracted
from the second utterance (pure Speaker B audio) is also cleaner than an
embedding from multi-speaker concatenation.

**But when diarization is OFF:** No benefit to splitting at 10s. A 30s
monologue from one person can be one utterance. Fewer utterances = less ASR
overhead. So the cap should be **conditional**:

```python
# In coordinator.__init__:
if self.config.diarization_model_id != "off":
    self._effective_max_utterance_ms = min(config.vad_max_utterance_ms, 10_000)
else:
    self._effective_max_utterance_ms = config.vad_max_utterance_ms  # 30s
```

### Trade-offs

- With diarization ON: ~3x more utterances in monologue-heavy sessions
- Each utterance is shorter → ASR is faster per call → net CPU roughly neutral
- 10s value matches scientific practice: PyAnnote papers use 5-15s segments;
  ECAPA-TDNN was trained on 2-5s utterances; 10s is a comfortable middle
- Actually **reduces** PyAnnote memory pressure: 10s of 16kHz mono = 160k
  samples, vs 480k samples for 30s. PyAnnote's transformer scales
  quadratically with input length.


## 2.5 VAD Resilience — Don't Crash on Error

### Current

`vad.py:186-190`:
```python
except Exception as exc:
    self._error = f"Silero VAD inference failed: {exc}"
    self._state = "ERROR"
    log.exception("Silero VAD inference failed")
    raise RuntimeError(self._error) from exc   # ← KILLS THE ENTIRE WEBSOCKET
```

And `coordinator.py:586-588`:
```python
vad_segment = self.vad.process(audio, sample_rate)
if vad_segment is None:
    return   # ← handles empty chunks but never reached on exception (raise kills first)
```

A transient Silero error (NaN tensor, CUDA glitch, memory pressure) causes
the WebSocket connection to die. All buffered audio is lost. The user's
recording is unrecoverable. This is the worst possible outcome for a
recoverable model error.

### How All Three Competitors Handle This

| Project | VAD Error Handling |
|---|---|
| **Meetily** | `warn!("VAD error: {}", e);` — log, skip chunk, continue |
| **Vexa** | Falls back to sending all audio unfiltered |
| **OpenOats** | Catches, logs, `continue` to next chunk |

**Voice Diary is the ONLY project that raises an exception on VAD failure.**

### Implementation

```python
try:
    while self._frame_buffer.size >= self._frame_samples:
        frame = ...
        event = self._iterator(torch.from_numpy(frame).float())
        ...
except Exception:
    log.exception("Silero VAD inference failed; treating chunk as silence")
    self._frame_buffer = np.zeros(0, dtype=np.float32)  # discard partial frame
    # Don't raise, don't touch _is_voiced
    return VADSegment(start_ms=start_ms, end_ms=end_ms, is_speech=False)
```

**Why `is_speech=False` is the safe default:**
- If the speaker WAS in speech, returning `is_speech=False` will trigger a
  falling-edge in the coordinator, flushing the utterance buffer. This is
  slightly wrong (cuts off the utterance early) but preserves all the
  previously-buffered audio.
- If the speaker was NOT in speech, it's a no-op.
- Alternative: return `is_speech = previous_state`. Less disruptive but risks
  false continuation if the model is truly corrupted.

### Trade-offs

- One downside: if the error is caused by a permanently corrupted model state,
  the pipeline silently produces no more speech. Detectable (user notices
  "no transcripts appearing") and recoverable (restart recording).
- This is a classic "fail open vs fail closed" decision. For a recording app,
  **fail open** (continue, possibly degraded) is better than **fail closed**
  (crash, lose all data).

### Mitigation

Add a **consecutive error counter**. If VAD fails 10 consecutive times, log
a critical error and optionally emit an `"error"` event to the frontend. This
gives the user visibility without crashing the pipeline.


## 2.6 Extract VAD State Machine into VAD Layer

### Current Architecture

The utterance buffering logic is split across two files in a way that creates
tight coupling:

| Responsibility | Where | Code |
|---|---|---|
| Frame buffering (512-sample windows) | `vad.py:170-173` | `_frame_buffer` |
| Speech/silence state (`_is_voiced`) | `vad.py:71,183-185` | Set by VADIterator events |
| Audio buffer (accumulated speech samples) | `coordinator.py:70` | `_buffered_audio` |
| Buffer timestamps | `coordinator.py:71-72` | `_buffer_started_ms`, `_buffer_ended_ms` |
| Speech duration tracking | `coordinator.py:75` | `_buffered_speech_ms` |
| Min-utterance gate | `coordinator.py:608-616` | `_buffered_speech_ms >= vad_min_utterance_ms` |
| Max-utterance force-flush | `coordinator.py:622-632` | `_buffered_speech_ms >= vad_max_utterance_ms` |

Additionally, `coordinator.py:74` (`_in_speech`) and `vad.py:71` (`_is_voiced`)
track the SAME information redundantly. Line 590 reads from the VAD and
writes to the coordinator: `was_in_speech = self._in_speech`.

### Target Architecture (After Refactor)

`VADProcessor` gains full ownership of audio buffering:

```python
class VADProcessor:
    _speech_buffer: list[np.ndarray]       # accumulated speech audio
    _speech_started_ms: int                # session-relative start
    _speech_duration_ms: int               # total speech in buffer
    _preroll_buffer: list[np.ndarray]      # recent chunks for context
    _is_voiced: bool                       # current speech/silence
```

New return type:
```python
VADResult: TypeAlias = None | VADMetadata | SpeechSegment
```
- `None` — no event, keep going
- `VADMetadata` — debug info (is_speech, probability)
- `SpeechSegment` — complete utterance (padded audio, start_ms, end_ms, duration_ms)

The coordinator simplifies to:

```python
async def process_chunk(self, audio, sample_rate):
    result = self.vad.process(audio, sample_rate)
    if result is None:
        return
    if isinstance(result, SpeechSegment):
        if result.duration_ms < self.config.vad_min_utterance_ms:
            return  # discard
        if result.duration_ms >= self._effective_max_utterance_ms:
            # large segment, but gating moved to coordinator
        await self._infer_and_emit(result)
```

### Why This Matters

1. **Testability:** You can test VAD buffering without spinning up a
   coordinator, ASR provider, diarization model, and embedding model.
   Currently, testing the utterance splitting logic requires the full stack.
2. **Reusability:** If we add batch file processing or a different audio
   source (file import, API audio), the VAD layer works unchanged.
3. **Parallelism:** With VAD owning the buffer, we can start ASR on segment N
   while VAD buffers segment N+1. Currently impossible because the single
   coordinator buffer is the bottleneck.
4. **Code clarity:** Coordinator drops from 632 to ~400 lines; VAD grows from
   192 to ~280 lines. Each file has one clear responsibility.

### Trade-offs

- **Risk:** This is a refactor of the two most critical files in the pipeline.
  A regression in utterance boundaries would affect every downstream system
  (ASR, diarization, embedding, speaker resolution).
- **Mitigation:** Unit tests in `backend/tests/` cover the coordinator; e2e
  tests cover full pipeline. All must pass before and after.

### Alignment with Competitive Landscape

- **Meetily:** `ContinuousVadProcessor` (`vad.rs`) already follows this
  pattern — it returns `SpeechSegment` objects directly.
- **OpenOats:** `StreamingTranscriber` manages buffering internally; the VAD
  manager (`VadManager`) just provides speech/silence classification.
- **Vexa:** `SpeakerStreamManager` owns the entire speaker buffer (audio
  accumulation, confirmation logic, Whisper submission). The VAD is an
  entry gate, not a segmenter.

All three competitors have the VAD layer (or equivalent) produce self-contained
segments.


## 2.7 Draft/Partial Utterance Streaming

### Current State

The pipeline is a **black box** from the user's perspective:
1. User speaks
2. 500ms silence → VAD declares speech-end
3. ASR runs (1-3s for faster-whisper)
4. Diarization runs (2-5s for PyAnnote)
5. Embedding runs (0.5s for ECAPA)
6. Speaker resolution runs (0.1s for cosine scan)
7. **Utterance appears in UI** — 4-9 seconds after user stopped speaking

The frontend shows a blinking "● LIVE" indicator but has no textual preview
of what's being said. This is the worst user experience of all analyzed
systems.

### How Competitors Solve This

**OpenOats** (`StreamingTranscriber.swift`) — the gold standard:
- Every ~400ms during active speech, the ASR backend emits a **partial
  hypothesis** — the current best guess at what's being said
- Partial text is displayed as **gray italic text** inline in the transcript
- When VAD speech-end fires, the **final transcript** canvas the gray text

**Vexa** (`SpeakerStreamManager`) — word-prefix confirmation:
- Every 2 seconds, audio buffer → Whisper
- Each result published as a **draft** segment
- Words that appear in 2 consecutive submissions → **confirmed** segment
- Drafts at ~2s latency; confirmed at ~4-6s

### Proposed Architecture for Voice Diary

Add a **fast ASR path** that skips diarization and embedding. Trigger it at
intervals during active speech:

```
Audio → VAD → buffer accumulating...
                │
                ├─ Every draft_interval_ms (5s) of speech:
                │    submit draft ASR to a SEPARATE thread
                │    → if draft completes before VAD silence:
                │        emit "draft_utterance" WebSocket message
                │        frontend shows gray interim text
                │
                └─ VAD speech-end:
                     full pipeline (ASR + diarization + embedding)
                     → emit "utterance" (replaces draft)
```

**New WebSocket message:**
```json
{
  "type": "draft_utterance",
  "data": {
    "session_id": "...",
    "started_ms": 1500,
    "transcript": "I went to the store and they",
    "confidence": 0.92,
    "language": "en"
  }
}
```

**New config:**
```python
draft_interval_ms: int = 5000       # How often to run draft ASR
draft_enabled: bool = False         # Feature flag, off by default
```

**Frontend change:**
- `CurrentSession.tsx` handles `"draft_utterance"` event
- Shows gray text at bottom of utterance list
- When final `"utterance"` arrives, draft text replaced by full entry
- `showLive` indicator stays during speech; draft text provides actual content

### Threading Challenge

The coordinator uses `ThreadPoolExecutor(max_workers=1)` for all ML inference.
Submitting a draft ASR to this pool while the main pipeline runs would queue
behind it — defeating the purpose.

**Solutions (ordered by complexity):**

1. **Separate ThreadPoolExecutor for drafts** (max_workers=1): The draft ASR
   doesn't compete with the main pipeline. Requires a second ASR model
   instance (~3GB for faster-whisper large-v3).

2. **Shared model with lock:** Single ASR model instance protected by a
   `threading.Lock`. Draft acquires lock → transcribes → releases. Main
   pipeline does the same. If lock is held, skip draft (next interval retries).
   Saves 3GB RAM but serializes ASR calls.

3. **True streaming ASR (future):** faster-whisper's native streaming API —
   feed audio incrementally, get partial decoder results continuously.
   No separate draft submissions needed. This is the endgame.

**Recommended starting point:** Option 1 (separate executor). Simplest, safest,
lowest latency. 3GB RAM overhead is acceptable for desktop (most users have
16GB+).

### Trade-offs

- Drafts skip diarization + embedding → no speaker labels on draft text.
  Acceptable — drafts are temporary previews.
- Two ASR model instances → ~3GB additional RAM.
- Draft latency: 5s interval + 1-3s ASR = 6-8s to first draft text.
  OpenOats does 400ms partials; we'd be slower but still 2-3x better than
  today's 4-9s after speech ends.
- `draft_interval_ms` can be reduced to 3s or 2s after initial testing for
  lower latency, at the cost of more ASR calls.


## Sequencing Recommendation

Ordered by risk and dependency:

```
Phase 1 (low risk, config only):
  2.2  min_silence 500→300
  2.3  speech_pad 200→350
  2.4  Max utterance conditional (10s with diarization)
  2.5  VAD resilience (don't raise)

Phase 2 (medium risk, VAD internals):
  2.1  Hysteresis (dual thresholds)
  2.6  Extract state machine into VAD layer
       ⚠ 2.6 depends on 2.1 (hysteresis changes VAD internals,
          better to refactor state machine after new logic is stable)

Phase 3 (medium risk, new feature):
  2.7  Draft/partial utterance streaming
       ⚠ 2.7 depends on 2.6 (needs clean VAD→SpeechSegment boundary
          for timer-based buffer sampling)
```

Each phase is independently testable. Phase 1 is a single afternoon of work.
Phase 2 is 1-2 days. Phase 3 is 2-3 days (includes frontend changes).
