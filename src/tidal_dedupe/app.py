"""Interactive orchestration for conservative TIDAL playlist deduplication."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from typing import Any

from .auth import load_session
from .backup import BackupError, write_backup
from .core import DeduplicationPlan, UnsafePlaylistSnapshotError, plan_ordered_playlists
from .models import PlaylistEntry, PlaylistSnapshot
from .tidal_client import PlaylistMutationError, PlaylistReadError, TidalClient


def _playlist_label(playlist: Any) -> str:
    name = getattr(playlist, "name", None) or getattr(playlist, "title", None)
    identifier = getattr(playlist, "id", "unknown")
    return f"{name or 'Untitled playlist'} ({identifier})"


def _select_playlists(playlists: list[Any]) -> list[Any]:
    import questionary

    choices = [questionary.Choice(title=_playlist_label(playlist), value=playlist) for playlist in playlists]
    selected = questionary.checkbox("Choose playlists to scan:", choices=choices).ask()
    return list(selected or [])


def _choose_cross_playlist_mode() -> bool:
    import questionary

    return bool(questionary.confirm(
        "CROSS-PLAYLIST MODE? First playlist wins; duplicates are REMOVED from lower playlists (OFF by default)",
        default=False,
    ).ask())


def _order_playlists(selected: list[Any]) -> list[Any]:
    """Allow repeated moves until the user accepts the keeper priority order."""
    import questionary

    ordered = list(selected)
    while True:
        print("\n[ CROSS-PLAYLIST MODE ON ]  Priority: TOP KEEPS tracks; LOWER LOSES duplicates")
        for index, playlist in enumerate(ordered, 1):
            print(f"  {index}. {_playlist_label(playlist)}")
        choices = []
        for index, playlist in enumerate(ordered):
            if index > 0:
                choices.append(questionary.Choice(
                    title=f"↑ Move UP: {_playlist_label(playlist)}", value=(index, -1)
                ))
            if index + 1 < len(ordered):
                choices.append(questionary.Choice(
                    title=f"↓ Move DOWN: {_playlist_label(playlist)}", value=(index, 1)
                ))
        choices.append(questionary.Choice(title="Done — use this priority order", value=None))
        choice = questionary.select("Reorder playlists (top priority is protected):", choices=choices).ask()
        if choice is None:
            return ordered
        index, direction = choice
        ordered[index], ordered[index + direction] = ordered[index + direction], ordered[index]


def _confirm() -> bool:
    import questionary

    return bool(questionary.confirm("Remove the planned duplicate entries?", default=False).ask())


def _entry_text(entry: PlaylistEntry) -> str:
    display = entry.display
    parts = [display.title]
    if display.artist:
        parts.append(display.artist)
    if display.album:
        parts.append(display.album)
    return " — ".join(parts)


def _print_plan(
    playlist: Any, plan: DeduplicationPlan, labels: dict[str, str], *, across_playlists: bool
) -> None:
    print(f"\n{_playlist_label(playlist)}")
    if not plan.removals:
        print("  No exact duplicate track IDs found.")
        return
    for removal in plan.removals:
        owner = removal.retained_playlist_id
        if across_playlists and owner is not None and owner != str(playlist.id):
            keep_text = f"keep in {labels[owner]} at position {removal.retained_index}"
        else:
            keep_text = f"keep position {removal.retained_index}"
        print(
            f"  Remove track {removal.track_id} at item position {removal.index} "
            f"({keep_text}): {_entry_text(removal.entry)}"
        )


def run(*, dry_run: bool = False, across_playlists: bool | None = None, backup: bool = True) -> int:
    """Authenticate, preview full plans, back up, and conditionally mutate."""
    try:
        client = TidalClient(load_session())
        playlists = client.editable_playlists()
    except (RuntimeError, PlaylistReadError) as exc:
        print(f"Unable to start: {exc}")
        return 1

    if not playlists:
        print("No user-owned editable playlists found.")
        return 0
    selected = _select_playlists(playlists)
    if not selected:
        print("No playlists selected; nothing changed.")
        return 0

    if across_playlists is None:
        across_playlists = len(selected) > 1 and _choose_cross_playlist_mode()
    if across_playlists and len(selected) < 2:
        print("Cross-playlist mode needs at least two selected playlists; nothing changed.")
        return 1
    if across_playlists:
        selected = _order_playlists(selected)
        print("\n[ CROSS-PLAYLIST MODE ON ]  First playlist keeps each track ID; lower playlists lose matches.")
    else:
        print("\n[ CROSS-PLAYLIST MODE OFF ]  Deduplicate independently inside each playlist.")

    labels = {str(playlist.id): _playlist_label(playlist) for playlist in selected}
    if len(labels) != len(selected):
        print("Duplicate playlist IDs in selection; nothing changed.")
        return 1
    snapshots: list[tuple[Any, PlaylistSnapshot]] = []
    for playlist in selected:
        try:
            snapshots.append((playlist, client.read_snapshot(playlist)))
        except PlaylistReadError as exc:
            print(f"\n{_playlist_label(playlist)}: scan aborted safely: {exc}")
            print("At least one playlist could not be scanned safely; no changes were made.")
            return 1
    try:
        plans = plan_ordered_playlists(
            [(str(playlist.id), snapshot) for playlist, snapshot in snapshots],
            across_playlists=across_playlists,
        )
    except (UnsafePlaylistSnapshotError, ValueError) as exc:
        print(f"Scan aborted safely: {exc}; no changes were made.")
        return 1

    changes = []
    for (playlist, _snapshot), plan in zip(snapshots, plans):
        _print_plan(playlist, plan, labels, across_playlists=across_playlists)
        if plan.removals:
            changes.append((playlist, plan))
    if not changes:
        print("No duplicate tracks to remove.")
        return 0
    if dry_run:
        print("Dry run complete; no changes were made (no backup necessary).")
        return 0
    print(f"\nAutomatic local backup: {'ON (recommended)' if backup else 'OFF — no recovery export will be created'}")
    if not _confirm():
        print("Cancelled; no changes were made.")
        return 0

    # Revalidate EVERY input, including higher-priority keeper playlists that
    # have no removals. Any drift invalidates the entire cross-playlist plan.
    for playlist, snapshot in snapshots:
        try:
            current = client.read_snapshot(playlist)
        except PlaylistReadError as exc:
            print(f"{_playlist_label(playlist)}: could not revalidate safely: {exc}")
            return 1
        if current != snapshot:
            print(f"{_playlist_label(playlist)} changed after preview; no changes were made.")
            return 1

    if backup:
        try:
            backup_path = write_backup([
                (str(playlist.id), _playlist_label(playlist), snapshot)
                for playlist, snapshot in snapshots
            ])
        except BackupError as exc:
            print(f"Backup failed: {exc}; no changes were made.")
            return 1
        print(f"Original playlists backed up to: {backup_path}")

    for playlist, plan in changes:
        try:
            current = client.read_snapshot(playlist)
        except PlaylistReadError as exc:
            print(f"{_playlist_label(playlist)}: could not revalidate safely: {exc}")
            return 1
        if current != plan.snapshot:
            print(f"{_playlist_label(playlist)} changed since backup; stopped before altering it.")
            return 1
        try:
            client.remove_index_chunks(playlist, plan.deletion_chunks())
        except PlaylistMutationError as exc:
            print(f"{_playlist_label(playlist)}: mutation stopped: {exc}")
            return 1
        try:
            final_snapshot = client.read_snapshot(playlist)
        except PlaylistReadError as exc:
            print(f"{_playlist_label(playlist)}: post-change verification failed: {exc}")
            return 1
        if final_snapshot != plan.expected_snapshot:
            print(f"{_playlist_label(playlist)}: post-change verification did not match the plan.")
            return 1
        print(f"{_playlist_label(playlist)}: removed {len(plan.removals)} duplicate track entries.")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely remove exact duplicate TIDAL track entries.")
    parser.add_argument("--dry-run", action="store_true", help="scan and preview without mutation")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--across-playlists", dest="across_playlists", action="store_true", help="deduplicate across selected playlists, highest priority first")
    mode.add_argument("--within-playlists", dest="across_playlists", action="store_false", help="deduplicate each playlist independently")
    parser.set_defaults(across_playlists=None)
    parser.add_argument("--no-backup", action="store_true", help="explicitly disable automatic backup (not recommended)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(dry_run=args.dry_run, across_playlists=args.across_playlists, backup=not args.no_backup)
