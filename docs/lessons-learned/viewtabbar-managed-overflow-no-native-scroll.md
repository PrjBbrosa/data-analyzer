---
id: viewtabbar-managed-overflow-no-native-scroll
status: active
owners: [codex]
keywords: [viewtabbar, overflow, qtabbar, scroll-buttons, cocoa]
paths:
  - mf4_analyzer/ui/view_tabbar.py
  - tests/ui/test_view_tabbar.py
checks:
  - rg -n "setUsesScrollButtons|minimumSizeHint|ScrollLeftButton|ScrollRightButton" mf4_analyzer/ui/view_tabbar.py tests/ui/test_view_tabbar.py
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_tabbar.py -q -p no:cacheprovider
---

# ViewTabBar Managed Overflow Has No Native Scroll Controls

Trigger: Changing ViewTabBar width budgeting, compact labels, or overflow
presentation.

Past failure: QTabBar native scroll controls surfaced beside the active View as
two blank rounded tab-like shells on Cocoa, creating a second overflow route.
Disabling them alone made Qt report every tab as its minimum width, preventing
the host from narrowing enough for the managed tail-retirement policy.

Rule: ViewTabBar owns overflow through compact labels and the managed `»N`
popup. Keep native QTabBar scroll controls disabled and let _ViewTabs report a
zero horizontal minimum so the owner can compact and retire tail tabs.

Verification: Run the owner tests, including the no-native-scroll-controls
regressions, and verify a narrow production-styled bar shows `»N`, has no
visible ScrollLeftButton/ScrollRightButton, and retains the current View.
