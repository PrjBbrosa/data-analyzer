"""Explicit diagnostic host for the native interaction-motion pilot.

Importing this module must not create a ``QApplication``, open a window, or
install application QSS. Runtime chrome and QSettings isolation happen in
:func:`main` only.

S01–S07 host production widgets or the light-page sample, each with an
explicit motion policy. Ordinary product launch is unchanged.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PyQt5.QtCore import QEvent, QObject, QSettings, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QGraphicsOpacityEffect,
)

from mf4_analyzer.app_meta import APP_NAME
from mf4_analyzer.ui.view_state import TIME_DOMAIN_MAX_VIEWS, ViewManager
from mf4_analyzer.ui.view_tabbar import ViewTabBar
from mf4_analyzer.ui.widgets.pill_switch import PillSwitch, PillSwitchLabel
from mf4_analyzer.ui_kit.fonts import setup_chinese_font
from mf4_analyzer.ui_kit.widgets.segmented_choice import SegmentedChoice
from mf4_analyzer.ui_kit.motion import (
    POLICY_LIGHT,
    POLICY_OFF,
    POLICY_REDUCED,
    MotionPolicy,
    ValueDriver,
    duration_ms,
    resolve_policy,
)
from mf4_analyzer.ui_kit.stylesheet import load_stylesheet

PROD_SETTINGS_ORG = "MF4Analyzer"
PROD_SETTINGS_APP = "DataAnalyzer"
PAGE_VIEWPORT_MAX = (640, 420)
SAMPLE_IDS = ("S01", "S02", "S03", "S04", "S05", "S06", "S07")
PLACEHOLDER_IDS = SAMPLE_IDS[:-1]

_APP_BOOTSTRAPPED = False
_ISOLATED_SETTINGS_DIR: Path | None = None
_ISOLATED_SETTINGS_INI: Path | None = None
_QSETTINGS_INIT_ORIG = None

_INPUT_EVENTS = {
    QEvent.KeyPress,
    QEvent.MouseButtonPress,
    QEvent.Wheel,
    QEvent.InputMethod,
}
_SETTINGS_FORMATS = {
    QSettings.NativeFormat,
    QSettings.IniFormat,
    QSettings.InvalidFormat,
}


def install_isolated_qsettings(settings_dir: Path) -> Path:
    """Divert NativeFormat and two-arg production settings to *settings_dir*.

    ``QSettings(organization, application)`` ignores ``setDefaultFormat`` and
    on macOS NativeFormat also ignores ``setPath``. Changing
    ``applicationName`` alone is not enough; the constructor itself is
    redirected to a temporary INI.
    """
    global _ISOLATED_SETTINGS_DIR, _ISOLATED_SETTINGS_INI, _QSETTINGS_INIT_ORIG

    settings_dir = Path(settings_dir)
    settings_dir.mkdir(parents=True, exist_ok=True)
    isolated_ini = settings_dir / "MF4Analyzer-DataAnalyzer.ini"

    QSettings.setDefaultFormat(QSettings.IniFormat)
    for fmt in (QSettings.IniFormat, QSettings.NativeFormat):
        QSettings.setPath(fmt, QSettings.UserScope, str(settings_dir))
        QSettings.setPath(fmt, QSettings.SystemScope, str(settings_dir))

    if _QSETTINGS_INIT_ORIG is None:
        _QSETTINGS_INIT_ORIG = QSettings.__init__

    def _isolated_init(self, *args, **kwargs):
        redirected = _redirected_ctor_args(args, kwargs, isolated_ini)
        if redirected is None:
            _QSETTINGS_INIT_ORIG(self, *args, **kwargs)
            return
        _QSETTINGS_INIT_ORIG(self, *redirected)

    QSettings.__init__ = _isolated_init
    _ISOLATED_SETTINGS_DIR = settings_dir
    _ISOLATED_SETTINGS_INI = isolated_ini
    return isolated_ini


def restore_isolated_qsettings() -> None:
    """Undo :func:`install_isolated_qsettings` constructor wrapping."""
    global _QSETTINGS_INIT_ORIG, _ISOLATED_SETTINGS_DIR, _ISOLATED_SETTINGS_INI
    if _QSETTINGS_INIT_ORIG is not None:
        QSettings.__init__ = _QSETTINGS_INIT_ORIG
        _QSETTINGS_INIT_ORIG = None
    _ISOLATED_SETTINGS_DIR = None
    _ISOLATED_SETTINGS_INI = None


def _is_settings_format(value) -> bool:
    return value in _SETTINGS_FORMATS


def _ctor_parent(args, kwargs):
    parent = kwargs.get("parent")
    if parent is not None:
        return parent
    for arg in args:
        if isinstance(arg, QObject) and not isinstance(arg, type):
            return arg
    return None


def _redirected_ctor_args(args, kwargs, isolated_ini: Path):
    if args and isinstance(args[0], str) and len(args) >= 2 and _is_settings_format(args[1]):
        return None
    parent = _ctor_parent(args, kwargs)
    if parent is not None:
        return (str(isolated_ini), QSettings.IniFormat, parent)
    return (str(isolated_ini), QSettings.IniFormat)


def verify_settings_isolated(settings_dir: Path) -> bool:
    """Return True when production org/app and NativeFormat stay under *settings_dir*."""
    root = Path(settings_dir).resolve()
    probes = (
        QSettings(PROD_SETTINGS_ORG, PROD_SETTINGS_APP),
        QSettings(
            QSettings.NativeFormat,
            QSettings.UserScope,
            PROD_SETTINGS_ORG,
            PROD_SETTINGS_APP,
        ),
    )
    for probe in probes:
        try:
            path = Path(str(probe.fileName())).resolve()
        except (OSError, TypeError, ValueError):
            return False
        if path != root and root not in path.parents:
            return False
    return True


def apply_demo_chrome(app: QApplication) -> None:
    """Install Fusion and the production stylesheet. Caller must restore in tests."""
    app.setStyle("Fusion")
    load_stylesheet(app)


def _policy_token(policy: MotionPolicy) -> str:
    policy = resolve_policy(policy)
    if policy.interpolates():
        return "light"
    if policy.reduced_motion:
        return "reduced"
    return "off"


class LightPageSample(QWidget):
    """S07: two resident light pages; only the target page fades in."""

    def __init__(self, parent=None, *, recorder=None):
        super().__init__(parent)
        self.setObjectName("motionSampleS07")
        self._policy = POLICY_OFF
        self._recorder = recorder
        self._page_id = "a"
        self._signal_count = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        caption = QLabel("此为轻量页面示例，不是已优化的时域或频域切换。", self)
        caption.setWordWrap(True)
        root.addWidget(caption)

        self._title = QLabel("轻量页面示例 · 页面 A", self)
        self._title.setObjectName("motionPageTitle")
        root.addWidget(self._title)

        switch_row = QHBoxLayout()
        self._btn_page_a = QPushButton("页面 A", self)
        self._btn_page_a.setObjectName("motionPageAButton")
        self._btn_page_a.setCheckable(True)
        self._btn_page_b = QPushButton("页面 B", self)
        self._btn_page_b.setObjectName("motionPageBButton")
        self._btn_page_b.setCheckable(True)
        self._page_group = QButtonGroup(self)
        self._page_group.setExclusive(True)
        self._page_group.addButton(self._btn_page_a)
        self._page_group.addButton(self._btn_page_b)
        self._btn_page_a.setChecked(True)
        self._btn_page_a.clicked.connect(self._on_page_a)
        self._btn_page_b.clicked.connect(self._on_page_b)
        switch_row.addWidget(self._btn_page_a)
        switch_row.addWidget(self._btn_page_b)
        switch_row.addStretch(1)
        root.addLayout(switch_row)

        self._viewport = QWidget(self)
        self._viewport.setObjectName("motionPageViewport")
        self._viewport.setMaximumSize(*PAGE_VIEWPORT_MAX)
        self._viewport.setMinimumSize(320, 200)
        self._viewport.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        viewport_layout = QVBoxLayout(self._viewport)
        viewport_layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget(self._viewport)
        self._stack.setObjectName("motionPageStack")
        self._page_a = self._build_page_a()
        self._page_b = self._build_page_b()
        self._stack.addWidget(self._page_a)
        self._stack.addWidget(self._page_b)
        self._stack.setCurrentWidget(self._page_a)
        viewport_layout.addWidget(self._stack)

        self._effect = QGraphicsOpacityEffect(self._viewport)
        self._effect.setOpacity(1.0)
        self._viewport.setGraphicsEffect(self._effect)

        host_row = QHBoxLayout()
        host_row.addWidget(self._viewport, 0, Qt.AlignLeft | Qt.AlignTop)
        host_row.addStretch(1)
        root.addLayout(host_row)

        self._driver = ValueDriver(self, on_value=self._apply_opacity)
        self._driver.snap(1.0)
        self._watch_input(self._viewport)

    @property
    def driver(self) -> ValueDriver:
        return self._driver

    @property
    def current_page_id(self) -> str:
        return self._page_id

    @property
    def signal_count(self) -> int:
        return self._signal_count

    @property
    def page_a(self) -> QWidget:
        return self._page_a

    @property
    def page_b(self) -> QWidget:
        return self._page_b

    @property
    def title_label(self) -> QLabel:
        return self._title

    @property
    def viewport(self) -> QWidget:
        return self._viewport

    def motion_policy(self) -> MotionPolicy:
        return self._policy

    def set_motion_policy(self, policy: MotionPolicy | None) -> None:
        self._policy = resolve_policy(policy)
        if self._driver.is_active():
            self.snap_to_end()

    def displayed_opacity(self) -> float:
        return float(self._effect.opacity())

    def request_page(self, page_id: str) -> None:
        if page_id not in ("a", "b"):
            raise ValueError(f"unknown light page {page_id!r}")
        if page_id == self._page_id:
            return
        self._signal_count += 1
        self._page_id = page_id
        self._title.setText(
            "轻量页面示例 · 页面 A" if page_id == "a" else "轻量页面示例 · 页面 B"
        )
        target = self._page_a if page_id == "a" else self._page_b
        self._stack.setCurrentWidget(target)
        self._btn_page_a.setChecked(page_id == "a")
        self._btn_page_b.setChecked(page_id == "b")

        duration = duration_ms("page_enter", self._policy)
        if duration <= 0:
            self._driver.snap(1.0)
        else:
            self._driver.snap(0.0)
            self._driver.go(1.0, duration_ms=duration)
        self._emit_log()

    def snap_to_end(self) -> None:
        self._driver.snap(1.0)

    def shutdown(self) -> None:
        self.snap_to_end()

    def reset(self) -> None:
        self._signal_count = 0
        self._page_id = "a"
        self._title.setText("轻量页面示例 · 页面 A")
        self._stack.setCurrentWidget(self._page_a)
        self._btn_page_a.setChecked(True)
        self._restore_page_defaults()
        self._driver.snap(1.0)

    def _on_page_a(self, _checked: bool = False) -> None:
        self.request_page("a")

    def _on_page_b(self, _checked: bool = False) -> None:
        self.request_page("b")

    def _apply_opacity(self, value) -> None:
        if value is None:
            return
        self._effect.setOpacity(float(value))

    def _emit_log(self) -> None:
        if self._recorder is None:
            return
        self._recorder(
            sample_id="S07",
            target=self._page_id,
            signals=self._signal_count,
            policy=self._policy,
            active=self._driver.is_active(),
        )

    def _build_page_a(self) -> QWidget:
        page = QWidget(self._stack)
        page.setObjectName("motionPageA")
        layout = QVBoxLayout(page)
        heading = QLabel("轻量页面示例", page)
        layout.addWidget(heading)
        form = QFormLayout()
        self._page_a_note = QLineEdit(page)
        self._page_a_note.setObjectName("motionPageANote")
        self._page_a_count = QSpinBox(page)
        self._page_a_count.setObjectName("motionPageACount")
        self._page_a_count.setRange(0, 99)
        self._page_a_flag = QCheckBox("启用标记", page)
        self._page_a_flag.setObjectName("motionPageAFlag")
        form.addRow("说明", self._page_a_note)
        form.addRow("计数", self._page_a_count)
        form.addRow(self._page_a_flag)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _build_page_b(self) -> QWidget:
        page = QWidget(self._stack)
        page.setObjectName("motionPageB")
        layout = QVBoxLayout(page)
        heading = QLabel("轻量页面示例", page)
        layout.addWidget(heading)
        form = QFormLayout()
        self._page_b_filter = QLineEdit(page)
        self._page_b_filter.setObjectName("motionPageBFilter")
        self._page_b_range = QComboBox(page)
        self._page_b_range.setObjectName("motionPageBRange")
        self._page_b_range.addItems(("低", "中", "高"))
        self._page_b_notes = QPlainTextEdit(page)
        self._page_b_notes.setObjectName("motionPageBNotes")
        self._page_b_notes.setMaximumHeight(96)
        form.addRow("条件", self._page_b_filter)
        form.addRow("量程", self._page_b_range)
        form.addRow("备注", self._page_b_notes)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _restore_page_defaults(self) -> None:
        self._page_a_note.clear()
        self._page_a_count.setValue(0)
        self._page_a_flag.setChecked(False)
        self._page_b_filter.clear()
        self._page_b_range.setCurrentIndex(0)
        self._page_b_notes.clear()

    def _watch_input(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if self._driver.is_active() and event.type() in _INPUT_EVENTS:
            if watched is self._viewport or self._viewport.isAncestorOf(watched):
                self.snap_to_end()
        return False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        old = event.oldSize()
        if (
            self._driver.is_active()
            and old.isValid()
            and old != event.size()
        ):
            self.snap_to_end()

    def hideEvent(self, event) -> None:
        self.snap_to_end()
        super().hideEvent(event)


class MotionDemoWindow(QWidget):
    """Standalone sample host. Not on the production launch path."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("motionDemoWindow")
        self.setWindowTitle(f"{APP_NAME} 原生交互动效样板")
        self._policy = POLICY_OFF
        self._build()

    def motion_policy(self) -> MotionPolicy:
        return self._policy

    def set_motion_policy(self, policy: MotionPolicy | None) -> None:
        policy = resolve_policy(policy)
        if policy == self._policy:
            self._sync_policy_buttons()
            return
        self._policy = policy
        self._apply_sample_policies(policy)
        self._sync_policy_buttons()
        self.record_sample(
            sample_id="host",
            target=_policy_token(policy),
            signals=0,
            policy=policy,
            active=False,
        )

    def log_text(self) -> str:
        return self._log.toPlainText()

    def record_sample(
        self,
        *,
        sample_id: str,
        target,
        signals: int,
        policy: MotionPolicy,
        active: bool,
    ) -> None:
        token = _policy_token(policy)
        line = (
            f"sample_id={sample_id} target={target} "
            f"signals={signals} motion={token} active={int(bool(active))}"
        )
        self._log.appendPlainText(line)

    def reset_demo(self) -> None:
        self._log.clear()
        self._reset_s01()
        self._reset_s02()
        self._reset_s03()
        self._reset_s04()
        self._reset_s05()
        self._reset_s06()
        self.sample_s07.reset()
        self.set_motion_policy(POLICY_OFF)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addLayout(self._build_toolbar())

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.NoFrame)
        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        self._placeholders = {}
        builders = {
            "S01": self._build_s01_sample,
            "S02": self._build_s02_sample,
            "S03": self._build_s03_sample,
            "S04": self._build_s04_sample,
            "S05": self._build_s05_sample,
            "S06": self._build_s06_sample,
        }
        for sample_id in PLACEHOLDER_IDS:
            box = builders[sample_id](body)
            body_layout.addWidget(box)
            self._placeholders[sample_id] = box

        s07_box = QGroupBox("S07 轻量页面", body)
        s07_box.setObjectName("motionSampleS07Host")
        s07_layout = QVBoxLayout(s07_box)
        self.sample_s07 = LightPageSample(s07_box, recorder=self.record_sample)
        s07_layout.addWidget(self.sample_s07)
        body_layout.addWidget(s07_box)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        root.addWidget(self._build_log_panel())
        self._sync_policy_buttons()
        self.resize(1200, 800)

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._policy_off = QPushButton("当前方式", self)
        self._policy_off.setObjectName("motionPolicyOff")
        self._policy_light = QPushButton("轻动效", self)
        self._policy_light.setObjectName("motionPolicyLight")
        self._policy_reduced = QPushButton("减少动效", self)
        self._policy_reduced.setObjectName("motionPolicyReduced")
        self._reset = QPushButton("复位", self)
        self._reset.setObjectName("motionDemoReset")

        self._policy_group = QButtonGroup(self)
        self._policy_group.setExclusive(True)
        for button in (self._policy_off, self._policy_light, self._policy_reduced):
            button.setCheckable(True)
            self._policy_group.addButton(button)
        self._policy_off.setChecked(True)

        self._policy_off.clicked.connect(self._on_policy_off)
        self._policy_light.clicked.connect(self._on_policy_light)
        self._policy_reduced.clicked.connect(self._on_policy_reduced)
        self._reset.clicked.connect(self._on_reset)

        row.addWidget(self._policy_off)
        row.addWidget(self._policy_light)
        row.addWidget(self._policy_reduced)
        row.addStretch(1)
        row.addWidget(self._reset)
        return row

    def _build_log_panel(self) -> QGroupBox:
        box = QGroupBox("诊断日志", self)
        box.setObjectName("motionDemoLogPanel")
        box.setCheckable(True)
        box.setChecked(False)
        layout = QVBoxLayout(box)
        self._log = QPlainTextEdit(box)
        self._log.setObjectName("motionDemoLog")
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText("sample_id / target / signals / motion")
        layout.addWidget(self._log)
        self._log.setVisible(False)
        box.toggled.connect(self._log.setVisible)
        return box

    def _policy_targets(self):
        yield from self.sample_s01_buttons
        yield self.sample_s02
        yield self.sample_s03
        yield self.sample_s04
        yield self.sample_s05
        yield self.sample_s06
        yield self.sample_s07

    def _apply_sample_policies(self, policy: MotionPolicy) -> None:
        for target in self._policy_targets():
            target.set_motion_policy(policy)

    def _build_s01_sample(self, parent: QWidget) -> QGroupBox:
        from mf4_analyzer.ui_kit.widgets.motion_button import make_sample_button

        box = QGroupBox("S01 动作按钮", parent)
        box.setObjectName("motionSampleS01")
        layout = QHBoxLayout(box)
        specs = (
            ("primary", None, "motionSampleS01Primary"),
            ("secondary", None, "motionSampleS01Secondary"),
            ("quiet", None, "motionSampleS01Quiet"),
            ("icon", 28, "motionSampleS01Icon28"),
            ("icon", 24, "motionSampleS01Icon24"),
        )
        self.sample_s01_buttons = []
        self._s01_signals = 0
        for role, icon_edge, object_name in specs:
            button = make_sample_button(role, box, icon_edge=icon_edge)
            button.setObjectName(object_name)
            button.clicked.connect(self._on_s01_clicked)
            self.sample_s01_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        return box

    def _on_s01_clicked(self) -> None:
        button = self.sender()
        self._s01_signals += 1
        role = "" if button is None else str(button.property("role") or button.objectName())
        self.record_sample(
            sample_id="S01",
            target=role,
            signals=self._s01_signals,
            policy=self._policy,
            active=self._sample_active(button),
        )

    def _reset_s01(self) -> None:
        for button in self.sample_s01_buttons:
            button.set_motion_policy(self._policy)
        self._s01_signals = 0

    def _build_s02_sample(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox("S02 开关", parent)
        box.setObjectName("motionSampleS02")
        layout = QHBoxLayout(box)
        self.sample_s02 = PillSwitch(box, object_name="motionSampleS02Switch")
        self.sample_s02_label = PillSwitchLabel("滤波预览", self.sample_s02, box)
        self.sample_s02_label.setObjectName("motionSampleS02Label")
        self._s02_signals = 0
        self.sample_s02.toggled.connect(self._on_s02_toggled)
        layout.addWidget(self.sample_s02)
        layout.addWidget(self.sample_s02_label)
        layout.addStretch(1)
        return box

    def _on_s02_toggled(self, checked: bool) -> None:
        self._s02_signals += 1
        self.record_sample(
            sample_id="S02",
            target=int(bool(checked)),
            signals=self._s02_signals,
            policy=self._policy,
            active=self._sample_active(self.sample_s02),
        )

    def _reset_s02(self) -> None:
        blocked = self.sample_s02.blockSignals(True)
        try:
            self.sample_s02.setChecked(False)
        finally:
            self.sample_s02.blockSignals(blocked)
        self.sample_s02.set_motion_policy(self._policy)
        self._s02_signals = 0

    def _build_s03_sample(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox("S03 分段选择", parent)
        box.setObjectName("motionSampleS03")
        layout = QVBoxLayout(box)
        self.sample_s03_combo = QComboBox(box)
        self.sample_s03_combo.setObjectName("motionSampleS03Combo")
        self.sample_s03_combo.addItem("自动", "auto")
        self.sample_s03_combo.addItem("手动", "manual")
        self.sample_s03 = SegmentedChoice(box)
        self.sample_s03.bind(self.sample_s03_combo)
        self._s03_signals = 0
        self.sample_s03.currentIndexChanged.connect(self._on_s03_index_changed)
        layout.addWidget(self.sample_s03)
        return box

    def _on_s03_index_changed(self, index: int) -> None:
        self._s03_signals += 1
        self.record_sample(
            sample_id="S03",
            target=index,
            signals=self._s03_signals,
            policy=self._policy,
            active=self._sample_active(self.sample_s03),
        )

    def _reset_s03(self) -> None:
        combo = self.sample_s03.bound_combo()
        blocked = combo.blockSignals(True)
        try:
            combo.setCurrentIndex(0)
        finally:
            combo.blockSignals(blocked)
        self.sample_s03.sync_from_bound_combo()
        self.sample_s03.set_motion_policy(self._policy)
        self._s03_signals = 0

    def _build_s04_sample(self, parent: QWidget) -> QGroupBox:
        box = QGroupBox("S04 View 标记", parent)
        box.setObjectName("motionSampleS04")
        layout = QVBoxLayout(box)
        caption = QLabel(
            "独立 ViewManager 样板，不接真实图表。标记只跟随确认后的 active View。",
            box,
        )
        caption.setWordWrap(True)
        self.sample_s04_manager = ViewManager(max_views=TIME_DOMAIN_MAX_VIEWS)
        self.sample_s04_manager.new_view()
        self.sample_s04_manager.new_view()
        self.sample_s04_manager.set_active(0)
        self.sample_s04 = ViewTabBar(
            self.sample_s04_manager,
            box,
            section="time",
        )
        self._s04_signals = 0
        self.sample_s04.switch_requested.connect(self._on_s04_switch)
        self.sample_s04.new_requested.connect(self._on_s04_new)
        self.sample_s04.delete_requested.connect(self._on_s04_delete)
        self.sample_s04.overflow_delete_requested.connect(self._on_s04_delete)
        layout.addWidget(caption)
        layout.addWidget(self.sample_s04)
        return box

    def _on_s04_switch(self, index: int) -> None:
        self._s04_signals += 1
        self.sample_s04_manager.set_active(index)
        self._log_s04()

    def _on_s04_new(self) -> None:
        self._s04_signals += 1
        self.sample_s04_manager.new_view()
        self._log_s04()

    def _on_s04_delete(self, index: int) -> None:
        self._s04_signals += 1
        self.sample_s04_manager.delete_view(index)
        self._log_s04()

    def _log_s04(self) -> None:
        manager = self.sample_s04_manager
        view = manager.get(manager.active)
        self.record_sample(
            sample_id="S04",
            target=str(view.view_id),
            signals=self._s04_signals,
            policy=self._policy,
            active=self._sample_active(self.sample_s04),
        )

    def _reset_s04(self) -> None:
        manager = self.sample_s04_manager
        manager.reset_to_single_default()
        manager.new_view()
        manager.new_view()
        manager.set_active(0)
        self.sample_s04.set_motion_policy(self._policy)
        self._s04_signals = 0

    def _build_s05_sample(self, parent: QWidget) -> QGroupBox:
        from mf4_analyzer.ui.inspector_sections.collapsible import (
            _CollapsibleParamSection,
        )

        box = QGroupBox("S05 参数折叠", parent)
        box.setObjectName("motionSampleS05")
        layout = QVBoxLayout(box)
        caption = QLabel(
            "样板列内的真实参数区，使用临时 INI，不写入用户 Inspector 设置。",
            box,
        )
        caption.setWordWrap(True)
        settings_dir = Path(tempfile.mkdtemp(prefix="tracelab-motion-s05-"))
        self.sample_s05_settings = QSettings(
            str(settings_dir / "s05.ini"),
            QSettings.IniFormat,
        )
        self.sample_s05 = _CollapsibleParamSection(
            "谱参数",
            "motion_demo/s05_expanded",
            settings=self.sample_s05_settings,
            default_expanded=False,
            parent=box,
        )
        persistent = QLabel("常用预设（持久区，始终可见）", self.sample_s05)
        persistent.setObjectName("motionSampleS05Persistent")
        self.sample_s05.add_persistent(persistent)
        body = QWidget(self.sample_s05)
        body.setObjectName("motionSampleS05Body")
        form = QFormLayout(body)
        self.sample_s05_field = QLineEdit(body)
        self.sample_s05_field.setObjectName("motionSampleS05Field")
        overlap = QLineEdit(body)
        overlap.setObjectName("motionSampleS05Overlap")
        form.addRow("窗函数", self.sample_s05_field)
        form.addRow("重叠", overlap)
        self.sample_s05.set_body(body)
        self._s05_signals = 0
        self.sample_s05.btn_collapser.toggled.connect(self._on_s05_toggled)
        layout.addWidget(caption)
        layout.addWidget(self.sample_s05)
        return box

    def _on_s05_toggled(self, checked: bool) -> None:
        self._s05_signals += 1
        self.record_sample(
            sample_id="S05",
            target=int(bool(checked)),
            signals=self._s05_signals,
            policy=self._policy,
            active=self._sample_active(self.sample_s05),
        )

    def _reset_s05(self) -> None:
        blocked = self.sample_s05.btn_collapser.blockSignals(True)
        try:
            self.sample_s05.set_expanded(False)
            self.sample_s05_field.clear()
        finally:
            self.sample_s05.btn_collapser.blockSignals(blocked)
        self.sample_s05.set_motion_policy(self._policy)
        self._s05_signals = 0

    def _build_s06_sample(self, parent: QWidget) -> QGroupBox:
        from mf4_analyzer.ui.recent_files import RecentEntry
        from mf4_analyzer.ui.widgets.recent_open_popup import RecentOpenPopup

        box = QGroupBox("S06 最近打开", parent)
        box.setObjectName("motionSampleS06")
        layout = QVBoxLayout(box)
        caption = QLabel(
            "合成记录。打开/清除只写入样板日志，不打开或清除用户文件。",
            box,
        )
        caption.setWordWrap(True)
        self.sample_s06_anchor = QPushButton("打开最近记录", box)
        self.sample_s06_anchor.setObjectName("motionSampleS06Anchor")
        self.sample_s06_anchor.clicked.connect(self._on_s06_show)
        records = Path(tempfile.mkdtemp(prefix="tracelab-motion-s06-"))
        existing = records / "steering_ok.mf4"
        existing.write_text("x", encoding="utf-8")
        project = records / "demo.tlproj"
        project.write_text("x", encoding="utf-8")
        missing = records / "missing_run.mf4"
        self.sample_s06_entries = (
            RecentEntry(path=str(existing), kind="file", opened_at="2026-09-04T12:00:00"),
            RecentEntry(path=str(project), kind="project", opened_at="2026-09-03T09:00:00"),
            RecentEntry(path=str(missing), kind="file", opened_at="2026-09-02T08:00:00"),
        )
        self.sample_s06 = RecentOpenPopup(self)
        self.sample_s06.populate(self.sample_s06_entries)
        self._s06_signals = 0
        self.sample_s06.open_requested.connect(self._on_s06_open_requested)
        self.sample_s06.clear_requested.connect(self._on_s06_clear_requested)
        self.sample_s06.closed.connect(self._on_s06_closed)
        layout.addWidget(caption)
        layout.addWidget(self.sample_s06_anchor, 0, Qt.AlignLeft)
        return box

    def _on_s06_show(self) -> None:
        self.sample_s06.reset_for_show()
        self.sample_s06.show_at(self.sample_s06_anchor)

    def _on_s06_open_requested(self, path: str) -> None:
        self._s06_signals += 1
        self.record_sample(
            sample_id="S06",
            target=f"open:{Path(path).name}",
            signals=self._s06_signals,
            policy=self._policy,
            active=self._sample_active(self.sample_s06),
        )

    def _on_s06_clear_requested(self) -> None:
        self._s06_signals += 1
        self.record_sample(
            sample_id="S06",
            target="clear",
            signals=self._s06_signals,
            policy=self._policy,
            active=False,
        )

    def _on_s06_closed(self) -> None:
        self.record_sample(
            sample_id="S06",
            target="closed",
            signals=self._s06_signals,
            policy=self._policy,
            active=False,
        )

    def _reset_s06(self) -> None:
        if self.sample_s06.isVisible():
            self.sample_s06.hide()
        self.sample_s06.populate(self.sample_s06_entries)
        self.sample_s06.reset_for_show()
        self.sample_s06.set_motion_policy(self._policy)
        self._s06_signals = 0

    @staticmethod
    def _sample_active(widget) -> bool:
        if widget is None:
            return False
        for name in (
            "_value_driver",
            "_motion_driver",
            "_marker_driver",
            "_openness_driver",
            "_hover_driver",
            "_press_driver",
            "_enter_driver",
        ):
            driver = getattr(widget, name, None)
            if driver is not None and driver.is_active():
                return True
        return False

    def _on_policy_off(self, _checked: bool = False) -> None:
        self.set_motion_policy(POLICY_OFF)

    def _on_policy_light(self, _checked: bool = False) -> None:
        self.set_motion_policy(POLICY_LIGHT)

    def _on_policy_reduced(self, _checked: bool = False) -> None:
        self.set_motion_policy(POLICY_REDUCED)

    def _on_reset(self, _checked: bool = False) -> None:
        self.reset_demo()

    def _sync_policy_buttons(self) -> None:
        mapping = {
            POLICY_OFF: self._policy_off,
            POLICY_LIGHT: self._policy_light,
            POLICY_REDUCED: self._policy_reduced,
        }
        target = mapping[self._policy]
        if not target.isChecked():
            target.setChecked(True)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.WindowDeactivate:
            self._apply_sample_policies(self._policy)
            if self.sample_s06.isVisible():
                self.sample_s06.hide()
            self.sample_s07.snap_to_end()
        super().changeEvent(event)

    def hideEvent(self, event) -> None:
        self._apply_sample_policies(self._policy)
        if self.sample_s06.isVisible():
            self.sample_s06.hide()
        self.sample_s07.snap_to_end()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        if self.sample_s06.isVisible():
            self.sample_s06.hide()
        self._apply_sample_policies(POLICY_OFF)
        self.sample_s07.shutdown()
        super().closeEvent(event)


def main(argv=None) -> int:
    global _APP_BOOTSTRAPPED

    settings_dir = Path(tempfile.mkdtemp(prefix="tracelab-motion-demo-"))
    install_isolated_qsettings(settings_dir)
    if not verify_settings_isolated(settings_dir):
        raise SystemExit(
            "motion_demo: QSettings isolation failed; "
            "refusing to touch the real MF4Analyzer/DataAnalyzer store."
        )
    setup_chinese_font()

    created_app = QApplication.instance() is None
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    apply_demo_chrome(app)
    _APP_BOOTSTRAPPED = True
    window = MotionDemoWindow()
    window.show()
    if created_app:
        return int(app.exec_())
    return 0


if __name__ == "__main__":
    sys.exit(main())
