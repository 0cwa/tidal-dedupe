"""Interactive orchestration for conservative TIDAL playlist deduplication."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from typing import Any

from .auth import load_session
from .core import DeduplicationPlan, UnsafePlaylistSnapshotError, plan_deduplication
from .models import PlaylistEntry
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


def _print_plan(playlist: Any, plan: DeduplicationPlan) -> None:
    print(f"\n{_playlist_label(playlist)}")
    if not plan.removals:
        print("  No exact duplicate track IDs found.")
        return
    for removal in plan.removals:
        print(
            f"  Remove track {removal.track_id} at item position {removal.index} "
            f"(keep position {removal.retained_index}): {_entry_text(removal.entry)}"
        )


def run(*, dry_run: bool = False) -> int:
    """Authenticate, preview plans, and conditionally apply safe mutations."""
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

    plans: list[tuple[Any, DeduplicationPlan]] = []
    failures = False
    for playlist in selected:
        try:
            plan = plan_deduplication(client.read_snapshot(playlist))
        except (PlaylistReadError, UnsafePlaylistSnapshotError) as exc:
            print(f"\n{_playlist_label(playlist)}: scan aborted safely: {exc}")
            failures = True
            continue
        _print_plan(playlist, plan)
        if plan.removals:
            plans.append((playlist, plan))

    if failures:
        print("At least one playlist could not be scanned safely; no changes were made.")
        return 1
    if not plans:
        print("No duplicate tracks to remove.")
        return 0
    if dry_run:
        print("Dry run complete; no changes were made.")
        return 0
    if not _confirm():
        print("Cancelled; no changes were made.")
        return 0

    for playlist, plan in plans:
        try:
            current = client.read_snapshot(playlist)
        except PlaylistReadError as exc:
            print(f"{_playlist_label(playlist)}: could not revalidate safely: {exc}")
            return 1
        if current != plan.snapshot:
            print(f"{_playlist_label(playlist)} changed after preview; skipped without mutation.")
            continue
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
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(dry_run=args.dry_run)
