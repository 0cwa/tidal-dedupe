# tidal-dedupe

An interactive terminal tool that removes only later occurrences of the exact
same TIDAL track ID from playlists you own and can edit. It never uses titles,
artist names, ISRCs, or other metadata to decide that tracks are duplicates.

## Install

Use Python 3.11 or newer in a dedicated virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
```

## Run

```bash
tidal-dedupe --dry-run
```

The first run opens TIDAL's PKCE login flow and stores this application's own
session file at `${XDG_STATE_HOME:-~/.local/state}/tidal-dedupe/session.json`.
The directory is created with restricted permissions and the session file is
restricted to the current user.

Without `--dry-run`, the program shows a complete removal preview and asks for
explicit confirmation, defaulting to **No**. Before every mutation it reads the
playlist again and skips it if its full ordered content changed. It verifies the
expected final ordering after each successful playlist update.

Only track entries with the same TIDAL track ID are deduplicated. Videos remain
untouched, and an unknown playlist item aborts that playlist's scan rather than
risking an incorrect deletion.

## Test

```bash
python -m pytest
```

The test suite uses fakes only; it does not log in to TIDAL or make any live
playlist changes.

## License

Copyright (C) 2026 0cwa. This project is licensed under the GNU Affero General
Public License, version 3 or any later version (AGPL-3.0-or-later). See
[LICENSE](LICENSE).
