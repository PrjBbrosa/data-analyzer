---
id: changelog-slides-reserve-bottom-safe-area
status: active
owners: [codex]
keywords: [release-notes, changelog, help-deck, pagination, bottom-safe-area]
paths: [mf4_analyzer/help/TraceLab-使用说明.html, tests/test_help_content.py]
checks: ["TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_help_content.py -q", "Playwright at 1920x1080 and 1280x720: newest release stays near the front, history is packed at the end, and content stays above deck controls"]
tests: [tests/test_help_content.py]
---

# Changelog Slides Keep Recent Front And Pack History At End

Trigger: Adding or editing entries in the application-help changelog deck.

Past failure: Appending all releases to one fixed-height slide hid the final
lines behind the floating controls. Splitting to exactly one release per slide
fixed the overlap but created excessive pages and scattered historical records.
Mechanical version-label and Windows package-name sync bullets also consumed
space without describing user-visible changes.

Rule: Keep the newest release on a dedicated recent-update slide near the front.
Move older releases to a history appendix at the end and greedily pack multiple
releases per slide from their actual rendered heights, while reserving visible
bottom whitespace above the floating controls. Keep changelog items limited to
actual behavior or capability changes; synchronize runtime and package version
surfaces elsewhere without recording that bookkeeping in every release.

Verification: Run the help-content tests and render the deck at 1920x1080 and
1280x720. Confirm that the newest release is near the front, every older release
appears exactly once on the final history pages, total page count stays compact,
and the last history entry remains inside the content body with visible space
above the control bar.
