---
id: matplotlib-pruning-needs-frozen-render-matrix
status: superseded
superseded_by: docs/superpowers/specs/2026-08-01-batch-qt-render-migration-design.md
owners: [codex]
keywords: [matplotlib, pyinstaller, frozen, pruning, fonts, pdf, svg, cjk]
paths:
  - mf4_analyzer/batch_render.py
  - tools/matplotlib_frozen_contract.py
  - tools/build_windows_folder.ps1
  - tools/build_windows_folder_lite.ps1
checks: []
tests: []
---

# Matplotlib Pruning Needs A Frozen Render Matrix (superseded)

Trigger: Historical work on PyInstaller Matplotlib collection, `mpl-data`
pruning, bundled fonts, or batch PNG/PDF/SVG output.

Past failure: Source tests could pass while a frozen Matplotlib artifact omitted
a lazy backend or font, and stale-EXE fallback could make new evidence describe
an older build.

Rule: Do not apply this Matplotlib-specific pruning contract to the Qt batch
renderer. It was superseded by the
[2026-08-01 Qt render migration](../superpowers/specs/2026-08-01-batch-qt-render-migration-design.md),
whose active packaging, PNG, font, thread, and frozen-smoke gates replace it.

Verification: Load the Qt CJK and Qt batch lifecycle lessons below, then verify
the current migration plan rather than reviving removed Matplotlib assets or
vector-output checks.
