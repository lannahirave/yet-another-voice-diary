"""Pure clustering and turn helper regression coverage."""
from __future__ import annotations

import numpy as np
import pytest

from backend.identification.clustering import centroid, cluster_embeddings
from backend.pipeline.turns import build_turn_slices, speaker_groups
from backend.providers.diarization import DiarizationSegment


def test_clustering_keeps_invalid_embeddings_singleton_and_centroid_ignores_them() -> None:
    embeddings = [np.array([1.0, 0.0]), np.zeros(2), np.array([0.99, 0.01])]
    assert cluster_embeddings(embeddings, threshold=0.9) == [[0, 2], [1]]
    np.testing.assert_allclose(centroid(embeddings), [0.995, 0.005])


def test_clustering_accepts_threshold_equality_and_preserves_invalid_singletons() -> None:
    assert cluster_embeddings(
        [np.array([1.0, 0.0]), np.array([1.0, 0.0])], threshold=1.0
    ) == [[0, 1]]
    assert cluster_embeddings(
        [np.array([np.nan, 1.0]), np.array([]), np.zeros(2)], threshold=0.9
    ) == [[0], [1], [2]]
    np.testing.assert_allclose(
        centroid([np.array([np.nan, 1.0]), np.array([]), np.zeros(2)]),
        np.zeros(0, dtype=np.float32),
    )


def test_clustering_empty_and_mismatched_dimension_contracts() -> None:
    assert cluster_embeddings([], threshold=0.9) == []
    np.testing.assert_array_equal(centroid([]), np.zeros(0, dtype=np.float32))
    with pytest.raises(ValueError):
        cluster_embeddings(
            [np.array([1.0, 0.0]), np.array([1.0, 0.0, 0.0])], threshold=0.9
        )


def test_turn_slices_clip_overlap_merge_and_group_audio() -> None:
    audio = np.arange(1000, dtype=np.float32)
    turns = build_turn_slices(
        audio, 1000, 5000,
        [DiarizationSegment(-1, 0.6, "a"), DiarizationSegment(0.4, 1.2, "b")],
    )
    assert [(t.speaker_label, t.started_ms, t.ended_ms) for t in turns] == [("a", 5000, 5600), ("b", 5600, 6000)]
    np.testing.assert_array_equal(turns[0].audio, audio[:600])
    np.testing.assert_array_equal(turns[1].audio, audio[600:])
    assert all(left.end_s <= right.start_s for left, right in zip(turns, turns[1:]))
    groups = speaker_groups(turns + [turns[0]])
    assert [(label, length) for label, _, length in groups] == [("a", 1200), ("b", 400)]
    np.testing.assert_array_equal(groups[0][1], np.concatenate((audio[:600], audio[:600])))
    np.testing.assert_array_equal(groups[1][1], audio[600:])


def test_turn_slices_preserve_gaps_and_fallback_for_empty_invalid_or_reversed_input() -> None:
    audio = np.arange(1000, dtype=np.float32)
    turns = build_turn_slices(
        audio,
        1000,
        0,
        [DiarizationSegment(0.1, 0.2, "a"), DiarizationSegment(0.4, 0.6, "b")],
    )
    assert [(t.speaker_label, t.start_s, t.end_s) for t in turns] == [
        ("a", 0.1, 0.2),
        ("b", 0.4, 0.6),
    ]
    np.testing.assert_array_equal(turns[0].audio, audio[100:200])
    np.testing.assert_array_equal(turns[1].audio, audio[400:600])
    assert turns[0].end_s < turns[1].start_s
    assert all(left.end_s <= right.start_s for left, right in zip(turns, turns[1:]))

    fallback = build_turn_slices(audio, 1000, 100, [])
    assert [(t.speaker_label, t.started_ms, t.ended_ms) for t in fallback] == [
        ("speaker-0", 100, 1100)
    ]
    np.testing.assert_array_equal(fallback[0].audio, audio)

    invalid = build_turn_slices(
        audio,
        1000,
        100,
        [
            DiarizationSegment(0.2, 0.2, "empty"),
            DiarizationSegment(0.8, 0.3, "reversed"),
            DiarizationSegment(2.0, 3.0, "outside"),
        ],
    )
    assert [(t.speaker_label, t.started_ms, t.ended_ms) for t in invalid] == [
        ("speaker-0", 100, 1100)
    ]
    np.testing.assert_array_equal(invalid[0].audio, audio)
    assert build_turn_slices(
        np.array([], dtype=np.float32),
        1000,
        0,
        [DiarizationSegment(0.0, 1.0, "a")],
    ) == []
    assert speaker_groups([]) == []
