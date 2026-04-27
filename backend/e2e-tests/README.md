# Backend e2e tests

Real-model integration suite. Unlike `backend/tests/` (fast unit/integration tests
that run on the `[dev]` extras only), these tests exercise the actual ML
providers — faster-whisper, SpeechBrain ECAPA, pyannote.audio — and the full
FastAPI app wired to a temporary SQLite DB.

## Requirements

- A Python env with the `[ml]` extras installed (typically `web_app/.venv-ml`):
  `torch`, `torchaudio`, `faster-whisper`, `speechbrain`, `pyannote.audio`,
  `silero-vad`, `soundfile`, `scipy`.
- `HF_TOKEN` in the environment — pyannote's `speaker-diarization-3.x` is gated.
- `web_app/docs/record_out.wav` — the reference utterance used by the inference
  tests ("hello how you are doing i am doing fine how are you").

## Running

```bash
cd web_app
.venv-ml/Scripts/python -m pytest backend/e2e-tests/ -v
```

The whole suite is session-scoped: the FastAPI app, DB, HTTP client, and loaded
ML models are reused across files. Test files run in alphabetical order, which
matters for `test_model_lifecycle.py` — see below.

## Fixtures (`conftest.py`)

| Fixture | Scope | Purpose |
|---|---|---|
| `e2e_app` | session | FastAPI app on a tmpdir SQLite DB. Monkeypatches `BackendConfig.default_path` into the tmpdir so `POST /config/*` calls do **not** overwrite `~/.voice-diary/config.json`. |
| `client` | session | `httpx.AsyncClient` over `ASGITransport` — used by every async HTTP test. |
| `sync_client` | session | `fastapi.testclient.TestClient` — required for WebSocket tests (`AsyncClient` has no `websocket_connect`). |
| `wav_f32` | session | `docs/record_out.wav` decoded as mono float32 @ 16 kHz, resampled if needed. |
| `db_conn` | session | Raw SQLite connection on the tmpdir DB for seeding rows directly. |
| `monkeypatch_session` | session | Session-scoped `MonkeyPatch` (the built-in fixture is function-scoped). |

## Test files

| File | Covers |
|---|---|
| `test_model_lifecycle.py` | `/models/status`, `/models/{kind}/load`/`unload` (idempotency, reload, unknown-kind 404), real inference for each provider (ASR transcript, ECAPA unit-vector, diarization ≥1 speaker), and `/models/{kind}/download-progress` SSE snapshot in both `UNLOADED` and `LOADED` states. **Leaves all models UNLOADED** so `test_pipeline_ws.py` can manage its own state. |
| `test_pipeline_ws.py` | Full `WS /ws/audio` flow with real ASR + VAD + embedding: start session → stream PCM → utterance event → speaker_segment event → stop. |
| `test_api_sessions.py` | `GET/POST /sessions`, `GET /sessions/{id}/utterances` against real DB. |
| `test_api_contacts.py` | Contact CRUD, merge, voiceprint confidence, `GET /contacts/{id}/utterances`. |
| `test_api_queue.py` | Unknown-queue clustering, batch resolve/skip, cascade re-identification. |
| `test_api_search.py` | FTS5 search results match seeded utterances. |
| `test_api_config.py` | `GET /config`, `POST /config/threshold`, `POST /config/provider/{kind}`. Includes `test_config_save_does_not_touch_user_home` — regression for the leak that wrote test temp paths into `~/.voice-diary/config.json`. |

## Conventions

- **Don't write to `~/.voice-diary/`.** The `default_path` monkeypatch in
  `e2e_app` enforces this for `BackendConfig.save()`. If you add another
  endpoint that touches the user home, mirror the regression test in
  `test_api_config.py`.
- **Leave models UNLOADED.** Lifecycle tests must clean up so the websocket
  tests can load on demand without state bleed.
- **Real audio only.** No synthetic embeddings — use `wav_f32` so providers
  exercise the same code paths as production.

## Download-progress placeholder

`GET /models/{kind}/download-progress` is currently a single-shot SSE that
emits one state snapshot (`progress: 0.0` if `UNLOADED`, `1.0` if `LOADED`)
and closes the stream. The e2e tests in `test_model_lifecycle.py` lock in
that contract. When the endpoint is upgraded to stream real progress
(see `docs/todo.md` §"Replace placeholder model progress"), update those
tests to consume multiple events and assert monotonic progress.
