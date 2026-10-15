"""Durable, private exports of complete playlist states before any mutation."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .models import PlaylistSnapshot


class BackupError(RuntimeError):
    """A backup was not safely persisted; no mutation should follow."""


def backup_directory() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "tidal-dedupe" / "backups"


def write_backup(
    playlists: Sequence[tuple[str, str, PlaylistSnapshot]], *, directory: Path | None = None
) -> Path:
    """Export every original ordered item, including videos and duplicates.

    Uses an exclusive, owner-only file and fsync before returning. A failure
    raises BackupError and callers must not start deletion.
    """
    if not playlists:
        raise BackupError("no playlists to back up")
    target_directory = directory if directory is not None else backup_directory()
    created = datetime.now(timezone.utc)
    payload = {
        "format": "tidal-dedupe-backup",
        "version": 1,
        "created_utc": created.isoformat(),
        "playlists": [
            {
                "id": playlist_id,
                "name": name,
                "items": [
                    {
                        "position": index,
                        "kind": entry.kind.value,
                        "id": entry.item_id,
                        "title": entry.display.title,
                        "artist": entry.display.artist,
                        "album": entry.display.album,
                        "isrc": entry.display.isrc,
                    }
                    for index, entry in enumerate(snapshot.entries)
                ],
            }
            for playlist_id, name, snapshot in playlists
        ],
    }
    path: Path | None = None
    created_file = False
    try:
        target_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target_directory.chmod(0o700)
        filename = f"playlists-{created:%Y%m%dT%H%M%SZ}-{secrets.token_hex(6)}.json"
        path = target_directory / filename
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        created_file = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return path
    except (OSError, ValueError, TypeError) as exc:
        # Only delete files that this attempt actually created. In particular,
        # an O_EXCL name collision must never remove somebody else's backup.
        if created_file and path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise BackupError(f"could not save a complete backup: {exc}") from exc
