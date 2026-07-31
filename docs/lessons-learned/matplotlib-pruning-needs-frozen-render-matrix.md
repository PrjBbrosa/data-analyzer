---
id: matplotlib-pruning-needs-frozen-render-matrix
status: active
owners: [codex]
keywords: [matplotlib, pyinstaller, frozen, pruning, fonts, pdf, svg, cjk]
paths:
  - mf4_analyzer/batch_render.py
  - tools/build_windows_folder.ps1
  - tools/build_windows_folder_lite.ps1
checks:
  - tools/verify_frozen_batch_render.py --exe <onedir-exe> --evidence-json <path>
tests:
  - tests/test_matplotlib_frozen_contract.py
  - tests/test_frozen_batch_render_smoke.py
  - tests/test_batch_renderer.py
---

# Matplotlib Pruning Needs A Frozen Render Matrix

Trigger: Changing PyInstaller Matplotlib collection/exclusions, `mpl-data`
pruning, bundled fonts, or the batch renderer's PNG/PDF/SVG paths.

Past failure: Source imports and renderer unit tests could pass while a frozen
artifact omitted a lazy backend/font dependency; installed site-package size
also concealed the real `_internal` footprint and did not prove the pruned
onedir executable could render CJK/vector output.

Rule: Keep full/lite exclusions in one executable contract, retain exactly the
approved four DejaVu Sans TTF files plus AFM/pdfcorefonts, and record `_internal`
bytes/files immediately before and after pruning.  Never call a prune safe from
source tests: the freshly built windowed executable must render all four batch
kinds to PNG/PDF/SVG and pass CJK warnings, extractable/rasterizable PDF, and
literal Turbo sample checks.  Do not exclude `mpl_toolkits` without that same
post-exclusion frozen evidence.

Verification: Run the three focused test files, build either Windows onedir
flavor, inspect the prune JSON for before/after bytes/files, and require the
frozen-smoke JSON to identify a `frozen-onedir-executable` with 12 artifacts.
