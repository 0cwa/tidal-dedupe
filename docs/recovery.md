# Recovering playlists from a backup

tidal-dedupe makes a **local JSON snapshot of every selected playlist before
any deletion**, unless you explicitly pass \`--no-backup\`. It records every
original item, its playlist and its position, including videos and repeated
tracks. This is a recovery **reference**, not an automated restore mechanism.

## Where to find the backup

Default (Linux/macOS):

~~~text
~/.local/state/tidal-dedupe/backups/
~~~

If \`XDG_STATE_HOME\` is set, the backup directory is
\`$XDG_STATE_HOME/tidal-dedupe/backups/\`.

Each successful, mutating run prints the full path, such as
\`playlists-YYYYMMDDTHHMMSSZ-<random>.json\`. No backup file is created
for a dry run, a cancelled run or a run that found nothing to remove.

On Unix-like systems, the application sets the backup directory to mode
\`0700\` and files to \`0600\`. Files contain potentially sensitive information
about listening habits. Do not publish them or send them in bug reports.

## If something goes wrong during deletion

1. **Stop** and do not rerun deduplication immediately. Some playlists may
   already have changed, while others may be untouched.
2. Locate the backup path printed just before removal. Keep an untouched copy
   in another safe location.
3. Inspect playlists in TIDAL and compare them with their snapshots. Each
   playlist is identified by its original ID, not just a name (names can match
   or change).
4. Reconstruct missing entries in TIDAL using the backed-up track/video IDs
   and item order, or use a separately reviewed restoration tool that supports
   this format. Repeated entries are preserved in the export.
5. Verify the final ordering and contents before running deduplication again.

**Important:** tidal-dedupe currently does not provide a restore/import
command and does not automatically undo changes to TIDAL. Reconstruction is
manual. Song availability and TIDAL limitations can prevent an exact restore.

## Inspecting a backup

For a formatted JSON view:

~~~bash
python -m json.tool "/path/to/playlists-...json"
~~~

To print a concise per-playlist listing without external dependencies:

~~~bash
python - "/path/to/playlists-...json" <<'PY'
import json
import sys
from pathlib import Path

backup = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if backup.get("format") != "tidal-dedupe-backup" or backup.get("version") != 1:
    raise SystemExit("Unsupported backup format")
for playlist in backup["playlists"]:
    print(f"\n{playlist['name']} (playlist ID {playlist['id']})")
    for item in playlist["items"]:
        print(f"  {item['position']:>5}: {item['kind']:<5} {item['id']} — {item['title']}")
PY
~~~

This snippet only reads a local JSON file; it **does not** connect to TIDAL or
alter any playlists.

## Backup schema (v1)

Top-level keys:

- \`format\`: \`tidal-dedupe-backup\`
- \`version\`: \`1\`
- \`created_utc\`: timestamp
- \`playlists\`: array in the selected scan/priority order

Each playlist object has \`id\`, \`name\` and an \`items\` array. Each item has
\`position\` (zero-based index), \`kind\` (\`track\` or \`video\`), \`id\`
(the exact TIDAL item ID), \`title\`, \`artist\`, \`album\`, and \`isrc\`
(the last three can be null). Positions are the original positions **before**
any removal, including interleaved videos.

Backups are never automatically deleted or uploaded by tidal-dedupe.
You are responsible for their secure storage and eventual removal.
