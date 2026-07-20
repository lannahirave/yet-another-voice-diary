"""Tests for configuration."""
import json
from pathlib import Path

from backend.config import (
    BackendConfig,
    DatabaseConfig,
    PipelineConfig,
    ProviderConfig,
)


def test_runtime_config_persists_absolute_database_path(
    tmp_path: Path, monkeypatch
) -> None:
    from backend.api.app import _load_runtime_config

    config_path = tmp_path / "config.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        BackendConfig, "default_path", staticmethod(lambda: config_path)
    )

    loaded = _load_runtime_config(None)

    expected = (tmp_path / "backend" / "voice_diary.db").resolve()
    assert loaded.database.path == expected
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert Path(saved["database"]["path"]) == expected


def test_default_config():
    """Test default configuration."""
    config = BackendConfig.default()
    assert config.database is not None
    assert config.pipeline is not None
    assert config.pipeline.speaker_identification_threshold == 0.5
    assert config.pipeline.vad_min_utterance_ms == 100
    assert config.pipeline.vad_max_utterance_ms == 8_000
    assert config.pipeline.blocklist_enabled is True
    assert config.providers.preload_on_start is True


def test_custom_config():
    """Test custom configuration."""
    db_config = DatabaseConfig(path=None)
    pipeline_config = PipelineConfig(vad_threshold=0.6)
    config = BackendConfig(database=db_config, pipeline=pipeline_config)

    assert config.pipeline.vad_threshold == 0.6


def test_config_save_and_load(tmp_path):
    """Config round-trips through JSON persistence."""
    config = BackendConfig.default()
    config.database.path = tmp_path / "voice_diary.db"
    config.pipeline.speaker_identification_threshold = 0.91
    config.pipeline.itn_enabled = False
    config.pipeline.itn_selected_maps = ["custom.json"]
    config.providers.asr_model_id = "whisper-tiny"

    path = tmp_path / "config.json"
    config.save(path)
    loaded = BackendConfig.load(path)

    assert loaded.database.path == Path(tmp_path / "voice_diary.db")
    assert loaded.pipeline.speaker_identification_threshold == 0.91
    assert loaded.pipeline.itn_enabled is False
    assert loaded.pipeline.itn_selected_maps == ["custom.json"]
    assert loaded.providers.asr_model_id == "whisper-tiny"


def test_invalid_diarization_model_id_normalizes_to_pyannote():
    providers = ProviderConfig(diarization_model_id="nemo")

    assert providers.diarization_model_id == "pyannote"


def test_invalid_embedding_model_id_normalizes_to_ecapa():
    providers = ProviderConfig(embedding_model_id="unsupported-embedding")

    assert providers.embedding_model_id == "ecapa"


def test_sortformer_diarization_model_id_is_preserved():
    providers = ProviderConfig(diarization_model_id="sortformer-v2.1")

    assert providers.diarization_model_id == "sortformer-v2.1"


def test_firered_vad_model_id_roundtrips_through_json(tmp_path):
    config = BackendConfig.default()
    config.providers.vad_model_id = "firered-stream-vad"
    path = tmp_path / "config.json"

    config.save(path)
    loaded = BackendConfig.load(path)

    assert loaded.providers.vad_model_id == "firered-stream-vad"


def test_invalid_vad_model_id_normalizes_to_silero():
    providers = ProviderConfig(vad_model_id="legacy-unknown-vad")

    assert providers.vad_model_id == "silero"


def test_load_rewrites_legacy_invalid_diarization_model_id(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        """
{
  "database": {"path": "backend/voice_diary.db", "echo": false},
  "pipeline": {
    "vad_threshold": 0.5,
    "vad_min_silence_ms": 500,
    "vad_speech_pad_ms": 200,
    "vad_min_utterance_ms": 300,
    "vad_max_utterance_ms": 30000,
    "speaker_identification_threshold": 0.5,
    "chunk_duration_ms": 100,
    "unload_models_after_stop": false
  },
  "providers": {
    "asr_model_id": "large-v3-turbo",
    "diarization_model_id": "nemo",
    "embedding_model_id": "ecapa"
  }
}
""".strip(),
        encoding="utf-8",
    )

    loaded = BackendConfig.load(path)

    assert loaded.providers.diarization_model_id == "pyannote"
    assert loaded.pipeline.itn_enabled is True
    assert loaded.pipeline.itn_selected_maps is None
    assert '"diarization_model_id": "pyannote"' in path.read_text(encoding="utf-8")


def test_load_rewrites_legacy_invalid_embedding_model_id(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        """
{
  "database": {"path": "backend/voice_diary.db", "echo": false},
  "pipeline": {
    "vad_threshold": 0.5,
    "vad_min_silence_ms": 500,
    "vad_speech_pad_ms": 200,
    "vad_min_utterance_ms": 300,
    "vad_max_utterance_ms": 30000,
    "speaker_identification_threshold": 0.5,
    "chunk_duration_ms": 100,
    "unload_models_after_stop": false
  },
  "providers": {
    "asr_model_id": "large-v3-turbo",
    "diarization_model_id": "pyannote",
    "embedding_model_id": "unsupported-embedding"
  }
}
""".strip(),
        encoding="utf-8",
    )

    loaded = BackendConfig.load(path)

    assert loaded.providers.embedding_model_id == "ecapa"
    assert '"embedding_model_id": "ecapa"' in path.read_text(encoding="utf-8")
