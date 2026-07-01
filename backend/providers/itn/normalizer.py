"""Map ASR transliterations to display terms after transcription."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_MAP_DIR = Path(__file__).resolve().parent
_WORD_BOUNDARY = r"[\w]"
_WHITESPACE_RE = re.compile(r"\s+")


class ITNNormalizer:
    """Inverse text normalizer backed by JSON transliteration maps."""

    def __init__(self, map_dir: Path | None = None) -> None:
        self.map_dir = map_dir or _DEFAULT_MAP_DIR
        self._replacement_by_variant: dict[str, str] = {}
        self._pattern: re.Pattern[str] | None = None
        self._loaded = False

    def normalize(self, text: str) -> str:
        """Return text with known transliterations replaced by display terms."""
        if not text:
            return text
        self._ensure_loaded()
        if self._pattern is None:
            return text

        def replace(match: re.Match[str]) -> str:
            key = _WHITESPACE_RE.sub(" ", match.group(0)).casefold()
            return self._replacement_by_variant.get(key, match.group(0))

        return self._pattern.sub(replace, text)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._replacement_by_variant = self._load_maps()
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

    def _load_maps(self) -> dict[str, str]:
        replacement_by_variant: dict[str, str] = {}
        if not self.map_dir.is_dir():
            log.warning("ITN map directory not found: %s", self.map_dir)
            return replacement_by_variant

        for path in sorted(self.map_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                transliterations = raw.get("transliterations")
                if not isinstance(transliterations, dict):
                    raise ValueError("missing transliterations object")
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


def normalize_transcript(text: str) -> str:
    """Normalize transcript text using the default backend ITN maps."""
    return _DEFAULT_NORMALIZER.normalize(text)
