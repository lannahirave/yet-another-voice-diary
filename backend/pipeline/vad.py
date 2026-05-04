"""Backward-compat shim — re-exports from ``backend.providers.vad``.

The VAD implementation moved to the providers layer.  Old import paths
(e.g.  ``from backend.pipeline.vad import VADSegment, VADProcessor``)
continue to work through this module.  New code should import directly
from ``backend.providers.vad``.
"""
from __future__ import annotations

from ..providers.vad import (
    SileroVADProvider as VADProcessor,
    VADSegment,
    create_vad_provider,
)

__all__ = ["VADProcessor", "VADSegment", "create_vad_provider"]
