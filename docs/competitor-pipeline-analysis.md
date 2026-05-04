# Competitor Pipeline Analysis: Meetily, Vexa, OpenOats

How three voice-transcription products implement VAD, ASR, diarization, and
utterance segmentation — compared against Voice Diary's approach.

Repos analyzed:
- [Meetily](https://github.com/Zackriya-Solutions/meetily) — Tauri desktop app (Rust + whisper.cpp)
- [Vexa](https://github.com/Vexa-ai/vexa) — Self-hosted meeting bot platform (Node.js + Python + Redis)
- [OpenOats](https://github.com/yazinsai/OpenOats) — macOS native copilot (Swift + CoreML/WhisperKit)

---

## 1. Project Overview

| | Meetily | Vexa | OpenOats | Voice Diary |
|---|---|---|---|---|
| **Type** | Desktop app | Self-hosted platform | macOS app | Desktop app (Electron) |
| **Language** | Rust + Next.js | Node.js + Python | Swift + SwiftUI | Python + TypeScript/React |
| **Platform** | Win/Mac/Linux | Docker/K8s | macOS 15+ (Apple Silicon) | Win/Mac/Linux |
| **Revenue** | Open core (Pro tier) | Open source, SaaS-hosted option | Open source | (internal project) |
| **Audio capture** | Mic + system loopback | Browser WebRTC per-speaker | Mic + system (CoreAudio) | Mic + system (getDisplayMedia) |
| **Key differentiator** | Rust performance, RNNoise denoising | Per-speaker DOM-driven audio, rich hallucination filter | Native performance, LS-EEND diarization, knowledge base copilot | Per-utterance speaker ID with voiceprint enrollment |

---

## 2. VAD (Voice Activity Detection)

All three use **Silero VAD** — but integrate it differently.

### Model Backend

| Project | Silero Backend | Format | Frame Size | SR |
|---|---|---|---|---|
| Meetily | `silero-rs` (Rust binding) | ONNX | 480 samples (30ms) | 16kHz |
| Vexa | `onnxruntime-node` | ONNX | 512 samples (32ms) | 16kHz |
| OpenOats | `FluidAudio.VadManager` | ONNX, optimized for Apple Silicon | 4096 samples (256ms) | 16kHz |
| **Voice Diary** | `silero_vad` (Python) | PyTorch JIT | 512 samples (32ms) | 16kHz |

### Hysteresis (Onset/Offset thresholds)

A key differentiator — only Meetily and Vexa use dual thresholds (onset higher
than offset) to prevent rapid toggling on borderline audio:

| | Onset (speech start) | Offset (speech end) | Redemption/min-silence |
|---|---|---|---|
| **Meetily** | 0.50 positive threshold | 0.35 negative threshold | 400ms |
| **Vexa** | 0.60 threshold | 0.45 (threshold - 0.15) | 250ms |
| **OpenOats** | FluidAudio `.default` | Same as onset | FluidAudio `.default` |
| **Voice Diary** | 0.50 threshold | Same as onset | 500ms |

**Observation:** Voice Diary uses a single threshold (0.5) with 500ms
min_silence. This is simpler but less nuanced than Meetily's dual-threshold
hysteresis, which allows earlier speech onset detection without false triggers.

### Padding

| | Pre-speech pad | Post-speech pad |
|---|---|---|
| **Meetily** | 300ms | 400ms |
| **Vexa** | N/A (per-request 2s chunks) | N/A |
| **OpenOats** | 512ms (2 chunks preroll) | N/A (VAD speech end) |
| **Voice Diary** | 200ms | 200ms |

**Observation:** Meetily pads more aggressively (300+400ms = 700ms total) vs
Voice Diary (400ms total). This captures more context for Whisper but produces
slightly wider utterance boundaries.

### VAD Trigger: Rise→Fall vs VADIterator

| | VAD API | State Model |
|---|---|---|
| **Meetily** | `VadSession.process(chunk)` returns `VadTransition::SpeechStart/SpeechEnd` events | `in_speech` boolean, accumulates samples between Start/End |
| **Vexa** | `isSpeechStreaming(audio)` returns `{speaking, probability}` per frame | Hysteresis counter — counts silence samples after offset |
| **OpenOats** | `vadManager.processStreamingChunk(chunk, state:)` returns `.speechStart/.speechEnd` events | Same Start/End pattern as Meetily |
| **Voice Diary** | `VADIterator` driven sample-by-sample via fixed frames, emits start/end internally | Coordinator-level `was_in_speech` + `is_speech_now` |

**Observation:** Meetily and OpenOats both wrap VAD events into a clean
Start/End state machine. Voice Diary's VADIterator approach is equivalent but
the event abstraction is split across `vad.py` (Silero events) and
`coordinator.py` (buffer gating). The Meetily/OpenOats pattern of returning
`SpeechSegment` objects directly from the VAD layer is cleaner.

---

## 3. ASR (Speech-to-Text)

### Model Choice

| | Primary Model | Alternative | Format |
|---|---|---|---|
| **Meetily** | whisper.cpp `large-v3-turbo` (GGML Q5_1) | Parakeet TDT 0.6B (ONNX) | C++ CTranslate2 |
| **Vexa** | faster-whisper `large-v3-turbo` (int8) | N/A | CTranslate2 |
| **OpenOats** | Parakeet TDT v2/v3, Qwen3 ASR, WhisperKit (CoreML) | AssemblyAI, ElevenLabs Scribe | CoreML / ONNX / Cloud |
| **Voice Diary** | faster-whisper `large-v3` (float16) | HuggingFace transformers fallback | CTranslate2 / PyTorch |

### Processing Mode

| | Per-utterance | Pseudo-streaming | True streaming | Partial results |
|---|---|---|---|---|
| **Meetily** | Yes | No | No | No (per-VAD-segment) |
| **Vexa** | Yes | **Yes** (2s submissions with LocalAgreement-2 word-prefix confirmation) | No | **Yes** (confirmed + pending drafts) |
| **OpenOats** | Yes | No | **Yes** (partial hypotheses every ~400ms during speech) | **Yes** (gray inline interim text) |
| **Voice Diary** | Yes | No | No | No |

**Insight:** Vexa's pseudo-streaming with word-prefix confirmation
(LocalAgreement-2) is the most sophisticated approach. It submits audio every
2 seconds, confirms text segments when they stabilize across consecutive
submissions, and emits both confirmed (stable) and pending (draft) segments.
Voice Diary's approach of waiting for VAD speech-end is simpler but has higher
latency — the user sees nothing until the VAD gap triggers.

### Hallucination Defense

| | Approach | Details |
|---|---|---|
| **Meetily** | Post-hoc text analysis | `clean_repetitive_text()` removes word/phrase repetitions; `is_meaningless_output()` rejects "thank you for watching", "applause", etc.; 70% repetition ratio → discard; no_speech_thold=0.55 |
| **Vexa** | **Two-layer** (server + client) | **Server:** `_looks_like_silence()` heuristic, `_looks_like_hallucination()` heuristic, temperature fallback chain [0.0→1.0], compression_ratio threshold, ngram repetition penalty. **Client:** 134+ known hallucination phrases (en/es/pt/ru), repetition loop detection, single-word <10 char filter, multi-layer quality gate (language prob ≥0.3, no_speech_prob ≤0.5, avg_logprob ≥-0.8, compression_ratio ≤2.4) |
| **OpenOats** | Echo suppression | Acoustic echo filter: Jaccard ≥0.78 or substring containment, 1.75s window, 4-word/20-char minimum. Live transcript cleaner (LLM-based filler removal). |
| **Voice Diary** | Silence/quality gate | Empty transcript → discard utterance; no_speech_thold not configured; depends on VAD to prevent hallucination on silence |

**Insight:** Vexa has the most comprehensive hallucination defense — a perfect
reference. Their known-phrase blacklist (134+ phrases) caught things like
"Thank you for watching", "Please subscribe", "Amara.org" that Whisper
hallucinates on silence. Voice Diary should adopt:
1. A hallucination-phrase blacklist
2. `compression_ratio` and `no_speech_prob` thresholds
3. Temperature fallback or repetition penalty

### Quality Gates

| Project | Quality filters on ASR output |
|---|---|
| **Meetily** | Confidence ≥0.3 (Whisper only, Parakeet has no confidence); no_speech_thold=0.55; max_len=200 tokens |
| **Vexa** | language_prob ≥0.3; no_speech_prob ≤0.5 AND avg_logprob ≥-0.7; avg_logprob ≥-0.8 AND duration ≥2.0s; compression_ratio ≤2.4 |
| **OpenOats** | Empty text silently ignored; cloud backends validate API keys preflight |
| **Voice Diary** | Empty transcript → discard utterance. No confidence/quality thresholds applied |

---

## 4. Diarization (Speaker Diarization)

This is where the projects diverge most dramatically:

### Approach Comparison

| | Diarization Approach | Speaker ID | Enrollment | Overlap |
|---|---|---|---|---|
| **Meetily** | **None** (Pro-only, coming soon) | N/A | N/A | N/A |
| **Vexa** | **Platform-specific DOM-driven** (no ML) | Per-track vote-and-lock (GMeet), caption-driven (Teams), DOM polling (Zoom) | N/A | N/A |
| **OpenOats** | **LS-EEND** (end-to-end neural, FluidAudio) | Frame-level speaker labels | None (per-session only) | **Native** (multi-speaker per frame) |
| **Voice Diary** | **PyAnnote 3.1** (clustering-based) | ECAPA-TDNN cosine matching against enrolled voice_profiles | Enrollment via unknown queue resolution | **Partial** (PyAnnote 3.1 native overlap support) |

### Vexa's "No-ML Diarization" — A Clever Hack

Vexa's approach is ingenious for its use case:
- Google Meet: Each participant = separate `<audio>` element. It watches DOM
  speaking-indicator CSS classes and uses a **vote-and-lock** system: track
  identity locked after 2 votes with ≥70% ratio. No ML needed.
- Teams: Reads built-in live captions (Teams' own ASR) to get `(speaker, text)`
  tuples. Routes audio by most recent caption event.
- Zoom: DOM polling every 250ms for active speaker badge. But Zoom's SFU
  display slots recycle — tracks can't be locked, lower accuracy.

**Limitation:** This only works for browser-based meeting platforms. It cannot
work for arbitrary audio or phone calls. Voice Diary's ML-based approach
(PyAnnote + ECAPA) is more general.

### OpenOats' LS-EEND — The Most Advanced ML Diarization

LS-EEND (End-to-End Neural Diarization) via FluidAudio is fundamentally
different from PyAnnote's pipeline approach:
- **PyAnnote:** Segmentation → Embedding extraction → Clustering (multi-stage)
- **LS-EEND:** Single neural network predicts speaker labels per frame directly

Advantages over PyAnnote: no clustering step, handles overlap naturally, single
pass. Limitation: fixed max speakers (4/7/10 depending on variant), no
cross-session speaker persistence.

### Voice Diary's Diarization vs. Competitors

| Aspect | Voice Diary | Best Competitor |
|---|---|---|
| Per-utterance diarization | Yes (PyAnnote on closed VAD segments) | OpenOats: Yes (LS-EEND on system audio, streaming) |
| Cross-session speaker ID | **Yes** (ECAPA voiceprints + cosine matching) | OpenOats: **No** (session-scoped only) |
| Speaker enrollment | **Yes** (manual via unknown queue) | OpenOats: No |
| Overlap handling | Partial (PyAnnote 3.1) | OpenOats: **Full** (LS-EEND native) |
| ML model loading overhead | High (PyAnnote ~2GB, ECAPA ~30MB) | OpenOats: Low (LS-EEND ~100MB CoreML) |

**Voice Diary's unique strength** is cross-session speaker identification with
manual enrollment. None of the three competitors offer this. They all treat
speaker labels as per-session ephemeral.

**OpenOats' LS-EEND** is worth investigating as a lighter-weight alternative
to PyAnnote — it runs on CoreML (Apple Silicon-optimized), handles overlap
natively, and uses far less memory.

---

## 5. Utterance Segmentation

### Comparison of Trigger Mechanisms

| | Primary Trigger | Min Utterance | Max Utterance | Pre-roll | Post-processing |
|---|---|---|---|---|---|
| **Meetily** | Silero SpeechEnd | 50ms (800 samples) | Whisper max_len=200 tokens | 300ms padding | Silence-based splitter for import flows (100ms window, RMS <0.02) |
| **Vexa** | `minAudioDuration`=3s + `submitInterval`=2s | 3s of unconfirmed audio | 30s buffer, 15s idle timeout | 2s chunk overlap | LocalAgreement-2 word-prefix confirmation, draft/pending system |
| **OpenOats** | Silero SpeechEnd + flushInterval (5/10s) | 1s (live), 0.5s (batch) | 5-10s flush | 512ms preroll (2 chunks) | Echo suppression (Jaccard 0.78), batch diarization slice (0.8s min run) |
| **Voice Diary** | Silero SpeechEnd | 300ms | 30s | 200ms padding each side | End-of-session flush gated on min_utterance |

### Key Architectural Differences

**Vexa's LocalAgreement-2 approach** is the most interesting. Instead of
waiting for silence, it continuously confirms text when words stabilize across
overlapping submissions. This means:
- Users see text faster (prevailing text appears ~2-4s after speech)
- Text is never wrong — only confirmed segments are finalized
- The 3s min_utterance is higher than all others, but drafts appear faster

**Meetily's 50ms min utterance** is too aggressive — virtually any VAD event
produces an utterance, relying entirely on Whisper hallucination defense to
filter noise.

**Voice Diary's 300ms min utterance** is a reasonable middle ground, but the
lack of partial/draft results means latency is higher than both Vexa and
OpenOats.

---

## 6. Pipeline Architecture

### Threading & Concurrency

| | Runtime | Audio Processing | ASR Inference | Inter-component Communication |
|---|---|---|---|---|
| **Meetily** | Tokio async | Single tokio task per pipeline | Single tokio task (1 worker) | mpsc::UnboundedSender/Receiver |
| **Vexa** | Node.js event loop + Python uvicorn | Per-bot container, per-speaker ScriptProcessor | HTTP POST to microservice, multi-worker | Redis Streams + Pub/Sub |
| **OpenOats** | Swift async/await, @MainActor | Two `Task.detached` (mic+sys) | Async per-stream, shared backends | AsyncStream, Combine/async, @Observable |
| **Voice Diary** | Python asyncio | WebSocket handler (sync → thread pool) | ThreadPoolExecutor (max_workers=1) | asyncio.Queue, callbacks |

### Streaming vs Batch

| | Live Mode | Post-Processing | Batch Re-transcription |
|---|---|---|---|
| **Meetily** | Real-time VAD → per-segment Whisper | LLM summarization (user-initiated) | Import/retranscription mode |
| **Vexa** | Pseudo-streaming (2s intervals) | S3 audio → post-meeting full transcription | Replay mode (`RAW_CAPTURE=true`) |
| **OpenOats** | Real-time partials + finals | LLM notes/suggestions/cleanup | **Yes** — batch re-transcription with better model, diarization, echo filter |
| **Voice Diary** | Real-time VAD → per-utterance ASR | None | None |

**Insight:** OpenOats' batch re-transcription is a powerful pattern — use a
fast model for live (Parakeet V2, ~200ms latency) then re-transcribe with a
better model post-meeting (Whisper large-v3-turbo, diarization enabled). Voice
Diary could adopt this to improve accuracy without sacrificing live latency.

### Provider Swap Pattern

| | Model Selectable at Runtime | Provider Abstraction |
|---|---|---|
| **Meetily** | Yes (Whisper vs Parakeet, model size) | `TranscriptionProvider` trait pattern |
| **Vexa** | Yes (model size, tier) | env vars + per-request overrides |
| **OpenOats** | **Yes** (6 local + 2 cloud) | **Clean protocol**: `TranscriptionBackend` with `prepare()`, `transcribe()`, `reset()`, properties for needs/supports |
| **Voice Diary** | Yes (ASR model, diarization model, embedding model) | `ASRProvider`, `DiarizationProvider`, `EmbeddingProvider` protocols |

**OpenOats' `TranscriptionBackend` protocol** is the cleanest — it includes
`prepare()` (pre-warm), `transcribe()` (with previousContext), `reset()`
(clear state), and properties for `skipPartials`, `needsModelDownload`, etc.
Voice Diary's protocol is comparable but doesn't have a `prepare/preflight`
step.

---

## 7. Frontend Integration

### How Results Reach UI

| | Transport | Update Mechanism | Partial Text | Speaker Display |
|---|---|---|---|---|
| **Meetily** | Tauri events (`transcript-update`) | React Context + useState | No | No speaker labels (yet) |
| **Vexa** | Redis pub/sub → WebSocket → Next.js | React hooks + WebSocket | Yes (draft/pending) | Speaker name from DOM |
| **OpenOats** | Swift @Observable in-process | Declarative reactive rendering | Yes (gray inline interim) | "You" / "Them" / "Speaker N" with colors |
| **Voice Diary** | WebSocket JSON → React state | useState + virtualizer | No (only show/hide indicator) | Contact name + avatar from voiceprint |

### Latency to First Text

| | Approximate Latency |
|---|---|
| **Meetily** | VAD speech-end + Whisper inference (1-5s after speech ends) |
| **Vexa** | 2-4s from speech onset (drafts), 4-6s for confirmed segments |
| **OpenOats** | ~400ms (partial hypotheses during speech), ~1-2s (final after VAD end) |
| **Voice Diary** | VAD speech-end (500ms silence) + ASR + diarization + embedding (3-10s total after speech ends) |

**Voice Diary has the highest latency** because it runs the full 4-stage
pipeline (ASR → diarization → embedding → speaker matching) before showing
anything. Adopting partial/draft results (like OpenOats) would dramatically
improve perceived responsiveness.

---

## 8. Audio Processing Pipeline (Pre-VAD)

| | Resampling | Noise Reduction | Normalization | Echo Cancellation |
|---|---|---|---|---|
| **Meetily** | rubato Sinc to 48kHz | **RNNoise** (10-15 dB), high-pass 80Hz | **EBU R128** to -23 LUFS | None (uses ring buffer sync) |
| **Vexa** | Browser native (ScriptProcessor) | None | None | Browser built-in |
| **OpenOats** | Internal to 16kHz mono Float32 | None (StreamingTranscriber raw) | None | Acoustic echo filter (text-level, post-transcription) |
| **Voice Diary** | Browser native (AudioContext 16kHz) | None | None | None |

**Meetily's audio chain is the gold standard** — RNNoise + EBU R128 loudness
normalization is what you'd expect from a professional audio pipeline. Voice
Diary does no audio preprocessing at all, which likely degrades ASR quality on
noisy mics.

---

## 9. Error Handling & Degradation

| | VAD Failure | ASR Failure | Diarization Failure | Pipeline Continuity |
|---|---|---|---|---|
| **Meetily** | Warn + skip chunk. Panic on init fail. | Emit error event + skip. No fallback ASR. | N/A | Continues on chunk errors |
| **Vexa** | Degrade gracefully (send all audio w/o VAD filtering) | Retry 3x backoff (1s→2s→4s). Drop on final fail. | N/A | Bot container independent, fails per-segment |
| **OpenOats** | Log + silently skip | Empty result ignored. Cloud: error surfaced in UI. | Stop relay, fallback to .them | Per-segment errors don't stop pipeline |
| **Voice Diary** | **Exception raised** (halts pipeline) | Empty transcript, error emitted. Fallback: HF transformers. | Treated as single-speaker "speaker-0" | Continues (per AGENTS.md) |

**Critical observation:** Voice Diary is the only project that raises an
exception on VAD failure. All three competitors treat VAD as recoverable —
they log + skip the chunk, or fall back to sending all audio unfiltered. Voice
Diary should adopt the skip-chunk pattern for VAD errors.

---

## 10. Key Takeaways for Voice Diary

### Strengths (unique features no competitor has)

1. **Cross-session speaker identification** with ECAPA voiceprint enrollment.
   All three competitors treat speakers as per-session ephemeral.
2. **Per-utterance speaker resolution** — diarization + embedding run on every
   utterance, producing contact-level attribution in real time.
3. **Dual-source tracking** (mic vs system) with source-scoped voice profiles.
4. **Manual speaker enrollment/resolution** via unknown queue.

### Gaps to Close

1. **Latency:** Implement partial/draft results during active speech (like
   OpenOats' ~400ms partials or Vexa's draft segments).
2. **Hallucination defense:** Adopt Vexa's multi-layer approach — known phrase
   blacklist, compression_ratio threshold, no_speech_prob gate, ngram
   repetition penalty.
3. **Audio preprocessing:** Meetily's RNNoise + EBU R128 normalization would
   improve ASR quality on noisy inputs.
4. **VAD resilience:** Don't raise on VAD error — log + skip chunk (Meetily
   pattern).
5. **Hysteresis:** Adopt dual-threshold onset/offset like Meetily and Vexa for
   smoother endpointing.
6. **Batch re-transcription:** OpenOats' pattern of live fast model + batch
   slow model would improve overall accuracy.
7. **Echo cancellation:** OpenOats' text-level acoustic echo filter (Jaccard
   similarity) would prevent transcribing mic playback of system audio.
8. **LS-EEND investigation:** A lighter, overlap-aware alternative to PyAnnote
   that could reduce model loading overhead.

### Architecture Patterns Worth Borrowing

| Pattern | Source | Benefit |
|---|---|---|
| Dual VAD thresholds (onset/offset hysteresis) | Meetily, Vexa | Fewer false edges, smoother endpointing |
| LocalAgreement-2 word-prefix confirmation | Vexa | Draft text appears faster, confirmed text never wrong |
| TranscriptionBackend protocol with prepare() | OpenOats | Clean provider swap, preflight validation |
| Batch re-transcription with better model | OpenOats | Fast live + accurate post-meeting |
| Audio pre-processing chain (denoise + normalize + high-pass) | Meetily | Better ASR accuracy |
| Hallucination phrase blacklist (134+ entries) | Vexa | Eliminates "Thank you for watching" on silence |
| temperature fallback chain [0.0→1.0] | Vexa | Recovers from hallucination at aggressive temperatures |
| Text-level echo filter (Jaccard similarity) | OpenOats | Prevents transcribing own system audio output |
