# tidal-dedupe

`tidal-dedupe` is an interactive terminal tool for conservatively removing
repeated **TIDAL track IDs** from playlists you own. It keeps the first
occurrence of each track ID and proposes removal of every later occurrence.

It is intentionally narrow: it does not try to decide whether two different
releases are "the same song." That makes it suitable for cleaning up accidental
duplicate additions without metadata-based guesses.

## Safety model

Before any deletion, the tool:

- previews **every** proposed removal with track ID and position and requires an explicit Yes (the default is **No**);
- rereads **all selected playlists** before changing anything, including any higher-priority playlist that keeps its tracks but has no removals; a changed item ID, type or order aborts the run;
- creates an **automatic local backup (ON by default)** of the original full selection before requesting any deletion. If writing the backup fails, no deletions are attempted;
- revalidates each target playlist again immediately before removal;
- removes from highest to lowest position in batches of no more than 50, then rereads and verifies the complete expected ordering.

It fails closed on incomplete reads, unsupported item types, changed playlists,
failed backups, and uncertain mutations. If an error occurs **during** a
multi-playlist operation, earlier playlists may already have been changed.
Inspect the backup and current TIDAL state before proceeding; the tool cannot
automatically roll back remote mutations.

## Duplicate matching and priority

| Item | Result |
| --- | --- |
| Later entry with the exact same TIDAL **track ID** | Proposed for removal |
| First entry with that exact ID | Kept |
| Different IDs with the same artist/title/album/ISRC | Both kept |
| Videos | Always kept |
| Unsupported item type | Entire scan aborts before mutation |

**Within-playlist mode (default, OFF cross-playlist toggle):** repeated track IDs
are removed independently within each playlist. Other playlists cannot affect
the plan.

**Cross-playlist mode (ON):** compare **all selected playlists in priority
order**. The **top playlist KEEPS** the track; later copies in lower playlists
are removed. This also removes duplicates within a playlist. After turning
cross-playlist mode on in the selector, use **Move UP** or **Move DOWN** to
reorder priorities; the terminal prints a prominent **CROSS-PLAYLIST MODE ON**
banner and the full ordering each time. Non-selected playlists are untouched.

## Install

Requires Python 3.11 or newer. A virtual environment keeps the application and
its dependencies isolated:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install 'tidal-dedupe @ git+https://github.com/0cwa/tidal-dedupe.git'
```

For a local checkout instead:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

## Use

Start with a non-mutating preview:

~~~bash
.venv/bin/tidal-dedupe --dry-run
~~~

Select playlists, then decide whether **CROSS-PLAYLIST MODE** should be on.
The mode starts **OFF**. If enabled, order playlists with Move UP / Move DOWN:
top priority keeps tracks, lower priorities lose matching track IDs. Review
every proposed removal and its keeper playlist/position.

When the preview looks right, run without dry-run:

~~~bash
.venv/bin/tidal-dedupe
~~~

The tool requests explicit confirmation (default No), checks all selected
playlists for changes, writes a backup, and only then begins deleting.
Only user-owned playlists that can be edited through tidalapi are offered.

To choose scope through command-line flags rather than the interactive toggle:

~~~bash
.venv/bin/tidal-dedupe --across-playlists --dry-run
.venv/bin/tidal-dedupe --within-playlists
~~~

### Automatic backups (ON by default)

Backups are timestamped JSON exports saved under
`~/.local/state/tidal-dedupe/backups/` (or the `XDG_STATE_HOME` equivalent).
On Unix-like systems, the backup directory is mode `0700` and each
file is mode `0600`. The exact backup path is printed before deletion.

Each backup stores the **original ordered entries of every selected playlist**
with playlist IDs, titles, item positions, track/video IDs, and display
metadata, including entries that will remain. Keep these files somewhere
safe if you need to reconstruct the original collection.

**This is a local recovery export, not a one-click TIDAL restore**: no
automatic import/rollback is implemented. If necessary, consult the backed-up
IDs and their ordering to reconstruct a playlist. See the
[backup recovery guide](docs/recovery.md) for the format, inspection commands
and recovery instructions.

Running with `--no-backup` disables this safeguard for **that run only**;
doing so is **not recommended**. Automatic backups are ON again on the next
run. A dry run neither mutates playlists nor needs to write a backup.

## Login and session privacy

The first run uses TIDAL's PKCE browser login. This application stores its
session separately at:

```text
${XDG_STATE_HOME:-~/.local/state}/tidal-dedupe/session.json
```

Its state directory is created with owner-only permissions (`0700`), and the
session file with owner-only permissions (`0600`). Treat the session file as a
credential: do not commit it, share it, or copy it into support requests. To
sign out locally, delete that specific file and run the tool again to log in.

## Development and verification

The test suite is fake-only: it does not authenticate with TIDAL or make live
playlist changes. The GitHub Actions workflow runs tests, source compilation
and package-build checks on Python 3.11 and 3.12 for PRs and main.

```bash
.venv/bin/python -m pytest
```

For a release build check:

```bash
.venv/bin/python -m pip install build
.venv/bin/python -m build
```

## License

Copyright (C) 2026 0cwa. This project is licensed under the GNU Affero General
Public License, version 3 or any later version (AGPL-3.0-or-later). See
[LICENSE](LICENSE).
