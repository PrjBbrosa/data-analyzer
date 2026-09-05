"""Shared motion policy and per-instance value interpolation.

This module owns :class:`MotionPolicy` and the first-round duration table.
It does not keep an application-wide widget registry and does not read
MainWindow, file, project, or analysis state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from weakref import ref

from PyQt5.QtCore import QEasingCurve, QObject, QVariantAnimation


DURATION_MS = {
    "hover_in": 100,
    "hover_out": 80,
    "press": 0,
    "release": 80,
    "switch": 160,
    "segment": 160,
    "view_marker": 140,
    "collapse_expand": 180,
    "collapse_collapse": 140,
    "recent_enter": 140,
    "page_enter": 140,
}
EASING = QEasingCurve.OutCubic


@dataclass(frozen=True)
class MotionPolicy:
    """Immutable per-instance motion choice. Missing policy equals off."""

    enabled: bool = False
    reduced_motion: bool = False

    def interpolates(self) -> bool:
        return bool(self.enabled) and not bool(self.reduced_motion)


POLICY_OFF = MotionPolicy(enabled=False, reduced_motion=False)
POLICY_LIGHT = MotionPolicy(enabled=True, reduced_motion=False)
POLICY_REDUCED = MotionPolicy(enabled=True, reduced_motion=True)


def resolve_policy(policy: MotionPolicy | None) -> MotionPolicy:
    return POLICY_OFF if policy is None else policy


def duration_ms(name: str, policy: MotionPolicy | None) -> int:
    if name not in DURATION_MS:
        known = ", ".join(sorted(DURATION_MS))
        raise ValueError(f"unknown motion duration {name!r}; expected one of: {known}")
    if not resolve_policy(policy).interpolates():
        return 0
    return DURATION_MS[name]


class ValueDriver(QObject):
    """Interruptible value interpolation owned by one widget.

    ``finished`` only settles presentation. Callers must commit business
    state before :meth:`go` and must not queue work on this object.
    """

    def __init__(
        self,
        owner: QObject,
        *,
        on_value: Callable | None = None,
    ) -> None:
        super().__init__(owner)
        self._owner_ref = ref(owner)
        self._on_value = on_value
        self._generation = 0
        self._current = None
        self._target = None
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve(EASING))
        self._anim.valueChanged.connect(self._on_anim_value)
        self._anim.finished.connect(self._on_finished)

    def current(self):
        return self._current

    def target(self):
        return self._target

    def generation(self) -> int:
        return self._generation

    def is_active(self) -> bool:
        return self._anim.state() == QVariantAnimation.Running

    def clock(self) -> QVariantAnimation:
        return self._anim

    def snap(self, value) -> None:
        self._generation += 1
        self._anim.stop()
        self._current = value
        self._target = value
        self._notify(value)

    def go(self, value, *, duration_ms: int) -> None:
        if self._same_target(value) and (
            self.is_active() or self._current == value
        ):
            return
        if int(duration_ms) <= 0 or self._current is None:
            self.snap(value)
            return
        start = self._current
        self._target = value
        self._generation += 1
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(value)
        self._anim.setDuration(int(duration_ms))
        if self._anim.currentTime() != 0:
            self._anim.setCurrentTime(0)
        self._anim.start()

    def stop_and_keep(self) -> None:
        if not self.is_active():
            return
        self._generation += 1
        current = self._anim.currentValue()
        self._anim.stop()
        if current is not None:
            self._current = current
            self._notify(current)

    def _same_target(self, value) -> bool:
        return self._target == value

    def _on_anim_value(self, value) -> None:
        self._current = value
        self._notify(value)

    def _on_finished(self) -> None:
        if self._target is not None:
            self._current = self._target
            self._notify(self._current)

    def _notify(self, value) -> None:
        if self._owner_ref() is None or self._on_value is None:
            return
        self._on_value(value)
