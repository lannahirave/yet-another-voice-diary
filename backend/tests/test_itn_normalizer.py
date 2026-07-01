from __future__ import annotations

import json
from pathlib import Path

from backend.providers.itn.normalizer import (
    ITNNormalizer,
    discover_itn_maps,
    resolve_selected_itn_maps,
)


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
    _write_map(tmp_path / "map.json", {"api": ["api spoken"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("connect api spoken") == "connect api"


def test_normalizer_replaces_multi_word_variant(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api": ["a p i"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("check a p i") == "check api"


def test_normalizer_prefers_longest_variant(tmp_path: Path) -> None:
    _write_map(
        tmp_path / "map.json",
        {"api client": ["api client spoken"], "api": ["api"]},
    )

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("api client spoken ready") == "api client ready"


def test_normalizer_does_not_replace_inside_larger_word(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api": ["api spoken"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("superapi spoken api spoken") == "superapi spoken api"


def test_normalizer_preserves_punctuation_around_replacement(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api": ["api spoken"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("api spoken, please.") == "api, please."


def test_normalizer_degrades_to_original_text_for_missing_or_malformed_maps(
    tmp_path: Path,
) -> None:
    missing = ITNNormalizer(tmp_path / "missing")
    assert missing.normalize("api spoken") == "api spoken"

    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    malformed = ITNNormalizer(tmp_path)
    assert malformed.normalize("api spoken") == "api spoken"


def test_discover_itn_maps_returns_valid_map_metadata(tmp_path: Path) -> None:
    _write_map(tmp_path / "map.json", {"api": ["api spoken", "api alt"]})

    maps = discover_itn_maps(tmp_path)

    assert len(maps) == 1
    assert maps[0].filename == "map.json"
    assert maps[0].label == "map"
    assert maps[0].valid is True
    assert maps[0].variant_count == 2
    assert maps[0].error is None


def test_discover_itn_maps_reports_malformed_json(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")

    maps = discover_itn_maps(tmp_path)

    assert maps[0].filename == "bad.json"
    assert maps[0].valid is False
    assert maps[0].error


def test_discover_itn_maps_reports_wrong_schema(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text(
        json.dumps({"transliterations": {"api": []}}),
        encoding="utf-8",
    )

    maps = discover_itn_maps(tmp_path)

    assert maps[0].valid is False
    assert maps[0].error == "no non-empty transliteration variants"


def test_normalizer_loads_only_selected_maps(tmp_path: Path) -> None:
    _write_map(tmp_path / "api.json", {"api": ["api spoken"]})
    _write_map(tmp_path / "sdk.json", {"sdk": ["sdk spoken"]})

    normalizer = ITNNormalizer(tmp_path)

    assert (
        normalizer.normalize("api spoken and sdk spoken", ["sdk.json"])
        == "api spoken and sdk"
    )


def test_normalizer_duplicate_variant_precedence_uses_filename_sort(
    tmp_path: Path,
) -> None:
    _write_map(tmp_path / "a.json", {"first": ["same spoken"]})
    _write_map(tmp_path / "b.json", {"second": ["same spoken"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("same spoken") == "first"


def test_resolve_selected_maps_defaults_to_all_valid_maps(tmp_path: Path) -> None:
    _write_map(tmp_path / "a.json", {"first": ["first spoken"]})
    _write_map(tmp_path / "b.json", {"second": ["second spoken"]})
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")

    assert resolve_selected_itn_maps(None, tmp_path) == ["a.json", "b.json"]


def test_normalizer_empty_selection_loads_no_maps(tmp_path: Path) -> None:
    _write_map(tmp_path / "api.json", {"api": ["api spoken"]})

    normalizer = ITNNormalizer(tmp_path)

    assert normalizer.normalize("api spoken", []) == "api spoken"
