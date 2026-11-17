---
id: dialog-size-guards-must-respect-window-purpose
status: active
owners: [codex]
keywords: [qt, dialog, geometry, content-height, tool-window, regression]
paths: [mf4_analyzer/ui_kit/dialog_geometry.py, mf4_analyzer/ui_kit/message_dialog.py]
checks: [show production short prompt with QSS and compare actual height to content-derived plan]
tests: [tests/ui_kit/test_dialog_geometry.py, tests/ui_kit/test_message_dialog.py, tests/ui/test_tool_window_screen_fit.py]
---

# Dialog Size Guards Must Respect Window Purpose

Trigger: Changing shared top-level window minimum sizes, degenerate-plan rejection, or native frame correction.

Past failure: A tool-window fix rejected any decorated client dimension under 200. The production unsaved-project prompt planned 380×134 but retained 346×307, leaving a large blank body. All 75 existing geometry/message tests passed because no assertion compared the short prompt's actual height with its content-derived plan. The same floor also appeared in post-show frame shrink.

Rule: Distinguish content-sized prompts from workspace windows through an explicit owner contract. Keep workspace protection, allow valid short content layouts, and use the same purpose policy in first fit and native frame correction. A counterfactual probe explains causality; it is not a production fix or Windows acceptance.

Verification: Show the production prompt with shared QSS, inspect rendered output and measured body/footer geometry, test short→long→short, and pair it with tool-window protection and frame-containment tests. The 2026-11-17 review reproduced the defect. The content/workspace split is now on the product path, and the Cocoa short unsaved prompt measured surplus 0. Windows validation remains pending. See docs/analyzer/reviews/2026-11-17-import-budget-and-dialog-recovery-report.md.
