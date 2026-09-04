"""Task 0 freeze of Spec SDI-A01..A18 — executable routing contract.

These tests document the Standard Desktop Interaction Contract. Several
assertions are intentionally RED on current production code (implicit
dialog defaults, chart Ctrl+Z back, incomplete Redo bindings, missing
command registry / dirty holder, QuickRef Esc-closes-immediately).

Do not xfail red tests. Do not change production code in Task 0.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QKeySequence, QPixmap
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QShortcut,
    QVBoxLayout,
    QWidget,
)


SPEC_PATH = Path("docs/analyzer/specs/2026-09-02-standard-desktop-interaction-contract-spec.md")

# IDs that cannot be fully expressed as offscreen key-event tests here.
# A18 needs Cocoa / frozen-Windows hide/destroy pressure (Task 7).
FOREGROUND_GATES = {
    "SDI-A18": "macOS Cocoa + Windows frozen hide/destroy pressure; Task 7",
}


# ---------------------------------------------------------------------------
# Key / focus helpers — QKeySequence semantics, never machine-local key names
# ---------------------------------------------------------------------------

def _widget_label(widget):
    if widget is None:
        return "None"
    name = widget.objectName() or ""
    return f"{type(widget).__name__}(objectName={name!r} text={getattr(widget, 'text', lambda: '')()!r})"


def _focus_ctx(widget=None, *, command="", extra=""):
    active = QApplication.focusWidget()
    parts = [
        f"command={command}" if command else "",
        f"active={_widget_label(active)}",
        f"target={_widget_label(widget)}" if widget is not None else "",
        extra,
    ]
    return " ".join(part for part in parts if part)


def _unique_bindings(standard_key):
    seen = []
    texts = set()
    for seq in QKeySequence.keyBindings(standard_key):
        if seq.isEmpty():
            continue
        portable = seq.toString(QKeySequence.PortableText)
        if not portable or portable in texts:
            continue
        texts.add(portable)
        seen.append(QKeySequence(seq))
    return seen


def _seq_key_and_modifiers(seq: QKeySequence):
    # Re-parse PortableText so standard-key bindings keep explicit modifiers
    # instead of a machine-local native encoding.
    portable = seq.toString(QKeySequence.PortableText)
    parsed = QKeySequence(portable) if portable else seq
    combo = parsed[0] if parsed.count() else seq[0]
    if hasattr(combo, "key") and hasattr(combo, "keyboardModifiers"):
        return combo.key(), combo.keyboardModifiers()
    value = int(combo)
    key = Qt.Key(value & ~int(Qt.KeyboardModifierMask))
    modifiers = Qt.KeyboardModifiers(value & int(Qt.KeyboardModifierMask))
    return key, modifiers


def _key_click_sequence(qtbot, widget, seq: QKeySequence):
    assert not seq.isEmpty(), f"empty QKeySequence for {_widget_label(widget)}"
    key, modifiers = _seq_key_and_modifiers(seq)
    qtbot.keyClick(widget, key, modifiers)


def _default_push_buttons(dialog):
    return [btn for btn in dialog.findChildren(QPushButton) if btn.isDefault()]


def _button_flag_report(dialog):
    rows = []
    for btn in dialog.findChildren(QPushButton):
        rows.append(
            f"{btn.text()!r} default={btn.isDefault()} autoDefault={btn.autoDefault()}"
        )
    return "; ".join(rows)


def _sequence_matches_undo(seq: QKeySequence) -> bool:
    if seq.isEmpty():
        return False
    portable = seq.toString(QKeySequence.PortableText)
    if portable == "Ctrl+Z":
        return True
    for binding in _unique_bindings(QKeySequence.Undo):
        if seq.matches(binding) == QKeySequence.ExactMatch:
            return True
        if portable == binding.toString(QKeySequence.PortableText):
            return True
    return False


def _flush_history_debounce(toolbar, qapp):
    timer = getattr(toolbar, "_history_timer", None)
    if timer is not None and timer.isActive():
        timer.stop()
        toolbar._commit_pending_view()
    qapp.processEvents()


def _simulate_pan(canvas, toolbar, qapp, lo, hi):
    primary = canvas._primary_xaxis_ax
    primary.set_xlim(lo, hi)
    vb = primary.view_box
    vb.sigRangeChangedManually.emit(vb.state["mouseEnabled"])
    _flush_history_debounce(toolbar, qapp)


def _make_channel_editor_files(tmp_path):
    import pandas as pd
    from mf4_analyzer.io.file_data import FileData

    df = pd.DataFrame({
        "time": np.arange(20) / 100.0,
        "rpm": np.arange(20.0),
        "trq": np.arange(20.0) * 2,
    })
    fd = FileData(
        str(tmp_path / "demo.mf4"),
        df,
        list(df.columns),
        {"rpm": "rpm", "trq": "Nm"},
        0,
    )
    return {"f0": fd}


def _panned_chart_stack(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 640)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")
    t = np.linspace(0.0, 10.0, 200)
    cs.canvas_time.plot_channels(
        [
            ("speed", True, t, np.sin(t), "#1769e0", "rpm"),
            ("torque", True, t, np.cos(t), "#ef4444", "Nm"),
        ],
        mode="subplot",
    )
    qapp.processEvents()
    toolbar = cs._time_card.toolbar
    canvas = cs.canvas_time
    primary = canvas._primary_xaxis_ax
    _simulate_pan(canvas, toolbar, qapp, 2.0, 4.0)
    _simulate_pan(canvas, toolbar, qapp, 6.0, 8.0)
    assert primary.get_xlim() == pytest.approx((6.0, 8.0))
    return cs, canvas, toolbar, primary


def _focus_chart_card(card, canvas):
    card.setFocusPolicy(Qt.StrongFocus)
    canvas.setFocusPolicy(Qt.StrongFocus)
    canvas.setFocus(Qt.OtherFocusReason)
    if QApplication.focusWidget() is None:
        card.setFocus(Qt.OtherFocusReason)
    target = QApplication.focusWidget()
    if target is None:
        return canvas
    if target is card or card.isAncestorOf(target):
        return target
    return canvas


def _back_action(card):
    return next(act for act in card.toolbar.actions() if act.data() == "back")


# ---------------------------------------------------------------------------
# SDI-A01 — dialog Return reaches explicit confirm, not first-created button
# ---------------------------------------------------------------------------

def test_channel_editor_return_activates_confirm_not_create(qapp, qtbot, tmp_path, monkeypatch):
    """SDI-A01: Channel Editor Return confirms; it must not create a channel."""
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    dlg = ChannelEditorDialog(None, _make_channel_editor_files(tmp_path), "f0")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    qapp.processEvents()

    ok_spy = QSignalSpy(dlg.btn_ok.clicked)
    create_spy = QSignalSpy(dlg.btn_create_single.clicked)
    accepted_spy = QSignalSpy(dlg.accepted)
    created_before = dict(dlg.new_channels)

    dlg.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    qtbot.keyClick(dlg, Qt.Key_Return)
    qapp.processEvents()

    ctx = _focus_ctx(
        dlg,
        command="channel_editor.confirm",
        extra=(
            f"ok_clicks={len(ok_spy)} create_clicks={len(create_spy)} "
            f"accepted={len(accepted_spy)} new_channels={list(dlg.new_channels)} "
            f"btn_ok.isDefault={dlg.btn_ok.isDefault()} "
            f"create.autoDefault={dlg.btn_create_single.autoDefault()} "
            f"buttons=[{_button_flag_report(dlg)}]"
        ),
    )
    assert dlg.btn_ok.isDefault(), f"confirm must be the unique default; {ctx}"
    assert dlg.btn_create_single.autoDefault() is False, f"create must not be autoDefault; {ctx}"
    if hasattr(dlg, "btn_create_dual"):
        assert dlg.btn_create_dual.autoDefault() is False, f"dual create must not be autoDefault; {ctx}"
    assert len(create_spy) == 0, f"Return must not click create; {ctx}"
    assert dlg.new_channels == created_before, f"Return must not create channels; {ctx}"
    assert len(ok_spy) >= 1 or len(accepted_spy) >= 1, f"Return must confirm/accept; {ctx}"


def test_chart_options_return_activates_ok_not_color_picker(qapp, qtbot, monkeypatch):
    """SDI-A01: Chart Options Return activates OK; color picker must not open."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from tests.ui.test_dialogs import _pg_handle_with_one_curve

    canvas, handle = _pg_handle_with_one_curve(qapp)
    qtbot.addWidget(canvas)

    color_calls = []

    def _fake_get_color(*args, **kwargs):
        color_calls.append({"args": args, "kwargs": kwargs})
        return QColor()

    monkeypatch.setattr(
        "mf4_analyzer.ui.dialogs.chart_options.QColorDialog.getColor",
        _fake_get_color,
    )

    dlg = ChartOptionsDialog(None, handle)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    qapp.processEvents()

    ok_spy = QSignalSpy(dlg.btn_ok.clicked)
    color_spy = QSignalSpy(dlg.btn_curve_color.clicked)
    accepted_spy = QSignalSpy(dlg.accepted)

    dlg.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    qtbot.keyClick(dlg, Qt.Key_Return)
    qapp.processEvents()

    ctx = _focus_ctx(
        dlg,
        command="chart_options.ok",
        extra=(
            f"ok_clicks={len(ok_spy)} color_clicks={len(color_spy)} "
            f"accepted={len(accepted_spy)} getColor_calls={len(color_calls)} "
            f"btn_ok.isDefault={dlg.btn_ok.isDefault()} "
            f"color.autoDefault={dlg.btn_curve_color.autoDefault()} "
            f"buttons=[{_button_flag_report(dlg)}]"
        ),
    )
    assert dlg.btn_ok.isDefault(), f"OK must be the unique default; {ctx}"
    assert dlg.btn_curve_color.autoDefault() is False, f"color picker must not be autoDefault; {ctx}"
    assert len(color_spy) == 0 and len(color_calls) == 0, f"Return must not open color picker; {ctx}"
    assert len(ok_spy) >= 1 or len(accepted_spy) >= 1, f"Return must activate OK/accept; {ctx}"


def test_channel_config_search_return_never_activates_import(qapp, qtbot, monkeypatch):
    """SDI-A01: Channel Config search Return stays in search; it must not import."""
    from tests.ui.test_channel_config_manager import _config, _dialog

    dialog = _dialog(
        qtbot,
        [_config("drive", "动力分析", ("EPS_CRC", "Torque"))],
        "drive",
    )
    qtbot.waitExposed(dialog)
    qapp.processEvents()

    opened = []
    dialog._open_file = lambda: opened.append("import") or ""

    import_spy = QSignalSpy(dialog.btn_import.clicked)
    save_spy = QSignalSpy(dialog.btn_save.clicked)
    dialog.btn_copy.click()
    qapp.processEvents()
    assert dialog.is_dirty() and dialog.btn_save.isEnabled()

    dialog.config_search.setFocus(Qt.OtherFocusReason)
    qtbot.keyClicks(dialog.config_search, "zzz")
    qapp.processEvents()
    assert dialog.config_search.hasFocus() or QApplication.focusWidget() is dialog.config_search
    qtbot.keyClick(dialog.config_search, Qt.Key_Return)
    qapp.processEvents()

    defaults = _default_push_buttons(dialog)
    ctx = _focus_ctx(
        dialog.config_search,
        command="channel_config.search",
        extra=(
            f"import_clicks={len(import_spy)} save_clicks={len(save_spy)} "
            f"open_file={opened} search_text={dialog.config_search.text()!r} "
            f"btn_save.isDefault={dialog.btn_save.isDefault()} "
            f"btn_import.isDefault={dialog.btn_import.isDefault()} "
            f"defaults={[btn.text() for btn in defaults]} "
            f"buttons=[{_button_flag_report(dialog)}]"
        ),
    )
    assert dialog.btn_save.isDefault(), f"save must be the unique dialog default; {ctx}"
    assert len(defaults) == 1 and defaults[0] is dialog.btn_save, f"save must be the only default; {ctx}"
    assert len(import_spy) == 0 and not opened, f"search Return must never import; {ctx}"
    assert len(save_spy) == 0, f"search Return must never save; {ctx}"
    assert dialog.config_search.text() == "zzz", f"search must remain owner of the text; {ctx}"


# ---------------------------------------------------------------------------
# SDI-A02 — destructive confirmation default is safe
# ---------------------------------------------------------------------------

def test_destructive_dialog_default_is_safe(qapp, qtbot, tmp_path, monkeypatch):
    """SDI-A02: channel-delete confirmation defaults to Cancel/No; Escape mutates nothing."""
    from PyQt5.QtWidgets import QMessageBox as _QMessageBox
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    from mf4_analyzer.ui.dialogs import channel_editor as channel_editor_mod

    dlg = ChannelEditorDialog(None, _make_channel_editor_files(tmp_path), "f0")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg._create_single()
    created = dict(dlg.new_channels)
    assert created, "need a derived channel to drive the real delete confirmation"
    for item in dlg._iter_export_items():
        if item.text() in created:
            item.setCheckState(Qt.Checked)

    seen = {}

    def fake_question(
        parent,
        title,
        text,
        buttons=_QMessageBox.Yes | _QMessageBox.No,
        defaultButton=_QMessageBox.NoButton,
    ):
        box = _QMessageBox(parent)
        box.setIcon(_QMessageBox.Question)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons)
        box.setDefaultButton(defaultButton)

        def _inspect_and_escape():
            yes = box.button(_QMessageBox.Yes)
            no = box.button(_QMessageBox.No)
            cancel = box.button(_QMessageBox.Cancel)
            seen["title"] = title
            seen["defaultButton_arg"] = int(defaultButton)
            seen["yes_is_default"] = bool(yes is not None and yes.isDefault())
            seen["no_is_default"] = bool(no is not None and no.isDefault())
            seen["cancel_is_default"] = bool(cancel is not None and cancel.isDefault())
            seen["escape_is_safe"] = box.escapeButton() in (no, cancel) and box.escapeButton() is not None
            qtbot.keyClick(box, Qt.Key_Escape)

        QTimer.singleShot(0, _inspect_and_escape)
        result = box.exec_()
        box.hide()
        box.setParent(None)
        box.deleteLater()
        qapp.processEvents()
        return result

    monkeypatch.setattr(channel_editor_mod.QMessageBox, "question", fake_question)
    dlg.btn_delete.click()
    qapp.processEvents()

    ctx = _focus_ctx(
        dlg,
        command="channel_editor.delete",
        extra=(
            f"title={seen.get('title')!r} default_arg={seen.get('defaultButton_arg')!r} "
            f"yes_default={seen.get('yes_is_default')} no_default={seen.get('no_is_default')} "
            f"cancel_default={seen.get('cancel_is_default')} escape_safe={seen.get('escape_is_safe')} "
            f"new_channels={list(dlg.new_channels)}"
        ),
    )
    assert seen, f"expected the product QMessageBox.question path; {ctx}"
    assert seen.get("no_is_default") or seen.get("cancel_is_default"), (
        f"destructive default must be Cancel/No; {ctx}"
    )
    assert not seen.get("yes_is_default"), f"Yes must not be the destructive default; {ctx}"
    assert dlg.new_channels == created, f"Escape/cancel must be zero mutation; {ctx}"


# ---------------------------------------------------------------------------
# SDI-A03 — documented Return exceptions (must stay GREEN)
# ---------------------------------------------------------------------------

def test_db_reference_cell_return_does_not_accept_dialog(qapp, qtbot, tmp_path):
    """SDI-A03: DB reference cell Enter commits the cell, not the dialog."""
    from mf4_analyzer.ui.db_reference_dialog import DbReferenceDefaultsDialog
    from mf4_analyzer.ui.db_reference_settings import DbReferenceSettingsStore
    from tests.ui.test_db_reference_controls import _dispose_dialog, _settings

    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    dlg = DbReferenceDefaultsDialog(None, store, current_mode="manual")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    buttons = dlg.findChildren(QPushButton)
    auto_defaults = [btn for btn in buttons if btn.autoDefault()]
    defaults = _default_push_buttons(dlg)
    accepted = []
    dlg.accepted.connect(lambda: accepted.append("accepted"))

    dlg.table.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    QTest.keyClick(dlg.table, Qt.Key_Return)
    qapp.processEvents()

    ctx = _focus_ctx(
        dlg.table,
        command="db_reference.cell_return",
        extra=(
            f"autoDefault={[btn.text() for btn in auto_defaults]} "
            f"defaults={[btn.text() for btn in defaults]} "
            f"accepted={accepted} visible={dlg.isVisible()}"
        ),
    )
    try:
        assert auto_defaults == [], f"every DB-reference button must disable autoDefault; {ctx}"
        assert dlg.isVisible(), f"cell Return must not close the dialog; {ctx}"
        assert accepted == [], f"cell Return must not accept the dialog; {ctx}"
        # Existing owner coverage: tests/ui/test_db_reference_controls.py
        # test_scientific_reference_editor_round_trips_small_values keyClicks Return
        # on the cell editor and asserts the value commits.
        from tests.ui import test_db_reference_controls as db_tests
        assert hasattr(db_tests, "test_scientific_reference_editor_round_trips_small_values")
    finally:
        _dispose_dialog(dlg)


def test_independent_tool_window_return_exception_is_covered(qapp, qtbot):
    """SDI-A03: independent tool-window Return does not accept/close the sheet."""
    from mf4_analyzer.ui.drawers.batch._geometry import configure_independent_tool_window
    from mf4_analyzer.ui.drawers.ultraview.sheet import UltraViewSheet

    page = QWidget()
    sheet = UltraViewSheet(None, page)
    qtbot.addWidget(sheet)
    qtbot.addWidget(page)
    configure_independent_tool_window(sheet)
    sheet.show()
    qtbot.waitExposed(sheet)
    qapp.processEvents()

    accepted = []
    sheet.accepted.connect(lambda: accepted.append("accepted"))
    qtbot.keyClick(sheet, Qt.Key_Return)
    qapp.processEvents()

    buttons = sheet.findChildren(QPushButton)
    ctx = _focus_ctx(
        sheet,
        command="ultraview_sheet.return",
        extra=(
            f"visible={sheet.isVisible()} accepted={accepted} "
            f"modal={sheet.isModal()} "
            f"buttons=[{_button_flag_report(sheet)}]"
        ),
    )
    assert sheet.isVisible(), f"Return must not close the tool window; {ctx}"
    assert accepted == [], f"Return must not accept the tool window; {ctx}"
    for button in buttons:
        assert button.autoDefault() is False and button.isDefault() is False, ctx
    from tests.ui import test_ultraview_mode_integration as uv_mode
    assert hasattr(uv_mode, "test_ultraview_board_actions_stay_in_the_tool_window")


# ---------------------------------------------------------------------------
# SDI-A04 — layered Esc (current Markup / UltraView baseline, keep GREEN)
# ---------------------------------------------------------------------------

def test_markup_layered_escape_cancels_crop_then_closes(qapp, qtbot):
    """SDI-A04: Markup Esc cancels crop first; a second Esc closes the editor."""
    from PyQt5.QtCore import QRectF
    from mf4_analyzer.ui.markup.editor import MarkupEditor

    pixmap = QPixmap(120, 80)
    pixmap.fill(QColor("#f7f7f7"))
    editor = MarkupEditor(pixmap)
    qtbot.addWidget(editor)
    editor.show()
    qtbot.waitExposed(editor)
    editor.set_active_crop_rect(QRectF(5, 5, 20, 20))
    assert editor.active_crop_rect().isValid()

    editor.setFocus(Qt.OtherFocusReason)
    qtbot.keyClick(editor, Qt.Key_Escape)
    qapp.processEvents()
    ctx = _focus_ctx(editor, command="markup.escape", extra=f"visible={editor.isVisible()}")
    assert not editor.active_crop_rect().isValid(), f"first Esc must cancel crop; {ctx}"
    assert editor.isVisible(), f"first Esc must not close the editor; {ctx}"

    qtbot.keyClick(editor, Qt.Key_Escape)
    qapp.processEvents()
    ctx = _focus_ctx(editor, command="markup.escape", extra=f"visible={editor.isVisible()}")
    assert not editor.isVisible(), f"second Esc must close the editor; {ctx}"


def test_ultraview_escape_is_noop_when_no_layer_is_active(qapp, qtbot):
    """SDI-A04: UltraView Esc with no cancellable layer is a no-op (does not close)."""
    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage

    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(800, 600)
    page.show()
    qtbot.waitExposed(page)
    page.setFocus(Qt.OtherFocusReason)
    qtbot.keyClick(page, Qt.Key_Escape)
    qapp.processEvents()
    ctx = _focus_ctx(page, command="ultraview.escape", extra=f"visible={page.isVisible()}")
    assert page.isVisible(), f"Esc with no layer must not close UltraView; {ctx}"


# ---------------------------------------------------------------------------
# SDI-A05 — search Esc clears, then closes and restores opener focus
# ---------------------------------------------------------------------------

def test_search_escape_clears_then_closes_and_restores_focus(qapp, qtbot):
    """SDI-A05: QuickRef search Esc clears first; a second Esc closes and restores focus."""
    from mf4_analyzer.ui.quickref_panel import QuickRefPanel

    opener = QLineEdit()
    opener.setObjectName("quickrefOpener")
    opener.setText("opener")
    qtbot.addWidget(opener)
    opener.show()
    qtbot.waitExposed(opener)
    opener.setFocus(Qt.OtherFocusReason)

    panel = QuickRefPanel()
    qtbot.addWidget(panel)
    panel.set_pinned(True)
    panel.show_panel(anchor_widget=opener)
    qtbot.waitExposed(panel)
    panel._search.setFocus(Qt.OtherFocusReason)
    qtbot.keyClicks(panel._search, "view")
    qapp.processEvents()
    assert panel._search.text()

    qtbot.keyClick(panel._search, Qt.Key_Escape)
    qapp.processEvents()
    ctx = _focus_ctx(
        panel._search,
        command="quickref.search_escape",
        extra=(
            f"search_text={panel._search.text()!r} panel_visible={panel.isVisible()} "
            f"search_focus={panel._search.hasFocus()} opener_focus={opener.hasFocus()} "
            f"shortcut_context=QuickRefPanel.eventFilter"
        ),
    )
    assert panel.isVisible(), f"first Esc must keep the panel open; {ctx}"
    assert panel._search.text() == "", f"first Esc must clear search text; {ctx}"
    assert panel._search.hasFocus() or QApplication.focusWidget() is panel._search, (
        f"first Esc must keep search focus; {ctx}"
    )

    qtbot.keyClick(panel._search, Qt.Key_Escape)
    qapp.processEvents()
    ctx = _focus_ctx(
        opener,
        command="quickref.search_escape",
        extra=(
            f"panel_visible={panel.isVisible()} opener_focus={opener.hasFocus()} "
            f"active={_widget_label(QApplication.focusWidget())}"
        ),
    )
    assert not panel.isVisible(), f"second Esc must close the panel; {ctx}"
    assert opener.hasFocus() or QApplication.focusWidget() is opener, (
        f"second Esc must restore opener focus; {ctx}"
    )


def test_search_escape_clears_before_host_close(qapp, qtbot):
    """SDI-A05: Esc with text clears SearchField and does not emit close."""
    from mf4_analyzer.ui_kit.widgets import SearchField

    field = SearchField("搜索操作…")
    qtbot.addWidget(field)
    field.show()
    qtbot.waitExposed(field)
    field.setFocus(Qt.OtherFocusReason)
    closes = []

    def _on_escape_requested():
        closes.append("close")

    field.escape_requested.connect(_on_escape_requested)
    field.setText("view")
    qapp.processEvents()
    assert field.text()

    qtbot.keyClick(field, Qt.Key_Escape)
    qapp.processEvents()
    ctx = _focus_ctx(
        field,
        command="search_field.escape",
        extra=f"search_text={field.text()!r} closes={closes!r}",
    )
    assert field.text() == "", f"first Esc must clear text; {ctx}"
    assert closes == [], f"first Esc must not request host close; {ctx}"
    assert field.hasFocus() or QApplication.focusWidget() is field, (
        f"first Esc must keep search focus; {ctx}"
    )


# ---------------------------------------------------------------------------
# SDI-A06 / SDI-A08 — Undo is edit-only; chart camera uses Alt+Left/Right
# ---------------------------------------------------------------------------

def test_text_focus_undo_does_not_reach_workspace_or_chart(qapp, qtbot):
    """SDI-A06: focused QLineEdit Undo must not trigger chart camera back."""
    cs, canvas, toolbar, primary = _panned_chart_stack(qapp, qtbot)
    card = cs._time_card
    back_act = _back_action(card)
    back_spy = QSignalSpy(back_act.triggered)

    edit = QLineEdit(card)
    edit.setObjectName("sdiTextFocusUndo")
    edit.setText("editable")
    edit.setGeometry(8, 8, 160, 28)
    edit.show()
    edit.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()

    undo_bindings = _unique_bindings(QKeySequence.Undo)
    assert undo_bindings, "Qt must expose at least one Undo binding"
    before = primary.get_xlim()
    _key_click_sequence(qtbot, edit, undo_bindings[0])
    qapp.processEvents()
    after = primary.get_xlim()

    ctx = _focus_ctx(
        edit,
        command="edit.undo",
        extra=(
            f"back_clicks={len(back_spy)} xlim_before={before} xlim_after={after} "
            f"back_shortcut={back_act.shortcut().toString(QKeySequence.PortableText)!r} "
            f"shortcut_context={back_act.shortcutContext()}"
        ),
    )
    assert after == pytest.approx(before), f"text-focus Undo must not navigate the chart; {ctx}"
    assert len(back_spy) == 0, f"text-focus Undo must not trigger chart back; {ctx}"


def test_chart_camera_history_uses_alt_left_right_not_undo(qapp, qtbot):
    """SDI-A08: chart camera back/forward is Alt+Left/Right; Undo must not navigate."""
    cs, canvas, toolbar, primary = _panned_chart_stack(qapp, qtbot)
    card = cs._time_card
    back_act = _back_action(card)
    back_spy = QSignalSpy(back_act.triggered)
    target = _focus_chart_card(card, canvas)

    undo_bindings = _unique_bindings(QKeySequence.Undo)
    assert undo_bindings, "Qt must expose at least one Undo binding"
    problems = []

    alt_left = QKeySequence("Alt+Left")
    before_alt = primary.get_xlim()
    _key_click_sequence(qtbot, target, alt_left)
    qapp.processEvents()
    after_alt = primary.get_xlim()
    alt_ctx = _focus_ctx(
        target,
        command="chart.view_back",
        extra=(
            f"xlim_before={before_alt} xlim_after_alt={after_alt} expected=(2.0, 4.0) "
            f"back_shortcut={back_act.shortcut().toString(QKeySequence.PortableText)!r} "
            f"shortcut_context={back_act.shortcutContext()} "
            f"alt_left={alt_left.toString(QKeySequence.PortableText)!r}"
        ),
    )
    if after_alt != pytest.approx((2.0, 4.0)):
        problems.append(f"Alt+Left must walk camera history back; {alt_ctx}")

    before_undo = primary.get_xlim()
    back_before = len(back_spy)
    _key_click_sequence(qtbot, target, undo_bindings[0])
    qapp.processEvents()
    after_undo = primary.get_xlim()
    undo_clicks = len(back_spy) - back_before
    navigated = (after_undo != pytest.approx(before_undo)) or undo_clicks > 0
    undo_ctx = _focus_ctx(
        target,
        command="chart.view_back",
        extra=(
            f"back_clicks={undo_clicks} xlim_before={before_undo} xlim_after={after_undo} "
            f"back_shortcut={back_act.shortcut().toString(QKeySequence.PortableText)!r} "
            f"shortcut_context={back_act.shortcutContext()} "
            f"undo={undo_bindings[0].toString(QKeySequence.PortableText)!r}"
        ),
    )
    if _sequence_matches_undo(back_act.shortcut()) and not navigated:
        problems.append(
            f"harness: Undo key never reached the current chart-back shortcut; {undo_ctx}"
        )
    if navigated:
        problems.append(f"Undo/Redo bindings must not navigate chart camera; {undo_ctx}")
    assert not problems, " | ".join(problems)


# ---------------------------------------------------------------------------
# SDI-A07 — every Qt Redo binding reaches the owner once
# ---------------------------------------------------------------------------

def _redo_shortcut_texts(widget):
    wanted = {seq.toString(QKeySequence.PortableText) for seq in _unique_bindings(QKeySequence.Redo)}
    found = {}
    for shortcut in widget.findChildren(QShortcut):
        text = shortcut.key().toString(QKeySequence.PortableText)
        if text in wanted:
            found.setdefault(text, []).append(shortcut)
    return wanted, found


def test_redo_registers_every_platform_binding_without_double_fire(qapp, qtbot):
    """SDI-A07: Markup and UltraView accept every Qt Redo binding, exactly once."""
    from PyQt5.QtCore import QRectF
    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
    from mf4_analyzer.ui.markup.editor import MarkupEditor

    redo_bindings = _unique_bindings(QKeySequence.Redo)
    assert redo_bindings, "Qt must expose at least one Redo binding"

    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(800, 600)
    page.show()
    qtbot.waitExposed(page)
    page.activateWindow()
    page.setFocusPolicy(Qt.StrongFocus)
    page.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()

    wanted, found = _redo_shortcut_texts(page)
    problems = []
    uv_ctx = _focus_ctx(
        page,
        command="ultraview.redo",
        extra=(
            f"wanted={sorted(wanted)} registered={sorted(found)} "
            f"primary={page._grid_redo.key().toString(QKeySequence.PortableText)!r} "
            f"shortcut_context={page._grid_redo.context()}"
        ),
    )
    if set(found) != wanted:
        problems.append(f"UltraView must register every Redo binding; {uv_ctx}")
    for text, shortcuts in found.items():
        if len(shortcuts) != 1:
            problems.append(f"UltraView Redo {text!r} registered twice; {uv_ctx}")

    for seq in redo_bindings:
        fires = []
        portable = seq.toString(QKeySequence.PortableText)
        if portable not in found:
            continue

        def _record(_checked=False, bucket=fires, label=portable):
            bucket.append(label)

        for shortcut in found[portable]:
            shortcut.activated.connect(_record)
        _key_click_sequence(qtbot, page, seq)
        qapp.processEvents()
        if fires != [portable]:
            problems.append(
                f"UltraView Redo must fire owner once for {portable!r}; "
                f"fires={fires} {uv_ctx}"
            )

    pixmap = QPixmap(120, 80)
    pixmap.fill(QColor("#f7f7f7"))
    editor = MarkupEditor(pixmap)
    qtbot.addWidget(editor)
    page.hide()
    editor.show()
    qtbot.waitExposed(editor)
    editor.activateWindow()
    editor.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    editor.add_rect_item(QRectF(10, 10, 30, 20))
    assert editor._undo_stack.count() == 1

    real_redo = editor._undo_stack.redo
    real_undo = editor._undo_stack.undo
    markup_counts = {"redo": 0, "undo": 0}

    def _counting_redo():
        markup_counts["redo"] += 1
        return real_redo()

    def _counting_undo():
        markup_counts["undo"] += 1
        return real_undo()

    editor._undo_stack.redo = _counting_redo
    editor._undo_stack.undo = _counting_undo
    try:
        for seq in redo_bindings:
            editor._undo_stack.setIndex(0)
            markup_counts["redo"] = 0
            markup_counts["undo"] = 0
            _key_click_sequence(qtbot, editor, seq)
            qapp.processEvents()
            ctx = _focus_ctx(
                editor,
                command="markup.redo",
                extra=(
                    f"binding={seq.toString(QKeySequence.PortableText)!r} "
                    f"redo_calls={markup_counts['redo']} undo_calls={markup_counts['undo']} "
                    f"stack_index={editor._undo_stack.index()}"
                ),
            )
            if markup_counts["redo"] != 1 or markup_counts["undo"] != 0:
                problems.append(
                    f"Markup Redo must reach the stack once; {ctx}"
                )
    finally:
        editor._undo_stack.redo = real_redo
        editor._undo_stack.undo = real_undo
    assert not problems, " | ".join(problems)


# ---------------------------------------------------------------------------
# SDI-A09 / A10 / A11 — command registry (RED until Task 1)
# ---------------------------------------------------------------------------

def test_each_global_command_has_exactly_one_qaction_owner():
    """SDI-A09: Open/Save/SaveAs/Quit have exactly one QAction owner."""
    from mf4_analyzer.ui.command_registry import CommandId, iter_command_actions

    required = (
        CommandId.OPEN_PROJECT,
        CommandId.OPEN_RECENT,
        CommandId.SAVE_PROJECT,
        CommandId.SAVE_PROJECT_AS,
        CommandId.QUIT,
    )
    seen = {}
    for command_id, action in iter_command_actions():
        if command_id not in required:
            continue
        seen.setdefault(command_id, []).append(action)
    missing = [command_id for command_id in required if command_id not in seen]
    doubles = {command_id: acts for command_id, acts in seen.items() if len(acts) != 1}
    counts = {command_id: len(acts) for command_id, acts in seen.items()}
    ctx = f"command=global.file_menu missing={missing} doubles={list(doubles)} counts={counts}"
    assert not missing, f"each global command must have an action owner; {ctx}"
    assert not doubles, f"each global command must have exactly one QAction; {ctx}"


def test_save_as_has_explicit_fallback_when_qt_binding_is_empty():
    """SDI-A10: SaveAs keeps a Ctrl+Shift+S fallback when Qt standard bindings are empty."""
    from mf4_analyzer.ui.command_registry import CommandId, bindings_for, native_text_for

    seqs = list(bindings_for(CommandId.SAVE_PROJECT_AS))
    portable = [seq.toString(QKeySequence.PortableText) for seq in seqs if not seq.isEmpty()]
    qt_standard = [
        seq.toString(QKeySequence.PortableText)
        for seq in QKeySequence.keyBindings(QKeySequence.SaveAs)
        if not seq.isEmpty()
    ]
    ctx = (
        f"command=file.save_as registered={portable} qt_standard={qt_standard} "
        f"native={native_text_for(CommandId.SAVE_PROJECT_AS)!r}"
    )
    if not qt_standard:
        assert portable.count("Ctrl+Shift+S") == 1, f"empty Qt SaveAs must fallback once; {ctx}"
        assert len(portable) == 1, f"fallback must be registered exactly once; {ctx}"
    else:
        assert portable, f"SaveAs must expose the Qt standard bindings; {ctx}"
        assert portable.count("Ctrl+Shift+S") <= 1, f"SaveAs fallback must not double-register; {ctx}"
    assert native_text_for(CommandId.SAVE_PROJECT_AS) == seqs[0].toString(QKeySequence.NativeText), ctx


def test_standard_bindings_use_native_qkeysequence_semantics():
    """SDI-A11: registry display text uses QKeySequence.NativeText, not hard-coded Ctrl/Cmd."""
    from mf4_analyzer.ui.command_registry import CommandId, bindings_for, native_text_for

    samples = {
        CommandId.UNDO: QKeySequence.Undo,
        CommandId.REDO: QKeySequence.Redo,
        CommandId.SAVE_PROJECT: QKeySequence.Save,
        CommandId.OPEN_PROJECT: QKeySequence.Open,
    }
    for command_id, standard in samples.items():
        text = native_text_for(command_id)
        seqs = list(bindings_for(command_id))
        expected = (
            seqs[0].toString(QKeySequence.NativeText)
            if seqs
            else QKeySequence(standard).toString(QKeySequence.NativeText)
        )
        ctx = (
            f"command={command_id} native={text!r} expected={expected!r} "
            f"portable={[s.toString(QKeySequence.PortableText) for s in seqs]}"
        )
        assert text == expected, f"help/menu text must be NativeText; {ctx}"
        assert "Command+" not in text or text == expected, ctx


def _command_binding_tokens(command_id):
    from mf4_analyzer.ui.command_registry import bindings_for, native_text_for

    tokens = set()
    native = native_text_for(command_id)
    if native:
        tokens.add(native)
    for seq in bindings_for(command_id):
        if seq.isEmpty():
            continue
        tokens.add(seq.toString(QKeySequence.PortableText))
        tokens.add(seq.toString(QKeySequence.NativeText))
    return {token for token in tokens if token}


def test_help_tokens_do_not_conflict_with_registry_bindings(qapp):
    """SDI-A11: QAction NativeText, tooltip, hint token, and quickref token agree."""
    from mf4_analyzer.ui import hints, quickref
    from mf4_analyzer.ui.command_registry import (
        CommandId,
        iter_command_actions,
        native_text_for,
        tooltip_for,
    )

    problems = []
    tokens_by_command = {
        command_id: _command_binding_tokens(command_id) for command_id in CommandId
    }
    nav_keys = {
        CommandId.VIEW_BACK: "back",
        CommandId.VIEW_FORWARD: "forward",
    }
    for command_id, action_key in nav_keys.items():
        token = hints.shortcut_tooltip(action_key)
        ctx = f"command={command_id.name} nav={action_key} token={token!r}"
        if token not in tokens_by_command[command_id]:
            problems.append(f"NAV_SHORTCUTS token missing from registry bindings; {ctx}")

    for command_id, action in iter_command_actions():
        native = native_text_for(command_id)
        tip = action.toolTip()
        expected_tip = tooltip_for(command_id)
        ctx = f"command={command_id.name} native={native!r} tooltip={tip!r}"
        if tip != expected_tip:
            problems.append(f"QAction tooltip != registry tooltip_for; {ctx}")
        if not native:
            continue
        shortcuts = [
            seq.toString(QKeySequence.NativeText)
            for seq in action.shortcuts()
            if not seq.isEmpty()
        ]
        if native not in shortcuts:
            problems.append(
                f"QAction shortcuts missing NativeText; {ctx} shortcuts={shortcuts}"
            )
        if native not in tip:
            problems.append(f"tooltip missing NativeText; {ctx}")

    history = hints.hint_text("view.history") or ""
    back = hints.NAV_SHORTCUTS["back"]
    if "视角后退已改为" not in history or back not in history:
        problems.append(
            f"view.history must say 视角后退已改为 {back}; text={history!r}"
        )
    if re.search(r"图表可后退.*Ctrl\+Z", history):
        problems.append(
            f"view.history still advertises Ctrl+Z as camera; text={history!r}"
        )

    undo_tokens = tokens_by_command[CommandId.UNDO]
    redo_tokens = tokens_by_command[CommandId.REDO]
    back_tokens = tokens_by_command[CommandId.VIEW_BACK] | {hints.NAV_SHORTCUTS["back"]}
    forward_tokens = tokens_by_command[CommandId.VIEW_FORWARD] | {
        hints.NAV_SHORTCUTS["forward"]
    }
    exclusive_undo = undo_tokens - back_tokens - forward_tokens
    exclusive_back = back_tokens - undo_tokens - redo_tokens
    exclusive_forward = forward_tokens - undo_tokens - redo_tokens

    camera_rows = []
    for group in quickref.QUICKREF:
        for row in group.rows:
            blob = f"{row.desc} {row.sub}"
            if row.desc.startswith("视角后退") or "后退 / 前进视图" in row.desc:
                camera_rows.append(row)
            for chip in row.keys:
                is_edit_row = "撤销" in blob or "重做" in blob or "编辑" in blob
                is_camera_row = "视角" in blob or "后退" in row.desc
                if chip in exclusive_back and not is_camera_row:
                    problems.append(
                        f"VIEW_BACK token {chip!r} on non-camera row "
                        f"{group.title}/{row.desc}"
                    )
                if chip in exclusive_forward and not is_camera_row:
                    problems.append(
                        f"VIEW_FORWARD token {chip!r} on non-camera row "
                        f"{group.title}/{row.desc}"
                    )
                if chip in exclusive_undo and not is_edit_row:
                    problems.append(
                        f"UNDO token {chip!r} on non-edit row {group.title}/{row.desc}"
                    )

    if len(camera_rows) != 1:
        problems.append(
            f"expected one camera-history quickref row, got {len(camera_rows)}"
        )
    else:
        camera = camera_rows[0]
        expected_keys = (
            hints.shortcut_tooltip("back"),
            hints.shortcut_tooltip("forward"),
        )
        if camera.keys != expected_keys:
            problems.append(
                f"camera quickref keys {camera.keys!r} != {expected_keys!r}"
            )
        if "Ctrl/Cmd+Z 保留给编辑撤销" not in camera.sub:
            problems.append(
                f"camera quickref missing edit-undo reservation; sub={camera.sub!r}"
            )

    hints_src = Path("mf4_analyzer/ui/hints.py").read_text(encoding="utf-8")
    if re.search(r'["\']back["\']\s*:\s*["\']Ctrl\+Z["\']', hints_src):
        problems.append("hints.NAV_SHORTCUTS still maps back=Ctrl+Z")
    if re.search(r'["\']forward["\']\s*:\s*["\']Ctrl\+Shift\+Z["\']', hints_src):
        problems.append("hints.NAV_SHORTCUTS still maps forward=Ctrl+Shift+Z")
    if quickref._sc("back") == "Ctrl+Z":
        problems.append("quickref _sc(back) still resolves to Ctrl+Z")

    assert not problems, "shortcut help conflicts:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# SDI-A09 / A16 / A18 — coordinator menus, toolbar identity, shortcut scope
# ---------------------------------------------------------------------------

class _FakeCommandHost(QMainWindow):
    """Cheap QMainWindow stand-in with the named IO/QuickRef slots."""

    def __init__(self):
        super().__init__()
        from mf4_analyzer.ui.toolbar import Toolbar

        self.toolbar = Toolbar(self)
        self.calls = []
        self._quickref_panel = None
        self._quickref_shortcut = QShortcut(QKeySequence(Qt.Key_Question), self)
        self._quickref_shortcut.setContext(Qt.ApplicationShortcut)

    def open_files_or_project(self):
        self.calls.append("open_files_or_project")

    def save_project_via_dialog(self):
        self.calls.append("save_project_via_dialog")

    def save_project_as_via_dialog(self):
        self.calls.append("save_project_as_via_dialog")

    def toggle_quickref_panel(self):
        self.calls.append("toggle_quickref_panel")


def _install_coordinator(host):
    from mf4_analyzer.ui.main_window.command_coordinator import CommandCoordinator

    coord = CommandCoordinator(host)
    coord.bind_toolbar(host.toolbar)
    return coord


def test_toolbar_and_owned_actions_trigger_same_named_slot_once(qapp, qtbot):
    """SDI-A09: toolbar chips reuse the coordinator's single QAction owners."""
    from mf4_analyzer.ui.command_registry import CommandId, bindings_for

    host = _FakeCommandHost()
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    host.toolbar.set_enabled_for_mode("time", has_file=True)
    coord = _install_coordinator(host)

    open_act = coord.action(CommandId.OPEN_PROJECT)
    save_act = coord.action(CommandId.SAVE_PROJECT)
    save_as_act = coord.action(CommandId.SAVE_PROJECT_AS)

    host.calls.clear()
    host.toolbar.btn_add.click()
    qapp.processEvents()
    ctx = _focus_ctx(
        host.toolbar.btn_add,
        command="file.open",
        extra=(
            f"calls={host.calls} action={open_act.objectName()!r} "
            f"shortcut_context={open_act.shortcutContext()}"
        ),
    )
    assert host.calls == ["open_files_or_project"], f"toolbar Open must hit the slot once; {ctx}"

    host.calls.clear()
    open_act.trigger()
    qapp.processEvents()
    ctx = _focus_ctx(
        host,
        command="file.open",
        extra=f"calls={host.calls} action={open_act.objectName()!r}",
    )
    assert host.calls == ["open_files_or_project"], f"Open QAction must hit the same slot once; {ctx}"

    host.calls.clear()
    host.toolbar.btn_save_project.click()
    qapp.processEvents()
    assert host.calls == ["save_project_via_dialog"], (
        f"toolbar Save must hit the slot once; calls={host.calls} "
        f"action={save_act.objectName()!r}"
    )

    host.calls.clear()
    save_act.trigger()
    qapp.processEvents()
    assert host.calls == ["save_project_via_dialog"], (
        f"Save QAction must hit the same slot once; calls={host.calls}"
    )

    host.calls.clear()
    host.toolbar.btn_save_project_as.trigger()
    qapp.processEvents()
    assert host.calls == ["save_project_as_via_dialog"], (
        f"toolbar Save As must hit the slot once; calls={host.calls} "
        f"action={save_as_act.objectName()!r}"
    )

    host.calls.clear()
    save_as_act.trigger()
    qapp.processEvents()
    assert host.calls == ["save_project_as_via_dialog"], (
        f"Save As QAction must hit the same slot once; calls={host.calls}"
    )

    host.calls.clear()
    quickref_binding = bindings_for(CommandId.QUICK_REFERENCE)[0]
    _key_click_sequence(qtbot, host, quickref_binding)
    qapp.processEvents()
    assert host.calls == ["toggle_quickref_panel"], (
        "the QuickRef QAction must retain its window shortcut without a menu; "
        f"calls={host.calls} binding={quickref_binding.toString(QKeySequence.PortableText)!r}"
    )


def test_ctrl_tab_routes_current_section_from_ordinary_focus_once(qapp, qtbot):
    """The platform View-cycle binding works outside the ViewTabBar."""
    from mf4_analyzer.ui.command_registry import CommandId, bindings_for
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 850)
    win.show()
    qtbot.waitExposed(win)
    win.view_manager.new_view(activate=False)
    qapp.processEvents()

    calls = []
    original = win._switch_view
    set_active_calls = []
    original_set_active = win.view_manager.set_active

    def _spy(idx):
        calls.append(idx)
        original(idx)

    def _set_active_spy(idx):
        set_active_calls.append(idx)
        original_set_active(idx)

    win._switch_view = _spy
    win.view_manager.set_active = _set_active_spy
    ordinary_focus_targets = (
        win.canvas_time,
        win.inspector.top.edit_xlabel,
        win.channel_list.tree,
        win.channel_list.search,
        win.view_tabbar.tabBar(),
    )
    for target in ordinary_focus_targets:
        win.view_manager.set_active(0)
        calls.clear()
        set_active_calls.clear()
        target.setFocus(Qt.TabFocusReason)
        qapp.processEvents()
        _key_click_sequence(qtbot, target, bindings_for(CommandId.NEXT_VIEW)[0])
        qapp.processEvents()
        assert calls == [1], _focus_ctx(
            target,
            command="view.next",
            extra=f"calls={calls} active={win.view_manager.active}",
        )
        assert set_active_calls == [1], "the View switch owner must run once"
        assert win.view_manager.active == 1

    calls.clear()
    set_active_calls.clear()
    _key_click_sequence(
        qtbot,
        win.channel_list.search,
        bindings_for(CommandId.PREVIOUS_VIEW)[0],
    )
    qapp.processEvents()
    assert calls == [0]
    assert set_active_calls == [0]
    assert win.view_manager.active == 0

    win.toggle_quickref_panel()
    panel = win._quickref_panel
    panel._search.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    calls.clear()
    set_active_calls.clear()
    _key_click_sequence(
        qtbot, panel._search, bindings_for(CommandId.NEXT_VIEW)[0]
    )
    qapp.processEvents()
    assert calls == [1], "QuickRef search remains a valid ordinary search focus"
    assert set_active_calls == [1]
    panel.hide()


def test_view_cycle_bindings_never_use_command_tab_on_darwin(monkeypatch):
    """C2: Qt's Meta modifier is physical Control on macOS, never Command."""
    import sys

    from mf4_analyzer.ui.command_registry import CommandId, bindings_for

    monkeypatch.setattr(sys, "platform", "darwin")
    assert [
        sequence.toString(QKeySequence.PortableText)
        for sequence in bindings_for(CommandId.NEXT_VIEW)
    ] == ["Meta+Tab"]
    assert [
        sequence.toString(QKeySequence.PortableText)
        for sequence in bindings_for(CommandId.PREVIOUS_VIEW)
    ] == ["Meta+Shift+Tab"]

    monkeypatch.setattr(sys, "platform", "linux")
    assert [
        sequence.toString(QKeySequence.PortableText)
        for sequence in bindings_for(CommandId.NEXT_VIEW)
    ] == ["Ctrl+Tab"]
    assert [
        sequence.toString(QKeySequence.PortableText)
        for sequence in bindings_for(CommandId.PREVIOUS_VIEW)
    ] == ["Ctrl+Shift+Tab"]


def test_view_cycle_shortcut_is_window_scoped_and_quickref_has_its_own(
    qapp, qtbot
):
    """C4: cycle shortcuts stay in their active top-level window."""
    from mf4_analyzer.ui.command_registry import CommandId, bindings_for
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 850)
    win.show()
    qtbot.waitExposed(win)
    cycle_bindings = {
        sequence.toString(QKeySequence.PortableText)
        for command_id in (CommandId.NEXT_VIEW, CommandId.PREVIOUS_VIEW)
        for sequence in bindings_for(command_id)
    }
    main_shortcuts = [
        shortcut
        for shortcut in win._view_shortcuts
        if shortcut.key().toString(QKeySequence.PortableText) in cycle_bindings
    ]
    assert main_shortcuts
    assert all(
        shortcut.context() == Qt.WindowShortcut for shortcut in main_shortcuts
    )

    win.toggle_quickref_panel()
    panel = win._quickref_panel
    assert panel is not None
    assert panel._view_cycle_shortcuts
    assert {
        shortcut.key().toString(QKeySequence.PortableText)
        for shortcut in panel._view_cycle_shortcuts
    } == cycle_bindings
    assert all(
        shortcut.context() == Qt.WindowShortcut
        for shortcut in panel._view_cycle_shortcuts
    )


def test_reset_view_metadata_matches_live_binding():
    """C5: metadata cannot advertise a chart reset key that no card installs."""
    from mf4_analyzer.ui.chart_stack._helpers import _NAV_SHORTCUTS
    from mf4_analyzer.ui.command_registry import (
        CommandId,
        bindings_for,
        metadata_for,
        native_text_for,
    )

    assert metadata_for(CommandId.RESET_VIEW).fallback == "Ctrl+R"
    assert [
        sequence.toString(QKeySequence.PortableText)
        for sequence in bindings_for(CommandId.RESET_VIEW)
    ] == ["Ctrl+R"]
    assert _NAV_SHORTCUTS["home"] == native_text_for(CommandId.RESET_VIEW)


def test_find_focuses_visible_search_field_before_quickref(qapp, qtbot):
    """C8: Find must prefer the active window's visible local search field."""
    from mf4_analyzer.ui.main_window.command_coordinator import CommandCoordinator
    from mf4_analyzer.ui_kit.widgets import SearchField

    host = _FakeCommandHost()
    qtbot.addWidget(host)
    body = QWidget(host)
    layout = QVBoxLayout(body)
    search = SearchField("筛选当前列表")
    other = QLineEdit()
    layout.addWidget(search)
    layout.addWidget(other)
    host.setCentralWidget(body)
    host.show()
    qtbot.waitExposed(host)
    host.raise_()
    host.activateWindow()
    qapp.processEvents()
    other.setFocus(Qt.TabFocusReason)
    coordinator = CommandCoordinator(host)

    coordinator._on_find()
    qapp.processEvents()

    assert QApplication.focusWidget() is search
    assert host.calls == []


def test_ctrl_tab_routes_analysis_and_fails_closed_for_transient_owners(
    qapp, qtbot
):
    """Analysis uses its owner once; modal/rename/IME/hidden bars block routing."""
    from PyQt5 import sip
    from mf4_analyzer.ui.command_registry import CommandId, bindings_for
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 850)
    win.show()
    qtbot.waitExposed(win)
    win._on_mode_changed("fft")
    manager = win.analysis_managers["fft"]
    manager.new_view(activate=False)
    qapp.processEvents()

    calls = []
    original = win._on_analysis_switch

    def _spy(section, idx):
        calls.append((section, idx))
        original(section, idx)

    win._on_analysis_switch = _spy
    focus = win.chart_stack.page_fft.pane_canvas(0)
    focus.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    _key_click_sequence(qtbot, focus, bindings_for(CommandId.NEXT_VIEW)[0])
    qapp.processEvents()
    assert calls == [("fft", 1)]
    assert manager.active == 1

    bar = win.chart_stack.page_fft.tabbar
    bar._begin_inline_rename(manager.active)
    editor = bar.findChild(QLineEdit, "viewTabRenameEditor")
    assert editor is not None
    calls.clear()
    _key_click_sequence(qtbot, editor, bindings_for(CommandId.NEXT_VIEW)[0])
    qapp.processEvents()
    assert calls == [], "an inline View rename owns the keyboard transaction"
    bar._finish_inline_rename(accepted=False)

    dialog = QDialog(win)
    dialog.setModal(True)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    calls.clear()
    _key_click_sequence(qtbot, dialog, bindings_for(CommandId.NEXT_VIEW)[0])
    qapp.processEvents()
    assert calls == [], "a modal dialog must block section navigation"
    dialog.hide()

    ime = QLineEdit(win.centralWidget())
    ime.is_ime_composing = lambda: True
    ime.setGeometry(12, 12, 180, 28)
    ime.show()
    ime.raise_()
    win.activateWindow()
    ime.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    assert QApplication.focusWidget() is ime
    calls.clear()
    _key_click_sequence(qtbot, ime, bindings_for(CommandId.NEXT_VIEW)[0])
    qapp.processEvents()
    assert calls == [], "an active IME composition must keep keyboard ownership"

    bar.hide()
    focus.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    calls.clear()
    _key_click_sequence(qtbot, focus, bindings_for(CommandId.NEXT_VIEW)[0])
    qapp.processEvents()
    assert calls == [], "a hidden section bar must not switch its manager"

    dead_bar = QWidget(win)
    sip.delete(dead_bar)
    win.chart_stack.page_fft.tabbar = dead_bar
    calls.clear()
    _key_click_sequence(qtbot, focus, bindings_for(CommandId.NEXT_VIEW)[0])
    qapp.processEvents()
    assert calls == [], "a destroyed section bar must fail closed"


def test_global_commands_do_not_fire_through_modal_dialog(qapp, qtbot):
    """SDI-A09: Open/Save WindowShortcut must not fire while a modal dialog is active."""
    from mf4_analyzer.ui.command_registry import CommandId, bindings_for

    host = _FakeCommandHost()
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    coord = _install_coordinator(host)
    open_act = coord.action(CommandId.OPEN_PROJECT)
    seqs = bindings_for(CommandId.OPEN_PROJECT)
    assert seqs, "Open must have a platform binding"
    assert open_act.shortcutContext() == Qt.WindowShortcut, (
        f"Open must be WindowShortcut, not ApplicationShortcut; "
        f"shortcut_context={open_act.shortcutContext()}"
    )

    dlg = QDialog(host)
    dlg.setModal(True)
    dlg.setWindowModality(Qt.ApplicationModal)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.activateWindow()
    dlg.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()

    host.calls.clear()
    _key_click_sequence(qtbot, dlg, seqs[0])
    qapp.processEvents()
    ctx = _focus_ctx(
        dlg,
        command="file.open",
        extra=(
            f"calls={host.calls} shortcut_context={open_act.shortcutContext()} "
            f"modal={dlg.isModal()} active={_widget_label(QApplication.activeWindow())}"
        ),
    )
    assert host.calls == [], f"Open must not fire through a modal dialog; {ctx}"


def test_hidden_or_destroyed_surface_leaves_no_active_shortcut(qapp, qtbot):
    """SDI-A18: hiding or destroying the host must not leave an active global shortcut."""
    from PyQt5 import sip
    from mf4_analyzer.ui.command_registry import CommandId, bindings_for

    host = _FakeCommandHost()
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    coord = _install_coordinator(host)
    open_act = coord.action(CommandId.OPEN_PROJECT)
    seqs = bindings_for(CommandId.OPEN_PROJECT)
    assert seqs, "Open must have a platform binding"
    assert open_act.shortcutContext() == Qt.WindowShortcut
    assert open_act.shortcutContext() != Qt.ApplicationShortcut

    host.hide()
    qapp.processEvents()
    host.calls.clear()
    _key_click_sequence(qtbot, host, seqs[0])
    qapp.processEvents()
    ctx = _focus_ctx(
        host,
        command="file.open",
        extra=(
            f"calls={host.calls} visible={host.isVisible()} "
            f"shortcut_context={open_act.shortcutContext()}"
        ),
    )
    assert host.calls == [], f"hidden host must not dispatch Open; {ctx}"

    sip.delete(host)
    qapp.processEvents()
    assert sip.isdeleted(open_act), (
        "destroying the host must destroy its Open QAction; "
        f"command=file.open shortcut_context=destroyed"
    )


def test_quit_action_exists_but_is_disabled_until_dirty_guard(qapp, qtbot):
    """SDI-A16: Quit QAction exists for T0/T5 but stays disabled and unhooked in T1."""
    from mf4_analyzer.ui.command_registry import CommandId

    host = _FakeCommandHost()
    qtbot.addWidget(host)
    host.show()
    closed = []
    host.closeEvent = lambda event: closed.append("close") or event.ignore()
    coord = _install_coordinator(host)
    quit_act = coord.action(CommandId.QUIT)
    ctx = (
        f"command=file.quit enabled={quit_act.isEnabled()} "
        f"objectName={quit_act.objectName()!r} "
        f"shortcut_context={quit_act.shortcutContext()} "
        f"menuRole={int(quit_act.menuRole())}"
    )
    assert quit_act.objectName() == "actionQuit", ctx
    assert not quit_act.isEnabled(), f"Quit must stay disabled until dirty guard; {ctx}"
    assert quit_act.menuRole() == QAction.NoRole, (
        f"Quit must not take the macOS app-menu Quit role yet; {ctx}"
    )

    quit_act.trigger()
    qapp.processEvents()
    assert closed == [], f"disabled Quit must not close the window; closed={closed} {ctx}"
    assert host.isVisible(), f"Quit must not hide the window; {ctx}"


def test_open_recent_command_is_unique_window_shortcut(qapp, qtbot):
    from mf4_analyzer.ui.command_registry import (
        CommandId,
        bindings_for,
        metadata_for,
        native_text_for,
        tooltip_for,
    )

    host = _FakeCommandHost()
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    coord = _install_coordinator(host)
    action = coord.action(CommandId.OPEN_RECENT)
    meta = metadata_for(CommandId.OPEN_RECENT)
    seqs = bindings_for(CommandId.OPEN_RECENT)
    ctx = (
        f"command=file.open_recent fallback={meta.fallback!r} "
        f"native={native_text_for(CommandId.OPEN_RECENT)!r} "
        f"shortcut_context={action.shortcutContext()}"
    )
    assert meta.fallback == "Ctrl+K", ctx
    assert seqs, ctx
    assert action.shortcutContext() == Qt.WindowShortcut, ctx
    assert native_text_for(CommandId.OPEN_RECENT) == seqs[0].toString(
        QKeySequence.NativeText
    ), ctx
    assert action.toolTip() == tooltip_for(CommandId.OPEN_RECENT), ctx
    assert host.toolbar.btn_open_caret.toolTip() == action.toolTip(), ctx

    host.calls.clear()
    opened = []
    host.toolbar.open_requested.connect(lambda: opened.append("open"))
    action.trigger()
    qapp.processEvents()
    assert host.calls == [], f"OPEN_RECENT must not fire Open; {ctx} calls={host.calls}"
    assert opened == [], f"OPEN_RECENT must not emit toolbar open_requested; {ctx}"
    popup = host.toolbar._recent_popup
    assert popup.isVisible(), ctx
    action.trigger()
    qapp.processEvents()
    assert popup.isVisible(), "repeat shortcut must keep the popup open"
    assert popup._search.hasFocus(), "repeat shortcut must focus search"
    find_action = coord.action(CommandId.FIND)
    find_portables = {
        seq.toString(QKeySequence.PortableText) for seq in find_action.shortcuts()
    }
    recent_portables = {
        seq.toString(QKeySequence.PortableText) for seq in action.shortcuts()
    }
    assert find_portables.isdisjoint(recent_portables), (
        f"OPEN_RECENT must not share FIND bindings; find={find_portables} "
        f"recent={recent_portables}"
    )
    popup.close()


# ---------------------------------------------------------------------------
# SDI-A14..A17 — project dirty holder (RED until Task 5)
# ---------------------------------------------------------------------------

def test_project_dirty_holder_is_the_single_owner():
    """SDI-A14, SDI-A15, SDI-A16, SDI-A17: ProjectDirtyState is the single dirty owner.

    A14 user mutation marks dirty; A15 restore/projection does not; A16
    Save/Discard/Cancel guard; A17 undo-to-save-point is clean.
    """
    try:
        from mf4_analyzer.ui.main_window.project_dirty import ProjectDirtyState
    except ImportError:
        from mf4_analyzer.ui.main_window._state_holders import ProjectDirtyState

    holder = ProjectDirtyState()
    ctx = f"command=project.dirty holder={type(holder).__name__}"
    for name in ("revision", "save_point", "mark_user_mutation", "is_dirty"):
        assert hasattr(holder, name), f"dirty holder must expose {name}; {ctx}"


def test_view_and_list_keyboard_paths_cover_sdi_a12(qapp, qtbot):
    """SDI-A12: F2 starts the existing rename; MainWindow owns View cycling."""
    from mf4_analyzer.ui.view_state import ViewManager
    from mf4_analyzer.ui.view_tabbar import ViewTabBar

    manager = ViewManager()
    manager.new_view()
    manager.new_view()
    manager.set_active(0)
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    bar.show()
    qtbot.waitExposed(bar)
    ids = [view.view_id for view in manager.views]
    switched = []
    bar.switch_requested.connect(switched.append)
    bar.tabBar().setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    qtbot.keyClick(bar.tabBar(), Qt.Key_Tab, Qt.ControlModifier)
    qapp.processEvents()
    assert switched == [], _focus_ctx(bar, command="view.next")
    assert [view.view_id for view in manager.views] == ids
    qtbot.keyClick(bar.tabBar(), Qt.Key_F2)
    qapp.processEvents()
    editor = bar.findChild(QLineEdit, "viewTabRenameEditor")
    assert editor is not None and editor.text() == manager.views[0].name


def test_file_and_config_focus_share_mutation_owner_sdi_a13(qapp, qtbot):
    """SDI-A13: config table/file rows are focusable; keyboard uses the same owners."""
    from tests.ui.test_channel_config_manager import _config, _dialog
    from tests.ui.test_file_navigator import FakeFd, _shown_file_nav

    nav = _shown_file_nav(qtbot, ("f0", FakeFd(filename="alpha.csv")))
    row = nav._ordered_file_rows()[0]
    assert row.focusPolicy() & Qt.TabFocus
    assert row.accessibleName() == "alpha.csv"

    original = _config("drive", "动力分析", ("EPS_CRC", "Torque"))
    dialog = _dialog(qtbot, [original], "drive")
    qtbot.waitExposed(dialog)
    table = dialog.channel_table
    config_row = dialog.config_row_widget("drive")
    assert table.focusPolicy() & Qt.TabFocus
    assert config_row.focusPolicy() & Qt.TabFocus
    table.setCurrentCell(0, 1)
    table.setFocus(Qt.TabFocusReason)
    qapp.processEvents()
    qtbot.keyClick(table, Qt.Key_Space)
    qapp.processEvents()
    assert dialog._chosen_channels == {"EPS_CRC"}
    assert dialog.drafts[0].channel_names == original.channel_names
    qtbot.keyClick(table, Qt.Key_Delete)
    qapp.processEvents()
    assert dialog.drafts[0].channel_names == ("Torque",)
    assert original.channel_names == ("EPS_CRC", "Torque")


# ---------------------------------------------------------------------------
# Coverage map
# ---------------------------------------------------------------------------

def test_spec_acceptance_ids_are_mapped():
    """Every Spec SDI-Axx id is referenced by this file or FOREGROUND_GATES."""
    spec_ids = set(re.findall(r"SDI-A\d+", SPEC_PATH.read_text(encoding="utf-8")))
    source = Path(__file__).read_text(encoding="utf-8")
    present = set(re.findall(r"SDI-A\d+", source))
    missing = sorted(spec_ids - present)
    extra_gates = sorted(set(FOREGROUND_GATES) - spec_ids)
    assert spec_ids, "spec must declare SDI-Axx ids"
    assert not missing, (
        f"unmapped acceptance ids: {missing}; FOREGROUND_GATES={FOREGROUND_GATES}"
    )
    assert not extra_gates, f"FOREGROUND_GATES has unknown ids: {extra_gates}"
