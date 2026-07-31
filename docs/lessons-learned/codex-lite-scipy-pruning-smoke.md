---
id: codex-lite-scipy-pruning-smoke
status: active
owners: [codex]
keywords: [windows, pyinstaller, lite, scipy, openblas, mat, h5py, pyav, frozen-smoke]
paths:
  - mf4_analyzer/io/runtime_dependencies.py
  - tools/build_windows_folder.ps1
  - tools/build_windows_folder_lite.ps1
  - tools/verify_lite_importer_runtime.py
  - tests/test_importer_runtime_smoke.py
checks:
  - .venv-build-win/Scripts/python.exe tools/verify_lite_importer_runtime.py --exe dist/TraceLabAnalyzer7.8/TraceLabAnalyzer7.8.exe
tests:
  - tests/test_windows_runtime_dependencies.py
  - tests/test_windows_build_script.py
  - tests/test_importer_runtime_smoke.py
---

# Lite SciPy Pruning Needs Frozen Import Smoke

Trigger: Reducing SciPy collection or native DLLs in the Windows analyzer-only
PyInstaller build.

Past failure: Whole-SciPy collection inflated the lite artifact even though
the application only needs MAT loading. Source imports alone could not prove
that the frozen executable still retained legacy MAT, v7.3/HDF5 MAT, audio,
and MP4 audio-track loading. The full builder also ran its 12-format render
smoke before replacing bundled MSVC DLLs, so that smoke described a tree that
was mutated afterward.

Rule: Keep the shared frozen-import contract. For lite SciPy pruning, retain
`scipy.io` and `h5py`, leave PyAV's FFmpeg closure intact, and only remove an
exactly resolved SciPy native DLL with a fail-closed layout check. Do not claim
the prune is safe until the freshly built frozen executable loads all four
representative fixtures. In every builder, run the frozen render smoke only
after pruning, DLL replacement, and every other packaged-tree mutation; do not
move the lite smoke ahead of its existing SciPy/Matplotlib pruning boundary.

Verification: Run the collection/build-script and importer-smoke tests, build
the lite onedir artifact, then run `tools/verify_lite_importer_runtime.py`
against its executable. Run focused FFT, FFT-vs-Time, and Order regression
tests to confirm analysis isolation. Keep
`test_frozen_render_smoke_runs_after_every_packaged_tree_mutation` green for
both Windows builders.
