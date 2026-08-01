---
id: matplotlib-pruning-needs-frozen-render-matrix
status: active
owners: [codex]
keywords: [matplotlib, pyinstaller, frozen, pruning, fonts, pdf, svg, cjk]
paths:
  - mf4_analyzer/batch_render.py
  - tools/matplotlib_frozen_contract.py
  - tools/build_windows_folder.ps1
  - tools/build_windows_folder_lite.ps1
checks:
  - tools/verify_frozen_batch_render.py --exe <onedir-exe> --evidence-json <path>
tests:
  - tests/test_matplotlib_frozen_contract.py
  - tests/test_frozen_batch_render_smoke.py
  - tests/test_batch_renderer.py
  - tests/test_windows_build_script.py
---

# Matplotlib Pruning Needs A Frozen Render Matrix

Trigger: Changing PyInstaller Matplotlib collection/exclusions, `mpl-data`
pruning, bundled fonts, or the batch renderer's PNG/PDF/SVG paths.

Past failure: Source imports and renderer unit tests could pass while a frozen
artifact omitted a lazy backend/font dependency; installed site-package size
also concealed the real `_internal` footprint and did not prove the pruned
onedir executable could render CJK/vector output.  A failed native PyInstaller
command could also fall through to a stale EXE under `-KeepPrevious`, allowing
new prune/smoke JSON to misrepresent an older artifact as the current build.
Matplotlib 3.11 then enabled its bundled Last Resort fallback by default, while
the four-font pruning rule deleted `LastResortHE-Regular.ttf`; the frozen
renderer failed even though PyInstaller itself completed successfully.

Rule: Keep full/lite exclusions in one executable contract. Always require the
approved four DejaVu Sans faces; when the collected Matplotlib tree contains
`LastResortHE-Regular.ttf`, preserve it too. Remove every other TTF while
retaining AFM/pdfcorefonts, and record `_internal` bytes/files immediately
before and after pruning. Delete prior prune/smoke evidence before invoking
PyInstaller and check its native exit code immediately, before testing EXE
existence or generating new evidence. Never call a prune safe from source
tests: the freshly built windowed executable must render all four batch kinds
to PNG/PDF/SVG and pass CJK warnings,
extractable/rasterizable PDF, and literal Turbo sample checks.  Do not exclude
`mpl_toolkits` without that same post-exclusion frozen evidence.

Verification: Run the four focused test files, including the failed-native-
command/stale-EXE probe, build either Windows onedir flavor, inspect the prune
JSON for before/after bytes/files, and require the frozen-smoke JSON to identify
a `frozen-onedir-executable` with 12 artifacts.
