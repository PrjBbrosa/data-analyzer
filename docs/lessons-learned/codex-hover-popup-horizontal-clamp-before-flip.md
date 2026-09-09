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

Past failure: Horizontal overflow rejected valid above/below candidates. Fixing
X passed a short synthetic summary probe but missed full FFT vs Time presets:
neither vertical side fit, so final clamping still covered the trigger. The
user reproduced flicker immediately after the fix was published. The real
main window produced 89-95 hover/show/hide events per second.

Rule: Clamp horizontal placement before choosing above/below. If neither
vertical side fits, try beside the whole preset row. Pure display cards must
not intercept native mouse input when a tiny work area forces overlap.
Screen containment alone does not prove stable hover behavior.

Verification: Cover both edges, preferred sides, flips, negative origins,
and real full builtin/custom preset payloads with production styling. Native
probes must verify that the cursor reaches the enabled target, the card actually
shows, and no repeated Leave/Hide occurs. Zero events without a visible card is
not a pass. Keep native foreground and offscreen geometry evidence separate.
