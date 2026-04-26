# T3 — `RebuildTimePopover` geometry clipping

**Date:** 2026-04-26
**Subtask:** T3 (popover geometry, scoped to one production file +
one new test file). Sibling tasks T1 (diagnosis) and T2 (Fs-edit
plumbing) own the "manual Fs has no effect" bug; T3 fixes only the
secondary user complaint that the popover renders off-screen on the
right pane.

## User complaint addressed

> "弹出的自定义时间轴在窗口外面，得缩小软件才能看得到。"

The FFT vs Time inspector "重建时间轴" button lives in the right pane,
which on a 1920×1080+ display sits very close to the screen's right
edge. `RebuildTimePopover.show_at` previously moved the dialog to
`anchor.mapToGlobal(anchor.rect().bottomLeft())` with no
screen-availability check, so the popover's right side could clip
beyond the primary monitor and the user had to shrink the whole
program window to see it. Same for the bottom edge when the inspector
section was scrolled to its bottom.

## Files changed

- `mf4_analyzer/ui/drawers/rebuild_time_popover.py` — geometry clipping
  in `show_at`; added `MARGIN` and `GAP` module constants; added
  helper `_available_geometry_for`.
- `tests/ui/test_rebuild_popover_geometry.py` — new pytest-qt suite
  (4 tests) covering right-edge, bottom-edge (flip-above), corner
  (clamp-both), and the room-available no-op case.

## Symbols touched (per
`orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`)

- `mf4_analyzer.ui.drawers.rebuild_time_popover`:
  - **modified:** `RebuildTimePopover.show_at`.
  - **added:** module-level constants `MARGIN`, `GAP`; new private
    helper `RebuildTimePopover._available_geometry_for`.
  - **unchanged:** `RebuildTimePopover.__init__`, `new_fs`, `event`.
- `tests/ui/test_rebuild_popover_geometry.py`:
  - **added:** `_avail`, `_build_window_with_anchor`,
    `test_popover_clamped_inside_right_edge`,
    `test_popover_clamped_inside_bottom_edge_flips_above`,
    `test_popover_clamped_inside_corner`,
    `test_popover_uses_anchor_bottom_when_room_available`.

No symbols were touched in any forbidden file (T1/T2 prod files,
`main_window.py`, inspector contextual classes, FFT/order algorithms,
loaders).

## Algorithm

1. `adjustSize()` then `sizeHint()` → resolve `(w, h)`.
2. Anchor's bottom-left in global coords = default `(x, y)`.
3. Pick the screen the anchor is on (`QGuiApplication.screenAt(anchor
   center global)`), fall back to `QApplication.primaryScreen()`,
   ultimate fallback to a synthetic 1920×1080 rect so the call never
   raises in headless edge-cases.
4. Horizontal: clamp into `[avail.left+MARGIN, avail.right-MARGIN]`.
   Qt's `right()` is inclusive (`x + w - 1 <= right_limit`), so the
   bound subtracts 1 the right way around — the bug-trigger geometry
   in the smoke test exposed this as a real off-by-one.
5. Vertical: if `(y, h)` overflows the bottom, attempt flip-above
   (`y = anchor_top_global.y() - h - GAP`); if the flipped position
   still doesn't fit (anchor in a vertical corner where neither below
   nor above clears), clamp so `bottom == bottom_limit` and then
   clamp again to top to guarantee `top >= top_limit`.
6. `MARGIN = 8`, `GAP = 4`.

## Tests

| Stage  | Total UI tests passing |
| ------ | ---------------------- |
| before | 181                    |
| after  | 185                    |

```
$ QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui
======================= 185 passed, 16 warnings in 6.72s =======================
```

Targeted run of the new file:

```
$ QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_rebuild_popover_geometry.py -v
tests/ui/test_rebuild_popover_geometry.py::test_popover_clamped_inside_right_edge        PASSED
tests/ui/test_rebuild_popover_geometry.py::test_popover_clamped_inside_bottom_edge_flips_above PASSED
tests/ui/test_rebuild_popover_geometry.py::test_popover_clamped_inside_corner            PASSED
tests/ui/test_rebuild_popover_geometry.py::test_popover_uses_anchor_bottom_when_room_available PASSED
4 passed in 0.77s
```

`test_drawers.py::test_rebuild_time_popover_anchors_below_widget`
continues to pass — the geometry fix is a no-op when the natural
anchor.bottomLeft position fits.

## UI verification

- Platform: `QT_QPA_PLATFORM=offscreen` (per
  `pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`, offscreen
  Qt exposes valid screen geometry, so geometry assertions are
  trustworthy in headless CI).
- Smoke exercise: scripted reproduction of "anchor in
  bottom-right corner of the available screen" produced popover
  geometry `QRect(519, 452, 273, 140)` inside `QRect(0, 0, 800, 600)`,
  with all four edges inside `MARGIN=8`. Same scenario before the fix
  produced a frame ending at right=789, bottom=646 (bottom > 591
  limit → off-screen).
- Macro/desktop verification: not exercised — this subagent runs
  headless. The fix is geometry-arithmetic (no platform-specific
  drawing), and the four pytest-qt cases cover the corner cases the
  user reported.

`ui_verified = true` (offscreen smoke pass per the brief's
`ui_verified: offscreen smoke 通过即可` clause).

## Lessons

No new lesson written. The fix is a textbook application of the
existing `pyqt-ui/2026-04-24-responsive-pane-containers.md` ("right
pane wide-end behavior is its own axis") and the offscreen-geometry
guidance from `pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`.
Both were consumed at startup. Re-deriving them would violate the
"no water content" rule in `LESSONS.md`'s README.

## Forbidden-symbol self-check

Per `orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`:

| Forbidden region | Touched? |
| ---------------- | -------- |
| Other prod `.py` outside `rebuild_time_popover.py` | No |
| `mf4_analyzer/ui/inspector*.py` (any contextual class) | No |
| `mf4_analyzer/ui/main_window.py` | No |
| Any T1/T2 file | No |
| FFT/order algorithm internals, `DataLoader`, `FileData`, `ChannelMath` | No |

`grep -rn "RebuildTimePopover"` confirms `main_window.py` still
references the same constructor signature `(self, fd.filename,
fd.fs)` and the same `show_at(anchor)` call site — no caller-side
adjustment needed.
