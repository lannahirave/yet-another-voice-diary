from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_nemo_sortformer_import_survives_preloaded_speechbrain():
    web_app = Path(__file__).parents[2]

    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(web_app / "backend" / "scripts" / "verify_nemo_sortformer.py"),
        ],
        cwd=web_app,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "NeMo Sortformer import: OK" in result.stdout


def test_nemo_sortformer_provider_load_survives_preloaded_speechbrain():
    web_app = Path(__file__).parents[2]
    script = """
import speechbrain
from types import SimpleNamespace
from backend.providers.diarization import (
    NeMoSortformerDiarizationProvider,
    import_nemo_sortformer_class,
)

sortformer_cls = import_nemo_sortformer_class()
original = sortformer_cls.from_pretrained

class FakeModel:
    def __init__(self):
        self.sortformer_modules = SimpleNamespace()

    def eval(self):
        return None

try:
    sortformer_cls.from_pretrained = classmethod(lambda cls, repo_id: FakeModel())
    provider = NeMoSortformerDiarizationProvider()
    provider.load()
    print(provider._state)
finally:
    sortformer_cls.from_pretrained = original
"""

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        cwd=web_app,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "LOADED" in result.stdout


def test_speechbrain_embedding_receives_indexed_cuda_device():
    web_app = Path(__file__).parents[2]
    script = """
from backend.providers.embedding import ECAPATDNNEmbeddingProvider
from speechbrain.inference import SpeakerRecognition

original = SpeakerRecognition.from_hparams

class FakeModel:
    pass

def fake_from_hparams(*args, **kwargs):
    print(f"DEVICE={kwargs['run_opts']['device']}")
    return FakeModel()

try:
    SpeakerRecognition.from_hparams = staticmethod(fake_from_hparams)
    provider = ECAPATDNNEmbeddingProvider(device="cuda")
    provider.load()
    print(provider._state)
finally:
    SpeakerRecognition.from_hparams = original
"""

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        cwd=web_app,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "DEVICE=cuda:0" in result.stdout
    assert "LOADED" in result.stdout


def test_pyannote_diarization_receives_indexed_cuda_device():
    web_app = Path(__file__).parents[2]
    script = """
from backend.providers.diarization import PyAnnoteDiarizationProvider
from pyannote.audio import Pipeline

original = Pipeline.from_pretrained

class FakePipeline:
    def to(self, device):
        print(f"DEVICE={device}")
        return self

try:
    Pipeline.from_pretrained = staticmethod(lambda *args, **kwargs: FakePipeline())
    provider = PyAnnoteDiarizationProvider(device="cuda")
    provider.load()
    print(provider._state)
finally:
    Pipeline.from_pretrained = original
"""

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        cwd=web_app,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "DEVICE=cuda:0" in result.stdout
    assert "LOADED" in result.stdout
