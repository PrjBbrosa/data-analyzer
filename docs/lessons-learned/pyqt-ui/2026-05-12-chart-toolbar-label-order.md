---
id: pyqt-ui/2026-05-12-chart-toolbar-label-order
status: active
owners: [codex]
keywords: [chart_stack, toolbar, locLabel, hint_label, annotation, TimeDomain, overflow, inspector]
paths: [mf4_analyzer/ui/chart_stack.py, mf4_analyzer/ui/style.qss, tests/ui/test_chart_stack.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q]
tests: [tests/ui/test_chart_stack.py]
---

# Chart Toolbar Label Order

Trigger: Load for changes to chart toolbar layout, Matplotlib locLabel, in-toolbar hint text, or per-card controls in `mf4_analyzer/ui/chart_stack.py`.

Past failure: Analysis cards inserted annotation controls before Matplotlib's
fixed `locLabel` and the in-toolbar `_hint_label`, while TimeDomain appended
its toolbar controls after those labels. FFT, FFT vs Time, and Order therefore
showed the toolbar controls and mode hint in the opposite order from
TimeDomain. A second pass found that when Inspector narrowed the chart,
TimeDomain's long text controls were pushed into QToolBar overflow, and
disabled Back/Forward buttons could look absent without a visible disabled
button frame.

Rule: Keep `locLabel` and `_hint_label` before each card's right-side control
spacer. TimeDomain and analysis cards should use the same append-after-hint
pattern unless a future design explicitly says otherwise. For narrow chart
widths, preserve the actual toolbar controls first; compact or hide explanatory
labels before allowing control buttons to be clipped or moved into overflow.
Disabled navigation buttons should still have visible chrome so users can tell
they are unavailable rather than missing.

Verification: Add or update action-order and narrow-width visibility tests that
compare widget indexes and assert TimeDomain control buttons stay visible inside
`toolbar.rect()`, then run
`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q`.
