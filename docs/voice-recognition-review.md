# Voice Recognition Review

Review of the speaker identification path in `web_app/`: what is stored, how
voices are compared, and likely reasons a voice fails to be recognized.

## 1. What gets stored in the DB

Schema: `backend/storage/schema.sql`.

- `voice_profiles` — enrolled "known" voices, one or many rows per contact
  - `embedding BLOB NOT NULL` — raw `float32` bytes (192-dim, ECAPA-TDNN, L2-normalized)
  - `quality_score`, `recorded_at`, `source_session_id`
- `speaker_segments` — every diarized speaker chunk produced from a session,
  with `embedding BLOB`, `status` (`unknown` / `identified`), `sim_score`,
  `contact_id`
- `unknown_queue` — points at unresolved `speaker_segments` for the UI

Embedding extraction: `ECAPATDNNEmbeddingProvider.embed()`
(`backend/providers/embedding.py:118`).

- Model: `speechbrain/spkrec-ecapa-voxceleb` (192-dim)
- Calls `model.encode_batch(waveform)` → `_normalize` → unit-norm float32
- Empty audio → `np.zeros(192)` (a sentinel that **will never match anything**,
  since cosine = 0)
- BLOB encoding is `arr.tobytes()` of float32; decoded with
  `np.frombuffer(..., dtype=np.float32).copy()` (`backend/identification/resolver.py:169`)

## 2. How the backend compares voices

Identification path for each finished utterance:

1. `coordinator._build_speaker_segments()` runs pyannote diarization, slices
   the utterance audio per speaker label, **concatenates** all slices for one
   label, then computes ONE ECAPA embedding over the concatenation
   (`backend/pipeline/coordinator.py:194`).
2. The biggest-by-samples segment becomes the utterance's "primary" speaker.
3. WS handler `on_seg` (`backend/api/routers/audio_ws.py:129`) calls
   `SpeakerResolver.resolve(segment, threshold=cfg.speaker_identification_threshold)`.
4. `SpeakerResolver._load_voice_profiles()` loads **every row** in
   `voice_profiles` and runs `SimilarityMatcher.find_best_match` — cosine
   similarity, picks the single highest score ≥ threshold
   (`backend/identification/matching.py:25`).
5. If matched → segment gets `contact_id` + `status='identified'`. Otherwise →
   `unknown_queue`.

Default threshold: `0.82` cosine on unit-norm ECAPA vectors
(`backend/config.py:61`).

Clustering path (`backend/identification/clustering.py`): for the unknown
queue, greedy single-pass linkage to a running centroid; threshold is
`cfg.speaker_identification_threshold + 0.10` margin
(`backend/api/routers/queue.py:39`). Resolving one cluster member cascades to
others via a re-resolve pass at `backend/api/routers/queue.py:127`.

## 3. Likely reasons a voice is NOT recognized

Rough order of impact in this repo:

1. **Threshold 0.82 is aggressive for ECAPA cosine.** ECAPA-VoxCeleb's
   published EER operating point is ~0.25–0.30 raw; after L2-norm cosine,
   genuine same-speaker pairs typically land in **0.55–0.85** in clean audio
   and frequently 0.45–0.75 in noisy single-mic capture. `0.82` will reject
   many true matches. Lowering to 0.55–0.65 and inspecting score histograms is
   the first thing to try.

2. **Diarization-induced mixing.** `_speaker_groups` concatenates all slices
   that share a pyannote label within one utterance and embeds the
   concatenation. If pyannote merges two people under one label (common in
   short, overlapped, or low-energy speech), the resulting embedding is a mix
   and won't match either enrolled profile. If diarization misses a turn, two
   speakers get embedded as one.

3. **Short audio = unstable embeddings.** ECAPA needs ~1.5–3 s for stable
   identification. Utterances shorter than that still get an embedding, but it
   drifts across sessions for the same person — bouncing under 0.82.

4. **Single-profile enrollment under varied conditions.** Auto-enrollment from
   `queue_repo.resolve` records one profile per resolve, and only for the
   first member of a batch (`record_voice_profile=(idx == 0)`,
   `backend/storage/queue_repo.py:198`). One enrollment captured in mic A /
   mood A won't match mic B / mood B. `_load_voice_profiles` returns each
   profile row separately and `find_best_match` takes the max, so additional
   profiles do help — but only if they exist.

5. **Empty / zero-norm embeddings get persisted.** `embed()` returns
   `np.zeros(192)` for empty audio; `_normalize` returns zeros if norm is 0 or
   NaN. Cosine of a zero vector is forced to 0 in `matching.py:18`, so these
   can't match — but they pollute `voice_profiles` if anything ever inserts
   them.

6. **No score fusion or top-k voting for identification.** Best-only match. If
   the runner-up profile is the correct one and lost by 0.001, it's discarded
   silently. `get_candidates` exists but is only used for the unknown-queue
   UI, not for primary identification.

7. **No model-version guard.** `voice_profiles` doesn't store the embedding
   model id or dimension. If `embedding_model_id` ever changes (the config
   endpoint allows it, `backend/api/routers/config_rt.py:65`), all old
   profiles become incompatible junk and silently fail to match. Adding a
   `model_id` column + dim check would prevent this.

8. **Sample-rate / channel assumptions.** ECAPA expects 16 kHz mono.
   Coordinator tracks `sample_rate` per buffer but feeds audio directly to
   `embedding.embed`. If WS audio ever arrives at a different SR or stereo,
   embeddings degrade with no error.

9. **Cross-connection visibility.** Each WS opens its own sqlite connection
   (`backend/api/routers/audio_ws.py:118`). Under WAL, profiles written via
   another connection without an explicit checkpoint barrier may not be
   visible to the resolver immediately.

## Suggested next steps

- Log the `sim_score` distribution over a known same-speaker session and pick
  the threshold from the histogram instead of the default.
- Add an assertion `embedding.shape == (192,)` and reject zero-norm vectors
  before persisting them.
- Store `model_id` + `dim` on `voice_profiles`; reject mismatched lookups.
- Compare per-speaker mean profile vs. best-of-N — likely worth the change
  once `voice_profiles` has 3+ rows per contact.

## Investigation log (2026-04-25)

### Tooling added under `backend/scripts/`

- `score_histogram.py` — reads `voice_profiles` and resolved `speaker_segments`
  from the DB, computes cosine similarity for every (segment, profile) pair,
  prints SAME vs DIFF stats and ASCII histograms, then suggests a threshold
  via balanced-accuracy peak. Also dumps best-score-per-profile for every
  segment still in the unknown queue, which is what surfaced the chunking bug
  below.
- `clear_db.py` — wipes user data from every table while preserving schema +
  indexes; child tables first to satisfy FK constraints, plus
  `utterances_fts`, then `VACUUM`. Confirmation prompt unless `--yes` is
  passed.

### Empirical finding: end-of-session flush emits 256 ms "utterances"

Running `score_histogram.py` against the dev DB showed every unresolved
segment scored 0.05–0.27 against the only enrolled profile — far below any
plausible same-speaker threshold for ECAPA. Cross-referencing with
`utterances.started_ms`/`ended_ms` revealed every problematic segment was
exactly **256 ms or 512 ms** long, with transcripts like ".", "Thanks.",
"До свидания!", and "ДИНАМИЧНАЯ МУЗЫКА" — Whisper hallucinations on near-
silent fragments.

Root cause: `coordinator.end_session()` (`backend/pipeline/coordinator.py:101`)
**always** flushes the buffered utterance on stop, bypassing the
`vad_min_utterance_ms = 300` gate. The intent is "don't drop the user's last
words"; the side effect is that the trailing 1–2 chunks of any session get
emitted as a real utterance and fed into the embedding pipeline. ECAPA cannot
produce a usable speaker vector from 256 ms of audio, so each one becomes a
junk vector that pollutes the unknown queue.

Fix direction (not yet implemented): keep emitting the transcript on
end-of-session, but **gate `_build_speaker_segments` on the same minimum
utterance length** so short flushes don't generate `speaker_segments` /
`unknown_queue` rows. Or persist them with `embedding=NULL` and skip the
resolver entirely.

### Operational finding: e2e config fixture leaked into user config

The Electron-spawned backend was reading a temp DB
(`%TEMP%\tmp7tjr1iu_\e2e.db`) instead of `web_app/backend/voice_diary.db`,
even though `cwd` was correct.

Cause: `backend/api/routers/config_rt.py` calls `request.app.state.config.save()`
on `POST /config/threshold` and `POST /config/provider/{kind}`. `save()`
serialises to `BackendConfig.default_path()` =
`~/.voice-diary/config.json` — *the user's real config* — regardless of
where the running config came from. Any e2e test that hit those endpoints
overwrote the user's config with the test's temp DB path.

Fix: `backend/e2e-tests/conftest.py` now monkeypatches `default_path` into
the same tmpdir as the e2e DB. `backend/e2e-tests/test_api_config.py` has a
new regression test, `test_config_save_does_not_touch_user_home`, that
snapshots `~/.voice-diary/config.json` around the threshold endpoint and
asserts it doesn't change. A longer-term improvement would be to thread the
save target through `app.state` instead of relying on a class-level
`default_path()`, so the router never touches user-scoped paths in any
context.

### Sandbox dump for listening to recorded audio

If you need to verify by ear what an utterance contains, set
`VOICE_DIARY_SAVE_DEV_AUDIO=1` (or `NODE_ENV=development`) before launching
the backend. Each session's full WAV is saved to `web_app/.dev-audio/` named
`<YYYYMMDD>-<HHMMSS>-<session-uuid>.wav`. Cross-reference the session id
against `utterances.started_ms` / `ended_ms` to seek to the right offset.

### Empirical threshold calibration (post-enrollment)

After enrolling four voice profiles for the same speaker across different
sessions, the score-histogram tool produced this **SAME-speaker** cosine
distribution against existing profiles (n=20):

```
min=0.582  p25=0.676  median=0.763  p75=0.825  p95=1.000  (1.000 = self-match)
```

And the five segments still sitting in the unknown queue (also same speaker)
scored against the existing profiles:

```
0.508, 0.595, 0.621, 0.741, 0.746
```

**Conclusion:** the ECAPA score for this speaker's true matches centres around
**0.65–0.80**. The shipped default of `0.86` (which had been raised from `0.82`
during a previous tuning attempt) sits **above** the speaker's own
upper-quartile, so almost every legitimate utterance was being rejected into
the unknown queue. Lowered the runtime threshold to **0.55** via the
`/config/threshold` endpoint — every previously-unresolved segment cascaded
to the correct contact on the next sweep.

The default in `backend/config.py` is still `0.82`. Keeping it there for now
because we don't yet have a multi-speaker DIFF distribution to calibrate
against impostor risk. A more durable fix is described in "Suggested next
steps" — log scores at every resolve and pick the threshold from the
combined SAME/DIFF histograms, not from a guessed default.

### Bug: queue showed the same contact twice

When a contact had ≥2 enrolled voice profiles, the queue UI listed them as
two separate suggestions ("Valera 76%", "Valera 67%") because
`SpeakerResolver.get_candidates` returned one row per `voice_profiles`
record. Fixed in `backend/identification/resolver.py`: now scores against
every profile, then collapses to one entry per contact keeping the best
score, then takes top_k. Regression test in
`backend/tests/test_resolver.py::test_get_candidates_dedupes_multiple_profiles_per_contact`.

### Bug: every HTTP request returned 500 (sqlite thread affinity)

After Electron started spawning the backend with the venv-ml interpreter,
`/contacts` and similar endpoints began returning 500 with
`sqlite3.ProgrammingError: SQLite objects created in a thread can only be
used in that same thread`.

Cause: FastAPI runs sync-generator dependencies via
`contextmanager_in_threadpool`. The setup half (before `yield`) and the
teardown half (`conn.close()`) can land on different threads from the
threadpool, and SQLite's default thread-affinity check raises on close.

Fix: `backend/api/deps.py` now passes `check_same_thread=False`. Safe here
because each connection lives for one request and is never accessed
concurrently across threads — the flag only relaxes the assertion, not the
underlying concurrency model.

### Feature: contact-level voiceprint confidence

The contact UI had a placeholder reading "Voiceprint not yet computed —
backend doesn't return contact-level confidence yet". Implemented as the
**mean pairwise cosine across the contact's voice profiles**, in [0, 1]:

- 0 profiles → 0.0 (sentinel: UI shows "not yet computed")
- 1 profile → 0.0 (one vector can't measure self-coherence; matches the
  existing UX where "Update profile" is disabled below 2)
- ≥2 profiles → mean of the C(n,2) upper-triangle entries of `M @ Mᵀ` after
  L2-normalisation

Zero-norm embeddings are filtered before averaging, so junk vectors from
the 256ms-flush bug don't drag the contact's confidence to 0.

Wired through:

- `backend/storage/contact_repo.py:_compute_confidence`
- `ContactOut.confidence: float = 0.0` in `backend/api/schemas.py`
- `ApiContact.confidence` and the `adaptContact` mapper on the frontend

Tests in `backend/tests/test_contact_repo.py` cover the four edge cases
(0/1/many profiles, identical profiles, zero-norm filtering) plus
`list_contacts` propagation.

### Feature: per-contact utterances endpoint and UI tab

Contact pages now have an **Utterances / Репліки** tab listing every
utterance attributed to that contact across all sessions, ordered
newest-session-first then chronological inside the session.

- `GET /contacts/{id}/utterances` → `list[UtteranceOut]`
- `SessionRepo.list_utterances_for_contact(contact_id)` joins
  `utterances → speaker_segments → sessions` and filters on `contact_id`
- The shared `UtteranceOut` schema gained Null-safe handling for
  `confidence` (older rows seeded without an ASR confidence value were
  failing Pydantic validation).
- Frontend: `listContactUtterances` API helper, lazy-loaded in
  `Contacts.tsx` when the user opens the tab; cancellation on
  contact-switch / unmount.
- Tests:
  `backend/tests/test_api_contacts.py::test_list_contact_utterances` (order
  + filter) and `test_list_utterances_for_unknown_contact_returns_404`.

### UI: identification-threshold slider widened to 0.00–1.00

The Settings slider was clamped to `0.60–0.95`, which hid exactly the band
where real ECAPA same-speaker matches land on noisy single-mic audio
(0.55–0.65). Now the slider spans the full cosine range; the existing
amber/green colour hints at 0.75 and 0.88 still work as visual guidance
without dictating the legal range.

### Operational: known stale config in `~/.voice-diary/config.json`

If the e2e suite was ever run against a build that pre-dates the conftest
isolation fix above, the user's `~/.voice-diary/config.json` may contain a
`database.path` pointing into `%TEMP%\tmp...\e2e.db`. Symptom: the live
backend shows phantom sessions that the canonical
`web_app/backend/voice_diary.db` doesn't have.

Recovery: edit `~/.voice-diary/config.json` and reset
`"database": {"path": "backend/voice_diary.db"}`, then restart the backend.
