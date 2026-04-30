---
id: codex-performance-ui-audit-flow
status: active
owners: [codex]
keywords: [performance, asammdf, PlotSignal.trim, viewport, envelope, toast, PresetBar, QMessageBox, audit, report, 先别改, 别直接改]
paths: [mf4_analyzer/ui/main_window.py, mf4_analyzer/ui/canvases.py, tests/ui/test_main_window_smoke.py, docs/superpowers/reports/*]
checks: [rg -n Toast, rg -n QMessageBox, rg -n _ds, rg -n PlotSignal]
tests: [tests/ui/test_main_window_smoke.py]
---

# Codex Performance And UI Audit Flow

Trigger: Load when the user asks for performance investigation, smoothness comparisons, non-invasive optimization proposals, or read-only UI audits.

Past failure: Work became risky when it jumped from a subjective performance complaint directly to code changes, or when UI audits checked source changes without checking stale tests and modal-to-toast behavior.

Rule: For performance work, research and write the report first when the user says not to edit, and keep proposed optimizations invisible to UI and workflow unless they broaden scope. For UI audits, read the requested files completely, cite exact lines, and cross-check tests that may still patch old modal paths after toast-based UX changes.

Verification: For smooth plotting work, compare current code against viewport-aware trimming/envelope patterns and save the report in the expected repo report folder. For audit work, grep `Toast`, `QMessageBox.warning`, and affected smoke tests before declaring the behavior aligned.
