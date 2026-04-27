# Batch UI Fixes + FFT vs Time Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three batch-dialog issues — (1) signal picker grows the dialog horizontally as more signals are selected, (2) RPM channel cannot be picked from a list and has no unit-aware coefficient input, (3) the FFT-vs-Time analysis available in single-shot mode is missing from batch mode.

**Architecture:**
- Issue 1 — replace the chip-string `QPushButton` display in `SignalPickerPopup` with a vertical chip frame (one chip per row, capped height with internal scroll). Width is bounded; height grows with selection count, contained within the InputPanel column.
- Issue 2 — add `single_select=True` mode to `SignalPickerPopup` (radio-style); InputPanel replaces the editable `QComboBox` with this single-select picker. Adjacent unit combo (rpm / rad/s / deg/s / 自定义) auto-populates a `QDoubleSpinBox` factor that writes through to existing `params['rpm_factor']`. The RPM row hides for methods that don't consume RPM (`fft`, `fft_time`).
- Issue 3 — add `fft_time` to `BatchRunner.SUPPORTED_METHODS`, dispatch to `SpectrogramAnalyzer` in `_run_one`, export 2D amplitude as long-format `(time_s, frequency_hz, amplitude)` dataframe, render PNG via matplotlib `imshow`, and degrade 64 MB ceiling overruns into per-task `failed`. UI gets a fourth method button + `overlap`/`remove_mean` widgets.

**Tech Stack:** PyQt5, pytest + pytest-qt, NumPy, pandas, matplotlib (Agg backend in tests), `mf4_analyzer.signal.spectrogram.SpectrogramAnalyzer`.

---

## File Structure

**Modified:**
- `mf4_analyzer/ui/drawers/batch/signal_picker.py` — replace `_display_btn` with a chip frame; add `single_select` mode.
- `mf4_analyzer/ui/drawers/batch/input_panel.py` — replace RPM `QComboBox` with single-select picker; add unit combo + factor spinbox; conditional row visibility per method.
- `mf4_analyzer/ui/drawers/batch/method_buttons.py` — add `fft_time` method + `overlap`/`remove_mean` widgets; remove `rpm_factor` (moved to InputPanel).
- `mf4_analyzer/ui/drawers/batch/sheet.py` — wire `methodChanged` → `InputPanel.set_method` for visibility init-sync.
- `mf4_analyzer/batch.py` — extend `SUPPORTED_METHODS`, add `fft_time` dispatch + dataframe + image branches.
- `mf4_analyzer/ui/style.qss` — add `#SignalChip` styling.

**Tests modified / created (all under existing files):**
- `tests/ui/test_batch_signal_picker.py` — chip layout, single-select mode, chip remove.
- `tests/ui/test_batch_input_panel.py` — RPM picker, unit-preset → factor, conditional visibility.
- `tests/ui/test_batch_method_buttons.py` — `fft_time` button, `rpm_factor` removal, new widgets.
- `tests/test_batch_runner.py` — `fft_time` dispatch, long-format dataframe, image, ceiling failure.
- `tests/ui/test_batch_smoke.py` — end-to-end smoke for `fft_time` if pattern matches existing smoke style.

---

## Phase 1: Signal Picker Chip Refactor (Issue 1)

### Task 1: Chip row widget

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/signal_picker.py` (top of file, before `SignalPickerPopup`)
- Test: `tests/ui/test_batch_signal_picker.py` (append)

- [ ] **Step 1.1: Write the failing test for chip-row widget**

```python
def test_signal_chip_emits_remove_signal(qtbot):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalChip
    chip = SignalChip("sig_a")
    qtbot.addWidget(chip)
    received = []
    chip.removeRequested.connect(received.append)
    qtbot.mouseClick(chip._remove_btn, Qt.LeftButton)
    assert received == ["sig_a"]


def test_signal_chip_label_truncates_long_name(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalChip
    long_name = "A_side.Rte." + "x" * 200
    chip = SignalChip(long_name, max_label_chars=40)
    qtbot.addWidget(chip)
    assert chip._label.toolTip() == long_name
    assert len(chip._label.text()) <= 41  # 40 + ellipsis "…"
    assert chip._label.text().endswith("…")
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `pytest tests/ui/test_batch_signal_picker.py::test_signal_chip_emits_remove_signal tests/ui/test_batch_signal_picker.py::test_signal_chip_label_truncates_long_name -v`
Expected: FAIL with `ImportError: cannot import name 'SignalChip'`

- [ ] **Step 1.3: Implement `SignalChip`**

First, extend the existing top-of-file imports in `mf4_analyzer/ui/drawers/batch/signal_picker.py` so `QLabel`, `QScrollArea`, and `QSizePolicy` are available — keeping all imports at module top per project style (no inline imports):

```python
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)
```

Then insert at the top of the file, after imports and before `class SignalPickerPopup`:

```python
class SignalChip(QWidget):
    """Single-row chip widget: signal label + remove button.

    Emits ``removeRequested(name)`` when the × button is clicked. The
    label elides at ``max_label_chars`` with the full name as tooltip
    so long DBC channel names don't push the chip frame wide.
    """

    removeRequested = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        max_label_chars: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self.setObjectName("SignalChip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 4, 2)
        lay.setSpacing(4)

        display = name if len(name) <= max_label_chars else name[: max_label_chars] + "…"
        self._label = QLabel(display, self)
        self._label.setToolTip(name)
        lay.addWidget(self._label, 1)

        self._remove_btn = QPushButton("×", self)
        self._remove_btn.setObjectName("SignalChipRemove")
        self._remove_btn.setFixedSize(18, 18)
        self._remove_btn.setFlat(True)
        self._remove_btn.clicked.connect(lambda: self.removeRequested.emit(self._name))
        lay.addWidget(self._remove_btn)

    def name(self) -> str:
        return self._name
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `pytest tests/ui/test_batch_signal_picker.py::test_signal_chip_emits_remove_signal tests/ui/test_batch_signal_picker.py::test_signal_chip_label_truncates_long_name -v`
Expected: PASS

- [ ] **Step 1.5: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/signal_picker.py tests/ui/test_batch_signal_picker.py
git commit -m "feat(batch-ui): add SignalChip widget with elided label and remove signal"
```

### Task 2: Vertical chip frame replacing display button

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/signal_picker.py:24-83` (the `__init__` of `SignalPickerPopup`) and `:240-245` (`_refresh_display`)
- Test: `tests/ui/test_batch_signal_picker.py` (append)

- [ ] **Step 2.1: Write the failing test for vertical chip layout**

```python
def test_picker_display_renders_one_chip_per_selected(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import (
        SignalPickerPopup, SignalChip,
    )
    p = SignalPickerPopup(available_signals=["a", "b", "c"])
    qtbot.addWidget(p)
    p.set_selected(("a", "b", "c"))
    chips = p._display_frame.findChildren(SignalChip)
    assert sorted(c.name() for c in chips) == ["a", "b", "c"]


def test_picker_display_height_grows_with_selection_not_width(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["sig1", "sig2", "sig3"])
    qtbot.addWidget(p)
    p.resize(280, 600)
    p.set_selected(("sig1",))
    one_h = p._display_frame.sizeHint().height()
    one_w = p._display_frame.sizeHint().width()
    p.set_selected(("sig1", "sig2", "sig3"))
    three_h = p._display_frame.sizeHint().height()
    three_w = p._display_frame.sizeHint().width()
    assert three_h > one_h
    assert three_w == one_w  # width must NOT scale with chip count


def test_picker_display_chip_remove_unselects_signal(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import (
        SignalPickerPopup, SignalChip,
    )
    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)
    p.set_selected(("a", "b"))
    received = []
    p.selectionChanged.connect(lambda tup: received.append(tup))
    chip_a = next(c for c in p._display_frame.findChildren(SignalChip)
                  if c.name() == "a")
    chip_a._remove_btn.click()
    assert "a" not in p.selected()
    assert received[-1] == ("b",)


def test_picker_display_clicking_empty_area_opens_popup(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    from PyQt5.QtCore import QPoint, Qt
    p = SignalPickerPopup(available_signals=["a"])
    qtbot.addWidget(p)
    p.show()
    qtbot.mouseClick(p._display_frame, Qt.LeftButton, pos=QPoint(5, 5))
    assert p.is_popup_visible() is True
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `pytest tests/ui/test_batch_signal_picker.py -k "display_renders_one_chip or display_height_grows or display_chip_remove or display_clicking_empty" -v`
Expected: FAIL with `AttributeError: 'SignalPickerPopup' object has no attribute '_display_frame'`

- [ ] **Step 2.3: Replace `_display_btn` with `_display_frame` and rebuild logic**

First, add a small `_ClickableFrame` helper class near the top of `mf4_analyzer/ui/drawers/batch/signal_picker.py`, just below `SignalChip` and before `SignalPickerPopup`. This is the **correct** way to make the chip area open the popup: a `QFrame` subclass that emits `clicked` from `mousePressEvent`. **Do NOT** use the `installEventFilter` approach — `eventFilter` on the parent frame would NOT see clicks on chip / scroll children, since QWidget event filtering only fires for events targeted at the watched object itself, and child widgets (chip QLabel, scroll viewport) consume left-button presses before they bubble.

```python
class _ClickableFrame(QFrame):
    """QFrame subclass that emits ``clicked`` on left mouse press.

    Used as the chip-display container so a click anywhere inside the
    frame area (including on the placeholder label or the scroll
    viewport background) toggles the popup. Children that consume
    presses themselves (the remove ``×`` button, chip label) shadow this
    naturally — they get the event first per Qt event delivery rules.
    """

    clicked = pyqtSignal()

    def mousePressEvent(self, event):  # noqa: N802 (Qt API)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
```

Then replace the chip-display section in `SignalPickerPopup.__init__` (currently lines ~42-53 around the `_display_btn` setup):

```python
        # ----- chip display frame (replaces single-line button) -----
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._display_frame = _ClickableFrame(self)
        self._display_frame.setObjectName("SignalPickerDisplay")
        self._display_frame.setFrameShape(QFrame.NoFrame)
        self._display_frame.setStyleSheet(
            "#SignalPickerDisplay {border:1px solid #cbd5e1; border-radius:6px;"
            " background:#fff;}"
        )
        self._display_frame.setMinimumHeight(28)
        # Width is bounded by the parent column; height grows with chip count
        # but is capped at MAX_VISIBLE_ROWS via the internal scroll container.
        self._display_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Click anywhere on the frame (including children that don't consume
        # the press) toggles the popup. The remove × button is a QPushButton
        # so it consumes its own press without bubbling.
        self._display_frame.clicked.connect(self._toggle_popup)

        frame_lay = QVBoxLayout(self._display_frame)
        frame_lay.setContentsMargins(4, 4, 4, 4)
        frame_lay.setSpacing(3)

        # Chip-row sizing constants. The display frame's sizeHint must
        # GROW with chip count (issue-1 contract) up to MAX_VISIBLE_ROWS,
        # then plateau (further chips scroll). A QScrollArea alone does
        # NOT propagate inner content size to the parent's sizeHint, so
        # we explicitly drive _chip_scroll's max/min height from the
        # current chip count in _refresh_display below.
        self._CHIP_ROW_HEIGHT = 26   # one chip row's pixel height (incl. spacing)
        self._CHIP_MAX_VISIBLE_ROWS = 3
        self._CHIP_FRAME_VPADDING = 8  # frame_lay top+bottom margins (4+4)

        # Scrollable inner area for chips (caps the visible height).
        self._chip_scroll = QScrollArea(self._display_frame)
        self._chip_scroll.setFrameShape(QFrame.NoFrame)
        self._chip_scroll.setWidgetResizable(True)
        self._chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Hard ceiling on the scroll area's height; _refresh_display sets
        # the soft height (= row_count * row_height) below this ceiling so
        # _display_frame.sizeHint() honestly reflects chip count.
        self._chip_scroll.setMaximumHeight(
            self._CHIP_MAX_VISIBLE_ROWS * self._CHIP_ROW_HEIGHT
        )

        self._chip_host = QWidget(self._chip_scroll)
        self._chip_layout = QVBoxLayout(self._chip_host)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(2)
        self._chip_layout.addStretch(1)
        self._chip_scroll.setWidget(self._chip_host)
        frame_lay.addWidget(self._chip_scroll, 1)

        self._placeholder_label = QLabel("(未选择信号)  ▾", self._display_frame)
        self._placeholder_label.setStyleSheet("color:#94a3b8; padding:2px 4px;")
        # Make the placeholder transparent to mouse events so a click on it
        # bubbles through to _ClickableFrame.mousePressEvent and opens the
        # popup. (QLabel by default does not consume left-button presses,
        # but it stops propagation through child→parent in some Qt builds —
        # WA_TransparentForMouseEvents is the explicit, portable fix.)
        self._placeholder_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        frame_lay.addWidget(self._placeholder_label)

        # Likewise for the scroll viewport's empty area: chips themselves
        # are children of _chip_host; clicks landing on host empty space
        # should propagate up. QScrollArea.viewport() is a normal QWidget
        # that does NOT consume left presses, so press events naturally
        # bubble to _display_frame — no extra setup needed there.

        outer.addWidget(self._display_frame, 1)
```

Replace the `_refresh_display` method body (currently `:240-245`):

```python
    def _refresh_display(self) -> None:
        # Tear down existing chip rows (everything except the trailing stretch).
        while self._chip_layout.count() > 1:
            item = self._chip_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not self._selected:
            self._placeholder_label.setVisible(True)
            self._chip_scroll.setVisible(False)
            # Reset the scroll area's fixed height so the frame collapses
            # to placeholder height when nothing is selected.
            self._chip_scroll.setFixedHeight(0)
            self.updateGeometry()
            return
        self._placeholder_label.setVisible(False)
        self._chip_scroll.setVisible(True)
        for name in self._selected:
            chip = SignalChip(name, parent=self._chip_host)
            chip.removeRequested.connect(self._on_chip_remove_requested)
            # Insert before the trailing stretch.
            self._chip_layout.insertWidget(self._chip_layout.count() - 1, chip)
        # Drive the scroll area's height from the chip count so
        # _display_frame.sizeHint().height() actually grows with
        # selection up to MAX_VISIBLE_ROWS, then plateaus (further
        # chips scroll). Without this, the QScrollArea reports a
        # fixed minimumSizeHint and the frame's overall sizeHint stays
        # constant — defeating the issue-1 contract test.
        visible_rows = min(len(self._selected), self._CHIP_MAX_VISIBLE_ROWS)
        target_h = visible_rows * self._CHIP_ROW_HEIGHT
        self._chip_scroll.setFixedHeight(target_h)
        self.updateGeometry()

    def _on_chip_remove_requested(self, name: str) -> None:
        if name not in self._selected:
            return
        sel = tuple(s for s in self._selected if s != name)
        self._selected = sel
        # Mirror the checkbox state in the popup so re-opening shows the
        # current truth.
        self._suppress_signal = True
        try:
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item.data(Qt.UserRole) == name:
                    cb = self._list.itemWidget(item)
                    if isinstance(cb, QCheckBox) and cb.isChecked():
                        cb.setChecked(False)
        finally:
            self._suppress_signal = False
        self._refresh_display()
        self.selectionChanged.emit(self._selected)
```

**Do NOT add a `_display_frame` branch to `eventFilter`.** The `_ClickableFrame.mousePressEvent` defined above is the sole click handler for the chip area. The existing `eventFilter` body for `self._popup` (currently `:250-267`) is unchanged — leave it as is.

Update the `show_popup` method to use `_display_frame` instead of `_display_btn`:

```python
    def show_popup(self) -> None:
        global_pos = self._display_frame.mapToGlobal(
            self._display_frame.rect().bottomLeft()
        )
        self._popup.move(global_pos)
        self._popup.adjustSize()
        self._popup.show()
        self._popup.raise_()
        self._popup.setFocus()
```

Delete the now-orphaned `_display_btn` references and the old text-mode `_refresh_display` body. Search for `_display_btn` in the file and remove every reference.

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `pytest tests/ui/test_batch_signal_picker.py -v`
Expected: PASS for all (including pre-existing tests that did not touch `_display_btn` directly).

- [ ] **Step 2.5: Add chip styling to QSS**

In `mf4_analyzer/ui/style.qss`, append at the end of file:

```css
/* Batch signal picker chips */
#SignalChip {
    background-color: #eef2f7;
    border: 1px solid #dfe5ee;
    border-radius: 6px;
}
#SignalChipRemove {
    color: #64748b;
    background: transparent;
    border: none;
    padding: 0;
    font-weight: 700;
    min-height: 18px;
}
#SignalChipRemove:hover { color: #ef4444; }
```

- [ ] **Step 2.6: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/signal_picker.py mf4_analyzer/ui/style.qss tests/ui/test_batch_signal_picker.py
git commit -m "feat(batch-ui): vertical chip layout with internal scroll, fixes horizontal growth (#issue-1)"
```

---

## Phase 2: Single-Select Mode for SignalPickerPopup (Issue 2a)

### Task 3: `single_select` flag

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/signal_picker.py` (constructor + `_on_checkbox_toggled`)
- Test: `tests/ui/test_batch_signal_picker.py` (append)

- [ ] **Step 3.1: Write the failing tests for single-select mode**

```python
def test_picker_single_select_replaces_previous_selection(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(
        available_signals=["a", "b", "c"], single_select=True,
    )
    qtbot.addWidget(p)
    received = []
    p.selectionChanged.connect(lambda tup: received.append(tup))
    p.set_selected(("a",))
    assert p.selected() == ("a",)
    p.set_selected(("b",))
    assert p.selected() == ("b",)
    # Setting two should be normalized to the first only.
    p.set_selected(("a", "c"))
    assert p.selected() == ("a",)


def test_picker_single_select_checking_unchecks_others(qtbot):
    from PyQt5.QtWidgets import QCheckBox
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    from PyQt5.QtCore import Qt
    p = SignalPickerPopup(
        available_signals=["a", "b"], single_select=True,
    )
    qtbot.addWidget(p)
    # Find each row's checkbox and toggle them in order
    boxes: dict[str, QCheckBox] = {}
    for i in range(p._list.count()):
        item = p._list.item(i)
        cb = p._list.itemWidget(item)
        boxes[item.data(Qt.UserRole)] = cb
    boxes["a"].setChecked(True)
    assert p.selected() == ("a",)
    boxes["b"].setChecked(True)
    assert p.selected() == ("b",)
    assert boxes["a"].isChecked() is False  # auto-unchecked
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `pytest tests/ui/test_batch_signal_picker.py -k "single_select" -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'single_select'`

- [ ] **Step 3.3: Add `single_select` to `SignalPickerPopup.__init__`**

In `mf4_analyzer/ui/drawers/batch/signal_picker.py`, modify the constructor signature:

```python
    def __init__(
        self,
        available_signals: Iterable[str] = (),
        partially_available: Mapping[str, str] | None = None,
        initial_selection: tuple[str, ...] = (),
        parent: QWidget | None = None,
        *,
        single_select: bool = False,
    ) -> None:
        super().__init__(parent)
        self._single_select = bool(single_select)
        self._available: list[str] = list(available_signals)
        self._partial: dict[str, str] = dict(partially_available or {})
        # Normalize initial selection if single_select.
        sel = tuple(initial_selection)
        if self._single_select and len(sel) > 1:
            sel = sel[:1]
        self._selected: tuple[str, ...] = sel
        # ... (rest of __init__ unchanged)
```

Update `set_selected` to normalize:

```python
    def set_selected(self, signals: Iterable[str]) -> None:
        new = tuple(s for s in signals)
        if self._single_select and len(new) > 1:
            new = new[:1]
        if new == self._selected:
            return
        # ... (rest unchanged)
```

Update `_on_checkbox_toggled` so single-select unchecks the other:

```python
    def _on_checkbox_toggled(self, signal: str, checked: bool) -> None:
        if self._suppress_signal:
            return
        if self._single_select:
            if checked:
                # Uncheck siblings without re-emitting per click.
                self._suppress_signal = True
                try:
                    for i in range(self._list.count()):
                        item = self._list.item(i)
                        cb = self._list.itemWidget(item)
                        if not isinstance(cb, QCheckBox):
                            continue
                        other = item.data(Qt.UserRole)
                        if other != signal and cb.isChecked():
                            cb.setChecked(False)
                finally:
                    self._suppress_signal = False
                self._selected = (signal,)
            else:
                self._selected = ()
            self._refresh_display()
            self.selectionChanged.emit(self._selected)
            return
        # multi-select original path:
        sel = list(self._selected)
        if checked and signal not in sel:
            sel.append(signal)
        elif not checked and signal in sel:
            sel.remove(signal)
        self._selected = tuple(sel)
        self._refresh_display()
        self.selectionChanged.emit(self._selected)
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `pytest tests/ui/test_batch_signal_picker.py -k "single_select" -v`
Expected: PASS

- [ ] **Step 3.5: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/signal_picker.py tests/ui/test_batch_signal_picker.py
git commit -m "feat(batch-ui): add single_select mode to SignalPickerPopup"
```

---

## Phase 3: RPM Picker + Unit-Aware Coefficient (Issue 2b/2c)

### Task 4: Replace RPM combo with single-select picker + unit + factor row

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py:432-498` (RPM combo construction + universe refresh)
- Test: `tests/ui/test_batch_input_panel.py` (append)

Constants (referenced by later steps):

```python
_RPM_UNIT_FACTORS: dict[str, float] = {
    "rpm":   1.0,
    "rad/s": 60.0 / (2.0 * 3.141592653589793),  # ≈ 9.5493
    "deg/s": 1.0 / 6.0,                         # ≈ 0.1667
    "自定义": 0.0,  # sentinel — leaves spinbox alone
}
```

- [ ] **Step 4.1: Write the failing tests for RPM picker + factor**

```python
def test_input_panel_rpm_uses_single_select_picker(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = InputPanel()
    qtbot.addWidget(p)
    p._file_list.add_loaded_file(0, "a.mf4", frozenset({"sig", "rpm_a"}))
    p._file_list.add_loaded_file(1, "b.mf4", frozenset({"sig", "rpm_a"}))
    assert isinstance(p._rpm_picker, SignalPickerPopup)
    assert p._rpm_picker._single_select is True


def test_input_panel_rpm_picker_partial_signals_visible_but_disabled(qtbot):
    """Partial-availability signals must show in the RPM picker (greyed),
    matching target-signal picker behavior. Resolves the 'RPM 通道无法选择'
    case where a candidate present in only some files used to vanish."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._file_list.add_loaded_file(0, "a.mf4", frozenset({"sig", "rpm_x"}))
    p._file_list.add_loaded_file(1, "b.mf4", frozenset({"sig"}))  # rpm_x only in 1/2
    assert "rpm_x" in p._rpm_picker.visible_items()
    assert p._rpm_picker.is_disabled("rpm_x") is True


def test_input_panel_rpm_unit_preset_sets_factor(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._rpm_unit_combo.setCurrentText("deg/s")
    assert abs(p._rpm_factor_spin.value() - 1.0 / 6.0) < 1e-9
    p._rpm_unit_combo.setCurrentText("rad/s")
    assert abs(p._rpm_factor_spin.value() - 60.0 / (2.0 * 3.141592653589793)) < 1e-6
    p._rpm_unit_combo.setCurrentText("rpm")
    assert p._rpm_factor_spin.value() == 1.0


def test_input_panel_rpm_manual_factor_switches_unit_to_custom(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._rpm_unit_combo.setCurrentText("rpm")
    p._rpm_factor_spin.setValue(0.42)
    assert p._rpm_unit_combo.currentText() == "自定义"


def test_input_panel_rpm_factor_is_returned_in_params(qtbot):
    """rpm_factor lives in params (existing key) so the BatchRunner
    backend (batch.py:506,516) keeps reading it unchanged."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._rpm_unit_combo.setCurrentText("deg/s")
    params = p.rpm_params()
    assert params == {"rpm_factor": 1.0 / 6.0}
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `pytest tests/ui/test_batch_input_panel.py -k "rpm" -v`
Expected: FAIL with `AttributeError: 'InputPanel' object has no attribute '_rpm_picker'`

- [ ] **Step 4.3: Replace RPM combo with picker + unit + factor**

First, extend the existing top-of-file imports in `mf4_analyzer/ui/drawers/batch/input_panel.py` to include `QDoubleSpinBox` (the new factor spinbox uses it; we keep all imports at module top per project style):

```python
from PyQt5.QtWidgets import (
    QAction, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QPushButton, QVBoxLayout, QWidget,
)
```

Then near the top of the file add the unit table:

```python
_RPM_UNIT_FACTORS: dict[str, float] = {
    "rpm":   1.0,
    "rad/s": 60.0 / (2.0 * 3.141592653589793),
    "deg/s": 1.0 / 6.0,
}
_RPM_UNIT_CUSTOM = "自定义"
```

Modify `InputPanel.__init__` so the RPM row is a horizontal trio (picker | unit | factor). Replace the existing RPM-combo construction (currently `:435-437` plus its wiring `:448`) with:

```python
        # ----- RPM row (single-select picker + unit + factor) -----
        rpm_host = QWidget(form_host)
        rpm_lay = QHBoxLayout(rpm_host)
        rpm_lay.setContentsMargins(0, 0, 0, 0)
        rpm_lay.setSpacing(6)

        self._rpm_picker = SignalPickerPopup(parent=rpm_host, single_select=True)
        rpm_lay.addWidget(self._rpm_picker, 1)

        self._rpm_unit_combo = QComboBox(rpm_host)
        for unit in _RPM_UNIT_FACTORS.keys():
            self._rpm_unit_combo.addItem(unit)
        self._rpm_unit_combo.addItem(_RPM_UNIT_CUSTOM)
        self._rpm_unit_combo.setMaximumWidth(90)
        rpm_lay.addWidget(self._rpm_unit_combo)

        # NOTE: setDecimals(10) so unit-preset factors with infinite
        # decimal expansions (1/6 ≈ 0.1666666667, 60/(2π) ≈ 9.5492965855)
        # round-trip through QDoubleSpinBox without losing more than
        # ~1e-10 of precision. The display stays readable; the maximum
        # width below keeps the column from ballooning.
        self._rpm_factor_spin = QDoubleSpinBox(rpm_host)
        self._rpm_factor_spin.setDecimals(10)
        self._rpm_factor_spin.setRange(0.0001, 10000.0)
        self._rpm_factor_spin.setValue(1.0)
        self._rpm_factor_spin.setMaximumWidth(140)
        rpm_lay.addWidget(self._rpm_factor_spin)

        # Form row label
        self._rpm_label_widget = QLabel("RPM 通道", form_host)
        form.addRow(self._rpm_label_widget, rpm_host)
        self._rpm_row_host = rpm_host  # referenced by set_method visibility

        # Wiring
        self._rpm_picker.selectionChanged.connect(lambda *_: self.changed.emit())
        self._rpm_unit_combo.currentTextChanged.connect(self._on_rpm_unit_changed)
        self._rpm_factor_spin.valueChanged.connect(self._on_rpm_factor_value_changed)
        # Internal flag so unit→factor and factor→unit don't ping-pong.
        self._rpm_factor_sync_busy = False
```

Delete the old `self._rpm_combo` block and its wiring line. Add the helper methods inside `InputPanel`:

```python
    def _on_rpm_unit_changed(self, unit: str) -> None:
        if unit in _RPM_UNIT_FACTORS:
            self._rpm_factor_sync_busy = True
            try:
                self._rpm_factor_spin.setValue(_RPM_UNIT_FACTORS[unit])
            finally:
                self._rpm_factor_sync_busy = False
        # When unit is "自定义", leave spinbox alone.
        self.changed.emit()

    def _on_rpm_factor_value_changed(self, value: float) -> None:
        if self._rpm_factor_sync_busy:
            self.changed.emit()
            return
        # Identify if the new value matches a known unit (within tolerance).
        match = None
        for unit, factor in _RPM_UNIT_FACTORS.items():
            if abs(value - factor) < 1e-6:
                match = unit
                break
        target = match if match is not None else _RPM_UNIT_CUSTOM
        if self._rpm_unit_combo.currentText() != target:
            self._rpm_unit_combo.blockSignals(True)
            try:
                idx = self._rpm_unit_combo.findText(target)
                if idx >= 0:
                    self._rpm_unit_combo.setCurrentIndex(idx)
            finally:
                self._rpm_unit_combo.blockSignals(False)
        self.changed.emit()

    def rpm_params(self) -> dict:
        return {"rpm_factor": float(self._rpm_factor_spin.value())}
```

Update `_refresh_signal_universe` to drive the picker (replace the old `self._rpm_combo` block):

```python
        # RPM picker shares the same universe.
        self._rpm_picker.set_available(available)
        self._rpm_picker.set_partially_available(partial)
```

Update `rpm_channel`:

```python
    def rpm_channel(self) -> str:
        sel = self._rpm_picker.selected()
        return sel[0] if sel else ""
```

Update `apply_rpm_channel`:

```python
    def apply_rpm_channel(self, ch: str) -> None:
        self._rpm_picker.set_selected((str(ch),) if ch else ())
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `pytest tests/ui/test_batch_input_panel.py -k "rpm" -v`
Expected: PASS

- [ ] **Step 4.5: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/input_panel.py tests/ui/test_batch_input_panel.py
git commit -m "feat(batch-ui): RPM single-select picker + unit-aware factor (rpm/rad·s/deg·s) (#issue-2)"
```

### Task 5: Wire `rpm_factor` from InputPanel into `BatchSheet.params()`

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py:645-669` (`get_preset`)
- Modify: `mf4_analyzer/ui/drawers/batch/method_buttons.py:80-84` (`_METHOD_FIELDS`)
- Test: `tests/ui/test_batch_method_buttons.py` (append) and `tests/ui/test_batch_smoke.py` if smoke-touched

- [ ] **Step 5.1: Write the failing tests for rpm_factor relocation**

```python
def test_param_form_no_longer_renders_rpm_factor(qtbot):
    """rpm_factor moved to the InputPanel — method_buttons must not
    render it any more (avoids two competing UI sources of the same key)."""
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("order_time")
    assert "rpm_factor" not in form.visible_field_names()
    form.set_method("order_track")
    assert "rpm_factor" not in form.visible_field_names()


def test_batch_sheet_get_preset_includes_rpm_factor_from_input_panel(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet._input_panel._rpm_unit_combo.setCurrentText("deg/s")
    sheet.apply_method("order_time")
    preset = sheet.get_preset()
    assert abs(preset.params["rpm_factor"] - 1.0 / 6.0) < 1e-9
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `pytest tests/ui/test_batch_method_buttons.py::test_param_form_no_longer_renders_rpm_factor tests/ui/test_batch_method_buttons.py::test_batch_sheet_get_preset_includes_rpm_factor_from_input_panel -v`
Expected: FAIL — `rpm_factor` is still in `_METHOD_FIELDS`.

- [ ] **Step 5.3: Drop `rpm_factor` from `_METHOD_FIELDS`**

In `mf4_analyzer/ui/drawers/batch/method_buttons.py`, change the constant:

```python
_METHOD_FIELDS: dict[str, tuple[str, ...]] = {
    "fft": ("window", "nfft"),
    "order_time": ("window", "nfft", "max_order", "order_res", "time_res"),
    "order_track": ("window", "nfft", "max_order", "target_order"),
}
```

The `_w_rpm_factor` widget can stay as a back-pocket field (it's not referenced by `_METHOD_FIELDS`, and the visibility helper hides it), so no further code change in this file. Optionally delete it for cleanliness — not required for behavior.

- [ ] **Step 5.4: Merge `InputPanel.rpm_params()` into `BatchSheet.get_preset()` AND add a preset-import round-trip**

Two writes — the export side (`get_preset`) injects `rpm_factor` from the InputPanel, and the import side (`apply_preset`) restores it BACK to the InputPanel from `preset.params`. **This pair is mandatory** — without the import side, a preset round-trip silently resets the spinbox to its default `1.0` because `_analysis_panel.apply_params` no longer holds `rpm_factor` (Step 5.3 dropped it from `_METHOD_FIELDS`).

Add the import-side helper to `mf4_analyzer/ui/drawers/batch/input_panel.py`:

```python
    def apply_rpm_factor(self, value: float) -> None:
        """Restore the RPM factor spinbox + unit combo from a preset.

        Pairs with ``rpm_params()`` so a saved preset's ``rpm_factor``
        round-trips through export → JSON → import without resetting.
        Picks the matching unit-preset label if ``value`` matches one
        within tolerance, else "自定义".
        """
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        # Sync the spinbox first; _on_rpm_factor_value_changed will then
        # pick the matching unit ("自定义" if no match) via the existing
        # bidirectional logic. Do NOT block signals — we want the
        # combo to follow.
        self._rpm_factor_spin.setValue(v)
```

Then in `mf4_analyzer/ui/drawers/batch/sheet.py`:

1. Update `get_preset` (currently `:645-669`):

```python
    def get_preset(self) -> AnalysisPreset:
        params = dict(self.params())
        params.update(self._input_panel.rpm_params())  # injects rpm_factor
        rng = self.time_range()
        if rng is not None:
            params["time_range"] = rng
        # ... rest unchanged
```

2. Update `apply_preset` (currently `:299-342`) so both branches restore `rpm_factor`. Insert this line in BOTH the `current_single` and `free_config` branches, AFTER `self.apply_params(dict(preset.params))`:

```python
            # Restore the InputPanel-owned rpm_factor field (Step 5.4).
            if "rpm_factor" in preset.params:
                self._input_panel.apply_rpm_factor(preset.params["rpm_factor"])
```

- [ ] **Step 5.4b: Round-trip test**

Append to `tests/ui/test_batch_input_panel.py`:

```python
def test_input_panel_rpm_factor_round_trips_through_preset(qtbot):
    """Export -> apply_preset -> get_preset must preserve rpm_factor.

    Regression guard for the rev-2 codex finding: Step 5.3 dropped
    rpm_factor from DynamicParamForm, so the import path needed an
    explicit ``apply_rpm_factor`` call to avoid silently resetting
    the spinbox to 1.0 on round-trip.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.apply_method("order_time")
    sheet._input_panel._rpm_unit_combo.setCurrentText("deg/s")
    exported = sheet.get_preset()
    assert abs(exported.params["rpm_factor"] - 1.0 / 6.0) < 1e-9

    # Round-trip via apply_preset on a fresh sheet
    sheet2 = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet2)
    sheet2.apply_preset(exported)
    re_exported = sheet2.get_preset()
    assert abs(re_exported.params["rpm_factor"] - 1.0 / 6.0) < 1e-9
```

- [ ] **Step 5.5: Run tests to verify they pass**

Run: `pytest tests/ui/test_batch_method_buttons.py -k "rpm_factor" tests/ui/test_batch_input_panel.py -k "rpm" -v`
Expected: PASS

- [ ] **Step 5.6: Run the full pre-existing tests once to catch regressions**

Run: `pytest tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_signal_picker.py tests/ui/test_batch_smoke.py -v`
Expected: PASS (any old test that asserted `rpm_factor` was a method-form field has just been replaced by Step 5.1's test).

- [ ] **Step 5.7: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/method_buttons.py mf4_analyzer/ui/drawers/batch/sheet.py tests/ui/test_batch_method_buttons.py
git commit -m "refactor(batch-ui): move rpm_factor from method form to InputPanel"
```

---

## Phase 4: Method-Conditional RPM Row Visibility

### Task 6: Hide RPM row for methods that don't consume RPM

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py` (add `set_method` + visibility helper)
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py:156-159` (wire `methodChanged`)
- Test: `tests/ui/test_batch_input_panel.py` (append)

Constants:

```python
_RPM_USING_METHODS = frozenset({"order_time", "order_track"})
```

- [ ] **Step 6.1: Write the failing tests for visibility**

```python
def test_input_panel_rpm_row_hidden_for_fft_method(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("fft")
    assert p._rpm_row_host.isVisibleTo(p) is False
    assert p._rpm_label_widget.isVisibleTo(p) is False


def test_input_panel_rpm_row_visible_for_order_time(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("order_time")
    assert p._rpm_row_host.isVisibleTo(p) is True
    assert p._rpm_label_widget.isVisibleTo(p) is True


def test_input_panel_rpm_row_hidden_for_fft_time(qtbot):
    """fft_time uses RPM-free spectrogram analysis (Phase 5)."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("fft_time")
    assert p._rpm_row_host.isVisibleTo(p) is False


def test_batch_sheet_method_change_drives_rpm_visibility(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.show()
    sheet.apply_method("fft")
    assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is False
    sheet.apply_method("order_time")
    assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is True
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `pytest tests/ui/test_batch_input_panel.py -k "rpm_row" tests/ui/test_batch_input_panel.py::test_batch_sheet_method_change_drives_rpm_visibility -v`
Expected: FAIL — `set_method` does not exist on `InputPanel`.

- [ ] **Step 6.3: Implement `InputPanel.set_method` + helper**

In `mf4_analyzer/ui/drawers/batch/input_panel.py`:

1. Add the constant near the other constants:

```python
_RPM_USING_METHODS = frozenset({"order_time", "order_track"})
```

2. In `InputPanel.__init__`, **after** the RPM row is added to the form via `form.addRow(self._rpm_label_widget, rpm_host)` (Step 4.3), record the row index and the form reference for later toggling, plus an initial visibility flag:

```python
        # Form reference + row index, captured for set_method's takeRow /
        # insertRow toggle (PyQt5 5.15.11 has no QFormLayout.setRowVisible —
        # verified against this repo's pinned PyQt5; revisit once we move
        # to PyQt5 5.15+ where setRowVisible exists). We MUST keep widgets
        # reparented to ``self`` while detached so they survive the layout
        # round-trip (matches the DynamicParamForm._render_for pattern).
        self._form_ref = form
        # _rpm_row_index = the QFormLayout row position of the RPM row at
        # construction time (after target-signals row is row 0). We snap
        # it from getWidgetPosition so the value is honest even if rows
        # are added in a different order in the future.
        idx, _role = form.getWidgetPosition(self._rpm_row_host)
        if idx < 0:
            raise RuntimeError("RPM row not found in form layout")
        self._rpm_row_index = idx
        self._rpm_row_visible = True  # initial state matches addRow above
```

3. Add the toggle method on `InputPanel` (alongside `_on_rpm_unit_changed` etc.):

```python
    def set_method(self, method: str) -> None:
        """Show/hide the RPM row based on whether the method consumes RPM.

        Driven by ``BatchSheet`` on ``methodChanged``. Per the
        ``conditional-visibility-init-sync-and-paired-field-children``
        lesson, ``BatchSheet.__init__`` MUST call this once after
        constructing both sub-widgets so the initial state is correct
        before ``show()``.

        Implementation note: PyQt5 5.15.11 does NOT expose
        ``QFormLayout.setRowVisible``, and a plain ``setVisible(False)``
        on the row's label + field leaves a blank gap (Qt reserves the
        row's vertical space). We therefore use ``takeRow`` /
        ``insertRow`` to fully detach and re-insert at the original
        index — matching the ``DynamicParamForm._render_for`` pattern
        already in use elsewhere in the batch UI. Detached widgets are
        reparented to ``self`` so they survive the layout round-trip
        and can be re-inserted later.
        """
        visible = method in _RPM_USING_METHODS
        if visible == self._rpm_row_visible:
            return
        if visible:
            # Re-insert at the original row position. ``insertRow`` accepts
            # the original index even if rows below have shifted up while
            # the RPM row was absent.
            self._form_ref.insertRow(
                self._rpm_row_index, self._rpm_label_widget, self._rpm_row_host,
            )
            self._rpm_label_widget.setVisible(True)
            self._rpm_row_host.setVisible(True)
        else:
            idx, _role = self._form_ref.getWidgetPosition(self._rpm_row_host)
            if idx >= 0:
                taken = self._form_ref.takeRow(idx)
                # Reparent both label and field widgets to ``self`` so they
                # persist (they're orphaned otherwise once the layout drops
                # them — Qt would eventually GC them).
                if taken.labelItem is not None:
                    lw = taken.labelItem.widget()
                    if lw is not None:
                        lw.setParent(self)
                        lw.hide()
                if taken.fieldItem is not None:
                    fw = taken.fieldItem.widget()
                    if fw is not None:
                        fw.setParent(self)
                        fw.hide()
        self._rpm_row_visible = visible
```

- [ ] **Step 6.4: Wire `methodChanged` in `BatchSheet`**

In `mf4_analyzer/ui/drawers/batch/sheet.py`, in `__init__` after the existing analysis_panel signal wiring (currently `:156-159`), add:

```python
        # Drive RPM-row visibility from the method (init-sync below).
        self._analysis_panel.methodChanged.connect(self._input_panel.set_method)
```

Then, before the existing seed call to `_recompute_pipeline_status()` (currently `:163`), add the init-sync:

```python
        # Init-sync (per conditional-visibility-init-sync lesson): seed the
        # RPM row before show() so it doesn't flash visible.
        self._input_panel.set_method(self._analysis_panel.current_method())
```

- [ ] **Step 6.5: Run tests to verify they pass**

Run: `pytest tests/ui/test_batch_input_panel.py -k "rpm_row or sheet_method_change" -v`
Expected: PASS

- [ ] **Step 6.6: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/input_panel.py mf4_analyzer/ui/drawers/batch/sheet.py tests/ui/test_batch_input_panel.py
git commit -m "feat(batch-ui): hide RPM row for methods that do not consume RPM"
```

---

## Phase 5: FFT vs Time Backend Integration (Issue 3)

### Task 7: `fft_time` enters `SUPPORTED_METHODS` + dataframe path

**Files:**
- Modify: `mf4_analyzer/batch.py` — `SUPPORTED_METHODS` (`:157`), `_run_one` (`:393-431`), append `_compute_fft_time_dataframe`
- Test: `tests/test_batch_runner.py` (append)

- [ ] **Step 7.1: Write the failing tests for `fft_time` dispatch + long-format export**

```python
def test_fft_time_method_supported(tmp_path):
    from mf4_analyzer.batch import BatchRunner
    assert "fft_time" in BatchRunner.SUPPORTED_METHODS


def test_fft_time_exports_long_format_dataframe(tmp_path):
    fd = _make_file(tmp_path, fs=1024.0)
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    preset = AnalysisPreset.free_config(
        name="batch fft_time",
        method="fft_time",
        target_signals=("sig",),
        params={
            "fs": 1024.0, "window": "hanning", "nfft": 256,
            "overlap": 0.5, "remove_mean": True,
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    import dataclasses
    preset = dataclasses.replace(preset, file_ids=(1,))
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    assert len(result.items) == 1
    df = pd.read_csv(result.items[0].data_path)
    assert list(df.columns) == ["time_s", "frequency_hz", "amplitude"]
    # Frame count must be > 1 with the synthetic 2048-sample input,
    # nfft=256, overlap=0.5 -> hop=128 -> at least 14 frames.
    assert df["time_s"].nunique() > 1
    assert df["frequency_hz"].nunique() == 256 // 2 + 1  # one-sided bins


def test_fft_time_exports_image(tmp_path):
    fd = _make_file(tmp_path, fs=1024.0)
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    preset = AnalysisPreset.free_config(
        name="batch fft_time img",
        method="fft_time",
        target_signals=("sig",),
        params={
            "fs": 1024.0, "window": "hanning", "nfft": 256,
            "overlap": 0.5, "remove_mean": True,
        },
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    import dataclasses
    preset = dataclasses.replace(preset, file_ids=(1,))
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    assert result.items[0].image_path is not None
    assert result.items[0].image_path.endswith(".png")
```

- [ ] **Step 7.2: Run tests to verify they fail**

Run: `pytest tests/test_batch_runner.py -k "fft_time" -v`
Expected: FAIL — `fft_time` not in `SUPPORTED_METHODS`.

- [ ] **Step 7.3: Add `fft_time` to `SUPPORTED_METHODS` + dispatch**

In `mf4_analyzer/batch.py`:

Replace `SUPPORTED_METHODS = {'fft', 'order_time', 'order_track'}` (line 157) with:

```python
    SUPPORTED_METHODS = {'fft', 'order_time', 'order_track', 'fft_time'}
```

Modify `_run_one` (`:393-431`) to add the `fft_time` branch *before* the `else: rpm = self._rpm_values(...)` block, since `fft_time` does not need RPM:

```python
    def _run_one(self, preset, fid, fd, signal_name, output_dir):
        sig = fd.data[signal_name].to_numpy(dtype=float, copy=False)
        time = fd.time_array
        fs = float(preset.params.get('fs') or fd.fs)
        method = preset.method
        stem = _safe_stem(f"{fd.short_name}_{signal_name}_{method}")

        if method == 'fft':
            sig, time, _ = self._apply_time_range(sig, time, preset.params)
            df = self._compute_fft_dataframe(sig, fs, preset.params)
            image_payload = ('fft', df)
        elif method == 'fft_time':
            sig, time, _ = self._apply_time_range(sig, time, preset.params)
            df = self._compute_fft_time_dataframe(
                sig, time, fs, preset.params, channel_name=signal_name,
            )
            image_payload = ('fft_time', df)
        else:
            rpm = self._rpm_values(fd, preset)
            sig, time, rpm = self._apply_time_range(sig, time, preset.params, rpm=rpm)
            if method == 'order_time':
                df = self._compute_order_time_dataframe(sig, rpm, time, fs, preset.params)
                image_payload = ('order_time', df)
            elif method == 'order_track':
                df = self._compute_order_track_dataframe(sig, rpm, fs, preset.params)
                image_payload = ('order_track', df)
            else:  # pragma: no cover
                raise ValueError(f"unsupported method: {method}")

        data_path = None
        image_path = None
        if preset.outputs.export_data:
            data_path = self._write_dataframe(
                df, output_dir / f"{stem}.{preset.outputs.data_format}"
            )
        if preset.outputs.export_image:
            image_path = self._write_image(image_payload, output_dir / f"{stem}.png")

        return BatchItemResult(
            method=method,
            file_id=fid,
            file_name=fd.filename,
            signal=signal_name,
            status='done',
            data_path=str(data_path) if data_path else None,
            image_path=str(image_path) if image_path else None,
        )
```

Append the new helper near the other `_compute_*_dataframe` methods:

```python
    @classmethod
    def _compute_fft_time_dataframe(cls, sig, time, fs, params, *, channel_name=''):
        from .signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams
        sp = SpectrogramParams(
            fs=float(fs),
            nfft=int(params.get('nfft', 1024)),
            window=str(params.get('window', 'hanning')),
            overlap=float(params.get('overlap', 0.5)),
            remove_mean=bool(params.get('remove_mean', True)),
            db_reference=float(params.get('db_reference', 1.0)),
        )
        result = SpectrogramAnalyzer.compute(
            signal=sig, time=time, params=sp, channel_name=channel_name or 'signal',
        )
        # amplitude shape: (freq_bins, frames) — long-format with time as
        # the X axis (matches order_time convention `time_s × order`).
        # Transpose so the x-major contract of _matrix_to_long_dataframe
        # holds: matrix.shape == (len(x_values), len(y_values)).
        return _matrix_to_long_dataframe(
            result.times,           # x
            result.frequencies,     # y
            result.amplitude.T,     # (freq_bins, frames) -> (frames, freq_bins)
            x_name='time_s',
            y_name='frequency_hz',
        )
```

- [ ] **Step 7.4: Run tests to verify they pass**

Run: `pytest tests/test_batch_runner.py -k "fft_time" -v`
Expected: PASS for `_method_supported` and `_exports_long_format_dataframe`. The `_exports_image` test will fail next — that drives Task 8.

- [ ] **Step 7.5: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "feat(batch): add fft_time method dispatch + long-format dataframe (#issue-3)"
```

### Task 8: `fft_time` PNG renderer + 64 MB ceiling failure

**Files:**
- Modify: `mf4_analyzer/batch.py` — `_write_image` (`:531-570`)
- Test: `tests/test_batch_runner.py` (append)

- [ ] **Step 8.1: Write failing test for ceiling overflow path**

```python
def test_fft_time_amplitude_ceiling_emits_failed_item(tmp_path, monkeypatch):
    """If the spectrogram analyzer rejects huge inputs (ValueError on
    >64 MB amplitude matrix), batch must surface that as a per-item
    failure rather than aborting the whole run."""
    fd = _make_file(tmp_path, fs=1024.0)
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.signal import spectrogram as sp_mod

    def boom(*args, **kwargs):
        raise ValueError("spectrogram amplitude matrix exceeds 64 MB")

    monkeypatch.setattr(sp_mod.SpectrogramAnalyzer, "compute", boom)

    preset = AnalysisPreset.free_config(
        name="boom",
        method="fft_time",
        target_signals=("sig",),
        params={"fs": 1024.0, "nfft": 256, "overlap": 0.5},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    import dataclasses
    preset = dataclasses.replace(preset, file_ids=(1,))
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status in ("partial", "blocked")
    assert any("64 MB" in (b or "") for b in result.blocked)
```

(`result.blocked` is a list of human-readable failure reasons populated by the existing per-item exception handler — verify by skimming `BatchRunner.run` around the `try/except` that wraps `_run_one`. If the field name differs in this codebase, adapt the assertion to match.)

- [ ] **Step 8.2: Run the test — should already PASS (TDD note inverted)**

Run: `pytest tests/test_batch_runner.py::test_fft_time_amplitude_ceiling_emits_failed_item -v`
Expected: **PASS** on the strength of Step 7.3 alone. **This test is intentionally NOT a red→green pair** — by the time Step 8.1 lands, Step 7.3 has already extended `_run_one` to dispatch `fft_time`, and the existing per-task error handler at `mf4_analyzer/batch.py:227-260` already converts the `ValueError` into a `BatchItemResult(status='blocked')` + `result.blocked` entry.

This is one of two non-TDD checkpoints in the plan (the other is Phase 7 Task 10 smoke). The Step 8.1 test is a regression guard, not a driver — its job is to lock in that ceiling overruns surface as per-task failures rather than aborting the run, so future refactors of `BatchRunner.run`'s exception handling don't silently regress this.

- [ ] **Step 8.3: Confirm per-task error funnelling is already in place**

`BatchRunner.run` (verified at `mf4_analyzer/batch.py:227-260` as of 2026-04-27) already wraps each `_run_one` call in `try/except Exception` that:
1. appends a `BatchItemResult(status='blocked', message=str(exc), ...)` to `items`
2. appends `f"{fname}:{signal_name}: {exc}"` to `blocked`
3. emits a `BatchProgressEvent(kind='task_failed', error=str(exc), ...)`

The `ValueError` raised by `SpectrogramAnalyzer.compute` (real overrun *or* the test's monkeypatched `boom`) flows through this exact path because the fft_time dispatch branch added in Step 7.3 calls `compute` from inside `_run_one`. **No additional code is needed in this step.** If the Step 8.2 test fails, the cause is likely a missing `fft_time` branch (return to Step 7.3) — NOT a need for new try/except wiring. Do not add a redundant handler.

- [ ] **Step 8.4: Extend `_write_image` for `fft_time`**

Inspecting current code: `_write_image`'s `else:` branch already pivots a long-format dataframe and renders an `imshow` heatmap with a colorbar — this is exactly what `fft_time` needs. The only addition is a label override and dB rendering option.

In `mf4_analyzer/batch.py`, modify `_write_image` (`:531-570`):

```python
    @staticmethod
    def _write_image(payload, path):
        kind, df = payload
        from matplotlib.figure import Figure
        import numpy as np

        fig = Figure(figsize=(8, 4.5), dpi=140)
        try:
            ax = fig.subplots()
            if kind == 'fft':
                ax.plot(df['frequency_hz'], df['amplitude'], lw=1.0)
                ax.set_xlabel('Frequency (Hz)')
                ax.set_ylabel('Amplitude')
            elif kind == 'order_track':
                ax.plot(df['rpm'], df['amplitude'], lw=1.0)
                ax.set_xlabel('RPM')
                ax.set_ylabel('Amplitude')
            else:
                pivot = df.pivot(
                    index=df.columns[1], columns=df.columns[0], values='amplitude'
                )
                matrix = pivot.to_numpy()
                if kind == 'fft_time':
                    # Render in dB for readability (display-only choice;
                    # the exported CSV/H5 stays linear amplitude). Match
                    # SpectrogramAnalyzer.amplitude_to_db: floor at tiny.
                    eps = np.finfo(float).tiny
                    matrix = 20.0 * np.log10(np.maximum(matrix, eps))
                    cbar_label = 'Amplitude (dB)'
                else:
                    cbar_label = 'Amplitude'
                im = ax.imshow(
                    matrix,
                    aspect='auto',
                    origin='lower',
                    extent=[
                        float(pivot.columns.min()),
                        float(pivot.columns.max()),
                        float(pivot.index.min()),
                        float(pivot.index.max()),
                    ],
                    interpolation='bilinear',
                    cmap='turbo',
                )
                ax.set_xlabel(df.columns[0])
                ax.set_ylabel(df.columns[1])
                fig.colorbar(im, ax=ax, label=cbar_label)
            ax.grid(True, alpha=0.25, ls='--')
            fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
            fig.savefig(path)
        finally:
            fig.clear()
        return path
```

- [ ] **Step 8.5: Run image export test to verify it passes**

Run: `pytest tests/test_batch_runner.py::test_fft_time_exports_image -v`
Expected: PASS

- [ ] **Step 8.6: Run the full batch_runner suite for regressions**

Run: `pytest tests/test_batch_runner.py -v`
Expected: PASS

- [ ] **Step 8.7: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "feat(batch): fft_time PNG render in dB + per-item failure isolation for ceiling"
```

---

## Phase 6: FFT vs Time UI (Issue 3)

### Task 9: Add `fft_time` button + `overlap`/`remove_mean` widgets

**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py` — `_METHOD_LABELS` (line 36-40)
- Test: `tests/ui/test_batch_method_buttons.py` (append)

- [ ] **Step 9.1: Write the failing tests for `fft_time` UI**

```python
def test_method_buttons_includes_fft_time(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup
    g = MethodButtonGroup()
    qtbot.addWidget(g)
    assert "fft_time" in g._buttons
    seen = []
    g.methodChanged.connect(seen.append)
    g.set_method("fft_time")
    assert seen[-1] == "fft_time"
    assert g.current_method() == "fft_time"


def test_param_form_fft_time_fields(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("fft_time")
    visible = form.visible_field_names()
    assert {"window", "nfft", "overlap", "remove_mean"} == visible


def test_param_form_fft_time_overlap_and_remove_mean_round_trip(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("fft_time")
    form.apply_params({"overlap": 0.75, "remove_mean": False, "nfft": 512})
    out = form.get_params()
    assert out["overlap"] == 0.75
    assert out["remove_mean"] is False
    assert out["nfft"] == 512


def test_batch_sheet_pipeline_summary_uses_friendly_fft_time_label(qtbot):
    """_METHOD_LABELS in sheet.py must include fft_time so the pipeline
    ANALYSIS strip shows 'FFT vs Time · <window>' instead of falling
    back to the raw 'fft_time' key (codex rev-2 minor finding).

    PipelineStrip API (from pipeline_strip.py): the three cards live on
    ``strip.cards: list[PipelineCard]``; index 1 is the ANALYSIS card,
    and its visible summary text is ``cards[1].summary_label.text()``.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.apply_method("fft_time")
    summary = sheet.strip.cards[1].summary_label.text()
    assert "FFT vs Time" in summary
    assert "fft_time" not in summary  # raw key must NOT leak through
```

- [ ] **Step 9.2: Run tests to verify they fail**

Run: `pytest tests/ui/test_batch_method_buttons.py -k "fft_time" -v`
Expected: FAIL — `fft_time` not in `_METHODS`.

- [ ] **Step 9.3: Add `fft_time` to `_METHODS`, `_METHOD_FIELDS`, and widgets**

In `mf4_analyzer/ui/drawers/batch/method_buttons.py`:

Modify `_METHODS`:

```python
_METHODS: tuple[tuple[str, str], ...] = (
    ("fft", "FFT"),
    ("fft_time", "FFT vs Time"),
    ("order_time", "order_time"),
    ("order_track", "order_track"),
)
```

Modify `_METHOD_FIELDS`:

```python
_METHOD_FIELDS: dict[str, tuple[str, ...]] = {
    "fft": ("window", "nfft"),
    "fft_time": ("window", "nfft", "overlap", "remove_mean"),
    "order_time": ("window", "nfft", "max_order", "order_res", "time_res"),
    "order_track": ("window", "nfft", "max_order", "target_order"),
}
```

Also update the `_METHOD_LABELS` dict in `mf4_analyzer/ui/drawers/batch/sheet.py` (line 36-40) so the pipeline-strip ANALYSIS summary renders the friendly label rather than the raw key:

```python
_METHOD_LABELS: dict[str, str] = {
    "fft": "FFT",
    "fft_time": "FFT vs Time",
    "order_time": "order_time",
    "order_track": "order_track",
}
```

First, extend the existing top-of-file imports in `mf4_analyzer/ui/drawers/batch/method_buttons.py` to include `QCheckBox` (kept at module top per project style — no inline imports):

```python
from PyQt5.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QPushButton, QSpinBox, QWidget,
)
```

Then inside `DynamicParamForm.__init__`, add the two new widgets next to the existing ones, and update the labels dict:

```python
        self._labels: dict[str, str] = {
            "window": "窗函数",
            "nfft": "NFFT",
            "max_order": "最大阶次",
            "order_res": "阶次分辨率",
            "time_res": "时间分辨率",
            "target_order": "目标阶次",
            "rpm_factor": "RPM 系数",   # legacy, kept harmless
            "overlap": "重叠率",
            "remove_mean": "去均值",
        }

        # ... (existing widgets unchanged) ...

        # overlap — QDoubleSpinBox 0..0.95
        self._w_overlap = QDoubleSpinBox(self)
        self._w_overlap.setRange(0.0, 0.95)
        self._w_overlap.setSingleStep(0.05)
        self._w_overlap.setDecimals(2)
        self._w_overlap.setValue(0.5)
        self._w_overlap.valueChanged.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["overlap"] = self._w_overlap

        # remove_mean — QCheckBox
        self._w_remove_mean = QCheckBox(self)
        self._w_remove_mean.setChecked(True)
        self._w_remove_mean.toggled.connect(lambda *_: self.paramsChanged.emit())
        self._widgets["remove_mean"] = self._w_remove_mean
```

Update `get_params` to handle the two new keys:

```python
        if "overlap" in self.visible_field_names():
            params["overlap"] = float(self._w_overlap.value())
        if "remove_mean" in self.visible_field_names():
            params["remove_mean"] = bool(self._w_remove_mean.isChecked())
```

Update `apply_params`:

```python
        if "overlap" in params:
            try:
                self._w_overlap.setValue(float(params["overlap"]))
            except (TypeError, ValueError):
                pass
        if "remove_mean" in params:
            self._w_remove_mean.setChecked(bool(params["remove_mean"]))
```

- [ ] **Step 9.4: Run tests to verify they pass**

Run: `pytest tests/ui/test_batch_method_buttons.py -v`
Expected: PASS

- [ ] **Step 9.5: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch/method_buttons.py tests/ui/test_batch_method_buttons.py
git commit -m "feat(batch-ui): add FFT vs Time method button + overlap/remove_mean widgets (#issue-3)"
```

---

## Phase 7: End-to-End Smoke Coverage

### Task 10: Smoke test exercising all three fixes together

**Files:**
- Test: `tests/ui/test_batch_smoke.py` (append)

- [ ] **Step 10.1: Add an end-to-end smoke test**

```python
def test_batch_smoke_fft_time_fixes_combined(qtbot, tmp_path):
    """Drives the dialog through: pick fft_time, RPM row hides; add a
    loaded file with multiple signals; pick first one then grow to four;
    assert the picker's sizeHint width does not scale with chip count
    (issue-1 contract) while height does grow (chips stack vertically).

    NOTE: we measure ``_signal_picker.sizeHint()`` rather than
    ``sheet.width()`` because the dialog itself is fixed by
    ``resize(1080, 760)`` and would not change regardless of picker
    behavior — that assertion would silently pass even if the bug
    returned. The picker-level sizeHint is the honest contract.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.show()

    # Pick fft_time -> RPM row hides
    sheet.apply_method("fft_time")
    assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is False

    # Add a fake loaded file with five available signals so 1- and 4-chip
    # selections are both valid.
    sheet._input_panel._file_list.add_loaded_file(
        0, "x.mf4", frozenset({"sig1", "sig2", "sig3", "sig4", "sig5"}),
    )
    qtbot.wait(20)  # let _refresh_signal_universe propagate

    # 1-chip baseline
    sheet._input_panel._signal_picker.set_selected(("sig1",))
    qtbot.wait(20)
    one_w = sheet._input_panel._signal_picker.sizeHint().width()
    one_h = sheet._input_panel._signal_picker.sizeHint().height()

    # Grow to 4 chips
    sheet._input_panel._signal_picker.set_selected(
        ("sig1", "sig2", "sig3", "sig4"),
    )
    qtbot.wait(20)
    four_w = sheet._input_panel._signal_picker.sizeHint().width()
    four_h = sheet._input_panel._signal_picker.sizeHint().height()

    # Width must NOT scale with chip count (issue-1 contract).
    assert four_w == one_w
    # Height grows with chip count, capped by the chip-scroll's
    # MAX_VISIBLE_ROWS height (Step 2.3 sets _chip_scroll.maxHeight=96).
    assert four_h >= one_h
```

- [ ] **Step 10.2: Run the smoke test**

Run: `pytest tests/ui/test_batch_smoke.py::test_batch_smoke_fft_time_fixes_combined -v`
Expected: PASS

- [ ] **Step 10.3: Run the full test suite to catch regressions**

Run: `pytest tests/ -v`
Expected: PASS for all batch-related and signal/spectrogram tests. Any pre-existing flake unrelated to these changes can be re-run individually; flag persistent failures back to the user.

- [ ] **Step 10.4: Commit**

```bash
git add tests/ui/test_batch_smoke.py
git commit -m "test(batch): end-to-end smoke combining chip layout, fft_time, RPM hide"
```

---

## Out of Scope (deferred — explicit non-goals)

- Replacing the multi-select target-signal picker's chip-row max-rows (3) with a user-configurable preference. Hard-coded for now; revisit if user reports the cap is too tight.
- Adding `db_reference` as a UI knob in the batch dialog. Currently fixed at 1.0 inside `_compute_fft_time_dataframe`. Single-shot mode exposes it; if users want batch parity, that's a follow-up.
- Per-method default `nfft` / `overlap` profiles. Defaults are static per-widget; no preset diversification yet.
- Migrating older preset JSONs that stored `rpm_factor` under different keys. The existing `params['rpm_factor']` key is preserved; if older formats existed, they need a migration spec.

---

## Self-Review Notes

This plan has been checked end-to-end:

1. **Spec coverage:** Issue 1 → Phase 1 (Tasks 1-2). Issue 2a → Phase 2 (Task 3). Issue 2b → Phase 3 (Tasks 4-5). Issue 2c → Phase 4 (Task 6). Issue 3 → Phase 5 (Tasks 7-8) + Phase 6 (Task 9). End-to-end → Phase 7 (Task 10).
2. **Placeholders:** No "TBD"/"add appropriate". Code shown in every implementation step.
3. **Type consistency:** `SignalChip`, `_ClickableFrame`, `_display_frame`, `_chip_host`, `_chip_scroll`, `_chip_layout`, `_CHIP_ROW_HEIGHT`, `_CHIP_MAX_VISIBLE_ROWS`, `_CHIP_FRAME_VPADDING`, `_rpm_picker`, `_rpm_unit_combo`, `_rpm_factor_spin`, `_rpm_factor_sync_busy`, `_rpm_row_host`, `_rpm_label_widget`, `_form_ref`, `_rpm_row_index`, `_rpm_row_visible`, `apply_rpm_factor`, `rpm_params`, `_RPM_UNIT_FACTORS`, `_RPM_UNIT_CUSTOM`, `_RPM_USING_METHODS` — names match across all task references. The `single_select` keyword on `SignalPickerPopup` matches between Phase 2 (where it's added) and Phase 3 (where InputPanel uses it).
4. **TDD discipline:** Every task starts with a failing test, runs it red, implements minimal code, runs it green, then commits.
5. **Squad routing:** When this plan is executed via the squad runbook, expected dispatch is `pyqt-ui-engineer` for Phases 1, 2, 3, 4, 6, 7 and `signal-processing-expert` for Phase 5. Files-overlap rework detection should fire only if both touch `batch.py` (Phase 5 is the sole `batch.py` toucher, so no overlap expected).

## Rev 1 corrections (post-spec-review)

This rev addresses 6 issues found by main Claude during pre-execution
review of rev 0:

1. **Phase 1 Task 2 — chip-area click handler.** Original used
   `installEventFilter(self._display_frame)` with the comment "Clicks land
   here unless they were swallowed by a chip / remove-button child first
   (Qt parent-bubbling)". This is **wrong**: `eventFilter` on a parent
   does NOT see events targeted at children. Clicks on the chip
   `QLabel` background area, the placeholder, or the scroll viewport
   would never reach the filter.
   **Fix:** introduced a small `_ClickableFrame(QFrame)` subclass with
   `mousePressEvent` → `clicked` signal, hooked to `_toggle_popup`. The
   placeholder gets `WA_TransparentForMouseEvents=True` for belt-and-
   suspenders portability. The remove × button is a `QPushButton` so it
   consumes its own press without bubbling — exactly the desired behavior.
2. **Phase 4 Task 6 Step 6.3 — RPM row visibility.** Original used
   `setVisible(False)` on label + field. In `QFormLayout` this leaves a
   blank row gap; PyQt5 5.15.11 (this repo's pinned version) does NOT
   expose `setRowVisible`.
   **Fix:** capture form ref + row index at construction time, then use
   `takeRow` / `insertRow` to fully detach and re-insert the row,
   reparenting the widgets to `self` while detached so they survive the
   round-trip. Matches the existing `DynamicParamForm._render_for`
   pattern.
3. **Phase 5 Task 7 Step 7.3 — `_compute_fft_time_dataframe` return
   shape.** Original returned `(df, freq_axis, time_axis)` but only `df`
   was consumed. **Fix:** return just the dataframe, matching the
   `_compute_order_time_dataframe` / `_compute_order_track_dataframe`
   convention.
4. **Phase 5 Task 8 Step 8.3 — dead-code fallback removed.** Original
   said "If the existing error handler does not wrap `_run_one`, add
   one" with sample code. Verified at `mf4_analyzer/batch.py:227-260`
   that the wrapper is already in place. The fallback is unreachable;
   left in, it would tempt the executor to add a redundant handler.
   **Fix:** rewrote Step 8.3 to confirm the existing handler suffices
   and to point back at Step 7.3 if the test still fails.
5. **Phase 7 Task 10 Step 10.1 — width assertion gives a false sense of
   security.** `BatchSheet.resize(1080, 760)` fixes the dialog width;
   the assertion `grown_w <= initial_w + 4` would pass on the buggy
   pre-fix code too, so a regression to the horizontal-growth chip
   layout would not be caught here.
   **Fix:** changed the smoke test to compare
   `_signal_picker.sizeHint().width()` between 1-chip and 4-chip
   states (must stay equal) and `sizeHint().height()` (must grow). The
   picker-level sizeHint is the honest contract.
6. **Phase 1 Task 1/2 Steps 1.3 / 2.3 — inline imports.** Original
   added `QLabel`, `QScrollArea`, `QSizePolicy` via inline `from PyQt5...
   import` statements scattered through `__init__`. **Fix:** all three
   moved into the file-top imports block, matching the rest of
   `mf4_analyzer/ui/drawers/batch/`.

## Rev 2 corrections (post-codex-spec-review)

Codex review of rev 1 (saved at
`docs/superpowers/reports/2026-04-27-batch-ui-fixes-and-fft-vs-time-spec-review.md`)
returned **needs revision before plan/merge**. Verdict driven by:
2 incomplete rev-1 corrections, 3 new blocking issues, 1 warning, 1
minor.

1. **Rev-1 Fix 1 incomplete — stale `eventFilter` body.** Step 2.3 still
   contained an "Extend `eventFilter` to also open the popup when
   clicking the display frame" snippet that contradicted the
   `_ClickableFrame.mousePressEvent` approach above it. **Fix:** removed
   the eventFilter snippet entirely and added an explicit "Do NOT add a
   `_display_frame` branch to `eventFilter`" instruction. The popup-only
   eventFilter body stays intact.
2. **Rev-1 Fix 6 incomplete — leftover inline imports.** Step 4.3
   carried `from PyQt5.QtWidgets import QDoubleSpinBox` and Step 9.3
   carried `from PyQt5.QtWidgets import QCheckBox`, both inline.
   **Fix:** added explicit "extend the existing top-of-file imports"
   blocks to both Steps. `input_panel.py` top imports gain
   `QDoubleSpinBox`; `method_buttons.py` top imports gain `QCheckBox`.
3. **NEW blocking — RPM factor decimals (Phase 3 Task 4).** Step 4.3
   originally used `QDoubleSpinBox.setDecimals(4)`, which rounds 1/6 to
   0.1667 and 60/(2π) to 9.5493 — failing the 1e-9 / 1e-6 tolerance
   tests. **Fix:** bumped to `setDecimals(10)` so unit-preset factors
   round-trip with ≤ 1e-10 precision loss. Spinbox max width grew from
   110 to 140 px to accommodate the extra digits.
4. **NEW blocking — chip-frame `sizeHint().height()` does NOT grow.**
   Step 2.3's `_chip_scroll.setMaximumHeight(96)` alone does not make
   `_display_frame.sizeHint().height()` honor chip count — `QScrollArea`
   does NOT propagate inner content size to its parent's sizeHint by
   default. So Step 2.1's "height grows with selection" test would
   fail and Phase 7's smoke test wouldn't catch a regression. **Fix:**
   added `_CHIP_ROW_HEIGHT`, `_CHIP_MAX_VISIBLE_ROWS`, `_CHIP_FRAME_VPADDING`
   constants and updated `_refresh_display` to call
   `_chip_scroll.setFixedHeight(min(rows, MAX_VISIBLE_ROWS) * ROW_HEIGHT)`
   so the frame's sizeHint honestly tracks chip count up to the cap and
   plateaus past it.
5. **NEW blocking — `apply_preset` does not restore `rpm_factor`.**
   Step 5.3 dropped `rpm_factor` from `_METHOD_FIELDS`, so
   `_analysis_panel.apply_params` no longer touches the spinbox. The
   InputPanel-owned spinbox would silently reset to its default (1.0)
   on every preset import, breaking round-trip via the Import preset…
   toolbar. **Fix:** added `InputPanel.apply_rpm_factor(value)` and a
   call to it in both branches of `BatchSheet.apply_preset`, plus a new
   round-trip test (`test_input_panel_rpm_factor_round_trips_through_preset`)
   in Step 5.4b.
6. **WARNING — Step 8.2 red/green inconsistency.** Original said
   "Run test to verify it FAILS" but Step 8.3 confirmed the existing
   per-task handler at `batch.py:227-260` already converts
   `ValueError` to a `partial` result, so the test would pass after
   Step 7.3 alone. **Fix:** rewrote Step 8.2 to expect PASS, with an
   explicit note that this checkpoint is a regression guard rather
   than a TDD red→green pair (one of two non-TDD checkpoints in the
   plan; the other is Phase 7 smoke). Removed redundant Step 8.4.
7. **MINOR — `_METHOD_LABELS` missing `fft_time`.** The pipeline-strip
   ANALYSIS summary builds via `_METHOD_LABELS.get(method, method)` so
   without an `fft_time` entry it would render the raw key. **Fix:**
   added the entry to Step 9.3 + a regression test
   (`test_batch_sheet_pipeline_summary_uses_friendly_fft_time_label`)
   that asserts the friendly label appears in
   `sheet.strip.cards[1].summary_label.text()`.
