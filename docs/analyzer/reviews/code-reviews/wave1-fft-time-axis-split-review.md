## Wave 1 Review — FFTTimeContextual axis-group split
**Status**: PASS

### Acceptance criteria
1. ✅ PASS — `FFTTimeContextual` builds the split axis groups as `QGroupBox("彩图")` with the Z row only and `QGroupBox("频谱")` with X/Y rows, then adds `彩图` before `频谱`; `OrderContextual` still uses the single `_make_axis_settings_group` / `"坐标轴设置"` path (`mf4_analyzer/ui/inspector_sections.py:827`, `mf4_analyzer/ui/inspector_sections.py:859`, `mf4_analyzer/ui/inspector_sections.py:865`, `mf4_analyzer/ui/inspector_sections.py:889`, `mf4_analyzer/ui/inspector_sections.py:913`, `mf4_analyzer/ui/inspector_sections.py:1574`, `mf4_analyzer/ui/inspector_sections.py:2076`).
2. ✅ PASS — The backward-compat aliases are assigned as identical objects: `chk_freq_auto = chk_x_auto`, `spin_freq_min = spin_x_min`, and `spin_freq_max = spin_x_max` (`mf4_analyzer/ui/inspector_sections.py:918`).
3. ✅ PASS — Initial Z/X/Y values are seeded with signals blocked before wiring, `combo_amp_unit` and all `chk_*_auto` signals are connected after seeding, and `FFTTimeContextual` seeds enabled state at init end (`mf4_analyzer/ui/inspector_sections.py:845`, `mf4_analyzer/ui/inspector_sections.py:850`, `mf4_analyzer/ui/inspector_sections.py:854`, `mf4_analyzer/ui/inspector_sections.py:923`, `mf4_analyzer/ui/inspector_sections.py:2162`, `mf4_analyzer/ui/inspector_sections.py:2165`, `mf4_analyzer/ui/inspector_sections.py:2182`).
4. ✅ PASS — `_enforce_label_widths(unify_columns=True)` only scans `QFormLayout` instances, while the split groups use `QVBoxLayout` containers and `_build_axis_row` uses `QHBoxLayout`, so the new axis rows do not join form label-column unification (`mf4_analyzer/ui/inspector_sections.py:522`, `mf4_analyzer/ui/inspector_sections.py:610`, `mf4_analyzer/ui/inspector_sections.py:828`, `mf4_analyzer/ui/inspector_sections.py:866`, `mf4_analyzer/ui/inspector_sections.py:2150`).
5. ✅ PASS — Diff scope is limited to `mf4_analyzer/ui/inspector_sections.py` and `tests/ui/test_inspector.py`; `_build_axis_row` still caps both spin boxes at 72 px, with no `style.qss` or `icons.py` edits in the reviewed diff (`mf4_analyzer/ui/inspector_sections.py:619`).
6. ✅ PASS — The requested focused run passed `81 passed`, the full suite passed with the current count `412 passed` (the prompt said 411), and the source adds `彩图` before `频谱`; the existing offscreen screenshot `.pytest-tmp/inspector-fft-time-after-split.png` shows that order (`mf4_analyzer/ui/inspector_sections.py:2076`).

### Defect findings
No defects found.

### Test coverage
- Before count: not independently determinable from this review; the prompt stated 411 tests.
- After/current count: `tests/ui/test_inspector.py` focused run passed `81 passed, 48 warnings`; full suite passed `412 passed, 48 warnings`.
- The rewritten `test_fft_time_contextual_has_axis_settings_group` covers both groups and verifies Z-only ownership for `彩图`, X/Y-only ownership for `频谱`, and all three backward-compat aliases (`tests/ui/test_inspector.py:1550`, `tests/ui/test_inspector.py:1571`, `tests/ui/test_inspector.py:1586`, `tests/ui/test_inspector.py:1593`).
- Minor residual coverage note: the test uses a title set plus `next(...)`, so it covers presence/ownership but would not catch duplicate `彩图` or duplicate `频谱` groups by itself (`tests/ui/test_inspector.py:1555`, `tests/ui/test_inspector.py:1564`).

### Summary
Wave 1 passes the requested review. The implementation keeps `OrderContextual` on the original single axis group, splits `FFTTimeContextual` into `彩图` and `频谱` with the expected child ownership, preserves legacy frequency aliases, and keeps the split rows outside `QFormLayout` label unification. No blocking defects were found; the only note is that the current suite contains 412 passing tests rather than the 411 count stated in the prompt.
