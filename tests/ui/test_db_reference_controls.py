"""Widget/dialog tests for the dB-reference Inspector controls (Task 3).

Spec: ``docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md``
sections 9-11. Plan Step 3.1 literal test names:
``docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md``.

CRITICAL: every test constructs its OWN throwaway
``QSettings(path, QSettings.IniFormat)`` under ``tmp_path`` (via
``DbReferenceSettingsStore``) -- NEVER the real
``QSettings("MF4Analyzer", "DataAnalyzer")``.
"""
import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QModelIndex, QRect, Qt
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QDialog
from PyQt5.QtCore import QSettings

from mf4_analyzer import db_reference
from mf4_analyzer.ui.db_reference_dialog import (
    DbReferenceDefaultsDialog,
    _CatalogItemDelegate,
)
from mf4_analyzer.ui.db_reference_settings import DbReferenceSettingsStore
from mf4_analyzer.ui.widgets.db_reference import (
    DbReferenceControl,
    ScientificReferenceSpinBox,
)


def _settings(tmp_path, name="db-reference.ini"):
    return QSettings(str(tmp_path / name), QSettings.IniFormat)


def test_catalog_delegate_ignores_deleted_scientific_reference_editor(qapp):
    """A queued Qt delegate geometry update may outlive its cell widget."""
    from PyQt5.QtWidgets import QStyleOptionViewItem

    editor = ScientificReferenceSpinBox()
    editor.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(editor)

    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 160, 32)

    # Must not surface the deleted-wrapper RuntimeError during dialog teardown.
    _CatalogItemDelegate().updateEditorGeometry(editor, option, QModelIndex())


# ---------------------------------------------------------------------------
# ScientificReferenceSpinBox
# ---------------------------------------------------------------------------

def test_scientific_reference_editor_round_trips_small_values(qtbot):
    spin = ScientificReferenceSpinBox()
    qtbot.addWidget(spin)

    for value in (1e-12, 1e-9, 1e-6, 2e-5):
        spin.setValue(value)
        assert spin.value() == pytest.approx(value, rel=1e-9)
        assert spin.lineEdit().text() == db_reference.format_reference_editor(value)

        # Full input/save/restore round trip: retype the displayed compact
        # text and commit via Enter.
        text = spin.lineEdit().text()
        spin.lineEdit().selectAll()
        QTest.keyClicks(spin.lineEdit(), text)
        QTest.keyClick(spin, Qt.Key_Return)
        assert spin.value() == pytest.approx(value, rel=1e-9)

    # Capital-E scientific notation typed directly.
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), "1E-9")
    QTest.keyClick(spin, Qt.Key_Return)
    assert spin.value() == pytest.approx(1e-9, rel=1e-9)


def test_invalid_reference_commit_restores_last_valid_without_mode_change(qtbot):
    control = DbReferenceControl()
    qtbot.addWidget(control)
    control.editor.setValue(2e-5)
    control.set_mode("auto")

    control.editor.lineEdit().selectAll()
    QTest.keyClicks(control.editor.lineEdit(), "-5")
    QTest.keyClick(control.editor, Qt.Key_Return)

    assert control.editor.value() == pytest.approx(2e-5)
    assert control.editor.property("error") is True
    assert control.editor.toolTip() == "reference 必须是有限正数"
    assert control.mode() == "auto"


def test_user_edit_switches_auto_to_manual_only_on_commit(qtbot):
    control = DbReferenceControl()
    qtbot.addWidget(control)
    control.set_mode("auto")
    mode_spy = QSignalSpy(control.mode_committed)

    control.editor.lineEdit().selectAll()
    QTest.keyClicks(control.editor.lineEdit(), "2e-5")
    # Mid-typing (not yet committed) must not flip Auto -> Manual.
    assert control.mode() == "auto"
    assert len(mode_spy) == 0

    QTest.keyClick(control.editor, Qt.Key_Return)

    assert control.mode() == "manual"
    assert len(mode_spy) == 1
    assert mode_spy[0][0] == "manual"


def test_manual_commit_refreshes_stale_auto_source_line(qtbot):
    """Task 10 visual-tour finding: the host's ``_resolve_and_apply_
    db_reference`` (the only other writer of the source line) no-ops
    whenever mode != 'auto', so without the control's own refresh a genuine
    user commit left the caption on its STALE pre-commit "自动 · ..." text
    directly under the now-amber "M" badge -- a contradictory, misleading
    state. The control has no channel facts of its own, so it substitutes
    the same "手动覆盖" token already used for the badge tooltip."""
    control = DbReferenceControl()
    qtbot.addWidget(control)
    control.set_mode("auto")
    control.set_source_text("自动 · 系统默认 · acceleration / m/s²")

    control.editor.lineEdit().selectAll()
    QTest.keyClicks(control.editor.lineEdit(), "2.5e-6")
    QTest.keyClick(control.editor, Qt.Key_Return)

    assert control.mode() == "manual"
    assert "自动" not in control.full_source_text()
    assert "手动覆盖" in control.full_source_text()


def test_compound_control_exposes_required_object_names_and_spin_alias(qtbot):
    control = DbReferenceControl()
    qtbot.addWidget(control)

    assert control.objectName() == "dbReferenceControl"
    assert control.editor.objectName() == "dbReferenceEditor"
    assert control.manage_button.objectName() == "dbReferenceManageButton"
    assert control.badge.objectName() == "dbReferenceModeBadge"
    assert control.source_label.objectName() == "dbReferenceSourceLabel"

    # ctx.spin_db_ref compatibility: value()/setValue()/valueChanged.
    assert control.spin_db_ref is control.editor
    control.spin_db_ref.setValue(3.5e-4)
    assert control.editor.value() == pytest.approx(3.5e-4)

    received = []
    control.editor.valueChanged.connect(received.append)
    control.spin_db_ref.setValue(1.0)
    assert received and received[-1] == pytest.approx(1.0)


def test_manage_button_is_square_and_matches_editor_rendered_height(qtbot):
    control = DbReferenceControl()
    qtbot.addWidget(control)
    control.show()
    qtbot.wait(20)
    control.refresh_geometry()

    editor_h = control.editor.height()
    btn = control.manage_button
    assert editor_h > 0
    assert btn.height() == editor_h
    assert btn.width() == btn.height()

    # 2026-07-13 visual-feedback fix: the manage BUTTON's right edge (not
    # the overhanging badge) is the alignment datum against the sibling
    # fields above it (频率加权 / 幅值轴, same _fit_field(align_right=True)
    # host as this compound root) -- so the button must sit flush against
    # the compound root's own right CONTENT edge, not inset to make room
    # for the badge. Encodes the "button edge is the datum" contract so a
    # future re-widening of the right margin (to reserve badge overhang
    # space again) can't silently regress this.
    right_margin = control.layout().contentsMargins().right()
    expected_right_edge = control.width() - right_margin
    button_top_left = btn.mapTo(control, btn.rect().topLeft())
    button_right_edge = button_top_left.x() + btn.width()
    assert button_right_edge == pytest.approx(expected_right_edge, abs=1)


def test_auto_manual_badge_text_color_state_and_no_clipping(qtbot):
    control = DbReferenceControl()
    qtbot.addWidget(control)
    control.show()
    qtbot.wait(20)
    control.refresh_geometry()

    control.set_mode("auto")
    assert control.badge.text() == "A"
    assert control.badge.property("mode") == "auto"

    control.set_mode("manual")
    assert control.badge.text() == "M"
    assert control.badge.property("mode") == "manual"

    control.refresh_geometry()
    badge_rect = control.badge.geometry()
    # Fully contained in the control's own bounding rect -- Qt clips child
    # painting to the parent, so this is the geometric proxy for "never
    # clipped" at the offscreen/structural level (Task 10's visual tour adds
    # the on-screen pixel-corner proof).
    assert control.rect().contains(badge_rect)
    assert badge_rect.width() == DbReferenceControl._BADGE_SIZE
    assert badge_rect.height() == DbReferenceControl._BADGE_SIZE

    # 2026-07-13 visual-feedback fix: the badge must NOT overhang past the
    # manage button's right edge any more (that space was reclaimed so the
    # BUTTON, not the badge, aligns with the sibling fields' right edge) --
    # the badge's right edge is now flush with (never past) the button's.
    btn = control.manage_button
    btn_top_left = btn.mapTo(control, btn.rect().topLeft())
    button_right_edge = btn_top_left.x() + btn.width()
    assert badge_rect.right() + 1 <= button_right_edge
    assert badge_rect.right() + 1 == pytest.approx(button_right_edge, abs=1)


def test_source_line_elides_but_tooltip_keeps_full_text(qtbot):
    control = DbReferenceControl()
    qtbot.addWidget(control)
    control.resize(160, 70)
    control.show()
    qtbot.wait(20)

    long_text = (
        "自动 · 系统默认 · acceleration / m/s² · "
        "这是一段用于测试省略但工具提示必须保留完整内容的很长来源说明文字"
    )
    control.set_source_text(long_text)

    displayed = control.source_label.text()
    assert displayed != long_text
    assert len(displayed) < len(long_text)
    assert control.source_label.toolTip() == long_text
    assert control.full_source_text() == long_text


# ---------------------------------------------------------------------------
# DbReferenceDefaultsDialog
# ---------------------------------------------------------------------------

def test_dialog_cancel_and_escape_leave_store_and_view_unchanged(qtbot, tmp_path):
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    before = store.snapshot()

    dlg = DbReferenceDefaultsDialog(None, store, current_mode="manual")
    qtbot.addWidget(dlg)
    mode_spy = QSignalSpy(dlg.view_mode_committed)
    catalog_spy = QSignalSpy(dlg.catalog_saved)

    # Simulate a user flipping the toggle then backing out via Cancel.
    dlg._mode_switch.setChecked(True)
    dlg._btn_cancel.click()

    assert dlg.result() == QDialog.Rejected
    assert store.snapshot() == before
    assert store.revision == 0
    assert len(mode_spy) == 0
    assert len(catalog_spy) == 0

    # Escape key on a fresh instance behaves the same way.
    dlg2 = DbReferenceDefaultsDialog(None, store, current_mode="manual")
    qtbot.addWidget(dlg2)
    mode_spy2 = QSignalSpy(dlg2.view_mode_committed)
    dlg2._mode_switch.setChecked(True)
    QTest.keyClick(dlg2, Qt.Key_Escape)

    assert dlg2.result() == QDialog.Rejected
    assert store.snapshot() == before
    assert len(mode_spy2) == 0


def test_dialog_save_is_atomic_and_updates_provenance(qtbot, tmp_path):
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    dlg = DbReferenceDefaultsDialog(None, store, current_mode="manual")
    qtbot.addWidget(dlg)

    row_idx = next(i for i, r in enumerate(dlg._rows) if r.builtin_id == "acceleration.si")
    assert dlg.table.item(row_idx, 3).text() == "系统"

    dlg._reference_editors[row_idx].setValue(2e-6)
    dlg.table.item(row_idx, 0).setText("振动加速度")

    mode_spy = QSignalSpy(dlg.view_mode_committed)
    catalog_spy = QSignalSpy(dlg.catalog_saved)
    dlg._mode_switch.setChecked(True)  # switch 当前 View to Auto in the same commit
    dlg._btn_save.click()

    assert dlg.result() == QDialog.Accepted
    assert len(catalog_spy) == 1
    assert len(mode_spy) == 1
    assert mode_spy[0][0] == "auto"

    snap = store.snapshot()
    user_ids = {e.builtin_id: e for e in snap.user_catalog if e.builtin_id}
    assert "acceleration.si" in user_ids
    assert user_ids["acceleration.si"].reference == pytest.approx(2e-6)
    assert user_ids["acceleration.si"].label == "振动加速度"

    # Provenance re-renders to 用户 for the touched row after save.
    row_idx2 = next(i for i, r in enumerate(dlg._rows) if r.builtin_id == "acceleration.si")
    assert dlg.table.item(row_idx2, 3).text() == "用户"

    resolution = db_reference.resolve_db_reference(
        mode="auto",
        facts=db_reference.ChannelReferenceFacts(quantity="acceleration", unit="m/s²"),
        user_catalog=snap.user_catalog,
        system_catalog=snap.system_catalog,
        prefer_channel_metadata=snap.prefer_channel_metadata,
    )
    assert resolution.source == "user"
    assert resolution.value == pytest.approx(2e-6)


def test_dialog_restore_uses_factory_working_copy_until_save(qtbot, tmp_path):
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    store.save(
        overrides=[{
            "builtin_id": "acceleration.si", "label": "x", "unit": "m/s²",
            "aliases": ["m/s²"], "reference": 2e-6,
        }],
        custom=[], hidden_builtin_ids=["force.si"], prefer_channel_metadata=True,
    )
    before_snapshot = store.snapshot()

    dlg = DbReferenceDefaultsDialog(None, store)
    qtbot.addWidget(dlg)
    assert dlg.table.rowCount() == (
        len(before_snapshot.system_catalog) + len(before_snapshot.user_catalog)
    )

    dlg._btn_restore.click()

    # Working copy now shows the pure factory table...
    assert dlg.table.rowCount() == len(db_reference.FACTORY_CATALOG_V1)
    accel_idx = next(i for i, r in enumerate(dlg._rows) if r.builtin_id == "acceleration.si")
    assert dlg._reference_editors[accel_idx].value() == pytest.approx(1e-6)
    force_idx = next(i for i, r in enumerate(dlg._rows) if r.builtin_id == "force.si")
    assert dlg.table.item(force_idx, 3).text() == "系统"

    # ...but the STORE stays exactly as it was until Save.
    assert store.snapshot() == before_snapshot

    dlg._btn_save.click()

    assert dlg.result() == QDialog.Accepted
    after = store.snapshot()
    assert after.system_catalog == db_reference.FACTORY_CATALOG_V1
    assert after.user_catalog == ()


def test_dialog_layout_insets_toggle_content_and_bounds_compact_columns(
    qtbot, tmp_path,
):
    """The visual layout keeps cards and compact table fields off their edges."""
    from PyQt5.QtWidgets import QHeaderView, QPushButton, QWidget
    from mf4_analyzer.ui import db_reference_dialog as dialog_mod

    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    dlg = DbReferenceDefaultsDialog(None, store, current_effective_summary="")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.wait(30)

    toggle_rows = dlg.findChildren(QWidget, "dbReferenceDialogToggleRow")
    assert len(toggle_rows) == 2
    for row in toggle_rows:
        margins = row.layout().contentsMargins()
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
            12, 5, 12, 5,
        )
    assert not dlg._effective_label.isVisible()

    header = dlg.table.horizontalHeader()
    assert header.sectionResizeMode(dialog_mod._COL_QUANTITY) == QHeaderView.Stretch
    assert header.sectionResizeMode(dialog_mod._COL_UNIT) == QHeaderView.Interactive
    assert dlg.table.columnWidth(dialog_mod._COL_UNIT) == dialog_mod._TABLE_UNIT_WIDTH
    assert dlg.table.columnWidth(dialog_mod._COL_QUANTITY) > dlg.table.columnWidth(
        dialog_mod._COL_UNIT
    )
    assert isinstance(dlg.table.itemDelegate(), dialog_mod._CatalogItemDelegate)

    delete_cell = dlg.table.cellWidget(0, dialog_mod._COL_DELETE)
    delete_button = delete_cell.findChild(QPushButton)
    assert dlg.table.rowHeight(0) == dialog_mod._TABLE_ROW_HEIGHT
    assert delete_button.geometry().left() >= 6
    assert delete_button.geometry().right() <= delete_cell.width() - 7
    assert delete_button.geometry().top() >= 4
    assert delete_button.geometry().bottom() <= delete_cell.height() - 5


def test_dialog_rejects_invalid_and_duplicate_rows_inline(qtbot, tmp_path):
    store = DbReferenceSettingsStore(settings=_settings(tmp_path))
    dlg = DbReferenceDefaultsDialog(None, store)
    qtbot.addWidget(dlg)
    dlg.show()

    # (a) an out-of-range reference on an existing builtin row.
    idx = next(i for i, r in enumerate(dlg._rows) if r.builtin_id == "force.si")
    dlg._reference_editors[idx].setValue(-1.0)

    catalog_spy = QSignalSpy(dlg.catalog_saved)
    dlg._btn_save.click()

    assert dlg.result() != QDialog.Accepted
    assert len(catalog_spy) == 0
    assert dlg._error_label.isVisible()
    assert dlg._error_label.text() != ""
    assert idx in dlg._row_errors
    assert store.snapshot().user_catalog == ()

    # Fix it, then add a new custom row whose (quantity, alias) collides with
    # force.si's own ("force", "N") pair -- must ALSO be rejected inline,
    # without saving. The dialog's "物理量" column doubles as the custom
    # row's matching quantity (see _collect_working_values), so it must
    # normalize to the SAME quantity ("force") as force.si for this to be a
    # genuine (quantity, alias) collision, not just a shared alias under a
    # different quantity (which spec R2 explicitly allows).
    dlg._reference_editors[idx].setValue(1e-6)
    dlg._add_custom_row()
    new_idx = dlg.table.rowCount() - 1
    dlg.table.item(new_idx, 0).setText("Force")
    dlg.table.item(new_idx, 1).setText("N")
    dlg._reference_editors[new_idx].setValue(1.0)

    dlg._btn_save.click()

    assert dlg.result() != QDialog.Accepted
    assert new_idx in dlg._row_errors
    assert store.snapshot().user_catalog == ()
