"""Tests for drawer/sheet/popover migrations."""
import numpy as np
from types import SimpleNamespace


class FakeFD:
    filename = "x.mf4"
    channels = ['a', 'b']

    def __init__(self):
        self.channel_units = {}

    class _Data:
        columns = ['a', 'b']
        values = None

    data = _Data()
    time_array = np.linspace(0, 1, 10)

    def get_signal_channels(self):
        return ['a', 'b']


def test_channel_editor_drawer_constructs(qapp):
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer
    drawer = ChannelEditorDrawer(parent=None, fd=FakeFD())
    assert drawer is not None


def test_export_sheet_constructs(qapp):
    from mf4_analyzer.ui.drawers.export_sheet import ExportSheet
    sheet = ExportSheet(parent=None, chs=["speed", "torque"])
    assert sheet.get_selected() == ["speed", "torque"]  # default all-checked


def test_batch_sheet_current_single_returns_current_preset(qapp):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch_sheet import BatchSheet

    preset = AnalysisPreset.from_current_single(
        name="current fft",
        method="fft",
        signal=(1, "a"),
        params={"fs": 1000.0, "nfft": 1024},
    )
    sheet = BatchSheet(parent=None, files={1: FakeFD()}, current_preset=preset)

    selected = sheet.get_preset()

    assert sheet.tabs.isTabEnabled(0)
    assert selected.source == "current_single"
    assert selected.signal == (1, "a")


def test_batch_sheet_without_current_preset_starts_on_free_config(qapp):
    from mf4_analyzer.ui.drawers.batch_sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={1: FakeFD()}, current_preset=None)

    assert not sheet.tabs.isTabEnabled(0)
    assert sheet.tabs.currentIndex() == 1


def test_axis_lock_popover_emits(qapp, qtbot):
    from mf4_analyzer.ui.drawers.axis_lock_popover import AxisLockPopover
    p = AxisLockPopover(current='none')
    qtbot.addWidget(p)
    with qtbot.waitSignal(p.lock_changed, timeout=200) as bl:
        for b in p._grp.buttons():
            if b.property('lock_key') == 'x':
                b.setChecked(True)
                break
    assert bl.args == ['x']


def test_axis_lock_popover_anchors(qapp, qtbot):
    from PyQt5.QtWidgets import QPushButton
    from mf4_analyzer.ui.drawers.axis_lock_popover import AxisLockPopover
    anchor = QPushButton("🔒")
    qtbot.addWidget(anchor)
    anchor.move(50, 100)
    anchor.show()
    qtbot.waitExposed(anchor)
    p = AxisLockPopover(current='x')
    qtbot.addWidget(p)
    p.show_at(anchor)
    qtbot.waitExposed(p)
    expected = anchor.mapToGlobal(anchor.rect().bottomLeft())
    assert abs(p.pos().x() - expected.x()) < 3
    assert abs(p.pos().y() - expected.y()) < 3


def test_rebuild_time_popover_returns_fs(qapp, qtbot):
    from mf4_analyzer.ui.drawers.rebuild_time_popover import RebuildTimePopover
    p = RebuildTimePopover(parent=None, target_filename="data.mf4", current_fs=1000)
    qtbot.addWidget(p)
    p.spin_fs.setValue(500)
    assert p.new_fs() == 500


def test_rebuild_time_popover_anchors_below_widget(qapp, qtbot):
    from PyQt5.QtWidgets import QPushButton
    from mf4_analyzer.ui.drawers.rebuild_time_popover import RebuildTimePopover
    anchor = QPushButton("⏱")
    qtbot.addWidget(anchor)
    anchor.move(100, 200)
    anchor.show()
    qtbot.waitExposed(anchor)
    p = RebuildTimePopover(parent=None, target_filename="d.mf4", current_fs=1000)
    qtbot.addWidget(p)
    p.show_at(anchor)
    qtbot.waitExposed(p)
    expected = anchor.mapToGlobal(anchor.rect().bottomLeft())
    assert abs(p.pos().x() - expected.x()) < 3
    assert abs(p.pos().y() - expected.y()) < 3


def test_rebuild_time_popover_does_not_close_on_spin_interaction(qapp, qtbot):
    from mf4_analyzer.ui.drawers.rebuild_time_popover import RebuildTimePopover
    p = RebuildTimePopover(parent=None, target_filename="d.mf4", current_fs=1000)
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    p.spin_fs.setFocus()
    qapp.processEvents()
    assert p.isVisible()
    p.spin_fs.setValue(500)
    qapp.processEvents()
    assert p.isVisible()
