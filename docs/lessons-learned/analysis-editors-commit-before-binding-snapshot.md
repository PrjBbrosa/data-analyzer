---
id: analysis-editors-commit-before-binding-snapshot
status: active
owners: [codex]
keywords: [comparison, focus, save, pending-input, db-reference, cache-only]
paths: [mf4_analyzer/ui/main_window/_analysis_mixin.py, mf4_analyzer/ui/main_window/window.py]
checks: []
tests: [tests/ui/test_analysis_comparison_state_contract.py]
---

# Commit validated editor input before switching its state owner

Trigger: Changing analysis View focus, saving projects, or wiring focus-out-only parameter editors.

Past failure: A dB reference editor with keyboardTracking disabled held typed text while save captured its old numeric value. Its deferred display callback could later submit DSP on a cache miss and resolve a different focused View.

Rule: Flush the outgoing editor through its own validation before snapshot or binding change; preserve invalid-input feedback and the last valid value. Display-only refresh must use cached results and retain the edited state identity across deferred callbacks. Respect valueChanged/value_committed ordering when Auto-to-Manual changes finish after the value signal.

Verification: Use actual key entry without Return, save/reopen and A/B focus changes; drain queued events before asserting no DSP submission. Test invalid values, Auto-to-Manual commit, and closing/deleting/changing focus before a deferred refresh. Run tests/ui/test_analysis_comparison_state_contract.py in the project Qt runtime.
