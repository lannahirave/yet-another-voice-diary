"""Map ASR transliterations to display terms after transcription."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_MAP_DIR = Path(__file__).resolve().parent
_WORD_BOUNDARY = r"[\w]"
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ITNMapInfo:
    filename: str
    label: str
    valid: bool
    variant_count: int = 0
    error: str | None = None


def discover_itn_maps(map_dir: Path | None = None) -> list[ITNMapInfo]:
    """Return validation metadata for ITN JSON maps in the map directory."""
    source_dir = map_dir or _DEFAULT_MAP_DIR
    if not source_dir.is_dir():
        log.warning("ITN map directory not found: %s", source_dir)
        return []

    maps: list[ITNMapInfo] = []
    for path in sorted(source_dir.glob("*.json")):
        maps.append(_inspect_map(path))
    return maps


def resolve_selected_itn_maps(
    selected_maps: list[str] | None,
    map_dir: Path | None = None,
) -> list[str]:
    """Resolve a selection into concrete valid map filenames."""
    valid = [info.filename for info in discover_itn_maps(map_dir) if info.valid]
    if selected_maps is None:
        return valid
    selected = set(selected_maps)
    return [filename for filename in valid if filename in selected]


def validate_selected_itn_maps(
    selected_maps: list[str] | None,
    map_dir: Path | None = None,
) -> list[str]:
    """Return invalid selected filenames, including path traversal attempts."""
    if selected_maps is None:
        return []
    known_valid = {info.filename for info in discover_itn_maps(map_dir) if info.valid}
    invalid: list[str] = []
    for filename in selected_maps:
        if Path(filename).name != filename or filename not in known_valid:
            invalid.append(filename)
    return invalid


class ITNNormalizer:
    """Inverse text normalizer backed by JSON transliteration maps."""

    def __init__(self, map_dir: Path | None = None) -> None:
        self.map_dir = map_dir or _DEFAULT_MAP_DIR
        self._replacement_by_variant: dict[str, str] = {}
        self._pattern: re.Pattern[str] | None = None
        self._loaded_selection: tuple[str, ...] | None | object = object()

    def normalize(self, text: str, selected_maps: list[str] | None = None) -> str:
        """Return text with known transliterations replaced by display terms."""
        if not text:
            return text
        self._ensure_loaded(selected_maps)
        if self._pattern is None:
            return text

        def replace(match: re.Match[str]) -> str:
            key = _WHITESPACE_RE.sub(" ", match.group(0)).casefold()
            return self._replacement_by_variant.get(key, match.group(0))

        return self._pattern.sub(replace, text)

    def _ensure_loaded(self, selected_maps: list[str] | None) -> None:
        selection_key: tuple[str, ...] | None
        if selected_maps is None:
            selection_key = None
        else:
            selection_key = tuple(sorted(selected_maps))
        if self._loaded_selection == selection_key:
            return
        self._loaded_selection = selection_key
        self._pattern = None
        self._replacement_by_variant = self._load_maps(selected_maps)
        if not self._replacement_by_variant:
            return

        alternatives = [
            re.escape(variant).replace(r"\ ", r"\s+")
            for variant in sorted(
                self._replacement_by_variant,
                key=lambda item: (len(item), item),
                reverse=True,
            )
        ]
        self._pattern = re.compile(
            rf"(?<!{_WORD_BOUNDARY})(?:{'|'.join(alternatives)})(?!{_WORD_BOUNDARY})",
            re.IGNORECASE | re.UNICODE,
        )

    def _load_maps(self, selected_maps: list[str] | None) -> dict[str, str]:
        replacement_by_variant: dict[str, str] = {}
        if not self.map_dir.is_dir():
            log.warning("ITN map directory not found: %s", self.map_dir)
            return replacement_by_variant

        selected_filenames = resolve_selected_itn_maps(selected_maps, self.map_dir)
        for filename in selected_filenames:
            path = self.map_dir / filename
            try:
                transliterations = _load_valid_transliterations(path)
                self._merge_transliterations(replacement_by_variant, transliterations)
            except Exception as exc:
                log.warning("failed to load ITN map %s: %s", path, exc)

        if replacement_by_variant:
            log.info(
                "ITN maps loaded variants=%d map_dir=%s",
                len(replacement_by_variant),
                self.map_dir,
            )
        return replacement_by_variant

    @staticmethod
    def _merge_transliterations(
        replacement_by_variant: dict[str, str],
        transliterations: dict[str, Any],
    ) -> None:
        for display, variants in transliterations.items():
            if not isinstance(display, str) or not display:
                continue
            if not isinstance(variants, list):
                continue
            for variant in variants:
                if not isinstance(variant, str):
                    continue
                normalized_variant = variant.strip()
                if not normalized_variant:
                    continue
                key = _WHITESPACE_RE.sub(" ", normalized_variant).casefold()
                replacement_by_variant.setdefault(key, display)


_DEFAULT_NORMALIZER = ITNNormalizer()


def normalize_transcript(text: str, selected_maps: list[str] | None = None) -> str:
    """Normalize transcript text using the default backend ITN maps."""
    return _DEFAULT_NORMALIZER.normalize(text, selected_maps)


def _inspect_map(path: Path) -> ITNMapInfo:
    try:
        transliterations = _load_valid_transliterations(path)
    except Exception as exc:
        return ITNMapInfo(
            filename=path.name,
            label=path.stem,
            valid=False,
            error=str(exc),
        )
    return ITNMapInfo(
        filename=path.name,
        label=path.stem,
        valid=True,
        variant_count=_variant_count(transliterations),
    )


def _load_valid_transliterations(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("root must be an object")
    transliterations = raw.get("transliterations")
    if not isinstance(transliterations, dict):
        raise ValueError("missing transliterations object")
    if _variant_count(transliterations) <= 0:
        raise ValueError("no non-empty transliteration variants")
    return transliterations


def _variant_count(transliterations: dict[str, Any]) -> int:
    count = 0
    for display, variants in transliterations.items():
        if not isinstance(display, str) or not display:
            continue
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, str) and variant.strip():
                count += 1
    return count
