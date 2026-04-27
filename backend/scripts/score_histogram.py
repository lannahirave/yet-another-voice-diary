"""Dump cosine-similarity distributions for same- vs different-speaker pairs.

Reads ``voice_profiles`` and resolved ``speaker_segments`` from the SQLite DB,
computes cosine similarity for every (segment, profile) pair, and prints
SAME-speaker vs DIFF-speaker statistics plus ASCII histograms. Use the
crossover region of the two distributions to pick a threshold instead of the
hard-coded default in ``config.py``.

Usage:
    python -m backend.scripts.score_histogram [path/to/voice_diary.db]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict

import numpy as np


def _decode(blob: bytes | memoryview) -> np.ndarray:
    return np.frombuffer(bytes(blob), dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _stats(name: str, xs: list[float]) -> None:
    if not xs:
        print(f"{name}: no data")
        return
    a = np.asarray(xs)
    print(
        f"{name}: n={len(a)} "
        f"min={a.min():.3f} p05={np.percentile(a, 5):.3f} "
        f"p25={np.percentile(a, 25):.3f} median={np.median(a):.3f} "
        f"p75={np.percentile(a, 75):.3f} p95={np.percentile(a, 95):.3f} "
        f"max={a.max():.3f}"
    )


def _histogram(name: str, xs: list[float], bins: int = 20) -> None:
    if not xs:
        return
    counts, edges = np.histogram(xs, bins=bins, range=(0.0, 1.0))
    peak = int(counts.max()) or 1
    print(f"\n{name} histogram (0.0-1.0):")
    for c, lo, hi in zip(counts, edges[:-1], edges[1:]):
        bar = "#" * int(40 * c / peak)
        print(f"  [{lo:.2f}-{hi:.2f}] {int(c):5d} {bar}")


def _suggest_threshold(same: list[float], diff: list[float]) -> None:
    if not same or not diff:
        return
    same_arr = np.asarray(same)
    diff_arr = np.asarray(diff)
    print("\nThreshold suggestions (cosine):")
    print(f"  SAME p05  = {np.percentile(same_arr, 5):.3f}  "
          "(below this rejects 5% of true matches)")
    print(f"  DIFF p95  = {np.percentile(diff_arr, 95):.3f}  "
          "(above this admits 5% of impostors)")
    print(f"  DIFF p99  = {np.percentile(diff_arr, 99):.3f}  "
          "(above this admits 1% of impostors)")
    grid = np.linspace(0.30, 0.95, 66)
    best_t, best_acc = None, -1.0
    for t in grid:
        tp = float((same_arr >= t).mean())
        tn = float((diff_arr < t).mean())
        acc = 0.5 * (tp + tn)
        if acc > best_acc:
            best_acc, best_t = acc, float(t)
    if best_t is not None:
        tp = float((same_arr >= best_t).mean())
        tn = float((diff_arr < best_t).mean())
        print(
            f"  balanced-accuracy peak at t={best_t:.3f}  "
            f"(true-accept={tp:.1%}, true-reject={tn:.1%})"
        )


def main(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    profiles: dict[str, list[np.ndarray]] = defaultdict(list)
    for r in conn.execute(
        "SELECT contact_id, embedding FROM voice_profiles "
        "WHERE embedding IS NOT NULL"
    ):
        emb = _decode(r["embedding"])
        if emb.size > 0 and float(np.linalg.norm(emb)) > 0.0:
            profiles[r["contact_id"]].append(emb)

    segments = list(conn.execute(
        """SELECT id, contact_id, embedding FROM speaker_segments
           WHERE status='identified'
             AND embedding IS NOT NULL
             AND contact_id IS NOT NULL"""
    ))

    profile_count = sum(len(v) for v in profiles.values())
    print(
        f"db={db_path}\n"
        f"profiles={profile_count} contacts={len(profiles)} "
        f"resolved_segments={len(segments)}"
    )
    if profile_count == 0 or not segments:
        print("not enough data to compute distributions")
        return 1

    same: list[float] = []
    diff: list[float] = []
    skipped_zero = 0
    for seg in segments:
        seg_emb = _decode(seg["embedding"])
        if seg_emb.size == 0 or float(np.linalg.norm(seg_emb)) == 0.0:
            skipped_zero += 1
            continue
        for cid, embs in profiles.items():
            for p in embs:
                score = _cosine(seg_emb, p)
                (same if cid == seg["contact_id"] else diff).append(score)

    if skipped_zero:
        print(f"skipped {skipped_zero} zero-norm segment embeddings")

    _stats("SAME-speaker", same)
    _stats("DIFF-speaker", diff)
    _histogram("SAME", same)
    _histogram("DIFF", diff)
    _suggest_threshold(same, diff)

    unknown_rows = list(conn.execute(
        """SELECT id, embedding FROM speaker_segments
           WHERE status='unknown' AND embedding IS NOT NULL"""
    ))
    if unknown_rows and profile_count > 0:
        print(
            f"\n--- Unresolved segments scored against existing profiles "
            f"(n={len(unknown_rows)}) ---"
        )
        unknown_best: list[float] = []
        for row in unknown_rows:
            seg_emb = _decode(row["embedding"])
            if seg_emb.size == 0 or float(np.linalg.norm(seg_emb)) == 0.0:
                print(f"  segment {row['id'][:8]}: zero-norm embedding")
                continue
            best_cid: str | None = None
            best_score = -1.0
            for cid, embs in profiles.items():
                for p in embs:
                    s = _cosine(seg_emb, p)
                    if s > best_score:
                        best_score, best_cid = s, cid
            unknown_best.append(best_score)
            print(
                f"  segment {row['id'][:8]} -> best_contact={best_cid[:8] if best_cid else None} "
                f"score={best_score:.3f}"
            )
        _stats("UNKNOWN best-score", unknown_best)
        _histogram("UNKNOWN best-score", unknown_best)
    return 0


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "backend/voice_diary.db"
    raise SystemExit(main(db))
