# E2E Test Suite — Research Findings

Three non-obvious bugs found while building and running the e2e test suite
(`backend/e2e-tests/`). Each required digging into library internals.

---

## 1. SpeechBrain / huggingface_hub API break

**Symptom:** `ECAPATDNNEmbeddingProvider.load()` fails with
`RuntimeError: failed to load embedding model … hf_hub_download() got an
unexpected keyword argument 'use_auth_token'`.

**Root cause:** SpeechBrain 1.0.x calls `hf_hub_download(…, use_auth_token=…)`
which was removed in `huggingface_hub` ≥ 0.20. The library also caches the
`hf_hub_download` reference inside `speechbrain.utils.fetching` at import time,
so patching only `huggingface_hub.hf_hub_download` is insufficient.

A second, related break: `huggingface_hub` ≥ 0.20 raises
`RemoteEntryNotFoundError` on 404, but SpeechBrain's `fetching.py` only catches
`requests.exceptions.HTTPError`. SpeechBrain expects a 404 for the optional
`custom.py` file in the model repo, catches the `HTTPError`, and converts it to
`ValueError`, which `interfaces.py` silently swallows. With the new exception
type, the 404 propagates and crashes the load.

**Fix** (`providers/embedding.py`):
```python
def _patch_speechbrain_hf_compat():
    orig = huggingface_hub.hf_hub_download
    def _compat(*args, use_auth_token=None, **kwargs):
        try:
            return orig(*args, **kwargs)
        except Exception as exc:
            if "EntryNotFoundError" in type(exc).__name__:
                from requests.exceptions import HTTPError
                raise HTTPError(f"404 Client Error: {exc}") from exc
            raise
    huggingface_hub.hf_hub_download = _compat
    speechbrain.utils.fetching.hf_hub_download = _compat   # patch cached ref
```

Called once, after importing SpeechBrain, before `SpeakerRecognition.from_hparams`.

---

## 2. WebSocket event drain race on session stop

**Symptom:** After the client sends `{"type":"stop"}`, the server closes the
connection before the client can receive any utterance/speaker-segment events.
The test's `receive_json()` loop collected an empty list.

**Root cause:** `end_session()` calls the `on_utt` / `on_seg` callbacks
synchronously. Those callbacks used `loop.call_soon_threadsafe(queue.put_nowait,
item)` — scheduling the put for the *next* event-loop iteration — rather than
calling `queue.put_nowait` directly. The sender task was cancelled before that
next iteration ran, so items were added to the queue only after the sender was
already dead.

**Fix** (`api/routers/audio_ws.py`):

1. Replace `loop.call_soon_threadsafe(queue.put_nowait, item)` with
   `queue.put_nowait(item)` in both `on_utt` and `on_seg`. All pipeline
   processing is synchronous inside `process_chunk` (no `await` points), so
   the callbacks are always called from the event-loop thread. `call_soon_threadsafe`
   was unnecessary and added exactly one iteration of latency.

2. Add an explicit drain loop in the `finally` block, after cancelling the sender
   task:
   ```python
   while not queue.empty():
       try:
           await ws.send_json(queue.get_nowait())
       except Exception:
           break
   ```
   This flushes any events queued by `end_session()` before `ws.close()`.

---

## 3. SileroVAD minimum chunk size

**Symptom:** The pipeline processed all audio chunks without ever buffering
speech. `_flush_buffered_utterance` was never called during streaming, and
`end_session()` found an empty buffer.

**Root cause:** `get_speech_timestamps` (SileroVAD's batch API) returns an empty
list for chunks shorter than ~300–400 ms at 16 kHz. On 100 ms (1 600-sample)
windows it returns no speech timestamps at all — including windows that are
entirely speech. The function is designed for full recordings, not short
streaming segments.

Verified empirically:

| Chunk size | Chunks with detected speech |
|---|---|
| 100 ms | 0 / 65 |
| 500 ms | 7 / 13 |
| 1 000 ms | 4 / 7 |

**Fix** (`e2e-tests/test_pipeline_ws.py`): Increased the streaming chunk size
from 1 600 samples (100 ms) to 8 000 samples (500 ms). This is only a test
concern; the production app receives browser-captured audio at whatever size the
front-end sends.

**Longer-term production note:** The current `VADProcessor.process()` calls
`get_speech_timestamps` on each incoming chunk independently. For reliable
streaming VAD, replace it with SileroVAD's stateful `VADIterator`, which
maintains inter-chunk state and works on standard 512-sample (32 ms) frames.
