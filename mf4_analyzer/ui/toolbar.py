"""Top three-segment toolbar: file actions · mode switcher · canvas actions."""
from PyQt5.QtCore import QEvent, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMenu,
    QPushButton, QSizePolicy, QWidget,
)

from .. import app_meta
from ..ui_kit.icons import Icons
from ..ui_kit.menus import apply_rounded_menu_chrome

_MODE_LABELS = {
    "time": "时域",
    "fft": "频谱",
    "fft_time": "时频",
    "order": "阶次",
    "frf": "频响",
}

# Icon-only half of the save split. Keep this tighter than a labeled chip so
# 打开 / 保存 / 批处理 can share one width instead of the caret dominating.
_SAVE_CARET_WIDTH = 20


def _make_sep(parent):
    sep = QFrame(parent)
    sep.setFrameShape(QFrame.VLine)
    sep.setFixedWidth(1)
    sep.setStyleSheet("background: #eef2f7; border: none;")
    return sep


def _make_mode_zone_divider(parent):
    """Return one symmetrical boundary marker for the analysis-mode zone."""
    divider = QFrame(parent)
    divider.setObjectName("modeZoneDivider")
    divider.setFixedSize(8, 16)
    tick = QFrame(divider)
    tick.setObjectName("modeZoneDividerTick")
    tick.setFixedSize(3, 8)
    tick.move(2, 4)
    return divider


class _LogoLabel(QLabel):
    """Brand logo that doubles as a hidden Cockpit entry.

    Three rapid left-clicks emit :pyattr:`triple_clicked`. The gesture is
    deliberately undiscoverable — the cursor and tooltip are unchanged, so
    the logo looks and behaves exactly like a static brand mark.

    Qt promotes the second press of a fast sequence into a
    ``mouseDoubleClickEvent`` (not a second ``mousePressEvent``), so we count
    both event kinds. A single-shot timer keyed to the platform double-click
    interval resets the counter once the clicks stop, so only *consecutive*
    clicks accumulate toward the gesture.
    """

    triple_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._clicks = 0
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._clear)

    def _clear(self):
        self._clicks = 0

    def _register_click(self):
        self._clicks += 1
        if self._clicks >= 3:
            self._clicks = 0
            self._reset_timer.stop()
            self.triple_clicked.emit()
        else:
            self._reset_timer.start(QApplication.doubleClickInterval())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._register_click()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._register_click()
        super().mouseDoubleClickEvent(event)


class Toolbar(QWidget):
    # Left segment
    open_requested = pyqtSignal()
    save_project_requested = pyqtSignal()
    save_project_as_requested = pyqtSignal()
    batch_requested = pyqtSignal()
    ultraview_requested = pyqtSignal()
    # Center segment
    mode_changed = pyqtSignal(str)  # time | fft | fft_time | frf | order
    # Right segment
    acquisition_cockpit_requested = pyqtSignal()
    # Panel toggle signals
    nav_panel_toggled = pyqtSignal()
    inspector_panel_toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("surfaceTopBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedHeight(44)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        # ── panel toggle buttons ─────────────────────────────────────────────
        self.btn_toggle_nav = QPushButton(self)
        self.btn_toggle_nav.setIcon(Icons.panel_left())
        self.btn_toggle_nav.setIconSize(QSize(16, 16))
        self.btn_toggle_nav.setCheckable(True)
        self.btn_toggle_nav.setProperty("role", "panel-toggle")
        self.btn_toggle_nav.setToolTip("收起/展开左侧导航")
        self.btn_toggle_nav.setFixedSize(28, 22)

        self.btn_toggle_inspector = QPushButton(self)
        self.btn_toggle_inspector.setIcon(Icons.panel_right())
        self.btn_toggle_inspector.setIconSize(QSize(16, 16))
        self.btn_toggle_inspector.setCheckable(True)
        self.btn_toggle_inspector.setProperty("role", "panel-toggle")
        self.btn_toggle_inspector.setToolTip("收起/展开右侧检查器")
        self.btn_toggle_inspector.setFixedSize(28, 22)

        # ── left group ──────────────────────────────────────────────────────
        self.btn_add = QPushButton("打开", self)
        self.btn_add.setIcon(Icons.add_file(QColor("#ffffff")))
        # Opening data is the primary entry point; retain its filled cue while
        # save/save-as/batch remain secondary file actions.
        self.btn_add.setProperty("role", "primary")
        self.btn_add.setToolTip("打开数据文件或项目（.tlproj）")
        self._save_split = self._make_save_split()
        self.btn_batch = QPushButton("批处理", self)
        self.btn_batch.setIcon(Icons.batch())
        self.btn_ultraview = QPushButton("总览", self)
        self.btn_ultraview.setIcon(Icons.mode_ultraview())
        self.btn_ultraview.setToolTip("总览（独立面板，只读对照已有预览）")
        for button in (
            self.btn_save_project, self.btn_save_caret, self.btn_batch,
            self.btn_ultraview,
        ):
            button.setProperty("role", "secondary")

        # ── center mode segment ─────────────────────────────────────────────
        self.btn_mode_time = QPushButton("时域", self)
        self.btn_mode_time.setIcon(Icons.mode_time())
        self.btn_mode_time.setToolTip("时域（Time Domain）")
        self.btn_mode_fft = QPushButton("频谱", self)
        self.btn_mode_fft.setIcon(Icons.mode_fft())
        self.btn_mode_fft.setToolTip("频谱（FFT）")
        self.btn_mode_fft_time = QPushButton("时频", self)
        self.btn_mode_fft_time.setIcon(Icons.mode_fft_time())
        self.btn_mode_fft_time.setToolTip("时频（FFT vs Time）")
        self.btn_mode_frf = QPushButton("频响", self)
        self.btn_mode_frf.setIcon(Icons.mode_frf())
        self.btn_mode_frf.setToolTip("频响（FRF / 系统辨识）")
        self.btn_mode_order = QPushButton("阶次", self)
        self.btn_mode_order.setIcon(Icons.mode_order())
        self.btn_mode_order.setToolTip("阶次（Order）")
        # Kept for compatibility with older tests/screenshots; UltraView is a
        # standalone tool window now, so this sixth mode button stays hidden.
        self.btn_mode_ultraview = QPushButton("总览", self)
        self.btn_mode_ultraview.setIcon(Icons.mode_ultraview())
        self.btn_mode_ultraview.setToolTip("总览（UltraView）")
        self.btn_mode_ultraview.hide()

        for b in (self.btn_add, self.btn_save_project,
                  self.btn_batch, self.btn_ultraview,
                  self.btn_mode_time, self.btn_mode_fft, self.btn_mode_fft_time,
                  self.btn_mode_frf, self.btn_mode_order, self.btn_mode_ultraview):
            b.setIconSize(QSize(16, 16))
        self.btn_save_caret.setIconSize(QSize(12, 12))

        # left layout
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        for b in (
            self.btn_add,
            self._save_split,
            self.btn_batch,
            self.btn_ultraview,
        ):
            left.addWidget(b, 0, Qt.AlignVCenter)

        # Wrap left in a QWidget so it has a concrete sizeHint that the
        # stretch arithmetic can balance against.
        left_widget = QWidget(self)
        left_widget.setLayout(left)
        left_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        left_widget.setObjectName("toolbarLeftGroup")

        # Center modes live in a self-contained zone.  Its equal inner layout
        # gaps keep both boundary markers at the same perceived distance from
        # the first/last mode button; the whole zone is then centered by the
        # balanced outer side hosts below.
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)
        segment_frame = QFrame(self)
        segment_frame.setObjectName("modeSegment")
        segment_frame.setLayout(center)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_active_dots = {}
        for key, b in self._mode_button_pairs():
            b.setCheckable(True)
            b.setProperty("segment", key)
            self._mode_group.addButton(b)
            center.addWidget(b, 0, Qt.AlignVCenter)
            dot = QFrame(b)
            dot.setObjectName("modeActiveDot")
            dot.setFixedSize(6, 6)
            dot.hide()
            self._mode_active_dots[key] = dot

        mode_zone = QFrame(self)
        mode_zone.setObjectName("toolbarModeZone")
        mode_zone.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        mode_zone_layout = QHBoxLayout(mode_zone)
        mode_zone_layout.setContentsMargins(6, 0, 6, 0)
        mode_zone_layout.setSpacing(12)
        left_mode_divider = _make_mode_zone_divider(mode_zone)
        right_mode_divider = _make_mode_zone_divider(mode_zone)
        mode_zone_layout.addWidget(left_mode_divider, 0, Qt.AlignVCenter)
        mode_zone_layout.addWidget(segment_frame, 0, Qt.AlignVCenter)
        mode_zone_layout.addWidget(right_mode_divider, 0, Qt.AlignVCenter)

        # ── right layout ────────────────────────────────────────────────────
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addStretch(1)

        self._logo_label = _LogoLabel(self)
        self._logo_label.setToolTip("博世华域转向系统有限公司")
        _logo_src = QPixmap(str(app_meta.asset_path("branding", "bosch_hasco_logo.png")))
        if not _logo_src.isNull():
            _app = QApplication.instance()
            _dpr = _app.devicePixelRatio() if _app is not None else 1.0
            _dpr = _dpr if _dpr and _dpr >= 1.0 else 1.0
            _scaled = _logo_src.scaledToWidth(int(190 * _dpr), Qt.SmoothTransformation)
            _scaled.setDevicePixelRatio(_dpr)
            self._logo_label.setPixmap(_scaled)
        right.addWidget(self._logo_label)

        # A right widget of the same fixed width as left_widget keeps the
        # segment_frame exactly centered while hosting right-aligned controls.
        right_widget = QWidget(self)
        right_widget.setLayout(right)
        right_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        right_widget.setObjectName("toolbarRightGroup")

        lay.addWidget(self.btn_toggle_nav)
        lay.addWidget(_make_sep(self))
        lay.addWidget(left_widget)
        lay.addStretch(1)
        lay.addWidget(mode_zone)
        lay.addStretch(1)
        lay.addWidget(right_widget)
        lay.addWidget(_make_sep(self))
        lay.addWidget(self.btn_toggle_inspector)

        self.btn_mode_time.setChecked(True)
        self._current_mode = 'time'
        self._mode_compact = False
        self._left_action_chip_width = 0

        # Keep mirror width in sync with left_widget after layout is settled.
        self._left_widget = left_widget
        self._right_widget = right_widget
        self._left_layout = left
        self._right_layout = right
        self._mode_zone = mode_zone
        self._mode_segment = segment_frame
        self._mode_zone_dividers = (left_mode_divider, right_mode_divider)
        self._pending_mirror_sync = False
        self._left_widget.installEventFilter(self)
        self._right_widget.installEventFilter(self)
        self._wire()
        self._sync_mode_active_dots()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._equalize_left_action_widths()
        self._sync_mirror()
        self._apply_mode_compact()
        self._sync_mode_active_dots()

    def showEvent(self, event):
        super().showEvent(event)
        self._equalize_left_action_widths()
        self._sync_mirror()
        self._apply_mode_compact()
        self._sync_mode_active_dots()

    def eventFilter(self, watched, event):
        if watched in (self._left_widget, self._right_widget) and event.type() in (
            QEvent.ChildAdded,
            QEvent.ChildRemoved,
            QEvent.LayoutRequest,
        ):
            self._schedule_mirror_sync()
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QColor("#dbe2eb"))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
        painter.end()
        super().paintEvent(event)

    def _sync_mirror(self):
        """Balance both side hosts so the analysis mode zone stays centered."""
        w = max(
            self._left_layout.sizeHint().width(),
            self._right_layout.sizeHint().width(),
            1,
        )
        # Fix both hosts to the same content-aware width.  Mirroring only the
        # right side works while left content grows, but would shift the zone
        # when a future top-level action is added on the right.
        if self._left_widget.width() != w:
            self._left_widget.setFixedWidth(w)
        if self._right_widget.width() != w:
            self._right_widget.setFixedWidth(w)

    def _schedule_mirror_sync(self):
        if self._pending_mirror_sync:
            return
        self._pending_mirror_sync = True
        QTimer.singleShot(0, self._run_scheduled_mirror_sync)

    def _run_scheduled_mirror_sync(self):
        self._pending_mirror_sync = False
        self._equalize_left_action_widths()
        self._sync_mirror()
        self._apply_mode_compact()

    def _mode_button_pairs(self):
        return (
            ("time", self.btn_mode_time),
            ("fft", self.btn_mode_fft),
            ("fft_time", self.btn_mode_fft_time),
            ("order", self.btn_mode_order),
            ("frf", self.btn_mode_frf),
        )

    def _labeled_mode_zone_width(self) -> int:
        fm = self.fontMetrics()
        buttons = 0
        for key, _button in self._mode_button_pairs():
            text_w = fm.horizontalAdvance(_MODE_LABELS[key])
            buttons += max(60, 16 + 4 + text_w + 20) + 2
        return 12 + 16 + 24 + 4 + buttons

    def _mode_zone_budget(self) -> int:
        left = max(self._left_widget.width(), self._left_widget.sizeHint().width(), 1)
        nav = max(self.btn_toggle_nav.width(), 28)
        insp = max(self.btn_toggle_inspector.width(), 28)
        chrome = nav + insp + 2 + (left * 2) + 40
        return max(0, self.width() - chrome)

    def _apply_mode_compact(self) -> None:
        need = self._mode_zone_budget() < self._labeled_mode_zone_width()
        if need == self._mode_compact:
            return
        self._mode_compact = need
        for key, button in self._mode_button_pairs():
            button.setText("" if need else _MODE_LABELS[key])
            button.setProperty("compact", "true" if need else "false")
            style = button.style()
            style.unpolish(button)
            style.polish(button)
        self._mode_segment.updateGeometry()
        self._mode_zone.updateGeometry()
        self._sync_mode_active_dots()

    def is_mode_compact(self) -> bool:
        return bool(self._mode_compact)

    def _sync_mode_active_dots(self):
        for key, button in self._mode_button_pairs():
            dot = self._mode_active_dots[key]
            dot.move(max(0, button.width() - dot.width() - 5), 4)
            dot.setVisible(button.isChecked())

    def _left_action_chips(self):
        return (
            self.btn_add,
            self._save_split,
            self.btn_batch,
            self.btn_ultraview,
        )

    def _equalize_left_action_widths(self):
        """Give 打开 / 保存 / 批处理 / 总览 one shared chip width."""
        chips = self._left_action_chips()
        if self._left_action_chip_width and all(
            chip.minimumWidth() == self._left_action_chip_width for chip in chips
        ):
            return
        for chip in chips:
            chip.setMinimumWidth(0)
        target = max(chip.sizeHint().width() for chip in chips)
        self._left_action_chip_width = target
        for chip in chips:
            chip.setMinimumWidth(target)
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _make_save_split(self):
        """One secondary chip: 保存 runs now; the caret opens 另存为."""
        host = QWidget(self)
        host.setObjectName("toolbarSaveSplit")
        host.setAttribute(Qt.WA_StyledBackground, True)
        host.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.btn_save_project = QPushButton("保存", host)
        self.btn_save_project.setObjectName("toolbarSaveMain")
        self.btn_save_project.setIcon(Icons.save_disk())
        self.btn_save_project.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.btn_save_project.setToolTip(
            "保存到当前 .tlproj 项目（未保存过则提示选择路径）"
        )

        self.btn_save_caret = QPushButton(host)
        self.btn_save_caret.setObjectName("toolbarSaveCaret")
        self.btn_save_caret.setIcon(Icons.chevron_down(QColor("#1769E0")))
        self.btn_save_caret.setFixedWidth(_SAVE_CARET_WIDTH)
        self.btn_save_caret.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_save_caret.setToolTip("另存为…")
        self.btn_save_caret.setAccessibleName("另存为")

        self._save_menu = apply_rounded_menu_chrome(QMenu(host))
        self.btn_save_project_as = self._save_menu.addAction("另存为")
        self.btn_save_project_as.setIcon(Icons.save_disk())
        self.btn_save_project_as.setToolTip("将当前会话另存为新的 .tlproj 项目")

        row.addWidget(self.btn_save_project, 1)
        row.addWidget(self.btn_save_caret, 0)
        return host

    def _open_save_menu(self):
        host = self._save_split
        self._save_menu.popup(host.mapToGlobal(host.rect().bottomLeft()))

    def _emit_save_project_as(self, _checked=False):
        self.save_project_as_requested.emit()

    def _wire(self):
        self.btn_add.clicked.connect(self.open_requested)
        self.btn_save_project.clicked.connect(self.save_project_requested)
        self.btn_save_caret.clicked.connect(self._open_save_menu)
        self.btn_save_project_as.triggered.connect(self._emit_save_project_as)
        self.btn_batch.clicked.connect(self.batch_requested)
        self.btn_ultraview.clicked.connect(self.ultraview_requested)
        # Hidden Cockpit entry: triple-click the brand logo (see _LogoLabel).
        self._logo_label.triple_clicked.connect(self.acquisition_cockpit_requested)
        for key, b in self._mode_button_pairs():
            b.clicked.connect(lambda _=False, k=key: self._set_mode(k))
        self.btn_toggle_nav.clicked.connect(self.nav_panel_toggled)
        self.btn_toggle_inspector.clicked.connect(self.inspector_panel_toggled)

    def _set_mode(self, mode):
        mapping = dict(self._mode_button_pairs())
        if mode not in mapping:
            mode = "time"
        if mode == self._current_mode:
            return
        self._current_mode = mode
        mapping[mode].setChecked(True)
        self._sync_mode_active_dots()
        self.mode_changed.emit(mode)

    def set_enabled_for_mode(self, mode, has_file):
        """Implements the §7.1 enabled-state matrix."""
        self._save_split.setEnabled(has_file)
        self.btn_save_project_as.setEnabled(has_file)
        self.btn_batch.setEnabled(True)
        self.btn_ultraview.setEnabled(True)

    def current_mode(self):
        return self._current_mode

    def set_nav_open(self, open: bool):
        """Sync the nav toggle button checked state (checked = panel hidden)."""
        self.btn_toggle_nav.setChecked(not open)

    def set_inspector_open(self, open: bool):
        """Sync the inspector toggle button checked state (checked = panel hidden)."""
        self.btn_toggle_inspector.setChecked(not open)
