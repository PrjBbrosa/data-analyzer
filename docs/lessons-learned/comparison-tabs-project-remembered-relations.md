---
id: comparison-tabs-project-remembered-relations
status: active
owners: [codex]
keywords: [comparison, navigation, view-tab, provider, persistence]
paths: [mf4_analyzer/ui/analysis_section_page.py, mf4_analyzer/ui/main_window/_analysis_mixin.py]
checks: []
tests: [tests/ui/test_analysis_view_navigation_contract.py]
---

# Comparison tabs project remembered relations through production wiring

Trigger: Changing analysis View navigation, comparison focus, or half-color tab indicators.

Past failure: Swatch tests injected a correct fake relation mapping, while the production page queried only its mounted peer. Switching away erased the indicator although the relation remained. Peer-tab clicks also focused a canvas without switching manager.active, splitting the tab background and active marker.

Rule: Tabs navigate pages; canvas clicks focus panes. Read remembered relationships from their owner, independently of mounted widgets. Capture outgoing edits before detaching bindings. Keep native tab selection and the confirmed manager identity aligned, including direct activation and overflow.

Verification: Exercise real MainWindow wiring and actual tab/overflow/canvas clicks across A+B → B → C → B → A. Check inactive-host swatch pixels, multiple relations, pending input, deletion and project reopen. A fake-provider painter test alone does not close the integration contract.
