"""Model lifecycle endpoints with background loading and progress streaming."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..schemas import ProviderStatus

router = APIRouter()
log = logging.getLogger(__name__)


# Approximate worst-case load duration (s) used for progress interpolation when
# the underlying provider has no real progress hook. Progress climbs linearly
# toward 0.95 over this window, then jumps to 1.0 on completion.
_LOAD_RAMP_SECONDS = 10.0


@dataclass
class _LoadState:
    """Per-kind load tracking on app.state."""
    progress: float = 0.0
    started_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)
    event: threading.Event = field(default_factory=threading.Event)


def _states(request: Request) -> dict[str, _LoadState]:
    states = getattr(request.app.state, "load_states", None)
    if states is None:
        states = {kind: _LoadState() for kind in request.app.state.providers}
        request.app.state.load_states = states
    return states


def _provider(request: Request, kind: str):
    providers = request.app.state.providers
    if kind not in providers:
        raise HTTPException(status_code=404, detail=f"unknown model kind: {kind}")
    return providers[kind]


def _provider_state(provider: object) -> str:
    state = getattr(provider, "_state", None)
    if state is None:
        state = "LOADED" if getattr(provider, "_model", None) is not None else "UNLOADED"
    return str(state)


def _interp_progress(load: _LoadState, provider_state: str) -> float:
    if provider_state == "LOADED":
        return 1.0
    if provider_state == "ERROR":
        return load.progress
    if provider_state == "LOADING":
        if load.started_at <= 0:
            return max(load.progress, 0.05)
        elapsed = max(0.0, time.monotonic() - load.started_at)
        ramp = min(0.95, 0.05 + 0.9 * (elapsed / _LOAD_RAMP_SECONDS))
        return max(load.progress, ramp)
    return 0.0


def _provider_status(kind: str, provider: object) -> ProviderStatus:
    model_id = _provider_model_id(provider)
    return ProviderStatus(
        kind=kind,
        model_id=model_id,
        state=_provider_state(provider),
        error=getattr(provider, "_error", None),
    )


def _provider_model_id(provider: object) -> str:
    return str(getattr(provider, "model_id", None) or getattr(provider, "model_size", "") or "")


@router.get("/status", response_model=dict[str, ProviderStatus])
def model_status(request: Request):
    return {
        kind: _provider_status(kind, provider)
        for kind, provider in request.app.state.providers.items()
    }


def _run_load(kind: str, provider: object, load: _LoadState) -> None:
    """Body of the background load thread."""
    started_at = time.monotonic()
    model_id = _provider_model_id(provider)
    try:
        load.progress = 0.05
        load.started_at = started_at
        load.event.clear()
        if hasattr(provider, "load"):
            provider.load()
        elif hasattr(provider, "_load_model"):
            provider._load_model()
        load.progress = 1.0
        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        log.info(
            "model loaded kind=%s model_id=%s provider=%s elapsed_ms=%.2f state=%s",
            kind,
            model_id,
            type(provider).__name__,
            elapsed_ms,
            _provider_state(provider),
        )
    except Exception as exc:
        # Provider already sets _state=ERROR and _error. Make sure progress
        # is non-zero so the SSE consumer can surface the error.
        if not getattr(provider, "_error", None):
            try:
                provider._error = str(exc)  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            provider._state = "ERROR"  # type: ignore[attr-defined]
        except Exception:
            pass
        load.progress = max(load.progress, 0.05)
        log.exception("background model load failed")
    finally:
        load.event.set()


@router.post("/{kind}/load", response_model=ProviderStatus)
def load_model(kind: str, request: Request):
    provider = _provider(request, kind)
    load = _states(request)[kind]

    with load.lock:
        state = _provider_state(provider)
        if state == "LOADING":
            return _provider_status(kind, provider)
        if state == "LOADED":
            load.progress = 1.0
            log.info(
                "model load skipped kind=%s model_id=%s provider=%s state=LOADED",
                kind,
                _provider_model_id(provider),
                type(provider).__name__,
            )
            return _provider_status(kind, provider)

        # mark LOADING immediately so concurrent calls observe it
        try:
            provider._state = "LOADING"  # type: ignore[attr-defined]
            provider._error = None  # type: ignore[attr-defined]
        except Exception:
            pass
        load.progress = 0.05
        load.started_at = time.monotonic()
        load.event.clear()

        thread = threading.Thread(
            target=_run_load,
            args=(kind, provider, load),
            name=f"load-{kind}",
            daemon=True,
        )
        thread.start()

    return _provider_status(kind, provider)


@router.post("/{kind}/unload", response_model=ProviderStatus)
def unload_model(kind: str, request: Request):
    provider = _provider(request, kind)
    load = _states(request)[kind]
    if _provider_state(provider) == "LOADING":
        raise HTTPException(status_code=409, detail="model is currently loading")
    # Wait for any background load thread to fully finish — CTranslate2
    # WhisperModel.__del__ can crash (STATUS_STACK_BUFFER_OVERRUN) if we
    # yank the reference out from under an in-progress C extension init.
    load.event.wait(timeout=2.0)
    if hasattr(provider, "unload"):
        provider.unload()
    else:
        provider._model = None
        provider._state = "UNLOADED"
        provider._error = None
    load.progress = 0.0
    load.started_at = 0.0
    load.event.set()
    return _provider_status(kind, provider)


@router.get("/{kind}/download-progress")
async def download_progress(kind: str, request: Request):
    provider = _provider(request, kind)
    load = _states(request)[kind]

    def snapshot() -> dict:
        state = _provider_state(provider)
        return {
            "kind": kind,
            "model_id": str(
                getattr(provider, "model_id", None)
                or getattr(provider, "model_size", "")
                or ""
            ),
            "progress": _interp_progress(load, state),
            "state": state,
            "message": getattr(provider, "_error", None) or "",
        }

    async def events() -> AsyncIterator[str]:
        # Always emit current snapshot first.
        yield f"data: {json.dumps(snapshot())}\n\n"

        # Stream progress while LOADING, then a final snapshot.
        last_progress = -1.0
        last_state = _provider_state(provider)
        while last_state == "LOADING":
            await asyncio.sleep(0.5)
            if await request.is_disconnected():
                return
            current = snapshot()
            if (
                current["state"] != last_state
                or abs(current["progress"] - last_progress) >= 0.02
            ):
                yield f"data: {json.dumps(current)}\n\n"
                last_progress = current["progress"]
                last_state = current["state"]

        if last_state != snapshot()["state"]:
            yield f"data: {json.dumps(snapshot())}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
