# Voice Diary

Local-first desktop app for recording conversations, transcribing speech, and associating speakers with saved contacts over time.

Voice Diary captures microphone and optional system audio, streams it to a local Python backend, runs speech recognition and speaker processing, then stores sessions, transcripts, contacts, and unresolved speakers in SQLite.

## What It Does

- Records microphone and optional system audio in an Electron desktop app.
- Streams audio to a local FastAPI backend for real-time processing.
- Transcribes speech with Whisper / faster-whisper.
- Detects speech boundaries with Silero VAD.
- Runs speaker diarization with PyAnnote or NVIDIA NeMo Sortformer.
- Builds speaker embeddings with SpeechBrain ECAPA-TDNN.
- Matches known speakers to saved contacts and queues unknown voices for review.
- Supports transcript search, session history, contact management, and runtime model settings.
- Packages as a desktop app with a self-installed Python backend runtime.

## Tech Stack

- **Desktop/UI:** Electron 41, React 19, TypeScript, Vite 8
- **State/data:** TanStack Query v5, REST, WebSocket, i18next
- **Backend:** Python, FastAPI, Uvicorn, Pydantic
- **Storage:** SQLite, FTS5, idempotent migrations
- **ML:** faster-whisper, Silero VAD, PyAnnote, NeMo Sortformer, SpeechBrain, PyTorch
- **Tests:** Vitest, Testing Library, pytest, httpx
- **Packaging:** electron-builder, bundled backend source, runtime installer scripts

## Project Layout

```text
web_app/
  backend/      FastAPI service, ML providers, pipeline, SQLite repositories, tests
  frontend/     Electron + React app, API client, query hooks, UI components
  scripts/      local install scripts and packaged-runtime bootstrap scripts
  docs/         architecture notes and implementation findings
```

## How It Works

```text
Electron UI
  -> captures mic/system audio
  -> sends float32 PCM chunks over WebSocket

FastAPI backend
  -> VAD endpointing
  -> ASR transcription
  -> diarization
  -> speaker embedding
  -> speaker/contact resolution
  -> SQLite persistence + FTS search
```

In development, Electron starts the Python backend on `127.0.0.1:8765` and loads the Vite UI from `127.0.0.1:5173`.

## Requirements

- Python 3.11+
- Node.js 20+
- npm
- uv
- ffmpeg on `PATH` for NeMo Sortformer
- Optional: NVIDIA GPU for CUDA acceleration
- Optional: `HF_TOKEN` for gated Hugging Face diarization models

## Install

Windows:

```bat
scripts\install.bat
```

Linux / macOS:

```bash
bash scripts/install.sh
```

Useful installer flags:

```bash
--cpu             force CPU-only PyTorch
--no-nemo         skip NeMo Sortformer
--skip-frontend   skip npm install
--skip-seed       accepted by scripts; currently no seed step runs
```

The installer creates `.venv-ml`, installs backend ML/dev dependencies, installs frontend dependencies, picks CPU/CUDA PyTorch wheels, and verifies imports.

## Run In Development

Full desktop app:

```bash
cd frontend
npm run electron:dev
```

Backend only:

```bash
# Windows
.venv-ml\Scripts\python.exe -m backend.run

# Linux / macOS
.venv-ml/bin/python -m backend.run
```

## Connect an External Agent

Voice Diary includes a local, read-only MCP server so external agents can
retrieve diary information without starting the API or loading ML models. It
exposes two tools:

- `search_transcripts` searches transcript snippets with optional session,
  contact, and language filters.
- `search_diary` searches transcripts, session titles and notes, and known
  contacts, grouped by session.

Install the backend dependencies, then configure an MCP client to launch the
server over stdio from the repository root:

```json
{
  "mcpServers": {
    "voice-diary": {
      "command": "D:\\web_app\\.venv-ml\\Scripts\\python.exe",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "D:\\web_app"
    }
  }
}
```

An editable/source installation also provides the `voice-diary-mcp` command.

GitHub Releases also provide standalone MCP sidecars for Windows, macOS, and
Linux. Download the file for your platform, verify it against
`SHA256SUMS.txt`, and point the external agent directly at the downloaded
executable. On macOS and Linux, make it executable first with
`chmod +x voice-diary-mcp-*`.

Launch Voice Diary once before using the sidecar. Startup creates the database
and records its absolute path in `~/.voice-diary/config.json`, allowing the
sidecar to find the same diary regardless of where the executable was saved.

```json
{
  "mcpServers": {
    "voice-diary": {
      "command": "C:\\Tools\\voice-diary-mcp-windows-x64.exe"
    }
  }
}
```

An explicit config or database can be selected with `--config PATH` or
`--database PATH`. The server opens SQLite in read-only mode, never applies
migrations, and never exposes audio, embeddings, configuration, or arbitrary
SQL. If the schema is outdated, open the current Voice Diary app once before
connecting again.

Connecting an external agent grants that agent access to sensitive transcript,
session-note, and contact data returned by its searches. Only connect agents
you trust. Release sidecars are standalone and do not expose a network port or
start Voice Diary's ML runtime.

Frontend only:

```bash
cd frontend
npm run dev
```

## Package Desktop App

```bash
cd frontend
npm run electron:build
```

`electron-builder` writes packaged output to `frontend/dist-app/`.

Packaged apps include backend source and runtime bootstrap scripts as `extraResources`. On first run, the app installs its Python backend runtime under Electron `userData/backend-runtime`, so it does not depend on the repo checkout or local `.venv*` folders.

## Verify

Fast checks:

```bash
cd frontend
npm run typecheck
npm run test:unit
```

```bash
# Windows
.venv-ml\Scripts\python.exe -m pytest backend\tests\ -v

# Linux / macOS
.venv-ml/bin/python -m pytest backend/tests/ -v
```

Real-model e2e tests need ML dependencies and usually `HF_TOKEN`:

```bash
# Windows
.venv-ml\Scripts\python.exe -m pytest backend\e2e-tests\ -v

# Linux / macOS
.venv-ml/bin/python -m pytest backend/e2e-tests/ -v
```

## Technical Highlights

Voice Diary combines a desktop product shell with a local ML backend and several production-oriented constraints:

- real-time audio streaming over WebSocket
- graceful degradation when ASR, diarization, or embedding fails
- source-scoped speaker identity for mic vs system audio
- embedding-space metadata to avoid invalid voice-profile matches
- background model lifecycle management with progress reporting
- packaged runtime installation that does not depend on the source checkout or development virtualenvs

## Privacy and Security

Voice Diary is local-first by default, but recordings, transcripts, and speaker
embeddings are sensitive data. See [Privacy and Security](docs/privacy-security.md)
for storage paths, cloud-provider behavior, deletion/export procedures, token
handling, Hugging Face requirements, and third-party model licenses.
