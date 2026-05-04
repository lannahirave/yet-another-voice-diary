# Voice Diary — Improvement Roadmap

> Branches and tasks derived from competitor pipeline analysis
> (`docs/competitor-pipeline-analysis.md`) and ongoing development.

---

## COMPLETED

| # | Task | Branch |
|---|---|---|
| 1 | Enable React Compiler, verify no regressions | separate branch |
| 2 | HF token setup during package install + model access instructions | separate branch |
| 3 | ElevenLabs Scribe provider (token stored in settings) | separate branch |

---

## ACTIVE — Utterance Pipeline Rework

> Source: `docs/competitor-pipeline-analysis.md` §2 (VAD) + §5 (Segmentation)
>
> All go in one branch: `pipeline/utterance-v2`

### 2.1 VAD Hysteresis — Dual Onset/Offset Thresholds

- [ ] Add `vad_negative_threshold` config (default 0.35)
- [ ] Implement dual-threshold in `VADProcessor`:
  - Onset (speech start): `vad_threshold` (0.50) — same as today
  - Offset (speech end): `vad_negative_threshold` (0.35) — lower, prevents mid-word toggling
- [ ] `VADIterator` doesn't support dual thresholds natively → consume raw probabilities from `VADIterator` and apply hysteresis in `VADProcessor`
- **Ref:** Meetily `vad.rs:43-44` (0.50/0.35), Vexa `vad.ts:29-32` (0.60/0.45)

### 2.2 Tighter Endpointing — Reduce min_silence

- [ ] Drop `vad_min_silence_ms` from 500ms → 300ms
- [ ] Shorter gap = utterances split on sentence pauses (~0.3s) rather than long breaks (0.5s)
- **Ref:** Meetily 400ms, Vexa 250ms, Voice Diary currently 500ms

### 2.3 Wider Speech Padding

- [ ] Increase `vad_speech_pad_ms` from 200ms → 350ms

##### frontend/src/api/client.ts:3-4
##### frontend/src/api/websocket.ts
##### frontend/src/types/api.ts
##### backend/api/routers/audio_ws.py
##### backend/pipeline/coordinator.py

### 2.4 Shorter Max Utterance (when diarization is on)

- [ ] When `diarization_model_id` is set (not `"off"`): `vad_max_utterance_ms` → 10s
- [ ] When diarization is off: keep at 30s
- [ ] Shorter utterances → better diarization accuracy (fewer speaker changes to untangle)
- **Ref:** OpenOats flushInterval 5s (local) / 10s (cloud), Vexa VAD_MAX_SPEECH_DURATION_S=15

### 2.5 VAD Resilience — Don't Crash on Error

- [ ] Replace `raise` on VAD failure with `warn` log + skip chunk
- [ ] Coordinator should not halt pipeline on VAD model glitch
- **Ref:** All three competitors skip chunk on VAD error; Voice Diary is the only one that raises

### 2.6 Extract VAD State Machine into VAD Layer

- [ ] Move `SpeechSegment` production from `coordinator.py` into `VADProcessor`
- [ ] `VADProcessor.process()` should return `list[SpeechSegment]` (pre-buffered, padded, timestamped)
- [ ] Coordinator should gate on min/max lengths, not manage the raw buffer
- **Ref:** Meetily's `ContinuousVadProcessor` returns `SpeechSegment` objects directly; OpenOats' `VadManager` emits `.speechStart`/`.speechEnd` with accumulated samples

### 2.7 Draft/Partial Utterance Streaming

- [ ] Add `"draft_utterance"` WebSocket event type
- [ ] Emit partial transcript at each `flushInterval` break (5-10s) before VAD silence triggers
- [ ] Frontend renders draft as gray interim text, replaces with final on `"utterance"` event
- [ ] Draft utterances skip diarization + embedding (ASR only, fast path)
- **Ref:** OpenOats partials every ~400ms during speech; Vexa draft/pending segments with LocalAgreement-2

---

## PLANNED — Speaker Attribution

> Source: `docs/competitor-pipeline-analysis.md` §4 (Diarization)

### Mic = You Always

- [ ] Hard-code mic → `speaker_label="you"` at the segment level (skip diarization on mic audio)
- [ ] Mic utterances always get `speaker_segment_id` linking to a per-session "you" segment
- **Ref:** OpenOats `.you` speaker enum; all three competitors track mic separately

### SYS = Never You

- [ ] System audio utterances can never resolve to a contact marked as "self"
- [ ] Add `is_self` flag on contacts; resolver skips self-profile for system-source segments
- **Ref:** OpenOats `.them` + `.remote(N)` for system audio

---

## PLANNED — Hallucination Defense

> Source: `docs/competitor-pipeline-analysis.md` §3 (ASR — Vexa's hallucination filter)

- [ ] Add hallucination phrase blacklist (seed from Vexa's 134-phrase list)
- [ ] Add `no_speech_prob` threshold check on ASR output
- [ ] Add `compression_ratio` threshold (reject > 2.4)
- [ ] Add repetition-penalty config (`no_repeat_ngram_size`)

---

## PLANNED — Audio Preprocessing

> Source: `docs/competitor-pipeline-analysis.md` §8 (Meetily's audio chain)

- [ ] Add high-pass filter (80Hz cutoff) before VAD
- [ ] Investigate RNNoise integration (Python bindings or subprocess)
- [ ] Normalize loudness to consistent level before ASR

---

## PLANNED — Batch Re-Transcription

> Source: `docs/competitor-pipeline-analysis.md` §6 (OpenOats batch pattern)

- [ ] After session ends, re-transcribe full session audio with better model
- [ ] Merge batch results into existing utterances (replace transcripts, keep speaker attributions)
- [ ] Guard: don't overwrite if batch quality is worse than live
