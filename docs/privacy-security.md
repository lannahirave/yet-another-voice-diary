# Privacy and Security

Last reviewed: 2026-07-13

This document describes the current Voice Diary implementation. It is technical
documentation, not a legal privacy policy, compliance certification, or security
audit. Treat recordings, transcripts, contact data, and voice embeddings as
sensitive personal data.

## Summary

Voice Diary is local-first by default:

```text
microphone / system audio
        |
        v
Electron renderer -- ws://127.0.0.1:8765 --> local FastAPI pipeline --> SQLite
                                                           |
                                                           +--> optional ElevenLabs API
                                                                (only when selected)
```

- The backend listens on `127.0.0.1:8765`, not on the local network.
- Local Whisper, VAD, diarization, and embedding providers run inference on the
  machine after their model files are available.
- Model downloads and gated-model authentication can contact Hugging Face.
- The optional ElevenLabs Scribe provider sends audio to the ElevenLabs Speech
  to Text API. It is not local processing.
- The application does not provide encryption at rest, automatic retention
  policies, a full-data export, or a security audit.

## What is stored and where

| Data | Current location / behavior |
| --- | --- |
| Runtime configuration | `~/.voice-diary/config.json` (`Path.home()` on the current platform). Stores model selections, pipeline settings, database path, and the ElevenLabs token. |
| Sessions and transcripts | SQLite database at the configured `DatabaseConfig.path`. The development default is `backend/voice_diary.db`, relative to the backend working directory. Use `GET /config/storage` or Settings > Storage to inspect the active path. |
| Contacts | The same SQLite database. |
| Voice embeddings | The same SQLite database as binary BLOBs in `speaker_segments` and `voice_profiles`. Embeddings are derived biometric-like data and should be protected like audio. |
| Full-text search index | SQLite FTS5 tables in the same database. It mirrors transcript text. |
| Raw audio | Normally held in memory while a session is processed and not persisted by the application database. When `VOICE_DIARY_SAVE_DEV_AUDIO=1`, session WAV files are written to `VOICE_DIARY_DEV_AUDIO_DIR`, or `.dev-audio` under the backend working directory if no directory is configured. |
| Debug reports | When `VOICE_DIARY_DEBUG=1` or development debug mode is enabled, `VOICE_DIARY_DEBUG_DIR` (default `.dev-audio`) can contain WAV files, JSON metadata, transcripts, model configuration, and an HTML report. |
| Packaged runtime and logs | The Python runtime is installed under Electron's `userData/backend-runtime`; runtime-install logs are under Electron's `userData/logs`. These are separate from the configured database path. |
| Model caches | Hugging Face, Transformers, SpeechBrain, and FireRed use their normal local cache/savedirectory behavior. Cache locations can vary by platform and environment variables such as `HF_HOME`; inspect the environment before deleting or backing up a machine. |
| User exports | The UI exports the selected session's transcript rows as JSON, Markdown, or CSV through the operating system's download mechanism. Exports contain time, speaker display name, text, and language - not raw audio or embeddings. |

The default database path is relative rather than explicitly placed in the
user-data directory. Packaged deployments should inspect the path shown by the
Storage settings/API before assuming where the database lives.

## What leaves the machine

### Local providers

With the default local providers, audio is processed by the local Python
backend. The project code does not implement cloud synchronization or a remote
database. Network access is still required to download model files, and gated
Hugging Face models require authentication.

Once a model is cached, inference does not require sending the recording to
Hugging Face. A Hugging Face token is for model access/download; it is not an
audio-upload setting.

### ElevenLabs Scribe

When `elevenlabs-scribe` is selected, each non-empty audio segment is sent to
`https://api.elevenlabs.io/v1/speech-to-text` with the configured API key. The
current provider uses the `scribe_v1` model identifier; check the current
[ElevenLabs Speech to Text documentation](https://elevenlabs.io/docs/overview/capabilities/speech-to-text/)
before relying on this integration, because service model availability and
retention terms can change.

ElevenLabs service retention, processing, residency, billing, and enterprise
controls are governed by ElevenLabs terms and account settings, not by Voice
Diary. Do not use this provider for confidential recordings unless the selected
ElevenLabs plan and settings meet the applicable requirements. The integration
currently does not expose a local zero-retention or residency control.

## Tokens and secrets

### Hugging Face

Set `HF_TOKEN` in the environment used to start the backend when a gated model
requires it. Voice Diary reads this through the Hugging Face libraries and does
not write it to `config.json`. Do not commit it, put it in screenshots, or pass
it as a command-line argument.

For PyAnnote, create a Hugging Face account, accept the access conditions for
the gated [`pyannote/speaker-diarization-3.1`](https://huggingface.co/pyannote/speaker-diarization-3.1)
repository, and make the token available to the backend. The model page states
that access requires accepting its conditions and sharing contact information.
NeMo Sortformer downloads from Hugging Face also require a token according to
the [NVIDIA Sortformer model card](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1).

### ElevenLabs

The ElevenLabs token is saved in `~/.voice-diary/config.json`. The API returns
only a masked suffix to the UI, but the local JSON value is not encrypted by
Voice Diary. Protect the file with normal OS account permissions and disk
encryption. If the file may have been exposed, revoke/rotate the token in
ElevenLabs and remove the local value.

The current UI requires a non-empty value when saving a token. To clear it,
stop the app and either edit the configuration value to an empty string or call
the local endpoint with an empty token:

```text
POST http://127.0.0.1:8765/config/elevenlabs-token
{"token":""}
```

Never expose the backend outside loopback to make this request.

## Delete and export data

### What the UI supports

- Delete individual utterances from session views.
- Delete contacts and their stored voice profiles.
- Delete unresolved queue clusters.
- Export the currently selected session's transcript as JSON, Markdown, or CSV.

The transcript export is not a complete data export: it does not include raw
audio, embeddings, debug artifacts, configuration, or model caches.

### API and maintenance commands

- `DELETE /sessions/{session_id}` deletes a session and its session-owned
  utterances/segments where the database relationships allow it.
- `DELETE /sessions/utterances/{utterance_id}` deletes one utterance.
- `DELETE /contacts/{contact_id}` deletes a contact and its voice profiles.
- `POST /unknown-queue/delete` deletes selected unresolved queue items.
- `python -m backend.scripts.clear_db <path-to-db> --yes` clears the supported
  user tables while preserving the SQLite schema and running `VACUUM`.

The maintenance command does not currently remove every operational table (for
example, `pipeline_errors`). For a definitive local wipe, delete the database
file and its SQLite sidecars as described below.

For a definitive local wipe, stop Voice Diary first and delete the active
database file together with any SQLite `-wal` and `-shm` sidecar files. Also
remove, if present:

1. `~/.voice-diary/config.json`;
2. `.dev-audio` and any configured debug/audio-capture directory;
3. Electron `userData/logs` and debug reports;
4. Hugging Face, Transformers, SpeechBrain, and FireRed model caches if the
   downloaded model files must also be removed.

Deleting the database does not revoke cloud-provider tokens or delete data
already sent to ElevenLabs. Handle that through the provider account and its
retention controls.

## Security controls and limitations

Current controls:

- Backend HTTP/WebSocket traffic uses loopback URLs only.
- CORS allows the local Vite origins used by the desktop app.
- Electron enables `contextIsolation` and disables `nodeIntegration`.
- The API masks the ElevenLabs token in configuration responses.
- Development audio capture is opt-in through an explicit environment flag.

Current limitations:

- The local API has no authentication because it is intended for loopback use.
  Do not bind it to `0.0.0.0`, forward the port, or expose it through a proxy
  without adding authentication and authorization.
- SQLite data, config, debug artifacts, and local logs are not encrypted by
  Voice Diary.
- There is no automatic deletion schedule, consent workflow, access audit log,
  or complete export/delete UI.
- Debug mode can write raw audio and should remain disabled for normal use.
- Backups, filesystem snapshots, cloud-sync folders, and OS indexing tools may
  copy or expose the local files independently of Voice Diary.

For sensitive deployments, use an encrypted OS account/disk, keep the backend
on loopback, disable ElevenLabs and debug capture, restrict filesystem access,
and define a retention/deletion process appropriate for the people recorded.

## Model and service licensing

The repository's MIT license does not replace the licenses or terms of the
third-party model weights and services. Review the linked model card and its
current license before redistributing a packaged build or using it commercially.

| Component | Current model/service | License or access note |
| --- | --- | --- |
| ASR | [`openai/whisper-large-v3-turbo`](https://huggingface.co/openai/whisper-large-v3-turbo) | MIT model license on the Hugging Face model card. |
| Diarization | [`pyannote/speaker-diarization-3.1`](https://huggingface.co/pyannote/speaker-diarization-3.1) | MIT model license, but gated Hugging Face access conditions apply. |
| Alternative diarization | [`nvidia/diar_streaming_sortformer_4spk-v2.1`](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1) | NVIDIA Open Model License Agreement; review the agreement before redistribution or commercial use. |
| Embeddings | [`speechbrain/spkrec-ecapa-voxceleb`](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) | Apache-2.0 model license. The training data and speaker-data rights are separate considerations. |
| Local VAD | [Silero VAD](https://github.com/snakers4/silero-vad) | MIT upstream license. |
| Alternative VAD | [`FireRedTeam/FireRedVAD`](https://huggingface.co/FireRedTeam/FireRedVAD) | Apache-2.0 model/repository license. |
| Cloud ASR | [ElevenLabs Scribe](https://elevenlabs.io/docs/api-reference/speech-to-text/convert) | Hosted service; use is governed by ElevenLabs account terms, API terms, and privacy/retention settings. No service model is redistributed by this repository. |

Model licenses do not grant rights to record people. Obtain any required
consent and confirm the legal basis, workplace policy, biometric-data rules,
and retention obligations for the jurisdictions in which recordings are made.
