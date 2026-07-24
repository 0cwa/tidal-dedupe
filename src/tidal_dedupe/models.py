"""Immutable, library-independent playlist data structures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class ItemKind(StrEnum):
    """Kinds of playlist items understood by the safety model."""

    TRACK = "track"
    VIDEO = "video"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class DisplayMetadata:
    """Human-readable fields for previews; never used for identity decisions."""

    title: str
    artist: str | None = None
    album: str | None = None
    isrc: str | None = None


@dataclass(frozen=True, slots=True)
class PlaylistEntry:
    """One item at one ordered position in a playlist."""

    kind: ItemKind
    item_id: str
    display: DisplayMetadata

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ValueError("playlist entries require a stable item ID")


@dataclass(frozen=True, slots=True, eq=False)
class PlaylistSnapshot:
    """An ordered, immutable view of a single playlist.

    Snapshot equality intentionally ignores display metadata.  A re-read is
    safe to mutate only when every item's ordered ``(kind, item_id)`` identity
    is unchanged.
    """

    entries: tuple[PlaylistEntry, ...]

    def __init__(self, entries: Iterable[PlaylistEntry]) -> None:
        object.__setattr__(self, "entries", tuple(entries))

    @property
    def identity(self) -> tuple[tuple[ItemKind, str], ...]:
        return tuple((entry.kind, entry.item_id) for entry in self.entries)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PlaylistSnapshot):
            return NotImplemented
        return self.identity == other.identity

    def __hash__(self) -> int:
        return hash(self.identity)
