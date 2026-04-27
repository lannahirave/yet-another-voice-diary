# Backend Codebase — Identified Issues

Generated from a thorough codebase audit (2026-04-28).

---

## Severity: High

### 1. Threshold default inconsistency (`config.py` vs `matching.py`)

**Files:** `backend/config.py:70`, `backend/identification/matching.py:25`

`PipelineConfig.speaker_identification_threshold` defaults to `0.5`, but `SimilarityMatcher.find_best_match()` has a hard-coded default of `0.82`. The `resolve()` method also defaults to `0.82`. The config value of `0.5` is never used as the default for `resolve()` — the resolver receives its threshold from the caller (coordinator), not from config.

**Impact:** Config UI (Settings > Memory > Identification threshold) controls a value that's not the actual matching default. The POST `/config/threshold` saves to disk correctly, but nothing reads this value at resolve time — the caller provides the threshold explicitly.

**Fix:** Either wire the config threshold into the resolver's default, or remove the `0.5` config default and document that callers must provide the threshold.

---

### 2. ECAPA embedding model fails to load (`WinError 123`)

**Files:** `backend/providers/embedding.py:108-113`, `docs/voice-identification-environment.md`

The SpeechBrain model cache path composes a mixed relative/absolute path:
```
pretrained_models\D:\MS_diploma\web_app\pretrained_models\speechbrain_spkrec-ecapa-voxceleb
```

This happens because `SpeakerRecognition.from_hparams()` receives a relative `savedir` while SpeechBrain internally resolves from an absolute cache root.

**Impact:** Speaker identification is completely broken. ASR, VAD, and diarization work. The embedding provider returns a zero vector on inference failure, so the pipeline continues but no real speaker matching happens.

**Fix:** Set a clean absolute `savedir` or pre-download the model to a known path before loading.

---

### 3. PyAnnote `transformers` compatibility may break silently after upgrades

**Files:** `backend/providers/diarization.py:209-216`

The PyAnnote import chain is fragile: `pyannote.audio → lightning → torchmetrics → transformers.AutoModel`. If `transformers` is upgraded to v5+ without also upgrading `torchmetrics`, the import fails with `ImportError: cannot import name 'AutoModel'`. Observed transiently with `transformers 5.6.2` + `torchmetrics 1.9.0` — may work on fresh imports but fail under specific load orders.

**Impact:** Diarization becomes unavailable. Pipeline falls back to full-utterance embedding (no per-speaker grouping), degrading identification quality.

**Fix:** Pin `transformers<5.0` in `pyproject.toml` for the `[ml]` extra, or upgrade `torchmetrics` to a version compatible with transformers v5.

---

## Severity: Medium

### 4. `_load_voice_profiles` dimension integrity check — `embedding_dim=0` bypasses filter

**File:** `backend/identification/resolver.py:169-171`

The guard `if stored_dim and stored_dim != actual_dim` uses truthiness. When `embedding_dim` is `0` (the schema default for unmigrated rows), the check is skipped because `0` is falsy. This means legacy profiles always pass dimension integrity checks regardless of actual dimension.

**Impact:** If a database has unmigrated profiles from a different embedding model (e.g., WavLM 512-dim), those profiles pass the dimension filter and get compared against ECAPA 192-dim embeddings. The cosine similarity would be computed on mismatched shapes, causing a numpy error or garbage score.

**Fix:** Compare `stored_dim is not None` instead of `stored_dim`, or run the 004 migration to backfill all legacy rows before the resolver is invoked.

---

### 5. Config rewrite-on-normalize can crash on read-only filesystem

**File:** `backend/config.py:144-145`

`BackendConfig.load()` auto-corrects legacy diarization model IDs and immediately re-saves. If the config file is read-only, or the parent directory is not writable, this raises an exception at load time.

**Impact:** App fails to start if the config file was deployed read-only or if the user's home directory has restrictive permissions.

**Fix:** Wrap the `config.save(source)` in a try-except and log a warning instead of crashing.

---

### 6. Per-kind `_provider_status` duplicated in two modules

**Files:** `backend/api/routers/models.py:73-80`, `backend/api/routers/config_rt.py:23-32`

The function that extracts `model_id`, `_state`, and `_error` from a provider object for display is implemented identically in both `models.py` and `config_rt.py`. This is a maintenance risk — changes to the provider state protocol must be made in two places.

**Fix:** Extract `_provider_status()` to a shared module (e.g., `api/deps.py` or a new `api/provider_utils.py`) and import it in both routers.

---

### 7. Zero-norm exact comparison in cosine and clustering

**Files:** `backend/identification/matching.py:18`, `backend/identification/clustering.py:50`

Both use exact equality (`== 0.0`) for zero-norm checks. Near-zero norms (e.g., `1e-40` from degenerate embeddings) pass the guard but produce numerically unstable cosine values (NaN or division overflow).

**Impact:** Very rare — real ECAPA embeddings are L2-normalized (norm ≈ 1.0). Could trigger with corrupted or empty embedding blobs.

**Fix:** Use tolerance-based comparison: `np.linalg.norm(a) < 1e-8`.

---

### 8. Greedy centroid clustering is order-dependent

**File:** `backend/identification/clustering.py:35-69`

The single-pass algorithm assigns each embedding to the first cluster whose centroid exceeds the threshold. Different input orders produce different cluster assignments.

**Impact:** The unknown-queue UI might show different cluster groupings on successive loads of the same data. The docstring acknowledges this and notes that cascade-re-identification after every resolve mitigates stale clustering. Acceptable for small queues (<50 items).

**Fix:** Not critical. Consider re-sorting embeddings by file path before clustering for determinism, or use agglomerative hierarchical clustering for more stable results.

---

## Severity: Low

### 9. `PipelineEngine` is dead code

**File:** `backend/pipeline/engine.py` (9 lines)

Contains only a constructor that stores `BackendConfig`. No methods. Not referenced anywhere in the codebase. Appears to be an early skeleton that was superseded by `PipelineCoordinator`.

**Fix:** Remove the file, or add a docstring noting it's a placeholder for future use.

---

### 10. `seed_dev_db.py` uses brittle path manipulation

**File:** `backend/scripts/seed_dev_db.py`

The script appends three levels of `os.path.dirname` to `sys.path` to import `backend.config`. This works only when run from the `web_app/` root.

**Impact:** Running the script from any other directory causes `ModuleNotFoundError`.

**Fix:** Use `pip install -e ".[dev]"` and import `from backend.config import BackendConfig` directly (the project structure already supports this with the pyproject.toml `package-dir` remapping). Or add `Path(__file__).resolve().parents[2]` to `sys.path` instead of the brittle relative chain.

---

### 11. `get_candidates` cross-model fallback may return misleading scores

**File:** `backend/identification/resolver.py:105-109`

When the current embedding model has no enrolled profiles, `get_candidates()` falls back to querying all profiles with the same embedding dimension, regardless of model_id. Different embedding models (e.g., ECAPA vs WavLM) produce vectors in different similarity-score distributions, so a score of 0.75 from WavLM profiles might mean something different than 0.75 from ECAPA profiles.

**Impact:** UI candidate suggestions might appear misleadingly confident when shown alongside scores from the current model. This is deliberate tradeoff documented in the code ("Candidate suggestions are a manual-assistance surface, not an automatic decision boundary").

**Fix:** Add a visual indicator in the UI when candidates come from a different model. Not essential — this is a UX enhancement, not a correctness bug.

---

### 12. `create_app` closes DB connection after migration then reopens later

**File:** `backend/api/app.py:84`

`Database` is opened, schema initialized, migrations applied, then `db.close()` called. Later, each HTTP request opens a fresh `sqlite3.Connection` via `get_db()`. This is intentional (per-request connections for concurrency safety) but the intermediate close-and-reopen adds unnecessary overhead for the migration phase.

**Impact:** Negligible performance impact (happens once at startup).

**Fix:** Not needed. The double-open is cheap and allows the migration connection to use different settings than request connections.

---

## Known Environment Issues

### ECAPA path bug (`WinError 123`)
See issue #2 above. Documented in `docs/voice-identification-environment.md`.

### `torchcodec` FFmpeg DLLs not installed
PyAnnote warns about missing FFmpeg DLLs. Harmless — Voice Diary feeds in-memory numpy arrays rather than audio files, so the file-decoding code path is never used.

### Stale `.pyc` caches after `transformers` upgrades
PyAnnote diarization may fail on stale `.pyc` caches after upgrading transformers. Clear with:
```bash
find .venv-ml -name "*.pyc" -delete
find .venv-ml -name "__pycache__" -type d -exec rm -rf {} +
```
