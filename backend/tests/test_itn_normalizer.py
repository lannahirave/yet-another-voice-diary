from __future__ import annotations

import json
from pathlib import Path

from backend.providers.itn.normalizer import ITNNormalizer


def _write_map(path: Path, transliterations: dict[str, list[str]]) -> None:
    path.write_text(
        json.dumps(
            {
                "source_language": "uk",
                "target_language": "en",
                "transliteration_type": "ITN",
                "transliterations": transliterations,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_normalizer_replaces_single_word_variant(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api": ["апі"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("підключи апі") == "підключи api"


def test_normalizer_replaces_multi_word_variant(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api": ["ей пі ай"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("перевір ей пі ай") == "перевір api"


def test_normalizer_prefers_longest_variant(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api client": ["апі клієнт"], "api": ["апі"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("апі клієнт готовий") == "api client готовий"


def test_normalizer_does_not_replace_inside_larger_word(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api": ["апі"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("суперапі апі") == "суперапі api"


def test_normalizer_preserves_punctuation_around_replacement(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api": ["апі"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("апі, будь ласка.") == "api, будь ласка."


def test_normalizer_degrades_to_original_text_for_missing_or_malformed_maps(
    tmp_path: Path,
) -> None:
    missing = ITNNormalizer(tmp_path / "missing")
    assert missing.normalize("апі") == "апі"

    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    malformed = ITNNormalizer(tmp_path)
    assert malformed.normalize("апі") == "апі"
