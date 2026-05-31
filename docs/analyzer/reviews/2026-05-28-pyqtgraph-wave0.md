OVERALL: NEEDS-REWORK

## Summary
- NEEDS-REWORK: W0's source diff is narrow, and the required focused tests pass, but the perf test is not actually opt-in: it is only marked with an unregistered `slow` marker (`tests/perf/test_timedomain_pan_perf.py:18-20`, `:46`), and running the file without `-m slow` still executes it (`1 passed, 1 warning in 9.49s` stdout below).
- PASS: `requirements.txt` has exactly the expected `pyqtgraph>=0.13.3` addition at line 7 and no other dependency hunk (`requirements.txt:1-14`; `git diff -- requirements.txt` stdout below).
- PASS: T2 added `TimeDomainCanvas.reset_cursor_state()` with mutate-then-redraw ordering and updated only `MainWindow._reset_cursors` (`mf4_analyzer/ui/canvases.py:1313-1333`; `mf4_analyzer/ui/main_window.py:680-700`; `git diff --unified=0` stdout below).
- NEEDS-INFO: the prompt says the agent reported 4 perf runs in JSON (`/tmp/wave-0-rescue-prompt.md:54-59`), but the checked-in results report contains three `TIMEDOMAIN_PAN_PERF` lines (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:104-110`).

## T1 review (perf baseline + dependency gate)

### Findings

- PASS: Dependency change is exactly the planned one-line requirement. Evidence:

```text
$ nl -ba requirements.txt | sed -n '1,30p'
     1	numpy
     2	pandas
     3	PyQt5
     4	matplotlib
     5	scipy>=1.10
     6	asammdf
     7	pyqtgraph>=0.13.3
     8	openpyxl
     9	pytest>=7.0
    10	pytest-qt>=4.2
    11	
    12	# Stage 8 - Vector/XCP backend (Windows-only)
    13	python-can[vector]>=4.3.0; sys_platform == "win32"
    14	pyxcp>=0.22.0; sys_platform == "win32"

$ git diff -- requirements.txt
@@ -4,6 +4,7 @@ PyQt5
 matplotlib
 scipy>=1.10
 asammdf
+pyqtgraph>=0.13.3
 openpyxl
 pytest>=7.0
 pytest-qt>=4.2
```

- PASS: The perf fixture exercises the current matplotlib `TimeDomainCanvas`, not a pyqtgraph mock: it imports `TimeDomainCanvas` from `mf4_analyzer.ui.canvases` (`tests/perf/test_timedomain_pan_perf.py:117-123`), builds 5 channels x 100,000 samples (`tests/perf/test_timedomain_pan_perf.py:125-131`), and times `primary.set_xlim(...)` followed by `cv._flush_pending_refresh()` in both warmup and timed loops (`tests/perf/test_timedomain_pan_perf.py:151-164`). Fresh phantom-API grep found no pyqtgraph/asammdf MagicMock usage in the T1/T2 artifacts:

```text
$ rg -n "MagicMock|mock|pyqtgraph|asammdf\.blocks\.cutils|positions\(" tests/perf/test_timedomain_pan_perf.py tests/ui/test_timedomain_canvas_contract.py docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md
tests/perf/test_timedomain_pan_perf.py:37:# We use importlib.util.find_spec rather than MagicMocking PyQt5; this honors
docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:43:print("pyqtgraph", bool(importlib.util.find_spec("pyqtgraph")))
docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:44:print("positions", callable(getattr(cutils, "positions", None)))
docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:51:pyqtgraph False
docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:52:positions True
```

- NEEDS-REWORK: The perf test is marked `slow`, but it is not excluded from default pytest execution. The file claims the slow marker keeps the default suite from running it (`tests/perf/test_timedomain_pan_perf.py:18-20`) and sets only `pytestmark = pytest.mark.slow` (`tests/perf/test_timedomain_pan_perf.py:46`). There is no pytest config file registering or excluding `slow`:

```text
$ rg --files | rg "(^pytest\.ini$|pyproject\.toml$|setup\.cfg$|tox\.ini$)"
# no output

$ TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py -q
.                                                                        [100%]
=============================== warnings summary ===============================
tests/perf/test_timedomain_pan_perf.py:46
  /Users/donghang/Downloads/data analyzer/tests/perf/test_timedomain_pan_perf.py:46: PytestUnknownMarkWarning: Unknown pytest.mark.slow - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    pytestmark = pytest.mark.slow

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1 passed, 1 warning in 9.49s
```

- NEEDS-INFO: The baseline numbers in the report are live-looking and stable across the three pasted runs (`p50_ms=10.576/10.677/10.779`, `p95_ms=10.779/10.816/10.920`; `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:104-110`), but the prompt explicitly asks to check a claimed 4-run JSON (`/tmp/wave-0-rescue-prompt.md:54-59`). I found only three run lines in the report, so the fourth-run claim remains unconfirmed.

- PASS: Dependency probe uses real import surfaces and matches the live venv without installing pyqtgraph. The results report copies `pyqtgraph False` and `positions True` (`docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:39-53`), and the fresh replay produced the same stdout:

```text
$ .venv/bin/python - <<'PY'
import importlib.util
from asammdf.blocks import cutils
print("pyqtgraph", bool(importlib.util.find_spec("pyqtgraph")))
print("positions", callable(getattr(cutils, "positions", None)))
PY
pyqtgraph False
positions True
```

- PASS: T1's extra `tests/perf/__init__.py` is reasonable scaffolding: it is an empty package marker, not behavior (`wc -c tests/perf/__init__.py` returned `0 tests/perf/__init__.py`). W0 status also matches the prompt's scoped file set plus the explicitly out-of-scope pre-existing docs (`/tmp/wave-0-rescue-prompt.md:12-30`):

```text
$ git status --short
 M docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md
 M docs/superpowers/specs/2026-05-28-review-followup-fixes.md
 M mf4_analyzer/ui/canvases.py
 M mf4_analyzer/ui/main_window.py
 M requirements.txt
?? docs/lessons-learned/orchestrator/decompositions/2026-05-28-pyqtgraph-timedomain-migration.md
?? docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md
?? docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md
?? tests/perf/
?? tests/ui/test_timedomain_canvas_contract.py
```

### Required verification stdout

```text
$ TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_xlim_refresh.py tests/ui/test_canvases.py tests/ui/test_axis_interaction.py -q
tests/ui/test_canvases.py::test_order_heatmap_has_borderless_main_axes_and_no_cbar_x_ticks
  /Users/donghang/Downloads/data analyzer/.venv/lib/python3.12/site-packages/pytestqt/plugin.py:220: UserWarning: Glyph 35889 (\N{CJK UNIFIED IDEOGRAPH-8C31}) missing from font(s) DejaVu Sans.
    app.processEvents()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
37 passed, 15 warnings in 10.41s

$ TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py -q -m slow
.                                                                        [100%]
=============================== warnings summary ===============================
tests/perf/test_timedomain_pan_perf.py:46
  /Users/donghang/Downloads/data analyzer/tests/perf/test_timedomain_pan_perf.py:46: PytestUnknownMarkWarning: Unknown pytest.mark.slow - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/how-to/mark.html
    pytestmark = pytest.mark.slow

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1 passed, 1 warning in 9.58s

$ TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/perf/test_timedomain_pan_perf.py -q -m slow -s
TIMEDOMAIN_PAN_PERF path=matplotlib channels=5 samples=100000 iters=50 p50_ms=10.864 p95_ms=11.124 mean_ms=7.265 min_ms=0.085 max_ms=11.151
1 passed, 1 warning in 9.34s
```

## T2 review (contract freeze + reset_cursor_state seam)

### Findings

- PASS: The contract test freezes the four exact signal names and payloads (`tests/ui/test_timedomain_canvas_contract.py:55-77`), and the live canvas declares those signals on `TimeDomainCanvas` (`mf4_analyzer/ui/canvases.py:497-502`).

- PASS: The contract test covers raw `channel_data` tuple semantics and verifies `get_statistics` is not reading poisoned envelope output (`tests/ui/test_timedomain_canvas_contract.py:132-156`, `:164-215`). The live canvas stores raw `(t, sig, color, unit)` in `channel_data` and keeps `data_id` separately (`mf4_analyzer/ui/canvases.py:511-518`).

- PASS: The contract test pins the retired SpanSelector behavior by asserting `MainWindow.plot_time` does not call `enable_span_selector` (`tests/ui/test_timedomain_canvas_contract.py:223-237`), and the live `plot_time` path leaves only the retirement comment at `mf4_analyzer/ui/main_window.py:1005-1008`.

- PASS: The contract test pins literal TimeChartCard labels and Ctrl+1..Ctrl+5 shortcuts (`tests/ui/test_timedomain_canvas_contract.py:245-290`). The live UI defines the same labels and shortcut tuple (`mf4_analyzer/ui/chart_stack.py:165-173`, `:554-580`, `:603-618`).

- PASS: The implementation seam matches the requested body and ordering: `reset_cursor_state()` mutates `_ax/_bx`, `_placing`, and `_refresh` before calling `draw_idle()` (`mf4_analyzer/ui/canvases.py:1313-1333`), and `_reset_cursors` uses `getattr(..., "reset_cursor_state", None)` plus a callable fallback (`mf4_analyzer/ui/main_window.py:680-700`).

- PASS: The source diff is limited to the intended T2 symbols:

```text
$ git diff --unified=0 -- mf4_analyzer/ui/main_window.py mf4_analyzer/ui/canvases.py
@@ -1312,0 +1313,22 @@ class TimeDomainCanvas(FigureCanvas):
+    def reset_cursor_state(self):
+        ...
+        self._ax = self._bx = None
+        self._placing = 'A'
+        self._refresh = True
+        self.draw_idle()
@@ -681,5 +681,17 @@ class MainWindow(QMainWindow):
-        """Reset both single and dual cursor state on the time-domain canvas."""
-        self.canvas_time._ax = self.canvas_time._bx = None
-        self.canvas_time._placing = 'A'
-        self.canvas_time._refresh = True
-        self.canvas_time.draw_idle()
+        """Reset both single and dual cursor state on the time-domain canvas.
+        ...
+        reset = getattr(self.canvas_time, "reset_cursor_state", None)
+        if callable(reset):
+            reset()
+        else:
+            self.canvas_time._ax = self.canvas_time._bx = None
+            self.canvas_time._placing = 'A'
+            self.canvas_time._refresh = True
+            self.canvas_time.draw_idle()
```

- PASS: Fresh stale-callsite grep shows no `plot_time` auto-enable call; the remaining `_ax/_bx` sites are initialization/reset lifecycle sites plus the explicit compatibility fallback required by the prompt (`/tmp/wave-0-rescue-prompt.md:66-76`):

```text
$ rg -n "enable_span_selector|_ax = None|_bx = None" mf4_analyzer/
mf4_analyzer/ui/main_window.py:694:            self.canvas_time._ax = self.canvas_time._bx = None
mf4_analyzer/ui/canvases.py:567:        self._ax = None;
mf4_analyzer/ui/canvases.py:568:        self._bx = None;
mf4_analyzer/ui/canvases.py:628:        self._ax = None;
mf4_analyzer/ui/canvases.py:629:        self._bx = None
mf4_analyzer/ui/canvases.py:639:        self._ax = None
mf4_analyzer/ui/canvases.py:640:        self._bx = None
mf4_analyzer/ui/canvases.py:1288:    def enable_span_selector(self, cb):
mf4_analyzer/ui/canvases.py:1305:            self._ax = self._bx = None;
mf4_analyzer/ui/canvases.py:1330:        self._ax = self._bx = None
```

### Required verification stdout

```text
$ TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_timedomain_canvas_contract.py tests/ui/test_main_window_smoke.py -q
...................................................                      [100%]
51 passed in 11.63s
```

Pre-change red/green history was not independently replayed because doing so would require reverting source in `mf4_analyzer/`, which the prompt forbids (`/tmp/wave-0-rescue-prompt.md:94-99`). The post-change required command is verified above.

## Scope-creep audit

- PASS: Future-task files are not present or changed. Evidence:

```text
$ git status --short -- mf4_analyzer/ui/pg_canvases.py mf4_analyzer/ui/_axis_handle.py mf4_analyzer/signal/_envelope_cutils.py mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui/dialogs.py
# no output

$ rg -n "TimeDomainCanvasPG|positions_envelope|class AxisHandle|PgAxisHandle|MplAxisHandle|import pyqtgraph|from pyqtgraph" mf4_analyzer/
# no output
```

- PASS: FFT path is untouched. The prompt names `FFTTimeWorker`, `SpectrogramResult`, and `_fft_time_cache_key` as shielded checks (`/tmp/wave-0-rescue-prompt.md:80-82`); the fresh added/deleted-line grep had no matches:

```text
$ git diff --unified=0 -- mf4_analyzer | rg -n "^[+-].*(FFTTimeWorker|SpectrogramResult|_fft_time_cache_key|fft_time|canvas_fft)"
# no output
```

- PASS: B1-B7 are remaining historical baseline, not W0 scope. The follow-up spec says it is completed / historical and not part of this migration (`docs/superpowers/specs/2026-05-28-review-followup-fixes.md:6-10`) and lists the live B1-B7 evidence ranges (`docs/superpowers/specs/2026-05-28-review-followup-fixes.md:14-29`). Fresh diff hunks only touch `canvases.py:1313` and `main_window.py:681`, not B2 `main_window.py:430-434` or B3 `canvases.py:2403/2443`; B1/B4-B7 path status was empty:

```text
$ git status --short -- mf4_analyzer/ui/inspector_sections.py mf4_analyzer/acquisition_ui/main_window.py can_logger/p0/a2l_probe.py tests/test_p0_a2l_probe.py tests/ui/test_main_window_smoke.py tests/ui/test_canvases.py tests/acquisition_ui/test_cockpit_close.py tests/acquisition_ui/test_dropped_frame_prompt.py tests/acquisition_ui/test_main_window_transport_chip.py
# no output
```

## Defensive-gate audit

| Gate | Verdict | Evidence |
| --- | --- | --- |
| codex-runtime-verification-entrypoints | PASS | Required pytest replays used `.venv/bin/python -m pytest` with `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen`; stdout shows `51 passed`, `37 passed`, and perf `1 passed` above (`/tmp/wave-0-rescue-prompt.md:84-92`). |
| codex-phantom-api-surface-guards | PASS | T1/T2 grep found only real `importlib.util.find_spec` and `getattr(cutils, "positions", None)` probe sites, with no MagicMock pyqtgraph/asammdf hits; report lines above paste the exact grep output. |
| codex-plan-spec-literal-evidence | PASS | T1/T2 checks were keyed to prompt lines `/tmp/wave-0-rescue-prompt.md:51-76` and design invariants `docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md:60-74`, `:158-177`, `:260-272`. |
| codex-confirmed-issue-list-means-remaining-scope | PASS | B1-B7 spec marks the list completed / historical and out of this migration (`docs/superpowers/specs/2026-05-28-review-followup-fixes.md:6-10`); status/diff evidence above shows no B1/B4-B7 path edits and no B2/B3 hunk. |
| codex-analyzer-doc-routing | PASS | The prompt requires this review under `docs/analyzer/reviews/2026-05-28-pyqtgraph-wave0.md` (`/tmp/wave-0-rescue-prompt.md:35`, `:101-103`), and this report is written there. |
| codex-visual-parity-rendered-screenshot | PASS | N/A by contract for this W0 review (`/tmp/wave-0-rescue-prompt.md:45`); no production renderer switch exists (`mf4_analyzer/ui/chart_stack.py:728-732`). |
| codex-fft-time-review-shields | PASS | Added/deleted-line grep for `FFTTimeWorker`, `SpectrogramResult`, `_fft_time_cache_key`, `fft_time`, and `canvas_fft` had no output; command stdout is pasted in Scope-creep audit. |
| pyqt-ui flush-after-axis-mutation-not-before | PASS | `reset_cursor_state()` mutates fields at `mf4_analyzer/ui/canvases.py:1330-1332` and redraws last at `mf4_analyzer/ui/canvases.py:1333`. |

## Suggested deltas

(required) Make the slow perf benchmark truly opt-in and remove the unknown-marker warning before shipping W0. Right now the test's own comment says the marker keeps the default suite from running it (`tests/perf/test_timedomain_pan_perf.py:18-20`), but fresh stdout proves default invocation of that file still runs the slow test and emits `PytestUnknownMarkWarning`. Apply this config-level diff:

```diff
diff --git a/pytest.ini b/pytest.ini
new file mode 100644
--- /dev/null
+++ b/pytest.ini
@@ -0,0 +1,5 @@
+[pytest]
+markers =
+    slow: opt-in performance and long-running checks excluded from the default suite
+addopts =
+    -m "not slow"
```

## Next-wave readiness

BLOCKED — T2's seam is ready, but W1 (T3 + T4) should wait until the required slow-marker/default-suite rework is applied; the fourth-run perf evidence mismatch is NEEDS-INFO, not a source-code blocker, but should be reconciled before using the baseline as final acceptance evidence (`/tmp/wave-0-rescue-prompt.md:54-59`; `docs/superpowers/reports/2026-05-28-pyqtgraph-timedomain-migration-results.md:104-110`).
