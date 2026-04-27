# AGENTS.md — Instructions for AI Coding Agents

This file describes the project conventions, verification commands, and coding
style that agents should follow when working on this codebase.

## Verification commands (run after every code change)

```bash
# Frontend typecheck (tsc --noEmit, must pass with zero errors)
cd D:\web_app\frontend && npm run typecheck

# Frontend unit tests
cd D:\web_app\frontend && npm run test:unit

# Backend tests (unit, run without ML models)
D:\web_app\.venv\Scripts\python.exe -m pytest D:\web_app\backend\tests\ -v

# Backend e2e tests (requires .venv-ml with [ml] extras + HF_TOKEN)
D:\web_app\.venv-ml\Scripts\python.exe -m pytest D:\web_app\backend\e2e-tests\ -v
```

## On commit

After every commit, run:
1. `npm run typecheck` in `frontend/`
2. `pytest` in `backend/tests/`

Never commit if either fails.

## Project structure

```
D:\web_app\
 ├─ frontend/        Node/Electron/React/Vite package
 │   └─ src/api/     backend-aware; must match backend/api/schemas.py shapes
 ├─ backend/         Python/FastAPI service
 │   └─ api/schemas.py   Pydantic models — frontend src/types/api.ts mirrors these
 ├─ docs/            architecture, findings, requirements
 └─ .venv/           dev Python env (base, ~20 MB, no ML)
 └─ .venv-ml/        ML Python env (includes torch, faster-whisper, speechbrain, pyannote)
```

## Style conventions

### Backend (Python)
- All type hints use new-style annotations: `list[X]`, `dict[str, X]`, `Optional[X]`
- Imports use `from __future__ import annotations` at top of every module
- Paths are computed relative to `web_app` root, never hardcoded absolute paths
- Repositories accept raw `sqlite3.Connection` (not `Database` wrapper)
- Providers follow the pattern: `__init__(model_id)` → `_load_model()` → `load()` → `unload()`
- Config dataclasses use `save(path)` / `load(path)` for JSON persistence
- Migrations are idempotent: check `PRAGMA table_info` before adding columns

### Frontend (TypeScript/React)
- React 18 + TypeScript strict mode
- State management: TanStack React Query v5 (not Context/useReducer for server state)
- API layer: `api/client.ts::apiFetch<T>()` wraps all HTTP calls (adds 10s timeout)
- Adapters in `api/adapters.ts` map API shapes → domain types
- Components use inline `const stS: Record<string, CSSProperties>` style objects
- i18n via `useTranslation()` hook — all user-facing strings must be translated
- New API endpoints require: (1) type in `types/api.ts`, (2) function in `api/*.ts`, (3) query/mutation in `query/*.ts`

### Shared patterns
- `src/types/api.ts` mirrors `backend/api/schemas.py` — keep them in sync
- Backend `POST /config/` endpoints: payload is `{ value: T }`, returns full `ConfigOut`
- Frontend mutations: onSuccess → `queryClient.setQueryData()` + `invalidateQueries()`
- Model lifecycle: background daemon threads + SSE progress streaming + per-kind `_LoadState` lock
- Config persistence path: `~/.voice-diary/config.json`

## Key architectural rules

1. **Source-scoped identity**: mic and system audio tracks are tracked separately
   (migration `003_audio_source`). Resolver scopes voice profiles by `source`.
2. **Embedding-space metadata**: `model_id` + `embedding_dim` on `voice_profiles`
   (migration `004`). Resolver rejects profiles from incompatible spaces.
3. **Graceful degradation**: pipeline continues when VAD/ASR/diarization/embedding
   fails — errors are emitted as events, not raised.
4. **Per-connection coordinator isolation**: each WebSocket gets its own
   `PipelineCoordinator`; provider singletons are shared.
5. **Optimistic mutations**: queue resolution patches session utterance caches
   immediately; rolls back on error.

## Known current issues

- ECAPA embedding model fails to load (`WinError 123`) — mixed relative/absolute
  path in SpeechBrain cache layer. See `docs/voice-identification-environment.md`.
- PyAnnote diarization may fail on stale `.pyc` caches after `transformers` upgrades.
- `torchcodec` FFmpeg DLLs not installed — harmless; Voice Diary uses in-memory numpy arrays.
