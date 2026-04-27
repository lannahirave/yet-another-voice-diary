# App Launch Flow

The full Electron app (frontend + Python backend) is started with:

```sh
npm run electron:dev
```

## What happens

1. **Vite dev server** — starts on `http://127.0.0.1:5173` (HMR for React renderer)
2. **Electron main process** — compiled via `tsc -p tsconfig.electron.json`, then launched with `NODE_ENV=development`
3. **Python backend** — spawned automatically by the Electron main process:
   - Resolves python from `.venv-ml` → `.venv` → system `python` (first found wins)
   - Runs `python -m backend.run` → starts Uvicorn with FastAPI on `127.0.0.1:8765`
   - Polls `/health` (40 attempts, 500 ms apart) before marking backend as ready

## Key files

| File | Role |
|---|---|
| `electron/main.ts` | Electron entry, spawns backend on app ready |
| `electron/python-manager.ts` | Spawns/kills Python process, health-check loop |
| `backend/run.py` | Uvicorn entry point (host `127.0.0.1`, port `8765`) |
| `src/` | React renderer (Vite) |
