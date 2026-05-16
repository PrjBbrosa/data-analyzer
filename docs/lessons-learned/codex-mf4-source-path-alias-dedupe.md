---
id: codex-mf4-source-path-alias-dedupe
status: active
owners: [codex]
keywords: [MF4, asammdf, channels_db, source_path, duplicate channels, acquisition replay, batch probe]
paths:
  - mf4_analyzer/io/loader.py
  - mf4_analyzer/ui/drawers/batch/input_panel.py
  - mf4_analyzer/acquisition_capture/backends.py
checks:
  - rg -n "channels_db|unique_mdf_channel_locations|source_from_mf4" mf4_analyzer tests
tests:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_mf4_loader.py tests/test_acquisition_capture_backends.py -q
---

# Codex MF4 Source Path Alias Dedupe

Trigger: Touching MF4 channel enumeration, analyzer channel lists, batch MF4
metadata probes, or acquisition replay source loading.

Past failure: asammdf exposes both a source-path display name such as
`A_side.sig` and the raw channel name `sig` for the same physical
`(group, index)` occurrence. The analyzer and replay UI treated those lookup
keys as separate signals, so a single MF4 channel rendered as duplicate cards
or duplicate selectable channels.

Rule: Deduplicate MF4 channels by physical `(group, index)` occurrence, not by
string prefix stripping alone. Prefer the raw channel name only when it maps to
one physical channel; when the raw name is ambiguous across multiple sources,
keep source-qualified names so real same-name ECU/source signals are not
merged.

Verification: Add or run regression coverage that creates source-path aliases
and ambiguous same-short-name channels. Confirm analyzer loading, batch probing,
and acquisition replay expose one channel for aliases while preserving
source-qualified names for true ambiguity.
