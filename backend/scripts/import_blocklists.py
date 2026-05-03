"""Import Whisper hallucination blocklists from upstream sources.

Sources:
  - HF dataset: https://huggingface.co/datasets/sachaarbonel/whisper-hallucinations
    (CSV with lang,phrase,count columns)
  - Russian gist: https://gist.githubusercontent.com/waveletdeboshir/8bf52f04bf78018194f25b2390c08309/raw/...
    (one phrase per line)

Usage:
    python import_blocklists.py phrases.csv              # CSV mode
    python import_blocklists.py ru_phrases.txt --lang ru  # single-language mode
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


BLOCKLIST_DIR = Path(__file__).resolve().parent.parent / "providers" / "blocklists"
# Only languages with >= this many phrases are kept
MIN_PHRASE_LENGTH = 2  # ignore single-char noise


def _normalize(text: str) -> str:
    """Normalize a phrase: lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    # Remove common punctuation but keep letters/digits/whitespace
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _write_blocklist(lang: str, phrases: set[str]) -> int:
    """Write a per-language blocklist file. Returns number of phrases written."""
    if not phrases:
        return 0
    lang = lang.lower()
    BLOCKLIST_DIR.mkdir(parents=True, exist_ok=True)
    filepath = BLOCKLIST_DIR / f"{lang}.txt"
    sorted_phrases = sorted(phrases)
    filepath.write_text("\n".join(sorted_phrases) + "\n", encoding="utf-8")
    return len(sorted_phrases)


def import_csv(csv_path: str) -> None:
    """Import from the HF dataset CSV (lang,phrase,count)."""
    phrase_map: dict[str, set[str]] = {}
    skipped = 0
    total = 0

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header != ["lang", "phrase", "count"]:
            print(f"[WARN] Unexpected header: {header}, continuing anyway")

        for row in reader:
            if len(row) < 2:
                continue
            total += 1
            lang, phrase = row[0].strip().lower(), row[1]
            normalized = _normalize(phrase)
            if len(normalized) < MIN_PHRASE_LENGTH:
                skipped += 1
                continue
            if re.fullmatch(r"\d+", normalized):  # pure numbers
                skipped += 1
                continue
            phrase_map.setdefault(lang, set()).add(normalized)

    total_written = 0
    for lang, phrases in sorted(phrase_map.items()):
        count = _write_blocklist(lang, phrases)
        print(f"  {lang}: {count} phrases")
        total_written += count

    print(f"Total: {total_written} phrases across {len(phrase_map)} languages "
          f"({total} raw, {skipped} skipped)")


def import_single(text_path: str, lang: str) -> None:
    """Import from a plain text file (one phrase per line)."""
    phrases: set[str] = set()
    skipped = 0
    total = 0

    with open(text_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            total += 1
            normalized = _normalize(line)
            if len(normalized) < MIN_PHRASE_LENGTH:
                skipped += 1
                continue
            phrases.add(normalized)

    count = _write_blocklist(lang, phrases)
    print(f"  {lang}: {count} phrases ({total} raw, {skipped} skipped)")


def import_from_url(url: str, lang: str = "") -> None:
    """Download and import from a URL. Auto-detects CSV vs plain text."""
    import urllib.request

    print(f"Fetching {url}...")
    data = urllib.request.urlopen(url).read().decode("utf-8")

    if url.endswith(".csv") or data.startswith("lang,phrase,count"):
        # CSV mode
        tmp = BLOCKLIST_DIR / "_tmp.csv"
        tmp.write_text(data, encoding="utf-8")
        try:
            import_csv(str(tmp))
        finally:
            tmp.unlink()
    elif "\n" in data.split("\n")[0] is not None:
        # Plain text, single language
        assert lang, "--lang required for plain text URLs"
        tmp = BLOCKLIST_DIR / f"_tmp_{lang}.txt"
        tmp.write_text(data, encoding="utf-8")
        try:
            import_single(str(tmp), lang)
        finally:
            tmp.unlink()
    else:
        print("[ERROR] Unknown format")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    source = sys.argv[1]

    if source.startswith("http://") or source.startswith("https://"):
        lang = ""
        args = sys.argv[2:]
        if "--lang" in args:
            idx = args.index("--lang")
            lang = args[idx + 1]
        import_from_url(source, lang)
    elif source.endswith(".csv"):
        import_csv(source)
    else:
        lang = "en"
        args = sys.argv[2:]
        if "--lang" in args:
            idx = args.index("--lang")
            lang = args[idx + 1]
        import_single(source, lang)
