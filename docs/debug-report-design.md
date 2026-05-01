# Voice Diary Debug Session Report — Design Document

## 1. Data Sources (already available from backend + DB)

The report generator receives a **single JSON payload** assembled from:

| Section | Source | Key Fields |
|---|---|---|
| Session meta | `session_repo.get_session()` → `RecordingSession` | `id`, `title`, `started_at`, `ended_at`, `language_hint`, `notes` |
| Utterances | `session_repo.list_utterances()` | `id`, `started_ms`, `ended_ms`, `transcript`, `language`, `confidence`, `source`, `speaker_segment_id`, `speaker_contact_id` |
| Raw audio | Numpy float32 arrays saved per-utterance during recording | Encoded as base64 WAV (16-bit PCM, 16 kHz mono) |
| Speaker segments | `speaker_segments` table JOIN `contacts` | `id`, `embedding` (base64), `diarization_model_id`, `contact_id`, `contact_name`, `status`, `source`, `sim_score` |
| VAD events | Collected during `PipelineCoordinator.process_chunk` | `timestamp_ms`, `is_speech` (boolean) |
| Pipeline errors | `coordinator.on("error", …)` events | `timestamp_ms`, `exception` (string) |
| ASR/diarization/embedding per-utt timings | Instrumentation wrappers on providers | `kind`, `utterance_id`, `duration_ms` |
| Unknown queue | `queue_repo.list_unresolved_with_extras(session_id=…)` | `id`, `speaker_segment_id`, `candidates[]`, `quote`, `fragment_count`, `duration_ms` |
| Config snapshot | `BackendConfig` serialised | All pipeline params, provider model_ids, device, thresholds |

---

## 2. HTML Structure

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Voice Diary Debug — Session {session_id}</title>
  <style>/* all CSS inline */</style>
</head>
<body>
  <header class="report-header">
    <div class="session-id">{session.id}</div>
    <h1>{session.title || "Untitled Session"}</h1>
    <div class="session-meta">
      <span>Started: {started_at}</span>
      <span>Ended: {ended_at}</span>
      <span>Duration: {duration_formatted}</span>
      <span>Language: {language_hint || "auto"}</span>
    </div>
  </header>

  <nav class="section-nav">  <!-- sticky jump-to links -->
    <a href="#summary">Summary</a>
    <a href="#timeline">Timeline</a>
    <a href="#utterances">Utterances</a>
    <a href="#speakers">Speaker Segments</a>
    <a href="#events">Pipeline Events</a>
    <a href="#queue">Unknown Queue</a>
    <a href="#config">Config</a>
  </nav>

  <main>
    <!-- 8. Statistics Summary -->
    <section id="summary" class="collapsible">
      <h2 class="section-toggle" data-target="summary-body">▼ Summary</h2>
      <div id="summary-body" class="section-body">
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-value">{total_utterances}</div>
            <div class="stat-label">Utterances</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{total_words}</div>
            <div class="stat-label">Words</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{avg_utterance_ms}ms</div>
            <div class="stat-label">Avg. Length</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{speech_ratio}%</div>
            <div class="stat-label">Speech Ratio</div>
          </div>
        </div>
        <div class="charts-row">
          <div class="chart-container">
            <h3>Speaker Distribution</h3>
            <div class="css-bar-chart">
              <!-- Pure CSS horizontal bars -->
              <div class="bar-row" style="--width: 55%; --color: #c084fc">
                <span class="bar-label">Contact A</span>
                <span class="bar-fill"></span>
                <span class="bar-value">8 utt.</span>
              </div>
            </div>
          </div>
          <div class="chart-container">
            <h3>Source Split</h3>
            <div class="css-pie" style="--mic-pct: 65; --sys-pct: 35"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- 3. Transcription Timeline -->
    <section id="timeline" class="collapsible">
      <h2 class="section-toggle" data-target="timeline-body">▼ Timeline</h2>
      <div id="timeline-body" class="section-body">
        <div class="timeline-container">
          <div class="timeline-axis" id="timeline-axis"><!-- JS-filled --></div>
          <div class="timeline-tracks" id="timeline-tracks">
            <!-- JS-generated rows per utterance -->
            <!-- Each row: colored stripe spanning ms range + transcript + speaker badge -->
          </div>
        </div>
      </div>
    </section>

    <!-- 4. Utterances (waveforms + transcript) -->
    <section id="utterances" class="collapsible">
      <h2 class="section-toggle" data-target="utterances-body">▼ Utterances ({N})</h2>
      <div id="utterances-body" class="section-body">
        <!-- Card per utterance -->
        <article class="utt-card" id="utt-{id}">
          <div class="utt-card-header">
            <span class="utt-timing">{started_ms}ms – {ended_ms}ms</span>
            <span class="utt-badge source-badge">{source}</span>
            <span class="utt-badge lang-badge">{language}</span>
            <span class="utt-badge conf-badge">{confidence}</span>
            <span class="utt-speaker" style="--speaker-color: {color}">{contact_name}</span>
          </div>
          <div class="utt-waveform">
            <svg viewBox="0 0 800 60" class="waveform-svg">
              <!-- Raw float32 → min/max per pixel column → polyline -->
            </svg>
          </div>
          <blockquote class="utt-transcript">{transcript}</blockquote>
        </article>
      </div>
    </section>

    <!-- 5. Speaker Segments Table -->
    <section id="speakers" class="collapsible collapsed">
      <h2 class="section-toggle" data-target="speakers-body">▶ Speaker Segments ({N})</h2>
      <div id="speakers-body" class="section-body hidden">
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Speaker Label</th>
              <th>Contact</th>
              <th>Status</th>
              <th>Diar. Model</th>
              <th>Sim Score</th>
              <th>Source</th>
              <th>Embedding</th>
            </tr>
          </thead>
          <tbody>
            <!-- Per segment: embedding as collapsed <details> -->
          </tbody>
        </table>
      </div>
    </section>

    <!-- 6. Pipeline Events Log -->
    <section id="events" class="collapsible">
      <h2 class="section-toggle" data-target="events-body">▼ Pipeline Events ({N})</h2>
      <div id="events-body" class="section-body">
        <div class="event-log">
          <!-- Chronological, color-coded by kind -->
          <div class="evt evt-vad">[+1234ms] VAD: speech start</div>
          <div class="evt evt-asr">[+3456ms] ASR: "hello world" (en, 0.97)</div>
          <div class="evt evt-diar">[+3500ms] Diarization: speaker_a (120ms)</div>
          <div class="evt evt-emb">[+3600ms] Embedding: computed in 45ms</div>
          <div class="evt evt-err">[+5000ms] ERROR: diarization unavailable</div>
          <div class="evt evt-vad">[+5678ms] VAD: speech end</div>
        </div>
      </div>
    </section>

    <!-- 7. Unknown Queue Items -->
    <section id="queue" class="collapsible collapsed">
      <h2 class="section-toggle" data-target="queue-body">▶ Unknown Queue ({N})</h2>
      <div id="queue-body" class="section-body hidden">
        <!-- Card per queue item with candidates -->
      </div>
    </section>

    <!-- 8. Configuration Snapshot -->
    <section id="config" class="collapsible collapsed">
      <h2 class="section-toggle" data-target="config-body">▶ Configuration</h2>
      <div id="config-body" class="section-body hidden">
        <pre class="config-json">{JSON.stringify(config, null, 2)}</pre>
      </div>
    </section>
  </main>

  <script>/* all JS inline */</script>
</body>
</html>
```

---

## 3. CSS Approach — Dark "Cursor" Theme

### Colour Palette
| Role | Hex | Usage |
|---|---|---|
| Base background | `#0d0c0b` | Page body |
| Surface panel | `#1a1817` | Cards, tables, log rows |
| Raised surface | `#252321` | Section headers, nav |
| Border subtle | `#33302e` | Dividers, table borders |
| Foreground primary | `#f2f1ed` | Text on dark |
| Foreground muted | `#8a8782` | Secondary text, timestamps |
| Accent blue | `#6cb2eb` | Links, VAD events |
| Accent purple | `#c084fc` | Speaker A (dihlarization label) |
| Accent green | `#4ade80` | Speaker B |
| Accent amber | `#fbbf24` | Speaker C |
| Accent rose | `#fb7185` | Speaker D |
| Accent cyan | `#22d3ee` | System audio source |
| Accent red | `#ef4444` | Errors |
| Warm cream **light sections** | `#f2f1ed` | Light panels (config, tables on cream) |
| Dark code bg | `#1f1e1c` | Code blocks, pre elements |

### Speaker Palette (8 colours, cycled)
```css
--spk-0: #c084fc;  /* purple */
--spk-1: #4ade80;  /* green */
--spk-2: #fbbf24;  /* amber */
--spk-3: #fb7185;  /* rose */
--spk-4: #22d3ee;  /* cyan */
--spk-5: #f472b6;  /* pink */
--spk-6: #a78bfa;  /* violet */
--spk-7: #34d399;  /* emerald */
```

### Key CSS features

1. **CSS Variables** for all colours, spacing, radii
2. **`font-family`**: `"JetBrains Mono", "Berkeley Mono", "Cascadia Code", "Fira Code", monospace`
3. **Collapsible sections** via `.section-body.hidden { display: none }`, toggled by JS
4. **Pure CSS bar chart**: `.bar-fill { width: var(--width); background: var(--color); }`
5. **Pure CSS pie chart**: `<conic-gradient>` background on a circular div with percentage CSS custom properties
6. **Sticky nav**: `position: sticky; top: 0; z-index: 100`
7. **Responsive breakpoints**: single column below 900px
8. **Scrollable timeline** horizontally, utterance cards vertically
9. **Print styles**: `@media print` hides nav, unfurls all collapsibles, uses white bg

### Typography scale
```
--text-xs: 0.6875rem;   /* 11px — monospace data */
--text-sm: 0.8125rem;   /* 13px — secondary labels */
--text-base: 0.9375rem; /* 15px — body, transcripts */
--text-lg: 1.125rem;    /* 18px — section headers */
--text-xl: 1.5rem;      /* 24px — session title */
--text-2xl: 2rem;       /* 32px — stat values */
```

---

## 4. JavaScript — Interactive Features

All JS is vanilla, self-contained in a single `<script>` block.

### 4.1 Collapsible Sections
```js
document.querySelectorAll('.section-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const body = document.getElementById(btn.dataset.target);
    const collapsed = body.classList.toggle('hidden');
    btn.textContent = (collapsed ? '▶' : '▼') + btn.textContent.slice(2);
  });
});
```

### 4.2 Waveform Rendering (SVG)
Audio data arrives as a base64-encoded WAV (or raw float32 packed in base64). The JS:

1. Decodes the base64 to a `Float32Array` via `DataView`
2. Partitions samples into N buckets (N = SVG width = 800)
3. For each bucket computes `min` and `max`
4. Draws `<polyline>` for the upper envelope and `<polyline>` for the lower envelope
5. Fills area between them with semi-transparent accent colour

```js
function renderWaveform(svgElem, float32Data) {
  const W = 800, H = 60;
  const bucketSize = Math.floor(float32Data.length / W);
  const tops = [], bottoms = [];
  for (let i = 0; i < W; i++) {
    const start = i * bucketSize;
    const slice = float32Data.slice(start, start + bucketSize);
    let mx = 0, mn = 0;
    for (let j = 0; j < slice.length; j++) {
      if (slice[j] > mx) mx = slice[j];
      if (slice[j] < mn) mn = slice[j];
    }
    tops.push(`${i},${H/2 - mx * H/2}`);
    bottoms.push(`${i},${H/2 - mn * H/2}`);
  }
  const pointsTop = tops.join(' ');
  const pointsBottom = bottoms.reverse().join(' ');
  svgElem.innerHTML = `
    <polyline points="${pointsTop}" fill="none" stroke="var(--accent)" stroke-width="1"/>
    <polyline points="${pointsBottom}" fill="none" stroke="var(--accent)" stroke-width="1"/>
    <polygon points="${pointsTop} ${pointsBottom}" fill="var(--accent)" opacity="0.15"/>
  `;
}
```

### 4.3 Timeline Rendering
The timeline is a horizontal-scrollable container with:
- A **time axis** at the top (tick marks every N seconds)
- One **row per utterance**, positioned absolutely with `left` and `width` proportional to `started_ms / total_duration_ms` and `duration_ms / total_duration_ms`
- Each bar colour-coded by speaker
- Transcript truncated to fit, shown on :hover via `title` attribute
- Source indicator as a small icon/dot on the bar

```js
function renderTimeline(utterances, totalMs) {
  const container = document.getElementById('timeline-tracks');
  utterances.forEach(u => {
    const left = (u.started_ms / totalMs) * 100;
    const width = Math.max(((u.ended_ms - u.started_ms) / totalMs) * 100, 0.5);
    const color = speakerColor(u.speaker_contact_id);
    const el = document.createElement('div');
    el.className = 'tl-bar';
    el.style.cssText = `left:${left}%;width:${width}%;background:${color}`;
    el.title = `[${u.started_ms}–${u.ended_ms}] ${u.transcript}`;
    el.innerHTML = `<span class="tl-label">${escapeHtml(u.transcript).slice(0, 40)}</span>`;
    container.appendChild(el);
  });
}
```

### 4.4 Embedding Detail Toggle
Embeddings (192–512 floats) are stored as compact `<span>` elements that expand on click:

```js
document.querySelectorAll('.embedding-toggle').forEach(el => {
  el.addEventListener('click', () => {
    el.classList.toggle('expanded');
  });
});
```

CSS: `.embedding-toggle { max-height: 1.2em; overflow: hidden; } .embedding-toggle.expanded { max-height: none; }`

### 4.5 Event Log Filtering
Checkboxes at the top of the event log section toggle visibility per event kind:
```
[✓] VAD  [✓] ASR  [✓] Diarization  [✓] Embedding  [✓] Errors
```

---

## 5. Audio Embedding Strategy

### Option A: Base64 WAV (preferred — playable in `<audio>` tag)

The backend writes a minimal WAV header (44 bytes) + the float32 samples converted to int16 PCM, then base64-encodes the whole buffer.

**WAV header (44 bytes)**:
```
Offset  Size  Description
0       4     "RIFF"
4       4     File size - 8
8       4     "WAVE"
12      4     "fmt "
16      4     16 (PCM)
20      2     1 (PCM format)
22      2     1 (mono)
24      4     16000 (sample rate)
28      4     32000 (byte rate)
32      2     2 (block align)
34      2     16 (bits per sample)
36      4     "data"
40      4     Data size
```

**Python encoder** (in the debug report generator):
```python
import base64, io, struct, numpy as np

def float32_to_wav_base64(audio: np.ndarray, sample_rate: int = 16000) -> str:
    samples = np.asarray(audio, dtype=np.float32)
    # Normalize to [-1, 1] if needed
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak * 0.95
    # Convert to int16
    int_samples = (samples * 32767).astype(np.int16)
    buf = io.BytesIO()
    buf.write(struct.pack('<4sI4s', b'RIFF', 36 + len(int_samples) * 2, b'WAVE'))
    buf.write(struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, 1, sample_rate,
                           sample_rate * 2, 2, 16))
    buf.write(struct.pack('<4sI', b'data', len(int_samples) * 2))
    buf.write(int_samples.tobytes())
    return base64.b64encode(buf.getvalue()).decode('ascii')
```

**In HTML**:
```html
<audio controls src="data:audio/wav;base64,{base64_string}"></audio>
```
and the waveform SVG reads the same bytes:
```js
const raw = atob(base64String);
const view = new DataView(Uint8Array.from(raw, c => c.charCodeAt(0)).buffer);
// Skip 44-byte header
const pcmData = new Int16Array(view.buffer, 44);
const floatData = Float32Array.from(pcmData, v => v / 32768);
renderWaveform(svgEl, floatData);
```

### Option B: Raw Float32 JSON array (compact for short utterances)
```json
"waveform": [0.0012, -0.0034, ...]  // 100-500 floats per short utterance
```
Readable but larger JSON size. Only used when utterance < 200ms (else WAV).

---

## 6. Mockup Description

### Top: Header Bar
```
┌──────────────────────────────────────────────────────────────┐
│  Session: a1b2c3d4-e5f6-...                                  │
│  Board Meeting Notes                      Started: 14:23:05  │
│                                          Ended:   14:45:32   │
│                                          Duration: 22m 27s   │
│                                          Language: en        │
└──────────────────────────────────────────────────────────────┘
```

### Sticky Nav
```
┌────────┬────────┬──────────┬───────────────┬───────┬───────┬────────┐
│Summary │Timeline│Utterances│Speaker Segments│Events │ Queue │ Config │
└────────┴────────┴──────────┴───────────────┴───────┴───────┴────────┘
```

### Summary Section
```
▼ Summary
┌──────────┬──────────┬──────────┬──────────┐
│    42    │   1,247  │   3.2s   │   68%    │
│Utterances│  Words   │Avg Length│Speech %  │
└──────────┴──────────┴──────────┴──────────┘

Speaker Distribution:
  ████████████████████████ 55%  Alice (11 utt.)
  ████████████████ 38%  Bob (8 utt.)
  ████ 7%  Unknown (3 utt.)

Source Split:  ● 65% mic  ● 35% system
```

### Timeline Section (horizontal scroll)
```
▼ Timeline
    0s    5s    10s   15s   20s   25s   30s
────┴──────┴──────┴──────┴──────┴──────┴────
  ████░░░░░░░░│██████████│░░░░│██████████████
  "Good morn…"  "Let's rev…"      "Action items…"
  [Alice/purple]  [Bob/green]       [Alice/purple]
```

### Utterance Card
```
▼ Utterances (42)
┌──────────────────────────────────────────────────────────────┐
│ +1200ms – +4500ms   [mic] [en] [0.97]   ▲ Alice             │
│ ──────────────────────────────────────────────────────────── │
│  ╭╮  ╭╮   ╭──╮   ╭╮  ╭╮   (SVG waveform)                   │
│ ─╯╰──╯╰───╯  ╰───╯╰──╯╰────────────────────────────────── │
│                                                              │
│ "Good morning everyone, let's review the quarterly numbers." │
│                                                              │
│ ▶  [play audio]                                              │
└──────────────────────────────────────────────────────────────┘
```

### Speaker Segments Table (collapsed by default)
```
▶ Speaker Segments (8)
  ┌──────────────────────────────────────────────────────────────────┐
  │ ID       │ Label       │ Contact │ Status  │ Model  │ Embedding  │
  ├──────────┼─────────────┼─────────┼─────────┼────────┼────────────┤
  │ ss-a1b2  │ speaker_a   │ Alice   │ ident.  │pyannote│ ▶ [192]    │
  │ ss-c3d4  │ speaker_b   │ Bob     │ ident.  │pyannote│ ▶ [192]    │
  │ ss-e5f6  │ speaker-0   │ —       │ unknown │pyannote│ ▶ [192]    │
  └──────────────────────────────────────────────────────────────────┘
```

### Pipeline Events Log
```
▼ Pipeline Events (156)
  Filters: [✓] VAD  [✓] ASR  [✓] Diarization  [✓] Embedding  [✓] Errors

  [+   0ms]  VAD        speech start
  [+ 100ms]  VAD        speech continuing…
  [+1200ms]  ASR        "Good morning everyone, let's review…"  (en, 0.97)
  [+1350ms]  Diarize    speaker_a  120ms slice
  [+1400ms]  Embedding  computed in 34ms  (192-dim)
  [+4500ms]  VAD        speech end
  [+4520ms]  ERROR      RuntimeError: diarization model timeout
  [+6789ms]  VAD        speech start
  ...
```

### Unknown Queue (collapsed, only shown if items exist)
```
▶ Unknown Queue (3)
  ┌──────────────────────────────────────────────────────────────────┐
  │ Segment: ss-e5f6  ● speaker-0 (mic)                              │
  │ Quote: "…and then we need to circle back on the vendor…"         │
  │ Fragments: 2  Duration: 8400ms                                   │
  │ Candidates:                                                      │
  │   ○ Alice  0.72                                                  │
  │   ○ Bob    0.68                                                  │
  │   ○ Carol  0.31                                                  │
  └──────────────────────────────────────────────────────────────────┘
```

### Config (collapsed)
```
▶ Configuration
  ┌──────────────────────────────────────────────────────────────────┐
  │ {                                                                │
  │   "pipeline": {                                                  │
  │     "vad_threshold": 0.5,                                        │
  │     "vad_min_silence_ms": 500,                                   │
  │     "vad_speech_pad_ms": 200,                                    │
  │     "vad_min_utterance_ms": 300,                                 │
  │     "vad_max_utterance_ms": 30000,                               │
  │     "speaker_identification_threshold": 0.5,                      │
  │     "chunk_duration_ms": 100,                                    │
  │     "unload_models_after_stop": false                             │
  │   },                                                             │
  │   "providers": {                                                 │
  │     "asr_model_id": "large-v3-turbo",                            │
  │     "diarization_model_id": "pyannote",                          │
  │     "embedding_model_id": "ecapa",                               │
  │     "device": "cuda",                                            │
  │     "preload_on_start": false                                    │
  │   }                                                              │
  │ }                                                                │
  └──────────────────────────────────────────────────────────────────┘
```

---

## 7. Report Data JSON Schema (what backend serialises)

```python
@dataclass
class DebugReportData:
    session: SessionOut
    utterances: list[DebugUtterance]
    speaker_segments: list[DebugSegment]
    vad_events: list[DebugVADEvent]
    pipeline_events: list[DebugPipelineEvent]
    queue_items: list[QueueItemOut]
    config: ConfigOut
    stats: DebugStats

@dataclass
class DebugUtterance:
    id: str
    started_ms: int
    ended_ms: int
    transcript: str
    language: str | None
    confidence: float
    source: str
    speaker_segment_id: str | None
    speaker_contact_id: str | None
    speaker_contact_name: str | None
    # Audio
    waveform_base64: str          # base64 WAV
    waveform_sample_rate: int     # 16000
    waveform_num_samples: int

@dataclass
class DebugSegment:
    id: str
    session_id: str
    contact_id: str | None
    contact_name: str | None
    status: str
    diarization_model_id: str
    sim_score: float
    source: str
    embedding_base64: str          # base64 of raw float32 bytes
    embedding_dim: int
    utterance_ids: list[str]       # utterances linked to this segment

@dataclass
class DebugVADEvent:
    timestamp_ms: int
    is_speech: bool
    note: str                      # "speech start", "speech end", "speech continue"

@dataclass
class DebugPipelineEvent:
    timestamp_ms: int
    kind: str                      # "vad", "asr", "diarization", "embedding", "error"
    utterance_id: str | None
    detail: str                    # human-readable
    duration_ms: int | None        # how long the step took

@dataclass
class DebugStats:
    total_utterances: int
    total_words: int
    total_duration_ms: int
    avg_utterance_ms: float
    speech_ratio: float            # percentage, 0-100
    speaker_distribution: dict[str, int]   # contact_name → utterance count
    source_distribution: dict[str, int]    # "mic" | "system" → count
    silence_count: int
    speech_count: int
```

---

## 8. Implementation Notes

### Backend — New endpoint: `GET /api/sessions/{session_id}/debug-report`
- Queries all data for the session
- Encodes audio as base64 WAV
- Serialises embeddings as base64
- Collects VAD/pipeline events from an in-memory buffer (see below)

### Backend — Event Buffering
The `PipelineCoordinator` currently emits events via callbacks. For debug mode:
1. Add an `_event_log: list[DebugPipelineEvent]` to the coordinator
2. In `process_chunk`, after VAD classification, append a VAD event
3. Instrument `_infer_utterance` with timing (perf_counter before/after each step)
4. In `_emit("error", …)`, also append to the log
5. Expose `get_event_log()` on the coordinator to retrieve it at session end
6. The coordinator instance is per-connection, so the buffer is naturally scoped

### Frontend — Report Generation
- Could be:
  - **Option A**: Backend generates the full HTML in-memory and returns it as `text/html` (self-contained, zero frontend work, `window.open()` the blob)
  - **Option B**: Backend returns JSON, frontend renders with inline React components
- **Recommendation**: Backend generates the full HTML. This is a debug tool, not a user-facing feature, so it doesn't need React/i18n. A Python `html` builder or Jinja2 template that produces the self-contained file is simpler and more portable (can be saved to disk from the Electron app's save dialog).

### File size considerations
- A 22-minute session with 42 utterances (~3s each avg) → ~126s of audio
- 126s × 16000 Hz × 2 bytes (int16) = ~4 MB raw
- Base64-encoded: ~5.3 MB
- Add the rest (JSON, HTML structure): ~5.5 MB total — well within a single-file range

For longer sessions, consider downsampling waveforms for display (1:4 decimation before base64), while keeping the `<audio>` tag playing the full-quality version.
