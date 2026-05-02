# Voice Diary

Desktop meeting recorder with automatic transcription and speaker identification.
Built as an MS diploma project.

## Architecture

```
web_app/
  ├── backend/   Python service, tests, model cache, dev DB, backend scripts
  ├── frontend/  Vite/React/Electron desktop shell
  ├── docs/      project notes and app-specific findings
  └── .venv*/    local Python environments (machine-specific)

Electron (Node 20, frontend/)
  └─ spawns ──► Python 3.11 backend  (FastAPI + uvicorn on 127.0.0.1:8765)
                  ├── SQLite (sessions, utterances, contacts, speaker_segments, FTS5)
                  ├── Whisper Large-v3-Turbo  (ASR — faster-whisper, int8/CPU)
                  ├── Silero VAD              (stub — Phase 5)
                  └── ECAPA-TDNN embedding    (stub — Phase 5)
  └─ loads ───► Vite / React 18 / TypeScript  (127.0.0.1:5173 in dev)
                  ├── AudioContext → ScriptProcessorNode → PCM over WebSocket
                  └── REST: /sessions /contacts /unknown-queue /search /config
```

## Directory ownership

- `backend/` owns Python source, backend tests, backend scripts, the dev SQLite file, and downloaded model artifacts.
- `frontend/` owns the Node package, Vite config, Electron main-process code, and UI source.
- `docs/` owns project notes, findings, and implementation history.
- hidden root folders like `.venv-ml/`, `.run-logs/`, and `.playwright-mcp/` are disposable local runtime state, not product structure.

## Phase status

| Phase | Feature | Status | Commit |
|---|---|---|---|
| 1 | Vite + React 18 + TS skeleton | ✅ Done | `18021e7` |
| 2 | FastAPI + SQLite + Whisper Turbo | ✅ Done | `1f9db8e` |
| 3 | Electron wrapper | ✅ Done | `35bfebb` |
| 4 | Replace mocks with real API | ✅ Done | `35bfebb` |
| 5 | Real VAD + speaker embedding + ID | 🟡 ASR done; VAD/embed stubs | — |
| 6 | Settings persistence | ⬜ Pending | — |
| 7 | Packaging (optional) | ⬜ Pending | — |

## Requirements

- Python 3.11+
- Node 20+
- uv
- ffmpeg on `PATH` for NeMo Sortformer diarization
- (optional) CUDA-capable NVIDIA GPU for faster ASR/diarization

## Quick start

Windows uses a unified installer. It creates `.venv-ml`, installs backend ML/dev
dependencies with `uv`, installs CUDA Torch wheels when NVIDIA CUDA is detected,
installs NeMo Sortformer by default, installs frontend dependencies with
`npm ci` when the lockfile exists, seeds the dev DB, and verifies imports.

```bat
cd D:\web_app
scripts\install.bat
cd frontend && npm run electron:dev
```

Useful installer modes:

```bat
scripts\install.bat --cpu             REM Force CPU-only PyTorch
scripts\install.bat --no-nemo         REM Skip NeMo Sortformer dependencies
scripts\install.bat --skip-frontend   REM Skip npm dependency installation
scripts\install.bat --skip-seed       REM Skip dev DB seed
scripts\install-nemo.bat              REM Add NeMo to an existing .venv-ml
```

Electron starts the backend through `frontend/electron/python-manager.ts`, which
prefers `D:\web_app\.venv-ml\Scripts\python.exe`. If Sortformer fails with
`ModuleNotFoundError: No module named 'nemo'`, the active `.venv-ml` does not
have NeMo installed; run `scripts\install-nemo.bat` or rerun
`scripts\install.bat`.

## CUDA-enabled PyTorch

`backend/providers/asr.py` and `backend/providers/embedding.py` already switch to
`cuda` automatically when `torch.cuda.is_available()` is true. The current blocker
was the installed wheel, not the provider code.

`benchmark_codemixing` confirmed that CUDA is available on this machine, but
`web_app` must stay on the torch `2.8.0` line because `pyannote.audio==4.0.3`
and the current SpeechBrain integration are not compatible with torch `2.11`.

Use this CUDA-enabled stack in `web_app`:

- `torch 2.8.0+cu126`
- `torchaudio 2.8.0+cu126`
- `torchvision 0.23.0+cu126`

`web_app` had CPU-only Torch installs, so it stayed on CPU. To make `web_app` use
CUDA, use the Windows installer. It detects CUDA 12.x/13.x drivers and installs
the PyTorch `cu126` wheels:

```bat
scripts\install.bat
.venv-ml\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.version.cuda)"
```

## API overview

| Endpoint | Description |
|---|---|
| `GET /health` | Backend liveness |
| `GET /sessions` | List recording sessions |
| `POST /sessions` | Create session |
| `GET /sessions/{id}/utterances` | Utterances for a session |
| `GET /contacts` | List contacts (includes voiceprint `confidence`) |
| `POST /contacts` | Create contact |
| `GET /contacts/{id}` | Single contact (includes `confidence`) |
| `PATCH /contacts/{id}` | Update name/notes |
| `DELETE /contacts/{id}` | Delete contact |
| `POST /contacts/{id}/merge` | Merge two contacts |
| `GET /contacts/{id}/utterances` | All utterances attributed to this contact |
| `GET /unknown-queue` | Unresolved speaker segments |
| `POST /unknown-queue/{id}/resolve` | Assign segment to contact |
| `GET /search?q=` | FTS5 full-text search |
| `GET /config` | Current model/threshold config |
| `WS /ws/audio?track=mic\|system` | Stream PCM → receive utterance events. The `track` param tags every emitted utterance/segment so mic and system-loopback streams stay separate end-to-end (resolver scopes voiceprints by source). Default `mic` keeps single-stream callers working. |

## Key files

| File | Role |
|---|---|
| `frontend/electron/main.ts` | Electron entry — spawns Python, opens window |
| `frontend/electron/python-manager.ts` | Starts/stops Python backend subprocess |
| `frontend/src/api/adapters.ts` | Maps API shapes → frontend domain types |
| `frontend/src/api/websocket.ts` | `AudioWebSocket` + `downsampleTo16k` |
| `frontend/src/context/ContactsContext.tsx` | Global contacts cache |
| `backend/api/app.py` | FastAPI factory, CORS, DI |
| `backend/api/routers/audio_ws.py` | PCM → ASR → utterance events |
| `backend/providers/asr.py` | Whisper Large-v3-Turbo (CPU int8 / CUDA fp16) |
| `backend/storage/session_repo.py` | Session + utterance CRUD |
| `backend/scripts/seed_dev_db.py` | Populate DB with sample Ukrainian sessions |
| `backend/scripts/score_histogram.py` | Diagnose identification — SAME vs DIFF cosine distributions, threshold suggestion |
| `backend/scripts/clear_db.py` | Wipe user data, preserve schema (child-tables-first + FTS + VACUUM) |
| `backend/identification/resolver.py` | `SpeakerResolver` (cosine match, dedupe by contact) |
| `backend/storage/contact_repo.py` | Contact CRUD + voiceprint confidence (mean pairwise cosine) |
| `docs/voice-recognition-review.md` | How embeddings are stored/compared, why matches fail, investigation log |
| `docs/todo.md` | Full build plan with per-phase detail |

## Running tests

```bash
python -m pytest backend/tests/ -v   # 67 tests
python -m pytest backend/e2e-tests/ -v   # real-model e2e (needs .venv-ml)
cd frontend && npm run typecheck      # tsc --noEmit
```

## Diagnostics & maintenance scripts

```bash
# Score-histogram: dump SAME vs DIFF cosine distributions for the data in
# the DB, plus best-score-per-profile for every unresolved segment in the
# unknown queue. Use this to pick speaker_identification_threshold from
# real data instead of guessing.
.venv-ml/Scripts/python -m backend.scripts.score_histogram backend/voice_diary.db

# Clear-DB: wipe all user rows from the dev SQLite DB while preserving
# schema, indexes, and FTS shadow. Confirms before deleting unless --yes.
.venv-ml/Scripts/python -m backend.scripts.clear_db --yes
```

## Voiceprint confidence

`GET /contacts` and `GET /contacts/{id}` return a `confidence` field in
`[0, 1]`: the mean pairwise cosine across the contact's voice profiles.
Higher = the enrolled profiles are mutually consistent → reliable
identification. Returns `0.0` when fewer than two profiles exist (the UI
treats this as "voiceprint not yet computed", matching the disabled
"Update profile" button).

Identification threshold is exposed at runtime via `POST /config/threshold`
(value in `[0, 1]`). For ECAPA on noisy single-mic audio, real same-speaker
scores typically land in `0.55–0.85`. The historical default of `0.82` is
too aggressive in practice — see
`docs/voice-recognition-review.md` for the empirical calibration log.

## Design

Warm-cream palette (`#f2f1ed` background, `#f54e00` accent).
Fonts: Lora (serif) + JetBrains Mono (monospace) via Google Fonts.
The design spec (`uploads/DESIGN-cursor.md`) references CursorGothic / jjannon / berkeleyMono —
unlicensed proprietary fonts. Drop them into `public/fonts/` and uncomment the `@font-face`
block in `src/styles/tokens.css` to activate.
