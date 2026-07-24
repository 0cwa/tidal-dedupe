"""Pure, conservative duplicate planning.

This module deliberately knows nothing about tidalapi or network mutation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ItemKind, PlaylistEntry, PlaylistSnapshot


class UnsafePlaylistSnapshotError(ValueError):
    """The snapshot contains an item that cannot safely be reasoned about."""


@dataclass(frozen=True, slots=True)
class DuplicateRemoval:
    """A later occurrence that may be removed after revalidation."""

    index: int
    retained_index: int
    track_id: str
    entry: PlaylistEntry


@dataclass(frozen=True, slots=True)
class DeduplicationPlan:
    """All removals for exactly one immutable playlist snapshot."""

    snapshot: PlaylistSnapshot
    removals: tuple[DuplicateRemoval, ...]

    @property
    def removal_indices(self) -> tuple[int, ...]:
        return tuple(removal.index for removal in self.removals)

    @property
    def expected_snapshot(self) -> PlaylistSnapshot:
        return expected_snapshot(self.snapshot, self.removal_indices)

    def deletion_chunks(self, maximum_size: int = 50) -> tuple[tuple[int, ...], ...]:
        return deletion_chunks(self.removal_indices, maximum_size)


def plan_deduplication(snapshot: PlaylistSnapshot) -> DeduplicationPlan:
    """Plan removal of later exact track-ID occurrences in one playlist.

    Videos are deliberately retained and unsupported entries cause a fail-closed
    error.  Seen IDs are local to this call, so separate playlists cannot
    influence one another.
    """

    first_index_by_track_id: dict[str, int] = {}
    removals: list[DuplicateRemoval] = []

    for index, entry in enumerate(snapshot.entries):
        if entry.kind is ItemKind.UNSUPPORTED:
            raise UnsafePlaylistSnapshotError(
                f"unsupported playlist item at position {index}"
            )
        if entry.kind is not ItemKind.TRACK:
            continue

        retained_index = first_index_by_track_id.setdefault(entry.item_id, index)
        if retained_index != index:
            removals.append(
                DuplicateRemoval(index, retained_index, entry.item_id, entry)
            )

    return DeduplicationPlan(snapshot=snapshot, removals=tuple(removals))


def expected_snapshot(
    snapshot: PlaylistSnapshot, removal_indices: tuple[int, ...] | list[int]
) -> PlaylistSnapshot:
    """Return the exact expected ordering after deleting these item positions."""

    indices = tuple(removal_indices)
    if len(indices) != len(set(indices)):
        raise ValueError("removal indices must be unique")
    if any(index < 0 or index >= len(snapshot.entries) for index in indices):
        raise ValueError("removal index is outside the playlist snapshot")

    removed = set(indices)
    return PlaylistSnapshot(entry for index, entry in enumerate(snapshot.entries) if index not in removed)


def deletion_chunks(
    removal_indices: tuple[int, ...] | list[int], maximum_size: int = 50
) -> tuple[tuple[int, ...], ...]:
    """Make ascending index chunks, ordered from highest range to lowest.

    Removing highest positions first preserves every not-yet-removed lower
    position.  ``maximum_size`` is explicit to make the production limit and
    its tests unambiguous.
    """

    if maximum_size < 1:
        raise ValueError("maximum_size must be positive")

    ordered = tuple(sorted(removal_indices))
    if len(ordered) != len(set(ordered)):
        raise ValueError("removal indices must be unique")
    if any(index < 0 for index in ordered):
        raise ValueError("removal indices must be non-negative")

    chunks = [ordered[start : start + maximum_size] for start in range(0, len(ordered), maximum_size)]
    return tuple(reversed(chunks))
