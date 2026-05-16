# Acquisition Cockpit Polish Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three packaging-and-settings cleanup gaps surfaced by the 2026-05-15 polish-wave review so a fresh clone runs green, the CLI honors user threshold overrides like the GUI does, and a broken settings file never aborts cockpit startup.

**Architecture:** Three disjoint changes. Stage 1 reverts a `.gitignore` allowlist and adds a `pytest.skip` guard so the spec-content test is opportunistic on artifact presence. Stage 2 wires `acquisition_capture.__init__` to call the existing `apply_overrides(load_user_settings())` once at import (best-effort; swallows everything). Stage 3 widens the exception net in `CockpitMainWindow._load_threshold_overrides`. No new modules, no new public APIs.

**Tech Stack:** PyQt5 5.15, pytest 9, asammdf-backed `mf4_analyzer` capture core.

Date: 2026-05-16
Spec: `docs/analyzer/acquisition/specs/2026-05-16-cockpit-polish-cleanup-spec.md`

---

## Non-Negotiable Constraints

- `mf4_analyzer/acquisition_capture/__init__.py` must remain Qt-free. The
  auto-load helper imports only `thresholds` + `logging`.
- The auto-load must not raise — any exception during settings load is
  swallowed and logged at `WARNING`. `KeyboardInterrupt` and `SystemExit`
  must still propagate.
- Test isolation: every new test that mutates `thresholds` calls
  `thresholds.reset_defaults()` in a teardown / `finally` block.
- Tests that import or reload `mf4_analyzer.acquisition_capture` MUST
  monkeypatch `HOME` to a `tmp_path` first; otherwise a developer's real
  `~/.acquisition-cockpit/settings.json` leaks into the test.
- Do not touch `tools/build_windows_folder.ps1`. The PS1 already regenerates
  the spec on each run; that behavior is now considered correct.
- Do not commit `build/spec/MF4DataAnalyzer.spec`. Stage 1 reverts the
  `.gitignore` allowlist so accidental commits are blocked.

## Stage 0 — Baseline Pin

**Goal:** Confirm the local baseline is green before any change.

**Files:** read-only.

- [ ] **Step 1: Run polish-wave + regression suite**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. .venv/bin/python -m pytest tests/test_packaging_imports.py tests/test_acquisition_settings_overrides.py -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/acquisition_ui/test_cockpit_polish_integration.py -v
```

Expected: 3 + 5 + 4 = 12 tests passing (no failures, no errors).

- [ ] **Step 2: Pin local spec artifact presence** (used for Stage 1 verification)

```bash
ls -la "/Users/donghang/Downloads/data analyzer/build/spec/MF4DataAnalyzer.spec"
```

Expected: file present. Note its mtime — Stage 1 will not regenerate it.

## Stage 1 — Packaging Test Gating

**Goal:** Make `test_pyinstaller_spec_lists_new_modules_and_style_data` skip when the spec is absent. Revert the `.gitignore` allowlist.

**Files:**
- Modify: `/Users/donghang/Downloads/data analyzer/tests/test_packaging_imports.py:56-68`
- Modify: `/Users/donghang/Downloads/data analyzer/.gitignore:9-12`

- [ ] **Step 1: Tighten the spec-content test to skip-if-absent**

Open `tests/test_packaging_imports.py`. Replace the body of
`test_pyinstaller_spec_lists_new_modules_and_style_data` so the existing
assertions only run when the spec exists:

```python
def test_pyinstaller_spec_lists_new_modules_and_style_data():
    if not SPEC_PATH.exists():
        pytest.skip(
            "PyInstaller spec is a build artifact; run "
            "tools/build_windows_folder.ps1 to regenerate before asserting."
        )
    text = SPEC_PATH.read_text(encoding="utf-8")

    for module_name in REQUIRED_HIDDEN_IMPORTS:
        assert module_name in text
    assert "mf4_analyzer.ui_kit.style.qss" not in text
    assert "ui_kit" in text and "style.qss" in text
    assert "widgets.*" not in text
    assert (
        'collect_submodules("mf4_analyzer.acquisition_ui.widgets")' in text
        or "collect_submodules('mf4_analyzer.acquisition_ui.widgets')" in text
        or all(module_name in text for module_name in WIDGET_MODULES)
    )
```

The diff is only the new four-line `if not SPEC_PATH.exists(): pytest.skip(...)` block at the top of the function body. Existing assertions stay byte-identical.

- [ ] **Step 2: Run the modified test against the local artifact**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. .venv/bin/python -m pytest tests/test_packaging_imports.py::test_pyinstaller_spec_lists_new_modules_and_style_data -v
```

Expected: PASS (artifact still present locally).

- [ ] **Step 3: Verify the skip path**

```bash
cd "/Users/donghang/Downloads/data analyzer"
mv build/spec/MF4DataAnalyzer.spec build/spec/MF4DataAnalyzer.spec.bak
PYTHONPATH=. .venv/bin/python -m pytest tests/test_packaging_imports.py::test_pyinstaller_spec_lists_new_modules_and_style_data -v
```

Expected: SKIPPED with the reason "PyInstaller spec is a build artifact...".

Restore the artifact:

```bash
mv build/spec/MF4DataAnalyzer.spec.bak build/spec/MF4DataAnalyzer.spec
```

- [ ] **Step 4: Revert the `.gitignore` allowlist**

Open `.gitignore`. The polish-wave wedge currently reads:

```
build/*
!build/spec/
build/spec/*
!build/spec/MF4DataAnalyzer.spec
```

Replace with the pre-wave single line:

```
build/
```

- [ ] **Step 5: Verify the spec file is back to fully ignored**

```bash
cd "/Users/donghang/Downloads/data analyzer"
git check-ignore -v build/spec/MF4DataAnalyzer.spec
```

Expected: output `.gitignore:9:build/	build/spec/MF4DataAnalyzer.spec` (line number may differ — the key signal is that `build/` is the rule).

```bash
git status --porcelain build/
```

Expected: empty (no `??` entry).

- [ ] **Step 6: Run the full packaging suite**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_packaging_imports.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
cd "/Users/donghang/Downloads/data analyzer"
git add tests/test_packaging_imports.py .gitignore
git commit -m "fix(packaging): treat PyInstaller spec as artifact; skip content test when absent

PyInstaller regenerates build/spec/MF4DataAnalyzer.spec on every run, so
the spec is a build artifact, not a checked-in source. Revert the polish
wave's .gitignore allowlist and make the spec-content test skip when the
artifact is absent. tools/build_windows_folder.ps1 stays the source of
truth for hidden imports; the matching PS1 test still gates packaging
coverage."
```

## Stage 2 — CLI Auto-Apply User Threshold Overrides

**Goal:** `mf4_analyzer/acquisition_capture/__init__.py` applies the user settings file once at import. CLI and GUI behave identically.

**Files:**
- Modify: `/Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_capture/__init__.py`
- Modify: `/Users/donghang/Downloads/data analyzer/tests/test_acquisition_settings_overrides.py`

- [ ] **Step 1: Write the parity test (red)**

Append the following two tests to `tests/test_acquisition_settings_overrides.py`. Reuse the existing top-of-file imports (`importlib`, `pytest`, `pathlib.Path`, `mf4_analyzer.acquisition_capture.thresholds`, `mf4_analyzer.acquisition_capture.config_store.ConfigSchemaError`); add any that are missing.

```python
def test_acquisition_capture_package_import_applies_user_overrides(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    thresholds.reset_defaults()
    thresholds.save_user_settings(
        {
            "version": thresholds.SETTINGS_VERSION,
            "thresholds": {"CAN_LOAD_GREEN_MAX_PCT": 11.0},
        }
    )
    thresholds.reset_defaults()

    import importlib
    import mf4_analyzer.acquisition_capture as acquisition_capture

    importlib.reload(acquisition_capture)
    try:
        assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 11.0
    finally:
        thresholds.reset_defaults()


def test_acquisition_capture_package_import_silent_on_corrupt_settings(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings_dir = tmp_path / ".acquisition-cockpit"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_bytes(b"{not json")

    thresholds.reset_defaults()

    import importlib
    import mf4_analyzer.acquisition_capture as acquisition_capture

    importlib.reload(acquisition_capture)
    try:
        assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
    finally:
        thresholds.reset_defaults()
```

- [ ] **Step 2: Run the new tests and confirm red**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_acquisition_settings_overrides.py::test_acquisition_capture_package_import_applies_user_overrides \
  tests/test_acquisition_settings_overrides.py::test_acquisition_capture_package_import_silent_on_corrupt_settings -v
```

Expected: the first test FAILS with `AssertionError: 60.0 != 11.0` (overrides not picked up). The second test passes vacuously (defaults are already 60.0) — that is fine; it locks in the silent-on-corrupt contract for Step 3.

- [ ] **Step 3: Implement the auto-load (green)**

Open `mf4_analyzer/acquisition_capture/__init__.py`. Append the following block at the end of the file, after the existing `__all__` list:

```python
def _autoload_user_threshold_overrides() -> None:
    """Apply user threshold overrides at package import.

    Best-effort: any failure (missing file, IO error, schema error, decode
    error) falls back to defaults silently. ``KeyboardInterrupt`` and
    ``SystemExit`` are NOT caught.
    """
    import logging

    log = logging.getLogger(__name__)
    try:
        overrides = thresholds.load_user_settings()
        if overrides:
            thresholds.apply_overrides(overrides)
    except Exception as exc:  # noqa: BLE001 - silent fallback per spec
        log.warning("could not auto-load user threshold overrides: %s", exc)


_autoload_user_threshold_overrides()
```

- [ ] **Step 4: Run the new tests and confirm green**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_acquisition_settings_overrides.py -v
```

Expected: all `test_acquisition_settings_overrides.py` tests pass (original 5 + new 2 = 7). No new warnings beyond the existing `BLE001` noqa.

- [ ] **Step 5: Run the package-level smoke**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. .venv/bin/python -c "import mf4_analyzer.acquisition_capture; print('OK')"
```

Expected: `OK` to stdout, no traceback.

- [ ] **Step 6: Run full acquisition + P0 + synthetic baseline**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
```

Expected: 207 passed, 1 skipped (matches Stage 0 baseline + new tests).

- [ ] **Step 7: Commit**

```bash
cd "/Users/donghang/Downloads/data analyzer"
git add mf4_analyzer/acquisition_capture/__init__.py tests/test_acquisition_settings_overrides.py
git commit -m "feat(acquisition): auto-apply user threshold overrides on package import

CLI (python -m mf4_analyzer.acquisition_capture ...) now honors
~/.acquisition-cockpit/settings.json the same way the cockpit GUI does.
Best-effort: any IO/schema/decode error falls back to defaults silently
with a logger.warning. Cockpit's own _load_threshold_overrides stays for
mid-session reloads (idempotent)."
```

## Stage 3 — Cockpit Exception Net

**Goal:** `CockpitMainWindow._load_threshold_overrides` catches `OSError` and `UnicodeDecodeError`, not just `ConfigSchemaError`.

**Files:**
- Modify: `/Users/donghang/Downloads/data analyzer/mf4_analyzer/acquisition_ui/main_window.py:389-394`
- Modify: `/Users/donghang/Downloads/data analyzer/tests/acquisition_ui/test_cockpit_polish_integration.py`

- [ ] **Step 1: Write the IsADirectoryError test (red)**

Append the following test to `tests/acquisition_ui/test_cockpit_polish_integration.py`. The existing imports at the top of that file already cover `thresholds`, `Path`, `CockpitMainWindow`.

```python
def test_cockpit_startup_survives_unreadable_settings_file(
    qapp, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings_dir = tmp_path / ".acquisition-cockpit"
    settings_dir.mkdir()
    # Replace the settings file with a directory so Path.read_text raises
    # IsADirectoryError (subclass of OSError) on macOS / Linux.
    (settings_dir / "settings.json").mkdir()

    thresholds.reset_defaults()
    window = CockpitMainWindow()
    try:
        assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
    finally:
        window.close()
        thresholds.reset_defaults()
```

- [ ] **Step 2: Confirm the test fails on the current main_window**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_cockpit_polish_integration.py::test_cockpit_startup_survives_unreadable_settings_file -v
```

Expected: FAIL with `IsADirectoryError: [Errno 21] Is a directory: '.../settings.json'` raised from `CockpitMainWindow.__init__ → _load_threshold_overrides → load_user_settings → Path.read_text`.

- [ ] **Step 3: Broaden the exception in `_load_threshold_overrides`**

Open `mf4_analyzer/acquisition_ui/main_window.py`. Replace the body of `_load_threshold_overrides` (currently lines 389-394):

```python
    def _load_threshold_overrides(self) -> None:
        try:
            thresholds.apply_overrides(thresholds.load_user_settings())
        except (ConfigSchemaError, OSError, UnicodeDecodeError) as exc:
            self._settings_load_error = str(exc)
            logger.warning("could not load acquisition settings: %s", exc)
```

`ConfigSchemaError` is already imported at the top of the module; `OSError` and `UnicodeDecodeError` are builtins.

- [ ] **Step 4: Re-run the new test (green)**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_cockpit_polish_integration.py -v
```

Expected: 5 passed (4 existing + 1 new).

- [ ] **Step 5: Run the cockpit-ui + analyzer-ui regression**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
```

Expected: 526 passed (baseline 525 + 1 new).

- [ ] **Step 6: Commit**

```bash
cd "/Users/donghang/Downloads/data analyzer"
git add mf4_analyzer/acquisition_ui/main_window.py tests/acquisition_ui/test_cockpit_polish_integration.py
git commit -m "fix(acquisition_ui): widen cockpit settings-load exception net

CockpitMainWindow._load_threshold_overrides now catches OSError and
UnicodeDecodeError in addition to ConfigSchemaError, so a directory at
settings.json, a permission error, or a non-UTF-8 file degrades to
defaults instead of aborting cockpit construction. Spec said settings-load
is best-effort; this brings the implementation in line."
```

## Final Rollup Gate

- [ ] **Step 1: Run the four acceptance suites in sequence**

```bash
cd "/Users/donghang/Downloads/data analyzer"
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_packaging_imports.py \
  tests/test_acquisition_settings_overrides.py -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_cockpit_polish_integration.py -v
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
```

Expected counts:

| Command | Expected |
| --- | --- |
| `tests/test_packaging_imports.py + tests/test_acquisition_settings_overrides.py` | 3 + 7 = 10 passed |
| `tests/acquisition_ui/test_cockpit_polish_integration.py` | 5 passed |
| `tests/test_acquisition_* + tests/test_p0_* + tests/synthetic` | 209 passed, 1 skipped (207 baseline + 2 new) |
| `tests/ui + tests/acquisition_ui` | 526 passed |

- [ ] **Step 2: Fresh-clone simulation**

```bash
cd "/Users/donghang/Downloads/data analyzer"
mv build/spec/MF4DataAnalyzer.spec /tmp/MF4DataAnalyzer.spec.bak
PYTHONPATH=. .venv/bin/python -m pytest tests/test_packaging_imports.py -v
mv /tmp/MF4DataAnalyzer.spec.bak build/spec/MF4DataAnalyzer.spec
```

Expected: `test_pyinstaller_spec_lists_new_modules_and_style_data` reports SKIPPED. The other two packaging tests pass.

- [ ] **Step 3: Three-commit log check**

```bash
cd "/Users/donghang/Downloads/data analyzer"
git log --oneline -3
```

Expected (top three lines, top is most recent):

```
<sha> fix(acquisition_ui): widen cockpit settings-load exception net
<sha> feat(acquisition): auto-apply user threshold overrides on package import
<sha> fix(packaging): treat PyInstaller spec as artifact; skip content test when absent
```
