# Generic ASCII Import Design

## Goal

Import tabular ASCII by its observed structure rather than its file extension,
while refusing to invent a time axis when neither a time column nor a
structurally verified sampling interval exists.

## Decision

Use a hybrid probe.  Existing delimited CSV handling remains the first path.
A fixed-width candidate is accepted only after at least eight consecutive,
same-width, all-numeric records and an aligned nonnumeric header are found.
Known metadata layouts may supply a sample interval only when their complete
structural signature matches.  Extension and header strings are hints, not
source-of-truth provenance.

## Contract

`DataLoader.load_ascii(path)` returns `(data, channels, units, fs, metadata)`.
`fs` is set only for a recognized metadata interval; a normal time-named column
continues to be resolved by `FileData`.  An ASCII table without either raises a
clear error instead of silently accepting the inherited 1000 Hz default.

`metadata` records `source_kind=ascii`, `ascii_kind`, `ascii_confidence`, and
the detector evidence.  Fixed-width parsing preserves missing values rather
than interpolating or deleting rows during import.

## Scope

- Delimited `.asc` retains current CSV behavior.
- Fixed-width scientific-notation tables with optional metadata, header, and
  unit rows are supported.
- Batch and GUI route `.asc` through the new loader.
- A generic numeric-looking text block without an aligned header is rejected.

## Non-goals

- TDMS, CANoe ASC logs, and unstructured event logs.
- Guessing sampling rate from an arbitrary scalar.
- A full import-configuration dialog in this change; ambiguous inputs fail
  with evidence and require a source-specific follow-up.
