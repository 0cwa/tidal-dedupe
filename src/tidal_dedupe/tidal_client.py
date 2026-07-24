"""Small fail-closed gateway around the subset of tidalapi this app uses."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from .models import DisplayMetadata, ItemKind, PlaylistEntry, PlaylistSnapshot


PAGE_SIZE = 100


class PlaylistReadError(RuntimeError):
    """The playlist could not be read as one complete, safe snapshot."""


class PlaylistMutationError(RuntimeError):
    """A requested playlist mutation did not complete with a positive result."""


class _CountMismatch(Exception):
    pass


def _library_types() -> tuple[type[Any], type[Any]]:
    """Load concrete media types lazily, keeping fake-only tests dependency-free."""
    try:
        from tidalapi.media import Track, Video
    except ImportError as exc:  # pragma: no cover - depends on package installation
        raise PlaylistReadError("tidalapi media types are unavailable") from exc
    return Track, Video


def _item_display(item: Any) -> DisplayMetadata:
    title = getattr(item, "name", None) or getattr(item, "title", None) or str(item.id)
    artist = getattr(item, "artist", None)
    artist_name = getattr(artist, "name", None) if artist is not None else None
    album = getattr(item, "album", None)
    album_name = getattr(album, "name", None) if album is not None else None
    return DisplayMetadata(
        title=str(title),
        artist=str(artist_name) if artist_name else None,
        album=str(album_name) if album_name else None,
        isrc=getattr(item, "isrc", None),
    )


class TidalClient:
    """Gateway that preserves item positions and refuses uncertain input."""

    def __init__(
        self,
        session: Any,
        *,
        track_type: type[Any] | None = None,
        video_type: type[Any] | None = None,
        page_size: int = PAGE_SIZE,
    ) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.session = session
        if track_type is None or video_type is None:
            default_track, default_video = _library_types()
            track_type = track_type or default_track
            video_type = video_type or default_video
        self._track_type = track_type
        self._video_type = video_type
        self._page_size = page_size

    def editable_playlists(self) -> list[Any]:
        """Return only playlists owned by this user and mutable by tidalapi."""
        try:
            user = self.session.user
            user_id = str(user.id)
            playlists = user.playlists()
        except Exception as exc:
            raise PlaylistReadError("could not list the logged-in user's playlists") from exc

        eligible: list[Any] = []
        for playlist in playlists:
            try:
                creator = getattr(playlist, "creator")
                owner_id = str(creator.id)
                remove_by_indices = getattr(playlist, "remove_by_indices")
            except Exception:
                continue
            if owner_id == user_id and callable(remove_by_indices):
                eligible.append(playlist)
        return eligible

    def _entry_for(self, item: Any) -> PlaylistEntry:
        item_id = getattr(item, "id", None)
        if item_id is None:
            raise PlaylistReadError("playlist item has no stable TIDAL ID")
        if isinstance(item, self._track_type):
            kind = ItemKind.TRACK
        elif isinstance(item, self._video_type):
            kind = ItemKind.VIDEO
        else:
            raise PlaylistReadError(f"unsupported playlist item type: {type(item).__name__}")
        return PlaylistEntry(kind=kind, item_id=str(item_id), display=_item_display(item))

    def _read_once(self, playlist: Any) -> PlaylistSnapshot:
        try:
            count = playlist.get_items_count()
            if not isinstance(count, int) or count < 0:
                raise PlaylistReadError("playlist reported an invalid item count")
            entries: list[PlaylistEntry] = []
            for offset in range(0, count, self._page_size):
                page = list(playlist.items(limit=self._page_size, offset=offset))
                remaining = count - offset
                if not page or len(page) > min(self._page_size, remaining):
                    raise _CountMismatch
                entries.extend(self._entry_for(item) for item in page)
            if len(entries) != count:
                raise _CountMismatch
            return PlaylistSnapshot(tuple(entries))
        except _CountMismatch:
            raise
        except PlaylistReadError:
            raise
        except Exception as exc:
            raise PlaylistReadError("failed to read playlist items") from exc

    def read_snapshot(self, playlist: Any) -> PlaylistSnapshot:
        """Read all ordered items, retrying only a possible count/page race once."""
        for attempt in range(2):
            try:
                return self._read_once(playlist)
            except _CountMismatch:
                if attempt == 1:
                    raise PlaylistReadError("playlist count did not match fetched items twice")
        raise AssertionError("unreachable")

    def remove_index_chunks(self, playlist: Any, chunks: Iterable[Sequence[int]]) -> None:
        """Apply caller-planned descending chunks, failing on any uncertain result."""
        previous_lowest: int | None = None
        for raw_chunk in chunks:
            chunk = list(raw_chunk)
            if not chunk or len(chunk) > 50 or chunk != sorted(chunk) or len(set(chunk)) != len(chunk):
                raise ValueError("each deletion chunk must contain 1-50 unique ascending indices")
            if any(index < 0 for index in chunk):
                raise ValueError("deletion indices cannot be negative")
            if previous_lowest is not None and chunk[-1] >= previous_lowest:
                raise ValueError("deletion chunks must proceed from higher indices to lower indices")
            try:
                result = playlist.remove_by_indices(chunk)
            except Exception as exc:
                raise PlaylistMutationError("remove_by_indices raised; playlist state is uncertain") from exc
            if result is False:
                raise PlaylistMutationError("remove_by_indices returned false; playlist state is uncertain")
            previous_lowest = chunk[0]
