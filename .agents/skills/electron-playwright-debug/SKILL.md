---
name: electron-playwright-debug
description: Reproduce and isolate bugs in this repository's Electron/Vite desktop app using source inspection, runtime logs, and Playwright's Electron automation. Use when Codex needs to debug renderer crashes, startup failures, IPC or preload issues, media-capture bugs, backend or WebSocket interactions, or Electron-only behavior that does not reproduce in a plain browser.
---

# Electron Playwright Debug

## Overview

Use this skill to debug the desktop app by reproducing the failing flow, shrinking it to the smallest crashing primitive, and tying the result back to exact source lines.

## Workflow

1. Start in `D:\web_app\frontend` unless the user points to a different app root.
2. Read the relevant code path first: `package.json`, `electron/`, the affected `src/components/` or `src/api/` files, and any backend route or WebSocket code involved.
3. Reproduce in the same mode the user reported.
   - If they mention `npm run electron:dev`, debug dev mode first.
   - If they mention `electron .` or a packaged build, treat `file://` loading and built-asset issues as a separate possibility.
4. Split the problem into one failure domain as early as possible.
   - Main process: app startup, backend spawn, `BrowserWindow`, IPC registration, preload wiring.
   - Renderer: React event handlers, media APIs, DOM state, `window.electronAPI`, WebSocket setup.
   - Backend: HTTP and WebSocket logs, especially health checks and per-session startup.
5. When the failure follows a user interaction, automate it with Playwright's Electron launcher, not browser-only page automation.
6. If the full UI flow is noisy, probe the suspected primitive directly with `page.evaluate(...)`.
7. Compare nearby variants instead of testing only one path.
   - Example: audio-only vs audio+video constraints, dev vs production, plain browser API vs Electron-mediated API.
8. Tie the conclusion back to exact files and lines before reporting a root cause.

## Repo-specific shortcuts

- The app root is `frontend` (relative to repo root `D:\web_app`).
- The Electron entrypoints are `electron/main.ts` and `electron/preload.ts`.
- The frontend state can persist between runs.
  - Current screen: `localStorage` key `vd_state`
  - System-audio toggle: `localStorage` key `vd_capture_system`
- If automation opens on the wrong screen, inspect `vd_state` or navigate with the sidebar before assuming the target UI is missing.
- If a production `file://` launch shows only the tweak panel or an empty shell, inspect built asset URLs in `dist/index.html` before chasing React logic.

## Reproduction harness

Use an inline Node harness when the project already depends on Playwright:

```powershell
@'
const { _electron: electron } = require('playwright');

(async () => {
  const app = await electron.launch({
    cwd: process.cwd(),
    args: ['.'],
    env: {
      ...process.env,
      NODE_ENV: 'development',
      ELECTRON_ENABLE_LOGGING: '1',
      ELECTRON_ENABLE_STACK_DUMPING: '1',
    },
  });

  const page = await app.firstWindow({ timeout: 60000 });
  page.on('console', (msg) => console.log('[console]', msg.type(), msg.text()));
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  page.on('crash', () => console.log('[crash] renderer crashed'));
  page.on('close', () => console.log('[close] renderer closed'));

  await page.waitForTimeout(3000);
  console.log('[url]', page.url());

  // Add UI actions or page.evaluate(...) probes here.
})();
'@ | node -
```

Prefer this over generic browser automation when the bug depends on preload APIs, IPC, renderer crashes, or Electron media behavior.

## Investigation pattern

### 1. Inspect the source path

- Search for the feature terms that match the bug: `desktopCapturer`, `getDisplayMedia`, `ipcMain`, `contextBridge`, `WebSocket`, `AudioContext`, `createSession`, `navigator.mediaDevices`.
- Read the exact handler that fires from the reported UI action before running the app.

### 2. Reproduce the visible flow

- Confirm the frontend mode, backend startup, and user-visible action.
- Watch terminal logs for the order of events.
- If the backend is still responding until the renderer dies, do not assume the backend is the cause.

### 3. Shrink to the primitive

- Use `page.evaluate(...)` to call the suspected API directly.
- Attach `crash` and `close` listeners before triggering the action.
- Distinguish:
  - Promise rejection or thrown error: application-level failure
  - Renderer `crash` without a JS error: Electron or Chromium process termination

### 4. Compare neighboring variants

- For media capture:
  - try audio-only
  - try audio + video
  - try `getUserMedia(...)` vs `getDisplayMedia(...)`
- For preload or IPC:
  - verify `window.electronAPI` exists
  - invoke the raw IPC-backed method directly from `page.evaluate(...)`

### 5. Map back to the code

- Identify the smallest failing call.
- Trace where the app invokes it.
- Report the precise file and line references for both the failing primitive and the UI path that reaches it.

## Output expectations

Report all of the following:

- The exact reproduction path
- The smallest failing call or constraint combination
- Which domain is at fault: main process, renderer, backend, or packaging
- The source files and lines that own the failure path
- The most likely fix, with a short rationale

## Guardrails

- Use official Electron documentation when media-capture, IPC, or session APIs may have changed across Electron or Chromium versions.
- Do not stop at "Electron crashed"; isolate the constraint set or API shape that causes the crash.
- Do not treat backend shutdown after renderer termination as the root cause unless the backend failed first.
- Preserve unrelated local changes while investigating.
