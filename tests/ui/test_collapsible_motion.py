"""S05 motion contracts for ``_CollapsibleParamSection``.

Uses an injected temp INI. Do not construct ``QSettings("MF4Analyzer",
"DataAnalyzer")`` here — that native store is the real user preference
file (lesson ``codex-qt-render-probes-isolate-qsettings``).
"""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWIDGETSIZE_MAX,
    QWidget,
)

from mf4_analyzer.ui.inspector_sections.collapsible import _CollapsibleParamSection
from mf4_analyzer.ui_kit.motion import (
    POLICY_LIGHT,
    POLICY_OFF,
    POLICY_REDUCED,
    duration_ms,
)


def _temp_settings(tmp_path, name="collapsible-motion.ini"):
    settings = QSettings(str(tmp_path / name), QSettings.IniFormat)
    settings.clear()
    settings.sync()
    return settings


def _make_body(min_height=96):
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    edit = QLineEdit()
    edit.setObjectName("collapsibleMotionField")
    label = QLabel("body controls")
    label.setMinimumHeight(min_height)
    disabled = QPushButton("disabled")
    disabled.setObjectName("collapsibleMotionDisabled")
    disabled.setEnabled(False)
    layout.addWidget(edit)
    layout.addWidget(label)
    layout.addWidget(disabled)
    box.edit = edit
    box.disabled = disabled
    return box


def _make_section(qtbot, tmp_path, *, key="tests/params_expanded", **kwargs):
    settings = kwargs.pop("settings", None) or _temp_settings(tmp_path)
    section = _CollapsibleParamSection("谱参数", key, settings=settings, **kwargs)
    persistent = QLabel("preset bar")
    persistent.setObjectName("collapsibleMotionPersistent")
    section.add_persistent(persistent)
    body = _make_body()
    section.set_body(body)
    qtbot.addWidget(section)
    section.resize(320, 280)
    section.show()
    qtbot.waitExposed(section)
    return section, settings, persistent, body


def _advance(section, ms):
    clock = section._openness_driver.clock()
    clock.setCurrentTime(int(ms))


def _focus_body_field(section, edit):
    QApplication.setActiveWindow(section)
    section.activateWindow()
    edit.setFocus(Qt.TabFocusReason)
    QApplication.processEvents()
    focused = QApplication.focusWidget()
    assert focused is edit or edit.hasFocus()


def test_default_off_is_immediate_show_hide(qtbot, tmp_path):
    section, settings, persistent, body = _make_section(qtbot, tmp_path)

    assert section.motion_policy() == POLICY_OFF
    assert section.is_expanded() is False
    assert persistent.isVisible()
    assert not body.isVisible()
    assert not section._openness_driver.is_active()

    section.set_expanded(True)
    assert section.is_expanded() is True
    assert section.btn_collapser.isChecked()
    assert body.isVisible()
    assert persistent.isVisible()
    assert not section._openness_driver.is_active()
    assert section._body.maximumHeight() == QWIDGETSIZE_MAX
    settings.sync()
    assert _settings_is_true(settings, "tests/params_expanded")


def test_reduced_motion_snaps_without_active_clock(qtbot, tmp_path):
    section, settings, persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_REDUCED)

    section.set_expanded(True)
    assert section.is_expanded() is True
    assert body.isVisible()
    assert persistent.isVisible()
    assert not section._openness_driver.is_active()
    assert section._body.maximumHeight() == QWIDGETSIZE_MAX
    assert duration_ms("collapse_expand", section.motion_policy()) == 0
    settings.sync()
    assert _settings_is_true(settings, "tests/params_expanded")

    section.set_expanded(False)
    assert section.is_expanded() is False
    assert not body.isVisible()
    assert persistent.isVisible()
    assert not section._openness_driver.is_active()


def test_settings_and_checked_commit_before_height_progress(qtbot, tmp_path):
    section, settings, persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_LIGHT)

    section.set_expanded(True)
    settings.sync()
    assert _settings_is_true(settings, "tests/params_expanded")
    assert section.is_expanded() is True
    assert section.btn_collapser.isChecked()
    assert persistent.isVisible()
    assert section._openness_driver.is_active()
    assert section._openness_driver.clock().duration() == 180
    assert settings.value("tests/params_expanded_height", None) is None
    assert settings.value("tests/params_arrow", None) is None
    assert list(settings.allKeys()) == ["tests/params_expanded"]

    _advance(section, 45)
    mid = section._body.maximumHeight()
    natural = section._motion_target_height
    assert natural is not None and natural > 0
    assert 0 < mid < natural
    assert 0.0 < section._presented_openness < 1.0
    assert 0.0 < section._arrow_degrees < 90.0
    settings.sync()
    assert _settings_is_true(settings, "tests/params_expanded")
    assert list(settings.allKeys()) == ["tests/params_expanded"]


def test_height_mid_frames_and_settle_releases_clip(qtbot, tmp_path):
    section, _settings, persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_LIGHT)
    section.set_expanded(True)

    clock = section._openness_driver.clock()
    assert clock.duration() == duration_ms("collapse_expand", POLICY_LIGHT)
    natural = section._motion_target_height
    assert natural > 0

    _advance(section, 0)
    assert section._body.maximumHeight() == 0
    assert body.isVisible()

    _advance(section, clock.duration() // 2)
    mid = section._body.maximumHeight()
    assert 0 < mid < natural
    assert persistent.isVisible()

    _advance(section, clock.duration())
    assert not section._openness_driver.is_active()
    assert body.isVisible()
    assert section._body.maximumHeight() == QWIDGETSIZE_MAX
    assert section._body.minimumHeight() == 0
    assert section.btn_collapser.arrowType() == Qt.DownArrow

    section.set_expanded(False)
    clock = section._openness_driver.clock()
    assert clock.duration() == duration_ms("collapse_collapse", POLICY_LIGHT)
    _advance(section, clock.duration() // 2)
    assert 0 < section._body.maximumHeight() < natural
    _advance(section, clock.duration())
    assert not section._openness_driver.is_active()
    assert not body.isVisible()
    assert persistent.isVisible()
    assert section._body.maximumHeight() == QWIDGETSIZE_MAX
    assert section.btn_collapser.arrowType() == Qt.RightArrow


def test_collapse_moves_body_focus_to_collapser(qtbot, tmp_path):
    section, _settings, _persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_LIGHT)
    section.set_expanded(True)
    _advance(section, duration_ms("collapse_expand", POLICY_LIGHT))
    assert not section._openness_driver.is_active()

    _focus_body_field(section, body.edit)

    section.set_expanded(False)
    focused = QApplication.focusWidget()
    assert focused is section.btn_collapser or section.btn_collapser.hasFocus()
    assert not body.edit.hasFocus()
    assert body.edit.focusPolicy() == Qt.NoFocus
    assert body.edit.isEnabled()
    assert not body.disabled.isEnabled()
    assert section._input_shielded is True
    assert section._input_shield.isVisible()


def test_fast_reverse_restores_input_without_changing_enabled(qtbot, tmp_path):
    section, _settings, _persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_LIGHT)
    section.set_expanded(True)
    _advance(section, duration_ms("collapse_expand", POLICY_LIGHT))

    original_policy = body.edit.focusPolicy()
    _focus_body_field(section, body.edit)
    section.set_expanded(False)
    _advance(section, 40)
    assert section._openness_driver.is_active()
    mid = section._presented_openness
    assert 0.0 < mid < 1.0
    assert body.edit.focusPolicy() == Qt.NoFocus
    assert body.edit.isEnabled()
    assert not body.disabled.isEnabled()

    section.set_expanded(True)
    assert body.edit.isEnabled()
    assert not body.disabled.isEnabled()
    assert body.edit.focusPolicy() == original_policy
    assert section._input_shielded is False
    assert not section._input_shield.isVisible()
    assert section._openness_driver.is_active()
    assert section._openness_driver.target() == 1.0
    assert section._presented_openness == pytest.approx(mid, abs=0.02)
    assert section._openness_driver.clock().startValue() == pytest.approx(
        mid, abs=0.02
    )


def test_content_replace_snaps_to_intent(qtbot, tmp_path):
    section, _settings, persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_LIGHT)
    section.set_expanded(True)
    _advance(section, 40)
    assert section._openness_driver.is_active()

    replacement = _make_body(min_height=72)
    section.set_body(replacement)
    assert not section._openness_driver.is_active()
    assert replacement.isVisible()
    assert not body.isVisible()
    assert persistent.isVisible()
    assert section._body.maximumHeight() == QWIDGETSIZE_MAX
    assert section._input_shielded is False
    assert section.is_expanded() is True


def test_hide_during_motion_snaps_to_intent(qtbot, tmp_path):
    section, _settings, persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_LIGHT)
    section.set_expanded(True)
    _advance(section, 50)
    assert section._openness_driver.is_active()

    section.hide()
    assert not section._openness_driver.is_active()
    assert section.is_expanded() is True
    assert section._body.maximumHeight() == QWIDGETSIZE_MAX
    section.show()
    qtbot.waitExposed(section)
    assert body.isVisible()
    assert persistent.isVisible()


def test_width_change_during_motion_snaps(qtbot, tmp_path):
    section, _settings, persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_LIGHT)
    section.set_expanded(True)
    _advance(section, 50)
    assert section._openness_driver.is_active()

    section.resize(480, section.height())
    assert not section._openness_driver.is_active()
    assert body.isVisible()
    assert persistent.isVisible()
    assert section._body.maximumHeight() == QWIDGETSIZE_MAX


def test_policy_off_after_light_snaps_and_matches_business_state(qtbot, tmp_path):
    section, settings, _persistent, body = _make_section(qtbot, tmp_path)
    section.set_motion_policy(POLICY_LIGHT)
    section.set_expanded(True)
    _advance(section, 30)
    assert section._openness_driver.is_active()

    section.set_motion_policy(None)
    assert section.motion_policy() == POLICY_OFF
    assert not section._openness_driver.is_active()
    assert section.is_expanded() is True
    assert body.isVisible()
    settings.sync()
    assert _settings_is_true(settings, "tests/params_expanded")


def test_injected_ini_does_not_use_real_org_app_store(tmp_path):
    settings = _temp_settings(tmp_path, "isolated.ini")
    section = _CollapsibleParamSection(
        "谱参数",
        "tests/params_expanded",
        settings=settings,
    )
    section.set_expanded(True)
    settings.sync()
    assert settings.fileName().endswith("isolated.ini")
    assert "MF4Analyzer" not in settings.fileName()
    assert settings.organizationName() == ""
    assert QApplication.instance() is not None


def _settings_is_true(settings, key):
    raw = settings.value(key)
    if isinstance(raw, bool):
        return raw is True
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def test_summary_yields_width_and_keeps_full_text_in_tooltip(qtbot, tmp_path):
    section, *_ = _make_section(qtbot, tmp_path)
    full = "自动(目标 4096) · hanning · 80%"
    section.set_summary(full)
    assert section.summary_text() == full
    assert section._summary.toolTip() == full
    assert section._summary.minimumSizeHint().width() == 0
    section.resize(288, 200)
    QApplication.processEvents()
    assert section._summary.width() < section._summary.sizeHint().width()


def _alpha_bounds(image):
    min_x = min_y = image.width()
    max_x = max_y = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 8:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    return None if max_x < 0 else (min_x, min_y, max_x, max_y)


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
@pytest.mark.parametrize("degrees", [0.0, 22.5, 45.0, 67.5, 90.0])
def test_motion_arrow_icon_stays_inside_logical_pixmap(
    qtbot, tmp_path, monkeypatch, dpr, degrees,
):
    from PyQt5.QtCore import QSize
    from PyQt5.QtGui import QImage

    section, *_ = _make_section(qtbot, tmp_path)
    monkeypatch.setattr(section, "devicePixelRatioF", lambda: dpr)
    icon = section._make_arrow_icon(degrees)
    pixmap = icon.pixmap(QSize(12, 12))
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    bounds = _alpha_bounds(image)
    assert bounds is not None
    left, top, right, bottom = bounds
    assert left >= 1
    assert top >= 1
    assert right <= image.width() - 2
    assert bottom <= image.height() - 2
    cx = 0.5 * (left + right)
    cy = 0.5 * (top + bottom)
    assert abs(cx - (image.width() - 1) / 2.0) < image.width() * 0.28
    assert abs(cy - (image.height() - 1) / 2.0) < image.height() * 0.28
