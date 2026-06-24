# BLF DBC Candidate Flow Design

## Goal

Make BLF opening less repetitive when the same DBC applies to multiple BLF
files, while still allowing different BLF files to use different DBC files.
The first version remembers DBC paths that successfully decoded a BLF during
the current app run, persists a recent DBC list for the next app launch, stores
BLF-to-DBC bindings inside `.tlproj` project files, probes those candidates for
later BLF opens, and asks the user before reusing or replacing uncertain
matches.

## Current Behavior

`ProjectIOMixin._load_one()` opens every `.blf` by immediately calling
`_prompt_blf_dbc()`. Canceling the DBC picker passes an empty list to
`DataLoader.load_blf()`, which exposes raw CAN bytes as channels. The UI does
not remember which DBC was used successfully, so opening multiple BLF files
from the same bus repeats the DBC picker each time.

## First-Version Scope

- Remember DBC path lists that successfully decoded a BLF in the current
  session.
- Persist recent successful DBC path lists in the analyzer's user settings so a
  fresh app launch can probe them.
- Persist per-BLF DBC bindings in `.tlproj` project files, using relative DBC
  paths where possible and absolute paths as fallback.
- Probe remembered DBCs, and simple `.dbc` files next to the BLF, before
  opening a DBC file picker.
- Do not expose "open as raw bytes" from the BLF UI flow.
- If the user cancels DBC selection or candidate confirmation, the BLF is not
  opened.
- Keep `DataLoader.load_blf(..., dbc_paths=None)` available for tests and
  non-UI callers; this change is only about the user-facing BLF open flow.

## Candidate Detection

`DataLoader` will expose a lightweight BLF/DBC probe that reads BLF frames and
checks one DBC path list against them without building the final resampled
DataFrame.

The probe reports:

- total BLF frame count and unique CAN id count
- frame count and unique CAN id count that the DBC knows about
- frame count that can be decoded into at least one numeric signal
- numeric decoded signal value count
- unique decoded signal names
- match strength: `none`, `weak`, or `strong`

Suggested strength rules for version one:

- `none`: no frame decodes into numeric signals.
- `strong`: at least 80% of unique BLF CAN ids and 80% of BLF frames decode.
- `weak`: some numeric signal data decodes, but below the strong thresholds.

These thresholds make the app conservative: a partial match can still be used,
but it requires explicit confirmation.

## UI Flow

When opening a `.blf`:

1. Use a verified `.tlproj` BLF-to-DBC binding first when opening a project.
2. Build candidates from successful session DBC path lists, newest first.
3. Add persisted recent DBC path lists loaded from user settings.
4. Add `.dbc` files found in the BLF's directory as single-DBC candidates.
5. Probe each unique candidate.
6. If no candidate matches, show a message explaining that a DBC must be
   selected, then open the DBC picker only if the user chooses to continue.
7. If one strong candidate matches, show a confirmation message:
   "Detected that this BLF can be decoded by `<dbc>`. Use it?"
   Choices are use it, choose another DBC, or cancel.
8. If one weak candidate matches, show a warning-style confirmation explaining
   the partial match. Choices are still use it, choose another DBC, or cancel.
9. If multiple candidates match, ask the user to choose one or choose another
   DBC manually.
10. If manual DBC selection cannot decode any numeric signal from the BLF, show
   a mismatch message and offer to choose again or cancel.
11. After a BLF decodes successfully, remember the DBC path list for future BLF
   opens in the same session and persist it to user settings.

Canceling at any prompt leaves the BLF unopened.

## Persistence

User settings store only recent successful DBC path lists, newest last. Missing
files are pruned on load and write. The recent list is a convenience candidate
source, not a guarantee; every candidate is still probed against the BLF before
use.

Project files store DBC bindings per BLF file reference. Each DBC reference
contains:

- `path_abs`: absolute DBC path at save time
- `path_rel`: path relative to the `.tlproj` directory when possible

When opening a project, the app resolves relative DBC paths first and absolute
paths second. If all saved DBC paths still exist and probe successfully against
the BLF, the BLF opens with that binding without showing the candidate picker.
If the binding is missing or no longer matches, the normal candidate flow runs.

## Error Handling

- Missing optional BLF/DBC dependencies keep the current loader errors.
- A selected DBC that cannot decode the BLF no longer falls through to raw-byte
  UI loading.
- Partial matches are allowed only after explicit confirmation.
- Unexpected decode failures during the final load still surface through the
  existing critical error path.
- User-settings recent DBC entries that point to missing files are ignored and
  removed during the next save.
- Project bindings are backward-compatible: older `.tlproj` files without DBC
  binding fields load normally.

## Testing

Add loader-level tests for strong, weak, and no-match DBC probes.

Add UI dispatch tests for:

- manual DBC selection still opens a BLF and remembers the DBC
- canceling DBC selection leaves the BLF unopened
- a later BLF can reuse a matching remembered DBC after confirmation without
  reopening the file picker
- recent DBC paths loaded from settings are available in a fresh MainWindow
- saving and reopening a `.tlproj` with a BLF uses the stored DBC binding
  without showing the DBC picker

Run focused checks with the repository venv:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py tests/ui/test_blf_open.py -q
```
