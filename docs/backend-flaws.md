# Backend Codebase — Verified Issues

Generated from a thorough codebase audit and verified by subagents (2026-04-28).

---

## Severity: High

### 1. Threshold default gap (config vs matcher) — but wired at runtime

**Files:** `backend/config.py:70`, `backend/identification/matching.py:29`, `backend/identification/resolver.py:43`

**Status:** PARTIAL — the default gap is real, but the claim that the config value is "never used" is false.

`PipelineConfig.speaker_identification_threshold` defaults to `0.5`, while `SimilarityMatcher.find_best_match()` hard-codes `0.82` and `resolve()` defaults to `0.82`. The gap means calling `resolve()` without explicitly passing `threshold=` uses 0.82, not the configured value.

**However**, both production callers explicitly read and pass the config threshold:
- `audio_ws.py:175-177`: `resolver.resolve(s, threshold=config.pipeline.speaker_identification_threshold)`
- `queue.py:198`: reads `threshold = config.pipeline.speaker_identification_threshold` and passes at `line 172`
- `queue.py:39`: cluster threshold = `config_threshold + _CLUSTER_MARGIN`

The config IS functional at runtime. The risk is only if a new caller invokes `resolve()` without the `threshold=` kwarg.

**Fix:** Change `resolve()` default to `None` and read config internally, or change the config default to `0.82` to match.

---

### 2. ECAPA embedding model fails to load (`WinError 123`)

**File:** `backend/providers/embedding.py:98`

**Status: CONFIRMED**

```python
savedir=f"backend/pretrained_models/{model_name.replace('/', '_')}",
```

`savedir` is a bare relative path. SpeechBrain's `from_hparams` internally concatenates this with its absolute cache root. On Windows, mixed `/` vs `\` separators produce an invalid path:
```
pretrained_models\D:\MS_diploma\web_app\pretrained_models\speechbrain_spkrec-ecapa-voxceleb
```

**Impact:** Speaker identification is completely broken. ASR, VAD, and diarization work.

**Fix:** Pass an absolute `savedir` using `Path(__file__)` or `Path.cwd()`, e.g.:
```python
savedir=str(Path("backend/pretrained_models") / model_name.replace("/", "_"))
```

---

### 3. `transformers>=4.40` open range allows v5.x which can break PyAnnote

**Files:** `backend/pyproject.toml:33`, `backend/providers/diarization.py:209`

**Status: CONFIRMED**

`pyannote.audio==4.0.3` (pinned) imports `lightning → torchmetrics → transformers.AutoModel`. But `transformers>=4.40` has no upper bound — pip can resolve v5.x, where `torchmetrics 1.9.0` may fail to import `AutoModel`.

**Impact:** Diarization becomes unavailable. Pipeline falls back to full-utterance embedding, degrading identification quality.

**Fix:** Pin `transformers>=4.44,<5.0` in the `[ml]` extra.

---

## Severity: Medium

### 4. `_load_voice_profiles` dimension check bypassed when `embedding_dim=0`

**File:** `backend/identification/resolver.py:169-170`

**Status: CONFIRMED**

```python
stored_dim = int(row_embedding_dim or 0)   # line 169
if stored_dim and stored_dim != actual_dim: # line 170 — 0 is falsy, skips check
    continue
```

When `embedding_dim` is `0` (schema default for unmigrated rows), the truthiness check at line 170 evaluates `False`, skipping the dimension filter entirely. Legacy profiles pass through regardless of actual embedding size.

**Fix:** Change to `if stored_dim is not None and stored_dim != actual_dim:` or ensure migration `004` backfills all rows before the resolver runs.

---

### 5. `BackendConfig.load()` crashes on read-only filesystem after normalization

**File:** `backend/config.py:145`

**Status: CONFIRMED**

```python
if raw_diarization_model_id != config.providers.diarization_model_id:
    config.save(source)  # line 145 — no try-except
```

When loading a config with a legacy diarization model ID (e.g., `"nemo"`), the auto-correction triggers an immediate `config.save()`. On a read-only filesystem or directory with restrictive permissions, this raises `PermissionError`/`OSError` uncaught.

**Fix:** Wrap in try-except, log a warning, and continue without saving.

---

### 6. `_provider_status` duplicated and diverged across two modules

**Files:** `backend/api/routers/models.py:73-80`, `backend/api/routers/config_rt.py:23-33`

**Status: CONFIRMED (diverged, not identical)**

Both define `_provider_status(kind, provider) -> ProviderStatus`. But they have diverged:
- `models.py` refactored state checking into a `_provider_state()` helper; `config_rt.py` kept it inline.
- `models.py` uses `str(model_id or "")` with secondary fallback; `config_rt.py` uses `getattr(..., "model_size", "") or ""`.
- Neither imports from the other.

**Fix:** Extract a single implementation into `api/provider_utils.py` and import from both routers.

---

### 7. Zero-norm uses exact `== 0.0` float comparison (no tolerance)

**Files:** `backend/identification/matching.py:18`, `backend/identification/clustering.py:50,74`

**Status: CONFIRMED**

```python
if norm_a == 0.0 or norm_b == 0.0:  # matching.py:18 — exact equality
if float(np.linalg.norm(emb)) == 0.0:  # clustering.py:50 — exact equality
if float(np.linalg.norm(e)) > 0.0:    # clustering.py:74 — exact equality
```

Floating-point norms near zero (e.g., `1e-16`) pass the guard and can cause division overflow or garbage similarity scores.

**Fix:** Replace `== 0.0` with `< 1e-8` tolerance.

---

### 8. Greedy centroid clustering is order-dependent (acceptable by design)

**File:** `backend/identification/clustering.py:49-67`

**Status: CONFIRMED**

Line 67 updates the centroid immediately (`best_cluster.add(idx, emb)`), which affects all subsequent comparisons in the single-pass loop at line 59. Different input orderings can produce different clusters. The docstring (lines 3-10) acknowledges this as intentional — the queue is small and cascade-re-identification mitigates staleness.

**Verdict:** Not a bug — acceptable by design. Documented for awareness.

---

## Severity: Low

### 9. `PipelineEngine` is dead code

**File:** `backend/pipeline/engine.py:5`

**Status: CONFIRMED**

Contains only a constructor. Zero references anywhere in the codebase. The actual orchestration is done by `PipelineCoordinator`.

**Fix:** Remove the file or mark as placeholder with a docstring.

---

### 11. `get_candidates()` cross-model fallback returns scores without `model_id` context

**File:** `backend/identification/resolver.py:105-109`

**Status: CONFIRMED**

When the current embedding model has no enrolled profiles, the fallback queries profiles from ANY model with matching dimension. The returned `(contact_id, score, contact_name)` tuples have no field indicating which model produced the score, so the UI cannot flag that candidates came from a different embedding space with potentially different score distributions.

**Note:** `resolve()` stays strict and never uses this fallback. This is documented as a deliberate tradeoff (lines 100-104).

**Fix:** Low priority — add a `model_id` field to candidate results for UI awareness.

---

### 12. `create_app` closes DB after migration — by design, NOT a bug

**Files:** `backend/api/app.py:84`, `backend/api/deps.py:27-50`

**Status: FALSE — intentionally designed this way**

The startup DB connection is for schema init + migrations only. Per-request connections are opened fresh in `get_db()` for concurrency safety (documented rationale in `deps.py:32-42`). The close/reopen is intentional and cheap.

**Verdict:** Removed from flaws list.

---

## Known Environment Issues

### ECAPA path bug (`WinError 123`)
See issue #2. Documented in `docs/voice-identification-environment.md`.

### `torchcodec` FFmpeg DLLs not installed
PyAnnote warns about missing FFmpeg DLLs. Harmless — Voice Diary feeds in-memory numpy arrays.

### Stale `.pyc` caches after `transformers` upgrades
```bash
find .venv-ml -name "*.pyc" -delete
find .venv-ml -name "__pycache__" -type d -exec rm -rf {} +
```
