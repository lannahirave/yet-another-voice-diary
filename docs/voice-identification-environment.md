# Voice Identification Environment in `web_app`

Technical note on how the runtime environment for speaker identification is assembled in `web_app`, which interpreter is used, where models are loaded from, and what currently blocks stable operation.

## 1. Which runtime is used

`web_app` has two local Python environments:

- `.venv` — base backend/dev environment
- `.venv-ml` — preferred runtime for real ML providers

Electron starts the backend through `frontend/electron/python-manager.ts` and resolves Python in this order:

1. `web_app/.venv-ml/Scripts/python.exe`
2. `web_app/.venv/Scripts/python.exe`
3. `python` from `PATH`

So speaker identification is effectively expected to run from `.venv-ml` whenever that environment exists.

## 2. Backend process shape

The desktop shell spawns:

- `python -m backend.run`
- `cwd = web_app`
- backend bind = `127.0.0.1:8765`

That means relative paths inside backend code are resolved from the `web_app` root, not from `web_app/backend`.

Relevant files:

- `frontend/electron/python-manager.ts`
- `backend/run.py`
- `backend/api/app.py`

## 3. ML stack used for speaker identification

Speaker identification is split into two providers:

- diarization: `PyAnnoteDiarizationProvider` or `NeMoSortformerDiarizationProvider`
- embedding: `ECAPATDNNEmbeddingProvider`

Default provider IDs come from `backend/config.py`:

- `diarization_model_id = "pyannote"`
- `embedding_model_id = "ecapa"`
- `speaker_identification_threshold = 0.5`

Optional ML dependencies are declared in `backend/pyproject.toml` under `.[ml]`:

- `speechbrain>=1.0`
- `pyannote.audio==4.0.3`
- `silero-vad>=5.1`
- `torch==2.8.0`
- `torchaudio==2.8.0`
- `torchvision==0.23.0`

NeMo Sortformer is intentionally split into a separate optional extra:

- `.[ml-nemo]` -> `nemo_toolkit[asr]`

This keeps the default speech stack smaller and lets the desktop app degrade
gracefully when NeMo is not installed.

The repo notes also fix the practical torch line to `2.8.0`, because this `web_app` stack does not currently install cleanly against newer torch `2.11` wheels.

## 4. How model loading is configured

### Embedding provider

`backend/providers/embedding.py` maps:

- `"ecapa"` or `"ecapa-tdnn"` ->
  `speechbrain/spkrec-ecapa-voxceleb`

Model loading is lazy: the model is not loaded at app startup. It is loaded only on the first call to `embed(audio)`.

Device selection is automatic:

- `cuda` if `torch.cuda.is_available()`
- otherwise `cpu`

The provider passes this cache directory to SpeechBrain:

- `savedir = "backend/pretrained_models/speechbrain_spkrec-ecapa-voxceleb"`

### Diarization provider

`backend/providers/diarization.py` maps:

- `"pyannote"` or `"pyannote-3.1"` ->
  `pyannote/speaker-diarization-3.1`
- `"sortformer-v2.1"` ->
  `nvidia/diar_streaming_sortformer_4spk-v2.1`

Both diarization backends are loaded lazily on the first diarization call.

Sortformer currently runs inside the app's existing utterance-based pipeline:

- the app does **not** use Sortformer's native chunk-wise live inference path yet
- instead, a closed VAD utterance is passed to `segment(audio)`
- the provider still applies NVIDIA's published accuracy-oriented streaming
  cache parameters:
  - `chunk_len = 340`
  - `chunk_right_context = 40`
  - `fifo_len = 40`
  - `spkcache_update_period = 300`

Important limitations of this integration:

- optimized for up to 4 active speakers
- English-oriented checkpoint, though it may still work reasonably on other languages
- not intended as a CPU-first path; if NeMo is missing, the provider enters `ERROR`
  with an actionable install hint instead of pretending the model is available

## 5. Where model files live

The actual local cache directory present in the repo is:

- `web_app/backend/pretrained_models/`

Observed contents include at least:

- `speechbrain_spkrec-ecapa-voxceleb`
- `wavlm`

There is no `web_app/pretrained_models/` directory at the app root.

## 6. Runtime flow for identification

The identification path is:

1. frontend streams `float32` mono PCM over `WS /ws/audio`
2. `backend/api/routers/audio_ws.py` feeds chunks into `PipelineCoordinator`
3. `PipelineCoordinator` runs:
   - VAD
   - ASR
   - diarization
   - embedding extraction per diarized speaker group
4. `SpeakerResolver.resolve(...)` compares the new embedding against all rows in `voice_profiles`
5. if the score is below threshold, the segment is written to `unknown_queue`

Matching is cosine similarity over stored `float32` embedding blobs.

## 7. Runtime observability

Provider state is exposed through the backend and UI:

- `GET /config`
- `POST /config/threshold`
- `POST /config/provider/{kind}`
- `POST /models/{kind}/load`
- `POST /models/{kind}/unload`

The frontend Settings page reads these states and surfaces:

- `LOADED`
- `UNLOADED`
- `LOADING`
- `ERROR`

This makes the identification environment partially inspectable at runtime without attaching a debugger.

## 8. Important compatibility patches already present

The repo already contains defensive patches around the voice-ID stack:

- Hugging Face compatibility patch for SpeechBrain in `backend/providers/embedding.py`
- Windows `inspect.py` compatibility shim for SpeechBrain lazy imports in `backend/providers/diarization.py`
- torch checkpoint compatibility wrapper for `pyannote/speaker-diarization-3.1`
- warning suppression for PyAnnote's torchcodec path when waveform tensors are passed directly

So the environment is not "vanilla"; it is already adapted around known Windows and dependency-friction issues.

## 9. Current operational problem

The current backend logs show a concrete failure in the embedding runtime:

- `SpeechBrain embedding model load failed`
- `WinError 123`
- malformed path:
  `pretrained_models\\D:\\MS_diploma\\web_app\\pretrained_models\\speechbrain_spkrec-ecapa-voxceleb`

This indicates the embedding layer is failing while resolving the SpeechBrain cache path on Windows. The local cache exists under `backend/pretrained_models`, but the runtime ends up composing a mixed relative/absolute path string.

Practical consequence:

- ASR can still run
- diarization may still run
- speaker embedding fails
- speaker identification then degrades or is skipped

This is currently the main environment-level blocker for stable voice identification in `web_app`.

## 10. Secondary configuration details that matter

- Backend config persists to `~/.voice-diary/config.json`, not inside `web_app`
- threshold and selected provider IDs can therefore survive restarts
- the default threshold in code is `0.5`
- supported diarization model IDs are currently:
  - `pyannote`
  - `pyannote-3.1`
  - `sortformer-v2.1`
- legacy `nemo` in old config files is normalized back to `pyannote`

## 11. Bottom line

The voice-identification environment in `web_app` is configured as a local Python sidecar, preferably running from `.venv-ml`, with lazy-loaded `pyannote` diarization and `SpeechBrain ECAPA` embeddings, local model cache in `backend/pretrained_models`, runtime control through `/config` and `/models`, and automatic CPU/CUDA selection.

Architecturally the environment is wired correctly, but in the current Windows runtime it is not fully healthy because the embedding provider is failing to load its cached SpeechBrain model due to broken path composition.
