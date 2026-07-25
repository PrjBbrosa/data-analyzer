# Lite Importer Dependency Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink the Windows analyzer-only package by replacing whole-SciPy collection with the tested `scipy.io.loadmat` collection path while preserving all documented `.mat` and audio/video imports.

**Architecture:** The runtime-dependency contract remains the sole declaration of optional importer packages. It gains an explicit `full`/`lite` collection flavor; only the lite flavor changes SciPy from whole-package collection to PyInstaller-discovered `scipy.io`/`scipy.io.matlab` imports. The normal PyInstaller SciPy hook remains responsible for native dependency closure.

**Tech Stack:** Python 3.12, PyInstaller, PowerShell, pytest, SciPy, h5py, PyAV.

## Global Constraints

- Lite supports legacy `.mat`, v7.3/HDF5 `.mat`, and `.mp4`, `.mov`, `.mkv`, `.m4v`, `.mp3`, `.m4a`, `.aac`, `.wav`, and `.flac` inputs.
- The full `build_windows_folder.ps1` builder retains `--collect-all scipy`.
- Lite must not pass `--collect-all scipy`; it passes hidden imports for `scipy.io` and `scipy.io.matlab`.
- Lite excludes only the import-blocker-proven-unused SciPy modules: `optimize`, `special`, `linalg`, `spatial`, `interpolate`, `stats`, `signal`, `fft`, `integrate`, and `ndimage`.
- Lite removes only its single `libscipy_openblas*.dll` after PyInstaller collection and only after resolving exactly one matching DLL under the current artifact's `_internal/scipy.libs` directory.
- Retain `h5py` collection and PyAV's FFmpeg DLL closure.
- Do not touch FFT, FFT-vs-Time, Order, batch, or analysis UI/canvas production modules.
- Run the frozen-import verifier, focused importer tests, focused analysis tests, and a fresh Windows lite build.

---

### Task 1: Add flavor-aware runtime dependency collection

**Files:**
- Modify: `mf4_analyzer/io/runtime_dependencies.py:99-105`
- Modify: `tools/windows_runtime_dependencies.py:20-35`
- Test: `tests/test_windows_runtime_dependencies.py:12-30`

**Interfaces:**
- Consumes: `FROZEN_IMPORT_DEPENDENCIES` and `pyinstaller_collection_args()`.
- Produces: `pyinstaller_collection_args(flavor: str = "full") -> tuple[str, ...]` and CLI `--flavor {full,lite}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_lite_collection_keeps_mat_and_av_dependencies_without_whole_scipy():
    args = pyinstaller_collection_args("lite")

    assert "scipy.io" in args
    assert "scipy.io.matlab" in args
    assert ("--collect-all", "scipy") not in zip(args[::2], args[1::2])
    assert ("--collect-all", "h5py") in zip(args[::2], args[1::2])
    assert ("--collect-all", "av") in zip(args[::2], args[1::2])


def test_collection_rejects_unknown_flavor():
    with pytest.raises(ValueError, match="unknown frozen-build flavor"):
        pyinstaller_collection_args("portable")
```

- [ ] **Step 2: Run the new tests to verify RED**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_windows_runtime_dependencies.py -q`

Expected: FAIL because `pyinstaller_collection_args` does not accept a flavor.

- [ ] **Step 3: Implement the smallest flavor-aware argument generator**

```python
def pyinstaller_collection_args(flavor: str = "full") -> tuple[str, ...]:
    if flavor not in {"full", "lite"}:
        raise ValueError(f"unknown frozen-build flavor: {flavor}")
    args: list[str] = []
    for dependency in FROZEN_IMPORT_DEPENDENCIES:
        if flavor == "lite" and dependency.package == "scipy":
            args.extend(("--hidden-import", "scipy.io"))
            args.extend(("--hidden-import", "scipy.io.matlab"))
        else:
            args.extend(("--collect-all", dependency.package))
    if flavor == "lite":
        for module in LITE_SCIPY_EXCLUDED_MODULES:
            args.extend(("--exclude-module", module))
    return tuple(args)
```

Declare `LITE_SCIPY_EXCLUDED_MODULES` as the exact ten-module tuple from the global constraint. Add an argparse choice `--flavor`, defaulting to `full`, and pass it to the generator when `--pyinstaller-args-json` is selected.

- [ ] **Step 4: Run the dependency tests and verifier to verify GREEN**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_windows_runtime_dependencies.py -q`

Expected: PASS.

Run: `.\\.venv-build-win\\Scripts\\python.exe tools\\windows_runtime_dependencies.py --verify --require-installed --requirements requirements.txt --build-script tools\\build_windows_folder.ps1 --build-script tools\\build_windows_folder_lite.ps1`

Expected: `Windows packaging contract: OK`.

- [ ] **Step 5: Commit the completed contract task**

```bash
git add mf4_analyzer/io/runtime_dependencies.py tools/windows_runtime_dependencies.py tests/test_windows_runtime_dependencies.py
git commit -m "feat: specialize lite importer collection"
```

### Task 2: Wire explicit flavors into both builders

**Files:**
- Modify: `tools/build_windows_folder.ps1:98`
- Modify: `tools/build_windows_folder_lite.ps1:104`
- Test: `tests/test_windows_build_script.py:135-154`

**Interfaces:**
- Consumes: `tools/windows_runtime_dependencies.py --pyinstaller-args-json --flavor <flavor>`.
- Produces: Full requests `full`; lite requests `lite` and no longer receives a whole-SciPy collection argument.

- [ ] **Step 1: Write the failing build-script assertions**

```python
def test_windows_build_scripts_request_their_collection_flavors():
    full = (ROOT / "tools" / "build_windows_folder.ps1").read_text(encoding="utf-8")
    lite = (ROOT / "tools" / "build_windows_folder_lite.ps1").read_text(encoding="utf-8")

    assert "--pyinstaller-args-json --flavor full" in full
    assert "--pyinstaller-args-json --flavor lite" in lite
    assert '"--collect-all", "scipy"' not in lite
```

- [ ] **Step 2: Run the assertion to verify RED**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_windows_build_script.py -q`

Expected: FAIL because neither builder supplies `--flavor`.

- [ ] **Step 3: Pass the flavor to the existing runtime-dependency CLI**

```powershell
# Full builder
$RuntimeDependencyArgsJson = & $VenvPython $RuntimeDependencyTool --pyinstaller-args-json --flavor full

# Lite builder
$RuntimeDependencyArgsJson = & $VenvPython $RuntimeDependencyTool --pyinstaller-args-json --flavor lite
```

Do not alter the full builder's acquisition, Qt, or PyAV configuration.

- [ ] **Step 4: Run build-script tests and the contract verifier to verify GREEN**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_windows_build_script.py tests/test_windows_runtime_dependencies.py -q`

Expected: PASS.

Run: `.\\.venv-build-win\\Scripts\\python.exe tools\\windows_runtime_dependencies.py --pyinstaller-args-json --flavor lite`

Expected: JSON contains `scipy.io` and `scipy.io.matlab`, contains `h5py` and `av`, and has no `--collect-all scipy` pair.

- [ ] **Step 5: Commit the completed builder task**

```bash
git add tools/build_windows_folder.ps1 tools/build_windows_folder_lite.ps1 tests/test_windows_build_script.py
git commit -m "build: use compact scipy collection in lite"
```

### Task 3: Verify importer behavior, analysis isolation, and measured size

**Files:**
- Modify: `MF4 Data Analyzer V1.py:7-42`
- Modify: `tools/build_windows_folder.ps1:183-214`
- Modify: `tools/build_windows_folder_lite.ps1:121-235`
- Create: `mf4_analyzer/io/importer_runtime_smoke.py`
- Create: `tools/verify_lite_importer_runtime.py`
- Test: `tests/test_importer_runtime_smoke.py`
- Test: `tests/test_mat_format.py`
- Test: `tests/test_audio_loader.py`
- Test: `tests/test_fft_amplitude_normalization.py`
- Test: `tests/test_order_analysis.py`
- Test: `tests/ui/test_fft_audio_compute_safety.py`
- Test: `tests/ui/test_fft_time_coordinator.py`
- Generated: `dist/TraceLabAnalyzer7.8/`

**Interfaces:**
- Consumes: the lite builder with `-SkipInstall` and the existing importer and analysis tests.
- Produces: `run(paths: Sequence[Path], output_path: Path) -> int`, entry flag `--importer-runtime-smoke --import-path <path>... --json <path>`, and measured artifact evidence.

- [ ] **Step 1: Write the failing non-GUI importer-smoke test**

```python
def test_importer_runtime_smoke_loads_each_path_and_writes_channel_counts(tmp_path):
    legacy_mat = ROOT / "testdoc" / "175rpm_-45deg-270tighten.mat"
    output = tmp_path / "importer-smoke.json"

    assert run([legacy_mat], output) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["files"][0]["channels"] > 0
```

- [ ] **Step 2: Run the new smoke test to verify RED**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_importer_runtime_smoke.py -q`

Expected: FAIL because `mf4_analyzer.io.importer_runtime_smoke` does not exist.

- [ ] **Step 3: Implement the smoke helper and frozen entry mode**

```python
def run(paths: Sequence[Path], output_path: Path) -> int:
    records = []
    for path in paths:
        if path.suffix.lower() == ".mat":
            groups = DataLoader.load_mat(path)
            channels = sum(len(group["channels"]) for group in groups)
        elif path.suffix.lower() in AUDIO_VIDEO_EXTS:
            _data, channel_names, _units, _fs, _meta = DataLoader.load_audio_video(path)
            channels = len(channel_names)
        else:
            raise ValueError(f"unsupported importer smoke path: {path}")
        records.append({"path": str(path), "channels": channels})
    output_path.write_text(json.dumps({"files": records}), encoding="utf-8")
    return 0 if all(record["channels"] > 0 for record in records) else 1
```

Add `--importer-runtime-smoke` and repeatable `--import-path` to the existing early child-mode parser. Require both at least one import path and `--json`; import and call `run()` before `mf4_analyzer.app.main` is imported.

- [ ] **Step 4: Add the Windows frozen-smoke launcher and verify GREEN**

`tools/verify_lite_importer_runtime.py` must use `tempfile.TemporaryDirectory`, `scipy.io.savemat` to write `legacy.mat`, `h5py.File` plus a MATLAB v7.3 userblock header to write numeric `time` and `signal` datasets to `sample-v73.mat`, `wave.open` to write a 48 kHz mono `sample.wav`, and PyAV to write an AAC-audio `sample.mp4`. It must invoke:

```text
<exe> --importer-runtime-smoke --import-path <temp>/legacy.mat --import-path <temp>/sample-v73.mat --import-path <temp>/sample.wav --import-path <temp>/sample.mp4 --json <temp>/result.json
```

The launcher must parse `result.json`, require exactly four records, and require every `channels` value to be greater than zero.

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_importer_runtime_smoke.py tests/test_mat_format.py tests/test_audio_loader.py -q`

Expected: PASS.

- [ ] **Step 5: Run source-level analysis regressions before rebuilding**

Run: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_mat_format.py tests/test_audio_loader.py tests/test_fft_amplitude_normalization.py tests/test_order_analysis.py tests/ui/test_fft_audio_compute_safety.py tests/ui/test_fft_time_coordinator.py -q`

Expected: PASS; no production FFT or Order code imports SciPy.

- [ ] **Step 6: Build a fresh lite artifact**

Run: `powershell -ExecutionPolicy Bypass -File tools\\build_windows_folder_lite.ps1 -SkipInstall`

Expected: an onedir folder at `dist\\TraceLabAnalyzer7.8` and a printed size smaller than the 383.1 MB baseline.

After PyInstaller succeeds, the lite builder resolves
`$OutputDir\\_internal\\scipy.libs`, finds exactly one
`libscipy_openblas*.dll` item, and removes that exact resolved file. The
four-fixture frozen importer smoke is mandatory evidence that this prune is
safe; if it fails, remove the prune block and rebuild before completion.

- [ ] **Step 7: Run the frozen import smoke launcher**

Run: `.\\.venv-build-win\\Scripts\\python.exe tools\\verify_lite_importer_runtime.py --exe dist\\TraceLabAnalyzer7.8\\TraceLabAnalyzer7.8.exe`

Expected: JSON result has four nonzero channel counts and the command returns zero. Do not remove `scipy.libs` unless a separately rebuilt artifact without it passes this command.

- [ ] **Step 8: Record before/after component sizes**

Run: `Get-ChildItem -LiteralPath dist\\TraceLabAnalyzer7.8\\_internal -Directory | ForEach-Object { $n=(Get-ChildItem $_.FullName -File -Recurse | Measure-Object Length -Sum).Sum; [PSCustomObject]@{Name=$_.Name; SizeMB=[math]::Round($n/1MB,1)} } | Sort-Object SizeMB -Descending`

Expected: no whole `scipy` toolkit trees such as `stats`, `optimize`, `special`, `linalg`, `signal`, `spatial`, or `interpolate`; `h5py`, `av`, and `av.libs` remain.

- [ ] **Step 9: Commit the verification helper and report measured build evidence**

```bash
git add MF4\ Data\ Analyzer\ V1.py mf4_analyzer/io/importer_runtime_smoke.py tools/verify_lite_importer_runtime.py tests/test_importer_runtime_smoke.py
git commit -m "test: verify compact lite importers"
```

Do not create a commit when no tracked verification artifact changed; instead record exact build and smoke output in the handoff.
