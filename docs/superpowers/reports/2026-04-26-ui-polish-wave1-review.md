## Deletion completeness
Signal RPM chain is deleted: `grep -nE 'compute_rpm_order_result|(^|[^[:alnum:]_])compute_order_spectrum([^[:alnum:]_]|$)|class[[:space:]]+OrderRpmResult|rpm_res' mf4_analyzer/signal/order.py` returned 0 lines; `mf4_analyzer/signal/order.py:23-30` shows `OrderAnalysisParams` fields without `rpm_res`.
Batch RPM method is deleted: `grep -nE "order_rpm|_compute_order_rpm_dataframe" mf4_analyzer/batch.py mf4_analyzer/ui/drawers/batch_sheet.py` returned 0 lines; `mf4_analyzer/batch.py:89` is `{'fft', 'order_time', 'order_track'}`.
UI RPM symbols are deleted: `grep -nE 'btn_or|spin_rpm_res|order_rpm_requested|do_order_rpm|_render_order_rpm' mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/inspector.py mf4_analyzer/ui/main_window.py tests/ui/test_inspector.py` returned 0 lines.
RPM branches/options are absent: `grep -nE "(_kind|kind)[[:space:]]*==[[:space:]]*['\"]rpm['\"]|order_rpm|spin_rpm_res" mf4_analyzer/ui/main_window.py mf4_analyzer/ui/drawers/batch_sheet.py` returned 0 lines.
Wave 1 commits targeted these removals: `git show --stat --oneline` reports `20a8ccf` removing `OrderRpmResult / compute_rpm_order_result / compute_order_spectrum / rpm_res`, `cfb301b` dropping `order_rpm`, `10d3f1a` dropping inspector RPM widgets/signals, `1f2f550` dropping main-window RPM paths, and `3c21437` dropping batch-sheet RPM UI.

## Retained API integrity
Signal APIs/classes remain: `mf4_analyzer/signal/order.py:34` `OrderTimeResult`, `:43` `OrderTrackResult`, `:50` `OrderAnalyzer`, `:92` `_order_amplitudes`, `:118` `_order_amplitudes_batch`, `:215` `compute_time_order_result`, `:281` `extract_order_track_result`, `:339` `compute_order_spectrum_time_based`.
Batch retained routes remain: `mf4_analyzer/batch.py:89` `SUPPORTED_METHODS = {'fft', 'order_time', 'order_track'}`, `:260-261` time dataframe calls `compute_time_order_result`, `:276-277` track dataframe calls `extract_order_track_result`.
UI retained routes remain: `mf4_analyzer/ui/main_window.py:119` worker time branch, `:124` worker track branch, `:1309` dispatches `'time'`, `:1336` dispatches `'track'`, `:1421` renders time, `:1423` renders track.
Batch-sheet retained choices remain: `mf4_analyzer/ui/drawers/batch_sheet.py:108` adds `["fft", "order_time", "order_track"]`.
Envelope helper remains: `mf4_analyzer/ui/canvases.py:192` defines `build_envelope`.

## Subtle breakage scan
`OrderContextual.__init__` has no dangling removed-widget runtime reference: it builds `btn_ot` at `mf4_analyzer/ui/inspector_sections.py:1060-1063`, `btn_ok` at `:1072-1074`, `btn_cancel` at `:1093-1097`, and connects only `btn_ot/btn_ok` at `:1101-1102`; grep for `btn_or|spin_rpm_res|order_rpm_requested` returned 0 lines.
`_enforce_label_widths` has no deleted-name dependency: `mf4_analyzer/ui/inspector_sections.py:477-519` walks `QFormLayout` rows via `findChildren`, `itemAt`, and field widgets rather than named RPM controls.
Order presets have no `rpm_res`: `mf4_analyzer/ui/inspector_sections.py:1114-1122` collects `rpm_factor/max_order/order_res/time_res/nfft/target_order`, `:1124-1138` applies those keys; `grep -n 'rpm_res' mf4_analyzer/ui/inspector_sections.py mf4_analyzer/ui/drawers/batch_sheet.py` returned 0 lines.
`MainWindow._dispatch_order_worker` keeps time/track only: `mf4_analyzer/ui/main_window.py:1358-1399` constructs and starts `OrderWorker`; callers pass `'time'` at `:1309` and `'track'` at `:1336`; RPM branch grep returned 0 lines.
`tests/ui/test_inspector.py` has no rpm-only parametrized no-op risk: `grep -nE 'parametrize|rpm|order_rpm' tests/ui/test_inspector.py` returned 0 lines, and `tests/ui/test_inspector.py:68-83` directly tests only order params plus time/track emits.

## Cross-spec note
The older canvas-perf spec still lists `compute_order_spectrum` as stable public API: `docs/superpowers/specs/2026-04-26-order-canvas-perf-design.md:446-448`.
The Wave 1 spec supersedes that contract: `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md:14` is `Supersedes prior spec`, `:18-21` deletes `compute_rpm_order_result`, `compute_order_spectrum`, `OrderRpmResult`, and `rpm_res`, while `:28-30` retains only `compute_order_spectrum_time_based`, `compute_time_order_result`, and `extract_order_track_result`.

## Verdict
approved — proceed to Wave 2
