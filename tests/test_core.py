from __future__ import annotations

import pytest

from tidal_dedupe.core import (
    UnsafePlaylistSnapshotError,
    deletion_chunks,
    expected_snapshot,
    plan_deduplication,
)
from tidal_dedupe.models import DisplayMetadata, ItemKind, PlaylistEntry, PlaylistSnapshot


def entry(item_id: str, kind: ItemKind = ItemKind.TRACK, **metadata: str) -> PlaylistEntry:
    return PlaylistEntry(kind, item_id, DisplayMetadata(metadata.pop("title", item_id), **metadata))


def snapshot(*entries: PlaylistEntry) -> PlaylistSnapshot:
    return PlaylistSnapshot(entries)


def test_removes_only_second_of_two_exact_track_ids() -> None:
    plan = plan_deduplication(snapshot(entry("A"), entry("A"), entry("B")))

    assert [(item.index, item.retained_index, item.track_id) for item in plan.removals] == [(1, 0, "A")]
    assert [item.item_id for item in plan.expected_snapshot.entries] == ["A", "B"]


def test_keeps_first_and_removes_every_later_occurrence() -> None:
    plan = plan_deduplication(snapshot(entry("A"), entry("B"), entry("A"), entry("A")))

    assert [(item.index, item.retained_index) for item in plan.removals] == [(2, 0), (3, 0)]
    assert [item.item_id for item in plan.expected_snapshot.entries] == ["A", "B"]


def test_seen_track_ids_are_recreated_for_each_playlist() -> None:
    first = plan_deduplication(snapshot(entry("A"), entry("A")))
    second = plan_deduplication(snapshot(entry("A"), entry("B")))

    assert first.removal_indices == (1,)
    assert second.removals == ()


def test_matching_metadata_with_different_track_ids_is_not_a_duplicate() -> None:
    common = {"title": "Same song", "artist": "Same artist", "isrc": "same-isrc"}
    plan = plan_deduplication(snapshot(entry("tidal-1", **common), entry("tidal-2", **common)))

    assert plan.removals == ()


def test_interleaved_video_is_preserved_and_item_positions_are_used() -> None:
    plan = plan_deduplication(
        snapshot(entry("A"), entry("video-1", ItemKind.VIDEO), entry("A"), entry("B"))
    )

    assert plan.removal_indices == (2,)
    assert [(item.kind, item.item_id) for item in plan.expected_snapshot.entries] == [
        (ItemKind.TRACK, "A"),
        (ItemKind.VIDEO, "video-1"),
        (ItemKind.TRACK, "B"),
    ]


def test_no_duplicates_has_no_removal_or_delete_chunks() -> None:
    plan = plan_deduplication(snapshot(entry("A"), entry("B")))

    assert plan.removals == ()
    assert plan.deletion_chunks() == ()
    assert plan.expected_snapshot == plan.snapshot


def test_unsupported_item_fails_closed() -> None:
    with pytest.raises(UnsafePlaylistSnapshotError, match="position 1"):
        plan_deduplication(snapshot(entry("A"), entry("unknown", ItemKind.UNSUPPORTED)))


def test_snapshot_equality_uses_ordered_kind_and_id_not_preview_metadata() -> None:
    original = snapshot(entry("A", title="Old title"), entry("v", ItemKind.VIDEO))
    same_identity = snapshot(entry("A", title="New title"), entry("v", ItemKind.VIDEO, title="New video"))
    reordered = snapshot(entry("v", ItemKind.VIDEO), entry("A"))
    different_kind = snapshot(entry("A", ItemKind.VIDEO), entry("v", ItemKind.VIDEO))

    assert original == same_identity
    assert hash(original) == hash(same_identity)
    assert original != reordered
    assert original != different_kind


def test_expected_snapshot_preserves_complete_order_and_rejects_bad_indices() -> None:
    original = snapshot(entry("A"), entry("video", ItemKind.VIDEO), entry("A"), entry("B"))

    assert expected_snapshot(original, (2,)).identity == (
        (ItemKind.TRACK, "A"),
        (ItemKind.VIDEO, "video"),
        (ItemKind.TRACK, "B"),
    )
    with pytest.raises(ValueError, match="unique"):
        expected_snapshot(original, (2, 2))
    with pytest.raises(ValueError, match="outside"):
        expected_snapshot(original, (4,))


def test_more_than_fifty_removals_are_ascending_within_descending_chunks() -> None:
    indices = tuple(range(1, 122))

    assert deletion_chunks(indices) == (
        tuple(range(101, 122)),
        tuple(range(51, 101)),
        tuple(range(1, 51)),
    )


def test_chunk_planning_rejects_unsafe_arguments() -> None:
    with pytest.raises(ValueError, match="positive"):
        deletion_chunks((1,), 0)
    with pytest.raises(ValueError, match="unique"):
        deletion_chunks((1, 1))
    with pytest.raises(ValueError, match="non-negative"):
        deletion_chunks((-1,))
