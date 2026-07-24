from __future__ import annotations

from types import SimpleNamespace

import pytest

from tidal_dedupe.auth import load_session
from tidal_dedupe.tidal_client import (
    PlaylistMutationError,
    PlaylistReadError,
    TidalClient,
)


class Track:
    def __init__(self, item_id: str, name: str = "same"):
        self.id, self.name = item_id, name


class Video:
    def __init__(self, item_id: str):
        self.id, self.name = item_id, "video"


class Unknown:
    id = "unknown"


class FakePlaylist:
    def __init__(self, items, *, count=None):
        self._items = list(items)
        self._count = len(items) if count is None else count
        self.calls = []
        self.removals = []
        self.remove_result = True

    def get_items_count(self):
        return self._count

    def items(self, *, limit, offset):
        self.calls.append((limit, offset))
        return self._items[offset : offset + limit]

    def remove_by_indices(self, indices):
        self.removals.append(list(indices))
        if isinstance(self.remove_result, Exception):
            raise self.remove_result
        return self.remove_result


def client():
    return TidalClient(object(), track_type=Track, video_type=Video, page_size=2)


def test_full_snapshot_is_sequential_and_preserves_interleaved_video():
    playlist = FakePlaylist([Track("A"), Video("V"), Track("B")])
    snapshot = client().read_snapshot(playlist)
    assert snapshot.identity == (("track", "A"), ("video", "V"), ("track", "B"))
    assert playlist.calls == [(2, 0), (2, 2)]


def test_count_mismatch_retries_once_then_fails_closed():
    playlist = FakePlaylist([Track("A")], count=2)
    with pytest.raises(PlaylistReadError, match="twice"):
        client().read_snapshot(playlist)
    assert playlist.calls == [(2, 0), (2, 0)]


@pytest.mark.parametrize("items", [[Unknown()], [Track("A"), Unknown()]])
def test_unsupported_items_fail_closed(items):
    with pytest.raises(PlaylistReadError, match="unsupported"):
        client().read_snapshot(FakePlaylist(items))


def test_item_read_exception_fails_closed():
    playlist = FakePlaylist([Track("A")])
    playlist.items = lambda **_: (_ for _ in ()).throw(OSError("network"))
    with pytest.raises(PlaylistReadError, match="failed to read"):
        client().read_snapshot(playlist)


def test_editable_playlists_accepts_owned_mutable_without_invented_flag():
    mine = SimpleNamespace(creator=SimpleNamespace(id="me"), remove_by_indices=lambda _: True)
    followed = SimpleNamespace(creator=SimpleNamespace(id="other"), remove_by_indices=lambda _: True)
    locked = SimpleNamespace(creator=SimpleNamespace(id="me"))
    malformed = SimpleNamespace(remove_by_indices=lambda _: True)
    session = SimpleNamespace(user=SimpleNamespace(id="me", playlists=lambda: [mine, followed, locked, malformed]))
    assert TidalClient(session, track_type=Track, video_type=Video).editable_playlists() == [mine]


def test_mutations_are_caller_chunked_and_stop_on_false():
    playlist = FakePlaylist([])
    playlist.remove_result = False
    with pytest.raises(PlaylistMutationError, match="returned false"):
        client().remove_index_chunks(playlist, [[52, 53], [1]])
    assert playlist.removals == [[52, 53]]


def test_mutations_are_high_to_low_and_at_most_fifty():
    playlist = FakePlaylist([])
    client().remove_index_chunks(playlist, [list(range(50, 100)), [2, 4]])
    assert playlist.removals == [list(range(50, 100)), [2, 4]]


def test_secure_pkce_login_uses_given_session_file(tmp_path):
    calls = []
    session = SimpleNamespace(login_session_file=lambda path, do_pkce: calls.append((path, do_pkce)))
    target = tmp_path / "state" / "session.json"
    assert load_session(target, session_factory=lambda: session) is session
    assert calls == [(target, True)]
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700


def test_mutation_exception_stops_later_chunks():
    playlist = FakePlaylist([])
    playlist.remove_result = OSError("network")
    with pytest.raises(PlaylistMutationError, match="raised"):
        client().remove_index_chunks(playlist, [[52, 53], [1]])
    assert playlist.removals == [[52, 53]]
