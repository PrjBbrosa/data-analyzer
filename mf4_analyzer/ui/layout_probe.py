"""Explicit layout-probe factories for ``TRACELAB_LAYOUT_PROBE=1``.

Called after Fusion and the shared stylesheet are installed. Uses a
temporary QSettings namespace and synthetic widgets only: no user
project, no save/delete, no acquisition session. Must not import
``acquisition_ui`` so Lite frozen builds stay clean.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from PyQt5.QtCore import QRect, QSettings
from PyQt5.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from mf4_analyzer.ui_kit.dialog_geometry import (
    fit_popover,
    fit_window,
    install_geometry_relayout,
)
from mf4_analyzer.ui_kit.layout_diagnostics import (
    collect_environment_facts,
    collect_widget_layout_facts,
    emit_environment_once,
    emit_layout_facts,
)


def _probe_dir() -> Path:
    override = os.environ.get("TRACELAB_LAYOUT_PROBE_DIR")
    if override:
        path = Path(override).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = Path(tempfile.mkdtemp(prefix="tracelab-layout-probe-"))
    return path


def _isolate_qsettings(tmp_dir: Path) -> None:
    ini_dir = tmp_dir / "qsettings"
    ini_dir.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(ini_dir))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(ini_dir))


def _grab(widget: QWidget, path: Path) -> None:
    image = widget.grab()
    image.save(str(path), "PNG")


def _synthetic_dialog(app: QApplication) -> QDialog:
    dialog = QDialog()
    dialog.setObjectName("layoutProbeDialog")
    dialog.setWindowTitle("布局探针")
    root = QVBoxLayout(dialog)
    label = QLabel("合成正文：不打开用户项目，不执行保存或删除。")
    label.setWordWrap(True)
    root.addWidget(label)
    button = QPushButton("关闭", dialog)
    button.setObjectName("layoutProbeClose")
    button.clicked.connect(dialog.reject)
    root.addWidget(button)
    return dialog


def _batch_preview_demo() -> QWidget:
    from mf4_analyzer.batch_types import BatchPreviewResult
    from mf4_analyzer.ui.drawers.batch.preview_dialog import BatchPreviewDialog

    dialog = BatchPreviewDialog(None)
    warnings = tuple(
        f"slice.position_clamped: 探针警告 {index}，长路径 "
        f"/very/long/synthetic/path/does/not/exist_{index}.mf4"
        for index in range(30)
    )
    dialog.set_result(
        BatchPreviewResult(
            image_path=None,
            group_id="probe",
            display_name="layout-probe",
            loaded_source_count=0,
            warnings=warnings,
            message="合成预览，未读取用户文件",
        )
    )
    return dialog


def _config_manager_demo() -> QWidget:
    from mf4_analyzer.ui.widgets.channel_config_manager import ChannelConfigManagerDialog

    dialog = ChannelConfigManagerDialog((), parent=None)
    return dialog


def _unsaved_project_demo() -> QWidget:
    from mf4_analyzer.ui_kit.message_dialog import build_unsaved_project_dialog

    return build_unsaved_project_dialog(None)


def _cursor_popover_demo(app: QApplication) -> tuple[QWidget, QWidget]:
    from mf4_analyzer.ui.chart_stack.cursor_display import CursorDisplayPopover

    host = QWidget()
    host.setObjectName("layoutProbeCursorAnchor")
    host.setGeometry(QRect(500, 500, 80, 24))
    host.show()
    popover = CursorDisplayPopover(host)
    return host, popover


def _record(
    records: list,
    widget: QWidget,
    *,
    prompt_id: str,
    output_dir: Path,
    extra: dict | None = None,
) -> None:
    facts = collect_widget_layout_facts(widget, prompt_id=prompt_id)
    if extra:
        facts.update(extra)
    emit_layout_facts(facts, detailed=True)
    png = output_dir / f"{prompt_id}.png"
    try:
        _grab(widget, png)
        facts["screenshot"] = png.name
    except RuntimeError:
        facts["screenshot"] = ""
    records.append(facts)


def run_layout_probe(app: QApplication | None = None) -> int:
    """Build synthetic demos, write JSON/screenshots, return a process code."""
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication is required for the layout probe")
    output_dir = _probe_dir()
    _isolate_qsettings(output_dir)
    emit_environment_once()
    records: list[dict] = []
    owned: list[QWidget] = []
    try:
        dialog = _synthetic_dialog(app)
        owned.append(dialog)

        def _fit_probe_dialog():
            fit_window(dialog, (380, 160), content_minimum=(280, 120))

        install_geometry_relayout(dialog, _fit_probe_dialog)
        dialog.show()
        app.processEvents()
        _fit_probe_dialog()
        app.processEvents()
        _record(records, dialog, prompt_id="probe_synthetic_dialog", output_dir=output_dir)

        preview = _batch_preview_demo()
        owned.append(preview)
        preview.show()
        app.processEvents()
        _record(records, preview, prompt_id="probe_batch_preview_30", output_dir=output_dir)

        manager = _config_manager_demo()
        owned.append(manager)
        manager.show()
        app.processEvents()
        _record(records, manager, prompt_id="probe_channel_config_manager", output_dir=output_dir)

        unsaved = _unsaved_project_demo()
        owned.append(unsaved)
        unsaved.show()
        app.processEvents()
        _record(records, unsaved, prompt_id="unsaved_project", output_dir=output_dir)

        host, popover = _cursor_popover_demo(app)
        owned.extend((host, popover))
        screen = app.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else QRect(0, 0, 800, 600)
        host.move(avail.right() - host.width() - 8, avail.bottom() - host.height() - 8)
        host.show()
        app.processEvents()
        popover.show_for(host, "dual")
        app.processEvents()
        fit_popover(popover, host)
        app.processEvents()
        _record(
            records,
            popover,
            prompt_id="probe_cursor_display_popover",
            output_dir=output_dir,
            extra={"anchor": {"x": host.x(), "y": host.y()}},
        )
    finally:
        summary = {
            "environment": collect_environment_facts(),
            "demos": records,
            "output_dir": str(output_dir),
        }
        summary_path = output_dir / "layout-probe.json"
        try:
            summary_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            emit_layout_facts(
                {"prompt_id": "probe_write_failed", "error": type(exc).__name__},
                detailed=True,
            )
        print(f"layout probe wrote {summary_path}", file=sys.stderr)
        for widget in owned:
            widget.close()
            widget.deleteLater()
        app.processEvents()
    return 0


def run_layout_probe_and_exit(app: QApplication) -> None:
    raise SystemExit(run_layout_probe(app))
