# FFT vs Time 2D — Module C Review (T5 + T6)

**Reviewer:** codex (read-only sandbox, static analysis)
**Date:** 2026-04-25
**Scope:** T5 (synchronous compute + cache) + T6 (worker thread)

---

## Verdict

**approve-with-nits**

Static review found Module C compliant with the FFT vs Time cache, worker, wiring, and boundary-discipline checklist. Test execution could not be verified by codex because pytest was unavailable in its sandbox:

- `pytest tests/ -v -p no:cacheprovider` → exit 127, `command not found: pytest`
- `python3 -m pytest tests/ -v -p no:cacheprovider` → exit 1, `No module named pytest`

Main Claude reran pytest in the host environment after the codex pass — see "Test execution (host re-run)" at the bottom.

---

## Blockers

None.

---

## Important

None found.

---

## Nits

- `mf4_analyzer/ui/main_window.py:217` — comment mentions `_copy_fft_time_image` routing to T8, but no actual connection is wired yet at that line. T8 owns export, so this is a comment-accuracy nit only.
- `main_window.py:99`, `:1199`, `:1223`, `:1274` — hard-coded cache/status literals (`12`, `'使用缓存结果'`, `'正在计算…'`). Acceptable for now; consider extracting to named constants if reused in T8/T9.

---

## Spec-Compliance Scorecard

| Item | Status | Note |
|---|---|---|
| 1. Cache key purity | PASS | `_fft_time_cache_key` includes only compute fields at `main_window.py:1097`. |
| 2. LRU semantics | PASS | Capacity 12 at `:99`; hit pop/reinsert at `:1114`; overflow `last=False` at `:1124`. |
| 3. Cache-hit status and sync path | PASS | Cache hit returns before worker at `:1219`; status contains `使用缓存结果` at `:1223`. |
| 4. Failed-compute keeps old chart | PASS | Failure handler only toasts/statuses at `:1336`; no `canvas_fft_time.clear()` path. |
| 5. Worker correctness | PASS | `FFTTimeWorker(QObject)` and signals at `:28`; cleanup chain at `:1261`–`:1271`. |
| 6. Re-entry guard | PASS | Running-thread guard and `正在计算…` shown at `:1195`. |
| 7. `cursor_info` wiring | PASS | Connected at `:240`; handler at `:1292`. |
| 8. `freq_range` clamp | PASS | Contradictory range returns `None` at `:1174`. |
| 9. Inspector relays | PASS | `pyqtSignal(object)` at `inspector.py:40`; relays at `inspector.py:108` and `:110`. |
| 10. Boundary discipline | PASS | `_fft_time_cache.clear()` callsites are zero; `_copy_fft_time_image` only appears in a comment at `:217`. |
| 11. Tests run green | DEFERRED → see host re-run below | pytest unavailable in codex sandbox; T6 report records 122 passed but codex could not independently verify. |
| 12. Cosmetic / hygiene | PASS | Only the nits above. |
| 13. Test quality | PASS | Widget tests use `qtbot.addWidget`; worker tests use `Qt.DirectConnection` per the QThread lesson. |

---

## Recommendation for Main Claude

Proceed with Module C. No source changes are required. Before tagging Module C as complete, rerun `pytest tests/ -v` in an environment where pytest and pytest-qt are installed to confirm the 122-test baseline. Optionally clean up the export-wiring comment at `main_window.py:217` before T8 is dispatched. Then proceed to T7 (cache invalidation sites).

---

## Test execution (host re-run by main Claude)

```
$ PYTHONPATH=. .venv/bin/pytest tests/ -q
........................................................................ [ 59%]
..................................................                       [100%]
122 passed in 4.08s
```

Item 11 is upgraded from DEFERRED to **PASS** — 122/122 green, matches the
T6 report's claim. No regressions.
