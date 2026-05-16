# Acquisition Cockpit Polish Cleanup Spec

Date: 2026-05-16
Status: Execution-ready draft
Plan: `docs/analyzer/acquisition/plans/2026-05-16-cockpit-polish-cleanup-implementation.md`
Builds on: `docs/analyzer/acquisition/specs/2026-05-15-cockpit-polish-wave-spec.md`

## Source Inputs

- 2026-05-15 polish-wave review (this session) — three concrete gaps:
  - `build/spec/MF4DataAnalyzer.spec` is required by
    `tests/test_packaging_imports.py::test_pyinstaller_spec_lists_new_modules_and_style_data`
    but is **not** tracked in git (`git ls-tree HEAD -- build/` is empty), so
    a fresh clone / CI run fails the test with `FileNotFoundError`. The local
    artifact additionally contains codex's hardcoded
    `Z:\Downloads\data analyzer\...` paths which we do not want to commit.
  - `mf4_analyzer/acquisition_capture/__init__.py` does NOT auto-load user
    threshold overrides on package import. Only `CockpitMainWindow._load_threshold_overrides`
    applies them, so the CLI path
    (`python -m mf4_analyzer.acquisition_capture --backend fake ...`) runs
    with defaults even when `~/.acquisition-cockpit/settings.json` exists.
    The original 2026-05-15 plan §Stage 2 listed this as a `Modify` item;
    spec was "MAY". We bring CLI and GUI into parity.
  - `CockpitMainWindow._load_threshold_overrides` only catches
    `ConfigSchemaError`. A corrupt-but-readable settings file raises
    `ConfigSchemaError` (caught), but a `PermissionError` / `IsADirectoryError` /
    `UnicodeDecodeError` on `Path.read_text` will surface as an uncaught
    exception and abort cockpit construction. Settings-load is best-effort
    by spec; any IO failure must degrade silently to defaults.

## Goal

Close the three packaging-and-settings cleanup gaps left by the polish wave
so that:

- A fresh clone runs `pytest tests/test_packaging_imports.py` green without
  any prior build invocation.
- The CLI (`python -m mf4_analyzer.acquisition_capture ...`) honors
  `~/.acquisition-cockpit/settings.json` exactly like the Cockpit GUI does.
- A corrupt, unreadable, or non-UTF-8 settings file never aborts Cockpit
  construction.

## Scope

In scope:

- Test gating: make `test_pyinstaller_spec_lists_new_modules_and_style_data`
  skip when `build/spec/MF4DataAnalyzer.spec` is absent; tighten the assertion
  set so the test still catches missing hidden-imports when a freshly
  generated spec is present.
- `.gitignore` revert: drop the `!build/spec/MF4DataAnalyzer.spec` allowlist
  added during the polish wave. The spec is a generated artifact and must
  stay ignored.
- Package-load auto-apply: `mf4_analyzer/acquisition_capture/__init__.py`
  calls `apply_overrides(load_user_settings())` once at import time, swallowing
  any exception (silent fallback to defaults).
- Exception coverage: `CockpitMainWindow._load_threshold_overrides` catches
  `ConfigSchemaError` AND `OSError` AND `UnicodeDecodeError`.

Out of scope:

- Spec-vs-implementation cosmetic mismatches (status-bar " samples" suffix,
  `跳到 A2L 源行` permanently disabled). These are documented in the polish
  wave review and considered acceptable for v1.
- Rewriting `tools/build_windows_folder.ps1`. The PS1 already regenerates
  the spec on every run, which is correct now that the spec is treated as
  a pure artifact.
- The `.codex/config.toml` `codex_hooks → hooks` rename — handled by
  `scripts/lessons/check.py` deprecation WARN.

## Product Decisions

| Topic | Decision |
| --- | --- |
| PyInstaller spec file | Treat `build/spec/MF4DataAnalyzer.spec` as a build artifact. Do NOT commit. The Windows build script regenerates it on every run with the local repo paths. The `--collect-submodules` / `--hidden-import` argument list in `tools/build_windows_folder.ps1` is the source of truth for what gets packaged. |
| Spec content test | `test_pyinstaller_spec_lists_new_modules_and_style_data` becomes opportunistic: it `pytest.skip`s when the spec file is absent, and asserts the same content invariants when present. The PS1 hidden-import contract test (`test_windows_build_script_lists_new_modules_and_widget_collection`) is the must-pass gate for packaging coverage. |
| CLI override parity | `acquisition_capture/__init__.py` loads `default_user_settings_path()` once and applies via `apply_overrides`. Failures (missing file, IO error, schema error) are swallowed with a `logger.warning`. The module remains import-safe on macOS / Linux. |
| Cockpit double-load | `CockpitMainWindow._load_threshold_overrides` stays — package import is a one-shot, but cockpit construction must re-read from disk to pick up edits made between cockpit sessions. The setter contract is idempotent so double-load is safe. |
| Cockpit exception net | `_load_threshold_overrides` catches `(ConfigSchemaError, OSError, UnicodeDecodeError)`. A future tightening to `BaseException` is rejected — `KeyboardInterrupt` must propagate. |

## Test Contract

### Packaging test gating

```python
# tests/test_packaging_imports.py
def test_pyinstaller_spec_lists_new_modules_and_style_data():
    if not SPEC_PATH.exists():
        pytest.skip(
            "PyInstaller spec is a build artifact; run "
            "tools/build_windows_folder.ps1 to regenerate before asserting."
        )
    text = SPEC_PATH.read_text(encoding="utf-8")
    # ... existing assertions unchanged ...
```

### CLI auto-load

```python
# tests/test_acquisition_settings_overrides.py — new test
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
        # Defaults restored because the corrupt file is swallowed.
        assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
    finally:
        thresholds.reset_defaults()
```

### Cockpit exception net

```python
# tests/acquisition_ui/test_cockpit_polish_integration.py — new test
def test_cockpit_startup_survives_unreadable_settings_file(
    qapp, monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings_dir = tmp_path / ".acquisition-cockpit"
    settings_dir.mkdir()
    # Put a directory where settings.json should be — Path.read_text raises
    # IsADirectoryError on macOS / Linux (subclass of OSError).
    (settings_dir / "settings.json").mkdir()

    thresholds.reset_defaults()
    window = CockpitMainWindow()
    try:
        assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0  # defaults retained
    finally:
        window.close()
        thresholds.reset_defaults()
```

## Acceptance Gates

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_packaging_imports.py \
  tests/test_acquisition_settings_overrides.py -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/acquisition_ui/test_cockpit_polish_integration.py -v
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui tests/acquisition_ui -v
```

All four invocations green.

Fresh-clone validation (manual):

```bash
git clean -fdx build/
PYTHONPATH=. .venv/bin/python -m pytest tests/test_packaging_imports.py -v
# Expected: test_pyinstaller_spec_lists_new_modules_and_style_data is SKIPPED.
# Other two packaging tests pass.
```
