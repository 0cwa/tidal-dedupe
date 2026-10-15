"""Fake-only regression coverage for cross-playlist priority and automatic backups."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from tidal_dedupe import app
from tidal_dedupe.backup import BackupError, write_backup
from tidal_dedupe.core import UnsafePlaylistSnapshotError, plan_ordered_playlists
from tidal_dedupe.models import DisplayMetadata, ItemKind, PlaylistEntry, PlaylistSnapshot


def track(item_id):
    return PlaylistEntry(ItemKind.TRACK, item_id, DisplayMetadata(item_id))


def video(item_id):
    return PlaylistEntry(ItemKind.VIDEO, item_id, DisplayMetadata(item_id))


def snapshot(*entries):
    return PlaylistSnapshot(entries)


def test_first_playlist_keeps_track_ids_and_lower_playlists_lose_them():
    higher = snapshot(track("a"), track("a"), video("v"), track("b"))
    lower = snapshot(track("b"), track("a"), track("c"), track("c"), video("v"))
    plans = plan_ordered_playlists((("high", higher), ("low", lower)), across_playlists=True)
    assert plans[0].removal_indices == (1,)
    assert plans[1].removal_indices == (0, 1, 3)
    assert [(item.retained_playlist_id, item.retained_index) for item in plans[1].removals] == [
        ("high", 3), ("high", 0), ("low", 2)
    ]
    assert plans[1].expected_snapshot.identity == (
        (ItemKind.TRACK, "c"), (ItemKind.VIDEO, "v")
    )


def test_priority_reversal_changes_who_keeps_track():
    first = snapshot(track("a"))
    second = snapshot(track("a"))
    left = plan_ordered_playlists((("left", first), ("right", second)), across_playlists=True)
    right = plan_ordered_playlists((("right", second), ("left", first)), across_playlists=True)
    assert left[1].removals[0].retained_playlist_id == "left"
    assert right[1].removals[0].retained_playlist_id == "right"


def test_scope_off_never_dedupes_between_playlists():
    plans = plan_ordered_playlists((
        ("one", snapshot(track("a"), track("a"))),
        ("two", snapshot(track("a"), track("b"))),
    ))
    assert [plan.removal_indices for plan in plans] == [(1,), ()]


def test_unsupported_items_or_duplicate_playlist_ids_are_rejected():
    with pytest.raises(UnsafePlaylistSnapshotError):
        plan_ordered_playlists((
            ("high", snapshot(track("a"))),
            ("low", snapshot(PlaylistEntry(ItemKind.UNSUPPORTED, "x", DisplayMetadata("x")))),
        ), across_playlists=True)
    with pytest.raises(ValueError, match="unique"):
        plan_ordered_playlists((("same", snapshot(track("a"))), ("same", snapshot(track("b")))))


def test_backup_contains_every_position_and_video_and_has_private_permissions(tmp_path):
    path = write_backup([
        ("id-1", "One", snapshot(track("a"), video("v"), track("a"))),
        ("id-2", "Two", snapshot(track("b"))),
    ], directory=tmp_path / "backups")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "tidal-dedupe-backup"
    assert data["version"] == 1
    assert [p["id"] for p in data["playlists"]] == ["id-1", "id-2"]
    assert [(e["position"], e["kind"], e["id"]) for e in data["playlists"][0]["items"]] == [
        (0, "track", "a"), (1, "video", "v"), (2, "track", "a")
    ]
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_backup_failure_is_reported(tmp_path):
    target = tmp_path / "not-a-directory"
    target.write_text("x")
    with pytest.raises(BackupError, match="could not save"):
        write_backup([("id", "Title", snapshot(track("a")))], directory=target)


def setup_client(monkeypatch, first, second, client_type):
    monkeypatch.setattr(app, "load_session", lambda: object())
    monkeypatch.setattr(app, "TidalClient", client_type)
    monkeypatch.setattr(app, "_select_playlists", lambda _: [first, second])
    monkeypatch.setattr(app, "_order_playlists", lambda playlists: playlists)
    monkeypatch.setattr(app, "_confirm", lambda: True)


def test_keeper_changed_after_preview_aborts_before_backup_and_deletion(monkeypatch):
    first = SimpleNamespace(id="high", name="Keeper")
    second = SimpleNamespace(id="low", name="Lower")
    reads = {"high": 0, "low": 0}
    calls = []
    class FakeClient:
        def __init__(self, _): pass
        def editable_playlists(self): return [first, second]
        def read_snapshot(self, playlist):
            reads[playlist.id] += 1
            if playlist.id == "high" and reads["high"] > 1:
                return snapshot(track("changed"))
            return snapshot(track("a"))
        def remove_index_chunks(self, *_): calls.append("mutation")
    setup_client(monkeypatch, first, second, FakeClient)
    monkeypatch.setattr(app, "write_backup", lambda _: calls.append("backup"))
    assert app.run(across_playlists=True) == 1
    assert calls == []


def test_failed_backup_blocks_all_mutations(monkeypatch):
    first = SimpleNamespace(id="high", name="Keeper")
    second = SimpleNamespace(id="low", name="Lower")
    calls = []
    class FakeClient:
        def __init__(self, _): pass
        def editable_playlists(self): return [first, second]
        def read_snapshot(self, _): return snapshot(track("a"))
        def remove_index_chunks(self, *_): calls.append("mutation")
    setup_client(monkeypatch, first, second, FakeClient)
    def fail(_):
        raise BackupError("out of space")
    monkeypatch.setattr(app, "write_backup", fail)
    assert app.run(across_playlists=True) == 1
    assert calls == []


def test_dry_run_never_creates_backup_and_live_run_backs_up_before_removal(monkeypatch, tmp_path):
    first = SimpleNamespace(id="high", name="Keeper")
    second = SimpleNamespace(id="low", name="Lower")
    state = {"high": [track("a")], "low": [track("a"), track("b")]}
    calls = []
    class FakeClient:
        def __init__(self, _): pass
        def editable_playlists(self): return [first, second]
        def read_snapshot(self, playlist): return snapshot(*state[playlist.id])
        def remove_index_chunks(self, playlist, chunks):
            calls.append("remove")
            for chunk in chunks:
                for position in sorted(chunk, reverse=True):
                    del state[playlist.id][position]
    setup_client(monkeypatch, first, second, FakeClient)
    def save(items):
        calls.append("backup")
        return write_backup(items, directory=tmp_path)
    monkeypatch.setattr(app, "write_backup", save)
    assert app.run(across_playlists=True, dry_run=True) == 0
    assert calls == []
    assert app.run(across_playlists=True) == 0
    assert calls == ["backup", "remove"]
    assert [e.item_id for e in state["low"]] == ["b"]


def test_interactive_reorder_and_default_off_toggle(monkeypatch):
    a = SimpleNamespace(id="a", name="Alpha")
    b = SimpleNamespace(id="b", name="Beta")
    c = SimpleNamespace(id="c", name="Gamma")
    moves = iter([(2, -1), (1, -1), None])
    defaults = []
    class FakeQuestionary:
        Choice = staticmethod(lambda title, value: SimpleNamespace(title=title, value=value))
        @staticmethod
        def select(_prompt, *, choices):
            return SimpleNamespace(ask=lambda: next(moves))
        @staticmethod
        def confirm(_prompt, *, default):
            defaults.append(default)
            return SimpleNamespace(ask=lambda: True)
    monkeypatch.setitem(sys.modules, "questionary", FakeQuestionary)
    assert [playlist.id for playlist in app._order_playlists([a, b, c])] == ["c", "a", "b"]
    assert app._choose_cross_playlist_mode() is True
    assert defaults == [False]
