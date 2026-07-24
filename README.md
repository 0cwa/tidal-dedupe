# tidal-dedupe

`tidal-dedupe` is an interactive terminal tool for conservatively removing
repeated **TIDAL track IDs** from playlists you own. It keeps the first
occurrence of each track ID and proposes removal of every later occurrence.

It is intentionally narrow: it does not try to decide whether two different
releases are "the same song." That makes it suitable for cleaning up accidental
duplicate additions without metadata-based guesses.

## Safety model

Before changing a playlist, the tool:

- shows the exact entries and positions it proposes to remove, then requires
  explicit confirmation (the default is **No**);
- rereads the complete playlist immediately before removal and skips it if its
  ordered item IDs or item types changed after the preview;
- removes positions from the end of the playlist towards the beginning, in
  batches of at most 50, so earlier positions stay valid; and
- rereads the playlist afterward and verifies the complete expected ordering.

It fails closed: an incomplete read, an unsupported item type, or an uncertain
mutation stops processing rather than guessing. A failed scan means **no
selected playlist is changed**. If an error occurs after a mutation request,
the remote playlist state may be uncertain; inspect it in TIDAL before running
the tool again.

## What is and is not a duplicate

| Item | Result |
| --- | --- |
| Later entry with the exact same TIDAL **track ID** | Proposed for removal |
| First entry with a track ID | Kept |
| Different track IDs, even with the same title, artist, album, or ISRC | Kept |
| Videos | Kept |
| Unknown/unsupported playlist items | Playlist scan is aborted safely |

Duplicates are evaluated independently for each playlist; the tool never
compares tracks across playlists.

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

```bash
.venv/bin/tidal-dedupe --dry-run
```

Choose the playlists to scan. The tool lists each proposed removal, including
its TIDAL track ID and playlist position. `--dry-run` never requests a playlist
mutation.

When the preview looks right, run without the flag:

```bash
.venv/bin/tidal-dedupe
```

Choose playlists again, review the preview, and answer the confirmation prompt.
Only playlists owned by the logged-in TIDAL user that the installed TIDAL client
can mutate are offered.

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
playlist changes.

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
