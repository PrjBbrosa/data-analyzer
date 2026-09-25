---
id: parentless-popup-final-reference-can-break-sip-exit-iteration
status: active
owners: [codex]
keywords: [PyQt5, SIP, QObject, destroyed, parentless, shutdown, use-after-free]
paths: [mf4_analyzer/ui/inspector_sections/presets.py, mf4_analyzer/ui_kit/glass_tooltip.py]
checks: [git diff --check]
tests: [tests/ui/test_popup_shutdown_subprocess.py, tests/ui/test_preset_bar_lifecycle.py, tests/ui/test_hover_card_screen_fit.py, tests/ui/test_glass_tooltip.py]
---

# Parentless Popup Final Reference Can Break SIP Exit Iteration

Trigger: Changing cached parentless Qt popups, destroyed callbacks, or diagnosing crashes in cleanup_qobject / sip_api_visit_wrappers at interpreter exit.

Past failure: On macOS Cocoa with PyQt5 5.15.11 / PyQt5-sip 12.19.0,
PresetBar's unparented _PresetHoverCard and the global _GlassTooltipPopup
could each have one remaining Python reference. PyQt's exit visitor deleted
the QObject; its destroyed callback cleared that last reference and freed the
SIP wrapper. SIP then read sw->next from the freed wrapper. LLDB stopped at
sip_api_visit_wrappers +100 and identified both classes; PYTHONMALLOC=debug
exposed 0xdddddddddddddddd in the wrapper. Native Cmd+Q reproduced the crash.

Rule: Keep destroyed invalidation and sip.isdeleted guards; they solve a
separate stale-wrapper problem. Also give popups explicit Qt ownership or
finish their destruction while QApplication is alive, before SIP's atexit
traversal. Keep a strong local reference across explicit destruction. Do not
silence crashes with os._exit, discard destroyed invalidation, or assume
window.close and a passing in-process widget test prove clean process exit.

Verification: Use fresh subprocesses with the real Cocoa backend and
PYTHONMALLOC=debug; check process exit codes, including native Cmd+Q after
showing a tooltip. A minimal failing case is a parentless QObject stored in
owner.object whose destroyed callback sets owner.object=None; parenting it to
QApplication avoids this case. In the full app, parenting preset cards alone
left the glass-tooltip crash; an experimental pre-atexit teardown of both
popup classes eliminated the observed reproduction. The source fix now gives each preset card its PresetBar parent and connects
app-wide tooltip disposal to QApplication.aboutToQuit (stop timer, hide,
deleteLater). Do not copy the diagnostic topLevelWidgets sweep into production.
Regression coverage checks owner deletion, no late popup revival, both close
and app.quit subprocesses with PYTHONMALLOC=debug, and process exit status.
Real Cocoa validation after the fix covered four automatic exits and native
Cmd+Q with the debug allocator, plus preset-card rendering/geometry. This
remains source/runtime evidence, not Windows frozen acceptance.
