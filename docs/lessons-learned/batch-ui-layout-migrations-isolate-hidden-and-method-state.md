---
id: batch-ui-layout-migrations-isolate-hidden-and-method-state
status: active
owners: [codex]
keywords: [batch, pyqt, layout, hidden-widget, method-state, axis-range, units, offscreen]
paths: [mf4_analyzer/ui/drawers/batch/method_buttons.py, mf4_analyzer/ui/drawers/batch/output_panel.py, tools/render_batch_compact_ui.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_compact_contract.py, tests/ui/test_batch_output_panel.py]
---

# Batch UI Layout Migrations Isolate Hidden And Method State

Trigger: Replacing a Batch Qt form/layout while retaining compatibility widgets,
or reusing one set of controls across analysis methods whose units or meanings
change.

Past failure: The compact Batch redesign kept an unlaid-out compatibility
`render_group_by` combo alive, but did not explicitly hide it. Qt placed it at
the parameter form origin, where it overlapped the first FFT label only after a
real render. The same pass reused the FFT X range after switching to time, so a
manual `5–800 Hz` range appeared as `5–800 s`.

Rule: Any compatibility-only widget left outside the active layout must be
explicitly hidden and covered by an `isVisibleTo()` assertion after the parent
is shown. When a shared editor changes units or semantics by method, store and
restore state per method (or reset on first visit); never preserve one raw
number by merely changing its label or suffix.

Verification: Show the real BatchSheet under the shipped QSS and assert the
compatibility holder remains hidden. Switch FFT manual X range → time manual X
range → FFT → time and assert each method restores only its own values. Render
the 1080×760 and 1440×900 method matrix and inspect it for overlapping controls
and cross-unit carryover, then run `git diff --check`.
