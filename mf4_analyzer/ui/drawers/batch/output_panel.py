"""Output column for the batch dialog.

Mirrors the pre-W4 ``batch_sheet.py`` output group (recovered from commit
``ad28d29~1``): directory ``QLineEdit`` + 选择… ``QPushButton`` opening
``QFileDialog.getExistingDirectory``, ``chk_data`` / ``chk_image`` checkboxes,
and a ``csv``/``xlsx`` format ``QComboBox``.

``BatchOutput`` owns every portable output option.  Runtime resume/retry stays
available to the runner and manifest APIs, but this compact GUI has no hidden
recovery-control surface.
"""
from __future__ import annotations

from pathlib import Path

import qtawesome as qta
from PyQt5.QtCore import QSize, QSignalBlocker, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout,
    QWidget,
)

from ....batch import BatchOutput
from ....batch_render_style import RenderStyle, render_style_from_params
from .... import db_reference
from ...inspector_sections._helpers import (
    _make_axis_settings_group,
    apply_db_reference_partial,
    apply_db_reference_preset,
    db_reference_params,
    make_db_reference_control,
)
from ..._axis_defaults import z_range_for
from .render_style_popover import RenderStylePopover


_GENERIC_DB_Z_RANGE = (-80.0, 0.0)
_ORDER_TIME_DB_Z_RANGE = (-50.0, -10.0)
_ORDER_TIME_METHOD = "order_time"
_BATCH_AXIS_LABEL_W = 72


def default_output_dir() -> str:
    """The hard-coded output directory, resolved fresh on every call.

    ``Path.home()`` is read at call time rather than at import so the 恢复默认
    escape hatch lands on the same string the panel is born with, even when a
    test has redirected ``HOME``.
    """
    return str(Path.home() / "Desktop" / "mf4_batch_output")


_AXIS_CONTEXTS = {
    "time": {
        "x_label": "时间 (X):",
        "x_unit": "s",
        "x_summary": "全时段",
        "y_label": "幅值 (Y):",
        "y_unit": "",
        "y_summary": "自动范围",
    },
    "fft": {
        "x_label": "频率 (X):",
        "x_unit": "Hz",
        "x_summary": "自动范围",
        "y_label": "幅值 (Y):",
        "y_unit": "",
        "y_summary": "自动范围",
    },
    "fft_time": {
        "x_label": "时间 (X):",
        "x_unit": "s",
        "x_summary": "全时段",
        "y_label": "频率 (Y):",
        "y_unit": "Hz",
        "y_summary": "0 → Nyquist",
    },
    "frf": {
        "x_label": "频率 (X):",
        "x_unit": "Hz",
        "x_summary": "自动范围",
        "y_label": "幅值 (Y):",
        "y_unit": "",
        "y_summary": "自动范围",
    },
    "order_time": {
        "x_label": "时间 (X):",
        "x_unit": "s",
        "x_summary": "全时段",
        "y_label": "阶次 (Y):",
        "y_unit": "",
        "y_summary": "0 → 最大阶次",
    },
}


class OutputPanel(QWidget):
    changed = pyqtSignal()
    #: The 恢复默认 escape hatch. Emitted, not handled here: this widget owns
    #: the hard-coded defaults, ``BatchSheet`` owns the persisted memory that
    #: also has to be forgotten.
    restore_defaults_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchOutputPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
QWidget#BatchOutputPanel {
    background-color: #ffffff;
}
QLabel#BatchSectionTitle {
    color: #26344a;
    font-size: 12px;
    font-weight: 700;
}
QLabel#BatchSectionNote {
    color: #94a3b8;
    font-size: 10px;
}
QWidget#BatchExportCard {
    background-color: #ffffff;
    border: 1px solid #c8d4e3;
    border-radius: 9px;
}
QWidget#BatchExportCard QLabel#batchOutputSettingsSummary {
    border-top: 1px solid #edf1f6;
    padding-top: 5px;
}
""")

        outer = QVBoxLayout(self)
        self._outer_layout = outer
        outer.setContentsMargins(12, 14, 12, 18)
        outer.setSpacing(12)

        section_head = QWidget(self)
        section_head.setObjectName("BatchOutputSectionHead")
        section_head_lay = QHBoxLayout(section_head)
        section_head_lay.setContentsMargins(0, 0, 0, 0)
        section_head_lay.setSpacing(6)
        title = QLabel("导出", section_head)
        title.setObjectName("BatchSectionTitle")
        section_head_lay.addWidget(title)
        section_head_lay.addStretch(1)
        note = QLabel("仅保留可操作信息", section_head)
        note.setObjectName("BatchSectionNote")
        section_head_lay.addWidget(note)

        # Escape hatch for the remembered preferences. It sits on the 导出
        # section head because that is exactly the scope of what is
        # remembered — output directory, export toggles, tick density and
        # text size all live in this panel and nowhere else.
        self._btn_restore_defaults = QPushButton("恢复默认", section_head)
        self._btn_restore_defaults.setObjectName("batchOutputRestoreDefaults")
        self._btn_restore_defaults.setToolTip(
            "清除记住的导出偏好，恢复输出目录、导出内容与刻度字体的默认值"
        )
        self._btn_restore_defaults.setCursor(Qt.PointingHandCursor)
        self._btn_restore_defaults.setSizePolicy(
            QSizePolicy.Maximum, QSizePolicy.Fixed,
        )
        self._btn_restore_defaults.setStyleSheet("""
QPushButton#batchOutputRestoreDefaults {
    border: none;
    background: transparent;
    color: #94a3b8;
    font-size: 10px;
    /* style.qss's global QPushButton rule sets font-weight: 600 and a
       26px min-height; both have to be answered here or this reads as a
       primary action instead of the section-note aside it sits next to. */
    font-weight: 400;
    min-height: 0;
    padding: 1px 2px;
}
QPushButton#batchOutputRestoreDefaults:hover {
    color: #1769e0;
    text-decoration: underline;
}
""")
        self._btn_restore_defaults.clicked.connect(
            lambda: self.restore_defaults_requested.emit()
        )
        section_head_lay.addWidget(self._btn_restore_defaults)
        outer.addWidget(section_head)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        # macOS defaults this to ``FieldsStayAtSizeHint``, which parks every
        # field at its sizeHint instead of filling the column.  Only fields
        # that actually ask to expand are affected, so the other rows keep
        # their current widths.
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._output_form = form

        # Directory
        self._dir_edit = QLineEdit(self)
        self._dir_edit.setText(default_output_dir())
        self._btn_browse = QPushButton("选择…", self)
        self._btn_browse.clicked.connect(self._choose_dir)
        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(0, 0, 0, 0)
        dir_row.addWidget(self._dir_edit, 1)
        dir_row.addWidget(self._btn_browse)
        form.addRow("输出目录", dir_row)

        # Auto-open the output folder once the run finishes. Visible and
        # on by default -- unlike the fixed-export-contract holders below,
        # this is a live, user-facing toggle.
        self._chk_open_folder = QCheckBox("完成后打开输出文件夹", self)
        self._chk_open_folder.setChecked(True)
        self._chk_open_folder.setToolTip(
            "批处理运行完成（或部分完成）后，自动打开输出目录"
        )
        form.addRow(self._chk_open_folder)

        # Compact export row. Detailed options stay collapsed until the user
        # clicks the settings button immediately after "图片".
        self._chk_data = QCheckBox("数据文件", self)
        self._chk_data.setChecked(True)
        self._chk_image = QCheckBox("图片", self)
        self._chk_image.setChecked(True)
        self._btn_output_settings = QPushButton(self)
        self._btn_output_settings.setObjectName("batchOutputSettingsButton")
        self._btn_output_settings.setCheckable(True)
        self._btn_output_settings.setFixedSize(28, 28)
        self._btn_output_settings.setIcon(
            qta.icon("mdi.tune-vertical", color="#1769e0")
        )
        self._btn_output_settings.setIconSize(QSize(15, 15))
        self._btn_output_settings.setToolTip("固定导出规则")
        self._btn_output_settings.setStyleSheet("""
QPushButton#batchOutputSettingsButton {
    border: 1px solid transparent;
    border-radius: 6px;
    color: #64748b;
    background-color: transparent;
    padding: 0;
}
QPushButton#batchOutputSettingsButton:hover,
QPushButton#batchOutputSettingsButton:checked {
    color: #1769e0;
    background-color: #eaf2ff;
    border-color: #cfe0f8;
}
""")

        export_host = QWidget(self)
        export_host.setObjectName("BatchExportCard")
        export_host.setAttribute(Qt.WA_StyledBackground, True)
        # ``Ignored`` is deliberate and load bearing: it keeps the panel's
        # minimumSizeHint at zero so the whole column still fits 288px (see
        # test_batch_output_panel_fits_288px_column).  It does not cause the
        # collapse on its own — ``Ignored`` carries ExpandFlag, so the field
        # grows as soon as the form's growth policy lets it.  The fix is on
        # the QFormLayout above, not here.
        export_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        export_lay = QVBoxLayout(export_host)
        export_lay.setContentsMargins(9, 8, 9, 8)
        export_lay.setSpacing(5)
        self._export_row_layout = QHBoxLayout()
        self._export_row_layout.setContentsMargins(0, 0, 0, 0)
        # 8px left the two CJK labels touching once the card actually had a
        # width to lay out in — 数据文件's text ran straight into 图片's
        # indicator.
        self._export_row_layout.setSpacing(18)
        self._export_row_layout.addWidget(self._chk_data)
        self._export_row_layout.addWidget(self._chk_image)
        self._export_row_layout.addWidget(self._btn_output_settings)
        self._export_row_layout.addStretch(1)
        export_lay.addLayout(self._export_row_layout)

        self._output_summary = QLabel(self)
        self._output_summary.setObjectName("batchOutputSettingsSummary")
        self._output_summary.setMinimumWidth(0)
        self._output_summary.setWordWrap(True)
        self._output_summary.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred,
        )
        self._output_summary.setStyleSheet(
            "color:#64748b;font-size:10px;padding:1px 0;"
        )
        export_lay.addWidget(self._output_summary)
        form.addRow("导出内容", export_host)

        self._output_settings = QFrame(self)
        self._output_settings.setObjectName("batchOutputSettings")
        self._output_settings.setAttribute(Qt.WA_StyledBackground, True)
        self._output_settings.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Minimum,
        )
        self._output_settings.setStyleSheet("""
QFrame#batchOutputSettings {
    background-color: #fbfcfe;
    border: 1px solid #dce4ef;
    border-radius: 8px;
}
QPushButton#batchOutputSettingsButton:checked {
    color: #1769e0;
    background-color: #eaf2ff;
    border-color: #cfe0f8;
}
""")
        settings_form = QFormLayout(self._output_settings)
        settings_form.setContentsMargins(8, 8, 8, 8)
        settings_form.setHorizontalSpacing(8)
        settings_form.setVerticalSpacing(6)

        # Format
        self._combo_format = QComboBox(self)
        self._combo_format.addItems(["csv", "xlsx"])
        self._combo_format.setCurrentText("xlsx")
        self._compact_field(self._combo_format)
        settings_form.addRow("数据格式", self._combo_format)

        self._combo_image_format = QComboBox(self)
        self._combo_image_format.addItem("PNG", "png")
        self._compact_field(self._combo_image_format)
        settings_form.addRow("图片格式", self._combo_image_format)

        self._combo_image_size = QComboBox(self)
        for label, value in (
            ("1080p · 1920×1080", "1920x1080"),
            ("2K · 2560×1440", "2560x1440"),
            ("4K · 3840×2160", "3840x2160"),
            ("自定义", "custom"),
        ):
            self._combo_image_size.addItem(label, value)
        self._compact_field(self._combo_image_size)
        settings_form.addRow("图片尺寸", self._combo_image_size)

        self._spin_image_width = QSpinBox(self)
        self._spin_image_width.setRange(320, 16384)
        self._spin_image_width.setValue(1920)
        self._spin_image_width.setSuffix(" px")
        self._compact_field(self._spin_image_width)
        settings_form.addRow("自定义宽", self._spin_image_width)

        self._spin_image_height = QSpinBox(self)
        self._spin_image_height.setRange(320, 16384)
        self._spin_image_height.setValue(1080)
        self._spin_image_height.setSuffix(" px")
        self._compact_field(self._spin_image_height)
        settings_form.addRow("自定义高", self._spin_image_height)

        self._combo_image_background = QComboBox(self)
        for label, value in (
            ("白色", "white"),
            ("透明", "transparent"),
            ("深色", "dark"),
        ):
            self._combo_image_background.addItem(label, value)
        self._compact_field(self._combo_image_background)
        settings_form.addRow("图片背景", self._combo_image_background)

        self._combo_image_line_width = QComboBox(self)
        for label, value in (
            ("细 · 1.0 px", 1.0),
            ("中 · 1.5 px", 1.5),
            ("粗 · 2.0 px", 2.0),
        ):
            self._combo_image_line_width.addItem(label, value)
        self._combo_image_line_width.setCurrentIndex(1)
        self._compact_field(self._combo_image_line_width)
        settings_form.addRow("曲线线宽", self._combo_image_line_width)

        self._spin_image_dpi = QSpinBox(self)
        self._spin_image_dpi.setRange(36, 1200)
        self._spin_image_dpi.setValue(144)
        self._spin_image_dpi.setSuffix(" DPI")
        self._compact_field(self._spin_image_dpi)
        settings_form.addRow("PNG DPI", self._spin_image_dpi)

        self._combo_conflict = QComboBox(self)
        for label, value in (
            ("自动编号", "auto_number"),
            ("报错", "error"),
            ("跳过", "skip"),
            ("覆盖", "overwrite"),
        ):
            self._combo_conflict.addItem(label, value)
        self._compact_field(self._combo_conflict)
        settings_form.addRow("文件冲突", self._combo_conflict)

        self._chk_manifest = QCheckBox("写入运行清单", self)
        self._chk_manifest.setChecked(True)
        settings_form.addRow("运行清单", self._chk_manifest)

        self._output_settings.hide()
        form.addRow(self._output_settings)
        outer.addLayout(form)

        self._frf_grouping_row = QFrame(self)
        self._frf_grouping_row.setObjectName("BatchFrfImageGrouping")
        grouping_layout = QHBoxLayout(self._frf_grouping_row)
        grouping_layout.setContentsMargins(0, 0, 0, 0)
        grouping_layout.setSpacing(8)
        grouping_layout.addWidget(QLabel("图片组织", self._frf_grouping_row))
        self._frf_grouping_combo = QComboBox(self._frf_grouping_row)
        self._frf_grouping_combo.addItem("每对一张", "none")
        self._frf_grouping_combo.addItem("按来源叠加", "source")
        self._frf_grouping_combo.addItem("按输入/输出对叠加", "channel")
        self._frf_grouping_combo.setMinimumWidth(0)
        self._frf_grouping_combo.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Fixed,
        )
        grouping_layout.addWidget(self._frf_grouping_combo, 1)
        outer.addWidget(self._frf_grouping_row)
        self._frf_grouping_row.hide()

        self._output_preview = QLabel("运行预览：等待完整配置", self)
        self._output_preview.setObjectName("batchOutputPreview")
        self._output_preview.setWordWrap(True)
        self._output_preview.setStyleSheet(
            "color:#475569;font-size:11px;padding:4px 0;"
        )
        outer.addWidget(self._output_preview)

        self.db_reference_control = make_db_reference_control(self)
        self.spin_db_ref = self.db_reference_control.editor
        self.db_reference_control.set_source_text("dB 参考：等待文件解析")
        self._reference_system_catalog = db_reference.FACTORY_CATALOG_V1
        self._reference_user_catalog = ()
        self._prefer_channel_metadata = True

        axis_group = _make_axis_settings_group(
            self,
            x_label="时间 (X):", x_unit="s",
            x_default_min=0.0, x_default_max=0.0,
            y_label="范围 (Y):", y_unit="",
            y_default_min=0.0, y_default_max=0.0,
            z_default_floor=_GENERIC_DB_Z_RANGE[0],
            z_default_ceiling=_GENERIC_DB_Z_RANGE[1],
            z_default_auto=True,
            x_default_auto=True,
            y_default_auto=True,
            x_auto_summary="全时段",
            y_auto_summary="自动范围",
            z_auto_summary="自动色阶",
            pre_header_rows=(("dB 参考:", self.db_reference_control),),
            amplitude_unit_row_label="幅值单位:",
        )
        self._axis_group = axis_group
        self._db_reference_row = self.db_reference_control.parentWidget()
        # Batch line plots may legitimately use negative engineering values
        # and dB amplitudes.  The shared helper's non-negative Y range is for
        # frequency/order axes, not a universal batch-output constraint.
        for spin in (self.spin_y_min, self.spin_y_max):
            spin.setRange(-1e12, 1e12)
        self._widen_axis_label_column(axis_group)
        self._flatten_axis_group_chrome(axis_group)
        self._z_axis_row = (
            self._axis_row_parts["z"]["label"].parentWidget().parentWidget()
        )
        outer.addWidget(axis_group)
        outer.addWidget(self._build_render_style_row())
        outer.addStretch(1)

        # The compact workflow has one fixed export contract.  Keep the
        # legacy widgets alive only as compatibility holders for old preset
        # readers; they are not an alternate visible configuration surface.
        self._btn_output_settings.hide()
        self._output_settings.hide()
        self._output_preview.hide()
        for widget in (
            self._combo_format, self._combo_image_format,
            self._combo_image_size, self._spin_image_width,
            self._spin_image_height, self._combo_image_background,
            self._combo_image_line_width, self._spin_image_dpi,
            self._combo_conflict, self._chk_manifest,
        ):
            widget.hide()
        self._method = "fft"
        self._axis_state_by_method: dict[str, dict] = {}

        # Wiring
        self._dir_edit.textChanged.connect(lambda *_: self.changed.emit())
        self._chk_open_folder.toggled.connect(lambda *_: self.changed.emit())
        self._chk_data.toggled.connect(lambda *_: self.changed.emit())
        self._chk_data.toggled.connect(lambda *_: self._sync_output_controls())
        self._chk_data.toggled.connect(lambda *_: self._refresh_output_summary())
        self._chk_image.toggled.connect(self._on_image_option_changed)
        self._btn_output_settings.toggled.connect(
            self._on_output_settings_toggled
        )
        self._combo_format.currentTextChanged.connect(lambda *_: self.changed.emit())
        self._combo_format.currentTextChanged.connect(
            lambda *_: self._refresh_output_summary()
        )
        self._combo_image_format.currentIndexChanged.connect(
            self._on_image_option_changed
        )
        self._combo_image_size.currentIndexChanged.connect(
            self._on_image_option_changed
        )
        self._combo_image_background.currentIndexChanged.connect(
            self._on_image_option_changed
        )
        self._combo_image_line_width.currentIndexChanged.connect(
            self._on_image_option_changed
        )
        for spin in (
            self._spin_image_width, self._spin_image_height,
            self._spin_image_dpi,
        ):
            spin.valueChanged.connect(lambda *_: self.changed.emit())
            spin.valueChanged.connect(lambda *_: self._refresh_output_summary())
        self._combo_conflict.currentIndexChanged.connect(
            lambda *_: self.changed.emit()
        )
        self._frf_grouping_combo.currentIndexChanged.connect(
            lambda *_: self.changed.emit()
        )
        self._chk_manifest.toggled.connect(lambda *_: self.changed.emit())
        self.db_reference_control.editor.valueChanged.connect(
            lambda *_: self.changed.emit()
        )
        self.db_reference_control.mode_committed.connect(
            lambda *_: self.changed.emit()
        )
        # User-driven dB↔Linear toggle: per spec §1.4 reset z_auto/z_range
        # to the new unit's defaults. Programmatic ``apply_axis_params``
        # path wraps its own ``setCurrentIndex`` in ``blockSignals`` so
        # preset loads do NOT re-enter this handler. Coalesce the three
        # internal mutations (chk + 2 spins) into a single ``changed``
        # emit (§5 风险 OutputPanel emits).
        for chk in (self.chk_x_auto, self.chk_y_auto, self.chk_z_auto):
            chk.toggled.connect(lambda *_: self.changed.emit())
        for spin in (
            self.spin_x_min, self.spin_x_max,
            self.spin_y_min, self.spin_y_max,
            self.spin_z_floor, self.spin_z_ceiling,
        ):
            spin.valueChanged.connect(lambda *_: self.changed.emit())
        self._apply_method_axis_context("fft")
        self._sync_axis_enabled()
        self._sync_output_controls()
        self._refresh_output_summary()

    @staticmethod
    def _compact_field(widget: QWidget) -> None:
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    # ------------------------------------------------------------------
    # Render style (tick density + text size)
    # ------------------------------------------------------------------
    def _build_render_style_row(self) -> QWidget:
        """Entry point for the export's tick density and text size.

        Sits directly under 坐标范围 because it answers the same question —
        how the axes read — one level up from the numeric ranges.
        """
        self._render_style = RenderStyle()
        self._render_style_popover = None

        row = QWidget(self)
        row.setObjectName("batchRenderStyleRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(6)

        self._render_style_summary = QLabel(row)
        self._render_style_summary.setObjectName("batchRenderStyleSummary")
        self._render_style_summary.setMinimumWidth(0)
        self._render_style_summary.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred,
        )
        self._render_style_summary.setStyleSheet(
            "color:#64748b;font-size:10px;padding:1px 0;"
        )
        layout.addWidget(self._render_style_summary, 1)

        self._btn_render_style = QPushButton("刻度与字体", row)
        self._btn_render_style.setObjectName("batchRenderStyleButton")
        self._btn_render_style.setCheckable(True)
        # Same glyph as the time-domain chart's 刻度密度 button so the two
        # entries read as the same control in two places.
        self._btn_render_style.setIcon(qta.icon("ri.ruler-2-line", color="#1769e0"))
        self._btn_render_style.setIconSize(QSize(14, 14))
        self._btn_render_style.setToolTip("设置导出图片的刻度密度与字体大小")
        self._btn_render_style.setMinimumWidth(0)
        self._btn_render_style.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._btn_render_style.setStyleSheet("""
QPushButton#batchRenderStyleButton {
    border: 1px solid #cfe0f8;
    border-radius: 6px;
    color: #1769e0;
    background-color: #ffffff;
    font-size: 11px;
    padding: 4px 9px;
}
QPushButton#batchRenderStyleButton:hover,
QPushButton#batchRenderStyleButton:checked {
    background-color: #eaf2ff;
    border-color: #a9c9f4;
}
""")
        self._btn_render_style.clicked.connect(self._on_render_style_clicked)
        layout.addWidget(self._btn_render_style)

        self._refresh_render_style_summary()
        return row

    def _on_render_style_clicked(self) -> None:
        popover = self._render_style_popover
        if popover is None:
            popover = RenderStylePopover(self)
            popover.style_changed.connect(self._on_render_style_changed)
            popover.closed.connect(
                lambda: self._btn_render_style.setChecked(False)
            )
            self._render_style_popover = popover
        if popover.isVisible():
            popover.hide()
            self._btn_render_style.setChecked(False)
            return
        popover.set_style(self._render_style, emit=False)
        popover.show_at(self._btn_render_style)
        self._btn_render_style.setChecked(True)

    def _on_render_style_changed(self, style: RenderStyle) -> None:
        if style == self._render_style:
            return
        self._render_style = style
        self._refresh_render_style_summary()
        self.changed.emit()

    def _refresh_render_style_summary(self) -> None:
        style = self._render_style
        self._render_style_summary.setText(
            f"刻度 X {style.tick_density_x} · Y {style.tick_density_y}"
            f" · 字号 {int(round(style.font_scale * 100))}%"
        )

    def render_style(self) -> RenderStyle:
        return self._render_style

    def render_style_params(self) -> dict:
        return self._render_style.as_params()

    def apply_render_style_params(self, params: dict) -> None:
        """Partial-apply: keys absent from *params* keep their current value."""
        if not params:
            return
        current = self._render_style.as_params()
        current.update(
            {key: value for key, value in dict(params).items() if key in current}
        )
        style = render_style_from_params(current)
        if style == self._render_style:
            return
        self._render_style = style
        popover = self._render_style_popover
        if popover is not None:
            popover.set_style(style, emit=False)
        self._refresh_render_style_summary()

    def set_compact_mode(self, compact: bool) -> None:
        side = 12 if compact else 18
        self._outer_layout.setContentsMargins(side, 14, side, 18)

    def _on_image_option_changed(self, _value=None) -> None:
        self._sync_output_controls()
        self._refresh_output_summary()
        self.changed.emit()

    def _on_output_settings_toggled(self, expanded: bool) -> None:
        # Retained for callers from an older dialog; the compact UI never
        # exposes the advanced panel.
        self._output_settings.hide()
        self._btn_output_settings.setChecked(False)

    def _refresh_output_summary(self) -> None:
        parts: list[str] = []
        if self._chk_data.isChecked():
            parts.append("XLSX")
        if self._chk_image.isChecked():
            parts.append("PNG 1920×1080")
        suffix = " · 冲突自动编号" if parts else ""
        self._output_summary.setText(" · ".join(parts) + suffix or "未选择导出内容")

    def _sync_output_controls(self) -> None:
        # Values are fixed by the compact contract; the two checkboxes alone
        # select whether each fixed artifact is requested.
        return

    def _on_amp_unit_changed(self, text: str) -> None:
        """User toggled dB↔Linear on ``combo_amp_unit``.

        Per spec §1.2/§1.4 (2026-05-01-codex-review-fixes): force
        ``z_auto`` ON and reset (z_floor, z_ceiling) to the new unit's
        defaults so the previous unit's numeric range cannot bleed into
        the new unit. Mirrors ``OrderContextual._on_amp_unit_changed`` /
        ``FFTTimeContextual._on_amp_unit_changed`` in
        ``inspector_sections.py``.

        Emit-once mitigation (§5 风险 OutputPanel emits): each mutated
        child widget's own ``toggled`` / ``valueChanged`` signal is
        normally re-emitted as ``self.changed``. To avoid the batch
        preset becoming dirty 3+ times for one user action, block the
        children only (NOT ``self``) while mutating, then emit
        ``changed`` once at the end.
        """
        floor, ceiling = z_range_for(text)
        for w in (self.chk_z_auto, self.spin_z_floor, self.spin_z_ceiling):
            w.blockSignals(True)
        try:
            self.chk_z_auto.setChecked(True)
            self.spin_z_floor.setValue(floor)
            self.spin_z_ceiling.setValue(ceiling)
        finally:
            for w in (self.chk_z_auto, self.spin_z_floor, self.spin_z_ceiling):
                w.blockSignals(False)
        self._sync_axis_enabled()
        self.changed.emit()

    def apply_method_defaults(self, method: str) -> None:
        """Switch axis semantics without leaking ranges between methods.

        X=5..800 means something different in FFT (Hz) and time (seconds).
        Each method therefore owns a small presentation-state snapshot.  A
        first visit gets canonical auto ranges; returning to a method restores
        only that method's prior edits.
        """
        target = str(method)
        previous = str(getattr(self, "_method", "") or "")
        if target == previous:
            self._apply_method_axis_context(target)
            return

        if previous:
            self._axis_state_by_method[previous] = self.axis_params()

        self._apply_method_axis_context(target)
        state = self._axis_state_by_method.get(target)
        if state is None:
            order_heatmap = target == _ORDER_TIME_METHOD
            state = {
                "x_auto": True, "x_min": 0.0, "x_max": 0.0,
                "y_auto": True, "y_min": 0.0, "y_max": 0.0,
                "z_auto": not order_heatmap,
                "z_floor": (
                    _ORDER_TIME_DB_Z_RANGE[0]
                    if order_heatmap else _GENERIC_DB_Z_RANGE[0]
                ),
                "z_ceiling": (
                    _ORDER_TIME_DB_Z_RANGE[1]
                    if order_heatmap else _GENERIC_DB_Z_RANGE[1]
                ),
                "amplitude_mode": "amplitude_db",
            }

        blocker = QSignalBlocker(self)
        try:
            self.apply_axis_params(state)
        finally:
            del blocker
        self._sync_axis_enabled()

    def _apply_method_axis_context(self, method: str) -> None:
        self._method = str(method)
        context = _AXIS_CONTEXTS.get(str(method), _AXIS_CONTEXTS["fft"])
        is_frf = str(method) == "frf"
        self._frf_grouping_row.setVisible(is_frf)
        self._output_preview.setVisible(is_frf)
        self._set_z_axis_visible(str(method) in {"fft_time", "order_time"})
        self._set_amplitude_unit_visible(str(method) not in {"time", "frf"})
        self._set_db_reference_visible(str(method) not in {"time", "frf"})
        for axis, suffix_key in (("x", "x_unit"), ("y", "y_unit")):
            suffix = context[suffix_key]
            text = f" {suffix}" if suffix else ""
            for spin_key in ("spin_min", "spin_max"):
                self._axis_row_parts[axis][spin_key].setSuffix(text)
        self._axis_row_parts["x"]["label"].setText(context["x_label"])
        self._axis_row_parts["x"]["summary"].setText(context["x_summary"])
        self._axis_row_parts["y"]["label"].setText(context["y_label"])
        self._axis_row_parts["y"]["summary"].setText(context["y_summary"])

    def frf_render_params(self) -> dict:
        if self._method != "frf":
            return {}
        return {
            "render_group_by": str(
                self._frf_grouping_combo.currentData() or "none"
            )
        }

    def apply_frf_render_params(self, params) -> None:
        if not isinstance(params, dict) or "render_group_by" not in params:
            return
        index = self._frf_grouping_combo.findData(
            str(params.get("render_group_by") or "none")
        )
        if index >= 0:
            self._frf_grouping_combo.setCurrentIndex(index)

    def set_x_axis_context(self, *, label: str, unit: str = "") -> None:
        """Update the presented X-axis identity without changing the recipe."""
        clean_label = str(label or "X").strip() or "X"
        clean_unit = str(unit or "").strip()
        display = (
            f"{clean_label} ({clean_unit})" if clean_unit else clean_label
        )
        self._axis_row_parts["x"]["label"].setText(display)
        suffix = f" {clean_unit}" if clean_unit else ""
        self.spin_x_min.setSuffix(suffix)
        self.spin_x_max.setSuffix(suffix)

    def _set_z_axis_visible(self, visible: bool) -> None:
        row = getattr(self, "_z_axis_row", None)
        if row is not None:
            row.setVisible(bool(visible))

    def _set_amplitude_unit_visible(self, visible: bool) -> None:
        row = getattr(self, "_amplitude_unit_row", None)
        if row is not None:
            row.setVisible(bool(visible))

    def _set_db_reference_visible(self, visible: bool) -> None:
        row = getattr(self, "_db_reference_row", None)
        if row is not None:
            row.setVisible(bool(visible))

    def _widen_axis_label_column(self, axis_group: QWidget) -> None:
        for parts in self._axis_row_parts.values():
            parts["label"].setMinimumWidth(_BATCH_AXIS_LABEL_W)
            parts["label"].setMaximumWidth(_BATCH_AXIS_LABEL_W)

        header = axis_group.findChild(QWidget, "axisHeaderRow")
        header_layout = header.layout() if header is not None else None
        spacer_item = header_layout.itemAt(0) if header_layout is not None else None
        if spacer_item is not None and spacer_item.spacerItem() is not None:
            spacer_item.spacerItem().changeSize(
                _BATCH_AXIS_LABEL_W,
                0,
                QSizePolicy.Fixed,
                QSizePolicy.Minimum,
            )
            header_layout.invalidate()

    def _flatten_axis_group_chrome(self, axis_group: QWidget) -> None:
        axis_group.setTitle("坐标范围")
        axis_group.setProperty("batchAxisCard", True)
        axis_group.setStyleSheet("""
QGroupBox#axisSettingsGroup {
    margin-top: 14px;
    padding: 17px 9px 9px 9px;
    border: 1px solid #c8d4e3;
    border-radius: 9px;
    background-color: #ffffff;
}
QGroupBox#axisSettingsGroup::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 2px 6px;
    color: #26344a;
    font-size: 12px;
    font-weight: 700;
    background-color: #ffffff;
}
QGroupBox#axisSettingsGroup QWidget#axisRow,
QGroupBox#axisSettingsGroup QWidget#axisRowLine,
QGroupBox#axisSettingsGroup QWidget#axisAutoCell,
QGroupBox#axisSettingsGroup QWidget#axisRangeHost,
QGroupBox#axisSettingsGroup QWidget#axisRangeSummaryPage,
QGroupBox#axisSettingsGroup QWidget#axisManualRangePage,
QGroupBox#axisSettingsGroup QWidget#axisUnitLine,
QGroupBox#axisSettingsGroup QWidget#axisHeaderRow,
QGroupBox#axisSettingsGroup QWidget#axisHeaderRange {
    border: 0;
    background-color: transparent;
}
QGroupBox#axisSettingsGroup QLabel[axisHeader="true"] {
    color: #97a1b2;
    font-size: 11px;
    font-weight: 500;
    background-color: transparent;
}
QGroupBox#axisSettingsGroup QWidget#axisRow {
    border-bottom: 1px solid #edf1f6;
}
""")

    def _is_method_default_z_state(self) -> bool:
        if self.combo_amp_unit.currentText() != "dB":
            return False
        current = (
            bool(self.chk_z_auto.isChecked()),
            float(self.spin_z_floor.value()),
            float(self.spin_z_ceiling.value()),
        )
        method_defaults = (
            (True, *_GENERIC_DB_Z_RANGE),
            (False, *_ORDER_TIME_DB_Z_RANGE),
        )
        return any(
            current[0] is default[0]
            and abs(current[1] - default[1]) < 1e-9
            and abs(current[2] - default[2]) < 1e-9
            for default in method_defaults
        )

    def _sync_axis_enabled(self) -> None:
        for key in ("x", "y", "z"):
            parts = self._axis_row_parts[key]
            auto = parts["checkbox"].isChecked()
            parts["stack"].setCurrentWidget(
                parts["summary_page"] if auto else parts["manual_page"]
            )
            parts["summary_page"].setVisible(auto)
            parts["manual_page"].setVisible(not auto)
            parts["summary"].setVisible(auto)
            for w in (parts["spin_min"], parts["arrow"], parts["spin_max"]):
                w.setVisible(not auto)
                w.setEnabled(not auto)

    # ------------------------------------------------------------------
    def _choose_dir(self) -> None:
        start = self._dir_edit.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", start)
        if path:
            self._dir_edit.setText(path)

    # ------------------------------------------------------------------
    def directory(self) -> str:
        return self._dir_edit.text().strip()

    def open_folder_after_run(self) -> bool:
        return bool(self._chk_open_folder.isChecked())

    def apply_open_folder_after_run(self, value: bool) -> None:
        blocker = QSignalBlocker(self._chk_open_folder)
        try:
            self._chk_open_folder.setChecked(bool(value))
        finally:
            del blocker

    def get_outputs(self) -> BatchOutput:
        """Return the sole authoritative portable output configuration.

        ``write_manifest`` is always ``False``: the GUI has never consumed
        the runner's ``.tracelab/runs/batch-manifest__*.json`` (no resume /
        retry / provenance entry point is exposed here), so a run that only
        ever gets triggered from this panel must not leave one behind.
        """
        return BatchOutput(
            export_data=bool(self._chk_data.isChecked()),
            export_image=bool(self._chk_image.isChecked()),
            data_format="xlsx",
            image_format="png",
            image_size="1920x1080",
            image_width=1920,
            image_height=1080,
            image_dpi=144,
            image_background="white",
            image_line_width=1.5,
            conflict_policy="auto_number",
            write_manifest=False,
            resume_policy="none",
        )

    def export_data(self) -> bool:
        return self.get_outputs().export_data

    def export_image(self) -> bool:
        return self.get_outputs().export_image

    def data_format(self) -> str:
        return self.get_outputs().data_format

    def reference_params(self) -> dict:
        if getattr(self, "_method", "fft") == "time":
            return {}
        return db_reference_params(self.db_reference_control)

    def apply_reference_params(self, params: dict, *, legacy: bool = False) -> None:
        if not params or getattr(self, "_method", "fft") == "time":
            return
        if legacy:
            apply_db_reference_preset(self.db_reference_control, params)
        else:
            apply_db_reference_partial(self.db_reference_control, params)

    def set_reference_catalog(self, snapshot=None) -> None:
        if snapshot is None:
            self._reference_system_catalog = db_reference.FACTORY_CATALOG_V1
            self._reference_user_catalog = ()
            self._prefer_channel_metadata = True
            return
        self._reference_system_catalog = tuple(
            getattr(snapshot, "system_catalog", ()) or ()
        )
        self._reference_user_catalog = tuple(
            getattr(snapshot, "user_catalog", ()) or ()
        )
        self._prefer_channel_metadata = bool(
            getattr(snapshot, "prefer_channel_metadata", True)
        )

    def effective_preview_text(self) -> str:
        return self.db_reference_control.full_source_text()

    def output_preview_text(self) -> str:
        return self._output_preview.text()

    def set_output_preview(self, preview=None, *, error: str = "") -> None:
        if error:
            self._output_preview.setText(f"运行预览不可用：{error}")
            return
        if preview is None:
            self._output_preview.setText("运行预览：等待完整配置")
            return
        estimate = "预估" if bool(getattr(preview, "estimated", False)) else "预览"
        fmt = str(getattr(preview, "image_format", "")).upper()
        size = (
            f"{int(getattr(preview, 'image_width', 0))}×"
            f"{int(getattr(preview, 'image_height', 0))}"
        )
        dpi = int(getattr(preview, "image_dpi", 0))
        if self._method == "frf":
            representative = getattr(preview, "representative_group", None)
            stem = str(getattr(representative, "planned_stem", "") or "")
            stem_text = f"；文件名 {stem}" if stem else ""
            self._output_preview.setText(
                f"{estimate}：{int(getattr(preview, 'task_count', 0))} 任务 · "
                f"{int(getattr(preview, 'data_artifact_count', 0))} 数据 · "
                f"{int(getattr(preview, 'image_artifact_count', 0))} 图片组 · "
                f"{int(getattr(preview, 'conflict_count', 0))} 冲突；"
                f"数据列 12 列；{fmt} {size} @ {dpi} DPI；"
                "元数据预估，真实时基/分段尚未预检"
                f"{stem_text}"
            )
            return
        self._output_preview.setText(
            f"{estimate}：{int(getattr(preview, 'task_count', 0))} 任务 · "
            f"{int(getattr(preview, 'artifact_count', 0))} 文件；"
            f"{fmt} {size} @ {dpi} DPI；"
            f"冲突策略 {getattr(preview, 'conflict_policy', '')} · "
            f"已有冲突 {int(getattr(preview, 'conflict_count', 0))}"
        )

    def update_effective_preview(
        self,
        rows,
        signals,
        *,
        weighting: str = "None",
        target_policy: str = "common",
        target_pairs=(),
    ) -> None:
        """Resolve the recipe-owned reference from cached probe facts only."""
        if getattr(self, "_method", "fft") == "time":
            # No visual dB state exists for time-domain output.
            return
        rows = tuple(rows or ())
        if any(
            getattr(row, "state", "") in {"path_pending", "probing"}
            for row in rows
        ):
            self._set_effective_preview("dB 参考：等待文件解析")
            return
        loaded = tuple(
            row for row in rows if getattr(row, "state", "") == "loaded"
        )
        signals = tuple(str(signal) for signal in (signals or ()))
        if not loaded:
            self._set_effective_preview("dB 参考：等待文件解析")
            return
        if not signals and not target_pairs:
            self._set_effective_preview("dB 参考：请选择目标信号")
            return

        exact = {
            (pair[0], str(pair[1]))
            for pair in (target_pairs or ())
            if isinstance(pair, (tuple, list)) and len(pair) == 2
        }
        groups: dict[tuple, int] = {}
        for row in loaded:
            source_id = getattr(row, "source_id", None)
            available = frozenset(getattr(row, "channels", ()) or ())
            candidates = signals
            if exact:
                candidates = tuple(
                    signal for sid, signal in exact if sid == source_id
                )
            for signal in candidates:
                if signal not in available:
                    # Missing common/available/exact targets are not
                    # resolvable and therefore never enter the reference
                    # preview count. Preflight surfaces the scope error.
                    continue
                resolution = self._resolve_preview_reference(row, signal)
                note = db_reference.format_reference_note(
                    resolution, weighting=str(weighting or "None"),
                )
                source = str(resolution.source)
                quantity = str(resolution.quantity or "")
                source_label = source
                if source == "system" and quantity:
                    source_label = f"system {quantity}"
                key = (source_label, note, resolution.warning or "")
                groups[key] = groups.get(key, 0) + 1
        if not groups:
            self._set_effective_preview("dB 参考：所选目标缺少可用单位/来源")
            return
        total = sum(groups.values())
        parts = [
            f"{count}×{source_label} · {note}"
            + (" ⚠" if warning else "")
            for (source_label, note, warning), count in groups.items()
        ]
        self._set_effective_preview(
            f"dB 参考：{total} 个目标：" + "；".join(parts)
        )

    def _resolve_preview_reference(self, row, signal: str):
        metadata = dict(getattr(row, "metadata", {}) or {})
        channel_metadata = metadata.get("channel_metadata") or {}
        facts = dict(channel_metadata.get(signal) or {})
        unit = facts.get("unit") or dict(
            getattr(row, "units", {}) or {}
        ).get(signal, "")
        channel_facts = db_reference.ChannelReferenceFacts(
            quantity=str(facts.get("quantity") or ""),
            unit=db_reference.canonicalize_source_unit(unit),
            metadata_reference=facts.get("db_reference"),
            is_audio_source=metadata.get("adapter_key") == "media",
        )
        params = self.reference_params()
        return db_reference.resolve_db_reference(
            mode=params["db_reference_mode"],
            manual_value=params["db_reference"],
            facts=channel_facts,
            user_catalog=self._reference_user_catalog,
            system_catalog=self._reference_system_catalog,
            prefer_channel_metadata=self._prefer_channel_metadata,
        )

    def _set_effective_preview(self, text: str) -> None:
        self.db_reference_control.set_source_text(str(text))

    # ------------------------------------------------------------------
    def apply_directory(self, path: str) -> None:
        self._dir_edit.setText(str(path or ""))

    def apply_outputs(self, out: BatchOutput) -> None:
        if out is None:
            return
        widgets = (self._chk_data, self._chk_image)
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self._chk_data.setChecked(bool(out.export_data))
            self._chk_image.setChecked(bool(out.export_image))
        finally:
            del blockers
        self._sync_output_controls()
        self._refresh_output_summary()

    def restore_defaults(self) -> None:
        """Reset every persisted display preference to its hard-coded default.

        Deliberately narrow: axes, dB reference, analysis parameters and the
        source/signal scope are NOT preferences and are left exactly as the
        user has them (they are also never persisted — see
        ``mf4_analyzer.ui.batch_settings``).
        """
        self.apply_directory(default_output_dir())
        self.apply_open_folder_after_run(True)
        self.apply_render_style_params(RenderStyle().as_params())
        self.apply_outputs(BatchOutput())

    @staticmethod
    def _set_combo_data(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def axis_params(self) -> dict:
        params = {
            "x_auto": bool(self.chk_x_auto.isChecked()),
            "x_min": float(self.spin_x_min.value()),
            "x_max": float(self.spin_x_max.value()),
            "y_auto": bool(self.chk_y_auto.isChecked()),
            "y_min": float(self.spin_y_min.value()),
            "y_max": float(self.spin_y_max.value()),
            "z_auto": bool(self.chk_z_auto.isChecked()),
            "z_floor": float(self.spin_z_floor.value()),
            "z_ceiling": float(self.spin_z_ceiling.value()),
            "amplitude_mode": (
                "amplitude_db"
                if self.combo_amp_unit.currentText() == "dB"
                else "amplitude"
            ),
        }
        if getattr(self, "_method", "fft") in {"time", "frf"}:
            params.pop("z_auto", None)
            params.pop("z_floor", None)
            params.pop("z_ceiling", None)
            params.pop("amplitude_mode", None)
        return params

    def apply_axis_params(self, params: dict) -> None:
        if not params:
            return
        # Apply combo_amp_unit FIRST under blockSignals so the W2
        # ``_on_amp_unit_changed`` reset handler does NOT fire on
        # programmatic preset loads (§1.5 边界: programmatic setters
        # must round-trip the user's persisted z_floor/z_ceiling/z_auto
        # intact). Apply checkboxes + spins AFTERWARD so the preset's
        # numbers win irrespective of any handler that did slip through.
        amplitude_value = params.get("amplitude_mode", params.get("amp_y"))
        if amplitude_value is not None:
            raw = str(amplitude_value)
            target = "dB" if "db" in raw.lower() else "Linear"
            idx = self.combo_amp_unit.findText(target)
            if idx >= 0:
                self.combo_amp_unit.blockSignals(True)
                try:
                    self.combo_amp_unit.setCurrentIndex(idx)
                finally:
                    self.combo_amp_unit.blockSignals(False)
        for key, widget in (
            ("x_auto", self.chk_x_auto),
            ("y_auto", self.chk_y_auto),
            ("z_auto", self.chk_z_auto),
        ):
            if key in params:
                widget.setChecked(bool(params[key]))
        for key, widget in (
            ("x_min", self.spin_x_min), ("x_max", self.spin_x_max),
            ("y_min", self.spin_y_min), ("y_max", self.spin_y_max),
            ("z_floor", self.spin_z_floor), ("z_ceiling", self.spin_z_ceiling),
        ):
            if key in params:
                try:
                    widget.setValue(float(params[key]))
                except (TypeError, ValueError):
                    pass
        self._sync_axis_enabled()
