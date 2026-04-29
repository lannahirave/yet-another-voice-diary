# Frontend Workspace

`frontend/` is the desktop shell package for `web_app`.

It owns:
- the Node package manifest and lockfile
- Vite config and TypeScript project files
- React UI source under `src/`
- Electron main/preload code under `electron/`
- frontend-only build helpers under `scripts/`
- i18n locale files under `src/i18n/locales/`

It does not own:
- Python backend code
- model downloads
- SQLite state
- backend tests or backend scripts

## Architecture

```
electron/main.ts           — Electron entry: spawns backend, creates BrowserWindow
 electron/python-manager.ts  — Python process lifecycle + health polling
 electron/preload.ts         — contextBridge IPC surface (window.electronAPI)
│
src/                       — React 18 + TypeScript SPA (Vite)
 ├─ main.tsx               — app entry (QueryClientProvider + i18n init)
 ├─ App.tsx                — root component: screen routing + top-level state
 ├─ components/            — 7 screens (CurrentSession, AllSessions, UnknownQueue,
 │                            Contacts, Search, Settings) + Sidebar + shared
 ├─ api/                   — HTTP/WS client layer (apiFetch, adapters, AudioWebSocket)
 ├─ query/                 — TanStack React Query v5 hooks + optimistic mutations
 ├─ types/                 — domain.ts (app types) + api.ts (backend response shapes)
 ├─ i18n/                  — i18next with uk (default) + en, detected via localStorage
 ├─ styles/                — tokens.css (design variables) + global.css
 ├─ hooks/                 — useScreen (localStorage vd_state persistence)
 └─ utils/                 — format, highlight, queue filters
```

## State management

Uses **TanStack React Query v5** for all server state:
- `useConfigQuery()` — backend config (threshold, providers status, preload-on-start)
- `useContactsListQuery()` / `useContactsData()` — contact cache with `contactById` lookup
- `useSessionsListQuery()` / `useSessionUtterancesQuery()` — session + transcript data
- `useQueueListQuery()` — unknown speaker queue (staleTime=5s)
- `useSearchResultsQuery()` — FTS5 full-text search with `keepPreviousData`

Mutations use **optimistic updates** for instant UI feedback:
- `useResolveQueueClusterMutation` — patches queue list + session utterances optimistically
- `useSkipQueueClusterMutation` — removes cluster from queue list immediately
- `useCreateContactMutation` — upserts new contact into list cache

## Settings > Memory tab

Two model lifecycle toggles:
- **Unload models after Stop** (`POST /config/unload-after-stop`) — frees RAM between sessions
- **Preload models on app start** (`POST /config/preload-on-start`) — loads ML models in background threads at `create_app()` time; the existing SSE progress infrastructure auto-discovers LOADING providers on mount

## Light/dark theme

Settings > General > Appearance. Persisted in `localStorage('vd-theme')`. Inline `<script>` in `index.html` sets `[data-theme]` attribute before first paint to prevent flash. CSS variables in `tokens.css` define both palettes with smooth `transition`.

## Inline session rename

Double-click a session title in either the list card or the transcript panel header → the transcript panel shows an inline input with accent border. Type a name, press Enter or blur → `PATCH /sessions/{id}` persists to backend, React Query cache invalidates so the new title survives tab switches. Empty/default titles show a dashed-border CTA pill.

## Inline utterance identify

In `CurrentSession`, unknown utterances show a clickable "Хто це сказав?" button. Fetches candidates via `GET /sessions/utterances/{id}/candidates` (lightweight — uses stored speaker_segment embeddings, no ML loading). Shows contact pills with similarity % and a skeleton while loading. On select → `POST /sessions/utterances/{id}/identify` assigns contact + cascade-checks remaining unknown utterances in the same session.

## Server-side queue search

Search and session filter in the unknown queue now use backend SQL (`LIKE` on quote transcripts across all items, not just loaded page). 300ms debounce. Queue list paginated 20 items at a time with "Load more". Sidebar badge uses lightweight `GET /unknown-queue/count`.

## Query caching

Global defaults changed to `staleTime: Infinity, refetchOnWindowFocus: false`. Queries only refetch on explicit invalidation (mutations) or per-query polling overrides (`staleTime: 5_000` on queue list, `10_000` on count).

## Common commands

```bash
cd web_app/frontend
npm install
npm run typecheck          # tsc -b --noEmit — verify types compile
npm run build              # production build
npm run test:unit          # vitest run
npm run electron:compile   # compile Electron main/preload to CommonJS
npm run electron:dev       # full dev: Vite HMR + Electron + Python backend
```

Electron dev starts the Python backend from the `web_app` root and prefers
`.venv-ml`, then `.venv`, then `python` when selecting the interpreter.
