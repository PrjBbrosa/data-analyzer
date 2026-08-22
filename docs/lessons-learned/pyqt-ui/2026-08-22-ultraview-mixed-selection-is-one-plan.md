---
id: pyqt-ui/2026-08-22-ultraview-mixed-selection-is-one-plan
status: active
owners: [codex]
keywords: [ultraview, mixed selection, nudge, delete, atomic, SelectionMutationPlan, set_free_grid_rects]
paths:
  - mf4_analyzer/ui/ultraview_edits.py
  - mf4_analyzer/ui/ultraview_state.py
  - mf4_analyzer/ui/chart_stack/ultraview/author_edits.py
  - mf4_analyzer/ui/main_window/ultraview_coordinator.py
checks:
  - rg -n "set_free_grid_rects\\(board" mf4_analyzer/ui/main_window/ultraview_coordinator.py
tests:
  - tests/ui/test_ultraview_author_state.py
  - tests/ui/test_ultraview_author_multiselect.py
  - tests/ui/test_ultraview_structure.py
---

# UltraView Mixed Selection Is One Plan

Trigger: Changing UltraView mixed card+author nudge/delete, `set_free_grid_rects`, `apply_author_nudge`, or Board history funnels.

Past failure: `_on_selection_nudge` discarded `set_free_grid_rects` warnings then always called `apply_author_nudge`. Card collision left cards in place while Sticky objects moved, still writing history.

Rule: Build a Qt-free `SelectionMutationPlan` first. Plan must not write the live Board. If any required card update is illegal, out of safety, or colliding, write nothing — cards, authors, history, and dirty all stay put — and show one warning. Success is one `BoardEditEntry`. Do not expand `FROZEN_MUTATION_FUNNEL_EXCEPTIONS` to hide a second writer. Staging DTOs must not assign Board model field names.

Verification: `test_mixed_nudge_collision_moves_neither_and_has_no_entry`, `test_mixed_nudge_past_safety_moves_neither`, `test_mutations_end_in_funnel`, `test_model_fields_written_only_in_state_module`.
