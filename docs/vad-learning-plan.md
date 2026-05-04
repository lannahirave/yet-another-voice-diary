# Learning Plan: VAD & Utterance Pipeline Refinement

> Start here. Read in order. Take notes. Ask questions.

---

## Step 1 — How audio becomes text (10 min reading)

**File:** `D:\web_app\backend\pipeline\coordinator.py` — lines 555-632

This is the brain. Read `process_chunk()` from top to bottom and answer:

1. What does `vad_segment.is_speech` mean? Where does it come from?
2. What triggers an utterance to be emitted? (hint: line 607-616)
3. What happens if someone talks for 30+ seconds? (hint: line 622-632)
4. What happens if they speak for only 200ms and stop?

---

## Step 2 — How VAD decides "speech" vs "silence" (10 min reading)

**File:** `D:\web_app\backend\pipeline\vad.py` — lines 138-192

This is the ears. Read `process()` and answer:

1. How does Silero's `VADIterator` turn audio into a speech/silence decision?
2. What do `min_silence_duration_ms` (line 124) and `speech_pad_ms` (line 125) do?
3. At line 175-190, what happens when the VAD crashes?
4. Why is there a `_frame_buffer`? Can audio arrive in any size?

---

## Step 3 — The config that controls everything (5 min reading)

**File:** `D:\web_app\backend\config.py` — lines 42-98 (`PipelineConfig`)

These are the knobs. Look at each field and trace it to where it's used:

| Field | Default | Used in | What it does |
|---|---|---|---|
| `vad_threshold` | 0.5 | `vad.py:122` | How sensitive Silero is to speech |
| `vad_min_silence_ms` | 500 | `vad.py:124` | How much silence before "speech ended" |
| `vad_speech_pad_ms` | 200 | `vad.py:125` | Extra audio captured around speech edges |
| `vad_min_utterance_ms` | 300 | `coordinator.py:608` | Shortest utterance we'll keep |
| `vad_max_utterance_ms` | 30000 | `coordinator.py:625` | Longest utterance before force-split |

---

## Step 4 — The wiring (5 min reading)

**File:** `D:\web_app\backend\api\app.py` — lines 87-96

How the coordinator gets built. Note what it receives and what it DOESN'T receive.
Hint: does the coordinator know whether diarization is enabled?

---

## Step 5 — What the competition does differently (reference)

**File:** `D:\web_app\docs\competitor-pipeline-analysis.md` — Section 2 (lines 26-80)

See how Meetily, Vexa, and OpenOats handle VAD. Key differences:
- They use **two thresholds** (one to start speech, a lower one to stop)
- They have **shorter silence gaps** (250-400ms vs our 500ms)
- Meetily wraps **more audio padding** around speech (700ms vs our 400ms)

---

## Step 6 — The four changes (review this doc)

**File:** `D:\web_app\docs\vad-improvement-plan.md`

Now read the detailed analysis for 2.2, 2.3, 2.4, and 2.5. For each:

1. What line of code changes?
2. What number changes from X to Y?
3. Why is Y better than X? (think about what the user would experience)

---

## Step 7 — Your turn: write the change summary

After reading everything, fill this out:

### Change A: min_silence (2.2)
- **File & line:** `config.py:56`
- **From:** `___` → **To:** `___`
- **Why:** ________________________________

### Change B: speech_pad (2.3)
- **File & line:** `config.py:64`
- **From:** `___` → **To:** `___`
- **Why:** ________________________________

### Change C: max utterance for diarization (2.4)
- **Files:** `coordinator.py:622-625` + `config.py:80` + `app.py:96`
- **What the code does today:** ________________
- **What it should do:** ________________
- **Obstacle:** The coordinator doesn't know if diarization is on. How would you solve this?

### Change D: VAD crash resilience (2.5)
- **File:** `vad.py:186-190`
- **What the code does today:** ________________
- **What it should do instead:** ________________

---

## After you answer

Once you've filled out Step 7, I'll show you the actual code changes. Compare your answers to the implementation. Any mismatch is worth discussing — it means there's a design decision to make.
