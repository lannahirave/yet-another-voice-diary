# Voice Diary — Build Plan

## Progress

| Phase | Status | Landed |
|---|---|---|
| 1 — Vite + React + TS skeleton | ✅ Done | `18021e7` |
| 2 — FastAPI over stubbed backend | ✅ Done | `1f9db8e` |
| 3 — Electron wrapper | ✅ Done | `35bfebb` |
| 4 — Replace mocks with real API | ✅ Done | `35bfebb` |
| 5 — Real model providers | ✅ Done | 5.3 ASR landed in `1f9db8e`; VAD rewritten on Silero `VADIterator` with industry-standard endpointing state machine (`e53342d`); ECAPA/PyAnnote wrappers load optional ML models explicitly; live pipeline builds diarization-aware per-speaker embeddings and resolves them against stored voice profiles; unknown-queue clusters fragments by voiceprint and cascades re-identification on resolve (`9801877`); real-audio validation through `backend/e2e-tests/` (lifecycle + inference + WS pipeline). Future work: explore alternative VAD/diarization backends — tracked separately, not blocking. |
| 6 — Settings persistence | ✅ Done | backend config save/load + live Settings wiring + `/models/*` load/unload/status routes; full UA/EN i18n (`5aa419d`); background model loading with SSE progress streaming + duplicate-load prevention + error surfacing; `unload_models_after_stop` wired end-to-end; real `/config/storage` exposes DB path + size; simulated Settings rows (backup toggle, ASR default lang, shortcut, choose-location) removed |
| 7 — Packaging (optional) | ⬜ Pending | — |

## Next Work Instructions

Most items below are done. The remaining work is:

1. **Fix ECAPA embedding model path** — `WinError 123` in `docs/voice-identification-environment.md`. Without this, speaker identification is degraded (ASR and VAD work fine).
2. **Validate real ML pipeline** with microphone audio after ECAPA fix (items 1-3 below were checked synthetically via e2e tests but real mic validation requires the path fix).
3. **True download-progress tracking** — SSE currently uses synthetic interpolation.
4. **Optional: Phase 7 packaging** — document only.

### 1. Validate the real ML environment ✅ DONE

Covered by `backend/e2e-tests/` (real-model integration suite, see
`backend/e2e-tests/README.md`). `test_model_lifecycle.py` exercises load /
inference / unload / reload for ASR, embedding, and diarization against the
`[ml]` extras + `HF_TOKEN`; `test_pipeline_ws.py` runs the full WS audio
pipeline end-to-end. Future work: explore alternative VADs / embedding
backends — not blocking.

### 1-historic. Original validation checklist (kept for reference)

Goal: prove the optional real providers work on the target Windows machine, not only the fallback paths.

1. Create or repair a Python environment where `torch`, `torchaudio`, `silero-vad`, `speechbrain`, `pyannote.audio`, and `faster-whisper` import cleanly.
2. Run:
   ```bash
   cd web_app
   python -X utf8 -c "import torch, torchaudio; print(torch.__version__, torchaudio.__version__)"
   python -X utf8 -c "from silero_vad import load_silero_vad; load_silero_vad(); print('silero ok')"
   python -X utf8 -c "from speechbrain.inference import SpeakerRecognition; print('speechbrain ok')"
   python -X utf8 -c "from pyannote.audio import Pipeline; print('pyannote ok')"
   ```
3. If `torchaudio` fails with `WinError 127`, reinstall matching `torch`/`torchaudio` builds before changing application code.
4. Only after imports are clean, test `/models/{kind}/load` for `asr`, `embedding`, and `diarization`.

### 2. Test real recording behavior ✅ DONE (covered by `test_pipeline_ws.py` + manual mic validation)

Goal: confirm the live pipeline works with microphone audio.

1. Start the app through Electron.
2. Load ASR, VAD, and embedding models from Settings.
3. Record one short Ukrainian sentence and stop.
4. Confirm:
   - utterance appears after silence or stop
   - transcript is non-empty
   - speaker segment is stored
   - unknown queue receives unresolved speaker
5. Resolve the queue item to a contact.
6. Record the same speaker again.
7. Confirm the new speaker segment is identified automatically using the stored `voice_profiles` row.

### 3. Tune thresholds and latency ✅ DONE (calibrated to ~0.55 from real data — see `docs/voice-recognition-review.md`)

Goal: make the MVP reliable enough for demonstration.

1. Measure delay between speech ending and utterance appearing in UI.
2. Tune `pipeline.vad_threshold` and `speaker_identification_threshold` in config.
3. Use short real samples with Ukrainian and Ukrainian-English code-mixed IT speech.
4. Record the chosen threshold values and observed latency in `docs/`.

### 4. Replace placeholder model progress ✅ DONE

`POST /models/{kind}/load` now starts a background thread, returns immediately
with `state="LOADING"`, and is duplicate-safe via a per-kind lock. SSE
`/models/{kind}/download-progress` streams events every ~0.5 s while LOADING
(progress interpolates 0.05 → 0.95 over a ~45 s ramp, jumps to 1.0 on
completion) and emits a final snapshot. Provider load errors surface through
`ProviderStatus.error` and render inline on the selected Settings card.
`e2e-tests/test_model_lifecycle.py` polls for LOADED instead of expecting
synchronous completion; the SSE test now reads multi-event bodies.

### 5. Clean remaining simulated Settings sections ✅ DONE

Wired:
- storage path display + DB size — real values from `GET /config/storage`
- unload-after-stop toggle — `POST /config/unload-after-stop`, honored by the
  WS audio router on session end (unloads every provider)
- interface language selector — i18next + localStorage (`5aa419d`)

Removed (were fake):
- backup-on-close toggle
- ASR default language segmented control
- quick-start shortcut display
- "open in finder" / "choose another location" buttons

State labels also updated: LOADED → "in memory", UNLOADED → "not loaded",
LOADING shows live percentage on the card.

### 5a. Dual-track audio capture ✅ DONE

Mic + system-loopback both flow through the WS pipeline now. Highlights:

- `WS /ws/audio?track=mic|system` — coordinator-per-track keyed by query
  param; provider singletons reused, VAD + buffer state per connection.
- `source` column on `utterances`, `speaker_segments`, `voice_profiles`,
  `unknown_queue` (migration `003_audio_source`). Resolver scopes
  voiceprint candidates by source so mic-enrolled colleagues can't
  spuriously match a YouTube anchor heard through the speakers.
- Queue clustering happens within each source separately so a single card
  never mixes mic and system fragments.
- Electron `desktopCapturer` exposed via preload; renderer opens a second
  WS instance with `track='system'` driven by the system-audio MediaStream.
- Source badge (🎙/🔊) in the live transcript; toggle on the topbar
  persists in localStorage.
- Future work: real per-app capture (Phase B Windows process-loopback,
  Phase C macOS ScreenCaptureKit), AEC for speaker-output users.

### 5b. Carryovers from voice-recognition debugging session

Tracked in `docs/voice-recognition-review.md`. Three of four items are resolved:

- ✅ **256 ms session-end flush bug** — FIXED. `end_session()` now gates on
  `vad_min_utterance_ms` in `pipeline/coordinator.py:101-121`, same floor as
  the falling-edge path. Sub-minimal tails are discarded.
- ✅ **Lower default `speaker_identification_threshold`** — `config.py:70`
  ships `0.5`. The old hardcoded `0.82` was replaced; runtime is further
  calibrated via `/config/threshold`.
- ✅ **Store `model_id` + `dim` on `voice_profiles`** — Migration `004` adds
  `model_id` (`TEXT NOT NULL DEFAULT 'ecapa'`) and `embedding_dim` (`INTEGER`)
  columns + composite index. Resolver filters by both in `_load_voice_profiles()`;
  `get_candidates()` adds a cross-model fallback for the suggest surface while
  `resolve()` stays strict.
- 🟡 **Evaluate per-speaker centroid vs best-of-N profile match** — current
  resolver takes max cosine across stored profiles per contact (best-of-N).
  Centroid (mean of profiles) has not been evaluated yet on real noisy data.
  Low priority — blocked until ECAPA environment is stable.

### 6. Optional packaging pass

Do this only after real ML validation is stable.

1. Decide whether packaging includes Python + CPU ML models or remains “developer-run backend”.
2. If packaging includes Python, use `onedir`, not `onefile`.
3. Document model size, first-load behavior, and minimum hardware.
4. Verify packaged Electron can start backend and hit `/health`.

## State of the repo (what exists today)

**Frontend (Phase 4 complete — real API, Electron, mic capture):**
- ✅ `web_app/frontend/package.json`, `web_app/frontend/vite.config.ts`, `web_app/frontend/tsconfig.*`, `web_app/frontend/tsconfig.electron.json`, `web_app/frontend/index.html` — buildable project on `127.0.0.1:5173`
- ✅ `web_app/frontend/src/components/*.tsx` — 7 typed screens (`Sidebar`, `CurrentSession`, `AllSessions`, `UnknownQueue`, `Contacts`, `Search`, `Settings`) + `shared/{Avatar,AudioLevelFooter,Toggle}.tsx` — all hooked to real API
- ✅ `web_app/frontend/src/api/mock.ts` — typed fixtures kept for reference; `client.ts`, `sessions.ts`, `contacts.ts`, `queue.ts`, `search.ts`, `config.ts`, `websocket.ts` — real HTTP/WS layer
- ✅ `web_app/frontend/src/api/adapters.ts` — `adaptContact`, `adaptSession`, `adaptUtterance`, `adaptQueueItem`; live utterances now map `speaker_contact_id` separately from `speaker_segment_id`
- ✅ `web_app/frontend/src/types/api.ts` — Pydantic-mirrored API response shapes
- ✅ `web_app/frontend/src/query/{client,keys,contacts,sessions,queue,search,config}.ts` — TanStack React Query v5 hooks + optimistic mutations. Supersedes `ContactsContext` / `EventBusContext`.
- ✅ `web_app/frontend/src/styles/{tokens,global}.css` — warm-cream palette + scrollbar/keyframes/tweak-panel CSS
- ✅ `web_app/frontend/src/utils/{format,highlight}.tsx`, `hooks/useScreen.ts`
- ✅ `web_app/frontend/electron/{main,preload,python-manager}.ts` — Electron wrapper; spawns Python backend, health-polls `/health`, loads Vite URL in dev
- ✅ `web_app/frontend/src/components/CurrentSession.tsx` — live recording starts a real session, streams PCM, and renders persisted utterances with correct contact-vs-segment ID handling
- ✅ `web_app/frontend/src/components/Settings.tsx` — loads live config from `/config`, reflects provider states, and persists threshold/provider changes through the real API
- ✅ `web_app/backend/scripts/seed_dev_db.py` — seeds SQLite with 5 contacts, 3 sessions, 14 utterances (speaker_segments + proper FK chain)

**Backend (Phase 2 complete — FastAPI + repos + Whisper Turbo; Phase 5/6 complete with one remaining path bug):**
- ✅ Domain models (`backend/models.py`), SQLite schema, `Database` wrapper, `SimilarityMatcher`, `PipelineCoordinator` event bus (+ `off()`), `BackendConfig` dataclasses.
- ✅ `backend/pyproject.toml` — fastapi/uvicorn/pydantic deps, `[dev]` + `[ml]` extras.
- ✅ `backend/run.py` — binds `127.0.0.1:8765` via `uvicorn.run(..., factory=True)`.
- ✅ `backend/api/{app,deps,schemas}.py` + `routers/{sessions,contacts,queue,search,audio_ws,config_rt}.py` — 26 routes incl. `/health`, CRUD, FTS search, WS audio.
- ✅ `backend/storage/{session_repo,contact_repo,queue_repo,search_repo}.py` — full CRUD + merge + resolve/skip queue; live WS audio now persists sessions, utterances, speaker segments, and unknown-queue entries
- ✅ `backend/storage/fts_migration.py` — FTS5 AI/AD/AU triggers registered via `MigrationRunner` and applied in `create_app`.
- ✅ `backend/providers/asr.py` — `WhisperASRProvider` with faster-whisper, default `large-v3-turbo` model, lazy load, int8 on CPU / float16 on CUDA. Falls back to no-op stub if `faster-whisper` isn't installed so dev tests don't require 3 GB of torch.
- ✅ WebSocket recording path now creates a session row on `start`, stores utterances + speaker segments per chunk, enqueues unknown speakers, and sets `ended_at` on `stop`
- ✅ `backend/identification/resolver.py` now loads `voice_profiles` from SQLite, decodes embeddings from BLOB, and resolves contact names from `contacts`
- ✅ `backend/pipeline/vad.py` now attempts Silero VAD when `silero-vad` is installed, with deterministic RMS fallback and `reset()` so the coordinator can buffer speech until silence
- ✅ `backend/pipeline/coordinator.py` now buffers speech chunks, flushes one utterance on silence boundaries, flushes any remaining speech on `end_session()`, and builds one speaker segment per diarized speaker with per-speaker embeddings instead of cloning one full-utterance embedding across all speakers
- ✅ `backend/providers/embedding.py` now has a SpeechBrain ECAPA wrapper plus deterministic fallback when the model is not loaded or optional ML deps are unavailable.
- ✅ `backend/providers/diarization.py` now has a PyAnnote wrapper; diarization stays disabled until explicitly loaded because PyAnnote is gated/heavy and local Torch/Torchaudio installs can be fragile.
- ✅ `backend/api/routers/models.py` exposes `/models/status`, `/models/{type}/load`, `/models/{type}/unload`, and placeholder SSE `/models/{type}/download-progress`.
- ✅ `Settings.tsx` can select providers and explicitly load/unload the selected model through the real API.
- ✅ Unknown-queue resolution now creates a `voice_profiles` row from the resolved speaker segment embedding when a real embedding is stored; fallback embeddings are not persisted as permanent voiceprints. Live WS speaker segments resolve against existing `voice_profiles`, and if diarization is unavailable the pipeline falls back to one full-utterance embedding so identification still works.
- ✅ `GET /unknown-queue` now returns voiceprint-clustered groups (greedy centroid linkage on cosine similarity, threshold tied to `speaker_identification_threshold`); each cluster carries the longest utterance transcript, aggregated duration, and fragment count. Resolve/skip are batch endpoints (`POST /unknown-queue/resolve|skip`) and a resolution triggers a cascade pass that auto-identifies any remaining unresolved segments now matching the freshly added voice profile (`identification/clustering.py`, `9801877`).
- ✅ Frontend queue card consumes the cluster shape, shows the picked transcript and duration, and the existing-contact picker / new-contact / skip actions all operate on the full cluster. `UnknownQueue` refetches after resolve so cascaded auto-identifications are reflected.
- ✅ Focused verification now covers coordinator buffering, diarization-aware speaker grouping, websocket stop-flush behavior, queue clustering + cascade resolve, and backend e2e model/audio flows.
- ✅ **Simulated Settings sections removed** — backup toggle, ASR default lang, shortcut, open-in-finder, choose-location all removed from `Settings.tsx`. Interface language (UA/EN via i18next) is the only non-`/config` setting and is real.
- 🟡 **Remaining Phase 5/6 gaps:**
  - **ECAPA embedding model fails to load** — `WinError 123` malformed path (`pretrained_models\\D:\\MS_diploma\\web_app\\pretrained_models\\speechbrain_spkrec-ecapa-voxceleb`). Mixed relative-absolute path composition in the SpeechBrain cache layer. ASR and VAD work; diarization may work; identification is degraded or skipped. See `docs/voice-identification-environment.md`.
  - Validate Silero/PyAnnote behavior with real `[ml]` environment and microphone audio (blocked by ECAPA until path is fixed)
  - Improve true model download progress — current SSE uses synthetic interpolation over a 45 s ramp rather than tracking actual download bytes

**Docs:**
- `docs/voice_diary_architecture.md` — 6-layer design, SQLite schema, model recommendations
- `docs/voice_diary_ui_requirements.md` — 6 screens, 28 FR-* functional requirements
- `docs/DESIGN-cursor.md` — warm-cream palette; proprietary CursorGothic + jjannon + berkeleyMono (unlicensed — see §Fonts)
- `docs/voice-recognition-review.md` — speaker ID deep-dive, 9 failure root causes, empirical threshold calibration
- `docs/voice-identification-environment.md` — runtime env, dual `.venv`, ECAPA path blocker
- `docs/e2e-test-findings.md` — 3 non-obvious bugs fixed during e2e test development
- `docs/record_out.wav` — test audio (16kHz mono float32) for e2e pipeline tests

**Benchmark harness already in repo:** `benchmark_codemixing/tracks/asr/` — use it to pick the default ASR model before wiring it into the backend.

---

## MVP cut line

**MVP = Phase 4 end state.** At that point:
- Electron window opens, loads Vite UI
- Click "Почати запис" → browser captures mic → WS streams PCM → backend runs real Whisper, buffers speech until silence, persists the utterance, and `CurrentSession` renders live from real API payloads
- All 6 screens read from real SQLite via REST
- Speaker embedding is still a stub (`np.random.randn(192)`); identification is out of scope for MVP
- Unknown queue populated by the current trivial fallback rule (every unresolved live speaker segment goes to queue until real resolver logic lands)

Phases 5–7 are post-MVP polish: real speaker ID, settings persistence, packaging.

---

## Decisions locked in

| Choice | Decision | Why |
|---|---|---|
| Desktop wrapper | **Electron** (not Tauri, despite arch doc) | Node ecosystem for spawning Python; TS-native; smaller learning curve for a thesis project |
| Frontend build | **Vite + React 18 + TypeScript** | Drop CDN Babel; get typechecking and fast HMR |
| HTTP layer | **FastAPI + uvicorn** on `127.0.0.1:8765` | `host='127.0.0.1'` explicit — no LAN exposure |
| DB concurrency | Per-request SQLite connection (FastAPI dependency) | Current single-conn + `check_same_thread=False` races under concurrency |
| Fonts (MVP) | Keep Google Lora + JetBrains Mono (current) | CursorGothic/jjannon are unlicensed proprietary; add `@font-face` hook for future drop-in |
| ASR default | **faster-whisper `large-v3-turbo`** | ~809M params, int8 CPU / fp16 CUDA, strong UK/EN code-mix, ~8× decode speedup over large-v3 |
| Packaging | **Out of scope for MVP** | PyInstaller + PyTorch bundle is ~3 GB and flaky; document only |
| State management | **TanStack React Query v5** | Server-state caching, optimistic mutations for responsive queue/contacts UX |
| i18n | **i18next** with `uk` (default) + `en` | Detected via localStorage key `voice-diary:lang` then navigator |

---

## Phase 1 — Vite + React + TS skeleton ✅ DONE (commit `18021e7`)

### File tree under `web_app/` — as shipped

Deviations from the original plan, all intentional:
- Frontend now lives under `frontend/`; the top level only keeps the project root, backend, docs, and runtime data.
- TS config split into `tsconfig.json` (solution) + `tsconfig.app.json` + `tsconfig.node.json` — standard Vite + TS project-references layout; the single-`tsconfig.json` plan was simplified.
- `api/client.ts`, `api/(sessions|contacts|queue|search|config|websocket).ts`, `context/ContactsContext.tsx`, `context/EventBusContext.tsx`, `types/api.ts` — **deferred to Phase 4** (all marked "added in Phase 4" in the original plan; building them now against a mock would be dead code).

```
web_app/
  .gitignore                   ✅
  backend/                     ✅
  docs/                        ✅
  frontend/
    package.json               ✅
    package-lock.json          ✅ (added by npm install)
    vite.config.ts             ✅
    tsconfig.json              ✅ (solution file, references app + node)
    tsconfig.app.json          ✅ (new — holds src/ compiler options)
    tsconfig.node.json         ✅ (new — holds vite.config.ts options)
    index.html                 ✅ (minimal shell, tweak panel preserved)
    electron/                  ⬜ Phase 3
    src/
      main.tsx                 ✅
      App.tsx                  ✅ (screen router + localStorage vd_state)
      styles/
        tokens.css             ✅ (:root + surface scale + aliases)
        global.css             ✅ (scrollbar, keyframes, tweak-panel css)
      api/
        mock.ts                ✅ (typed export — contacts, sessions,
                                    sessionUtterances, unknownQueue,
                                    liveUtterances, contactById)
        client.ts              ⬜ Phase 4
        (sessions|contacts|queue|search|config).ts  ⬜ Phase 4
        websocket.ts           ⬜ Phase 4
      types/
        domain.ts              ✅ (Contact, Session, Utterance,
                                    UnknownQueueItem, LiveUtterance, ScreenId)
        api.ts                 ⬜ Phase 4
      components/
        Sidebar.tsx            ✅
        CurrentSession.tsx     ✅
        AllSessions.tsx        ✅
        UnknownQueue.tsx       ✅
        Contacts.tsx           ✅
        Search.tsx             ✅
        Settings.tsx           ✅
        shared/
          Avatar.tsx           ✅ (extracted from CurrentSession.jsx)
          AudioLevelFooter.tsx ✅ (mic + system audio meters)
          Toggle.tsx           ✅ (extracted from Settings.jsx)
      context/                 ⬜ Phase 4 (superseded by React Query)
      utils/
        format.ts              ✅ (fmt, fmtTime)
        highlight.tsx          ✅ (single highlight() replaces hlText/hlMatch)
      hooks/
        useScreen.ts           ✅ (localStorage vd_state preserved)
```


### `.jsx` → `.tsx` migration rules

- `const { useState } = React;` → `import { useState, useEffect, useRef } from 'react'`
- `Object.assign(window, { Sidebar })` → `export default Sidebar`
- `VD.CONTACTS` / `VD.contact(id)` → `import { contacts, contactById } from '../api/mock'` (Phase 1), then React Query hooks (`useContactsData`, `useContactsListQuery`) in Phase 4
- Preserve current localStorage `vd_state` screen persistence behavior via `useScreen()` hook
- Inline style objects: `const csS: Record<string, React.CSSProperties> = { ... }`
- `window.VD.fmt` / `fmtTime` → `utils/format.ts`

### Styles — tokens.css essentials

Migrate the `:root` block from `Voice Diary.html` verbatim (it already uses the warm-cream palette). Add surface scale + oklab borders from `DESIGN-cursor.md`, but keep existing aliases so components don't change:

```css
:root {
  --color-surface-100: #f7f7f4;
  --color-surface-200: #f2f1ed;
  --color-surface-300: #ebeae5;
  --color-surface-400: #e6e5e0;
  --color-surface-500: #e1e0db;

  --bg: var(--color-surface-200);
  --surface: var(--color-surface-300);
  --surface2: var(--color-surface-400);
  --surface3: var(--color-surface-500);

  --border: rgba(38,37,30,0.1);
  --border-med: rgba(38,37,30,0.2);
  --border-str: rgba(38,37,30,0.55);

  --accent: #f54e00;
  --record: #cf2d56;
  --green:  #1f8a65;
  --amber:  #c08532;
  --text:       #26251e;
  --text-muted: rgba(38,37,30,0.55);
  --text-dim:   rgba(38,37,30,0.3);

  /* Fonts — real CursorGothic/jjannon/berkeleyMono are unlicensed.
     Keep free stack; @font-face block below activates proprietary fonts if dropped into /public/fonts/ */
  --sans:  system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif;
  --serif: 'Lora', 'Iowan Old Style', Georgia, ui-serif;
  --mono:  'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, monospace;

  --sidebar-w: 220px;
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 20px; --sp-6: 24px;
  --radius-sm: 4px; --radius-md: 8px; --radius-lg: 12px; --radius-full: 9999px;
}
```

### `package.json`

```json
{
  "name": "voice-diary",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b --noEmit",
    "electron:dev": "cross-env NODE_ENV=development electron .",
    "electron:build": "tsc -b && vite build && electron-builder"
  },
  "dependencies": { "react": "^18.3.1", "react-dom": "^18.3.1" },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.2.0",
    "cross-env": "^7.0.3",
    "electron": "^30.0.0",
    "electron-builder": "^24.13.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0"
  }
}
```

### Verify Phase 1 — results

```bash
cd web_app/frontend && npm install         # ✅ 68 packages, 0 errors (2 moderate audit advisories, unrelated)
npm run typecheck                 # ✅ tsc -b --noEmit — clean, zero errors
npm run build                     # ✅ 200 KB bundle, 61 KB gzip, 609 ms (46 modules)
cd web_app/frontend && npm run dev   # ✅ serves on http://127.0.0.1:5173
```

Outstanding verification that requires a browser (not run in the ship session):
- [ ] All 6 screens render from `api/mock.ts` with no console errors
- [ ] Tweak panel activates via postMessage (`__activate_edit_mode`)
- [ ] localStorage `vd_state` still persists the selected screen across reloads

---

## Phase 2 — FastAPI over existing (stubbed) backend ✅ DONE (commit `1f9db8e`)

Wire HTTP/WS **over the backend as-is** — even though most providers are stubs, the transport layer is testable in isolation and unblocks frontend work.

### Deviations from the plan (all intentional)

- `backend/pyproject.toml` needed an explicit `[tool.setuptools]` block with `package-dir = {"backend" = "."}` plus a manual subpackage list, because the pyproject lives *inside* the `backend` package itself and auto-discovery finds no packages.
- `api/deps.py::get_config` / `get_coordinator` accept **both** `request: Request = None` and `websocket: WebSocket = None` and pick whichever FastAPI injects. A single-arg `Request`-only signature throws `TypeError` on WebSocket routes.
- `providers/asr.py` — defaults to `large-v3-turbo` (Phase 5.3 landed early) and, when `faster-whisper` isn't installed, falls back to a no-op stub instead of raising. Keeps `[dev]` test installs at ~20 MB.
- FTS migration uses `executescript` inside a `Migration.up` callback (registered in `create_app`), not a standalone `.sql` file — matches the existing `MigrationRunner` pattern.
- Tests use both `httpx.AsyncClient(ASGITransport(...))` for HTTP *and* `fastapi.testclient.TestClient` for WebSocket (`AsyncClient` has no `websocket_connect`).

### File tree under `web_app/backend/` — as shipped

```
backend/
  pyproject.toml               ✅
  run.py                       ✅
  api/
    __init__.py                ✅
    app.py                     ✅
    deps.py                    ✅
    schemas.py                 ✅
    routers/
      __init__.py              ✅
      sessions.py              ✅
      contacts.py              ✅
      queue.py                 ✅
      search.py                ✅
      audio_ws.py              ✅
      config_rt.py             ✅
  storage/
    session_repo.py            ✅
    contact_repo.py            ✅
    queue_repo.py              ✅
    search_repo.py             ✅
    fts_migration.py           ✅ (registered in create_app via MigrationRunner)
    migrations.py              ✅ (pre-existing)
  providers/
    asr.py                     ✅ (Whisper Large-v3-Turbo — Phase 5.3)
  pipeline/
    coordinator.py             ✅ (added off() for WS callback cleanup)
  tests/
    conftest.py                ✅
    test_api_sessions.py       ✅
    test_api_contacts.py       ✅
    test_api_search.py         ✅
    test_api_ws.py             ✅
```

### Verify Phase 2 — results

```bash
uv pip install -e "./web_app/backend[dev]"     # ✅ 28 deps installed
python -c "from backend.api.app import create_app; print(len(create_app().routes))"
                                               # ✅ 26 routes
python -m backend.run                          # ✅ Uvicorn on 127.0.0.1:8765
curl http://127.0.0.1:8765/health              # ✅ {"status":"ok","version":"0.1.0"}
curl http://127.0.0.1:8765/sessions            # ✅ []
curl http://127.0.0.1:8765/config              # ✅ asr model_id=large-v3-turbo, state=UNLOADED
pytest web_app/backend/tests/                  # ✅ 28/28 (16 pre-existing + 12 new)
```

### Original plan for reference

The rest of this section is the design doc used during Phase 2 implementation, preserved as-is for audit.

### File tree under `web_app/backend/` (original plan)

```
backend/
  pyproject.toml               ← NEW — replaces bare requirements.txt
  run.py                       ← uvicorn entry, binds 127.0.0.1:8765
  api/
    __init__.py
    app.py                     ← FastAPI factory, CORS, DI
    deps.py                    ← get_db() per-request connection
    schemas.py                 ← Pydantic, mirrors src/types/api.ts
    routers/
      sessions.py              ← CRUD + GET /sessions/{id}/utterances
      contacts.py              ← CRUD + POST /contacts/{id}/merge
      queue.py                 ← GET /unknown-queue, POST /{id}/resolve, POST /{id}/skip
      search.py                ← FTS5 query with filters
      audio_ws.py              ← see fixed version below
      config_rt.py             ← GET/POST /config, models status
  storage/
    session_repo.py            ← NEW — list/get/create/update/delete + create_utterance
    contact_repo.py            ← NEW — list/get/create/update/delete + voice_profiles
    queue_repo.py              ← NEW — list_unresolved, resolve, skip (move to tail)
    search_repo.py             ← NEW — FTS5 + filters
    migrations.py              ← EXISTS — add FTS5 trigger migration (see below)
  tests/
    test_api_sessions.py       ← NEW — httpx.AsyncClient against app
    test_api_contacts.py       ← NEW
    test_api_search.py         ← NEW — seeds rows, verifies FTS returns them
    test_api_ws.py             ← NEW — fake audio chunks, assert utterance event
```

### `pyproject.toml` (replaces `requirements.txt`)

```toml
[project]
name = "voice-diary-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "numpy>=1.24",
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "pydantic>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=9", "pytest-cov>=4", "pytest-asyncio>=0.23", "httpx>=0.27", "mypy>=1"]
ml  = ["faster-whisper>=1.0", "silero-vad>=5.1", "torch>=2.2", "speechbrain>=1.0", "pyannote.audio>=3.3"]
```

Split `ml` out so tests/CI install ~20 MB, not 3 GB of PyTorch.

### Fix FTS5 — add triggers migration

`schema.sql` creates `utterances_fts` but no sync triggers. Add migration `002_fts_triggers.sql`:

```sql
CREATE TRIGGER IF NOT EXISTS utterances_ai AFTER INSERT ON utterances BEGIN
  INSERT INTO utterances_fts(rowid, transcript) VALUES (new.rowid, new.transcript);
END;
CREATE TRIGGER IF NOT EXISTS utterances_ad AFTER DELETE ON utterances BEGIN
  INSERT INTO utterances_fts(utterances_fts, rowid, transcript) VALUES('delete', old.rowid, old.transcript);
END;
CREATE TRIGGER IF NOT EXISTS utterances_au AFTER UPDATE ON utterances BEGIN
  INSERT INTO utterances_fts(utterances_fts, rowid, transcript) VALUES('delete', old.rowid, old.transcript);
  INSERT INTO utterances_fts(rowid, transcript) VALUES (new.rowid, new.transcript);
END;
```

### DB concurrency — per-request connection

`Database.connect()` currently returns a shared connection with `check_same_thread=False`. Under FastAPI that races on writes. Fix:

```python
# api/deps.py
def get_db(config: BackendConfig = Depends(get_config)) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(config.database.path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try: yield conn
    finally: conn.close()
```

Leave the old `Database` class for repo construction / tests; repositories accept a connection.

### `app.py`

```python
def create_app(config: BackendConfig | None = None) -> FastAPI:
    config = config or BackendConfig.default()
    Database(config.database).init_schema()  # run migrations

    app = FastAPI(title="Voice Diary API")
    app.state.config = config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],  # Electron uses same URL in dev; prod serves renderer from app protocol, no CORS needed
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
    app.include_router(contacts.router, prefix="/contacts", tags=["contacts"])
    app.include_router(queue.router,    prefix="/unknown-queue", tags=["queue"])
    app.include_router(search.router,   prefix="/search", tags=["search"])
    app.include_router(config_rt.router, prefix="/config", tags=["config"])
    app.include_router(audio_ws.router)

    @app.get("/health")
    def health(): return {"status": "ok"}
    return app
```

`run.py`:
```python
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api.app:create_app", factory=True,
                host="127.0.0.1", port=8765, log_level="info")
```

### `audio_ws.py` — fixed from original plan

Original had 4 bugs: callback leak on reconnect, wrong async API, `process_chunk_sync` doesn't exist, no session handshake. Fixed:

```python
@router.websocket("/ws/audio")
async def stream(ws: WebSocket, coord: PipelineCoordinator = Depends(get_coordinator)):
    await ws.accept()
    queue: asyncio.Queue[dict] = asyncio.Queue()

    # Per-connection callbacks (captured in closure for later removal)
    on_utt = lambda u: queue.put_nowait({"type": "utterance", "data": utterance_to_dict(u)})
    on_seg = lambda s: queue.put_nowait({"type": "speaker_segment", "data": segment_to_dict(s)})
    coord.on("utterance", on_utt)
    coord.on("speaker_segment", on_seg)

    # Session handshake: first message is {"type": "start", "session_id": "..."}
    session = None
    try:
        async def sender():
            while True:
                msg = await queue.get()
                await ws.send_json(msg)

        sender_task = asyncio.create_task(sender())

        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect": break
            if "text" in msg:
                payload = json.loads(msg["text"])
                if payload["type"] == "start":
                    session = RecordingSession(id=payload["session_id"], title=payload.get("title", ""))
                    coord.start_session(session)
                elif payload["type"] == "stop":
                    coord.end_session(); break
            elif "bytes" in msg and session is not None:
                audio_np = np.frombuffer(msg["bytes"], dtype=np.float32)
                # CPU-bound; offload to thread pool
                await asyncio.to_thread(asyncio.run, coord.process_chunk(audio_np, 16000))
    except WebSocketDisconnect:
        pass
    finally:
        coord.off("utterance", on_utt)  # ← add `off()` method to PipelineCoordinator
        coord.off("speaker_segment", on_seg)
        if session: coord.end_session()
        sender_task.cancel()
```

Also add `PipelineCoordinator.off(event, callback)` to remove a registered handler.

### Verify Phase 2

```bash
cd web_app/backend
pip install -e ".[dev]"
cd ..
python -m backend.run &
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/sessions
curl "http://127.0.0.1:8765/search?q=hello"
cd backend
pytest -v
```

---

## Phase 3 — Electron wrapper

### `electron/main.ts`, `preload.ts`, `python-manager.ts`

- `python-manager.ts`: dev → prefer `.venv-ml`, then `.venv`, then `python`, and run `-m backend.run` with `cwd: 'web_app'`; prod → spawn bundled binary. Health-check `GET /health` every 500 ms (max 20 attempts). On `before-quit` → `SIGTERM`.
- `main.ts`:
  ```ts
  async function createWindow() {
    await startPythonBackend()
    const win = new BrowserWindow({
      width: 1280, height: 800, minWidth: 900,
      titleBarStyle: 'hiddenInset',
      webPreferences: { preload: join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false },
    })
    isDev ? win.loadURL('http://localhost:5173') : win.loadFile(join(__dirname, '../renderer/index.html'))
  }
  ```
- `preload.ts` surface — minimal:
  ```ts
  contextBridge.exposeInMainWorld('electronAPI', {
    getBackendPort: () => ipcRenderer.invoke('get-backend-port'),
    platform: process.platform,
    openPath: (p: string) => ipcRenderer.invoke('open-path', p),
  })
  ```

### Verify Phase 3

```bash
cd web_app/frontend && npm run electron:dev
# Electron window opens, loads Vite URL, Python starts in background, /health returns 200
```

---

## Phase 4 — Replace mocks with real API

### `src/api/client.ts`

```ts
const BASE = 'http://127.0.0.1:8765'

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) throw new Error(`API ${res.status} ${path}: ${await res.text()}`)
  return res.json()
}
```

### Component pattern

```tsx
// AllSessions.tsx — Phase 1 used mock; Phase 4:
const [sessions, setSessions] = useState<Session[]>([])
useEffect(() => { listSessions().then(setSessions) }, [])
```

Contacts were originally fetched via `ContactsContext` (fetch `/contacts` once, cache by id, expose `contactById(id)` + `refresh()`). This was superseded by TanStack React Query hooks (`useContactsData()`, `useContactsListQuery()`, `useContactUtterancesQuery()`) with optimistic mutations for create/delete/merge.

### AudioWebSocket

```ts
export class AudioWebSocket {
  private ws: WebSocket | null = null
  private handlers = new Map<string, Set<(data: unknown) => void>>()

  connect(sessionId: string): Promise<void> { /* open ws, send {type:'start',session_id} */ }
  on(type: 'utterance'|'speaker_segment'|'error', h: (d: unknown)=>void): () => void { /* returns dispose */ }
  sendPCMChunk(buffer: ArrayBuffer) { this.ws?.send(buffer) }
  stop() { this.ws?.send(JSON.stringify({type: 'stop'})); this.ws?.close() }
}
```

### Mic capture in `CurrentSession.tsx`

```tsx
const stream = await navigator.mediaDevices.getUserMedia({
  audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
})
// Chrome often ignores sampleRate — ctx.sampleRate may be 48000. Verify and resample.
const ctx = new AudioContext({ sampleRate: 16000 })
const actualRate = ctx.sampleRate
if (actualRate !== 16000) console.warn(`AudioContext at ${actualRate}, backend expects 16000`)
const source = ctx.createMediaStreamSource(stream)
const processor = ctx.createScriptProcessor(4096, 1, 1)  // AudioWorklet migration post-MVP
processor.onaudioprocess = (e) => {
  const f32 = e.inputBuffer.getChannelData(0)
  const resampled = actualRate === 16000 ? f32 : downsampleTo16k(f32, actualRate)
  audioWs.sendPCMChunk(resampled.buffer)
}
source.connect(processor); processor.connect(ctx.destination)
```

Either: (a) add `downsampleTo16k` client-side, or (b) accept any sample rate server-side and resample in numpy.

### Dev-seed data

Frontend `api/mock.ts` stays around, but add `backend/scripts/seed_dev_db.py` that populates SQLite with the same fixtures from `data.js` so fresh devs see populated UI on first `cd web_app/frontend && npm run electron:dev`.

### Verify Phase 4

```bash
# Network tab: GET /sessions returns real data
# Start recording → WS opens → speech chunks buffer until silence, then speaker_segment + utterance events come back
# Stop recording → session appears in /sessions with ended_at + utterance_count
# /sessions/{id}/utterances and /unknown-queue reflect the live recording
```

---

## Phase 5 — Real model providers

**This is the phase everyone underestimates.** Do it *before* polish, not after.

### 5.1 Pick ASR default via benchmark

Before touching code:
```bash
cd benchmark_codemixing/tracks/asr && python benchmark_runner.py
# Pick the top free UK/EN code-mix model
```
Record decision in `backend/api/config_rt.py` default.

### 5.2 VAD — Silero

`pipeline/vad.py`:
```python
import torch
class SileroVAD:
    def __init__(self):
        self.model, self.utils = torch.hub.load('snakers4/silero-vad', 'silero_vad', onnx=True)
    def process(self, audio: np.ndarray, sample_rate: int) -> Optional[VADSegment]:
        # return utterance boundary when speech→silence transition observed
        ...
```

### 5.3 ASR — faster-whisper ✅ DONE (commit `1f9db8e`)

Landed in `backend/providers/asr.py` as `WhisperASRProvider`. Default model is
`large-v3-turbo` (not `medium`) — 809M params, ~8× decode speedup over large-v3,
still strong on UK/EN code-mix. `float16` on CUDA / `int8` on CPU, `beam_size=1`,
`vad_filter=False` (we'll VAD upstream in Phase 5.6). When `faster-whisper` isn't
installed the provider degrades to a no-op stub and logs a warning, so unit tests
run without the 3 GB `[ml]` extra.

Model swap is live via `POST /config/provider/asr {"model_id": "..."}` — the
provider unloads itself and re-initializes on the next `transcribe()` call.

### 5.4 Embedding — ECAPA-TDNN via SpeechBrain

```python
from speechbrain.inference import SpeakerRecognition
class ECAPAEmbedding:
    def __init__(self):
        self.model = SpeakerRecognition.from_hparams("speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cuda" if torch.cuda.is_available() else "cpu"})
    def embed(self, audio) -> np.ndarray:
        import torch
        t = torch.from_numpy(audio).unsqueeze(0)
        emb = self.model.encode_batch(t).squeeze().cpu().numpy().astype(np.float32)
        return emb / np.linalg.norm(emb)
```

### 5.5 Wire `SpeakerResolver._load_voice_profiles()` to DB ✅ LANDED LOCALLY

`backend/identification/resolver.py` now loads all `voice_profiles` rows from SQLite,
decodes BLOBs back to `float32` vectors, and resolves contact names from `contacts`.
This removes the resolver's last DB stubs; what remains is feeding it real embeddings
from a non-stub provider and invoking it from the live pipeline.

### 5.6 Pipeline — chunked, VAD-driven

Current local state:
1. Append incoming 100 ms chunks to a rolling buffer
2. Run the current VAD processor on each chunk
3. On silence → flush buffered speech → ASR + diarization-aware per-speaker embeddings + emit events → clear buffer

Still pending to finish Phase 5.6:
- validate latency/segmentation behavior on real microphone audio
- verify ECAPA embeddings against manually resolved `voice_profiles`
- verify PyAnnote/Silero loading on the intended Windows environment; local broken Torch/Torchaudio installs must degrade cleanly

### Verify Phase 5 (FR-TR-01)

```bash
# Speak one sentence → utterance appears in UI after silence boundary / stop flush
# Speak multiple speakers in one session → unknown queue populates
# Resolve an unknown speaker once, then re-speak in a new session → should auto-identify from stored voice_profiles
```

---

## Phase 6 — Settings persistence + model management

### Config persistence (backend + basic UI landed)

```python
# config.py
@dataclass
class BackendConfig:
    database: DatabaseConfig
    pipeline: PipelineConfig
    providers: ProviderConfig  # NEW — asr_model, embed_model, diarization_model

    def save(self, path: Path): path.write_text(json.dumps(asdict(self), default=str))
    @classmethod
    def load(cls, path: Path) -> "BackendConfig": ...
```

Implemented now:
- `POST /config/*` writes through
- `create_app` loads from disk
- default path is `~/.voice-diary/config.json`
- `Settings.tsx` loads `GET /config`, reflects provider status, and persists threshold/provider selection through the real API

Implemented now:
- `/models/*` status/load/unload routes
- placeholder `/models/{type}/download-progress` SSE state snapshot
- Settings load/unload buttons for selected provider models

Still pending:
- real download-progress tracking (currently uses synthetic 45 s interpolation instead of actual download bytes)

### Routes

- `GET /config`
- `POST /config/threshold` `{ value: 0.82 }`
- `POST /config/provider/{type}` `{ model_id: "whisper-medium" }`
- `GET /models/status` → `{ asr: {state: "LOADED", ram_mb: 1480}, ... }`
- `POST /models/{type}/load`, `POST /models/{type}/unload`
- `GET /models/{type}/download-progress` (SSE stream, needed for FR-ML-01)

`Settings.tsx` now uses real `/config` data for provider selection and threshold persistence, and selected model cards call `/models/{type}/load` or `/models/{type}/unload`.

### Verify Phase 6

```bash
# Change threshold in Settings → restart app → threshold persisted
# Change ASR / embedding / diarization provider in Settings → next use reflects the saved selection
# Settings UI reflects backend state instead of local component state
```

---

## Phase 7 (optional) — Packaging

**Not needed for diploma defense.** Document only:
- PyInstaller `--onedir` (not `--onefile` — PyTorch extraction is slow and breaks)
- `electron-builder` with `extraResources: ['dist/voice-diary-backend/']`
- `main.ts` resolves backend path from `app.isPackaged`
- Signed builds are out of scope

---

## Known risks

| Risk | Mitigation |
|---|---|
| Whisper can't hit 2 s latency on CPU | Use `faster-whisper` int8; fall back to `tiny` model on low-spec machines; document minimum hardware |
| PyAnnote 3.x is gated (HuggingFace token + license acceptance) | Use diarization-disabled mode as default; document token setup for advanced users |
| `ScriptProcessorNode` glitches / deprecated | Listed; AudioWorklet migration is post-MVP |
| `app.isPackaged` + `file://` breaks `fetch()` to `127.0.0.1` (mixed content in some configs) | Always load renderer via `http://localhost:5173` even in prod (bundle served by Python); or register custom protocol |
| Chrome returns 48 kHz despite 16 kHz request | ✅ Resolved — `downsampleTo16k()` in `api/websocket.ts` handles resampling |
| ECAPA embedding fails to load (`WinError 123`) | See `docs/voice-identification-environment.md` — SpeechBrain cache root composes a mixed relative/absolute path. Until fixed, speaker identification is degraded. Fix: patch the SpeechBrain model save dir or pre-download the model to a clean path. |
| FAISS won't be packaged cross-platform | N/A — staying on numpy cosine until > 500 contacts (doc says so) |
| PyTorch + CUDA vs. CPU-only: two build matrices | Ship CPU-only by default; GPU is opt-in via env |

---

## Reuse scorecard (corrected)

**Zero-change reuse:**
- SQLite schema (add FTS5 triggers as migration)
- Component style objects (already CSS-var-driven)
- `SimilarityMatcher`, `PipelineCoordinator` event bus shape, `MigrationRunner`
- Domain models (`models.py`)

**Migrate (syntax only):**
- ✅ 7 `.jsx` → `.tsx` (Phase 1)
- ✅ `Voice Diary.html` `:root` → `tokens.css` (Phase 1)
- ✅ `data.js` → `api/mock.ts` (Phase 1; seed script deferred to Phase 4)

**Rewrite:**
- ✅ `providers/asr.py` — Whisper Large-v3-Turbo (Phase 5.3, `1f9db8e`)
- 🟡 `providers/diarization.py`, `providers/embedding.py` — real optional wrappers work; embedding blocked by ECAPA path bug (`WinError 123`), see `docs/voice-identification-environment.md`
- 🟡 `pipeline/vad.py` — Silero VADIterator works when `silero-vad` is installed; falls back to deterministic RMS. Needs real-audio validation only.
- ✅ `identification/resolver.py::_load_voice_profiles()`, `_get_contact_name()` — wired to DB locally
- ✅ `PipelineCoordinator.process_chunk` — buffers until silence, flushes on session end, runs diarization-aware per-speaker embeddings, resolves against DB voice profiles via `SpeakerResolver`. Full code path works; blocked on real embeddings by ECAPA path bug.
- ✅ `Database` — per-request conn via `api/deps.py::get_db` (old `Database` still around for non-HTTP callers)
- ✅ 5 migrations: schema, FTS triggers, audio source, voice profile metadata, diarization model
- ✅ `backend/e2e-tests/` — 8 test files with real-model session-scoped fixtures

**Build new:**
- ✅ `pyproject.toml`, `run.py` (Phase 2, `1f9db8e`)
- ✅ `api/` — app, deps, schemas, 6 routers (Phase 2, `1f9db8e`)
- ✅ `storage/*_repo.py` — 4 repositories (Phase 2, `1f9db8e`), with live WS persistence hooks landed locally
- ✅ FTS5 sync triggers migration via `storage/fts_migration.py` (Phase 2, `1f9db8e`)
- ✅ Electron project — `frontend/electron/{main,preload,python-manager}.ts`, `frontend/tsconfig.electron.json` (Phase 3, `35bfebb`)
- ✅ Vite + React + TS project (Phase 1)
- ✅ `ContactsContext` (Phase 4, `35bfebb`); now superseded by React Query hooks (`query/contacts.ts`)
- ✅ `frontend/src/api/{client,adapters,sessions,contacts,queue,search,config,websocket}.ts` (Phase 4, `35bfebb`)
- ✅ `frontend/src/types/api.ts` (Phase 4, `35bfebb`)
- ✅ `shared/Avatar`, `shared/AudioLevelFooter`, `shared/Toggle` (Phase 1)
- ✅ `utils/highlight.tsx`, `utils/format.ts` (Phase 1)
- ✅ `backend/scripts/seed_dev_db.py` (Phase 4, `35bfebb`)
- ✅ Backend config persistence (`config.py`, `api/app.py`, `api/routers/config_rt.py`) landed locally
- ✅ Live Settings wiring (`frontend/src/components/Settings.tsx`) landed locally
- ✅ Resolver DB tests (`backend/tests/test_resolver.py`) and pipeline buffering tests (`backend/tests/test_pipeline_coordinator.py`) landed locally

---

## Critical files

| File | Why |
|---|---|
| `web_app/frontend/src/styles/tokens.css` | Design system root — every component reads this |
| `web_app/frontend/electron/python-manager.ts` | Desktop-app startup reliability hinges on this |
| `web_app/backend/api/app.py` | FastAPI factory — CORS, DI, lifecycle, and config bootstrap from disk |
| `web_app/backend/api/routers/audio_ws.py` | Real-time bridge + live persistence into sessions / utterances / speaker_segments / unknown_queue |
| `web_app/backend/storage/session_repo.py` | All session/utterance reads and writes, plus live speaker-segment inserts |
| `web_app/backend/pipeline/coordinator.py` | VAD endpointing state machine, diarization-aware utterance flush, resolver integration per `SpeakerResolver` — fully wired, blocked on real embeddings by ECAPA path bug |
| `web_app/backend/identification/resolver.py` | Model-ID-scoped voice profile loading from SQLite BLOBs, source-track isolation, cross-model fallback for candidate suggestions |
| `web_app/backend/providers/asr.py` | faster-whisper large-v3-turbo — working (int8 CPU / fp16 CUDA) |
| `web_app/frontend/src/api/websocket.ts` | Every live-UI feature reads from this |
| `web_app/frontend/src/components/Settings.tsx` | Real config-backed provider selection and threshold persistence now live here |
