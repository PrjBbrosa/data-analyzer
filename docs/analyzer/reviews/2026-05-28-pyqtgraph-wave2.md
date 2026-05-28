OVERALL: NEEDS-REWORK

## Summary

- Current verdict: NEEDS-REWORK. W2 is broadly implemented and the bounded suite is green (`180 passed, 15 warnings`), but two review blockers remain before W3/T7 can switch production rendering.
- T5 has the new `TimeDomainCanvasPG`, exact four-signal surface, PyQt5 binding pin before `import pyqtgraph`, `PgAxisHandle`, curve cache, and screenshot grab. Blocker: `_refresh_visible_data()` still calls `pdi.setData(env_t, env_s)` in the pan/refresh hot path at `mf4_analyzer/ui/pg_canvases.py:866-875`, despite the bind-only requirement.
- T6 implements subplot, overlay, cursor HTML, wheel dispatch, xlim preservation, and three 1200x800 PNG screenshots. Blocker: the xlim sync path listens only to the primary ViewBox (`mf4_analyzer/ui/pg_canvases.py:374-379`, `mf4_analyzer/ui/pg_canvases.py:683-693`), and the test checks only primary -> `axes_list[2]` (`tests/ui/test_pg_timedomain_canvas.py:1108-1137`), not all 5 axes or non-primary-origin changes.
- Inside-label threshold has one standard-width and one narrow-width test (`tests/ui/test_pg_timedomain_canvas.py:1148-1170`), but no near-threshold or larger-than-standard evidence. The T5 skeleton PNG is 640x360, not the reported 800x480.
- Scope guard is not clean: mandated `git status --short -- ...` shows `dialogs.py` modified alongside `canvases.py` and `main_window.py`; `chart_stack.py` is clean and the FFT grep is empty.

## T5 review

Verdict: NEEDS-REWORK.

- `TimeDomainCanvasPG` exists as a `QWidget`-hosted pyqtgraph canvas and explicitly stays out of `ChartStack` until T7: `mf4_analyzer/ui/pg_canvases.py:6-11`, `mf4_analyzer/ui/pg_canvases.py:175-185`.
- The four design §3.1 signals are present with the exact names: `cursor_info`, `dual_cursor_info`, `span_selected`, `overlay_channel_selected` at `mf4_analyzer/ui/pg_canvases.py:181-185`. The matching contract test pins signatures at `tests/ui/test_pg_timedomain_canvas.py:565-586`.
- Risk Register R7 is satisfied: `PYQTGRAPH_QT_LIB` is set before `import pyqtgraph` at `mf4_analyzer/ui/pg_canvases.py:55-66`, and pyqtgraph imports as `0.14.0` in the repo venv.
- The compatibility surface is present: `axes_list`, `_channel_lines`, raw `channel_data`, `_channel_data_id`, monotonicity cache, primary axis handle, cursor state, and refresh timer are initialized at `mf4_analyzer/ui/pg_canvases.py:206-259`; tests assert these post-plot surfaces at `tests/ui/test_pg_timedomain_canvas.py:630-687`.
- `PgAxisHandle` is filled, not a stub: limits delegate through `ViewBox.setXRange(..., padding=0)` / `setYRange` at `mf4_analyzer/ui/_axis_handle.py:347-373`; labels/title/grid/lines/mappables/redraw are implemented at `mf4_analyzer/ui/_axis_handle.py:404-514`; tests exercise the real `PlotItem`/`ViewBox` path at `tests/ui/test_pg_timedomain_canvas.py:953-1047`.
- The curve-layer cache exists and is keyed by `(channel, bucketed_lo, bucketed_hi, bucketed_pixel_width)` via `_quantize_range_key()` at `mf4_analyzer/ui/pg_canvases.py:145-167`; the cache and `_last_range_key` are initialized at `mf4_analyzer/ui/pg_canvases.py:247-259` and populated in `_refresh_visible_data()` at `mf4_analyzer/ui/pg_canvases.py:807-865`. Tests cover population, distinct keys, same-xlim no-inflation, and real `positions_envelope` consumption at `tests/ui/test_pg_timedomain_canvas.py:788-912`.
- Blocker: the required grep for literal `PlotDataItem.setData(` returns no output, but the actual hot path still calls the bound method `pdi.setData(env_t, env_s)` after every cache rebuild at `mf4_analyzer/ui/pg_canvases.py:866-875`. That contradicts the module contract that `PlotDataItem.setData` is fallback/bind-only at `mf4_analyzer/ui/pg_canvases.py:23-25` and `mf4_analyzer/ui/pg_canvases.py:441-447`.
- `grab_pixmap()` has the expected non-null fallback path at `mf4_analyzer/ui/pg_canvases.py:1404-1435`, and the skeleton screenshot test writes `/tmp/pg_skeleton_single_channel.png` at `tests/ui/test_pg_timedomain_canvas.py:922-944`. However, live dimensions are 640x360, not the agent-reported 800x480, so the screenshot evidence is NEEDS-INFO even though the test's geometry gate passes.

## T6 review

Verdict: NEEDS-REWORK, because the implemented features are present but xlim parity is under-proven and not guaranteed for non-primary-origin changes.

- Subplot mode builds one `PlotItem`/`PgAxisHandle` per visible channel at `mf4_analyzer/ui/pg_canvases.py:331-355`; the test asserts 5 axes and primary -> secondary propagation at `tests/ui/test_pg_timedomain_canvas.py:1092-1137`.
- Overlay mode uses one shared plot and per-channel `PlotDataItem`s at `mf4_analyzer/ui/pg_canvases.py:356-365`; selection, emphasis, deselect emission, and selected-channel Y-drag are implemented at `mf4_analyzer/ui/pg_canvases.py:948-1123` and covered at `tests/ui/test_pg_timedomain_canvas.py:1180-1279`.
- Cursor HTML parity imports `_format_dual_html` and `_interp_cursor_value` from the matplotlib module at `mf4_analyzer/ui/pg_canvases.py:73-79`. Single-cursor HTML mirrors `TimeDomainCanvas._update_single()` at `mf4_analyzer/ui/canvases.py:1428-1448` and `mf4_analyzer/ui/pg_canvases.py:1185-1206`; dual-cursor HTML reuses `_format_dual_html` at `mf4_analyzer/ui/pg_canvases.py:1208-1254` and matches the matplotlib path at `mf4_analyzer/ui/canvases.py:1450-1499`. Tests compare byte-for-byte at `tests/ui/test_pg_timedomain_canvas.py:1293-1395`.
- Ctrl/Shift/plain wheel handling is routed through `_ModifierWheelViewBox.wheelEvent()` at `mf4_analyzer/ui/pg_canvases.py:96-132` and `_handle_wheel_dispatch()` at `mf4_analyzer/ui/pg_canvases.py:1129-1178`; the reference matplotlib behavior is at `mf4_analyzer/ui/canvases.py:1501-1515`. Tests cover Ctrl X zoom, Shift Y zoom, and plain Y pan at `tests/ui/test_pg_timedomain_canvas.py:1398-1502`.
- Mode-switch xlim preservation is implemented by capturing before `clear()` and restoring/flushing after rebuild at `mf4_analyzer/ui/pg_canvases.py:395-438`; the test preserves `(0.30, 0.45)` through subplot -> overlay at `tests/ui/test_pg_timedomain_canvas.py:1511-1536`.
- Three T6 visual screenshots are covered by geometry tests at `tests/ui/test_pg_timedomain_canvas.py:1563-1639`. Live files exist and match 1200x800: `/tmp/pg_parity_subplot_5ch.png`, `/tmp/pg_parity_overlay_5ch.png`, and `/tmp/pg_parity_dual_cursor.png`.
- The T6 test count is 55 for `tests/ui/test_pg_timedomain_canvas.py`, meeting the requested T4+T5+T6 >=55 gate.
- Verification command:

```text
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_canvases.py tests/ui/test_xlim_refresh.py tests/ui/test_timedomain_canvas_contract.py tests/ui/test_main_window_smoke.py tests/ui/test_dialogs.py tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py tests/ui/test_axis_interaction.py -q
...
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
180 passed, 15 warnings in 15.54s
```

## Architectural decisions audit

1. DROP `setXLink` — Verdict: NEEDS-REWORK.

- Positive: no live `setXLink` call is present; grep only finds explanatory comments at `mf4_analyzer/ui/pg_canvases.py:340-347` and `mf4_analyzer/ui/pg_canvases.py:718-722`.
- Positive for primary-origin changes: the primary `sigXRangeChanged` handler calls `_propagate_xlim_to_siblings()` before scheduling refresh at `mf4_analyzer/ui/pg_canvases.py:714-730`, and the propagation loop pushes the exact `(lo, hi)` to every non-primary handle with `padding=0` and `blockSignals(True)` at `mf4_analyzer/ui/pg_canvases.py:732-763`.
- Gap: only the first axis is connected as `_primary_xaxis_ax` at `mf4_analyzer/ui/pg_canvases.py:374-379`, and `_connect_xrange_listener()` attaches only that handle's ViewBox at `mf4_analyzer/ui/pg_canvases.py:683-693`. A range change that originates on `axes_list[1]`/`[2]`/`[3]`/`[4]` is not wired to propagate back to the primary or the other siblings.
- Gap in the pinning test: `test_subplot_builds_five_plot_items_sharing_x_axis` sets `primary.set_xlim(...)` twice and checks only `secondary = canvas.axes_list[2]` at `tests/ui/test_pg_timedomain_canvas.py:1108-1137`. It does not assert all five axes, and it does not simulate or directly set a non-primary origin. This misses the most likely drift case after dropping `setXLink`.

2. Inside-label rule — Verdict: NEEDS-INFO.

- Matplotlib's production rule is rendered-bbox based: label bbox height, figure-left clipping, tick-label overlap, and label-label overlap are checked at `mf4_analyzer/ui/canvases.py:937-965`.
- The pyqtgraph path uses a viewport-width threshold: it reads `_glw.viewport().width()` at `mf4_analyzer/ui/pg_canvases.py:1302-1306`, then returns `widget_w < 320` at `mf4_analyzer/ui/pg_canvases.py:1307-1323`.
- Standard 1200-px behavior is covered: the test resizes to 1200x800 and expects outside labels (`False`) at `tests/ui/test_pg_timedomain_canvas.py:1148-1156` and `tests/ui/test_pg_timedomain_canvas.py:1163-1168`.
- Non-standard smaller width is covered: the same test resizes to 220x800 and expects inside labels (`True`) at `tests/ui/test_pg_timedomain_canvas.py:1157-1170`.
- Remaining uncertainty: there is no near-boundary test around 319/320/321 px and no larger-than-standard case (for example 1600 px). The current evidence shows the threshold behaves at 1200 and 220, but it does not fully prove graceful degradation across smaller/larger layouts.

## Scope-creep audit

Verdict: NEEDS-INFO / NEEDS-REWORK until the unexpected `dialogs.py` modification is attributed or removed from W2.

- Required scope was W2-only: `pg_canvases.py`, `_axis_handle.py` `PgAxisHandle`, and appended parity tests; production switch in `ChartStack` is T7 and out of scope. `pg_canvases.py` itself says it is intentionally not wired into `ChartStack` yet at `mf4_analyzer/ui/pg_canvases.py:6-11`.
- Mandated status output for protected UI files:

```text
 M mf4_analyzer/ui/canvases.py
 M mf4_analyzer/ui/dialogs.py
 M mf4_analyzer/ui/main_window.py
```

- `chart_stack.py` is absent from that output, so the T7 production switch appears untouched. `canvases.py` and `main_window.py` contain the known pre-W2 cursor-reset seam at `mf4_analyzer/ui/canvases.py:1310-1331` and `mf4_analyzer/ui/main_window.py:678-700`.
- `dialogs.py` is modified, which conflicts with the explicit W2 protected-file expectation. The current diff changes `ChartOptionsDialog` to accept `axis_or_handle` and call `make_handle()` at `mf4_analyzer/ui/dialogs.py:293-315`, then routes axis reads/writes through `self.handle` at `mf4_analyzer/ui/dialogs.py:555-702`. That may be older AxisHandle work, but it is not clean under the W2 audit as requested.
- FFT shield passed: `git diff -- mf4_analyzer | rg -n '^[+-].*(FFTTimeWorker|SpectrogramResult|_fft_time_cache_key|fft_time)'` returned no output.
- B1-B7 untouched: NOT CONFIRMED from the current dirty worktree alone. The mandatory FFT grep is empty, but `git status --short` shows unrelated/untracked migration and signal files outside W2. A branch-base diff is needed to attribute those safely.

## Defensive-gate audit

| Gate | Verdict | Evidence |
| --- | --- | --- |
| codex-runtime-verification-entrypoints | PASS | Used repo venv with `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen`; bounded suite ended `180 passed, 15 warnings in 15.54s`. |
| codex-phantom-api-surface-guards | PASS | Tests state no `MagicMock` for `cutils` at `tests/ui/test_pg_timedomain_canvas.py:15-21`; real C path spy preserves `asammdf.blocks.cutils.positions` at `tests/ui/test_pg_timedomain_canvas.py:254-280`; forced fallback uses `_HAS_POSITIONS_C`, not mocked cutils, at `tests/ui/test_pg_timedomain_canvas.py:282-305`. |
| codex-plan-spec-literal-evidence | PASS | Cursor parity imports shared helpers at `mf4_analyzer/ui/pg_canvases.py:73-79`; tests compare single/dual HTML byte-for-byte at `tests/ui/test_pg_timedomain_canvas.py:1293-1395`. |
| codex-confirmed-issue-list-means-remaining-scope | PASS | `plot_channels_preserving_xlim()` explicitly keeps MainWindow tangent-only guard out of W2 at `mf4_analyzer/ui/pg_canvases.py:395-405`; `ChartStack` status is clean. |
| codex-analyzer-doc-routing | PASS | This review artifact is under `docs/analyzer/reviews/2026-05-28-pyqtgraph-wave2.md`, matching analyzer review routing. |
| codex-fft-time-review-shields | PASS | Required FFT grep returned no output, so no W2 diff mentions `FFTTimeWorker`, `SpectrogramResult`, `_fft_time_cache_key`, or `fft_time`. |
| codex-visual-parity-rendered-screenshot | NEEDS-INFO | T6 screenshots exist and are 1200x800 at `tests/ui/test_pg_timedomain_canvas.py:1573-1639`; T5 skeleton screenshot exists but is 640x360, not the reported 800x480 (`tests/ui/test_pg_timedomain_canvas.py:922-944`). |
| pyqt-ui flush-after-axis-mutation-not-before | PASS | Xlim restore calls `set_xlim()` before `_flush_pending_refresh()` at `mf4_analyzer/ui/pg_canvases.py:423-438`; cursor reset mutates state before `draw_idle()` at `mf4_analyzer/ui/pg_canvases.py:564-575`. |
| pyqt-ui cache-invalidation-event-conditional | PASS | `_last_range_key` skips same-range refresh work at `mf4_analyzer/ui/pg_canvases.py:828-834`; replay test pins no cache growth at `tests/ui/test_pg_timedomain_canvas.py:852-873`. |
| pyqt-ui tightbbox-survives-offscreen-qt | PASS | `grab_pixmap()` falls back from widget grab to GLW grab to a 1x1 transparent pixmap at `mf4_analyzer/ui/pg_canvases.py:1404-1435`; offscreen test asserts non-null geometry at `tests/ui/test_pg_timedomain_canvas.py:922-944`. |
| signal-processing branch-reached-is-not-behavior-correct | PASS | T6 test block requires two-frame or byte-equality assertions at `tests/ui/test_pg_timedomain_canvas.py:1058-1063`; examples include overlay emphasis at `tests/ui/test_pg_timedomain_canvas.py:1180-1218` and wheel behavior at `tests/ui/test_pg_timedomain_canvas.py:1403-1502`. |
| signal-processing envelope-cache-bucket-width-quantization | PASS | `_quantize_range_key()` uses `span / pixel_width` and returns integer bucketed lo/hi plus pixel width at `mf4_analyzer/ui/pg_canvases.py:145-167`; distinct/same xlim tests cover key behavior at `tests/ui/test_pg_timedomain_canvas.py:820-873`. |

## Suggested deltas

1. (required) Remove `pdi.setData(env_t, env_s)` from `_refresh_visible_data()` or move all pyqtgraph data mutation back to the initial bind path; add a regression that fails on any bound `setData` call during `set_xlim` / `_flush_pending_refresh`.
2. (required) Harden xlim sync after dropping `setXLink`: either connect every subplot ViewBox and propagate origin -> all siblings, or explicitly prevent non-primary X-range mutation. Add tests that assert all five subplots match and that a non-primary-origin change cannot drift.
3. (required) Resolve the `dialogs.py` scope violation: either prove it is pre-W2 baseline in the report context or keep it out of the W2 patch set. Current status does not satisfy the protected-file check.
4. (required) Strengthen inside-label evidence with threshold-boundary and larger-than-standard cases, ideally comparing the pyqtgraph threshold decision against matplotlib bbox decisions for the same channel set at 1200 px and at least one non-standard width on each side.
5. (optional) Make screenshot dimensions deterministic: resize the T5 skeleton canvas to the reported 800x480 or update the agent-reported number/test expectation so the artifact metadata and report agree.

## Next-wave readiness

BLOCKED for W3/T7 production switch.

Reason: W2 passes the bounded runtime suite, but production switching should wait until the pyqtgraph refresh path no longer mutates `PlotDataItem` via `setData` during pan/refresh, subplot xlim sync is proven across all five axes and non-primary-origin changes, and the protected-file scope issue around `dialogs.py` is resolved.
