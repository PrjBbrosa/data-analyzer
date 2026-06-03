# Copy Annotation Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the four chart-card toolbar copy buttons copy an image, show a dismissible optional thumbnail that can open a lightweight crop/annotation editor, while keeping the copied image immediately usable.

**Architecture:** `ChartStack` captures the final hi-DPI `QPixmap` and emits it upward; `MainWindow` owns clipboard publishing, toast, thumbnail, and editor lifecycle. `mf4_analyzer/ui/markup/` stays self-contained and only depends on PyQt and `QPixmap`.

**Tech Stack:** PyQt5 widgets/graphics scene, pytest-qt offscreen UI tests, existing Precision Light UI tokens, existing chart copy helpers.

---

## Files

- Create: `mf4_analyzer/ui/markup/__init__.py` exporting `CopyThumbnail` and `MarkupEditor`.
- Create: `mf4_analyzer/ui/markup/thumbnail.py` for the clickable right-bottom thumbnail.
- Create: `mf4_analyzer/ui/markup/editor.py` for the non-modal editor window.
- Modify: `mf4_analyzer/ui/chart_stack.py` so `_copy_card_image` emits captured `QPixmap` instead of writing clipboard directly.
- Modify: `mf4_analyzer/ui/main_window.py` so `MainWindow` publishes pixmaps, owns thumbnail/editor instances, and keeps FFT-vs-Time inspector copy outside the new flow.
- Test: `tests/ui/test_copy_thumbnail.py`, `tests/ui/test_markup_editor.py`, `tests/ui/test_chart_stack.py`, `tests/ui/test_main_window_smoke.py`, `tests/ui/test_timedomain_canvas_contract.py`.

---

### Task 1: Final UI/Spec Contract

**Files:**
- Modify: `docs/superpowers/specs/2026-05-31-copy-annotation-editor-design.md`
- Keep: `docs/analyzer/ui-prototypes/2026-05-31-copy-annotation-editor-ui.html`

- [x] **Step 1: Save current UI prototype**

Keep the approved prototype at:

```text
docs/analyzer/ui-prototypes/2026-05-31-copy-annotation-editor-ui.html
```

- [x] **Step 2: Lock toolbar decisions into the spec**

The editor toolbar is one row:

```text
[关闭] | 红色 4px | [选择] [裁剪] [箭头] [直线] [矩形] [画笔] [文字] [序号] | [撤销] [重做] | [保存 Ctrl+S] [完成复制 ↵]
```

The toolbar does not include a trash/delete button and does not include a separate copy button.

### Task 2: Thumbnail Widget

**Files:**
- Create: `mf4_analyzer/ui/markup/__init__.py`
- Create: `mf4_analyzer/ui/markup/thumbnail.py`
- Test: `tests/ui/test_copy_thumbnail.py`

- [ ] **Step 1: Write failing thumbnail tests**

Add tests for:

```python
def test_thumbnail_present_shows_preview_and_keeps_full_pixmap(qtbot): ...
def test_thumbnail_click_emits_full_resolution_pixmap(qtbot): ...
def test_thumbnail_close_and_dismiss_hide_widget(qtbot): ...
def test_thumbnail_hover_pauses_and_resumes_timer(qtbot): ...
```

- [ ] **Step 2: Run red tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ui/test_copy_thumbnail.py -q
```

Expected before implementation: import or attribute failures for `CopyThumbnail`.

- [ ] **Step 3: Implement `CopyThumbnail`**

Implement `present(pix)`, `dismiss()`, `clicked = pyqtSignal(QPixmap)`, a 3000 ms timer, hover pause/resume, close button, and right-bottom parent positioning.

- [ ] **Step 4: Run green tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ui/test_copy_thumbnail.py -q
```

Expected after implementation: all thumbnail tests pass.

### Task 3: Markup Editor Core

**Files:**
- Create: `mf4_analyzer/ui/markup/editor.py`
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: Write failing editor tests**

Add tests for:

```python
def test_editor_initializes_scene_with_background_pixmap(qtbot): ...
def test_editor_toolbar_has_single_output_copy_action_and_no_delete(qtbot): ...
def test_apply_crop_rect_resizes_background_and_offsets_items(qtbot): ...
def test_render_result_uses_current_background_size(qtbot): ...
def test_finish_and_copy_calls_on_done(qtbot): ...
```

- [ ] **Step 2: Run red tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ui/test_markup_editor.py -q
```

Expected before implementation: import or attribute failures for `MarkupEditor`.

- [ ] **Step 3: Implement editor minimum viable behavior**

Implement a non-modal `QWidget` with a single top toolbar, `QGraphicsScene`, background `QGraphicsPixmapItem`, `apply_crop_rect(QRectF)`, `render_result()`, and `finish_and_copy()`.

- [ ] **Step 4: Run green tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ui/test_markup_editor.py -q
```

Expected after implementation: all editor tests pass.

### Task 3.5: Snipaste-Style P0/P1 Interaction Polish

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`
- Modify: `tests/ui/test_markup_editor.py`
- Modify: `docs/superpowers/specs/2026-05-31-copy-annotation-editor-design.md`

Scope guard: do not add P2 tools. No mosaic, blur, eraser, color picker, pin-to-screen, OCR, history, upload/share, rotation, transparency, or click-through. Improve only the existing tools: select, crop, arrow, line, rectangle, pen, text, number, undo/redo, save, done-copy.

- [ ] **Step 1: Write failing tests for P0/P1 editor interaction**

Add focused tests in `tests/ui/test_markup_editor.py`:

```python
def test_zoom_controls_change_view_scale_without_changing_render_size(qtbot): ...
def test_style_controls_apply_to_new_and_selected_items(qtbot): ...
def test_select_tool_drags_existing_item(qtbot): ...
def test_shift_drag_line_constrains_to_horizontal_or_vertical(qtbot): ...
def test_text_tool_creates_inline_editable_text_item(qtbot): ...
def test_crop_tool_creates_adjustable_box_before_apply(qtbot): ...
def test_delete_arrow_keys_and_copy_paste_operate_on_selection(qtbot): ...
def test_toolbar_uses_icons_and_primary_done_button(qtbot): ...
```

- [ ] **Step 2: Run red tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

Expected before implementation: failures for missing zoom helpers, immutable style controls, immediate crop apply, popup text input, no icon-only toolbar, or missing selection operations.

- [ ] **Step 3: Implement P0 editor polish**

In `mf4_analyzer/ui/markup/editor.py`:
- Add zoom helpers (`zoom_in`, `zoom_out`, `actual_size`, `fit_to_window`) and wheel zoom around the cursor.
- Add color swatches and width controls; apply changes to selected items and remember current style for new items.
- Replace tool text buttons with icon-only `QToolButton`s using existing `qtawesome` MDI icons; keep tooltips with Chinese names and shortcuts.
- Style `完成复制` as the blue primary action and keep `保存` secondary.
- Replace text popup input with inline `QGraphicsTextItem` editing on the scene.
- Change crop drag to create an adjustable crop box; only `apply_active_crop()` / Enter commits the crop.

- [ ] **Step 4: Implement P1 editor polish**

In `mf4_analyzer/ui/markup/editor.py`:
- Implement explicit select-mode drag for whole items.
- Add handles for line/arrow endpoints and rectangle corners/edges.
- Add `Shift` constraint while drawing line/arrow (nearest horizontal/vertical) and square constraint for rectangle.
- Add `Ctrl/Cmd+A` select all, `Ctrl/Cmd+C/V` copy/paste selected annotations, `Delete/Backspace` delete selected, and arrow-key movement.
- Add undo commands for add/delete/move/style/crop where the interaction changes scene state.

- [ ] **Step 5: Run green tests**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

Expected after implementation: all markup editor tests pass.

### Task 4: ChartStack Pixmap Signal

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `tests/ui/test_chart_stack.py`
- Modify: `tests/ui/test_timedomain_canvas_contract.py`

- [ ] **Step 1: Write failing signal tests**

Update the contract so `ChartStack` exposes `image_captured = pyqtSignal(QPixmap)` and `_copy_card_image` emits that pixmap after cursor-pill compositing.

- [ ] **Step 2: Run red tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ui/test_timedomain_canvas_contract.py::test_chart_stack_copy_card_image_composites_cursor_pill tests/ui/test_chart_stack.py::test_copy_card_image_renders_at_hidpi_scale tests/ui/test_chart_stack.py::test_copy_card_image_composites_scaled_cursor_pill -q
```

Expected before implementation: signature/clipboard assertions fail.

- [ ] **Step 3: Implement signal migration**

Keep `_copy_card_image` capture and cursor-pill composition intact, remove direct clipboard write from `ChartStack`, emit `image_captured.emit(pix)`.

- [ ] **Step 4: Run green tests**

Run the same command and expect all selected tests to pass.

### Task 5: MainWindow Publish Pipeline

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`
- Test: `tests/ui/test_main_window_smoke.py`

- [ ] **Step 1: Write failing publish tests**

Add tests for:

```python
def test_publish_copied_pixmap_sets_clipboard_toast_and_thumbnail(qtbot, monkeypatch): ...
def test_publish_copied_pixmap_ignores_null_pixmap(qtbot, monkeypatch): ...
def test_chart_stack_image_captured_routes_to_publish_pipeline(qtbot, monkeypatch): ...
def test_thumbnail_click_opens_markup_editor_with_full_pixmap(qtbot, monkeypatch): ...
def test_editor_done_republishes_annotated_pixmap_without_thumbnail_loop(qtbot, monkeypatch): ...
```

- [ ] **Step 2: Run red tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ui/test_main_window_smoke.py::test_publish_copied_pixmap_sets_clipboard_toast_and_thumbnail tests/ui/test_main_window_smoke.py::test_publish_copied_pixmap_ignores_null_pixmap tests/ui/test_main_window_smoke.py::test_chart_stack_image_captured_routes_to_publish_pipeline tests/ui/test_main_window_smoke.py::test_thumbnail_click_opens_markup_editor_with_full_pixmap tests/ui/test_main_window_smoke.py::test_editor_done_republishes_annotated_pixmap_without_thumbnail_loop -q
```

Expected before implementation: missing method/import failures.

- [ ] **Step 3: Implement publish/editor lifecycle**

Create `_copy_thumbnail` in `_init_ui`, connect `image_captured` to `_publish_copied_pixmap`, add `_open_markup_editor`, keep editor refs alive, add `_publish_annotated_pixmap`.

- [ ] **Step 4: Run green tests**

Run the same command and expect all selected tests to pass.

### Task 6: Scope Guard And Regression Verification

**Files:**
- Existing tests only unless failures reveal a required narrow fix.

- [ ] **Step 1: Verify FFT-vs-Time inspector copy remains outside scope**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ui/test_main_window_smoke.py::test_copy_fft_time_image_warns_when_no_result tests/ui/test_main_window_smoke.py::test_copy_fft_time_image_pushes_pixmap_when_has_result -q
```

Expected: both tests pass and no thumbnail/publish path is required.

- [ ] **Step 2: Run focused feature suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/ui/test_copy_thumbnail.py tests/ui/test_markup_editor.py tests/ui/test_chart_stack.py::test_copy_card_image_renders_at_hidpi_scale tests/ui/test_chart_stack.py::test_copy_card_image_composites_scaled_cursor_pill tests/ui/test_timedomain_canvas_contract.py::test_chart_stack_copy_card_image_composites_cursor_pill tests/ui/test_main_window_smoke.py::test_copy_fft_time_image_warns_when_no_result tests/ui/test_main_window_smoke.py::test_copy_fft_time_image_pushes_pixmap_when_has_result -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run lesson gate**

Run:

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```

Expected: no required lesson unless implementation uncovered a repeatable workflow or regression risk.
