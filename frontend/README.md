# Frontend Workspace

`frontend/` is the desktop shell package for `web_app`.

It owns:
- the Node package manifest and lockfile
- Vite config and TypeScript project files
- React UI source under `src/`
- Electron main/preload code under `electron/`
- frontend-only build helpers under `scripts/`

It does not own:
- Python backend code
- model downloads
- SQLite state
- backend tests or backend scripts

Common commands:

```bash
cd web_app/frontend
npm install
npm run typecheck
npm run build
npm run electron:compile
npm run electron:dev
```

Electron dev starts the Python backend from the `web_app` root and prefers
`.venv-ml`, then `.venv`, then `python` when selecting the interpreter.
