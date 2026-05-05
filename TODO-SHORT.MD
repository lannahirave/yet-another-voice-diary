# Voice Diary — Improvement Roadmap

> Branches and tasks derived from competitor pipeline analysis
> (`docs/competitor-pipeline-analysis.md`) and ongoing development.

---

## COMPLETED

| # | Task | Commits |
|---|---|---|
| 1 | Enable React Compiler, verify no regressions | 4ed5643 |
| 2 | HF token setup during package install + model access instructions | separate branch |
| 3 | ElevenLabs Scribe provider (token stored in settings) | 762b5df |
| 4 | VAD as first-class provider with Vexa hysteresis (onset 0.60/offset 0.45) | bea8a76 |
| 5 | VAD param tuning: min_silence 300ms, padding 300/400ms, max_utt 10s | bea8a76 |
| 6 | VAD resilience: degraded mode instead of crash | bea8a76 |
| 7 | Settings Pipeline tab — 7 VAD sliders + 4 ASR quality sliders | bea8a76 |
| 8 | Frontend utterance visual merging (same speaker, <1s gap) | bea8a76 |
| 9 | ASR quality gates: no_speech_threshold, compression_ratio, repetition_penalty, ngram_block | d553d47 |
| 10 | Model loading progress: SSE replaced with React Query polling | d553d47 |
| 11 | VAD owns audio buffer — SpeechSegment returned per utterance (2.6) | b81a0e7 |
| 12 | Draft streaming: lightweight Whisper small for gray interim text (2.7) | 7bdb46d |
| 13 | Log whisper model_id in transcription messages | e3f7cd9 |
| 14 | Debug report: utt_id in events + save/fail logging | 992afb5 |
| 15 | Debug report: full session ID display | 992afb5 |
| 16 | RAM fixes: frame buffer list-of-chunks, GC pulse, draft ASR unload | 76c9095 |
| 17 | Mic = You always: skip diarization for mic audio | c2ac48b |
| 18 | mic_is_self toggle in Settings + draft streaming toggle | 7f6e33c |

---

## PLANNED — SYS = Never You

> Source: `docs/competitor-pipeline-analysis.md` §4 (Diarization)

- [ ] System audio utterances can never resolve to a contact marked as "self"
- [ ] Add `is_self` flag on contacts table + create/edit UI checkbox
- [ ] Resolver skips self-profile for system-source segments

---

## PLANNED — ASR Hardening

> Source: `docs/competitor-pipeline-analysis.md` §3 (ASR — Vexa's temperature fallback)

- [ ] Temperature fallback chain `[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]` — retry on hallucination
- [ ] Audio preprocessing: high-pass filter (80Hz) + loudness normalization

---

## PLANNED — Batch Re-Transcription

> Source: `docs/competitor-pipeline-analysis.md` §6 (OpenOats batch pattern)

- [ ] After session ends, re-transcribe full audio with better model
- [ ] Merge batch results into existing utterances
- [ ] Guard: don't overwrite if batch quality is worse than live
