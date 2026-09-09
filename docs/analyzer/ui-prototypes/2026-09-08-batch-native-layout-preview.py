"""Standalone layout preview using the CURRENT BatchSheet widget instances.

Run from this repository with its .venv Python. No product source changes.
The sample's import/export/run entry points are intercepted; QSettings is isolated.
Native Cocoa grabs and a JSON probe go under .state/batch-native-layout-preview/.

    TMPDIR=/tmp PYTHONPATH=. .venv/bin/python \
      docs/analyzer/ui-prototypes/2026-09-08-batch-native-layout-preview.py --live
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TMPDIR", "/tmp")

from PyQt5.QtCore import QCoreApplication, QEvent, QSettings, Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)


def isolate_settings(directory):
    path = str(directory / "preferences.ini")

    def settings(*_args, **_kwargs):
        return QSettings(path, QSettings.IniFormat)

    for name in (
        "mf4_analyzer.ui.inspector_sections",
        "mf4_analyzer.ui.inspector_sections._helpers",
        "mf4_analyzer.ui.inspector_sections.collapsible",
        "mf4_analyzer.ui.inspector_sections.presets",
        "mf4_analyzer.ui.inspector_sections.persistent_top",
    ):
        module = importlib.import_module(name)
        if hasattr(module, "_preset_settings"):
            module._preset_settings = settings
    batch_settings = importlib.import_module("mf4_analyzer.ui.batch_settings")
    batch_settings._default_settings = settings
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(directory))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(directory))
    return batch_settings.BatchPanelPrefsStore(settings())


from mf4_analyzer.batch_types import FrfPairRule
from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
from mf4_analyzer.ui_kit.stylesheet import load_stylesheet

SIGNALS = frozenset({"Steering_Torque", "Steering_Angle", "Rack_Force", "Motor_Current", "Motor_Speed"})
SOURCES = ("Sweep_Forward_01.mf4", "Sweep_Forward_02.mf4", "TLC_Sweep_Forward_01.mf4", "TLC_Sweep_Forward_02.mf4")


class Fold(QWidget):
    """Prototype-only wrapper; its child remains the original product widget."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self.button = QToolButton(self)
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setArrowType(Qt.RightArrow)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.button.setStyleSheet(
            "QToolButton { text-align:left; border:0; border-top:1px solid #e3eaf3;"
            "padding:9px 0; color:#60748f; background:transparent; font-size:11px; }"
        )
        outer.addWidget(self.button)
        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(9)
        outer.addWidget(self.body)
        self.body.hide()
        self.button.toggled.connect(self.set_expanded)

    def add(self, widget):
        self.body_layout.addWidget(widget)
        widget.show()

    def set_expanded(self, expanded):
        self.button.setChecked(expanded)
        self.button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)


class NativeLayoutPreview(BatchSheet):
    def __init__(self, prefs_store):
        self._preview_layout_ready = False
        self._notice_dialog = None
        super().__init__(None, files={}, prefs_store=prefs_store)
        self.setWindowTitle("批处理分析 · 原控件布局预览（示例数据）")
        # These original controls keep their original appearance. Only the
        # standalone demo callbacks are replaced, so synthetic paths cannot run.
        file_list = self._input_panel._file_list
        file_list._btn_disk.clicked.disconnect()
        file_list._btn_disk.clicked.connect(self._sample_files)
        file_list._btn_loaded.clicked.disconnect()
        file_list._btn_loaded.clicked.connect(self._sample_files)
        self._btn_preview.setToolTip("独立布局预览：展示说明，不执行数据计算")
        self._btn_run.setToolTip("独立布局预览：展示说明，不启动批处理")

    def _sample_files(self):
        fl = self._input_panel._file_list
        for i, name in enumerate(SOURCES):
            fl.add_loaded_file(f"sample-{i}", f"/示例数据/{name}", SIGNALS)
        if self._preview_layout_ready:
            self._set_file_details(self._file_toggle.isChecked())

    def seed(self):
        self._sample_files()
        self.apply_method("frf")
        self._input_panel.apply_frf_pair_rules((FrfPairRule("Steering_Torque", ("Rack_Force",)),))
        self._output_panel.apply_directory("/示例输出/mf4_batch_output")
        self._analysis_panel._apply_slot("torque")
        self._recompute_pipeline_status()

    def _on_run_clicked(self):
        self._show_demo_notice("运行入口", "这是独立布局预览。\n原有控件可调整，未启动批处理，也不会生成分析文件。")

    def _on_preview_clicked(self):
        self._show_demo_notice("预览入口", "本窗口用于确认真实控件的排版。\n示例仅包含通道目录，未加载实际波形，不执行计算。")

    def _on_import_preset(self):
        self._show_demo_notice("导入方案", "此按钮沿用原控件外观。\n布局预览中不导入真实方案。")

    def _on_export_preset(self):
        self._show_demo_notice("导出方案", "此按钮沿用原控件外观。\n布局预览中不写出方案文件。")

    def _show_demo_notice(self, title, message):
        if self._notice_dialog is not None:
            self._notice_dialog.close()
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(20, 18, 20, 18)
        text = QLabel(message, dialog)
        text.setWordWrap(True)
        lay.addWidget(text)
        close = QPushButton("返回配置", dialog)
        close.clicked.connect(dialog.accept)
        lay.addWidget(close)
        dialog.resize(400, 150)
        self._notice_dialog = dialog
        dialog.show()

    @staticmethod
    def _remove_stretch(layout):
        for index in reversed(range(layout.count())):
            if layout.itemAt(index).spacerItem() is not None:
                layout.takeAt(index)

    def rearrange(self):
        """Reparent the real controls. Do not replace their data/state owners."""
        self._original_widgets = tuple(self.findChildren(QWidget))
        self._parked = QWidget(self)
        self._parked.hide()
        root = self.layout()
        root.removeWidget(self.strip)
        self.strip.hide()  # remains the original status projection/model seam
        inp, analysis, output = self._input_panel, self._analysis_panel, self._output_panel
        for scroll in (self._input_scroll, self._analysis_scroll, self._output_scroll):
            scroll.takeWidget()
            self._detail_lay.removeWidget(scroll)
            scroll.hide()

        # Parent selection above its dependent targets/parameters.
        method_header = analysis._outer_layout.takeAt(0).widget()
        method_header.setParent(self._parked)
        analysis._outer_layout.removeWidget(analysis._method_group)
        method_host = QWidget(self)
        method_lay = QHBoxLayout(method_host)
        method_lay.setContentsMargins(18, 12, 18, 12)
        method_lay.setSpacing(18)
        title = QLabel("分析方法", method_host)
        title.setObjectName("BatchSectionTitle")
        method_lay.addWidget(title)
        method_lay.addWidget(analysis._method_group, 1)
        analysis._method_group.show()
        root.insertWidget(1, method_host)
        self._method_host = method_host

        # Shared editing pane: existing InputPanel, existing AnalysisPanel.
        main = QWidget(self._detail_host)
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        self._guide = QLabel("选择方法 → 添加文件与选择目标 → 确认参数", main)
        self._guide.setWordWrap(True)
        self._guide.setStyleSheet("color:#607b9b; background:#eef5fd; padding:9px 18px; font-size:11px;")
        ml.addWidget(self._guide)
        self._remove_stretch(inp._outer_layout)
        self._remove_stretch(analysis._outer_layout)
        ml.addWidget(inp)
        line = QFrame(main)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#e0e8f2;")
        ml.addWidget(line)
        ml.addWidget(analysis)
        ml.addStretch(1)
        self._main_scroll = QScrollArea(self._detail_host)
        self._main_scroll.setObjectName("NativePreviewMainScroll")
        self._main_scroll.setFrameShape(QFrame.NoFrame)
        self._main_scroll.setWidgetResizable(True)
        self._main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._main_scroll.setMinimumSize(0, 0)
        self._main_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self._main_scroll.setStyleSheet("QScrollArea#NativePreviewMainScroll { border:0; border-right:1px solid #dbe4ef; background:white; }")
        self._main_scroll.setWidget(main)
        inp.show()
        analysis.show()
        self._detail_lay.addWidget(self._main_scroll, 65)
        self._output_scroll.setWidget(output)
        output.show()
        self._output_scroll.show()
        self._detail_lay.addWidget(self._output_scroll, 35)

        # Keep the real +loaded / +disk controls. Collapse only their list body.
        fl = inp._file_list
        self._file_toggle = QPushButton("查看文件", fl)
        self._file_toggle.setProperty("role", "quiet")
        self._file_toggle.setCheckable(True)
        header = fl.layout().itemAt(0).layout()
        header.addWidget(self._file_toggle)
        self._file_toggle.toggled.connect(self._set_file_details)
        fl.filesChanged.connect(self._refresh_file_collapsed)
        self._set_file_details(False)

        # The actual FRF parameter form stays intact, under a disclosure row.
        self._parameter_fold = Fold("计算与显示参数 · 展开调整", analysis)
        position = analysis._outer_layout.indexOf(analysis._param_form)
        analysis._outer_layout.removeWidget(analysis._param_form)
        self._parameter_fold.add(analysis._param_form)
        analysis._outer_layout.insertWidget(position, self._parameter_fold)
        self._facts = QLabel(analysis)
        self._facts.setWordWrap(True)
        self._facts.setStyleSheet("color:#647b97; font-size:11px; padding:3px 0 5px;")
        analysis._outer_layout.insertWidget(position, self._facts)

        # Move the existing preprocessing panel with its switch and settings.
        filter_panel = inp._filter_panel
        form = inp._target_stack.parentWidget().layout()
        self._filter_layout_item = form.takeRow(filter_panel)
        self._preprocess_fold = Fold("预处理 · 原始数据", analysis)
        self._preprocess_fold.add(filter_panel)
        analysis._outer_layout.addWidget(self._preprocess_fold)

        # Output controls unchanged; only the existing axis/style group folds.
        axis_position = output._outer_layout.indexOf(output._axis_group)
        style_row = output._btn_render_style.parentWidget()
        output._outer_layout.removeWidget(output._axis_group)
        output._outer_layout.removeWidget(style_row)
        self._output_fold = Fold("坐标范围与图像显示 · 自动范围", output)
        self._output_fold.add(output._axis_group)
        self._output_fold.add(style_row)
        output._outer_layout.insertWidget(axis_position, self._output_fold)
        plan_host = QFrame(output)
        plan_host.setStyleSheet("QFrame { background:#f6f9fd; border:1px solid #e1e8f1; border-radius:7px; }")
        plan_lay = QVBoxLayout(plan_host)
        plan_lay.setContentsMargins(12, 12, 12, 12)
        self._plan = QLabel(plan_host)
        self._plan.setWordWrap(True)
        self._plan.setStyleSheet("border:0; color:#526b87; font-size:11px; background:transparent;")
        plan_lay.addWidget(self._plan)
        output._outer_layout.insertWidget(output._outer_layout.count()-1, plan_host)

        self._locate_button = QPushButton("定位待配置项", self._footer_host)
        self._locate_button.setProperty("role", "quiet")
        self._locate_button.clicked.connect(self._locate_missing)
        self._footer_lay.insertWidget(self._footer_lay.indexOf(self._btn_cancel), self._locate_button)
        self._toolbar_title.setText("批处理分析 · 布局预览")
        self._toolbar_title.setToolTip("复用当前程序的真实控件；仅示例数据，不执行分析。")
        analysis.methodChanged.connect(self._update_preview)
        analysis.paramsChanged.connect(self._update_preview)
        self._preview_layout_ready = True
        self._update_preview()

    def _set_file_details(self, expanded):
        fl = self._input_panel._file_list
        self._file_toggle.setText("收起文件" if expanded else "查看文件")
        fl._list.setVisible(expanded and bool(fl._rows))
        fl._empty_label.setVisible(expanded and not fl._rows)
        self._input_panel._file_manager_host.setFixedHeight(220 if expanded else 53)

    def _refresh_file_collapsed(self):
        self._set_file_details(self._file_toggle.isChecked())

    def _recompute_pipeline_status(self):
        super()._recompute_pipeline_status()
        if self._preview_layout_ready:
            self._update_preview()

    def _update_preview(self, *_args):
        if not self._preview_layout_ready:
            return
        params = self._analysis_panel.get_params()
        facts = []
        for key, name in (("estimator", "估计器"), ("window", "窗"), ("t_win_s", "窗长 (s)"), ("overlap", "重叠率")):
            if key in params:
                facts.append(f"{name} {params[key]}")
        if "nfft_mode" in params:
            facts.append("NFFT 自动" if params["nfft_mode"] == "auto" else f"NFFT {params.get('nfft')}")
        if not facts:
            facts.append("使用当前时域设置")
        self._facts.setText(" · ".join(facts))
        rows = self._input_panel._file_list.loaded_rows()
        signals = self.selected_signals()
        runnable = self.is_runnable()
        self._locate_button.setVisible(not runnable)
        self._guide.setText(
            "配置已就绪。需要微调时展开原有参数；文件和目标可随时修改。" if runnable
            else "先添加文件，再选择当前分析需要的目标；底部可定位待配置项。"
        )
        selected = " → ".join(signals) if self.method() == "frf" else "、".join(signals)
        self._plan.setText(
            f"本次配置\n\n{len(rows)} 个逻辑来源\n{selected or '待选择目标'}\n\n"
            f"{'配置已就绪' if runnable else '尚有项目需要配置'}\n\n"
            "独立布局预览 · 示例数据\n运行与预览入口仅展示说明。"
        )

    def _locate_missing(self):
        if not self._input_panel._file_list.loaded_rows():
            self._set_file_details(True)
            widget = self._input_panel._file_manager_host
        elif not self.selected_signals() or self._input_panel.frf_pair_validation_message():
            widget = self._input_panel._target_stack
        else:
            self._parameter_fold.set_expanded(True)
            widget = self._analysis_panel
        self._main_scroll.ensureWidgetVisible(widget, 10, 15)
        widget.setFocus()


def drain(app, ms=180):
    from PyQt5.QtTest import QTest
    QTest.qWait(ms)
    app.processEvents()


def config_snapshot(sheet):
    return dataclasses.asdict(sheet.get_preset())


def rect(widget, sheet):
    from PyQt5.QtCore import QPoint
    pos = widget.mapTo(sheet, QPoint(0, 0))
    return [pos.x(), pos.y(), widget.width(), widget.height()]


def capture(sheet, path):
    if not sheet.grab().save(str(path)):
        raise RuntimeError(f"could not save {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=ROOT / ".state/batch-native-layout-preview")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    temp = tempfile.TemporaryDirectory(prefix="tracelab-batch-native-preview-")
    prefs_store = isolate_settings(Path(temp.name))
    app = QApplication(sys.argv[:1])
    app.setApplicationName("TraceLabBatchLayoutPreview")
    app.setOrganizationName("TraceLabPreviewIsolated")
    app.setStyle("Fusion")
    load_stylesheet(app)
    sheet = NativeLayoutPreview(prefs_store)
    sheet.seed()
    screen = app.primaryScreen().availableGeometry()
    sheet.resize(min(1280, screen.width()-40), min(820, screen.height()-60))
    sheet.show()
    drain(app)
    before = config_snapshot(sheet)
    tracked = {
        "methods": sheet._analysis_panel._method_group,
        "presets": sheet._analysis_panel._preset_host,
        "parameter_form": sheet._analysis_panel._param_form,
        "frf_pairs": sheet._input_panel._frf_pair_editor,
        "signal_picker": sheet._input_panel._signal_picker,
        "file_manager": sheet._input_panel._file_manager_host,
        "axis_group": sheet._output_panel._axis_group,
        "preview_button": sheet._btn_preview,
        "run_button": sheet._btn_run,
    }
    ids_before = {name: id(widget) for name, widget in tracked.items()}
    capture(sheet, args.out_dir / "01-current-controls.png")
    sheet.rearrange()
    drain(app)
    after = config_snapshot(sheet)
    assert before == after, "Layout relocation changed the authored preset"
    from PyQt5 import sip
    assert all(not sip.isdeleted(widget) for widget in sheet._original_widgets)
    capture(sheet, args.out_dir / "02-native-layout-collapsed.png")
    facts = {
        "platform": app.platformName(),
        "screen_available": [screen.x(), screen.y(), screen.width(), screen.height()],
        "client": [sheet.width(), sheet.height()],
        "frame": [sheet.frameGeometry().x(), sheet.frameGeometry().y(), sheet.frameGeometry().width(), sheet.frameGeometry().height()],
        "same_preset_before_after": before == after,
        "same_control_instances": ids_before == {name:id(widget) for name,widget in tracked.items()},
        "all_original_widgets_alive": len(sheet._original_widgets),
        "controls": {name: {"class": type(widget).__name__, "module": type(widget).__module__, "rect": rect(widget,sheet)} for name,widget in tracked.items()},
        "checks": [],
    }
    # Use disposable reference/candidate dialogs so the deliverable stays at
    # the original authored sample state throughout the stress probes.
    roundtrip_results = []
    for relocated in (False, True):
        probe = NativeLayoutPreview(prefs_store)
        probe.seed()
        probe_preset = probe.get_preset()
        if relocated:
            probe.rearrange()
        for method in ("time", "fft", "fft_time", "order_time", "frf"):
            probe.apply_method(method)
            drain(app, 30)
            inp = probe._input_panel
            assert inp._method == method
            assert probe._output_panel._method == method
            assert (inp._target_stack.currentWidget() is inp._frf_pair_editor) == (method == "frf")
            assert inp._rpm_row_visible == (method == "order_time")
            if relocated:
                facts["checks"].append(f"{method}: existing target and output signals synchronized")
        probe.apply_preset(probe_preset)
        drain(app)
        roundtrip_results.append(config_snapshot(probe))
        probe.close()
        probe.deleteLater()
        drain(app, 30)
    assert roundtrip_results[0] == roundtrip_results[1], "Relocation changed the existing method/preset round trip"
    facts["checks"].append("Five-method/preset round trip matches the unmodified layout")
    facts["baseline_roundtrip_differences"] = {
        k: [before.get(k), roundtrip_results[0].get(k)]
        for k in before if before.get(k) != roundtrip_results[0].get(k)
    }
    assert config_snapshot(sheet) == after
    sheet._parameter_fold.set_expanded(True)
    sheet._output_fold.set_expanded(True)
    drain(app)
    from PyQt5.QtCore import QPoint
    parameter_y = sheet._parameter_fold.mapTo(sheet._main_scroll.widget(), QPoint(0, 0)).y()
    sheet._main_scroll.verticalScrollBar().setValue(max(0, parameter_y - 12))
    drain(app, 80)
    assert sheet._analysis_panel._param_form.isVisibleTo(sheet)
    assert sheet._output_panel._axis_group.isVisibleTo(sheet)
    capture(sheet, args.out_dir / "03-native-layout-expanded.png")
    sheet._parameter_fold.set_expanded(False)
    sheet._output_fold.set_expanded(False)
    sheet._main_scroll.verticalScrollBar().setValue(0)
    sheet._file_toggle.setChecked(True)
    drain(app)
    assert sheet._input_panel._file_list._list.isVisibleTo(sheet)
    capture(sheet, args.out_dir / "04-native-layout-files.png")
    sheet._file_toggle.setChecked(False)
    # Exercise preserved native selector popup and its close path.
    group = sheet._input_panel._frf_pair_editor._groups[0]
    from PyQt5.QtTest import QTest
    QTest.mouseClick(group.input_picker._arrow_button, Qt.LeftButton)
    drain(app, 70)
    popup = app.activePopupWidget()
    facts["selector_popup_opened"] = popup is not None
    if popup is not None:
        QTest.keyClick(popup, Qt.Key_Escape)
    drain(app, 60)
    assert sheet._runner_thread is None and sheet._preview_thread is None
    sheet._main_scroll.verticalScrollBar().setValue(0)
    sheet._btn_preview.setFocus()
    capture(sheet, args.out_dir / "02-native-layout-collapsed.png")
    facts["no_compute_threads"] = True
    (args.out_dir / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"platform":facts["platform"], "size":facts["client"], "same_controls":facts["same_control_instances"], "same_preset":facts["same_preset_before_after"], "checks":facts["checks"], "popup":facts["selector_popup_opened"], "output":str(args.out_dir)},ensure_ascii=False), flush=True)
    if args.live:
        sheet.raise_()
        sheet.activateWindow()
        app.exec_()
    else:
        sheet.close()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    temp.cleanup()


if __name__ == "__main__":
    main()
