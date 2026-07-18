# Windows Packaged Text Clarity — Global Optimization Plan

**Status:** Approved for investigation and controlled rollout; no rendering
configuration has changed as part of writing this plan.

**Goal:** Make TraceLab's Chinese, Latin, and numeric text consistently crisp
in the shipped Windows application, while preserving each user's Windows
display scale, existing layout behavior, chart readability, and macOS output.

**Non-goals:** This is not an OS ClearType-tuning guide, a forced application
scale-factor change, a Qt major-version upgrade, or a blanket size increase.
Those would either change user-owned Windows settings, risk layout regressions,
or hide the real source of softness.

## What is known now

| Surface | Current path | Evidence and implication |
|---|---|---|
| Standard controls | `mf4_analyzer/ui_kit/style.qss` requests `Microsoft YaHei` first at `12px`; many local overrides use `9px`–`11px`. | A 9px CJK bold label has little pixel budget at Windows 100%/125%, so it is a primary candidate. |
| Reported time/frequency slice toggle | Ordinary `QPushButton` in `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`; QSS applies `9px`, weight 700. | It is not a GPU rendering surface; a GPU-only change cannot fix it. |
| Charts | `mf4_analyzer/ui/pg_canvas/fonts.py` resolves a separate pyqtgraph font stack and chart objects also own explicit fonts. | Widget and chart text must be checked independently, even if they share a family resolver. |
| Time-domain GPU viewport | A separate OpenGL path. | It stays isolated from the widget-font rollout and gets its own regression check. |
| DPI startup | `mf4_analyzer/app.py::_configure_high_dpi()` opts into high DPI and sets `PassThrough` before `QApplication`. | Fractional-scale behavior is global. It is an A/B candidate, not a presumed defect. |
| Windows package | `tools/build_windows_folder.ps1` and `tools/build_windows_folder_lite.ps1` create PyInstaller `--onedir` packages from unpinned `PyQt5` and `pyqtgraph>=0.13.3`. | Both package variants must contain the same approved rendering configuration and record the actual Qt runtime version. |

The local macOS probe resolved the requested family to `PingFang SC` at DPR 2;
that supports the reported platform difference but is not proof for Windows.
Only screenshots and font/DPI diagnostics from the packaged Windows EXE decide
the rollout.

## Decision rules

1. Keep the Windows display setting authoritative. Never ship `QT_SCALE_FACTOR`,
   `QT_FONT_DPI`, or `QT_SCREEN_SCALE_FACTORS`; Qt documents those as test or
   debugging controls and warns against overriding native display values.
2. Do not choose a DPI rounding policy from theory. `PassThrough`, `Round`, and
   `RoundPreferFloor` will be compared only at the Windows scales where their
   geometry and rasterization differ. A candidate that changes layout scale or
   introduces clipping is rejected even if a single label looks sharper.
3. Prefer one platform-aware font-profile resolver and an audited readable-size
   floor over scattered, surface-specific font guesses. QSS, direct widget
   stylesheets, and pyqtgraph constructors must consume that decision
   deliberately; they cannot all be blindly replaced with a new string.
4. Treat `QFont` hinting as an experiment with recorded effective fonts, not a
   promise. Qt describes hinting preferences as platform-dependent; DirectWrite
   may already use full hinting by default.
5. A macOS/offscreen test proves wiring only. The release gate is a real
   Windows package executed at native Windows display scales.

## Implementation phases

### Phase 1 — Reproducible packaged-Windows baseline

**Files to add/modify**

- Add a narrowly scoped diagnostic helper under `mf4_analyzer/` (final module
  location chosen after locating existing CLI/debug conventions).
- Modify `mf4_analyzer/app.py` only to call that helper under an explicit
  diagnostics flag before normal-window creation; normal launches remain
  silent and unchanged.
- Add focused tests under `tests/` for diagnostic serialization and for
  "does not change normal startup".

**Work**

1. Add a diagnostics mode usable from the packaged EXE, for example an
   environment-controlled JSON snapshot. It must record Qt/PyQt versions,
   platform plugin, high-DPI attributes and policy, relevant `QT_*` values,
   each active screen's DPR/logical DPI/physical DPI, and the effective
   `QFontInfo` for:
   - application default font;
   - a representative QSS `QPushButton` (including the 9px slice-toggle
     profile);
   - the pyqtgraph chart font at each shipped chart size.
2. Build both full and lite Windows packages with their existing PowerShell
   entrypoints. Capture the package command, PyInstaller version, Python
   version, and bundled Qt DLL version beside each probe.
3. On a Windows test machine, capture the current package at 100%, 125%, and
   150% display scale. For every scale record an unscaled native screenshot,
   the diagnostics JSON, Windows version, monitor resolution, and whether the
   app was started from the package rather than source.
4. Cover a fixed comparison scene: toolbar and inspector controls; the
   time/frequency toggle shown in the report; QuickRef/body copy; axis ticks,
   legend and tooltip text; an FFT/Order heatmap; and the time-domain GPU
   viewport. Include Chinese, English, digits, bold, and regular text.

**Exit criteria**

- Baseline evidence distinguishes effective family/size/DPR for widgets and
  charts at every scale.
- The cause can be assigned to one or more of: undersized local styles,
  ineffective Windows family resolution, fractional-DPI behavior, or the
  separate GPU viewport. It must not be described as GPU-only without that
  evidence.

### Phase 2 — Font and readable-size candidate matrix

**Likely files to audit**

- `mf4_analyzer/ui_kit/style.qss`
- `mf4_analyzer/ui/pg_canvas/fonts.py`
- direct local styles in `mf4_analyzer/ui/`, especially
  `pg_canvas/heatmap_canvas.py`, `quickref_panel.py`, and inspector sections
- pyqtgraph axes, legends, and tooltip creation paths

**Work**

1. Inventory every explicit `font-size` below the selected readable floor and
   classify it as user-facing text, decorative/chrome text, or chart text.
   Include QSS, inline Qt stylesheets, and HTML/RichText fragments; do not
   search `style.qss` alone.
2. Prototype font profiles in one resolver, retaining platform fallback:
   Windows candidates must compare `Microsoft YaHei UI` and the existing
   `Microsoft YaHei` request, while macOS remains `PingFang SC` and Linux
   keeps its compatible fallback. Record the actually resolved family rather
   than assuming the requested first family won.
3. In the same matrix, test only conservative readable-size changes for the
   classed user-facing small text. The reported 9px bold slice controls are a
   required candidate; container minimum widths/heights and button text
   elision must be measured with each candidate.
4. Ensure normal Qt widgets and pyqtgraph derive their compatible profile from
   the same policy while retaining any intentionally different chart sizing.
   Do not set a global application font and leave the QSS/chart overrides
   unknowingly competing with it.
5. Use deterministic offscreen tests to assert profile selection, effective
   requested size, no `< 10px` user-facing exception without an explicit
   rationale, and narrow-panel non-overflow. These tests are not the visual
   decision.

**Candidate acceptance rule**

At each native Windows scale, the candidate must be visually at least as clear
as baseline across the fixed scene, have no glyph fallback mismatch, and have
no clipping/overlap/layout-density regression. A perceived improvement on only
one 9px toggle is insufficient for global selection.

### Phase 3 — DPI policy A/B, isolated from font selection

**Files**

- `mf4_analyzer/app.py`
- tests for startup policy selection and no late-application calls
- both Windows build scripts only if a build label or diagnostics switch is
  needed; neither gets a permanent fixed scale environment variable

**Work**

1. After choosing the best font/size profile, build otherwise identical
   Windows packages with the existing `PassThrough`, `Round`, and
   `RoundPreferFloor` policies. Make the policy selectable for test packages
   only and resolve it before constructing `QApplication`.
2. Test 100%, 125%, 150%, and a 175% scale if available, including moving the
   window between monitors with different scales. Compare text sharpness,
   one-pixel seams, chart coordinates, toolbar/inspector geometry, and popup
   positioning.
3. Ship a policy change only when its package evidence is better across the
   matrix and it does not make the application unexpectedly "small" or
   "large". Otherwise retain `PassThrough`; the font profile rollout remains
   valid independently.

### Phase 4 — One global rollout, not a broad style rewrite

**Files expected to change**

- Central platform-aware font-profile module (new or existing appropriate
  module after Phase 1 discovery)
- `mf4_analyzer/app.py`
- `mf4_analyzer/ui_kit/style.qss`
- `mf4_analyzer/ui/pg_canvas/fonts.py`
- only those direct style owners identified by the audited small-text list
- focused widget, pyqtgraph, and startup tests
- `tools/build_windows_folder.ps1` and
  `tools/build_windows_folder_lite.ps1` only if they need an auditable
  version/diagnostic hook; no incidental packaging cleanup

**Work**

1. Implement the single winning Windows profile, keeping macOS and Linux
   selection explicit and backwards compatible.
2. Replace only audited user-facing tiny-text rules. Preserve compact labels
   with their geometry revalidated; do not make every 9–11px decorative token
   larger by default.
3. Keep the GPU time viewport separate. If it remains softer after the widget
   rollout, open a dedicated OpenGL rendering task with its own rasterization
   evidence rather than adding GPU workarounds to global widget configuration.
4. Pin or record the exact PyQt5/Qt runtime used for approved Windows release
   builds so a later dependency resolver update cannot silently invalidate the
   visual baseline. A Qt runtime upgrade, if needed, is a separate controlled
   compatibility task.

### Phase 5 — Release validation and rollback

1. Run the focused tests plus the existing UI suite under offscreen Qt with
   isolated `QSettings`; then run the project smoke tests covering Time, FFT,
   FFT vs Time, and Order views.
2. Rebuild both Windows full and lite packages from clean build environments.
   Execute each package on Windows at the selected native display scales,
   archive screenshots and diagnostics with the build identity, and compare
   them side by side against Phase 1.
3. Perform a macOS on-screen regression pass. Its purpose is to prove that
   platform-specific selection preserved the already-sharp macOS output, not
   to substitute for the Windows gate.
4. Verify all text-bearing controls in the fixed scene, narrow inspector
   panels, dialog/popup menus, chart export, tooltip/legend rendering, and
   cross-monitor transitions.
5. Roll back by reverting the single profile/policy change if a package
   regression is found. Do not ask users to modify system scale or font
   smoothing as the rollback path.

## Required evidence table for the final decision

| Evidence | Source | Required? |
|---|---|---|
| Effective family, pixel/point size, hinting preference | Packaged-EXE diagnostics JSON | Yes |
| DPR/logical DPI/high-DPI policy and `QT_*` environment | Packaged-EXE diagnostics JSON | Yes |
| Native screenshots at every selected Windows scale | Windows physical display, no image-editor rescale | Yes |
| Full and lite package provenance | Build logs + package manifest | Yes |
| Widget/chart layout and startup tests | CI/local offscreen run | Yes |
| macOS rendering pass | Real macOS application | Yes |

## External technical basis

- Qt, [High DPI](https://doc.qt.io/qt-6.8/highdpi.html): native Windows display
  scale is authoritative; fractional scaling and scale-factor policy need
  deliberate testing.
- Qt, [QGuiApplication high-DPI policy](https://doc.qt.io/qt-6/qguiapplication.html):
  the policy must be selected before app creation and pass-through scaling can
  expose Windows painting artifacts.
- Qt, [QFont hinting preferences](https://doc.qt.io/qt-6.5/qfont.html): hinting
  is a platform-dependent preference; Windows DirectWrite behavior must be
  measured rather than assumed.

## Separate change completed in this task

The spectrum preset label was renamed from `自定义+` to `自定义`, while retaining
slot 4's save/load semantics and QSettings key. Focused inspector tests and a
288px-wide offscreen widget capture verified the four labels remain visible.
That label edit is not evidence for any Windows font-profile decision.
