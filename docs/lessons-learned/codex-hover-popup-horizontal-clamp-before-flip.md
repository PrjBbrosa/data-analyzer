---
id: codex-hover-popup-horizontal-clamp-before-flip
status: active
owners: [codex]
keywords: [tooltip, preset, hover, flicker, screen-edge, geometry]
paths: [mf4_analyzer/ui_kit/dialog_geometry.py, mf4_analyzer/ui/inspector_sections/presets.py]
checks: [git diff --check]
tests: [tests/ui_kit/test_dialog_geometry.py, tests/ui/test_preset_bar_lifecycle.py, tests/ui/test_hover_card_screen_fit.py]
---

# Clamp Hover Popup X Before Selecting Its Vertical Side

Trigger: Anchored hover popups flicker near screen edges or in maximized windows.

Past failure: A centered Preset card extended past the right screen edge.
Both above/below candidates failed full-rectangle containment because of X,
so final clamping covered the hovered button. Native Windows repeatedly sent
Enter/Show/Leave/Hide with a stationary cursor (269 events in 1.5 seconds).

Rule: Clamp horizontal placement before choosing an above/below candidate.
When either vertical side fits, preserve the trigger gap. Screen containment
alone does not prove correct placement or stable hover behavior.

Verification: Cover both horizontal edges, both preferred sides, required flips,
and negative screen origins. Exercise the real widget with a stationary native
Windows cursor; the repaired edge case produced only Enter/Show. Keep native
probes separate from offscreen geometry evidence.
