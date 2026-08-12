---
id: codex-viewstate-composite-key-tables-stay-in-sync
status: active
owners: [codex]
keywords: [ylims, remap_view_fids, ViewState, composite-key, fid-map, project-io]
paths:
  - mf4_analyzer/ui/project_io.py
  - mf4_analyzer/ui/view_state.py
  - mf4_analyzer/ui/main_window/_channel_scope_mixin.py
  - mf4_analyzer/ui/pg_canvas/_shared.py
checks:
  - rg -n "ylims" mf4_analyzer/ui/project_io.py mf4_analyzer/ui/main_window/_channel_scope_mixin.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_project_session.py::test_project_roundtrip_preserves_per_channel_ylims tests/ui/test_project_session.py::test_file_removal_drops_ylims_for_closed_fid tests/test_project_io.py::test_remap_rewrites_and_drops -q
---

# ViewState Composite-Key Tables Stay In Sync

Trigger: Touching `remap_view_fids`, close-file ViewState cleanup, or any
persisted TimeDomain table keyed by `_view_state_channel_key` / JSON
`[fid, name]`.

Past failure: `colors`/`checked`/`hidden_channels` were remapped and scrubbed on
project reopen / file close, but `ylims` used the same composite encoding and
was left untouched — every reopen dropped per-channel Y scales (A3), and closed
fids left orphan ylims entries that could be written back.

Rule: When adding or changing a ViewState field whose identity embeds `fid`,
update all three surfaces together: `remap_view_fids`,
`_filter_time_view_state_for_removed_fids` (and channel removal if applicable),
and restore-side coercion. Decode with `json.loads` → `[fid, name]`, remap or
drop, re-encode with the shared encoder. Do not invent a second degenerate-span
threshold for pair validation — reuse `_DEGENERATE_SPAN_RATIO`.

Verification: Save→same-window reopen asserts remapped ylims survive; close-fid
filter drops matching ylims keys; `remap_view_fids` unit coverage includes
ylims; old payloads without ylims remain empty-compatible.
