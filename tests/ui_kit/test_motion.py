"""Contracts for the shared motion policy and interruptible value driver."""
from __future__ import annotations

import pytest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui_kit.motion import (
    DURATION_MS,
    POLICY_LIGHT,
    POLICY_OFF,
    POLICY_REDUCED,
    MotionPolicy,
    ValueDriver,
    duration_ms,
    resolve_policy,
)


def test_missing_policy_equals_off_and_zero_duration():
    assert resolve_policy(None) == POLICY_OFF
    assert not POLICY_OFF.interpolates()
    assert POLICY_LIGHT.interpolates()
    assert not POLICY_REDUCED.interpolates()
    assert duration_ms("switch", None) == 0
    assert duration_ms("switch", POLICY_OFF) == 0
    assert duration_ms("switch", POLICY_REDUCED) == 0
    assert duration_ms("switch", POLICY_LIGHT) == DURATION_MS["switch"]


def test_unknown_duration_name_is_rejected():
    with pytest.raises(ValueError, match="unknown motion duration"):
        duration_ms("bounce", POLICY_LIGHT)


def test_reverse_continues_from_current_displayed_value(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    seen = []
    driver = ValueDriver(host, on_value=seen.append)
    driver.snap(0.0)
    driver.go(1.0, duration_ms=160)
    driver.clock().setCurrentTime(40)
    mid = driver.current()
    assert mid not in (None, 0.0, 1.0)
    assert driver.is_active()

    driver.go(0.0, duration_ms=160)
    assert driver.clock().startValue() == pytest.approx(float(mid))
    assert driver.target() == 0.0
    assert driver.current() == pytest.approx(float(mid))


def test_same_target_is_noop(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    seen = []
    driver = ValueDriver(host, on_value=seen.append)
    driver.snap(1.0)
    baseline = list(seen)
    generation = driver.generation()
    driver.go(1.0, duration_ms=160)
    assert seen == baseline
    assert driver.generation() == generation
    assert not driver.is_active()

    driver.go(0.0, duration_ms=160)
    generation = driver.generation()
    started = driver.clock().startValue()
    driver.go(0.0, duration_ms=160)
    assert driver.generation() == generation
    assert driver.clock().startValue() == started


def test_reduced_and_disabled_policies_snap_without_active_clock(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    driver = ValueDriver(host)
    driver.snap(0.0)
    driver.go(1.0, duration_ms=duration_ms("switch", POLICY_REDUCED))
    assert driver.current() == 1.0
    assert not driver.is_active()
    driver.go(0.0, duration_ms=duration_ms("switch", POLICY_OFF))
    assert driver.current() == 0.0
    assert not driver.is_active()
    assert driver.clock().state() == driver.clock().Stopped


def test_delete_later_stops_driver_without_callback_into_dead_owner(qapp):
    from PyQt5 import sip
    from PyQt5.QtCore import QEvent
    from PyQt5.QtWidgets import QApplication

    host = QWidget()
    calls = []

    def on_value(value):
        calls.append(value)
        host.windowTitle()

    driver = ValueDriver(host, on_value=on_value)
    driver.snap(0.0)
    driver.go(1.0, duration_ms=160)
    assert driver.is_active()
    host.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
    assert sip.isdeleted(host)
    assert calls


def test_go_after_finished_run_rebases_clock_to_zero(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    driver = ValueDriver(host)
    driver.snap(0.0)
    driver.go(1.0, duration_ms=160)
    driver.clock().setCurrentTime(160)
    assert not driver.is_active()
    assert driver.current() == pytest.approx(1.0)
    assert driver.clock().currentTime() == 160

    driver.go(0.0, duration_ms=140)
    assert driver.is_active()
    assert driver.clock().currentTime() == 0
    assert driver.clock().startValue() == pytest.approx(1.0)
    assert driver.target() == 0.0
    driver.clock().setCurrentTime(35)
    mid = float(driver.current())
    assert 0.0 < mid < 1.0


def test_idle_driver_has_no_running_timer(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    driver = ValueDriver(host)
    driver.snap(0.25)
    assert not driver.is_active()
    assert driver.clock().state() == driver.clock().Stopped
    assert not MotionPolicy().enabled
