from __future__ import annotations

from types import SimpleNamespace

from tidal_dedupe import app
from tidal_dedupe.models import DisplayMetadata, ItemKind, PlaylistEntry, PlaylistSnapshot


def track(item_id: str) -> PlaylistEntry:
    return PlaylistEntry(ItemKind.TRACK, item_id, DisplayMetadata(item_id))


def test_dry_run_cannot_reach_mutation(monkeypatch):
    playlist = SimpleNamespace(id="p1", name="Playlist")
    snapshot = PlaylistSnapshot((track("A"), track("A")))

    class FakeClient:
        def __init__(self, _session):
            self.mutation_calls = 0

        def editable_playlists(self):
            return [playlist]

        def read_snapshot(self, _playlist):
            return snapshot

        def remove_index_chunks(self, _playlist, _chunks):
            self.mutation_calls += 1
            raise AssertionError("dry run reached mutation")

    monkeypatch.setattr(app, "load_session", lambda: object())
    monkeypatch.setattr(app, "TidalClient", FakeClient)
    monkeypatch.setattr(app, "_select_playlists", lambda _: [playlist])
    monkeypatch.setattr(app, "_confirm", lambda: (_ for _ in ()).throw(AssertionError("asked")))

    assert app.run(dry_run=True) == 0


def test_changed_snapshot_skips_mutation(monkeypatch):
    playlist = SimpleNamespace(id="p1", name="Playlist")
    original = PlaylistSnapshot((track("A"), track("A")))
    changed = PlaylistSnapshot((track("A"), track("B"), track("A")))

    class FakeClient:
        def __init__(self, _session):
            self.snapshots = iter((original, changed))
            self.mutation_calls = 0

        def editable_playlists(self):
            return [playlist]

        def read_snapshot(self, _playlist):
            return next(self.snapshots)

        def remove_index_chunks(self, _playlist, _chunks):
            self.mutation_calls += 1

    created: list[FakeClient] = []

    def make_client(session):
        client = FakeClient(session)
        created.append(client)
        return client

    monkeypatch.setattr(app, "load_session", lambda: object())
    monkeypatch.setattr(app, "TidalClient", make_client)
    monkeypatch.setattr(app, "_select_playlists", lambda _: [playlist])
    monkeypatch.setattr(app, "_confirm", lambda: True)

    assert app.run() == 0
    assert created[0].mutation_calls == 0


def test_final_verification_requires_complete_expected_snapshot(monkeypatch):
    playlist = SimpleNamespace(id="p1", name="Playlist")
    original = PlaylistSnapshot((track("A"), track("A"), track("B")))
    wrong_final = PlaylistSnapshot((track("A"), track("B"), track("unexpected")))

    class FakeClient:
        def __init__(self, _session):
            self.snapshots = iter((original, original, wrong_final))
            self.mutation_calls = 0

        def editable_playlists(self):
            return [playlist]

        def read_snapshot(self, _playlist):
            return next(self.snapshots)

        def remove_index_chunks(self, _playlist, _chunks):
            self.mutation_calls += 1

    monkeypatch.setattr(app, "load_session", lambda: object())
    monkeypatch.setattr(app, "TidalClient", FakeClient)
    monkeypatch.setattr(app, "_select_playlists", lambda _: [playlist])
    monkeypatch.setattr(app, "_confirm", lambda: True)

    assert app.run() == 1
