"""Render the approved compact BatchSheet state matrix offscreen.

The probe uses the shipped QSS, isolated QSettings, real widget state changes,
and DPR=1.  It intentionally emits more than one happy-path image: visual
acceptance needs method, preset, range, output, inline-file, and footer states at the
two supported sizes.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("TMPDIR", "/tmp/tracelab-batch-compact-ui-proof")
os.environ.setdefault(
    "XDG_CONFIG_HOME", "/tmp/tracelab-batch-compact-ui-proof/xdg",
)

from PyQt5.QtCore import PYQT_VERSION_STR, qVersion  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from mf4_analyzer.batch import BatchProgressEvent, BatchRunResult  # noqa: E402
from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet  # noqa: E402
from mf4_analyzer.ui_kit.stylesheet import load_stylesheet  # noqa: E402


def _process(app: QApplication) -> None:
    for _ in range(12):
        app.processEvents()


def _seed_sources(sheet: BatchSheet) -> None:
    file_list = sheet._input_panel._file_list
    signals = frozenset({"Rte_ActRet", "Rte_MotorTorque", "Rte_Rpm"})
    for index, path in enumerate((
        "drive_front.mf4", "drive_rear.mf4", "drive_nominal.mf4",
    ), start=1):
        file_list.add_loaded_file(f"source-{index}", path, signals)
    sheet.apply_signals(("Rte_ActRet", "Rte_MotorTorque"))
    sheet._output_panel.apply_directory("/tmp/tracelab-batch-output")


def _save(widget, path: Path) -> None:
    if not widget.grab().save(str(path)):
        raise RuntimeError(f"could not render {path}")


def _visible_to(widget, ancestor) -> bool:
    return bool(widget.isVisibleTo(ancestor))


def _sheet_facts(sheet: BatchSheet, name: str) -> dict:
    panes = (sheet._input_scroll, sheet._analysis_scroll, sheet._output_scroll)
    form = sheet._analysis_panel._param_form
    grouping = getattr(form, "_grouping_cards", None)
    axis = sheet._output_panel._axis_group
    return {
        "name": name,
        "size": [sheet.width(), sheet.height()],
        "fixed_rows": {
            "toolbar": sheet._toolbar_host.height(),
            "pipeline": sheet.strip.height(),
            "footer": sheet._footer_host.height(),
        },
        "pane_widths": [pane.width() for pane in panes],
        "pane_horizontal_policy": [
            int(pane.horizontalScrollBarPolicy()) for pane in panes
        ],
        "pane_vertical_max": [pane.verticalScrollBar().maximum() for pane in panes],
        "method": sheet.method(),
        "method_button_widths": {
            key: button.width()
            for key, button in sheet._analysis_panel._method_group._buttons.items()
        },
        "time_x_axis": {
            "source": form._w_x_source.currentData(),
            "channel_visible": _visible_to(form._field_hosts["x_channel"], sheet),
            "origin_visible": _visible_to(form._field_hosts["x_origin"], sheet),
            "channel_slot": [
                form._field_hosts["x_channel"].x(),
                form._field_hosts["x_channel"].y(),
                form._field_hosts["x_channel"].width(),
                form._field_hosts["x_channel"].height(),
            ],
            "origin_slot": [
                form._field_hosts["x_origin"].x(),
                form._field_hosts["x_origin"].y(),
                form._field_hosts["x_origin"].width(),
                form._field_hosts["x_origin"].height(),
            ],
        },
        "grouping": grouping.mode() if grouping is not None else "",
        "preset_state": sheet._analysis_panel.preset_state_text(),
        "source_interval_visible": _visible_to(
            sheet._analysis_panel.source_interval_widget(), sheet,
        ),
        "db_visible": _visible_to(
            sheet._output_panel.db_reference_control, sheet,
        ),
        "amplitude_unit_visible": _visible_to(
            sheet._output_panel._amplitude_unit_row, sheet,
        ),
        "amplitude_unit": sheet._output_panel.combo_amp_unit.currentText(),
        "z_visible": _visible_to(sheet._output_panel._z_axis_row, sheet),
        "axis_card": {
            "title": axis.title(),
            "bordered": axis.property("batchAxisCard") is True,
            "geometry": [axis.x(), axis.y(), axis.width(), axis.height()],
        },
        "footer": {
            "status": sheet._footer_status.text(),
            "task": sheet._footer_task_summary.text(),
            "progress": [
                sheet._footer_progress.value(), sheet._footer_progress.maximum(),
            ],
        },
        "run_enabled": sheet._btn_run.isEnabled(),
        "legacy_task_list_visible": sheet._task_list.isVisible(),
        "filter_settings_visible": _visible_to(
            sheet._input_panel._filter_panel._settings, sheet,
        ),
        "filter_time_options_visible": _visible_to(
            sheet._input_panel._filter_panel._time_options, sheet,
        ),
        "inline_files": {
            "facts": sheet._input_panel._file_facts.text(),
            "status": sheet._input_panel._file_ready.text(),
            "row_count": sheet._input_panel._file_list._list.count(),
            "empty_visible": _visible_to(
                sheet._input_panel._file_list._empty_label, sheet,
            ),
            "list_height": sheet._input_panel._file_list._list.height(),
            "list_scroll_max": (
                sheet._input_panel._file_list._list.verticalScrollBar().maximum()
            ),
        },
    }


def _save_sheet_state(
    app: QApplication, sheet: BatchSheet, out_dir: Path, name: str, facts: list,
) -> None:
    _process(app)
    if sheet._toolbar_host.height() != 50:
        raise AssertionError("toolbar must render at 50px")
    if sheet.strip.height() != 62:
        raise AssertionError("pipeline must render at 62px")
    if sheet._footer_host.height() != 54:
        raise AssertionError("footer must render at 54px")
    if sheet._task_list.isVisible():
        raise AssertionError("legacy task list must stay hidden")
    _save(sheet, out_dir / f"{name}.png")
    facts.append(_sheet_facts(sheet, name))


def _show_running_state(sheet: BatchSheet) -> None:
    tasks = sheet._build_dry_run_preview()
    sheet._task_list.apply_dry_run(
        tasks, sheet._outputs_per_task(), artifact_count=len(tasks) * 2,
    )
    sheet._running = True
    sheet.lock_editing()
    sheet._task_list.on_run_started()
    total = max(1, len(tasks))
    sheet._present_footer(
        "running", done=min(2, total), total=total, task_count=len(tasks),
    )


class _RenderThreadStub:
    def __init__(self) -> None:
        self.cancel_requested = False

    def request_cancel(self) -> None:
        self.cancel_requested = True

    def deleteLater(self) -> None:  # noqa: N802 - QThread-compatible probe
        return


def _show_completed_state(sheet: BatchSheet) -> None:
    total = sheet._task_list.row_count()
    for index in range(1, total + 1):
        sheet._on_runner_progress(BatchProgressEvent(
            kind="task_done", task_index=index, total=total,
        ))
    sheet._last_result = BatchRunResult(status="done")
    # Completion UI is the real QThread.finished projection; only the modal
    # toast is suppressed because an unattended offscreen probe cannot close it.
    sheet._show_result_toast = lambda _result: None
    sheet._on_thread_finished()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / ".state" / "batch-compact-ui-redesign-proof"),
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    load_stylesheet(app)

    state_facts: list[dict] = []

    empty_sheet = BatchSheet(None, files={})
    empty_sheet.resize(1080, 760)
    empty_sheet.show()
    _save_sheet_state(
        app, empty_sheet, out_dir, "1080-input-empty", state_facts,
    )
    empty_sheet.close()

    sheet = BatchSheet(None, files={})
    _seed_sources(sheet)
    sheet.resize(1080, 760)
    sheet.show()
    _process(app)

    # 1080×760 matrix -------------------------------------------------
    sheet.apply_method("time")
    grouping = sheet._analysis_panel._param_form._grouping_cards
    for mode in ("none", "source", "channel"):
        grouping.set_mode(mode)
        _save_sheet_state(
            app, sheet, out_dir, f"1080-time-group-{mode}", state_facts,
        )
    form = sheet._analysis_panel._param_form
    form.apply_params({"x_source": "time", "x_origin": "absolute"})
    _process(app)
    _save_sheet_state(app, sheet, out_dir, "1080-time-x-origin", state_facts)
    origin_slot = form._field_hosts["x_origin"].geometry()
    form.apply_params({"x_source": "channel", "x_channel": "Rte_Rpm"})
    _process(app)
    channel_slot = form._field_hosts["x_channel"].geometry()
    if not form._field_hosts["x_channel"].isVisibleTo(sheet):
        raise AssertionError("channel X source must reveal its dependent slot")
    if form._field_hosts["x_origin"].isVisibleTo(sheet):
        raise AssertionError("channel X source must hide the time-origin host")
    if any(
        abs(actual - expected) > 1
        for actual, expected in zip(
            (channel_slot.x(), channel_slot.y(), channel_slot.width(), channel_slot.height()),
            (origin_slot.x(), origin_slot.y(), origin_slot.width(), origin_slot.height()),
        )
    ):
        raise AssertionError("TimeDomain X dependent field moved out of its slot")
    _save_sheet_state(app, sheet, out_dir, "1080-time-x-channel", state_facts)
    sheet._input_panel._filter_panel._enable_switch.setChecked(True)
    _save_sheet_state(
        app, sheet, out_dir, "1080-time-filter-expanded", state_facts,
    )
    sheet._input_panel._filter_panel._enable_switch.setChecked(False)
    if sheet._output_panel.db_reference_control.isVisibleTo(sheet):
        raise AssertionError("time mode must not expose dB reference")
    if sheet._analysis_panel.source_interval_widget().isVisibleTo(sheet):
        raise AssertionError("time mode must not expose FFT source interval")

    _save_sheet_state(
        app, sheet, out_dir, "1080-input-inline-ready", state_facts,
    )

    sheet._input_panel._file_list._set_row_state(
        "drive_front.mf4", "probe_failed",
    )
    sheet._input_panel._file_list._set_row_state(
        "drive_rear.mf4", "probing",
    )
    _save_sheet_state(
        app, sheet, out_dir, "1080-input-partial-failure", state_facts,
    )
    sheet._input_panel._file_list._set_row_state("drive_front.mf4", "loaded")
    sheet._input_panel._file_list._set_row_state("drive_rear.mf4", "loaded")

    extra_paths = []
    for index in range(4, 9):
        path = f"long_batch_source_{index}.mf4"
        extra_paths.append(path)
        sheet._input_panel._file_list.add_loaded_file(
            f"source-{index}", path,
            frozenset({"Rte_ActRet", "Rte_MotorTorque", "Rte_Rpm"}),
        )
    _save_sheet_state(
        app, sheet, out_dir, "1080-input-inline-long-list", state_facts,
    )
    for path in extra_paths:
        sheet._input_panel._file_list.remove_path(path)

    sheet.apply_method("fft")
    sheet._analysis_panel._preset_buttons["torque"].click()
    _save_sheet_state(app, sheet, out_dir, "1080-fft-applied", state_facts)
    sheet._output_panel._on_render_style_clicked()
    _process(app)
    render_style_popover = sheet._output_panel._render_style_popover
    _save(render_style_popover, out_dir / "1080-render-style-default.png")
    render_style_popover._slider_x.setValue(20)
    render_style_popover._slider_y.setValue(14)
    render_style_popover._slider_font.setValue(125)
    _process(app)
    _save(render_style_popover, out_dir / "1080-render-style-custom.png")
    render_style_facts = {
        "slider": [
            render_style_popover._slider_x.value(),
            render_style_popover._slider_y.value(),
            render_style_popover._slider_font.value(),
        ],
        "spin": [
            render_style_popover._spin_x.value(),
            render_style_popover._spin_y.value(),
            render_style_popover._spin_font.value(),
        ],
        "recipe": sheet._output_panel.render_style_params(),
    }
    render_style_popover.hide()
    _save_sheet_state(app, sheet, out_dir, "gui-default-linewidth", state_facts)
    sheet._output_panel.combo_amp_unit.setCurrentText("Linear")
    _save_sheet_state(app, sheet, out_dir, "fft-linear", state_facts)
    sheet._output_panel.combo_amp_unit.setCurrentText("dB")
    sheet._analysis_panel._param_form._w_t_win_s.setValue(1.0)
    _save_sheet_state(app, sheet, out_dir, "1080-fft-dirty", state_facts)
    sheet._output_panel.chk_x_auto.setChecked(False)
    sheet._output_panel.spin_x_min.setValue(5.0)
    sheet._output_panel.spin_x_max.setValue(800.0)
    _save_sheet_state(app, sheet, out_dir, "1080-fft-manual-range", state_facts)

    for method, name in (
        ("fft_time", "1080-fft-vs-time"),
        ("order_time", "1080-order"),
    ):
        sheet.apply_method(method)
        _save_sheet_state(app, sheet, out_dir, name, state_facts)

    sheet.apply_method("fft")
    sheet._output_panel._chk_data.setChecked(True)
    sheet._output_panel._chk_image.setChecked(False)
    _save_sheet_state(app, sheet, out_dir, "1080-output-data-only", state_facts)
    sheet._output_panel._chk_data.setChecked(False)
    sheet._output_panel._chk_image.setChecked(True)
    _save_sheet_state(app, sheet, out_dir, "1080-output-image-only", state_facts)
    sheet._output_panel._chk_image.setChecked(False)
    _save_sheet_state(app, sheet, out_dir, "1080-output-blocked", state_facts)

    sheet._output_panel._chk_data.setChecked(True)
    sheet._output_panel._chk_image.setChecked(True)
    sheet.apply_method("fft")
    _show_running_state(sheet)
    _save_sheet_state(app, sheet, out_dir, "1080-running", state_facts)
    sheet._runner_thread = _RenderThreadStub()
    sheet._on_cancel_clicked()
    _save_sheet_state(app, sheet, out_dir, "1080-cancelling", state_facts)
    _show_completed_state(sheet)
    _save_sheet_state(app, sheet, out_dir, "1080-completed", state_facts)

    # 1440×900 overview matrix ---------------------------------------
    sheet.resize(1440, 900)
    sheet.apply_method("time")
    grouping.set_mode("source")
    _save_sheet_state(app, sheet, out_dir, "1440-time-source", state_facts)
    for method, name in (
        ("fft", "1440-fft-applied"),
        ("fft_time", "1440-fft-vs-time"),
        ("order_time", "1440-order"),
    ):
        sheet.apply_method(method)
        if method == "fft":
            sheet._analysis_panel._preset_buttons["torque"].click()
        _save_sheet_state(app, sheet, out_dir, name, state_facts)
    sheet.apply_method("fft")
    _show_running_state(sheet)
    _save_sheet_state(app, sheet, out_dir, "1440-running", state_facts)

    facts = {
        "environment": {
            "platform": platform.platform(),
            "qt_platform": app.platformName(),
            "qt": qVersion(),
            "pyqt": PYQT_VERSION_STR,
            "dpr": float(sheet.devicePixelRatioF()),
            "git_head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True,
            ).strip(),
            "git_branch": subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=REPO_ROOT, text=True,
            ).strip(),
            "worktree_dirty": bool(subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True,
            ).strip()),
        },
        "states": state_facts,
        "render_style": render_style_facts,
        "fft_export_contract": {
            "data_format": "xlsx",
            "image_format": "png",
            "image_size": [1920, 1080],
            "image_line_width": 1.5,
            "conflict_policy": "auto_number",
        },
    }
    (out_dir / "facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    if not any(
        fact["name"] == "1440-fft-applied" and fact["source_interval_visible"]
        for fact in state_facts
    ):
        raise AssertionError("wide FFT proof must show its source interval")
    sheet.unlock_editing()
    sheet.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
