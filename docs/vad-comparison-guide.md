# VAD Pipeline — Comparison Guide

> Pick one topic at a time. Read what Voice Diary does, then what each
> competitor does differently. Decide which approach you want.

---

## Topic 1: How VAD decides "speech started" / "speech ended"

### Voice Diary (current)

```
                     ┌─────────────┐
                     │  threshold   │
                     │    0.50      │
                     └──────┬───────┘
                            │
        prob >= 0.50 ───────┼─────── prob < 0.50
        "SPEECH START"      │       "SPEECH END" (after 500ms silence)
```

One number for both decisions. When probability crosses 0.50 upward →
speech starts. When it drops below 0.50 for 500ms → speech ends.

**Problem:** Someone hesitating ("uhhh...") causes probability to flicker
around 0.50. Each crossing triggers a state change. Utterances get split
mid-thought, or phantom utterances get created from noise.

### Meetily

```
    ┌─────────────┐
    │  onset 0.50  │ ← speech starts here (same as us)
    │  offset 0.35 │ ← speech ends here (LOWER than onset)
    └──────┬───────┘
           │
    prob ≥ 0.50 ───── SPEECH START
           │
    prob drops to 0.46 → STILL SPEECH (in the "hysteresis band")
    prob drops to 0.34 → START counting silence (400ms) → SPEECH END
```

Two numbers. Speech starts at 0.50 but doesn't end until 0.35. The gap
(0.50–0.35) absorbs wavering. The "uhhh..." stays one utterance.

### Vexa

```
    ┌─────────────┐
    │  onset 0.60  │ ← harder to start (noisy meeting environment)
    │  offset 0.45 │ ← onset - 0.15 (always 0.15 below onset)
    └─────────────┘
```

Same idea, higher numbers. Makes sense for meetings where background noise
is higher — you want to be sure it's real speech before starting.

### OpenOats

Uses FluidAudio's `VadConfig.default`. Single threshold, no public hysteresis
configuration. Less relevant as a comparison — they don't expose VAD tuning.

### Decision

| Option | What it means |
|---|---|
| **Stick with Voice Diary** | Single threshold 0.50. Simpler code but wavering near 0.50 causes false edges |
| **Adopt Meetily pattern** | Onset 0.50, offset 0.35. Smoother endpointing. Requires bypassing VADIterator to get raw probabilities |
| **Adopt Vexa pattern** | Onset 0.60, offset 0.45. Conservative start, good for noisy mics. Same implementation work as Meetily |

---

## Topic 2: How much silence before "speech ended"

### Voice Diary (current)

**500ms** of continuous silence before the VAD declares speech ended.

Example: "I went to the store. [280ms breath] They were out of milk."

With 500ms → ONE utterance. The 280ms breath is shorter than 500ms,
so both sentences merge. Diarization gets one shot at speaker attribution.

### Meetily

**400ms** (called `redemption_time`).

### Vexa

**250ms**.

### OpenOats

~200–300ms (FluidAudio default, estimated from behavior patterns).

### What this means for the user

| min_silence | Effect |
|---|---|
| **500ms** (us) | Long gaps needed. Multi-sentence paragraphs become one utterance. Fewer but longer utterances. Higher latency before text appears. |
| **400ms** | Natural sentence boundary matches most conversational pauses. |
| **250ms** | Eager splitting. Quick back-and-forth conversation captured as separate utterances. More ASR calls but better per-speaker tracking. |

### Decision

| Option | Trade-off |
|---|---|
| 500ms | Less CPU, fewer utterances, higher latency, worse diarization |
| 400ms | Middle ground — matches Meetily |
| 300ms | More utterances, better diarization, slightly more CPU |

---

## Topic 3: How much extra audio around speech edges

### Voice Diary (current)

**200ms** of silence added BEFORE and AFTER detected speech. Total: 400ms.

This padding gives Whisper context to transcribe the first and last words
correctly. Too little → Whisper misses the initial phoneme of the first word.

### Meetily

**300ms** before + **400ms** after. Total: 700ms.

### OpenOats

**512ms** before (2 chunks of 256ms preroll).

### What this means

| Padding | Effect on transcription |
|---|---|
| 200ms (us) | Bare minimum. Edge words sometimes mis-transcribed |
| 350ms | More context. Whispers transcribes edge words more reliably |
| 700ms (Meetily) | Most generous. Best edge-word accuracy, slightly wider timestamps |

### Decision

Cost is negligible (a few thousand extra samples per utterance, no latency
impact — it's pre-buffered, not waited for). Recommend matching Meetily at
350ms each side (700ms total).

---

## Topic 4: Maximum utterance length before force-split

### Voice Diary (current)

**30 seconds** — always. If someone talks continuously for 30s, the buffer
is force-flushed mid-speech and a new utterance starts.

### The problem with 30s when diarization is on

PyAnnote processes the ENTIRE utterance to find speaker changes. A 30-second
utterance could contain:

```
[Speaker A: 8s] [Speaker B: 12s] [Speaker A: 10s]
```

That's 2 speaker changes to find in 30s of audio. Hard problem for the model.

With a **10-second** cap:

```
[Speaker A: 8s] [Speaker B: 2s] → flush → utterance 1 (1 change)
[Speaker B: 10s] → flush → utterance 2 (pure single-speaker)
[Speaker A: 10s] → flush → utterance 3 (pure single-speaker)
```

Easier for PyAnnote. Cleaner embeddings (no cross-speaker mixing).

### What competitors use

| Project | Max segment |
|---|---|
| OpenOats | 5s (local Parakeet) / 10s (cloud Whisper) |
| Vexa | 15s (server-side VAD cap) |
| Meetily | Controlled by Whisper max_len=200 tokens (~15-20s of speech) |

### Decision

| Option | When diarization enabled | When diarization disabled |
|---|---|---|
| 30s always (current) | Poor diarization on multi-speaker segments | Fine — monologues stay as one utterance |
| 10s always | Better diarization | Unnecessary splits on monologues — more ASR calls for no benefit |
| **10s with diarization, 30s without** | Better diarization | Monologues stay intact |

The third option is best but requires the coordinator to know whether
diarization is active. Today it doesn't — it receives the diarization provider
instance but not the config flag saying "this is enabled."

---

## Topic 5: What happens when VAD crashes

### Voice Diary (current)

```python
# vad.py line 186-190
except Exception as exc:
    ...log...
    raise RuntimeError(...) from exc   # ← kills the entire WebSocket
```

If the Silero model produces a NaN, or a CUDA glitch happens, or memory
pressure causes a transient error — the entire recording dies. All buffered
audio is lost. The user must stop and restart.

### All three competitors

| Project | VAD error handling |
|---|---|
| **Meetily** | `warn!("VAD error: {}", e);` — log, skip chunk, continue |
| **Vexa** | Falls back to sending raw audio to Whisper unfiltered |
| **OpenOats** | Catches, logs, `continue` to next chunk |

**Voice Diary is the only project that crashes on VAD error.**

### Decision

| Option | Effect |
|---|---|
| Crash on error (current) | One transient model glitch = lost recording |
| Skip chunk + return silence | Recording continues. If VAD is permanently broken, user notices "no text appearing" and can restart. Far better than losing everything. |

---

## Summary: the four changes

| # | Topic | Current | Target | Why |
|---|---|---|---|---|
| 2.1 | Hysteresis | Single threshold 0.50 | Onset 0.50 / offset 0.35 | Absorbs wavering, fewer false edges |
| 2.2 | min_silence | 500ms | 300ms | Captures sentence boundaries, better diarization |
| 2.3 | speech_pad | 200ms | 350ms | Better edge-word transcription |
| 2.4 | max_utterance | 30s always | 10s with diarization | Cleaner diarization segments |
| 2.5 | VAD resilience | Crash on error | Log + skip chunk | Don't lose the recording |

---

## How to use this guide

1. Pick one topic from the five above
2. Read the current Voice Diary code (file + line numbers are in `docs/vad-learning-plan.md`)
3. Read the competitor patterns below it
4. Decide which approach you want
5. Tell me your decision — I'll implement it

You can go in any order. Topic 2 (min_silence) is the simplest — a one-line config change. Topic 1 (hysteresis) is the most impactful but requires the most code.
