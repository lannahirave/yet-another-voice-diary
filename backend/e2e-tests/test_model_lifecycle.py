"""Verificator — tests the full load / inference / unload lifecycle for every ML model.

Run order (alphabetically first in e2e-tests/):
  initial UNLOADED check  →  load  →  load idempotent  →  inference
  →  unload  →  unload idempotent  →  reload + cleanup

All models are left in UNLOADED state after this file so that
test_pipeline_ws.py can manage its own model state independently.

Requirements:
  - .venv-ml with faster-whisper, speechbrain, pyannote.audio, torch installed
  - HF_TOKEN env var set (required by pyannote/speaker-diarization-3.x)
  - docs/record_out.wav present ("hello how you are doing i am doing fine how are you")
"""
from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

_ALL_KINDS = ["asr", "embedding", "diarization"]
_LOAD_TIMEOUT_S = 600.0


async def _wait_for_state(
    client: AsyncClient,
    kind: str,
    target: str,
    timeout: float = _LOAD_TIMEOUT_S,
) -> dict:
    """Poll /models/status until ``kind`` reaches ``target`` (or ERROR)."""
    deadline = asyncio.get_event_loop().time() + timeout
    last: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get("/models/status")
        assert r.status_code == 200
        last = r.json()[kind]
        if last["state"] == target:
            return last
        if last["state"] == "ERROR":
            raise AssertionError(f"{kind} entered ERROR: {last}")
        await asyncio.sleep(0.5)
    raise AssertionError(
        f"{kind} did not reach {target} within {timeout}s; last={last}"
    )


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", _ALL_KINDS)
async def test_initially_unloaded(client: AsyncClient, kind: str) -> None:
    r = await client.get("/models/status")
    assert r.status_code == 200
    assert r.json()[kind]["state"] == "UNLOADED", (
        f"{kind} should be UNLOADED at test start; got {r.json()[kind]}"
    )


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", _ALL_KINDS)
async def test_load(client: AsyncClient, kind: str) -> None:
    r = await client.post(f"/models/{kind}/load")
    assert r.status_code == 200, f"load {kind} failed: {r.text}"
    # Background load — accept LOADING or LOADED here; poll until LOADED below.
    assert r.json()["state"] in {"LOADING", "LOADED"}, r.json()
    await _wait_for_state(client, kind, "LOADED")


@pytest.mark.parametrize("kind", _ALL_KINDS)
async def test_load_is_idempotent(client: AsyncClient, kind: str) -> None:
    # Already LOADED from previous test; second load is a no-op returning LOADED.
    r = await client.post(f"/models/{kind}/load")
    assert r.status_code == 200
    assert r.json()["state"] == "LOADED"


# ---------------------------------------------------------------------------
# Inference — real audio through each provider
# ---------------------------------------------------------------------------


async def test_asr_transcribes_real_audio(
    e2e_app: FastAPI, wav_f32: np.ndarray
) -> None:
    provider = e2e_app.state.providers["asr"]
    result = provider.transcribe(wav_f32, language_hint="en")
    assert result.transcript.strip() != "", "ASR returned empty transcript"
    assert "hello" in result.transcript.lower(), (
        f"Expected 'hello' in transcript, got: {result.transcript!r}"
    )


async def test_embedding_produces_unit_vector(
    e2e_app: FastAPI, wav_f32: np.ndarray
) -> None:
    provider = e2e_app.state.providers["embedding"]
    vec = provider.embed(wav_f32)
    assert vec.ndim == 1, f"Expected 1-D vector, got shape {vec.shape}"
    assert vec.shape[0] == 192, f"Expected 192-dim ECAPA embedding, got {vec.shape[0]}"
    norm = float(np.linalg.norm(vec))
    assert abs(norm - 1.0) < 1e-4, f"Expected unit vector (norm≈1), got norm={norm:.6f}"


async def test_diarization_detects_at_least_one_speaker(
    e2e_app: FastAPI, wav_f32: np.ndarray
) -> None:
    provider = e2e_app.state.providers["diarization"]
    segments = provider.segment(wav_f32)
    assert len(segments) >= 1, "Diarization found no speaker segments in real audio"


# ---------------------------------------------------------------------------
# Status endpoint reflects loaded state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", _ALL_KINDS)
async def test_status_shows_loaded(client: AsyncClient, kind: str) -> None:
    r = await client.get("/models/status")
    assert r.json()[kind]["state"] == "LOADED"


# ---------------------------------------------------------------------------
# Unload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", _ALL_KINDS)
async def test_unload(client: AsyncClient, kind: str) -> None:
    r = await client.post(f"/models/{kind}/unload")
    assert r.status_code == 200
    assert r.json()["state"] == "UNLOADED", r.json()


@pytest.mark.parametrize("kind", _ALL_KINDS)
async def test_unload_is_idempotent(client: AsyncClient, kind: str) -> None:
    r = await client.post(f"/models/{kind}/unload")
    assert r.status_code == 200
    assert r.json()["state"] == "UNLOADED"


# ---------------------------------------------------------------------------
# Reload — verify models can be loaded again after unload; cleanup after
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", _ALL_KINDS)
async def test_reload_after_unload(client: AsyncClient, kind: str) -> None:
    r = await client.post(f"/models/{kind}/load")
    assert r.status_code == 200
    assert r.json()["state"] in {"LOADING", "LOADED"}
    await _wait_for_state(client, kind, "LOADED")
    cleanup = await client.post(f"/models/{kind}/unload")
    assert cleanup.json()["state"] == "UNLOADED"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_unknown_kind_load_returns_404(client: AsyncClient) -> None:
    r = await client.post("/models/nonexistent/load")
    assert r.status_code == 404


async def test_unknown_kind_unload_returns_404(client: AsyncClient) -> None:
    r = await client.post("/models/nonexistent/unload")
    assert r.status_code == 404


async def test_unknown_kind_status_absent_from_map(client: AsyncClient) -> None:
    r = await client.get("/models/status")
    assert "nonexistent" not in r.json()


# ---------------------------------------------------------------------------
# Download-progress SSE — placeholder implementation emits one state snapshot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", _ALL_KINDS)
async def test_download_progress_emits_snapshot_when_unloaded(
    client: AsyncClient, kind: str
) -> None:
    # Models are UNLOADED after the cleanup in test_reload_after_unload.
    r = await client.get(f"/models/{kind}/download-progress")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert body.startswith("data: ")
    payload = json.loads(body[len("data: "):].strip())
    assert payload["kind"] == kind
    assert payload["state"] == "UNLOADED"
    assert payload["progress"] == 0.0


async def test_download_progress_reports_loaded_after_load(
    client: AsyncClient,
) -> None:
    await client.post("/models/asr/load")
    await _wait_for_state(client, "asr", "LOADED")
    try:
        r = await client.get("/models/asr/download-progress")
        assert r.status_code == 200
        # Body may contain multiple SSE events when LOADING was observed during
        # streaming; the final event must report LOADED with progress == 1.0.
        events = [
            json.loads(line[len("data: "):].strip())
            for line in r.text.splitlines()
            if line.startswith("data: ")
        ]
        assert events, f"no SSE events in response: {r.text!r}"
        last = events[-1]
        assert last["state"] == "LOADED"
        assert last["progress"] == 1.0
        assert last["model_id"]
    finally:
        await client.post("/models/asr/unload")


async def test_download_progress_unknown_kind_returns_404(
    client: AsyncClient,
) -> None:
    r = await client.get("/models/nonexistent/download-progress")
    assert r.status_code == 404
