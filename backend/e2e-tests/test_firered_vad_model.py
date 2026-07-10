from __future__ import annotations

import os

import numpy as np
import pytest

from backend.providers.vad import FireRedVADProvider


pytestmark = pytest.mark.network


@pytest.mark.skipif(
    os.environ.get("VOICE_DIARY_RUN_FIRERED_SMOKE") != "1",
    reason="set VOICE_DIARY_RUN_FIRERED_SMOKE=1 to download the pinned model",
)
def test_pinned_firered_stream_vad_model_smoke() -> None:
    provider = FireRedVADProvider()
    provider.load()
    session = provider.create_session()

    assert provider._state == "LOADED"
    assert session.process(np.zeros(1_600, dtype=np.float32), 16_000) is None
    assert session.pop_error() is None
