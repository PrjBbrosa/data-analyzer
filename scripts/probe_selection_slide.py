#!/usr/bin/env python3
"""TraceLab selection-slide probe (Spec §5.2, Plan T6).

Measures P1 selected-background slides on real widgets and production QSS.
Script → UI only; product code must not import this module.

Reuse isolation, environment, snapshot, teardown, and synthetic-fixture
helpers from ``scripts/probe_interaction_motion.py``. Do not copy that
file. Importing this module must not create a QApplication.

Usage:
    TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_selection_slide.py \\
        --output-dir .state/selection-slide-rollout/cocoa
    TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \\
        .venv/bin/python scripts/probe_selection_slide.py --logic-only \\
        --output-dir .state/selection-slide-rollout/logic
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_motion_probe():
    name = "probe_interaction_motion"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    path = REPO_ROOT / "scripts" / "probe_interaction_motion.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_motion = _load_motion_probe()

ACTION_TIMEOUT_S = _motion.ACTION_TIMEOUT_S
GROUP_TIMEOUT_S = _motion.GROUP_TIMEOUT_S
WARMUP_COUNT = _motion.WARMUP_COUNT
WARM_SAMPLE_COUNT = _motion.WARM_SAMPLE_COUNT
STATUS_PASS = _motion.STATUS_PASS
STATUS_FAIL = _motion.STATUS_FAIL
STATUS_UNVERIFIED = _motion.STATUS_UNVERIFIED
STATUS_NOT_IN_SCOPE = _motion.STATUS_NOT_IN_SCOPE
REASON_LOGIC_ONLY = _motion.REASON_LOGIC_ONLY
REASON_OFFSCREEN = _motion.REASON_OFFSCREEN
REASON_NOT_EXPOSED = _motion.REASON_NOT_EXPOSED
REASON_NO_PAINT = _motion.REASON_NO_PAINT
REASON_NO_ENDPOINT = _motion.REASON_NO_ENDPOINT
REASON_NOT_APPLICABLE = _motion.REASON_NOT_APPLICABLE
REASON_TIMEOUT = _motion.REASON_TIMEOUT
REASON_SOURCE_CHANGED = _motion.REASON_SOURCE_CHANGED
REASON_EXCEPTION = _motion.REASON_EXCEPTION
PlatformPolicyError = _motion.PlatformPolicyError
ProbeError = _motion.ProbeError
IsolationError = _motion.IsolationError
isolate_qsettings = _motion.isolate_qsettings
prove_qsettings_isolated = _motion.prove_qsettings_isolated
environment_record = _motion.environment_record
source_snapshot = _motion.source_snapshot
snapshots_match = _motion.snapshots_match
teardown_probe = _motion.teardown_probe
drain_deferred_deletes = _motion.drain_deferred_deletes
window_is_exposed = _motion.window_is_exposed
wait_window_exposed = _motion.wait_window_exposed
require_platform = _motion.require_platform
is_offscreen_platform = _motion.is_offscreen_platform
make_synthetic_arrays = _motion.make_synthetic_arrays
make_synthetic_frame = _motion.make_synthetic_frame
TimeoutBudget = _motion.TimeoutBudget
MethodWraps = _motion.MethodWraps
pump_until = _motion.pump_until
percentile = _motion.percentile
summarize_series = _motion.summarize_series
_widget_alive = _motion._widget_alive

SCHEMA_VERSION = 1
IDLE_OBSERVE_S = 0.5
DEFAULT_OUTPUT_DIR = ".state/selection-slide-rollout"
ENTRY_BUTTON_CLICK = "button_click"
ENTRY_KEY_ACTIVATION = "key_activation"
ENTRY_PROGRAM_RESTORE = "program_restore"

P1_IDS = ("N1", "N2", "B1", "B2", "B3", "B4", "B5", "B6", "C1", "C2")
P1_REPRESENTATIVE_IDS = ("N1", "N2", "B1", "B5", "C1", "C2")
REPRESENTATIVE_SCENE_IDS = (
    "N1-empty",
    "N1-cached",
    "N2",
    "B1-phase",
    "B1-preset",
    "B5",
    "C1",
    "C2",
)
POLICIES = ("off", "light")
TIMING_FIELDS = (
    "feedback_paint_ms",
    "animation_end_ms",
    "content_ready_ms",
    "paint_intervals_ms",
    "paint_work_ms",
)
SNAPSHOT_PATHS = (
    "mf4_analyzer/ui_kit/motion.py",
    "mf4_analyzer/ui_kit/widgets/selection_indicator.py",
    "mf4_analyzer/ui_kit/widgets/segmented_choice.py",
    "mf4_analyzer/ui_kit/style.qss",
    "mf4_analyzer/ui/toolbar.py",
    "mf4_analyzer/ui/drawers/batch/method_buttons.py",
    "mf4_analyzer/ui/inspector_sections/contextual_frf.py",
    "mf4_analyzer/ui/inspector_sections/contextual_fft.py",
    "mf4_analyzer/ui/inspector_sections/contextual_fft_time.py",
    "mf4_analyzer/ui/inspector_sections/contextual_order.py",
    "mf4_analyzer/ui/inspector_sections/persistent_top.py",
    "mf4_analyzer/ui/inspector_sections/_helpers.py",
    "mf4_analyzer/ui/drawers/batch/input_panel.py",
    "mf4_analyzer/ui/drawers/batch/slice_panel.py",
    "mf4_analyzer/ui/drawers/batch/chart_statistics_panel.py",
    "mf4_analyzer/ui/chart_stack/cards.py",
    "mf4_analyzer/ui/chart_stack/_helpers.py",
)


def scene_p1_id(scene_id: str) -> str:
    return str(scene_id).split("-", 1)[0]


def representative_p1_ids(scene_ids=REPRESENTATIVE_SCENE_IDS) -> tuple[str, ...]:
    seen: list[str] = []
    for scene_id in scene_ids:
        p1 = scene_p1_id(scene_id)
        if p1 not in seen:
            seen.append(p1)
    return tuple(seen)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def _timing_reason(
    *,
    logic_only: bool,
    offscreen: bool,
    exposed: bool,
    has_paint: bool,
    animated: bool,
    timed_out: bool,
    error: str | None,
    field: str,
) -> str | None:
    if logic_only:
        return REASON_LOGIC_ONLY
    if offscreen:
        return REASON_OFFSCREEN
    if error:
        return REASON_EXCEPTION
    if timed_out:
        return REASON_TIMEOUT
    if not exposed:
        return REASON_NOT_EXPOSED
    if field == "animation_end_ms" and not animated:
        return REASON_NOT_APPLICABLE
    if field in {"feedback_paint_ms", "paint_intervals_ms", "paint_work_ms"} and not has_paint:
        return REASON_NO_PAINT
    if field == "paint_intervals_ms" and not animated:
        return REASON_NOT_APPLICABLE
    return None


def make_raw_record(
    *,
    scene_id: str,
    policy: str,
    source_fingerprint: str | None,
    target: str,
    signal_counts: Mapping[str, Any],
    final_state: Mapping[str, Any],
    platform_plugin: str,
    phase: str,
    entry_kind: str,
    seq: int,
    feedback_paint_ms: float | None = None,
    animation_end_ms: float | None = None,
    content_ready_ms: float | None = None,
    paint_intervals_ms: list[float] | None = None,
    paint_work_ms: list[float] | None = None,
    logic_only: bool = False,
    offscreen: bool = False,
    exposed: bool = False,
    has_paint: bool = False,
    animated: bool = False,
    timed_out: bool = False,
    error: str | None = None,
    extra_reasons: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build one raw row. Unmeasurable timings are null + reason, never 0."""
    values = {
        "feedback_paint_ms": feedback_paint_ms,
        "animation_end_ms": animation_end_ms,
        "content_ready_ms": content_ready_ms,
        "paint_intervals_ms": paint_intervals_ms,
        "paint_work_ms": paint_work_ms,
    }
    reasons: dict[str, str | None] = {}
    for field_name, value in values.items():
        reason = _timing_reason(
            logic_only=logic_only,
            offscreen=offscreen,
            exposed=exposed,
            has_paint=has_paint,
            animated=animated,
            timed_out=timed_out,
            error=error,
            field=field_name,
        )
        if extra_reasons and field_name in extra_reasons:
            reason = extra_reasons[field_name]
        if reason is not None:
            values[field_name] = None
            reasons[field_name] = reason
        elif value is None:
            reasons[field_name] = REASON_NO_ENDPOINT
        else:
            reasons[field_name] = None
    status = STATUS_PASS
    if error:
        status = STATUS_UNVERIFIED
    elif timed_out:
        status = STATUS_UNVERIFIED
    return {
        "scene_id": scene_id,
        "policy": policy,
        "source_fingerprint": source_fingerprint,
        "target": target,
        "signal_counts": dict(signal_counts),
        "feedback_paint_ms": values["feedback_paint_ms"],
        "animation_end_ms": values["animation_end_ms"],
        "content_ready_ms": values["content_ready_ms"],
        "paint_intervals_ms": values["paint_intervals_ms"],
        "paint_work_ms": values["paint_work_ms"],
        "null_reasons": reasons,
        "final_state": dict(final_state),
        "platform": platform_plugin,
        "phase": phase,
        "entry_kind": entry_kind,
        "seq": seq,
        "timed_out": bool(timed_out),
        "error": error,
        "status": status,
    }


def scene_status_from_records(
    records: list[Mapping[str, Any]],
    *,
    logic_only: bool,
    exposed: bool,
    timed_out: bool,
    error: str | None,
    source_changed: bool,
    contract_ok: bool,
) -> dict[str, str | None]:
    if error or timed_out or source_changed:
        reason = (
            REASON_EXCEPTION if error
            else REASON_TIMEOUT if timed_out
            else REASON_SOURCE_CHANGED
        )
        return {
            "status": STATUS_UNVERIFIED,
            "contract_status": STATUS_FAIL if (error and not contract_ok) else STATUS_UNVERIFIED,
            "performance_status": STATUS_UNVERIFIED,
            "reason": reason,
        }
    if logic_only or not exposed:
        return {
            "status": STATUS_UNVERIFIED,
            "contract_status": STATUS_PASS if contract_ok else STATUS_FAIL,
            "performance_status": STATUS_UNVERIFIED,
            "reason": REASON_LOGIC_ONLY if logic_only else REASON_NOT_EXPOSED,
        }
    return {
        "status": STATUS_PASS if contract_ok else STATUS_FAIL,
        "contract_status": STATUS_PASS if contract_ok else STATUS_FAIL,
        "performance_status": STATUS_PASS if contract_ok else STATUS_FAIL,
        "reason": None,
    }


def summarize_timing(records: list[Mapping[str, Any]], field_name: str) -> dict[str, Any] | None:
    values = [
        rec[field_name]
        for rec in records
        if rec.get("phase") == "warm" and rec.get(field_name) is not None
    ]
    if field_name in {"paint_intervals_ms", "paint_work_ms"}:
        flat: list[float] = []
        for rec in records:
            if rec.get("phase") != "warm":
                continue
            raw = rec.get(field_name)
            if isinstance(raw, list):
                flat.extend(float(v) for v in raw)
        values = flat
    return summarize_series(values) if values else None


# ---------------------------------------------------------------------------
# Qt helpers (imported only when a QApplication is allowed)
# ---------------------------------------------------------------------------

def _qapp():
    from PyQt5.QtWidgets import QApplication

    inst = QApplication.instance()
    if inst is not None:
        return inst
    return QApplication(sys.argv[:1] or ["probe-selection-slide"])


def _policy_obj(name: str):
    from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF

    return POLICY_LIGHT if name == "light" else POLICY_OFF


def _click_button(button) -> str:
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    QTest.mouseClick(button, Qt.LeftButton)
    return ENTRY_BUTTON_CLICK


def _key_click(widget, key) -> str:
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    QTest.keyClick(widget, key, Qt.NoModifier)
    return ENTRY_KEY_ACTIVATION


def _rect_dict(widget) -> dict[str, Any] | None:
    if widget is None or not _widget_alive(widget):
        return None
    rect = widget.geometry()
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "w": int(rect.width()),
        "h": int(rect.height()),
        "objectName": str(widget.objectName() or ""),
        "visible": bool(widget.isVisible()),
        "enabled": bool(widget.isEnabled()),
    }


def _indicator_of(owner, name: str | None = None):
    if owner is None:
        return None
    if name is not None:
        mapping = getattr(owner, "_choice_indicators", None)
        if isinstance(mapping, dict):
            return mapping.get(name)
    helper = getattr(owner, "_indicator", None)
    if helper is not None:
        return helper
    getter = getattr(owner, "_ensure_indicator", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return None


def _driver_of(owner, name: str | None = None):
    helper = _indicator_of(owner, name)
    if helper is None:
        driver = getattr(owner, "_motion_driver", None)
        return driver
    getter = getattr(helper, "driver", None)
    if callable(getter):
        return getter()
    return None


def _plate_of(owner, name: str | None = None):
    helper = _indicator_of(owner, name)
    if helper is None:
        return getattr(owner, "_selection_pill", None)
    plate = getattr(helper, "_plate", None)
    return plate


class PaintTap:
    """Record real paintEvent work. Never synthesizes 0 for a missed paint."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._wraps: list[tuple[Any, str, Any]] = []

    def attach(self, widget, identity: str) -> None:
        if widget is None or not _widget_alive(widget):
            return
        original = widget.paintEvent

        def painted(event):
            t0 = time.perf_counter()
            try:
                return original(event)
            finally:
                self.events.append({
                    "identity": identity,
                    "t_start": t0,
                    "t_end": time.perf_counter(),
                })

        widget.paintEvent = painted
        self._wraps.append((widget, "paintEvent", original))

    def restore(self) -> None:
        while self._wraps:
            widget, name, original = self._wraps.pop()
            try:
                if _widget_alive(widget):
                    setattr(widget, name, original)
            except Exception:
                pass

    def after(self, t0: float) -> list[dict[str, Any]]:
        return [item for item in self.events if item["t_start"] >= t0]


def _paint_metrics(tap: PaintTap, t0: float) -> tuple[float | None, list[float], list[float]]:
    events = tap.after(t0)
    if not events:
        return None, [], []
    first = events[0]
    feedback = (first["t_end"] - t0) * 1000.0
    work = [(item["t_end"] - item["t_start"]) * 1000.0 for item in events]
    intervals = [
        (cur["t_start"] - prev["t_end"]) * 1000.0
        for prev, cur in zip(events, events[1:])
    ]
    return feedback, intervals, work


def _wait_animation(app, driver, budget: Any, *, logic_only: bool) -> float | None:
    if logic_only:
        return None
    if driver is None:
        return None
    is_active = getattr(driver, "is_active", None)
    if not callable(is_active):
        return None
    if not is_active():
        return None
    ended = {"t": None}

    def mark() -> None:
        if ended["t"] is None:
            ended["t"] = time.perf_counter()

    clock = driver.clock() if callable(getattr(driver, "clock", None)) else None
    if clock is not None:
        try:
            clock.finished.connect(mark)
        except Exception:
            clock = None
    ok = pump_until(app, lambda: (not is_active()) or budget.expired("action"), ACTION_TIMEOUT_S)
    if clock is not None:
        try:
            clock.finished.disconnect(mark)
        except Exception:
            pass
    if not ok or budget.expired("action"):
        return None
    return ended["t"]


def _observe_idle(app, driver, *, logic_only: bool) -> dict[str, Any]:
    if logic_only:
        return {"spontaneous_updates": None, "reason": REASON_LOGIC_ONLY, "driver_active": None}
    starts = 0
    was_active = bool(driver is not None and driver.is_active())
    deadline = time.perf_counter() + IDLE_OBSERVE_S
    while time.perf_counter() < deadline:
        app.processEvents()
        active = bool(driver is not None and driver.is_active())
        if active and not was_active:
            starts += 1
        was_active = active
    return {
        "spontaneous_updates": starts,
        "reason": None,
        "driver_active": bool(driver is not None and driver.is_active()),
    }


def _save_png(widget, path: Path) -> bool:
    if widget is None or not _widget_alive(widget):
        return False
    try:
        pixmap = widget.grab()
        path.parent.mkdir(parents=True, exist_ok=True)
        return bool(pixmap.save(str(path), "PNG"))
    except Exception:
        return False


def capture_geometry_bundle(
    *,
    output_dir: Path,
    scene_id: str,
    policy: str,
    host,
    buttons: Mapping[str, Any],
    plate,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    shot_dir = output_dir / "screenshots"
    payload: dict[str, Any] = {
        "scene_id": scene_id,
        "policy": policy,
        "host": _rect_dict(host),
        "plate": _rect_dict(plate),
        "buttons": {key: _rect_dict(btn) for key, btn in buttons.items()},
        "files": {},
        "radius": None,
        "dpr": None,
    }
    if extra:
        payload.update(dict(extra))
    if plate is not None and _widget_alive(plate):
        helper = getattr(plate, "_indicator_ref", None)
        indicator = helper() if callable(helper) else None
        style = getattr(indicator, "_style", None) if indicator is not None else None
        if style is not None:
            payload["radius"] = int(style.radius)
    try:
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            payload["dpr"] = float(screen.devicePixelRatio())
    except Exception:
        payload["dpr"] = None
    prefix = f"{scene_id}-{policy}"
    if host is not None:
        host_path = shot_dir / f"{prefix}-host.png"
        if _save_png(host, host_path):
            payload["files"]["host"] = str(host_path)
    if plate is not None:
        plate_path = shot_dir / f"{prefix}-plate.png"
        if _save_png(plate, plate_path):
            payload["files"]["plate"] = str(plate_path)
    for key, btn in buttons.items():
        btn_path = shot_dir / f"{prefix}-button-{key}.png"
        if _save_png(btn, btn_path):
            payload["files"][f"button-{key}"] = str(btn_path)
    return payload


def try_native_recording(output_dir: Path, widget) -> dict[str, Any]:
    dest = output_dir / "native-recording.mov"
    if sys.platform != "darwin":
        return {
            "status": STATUS_UNVERIFIED,
            "reason": "native_recording_unavailable",
            "detail": f"platform={sys.platform}",
            "path": None,
        }
    ffmpeg = None
    for candidate in ("ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if candidate == "ffmpeg":
            from shutil import which

            ffmpeg = which("ffmpeg")
        elif Path(candidate).exists():
            ffmpeg = candidate
        if ffmpeg:
            break
    if not ffmpeg:
        return {
            "status": STATUS_UNVERIFIED,
            "reason": "native_recording_unavailable",
            "detail": "ffmpeg_missing",
            "path": None,
        }
    try:
        completed = subprocess.run(
            [
                ffmpeg, "-y", "-f", "avfoundation",
                "-capture_cursor", "1", "-i", "1:none",
                "-t", "2", "-pix_fmt", "yuv420p", str(dest),
            ],
            cwd=str(REPO_ROOT),
            timeout=20,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return {
            "status": STATUS_UNVERIFIED,
            "reason": "native_recording_unavailable",
            "detail": str(exc),
            "path": None,
        }
    if dest.is_file() and dest.stat().st_size > 0 and completed.returncode == 0:
        return {
            "status": STATUS_UNVERIFIED,
            "reason": "recording_captured_not_a_pass_substitute",
            "path": str(dest),
        }
    return {
        "status": STATUS_UNVERIFIED,
        "reason": "native_recording_unavailable",
        "detail": (completed.stderr or completed.stdout or "")[-400:],
        "path": None,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Scene hosts
# ---------------------------------------------------------------------------

@dataclass
class SceneHost:
    scene_id: str
    policy: str
    widget: Any
    owner: Any
    buttons: dict[str, Any]
    next_target: Callable[[int, str | None], str]
    user_activate: Callable[[str, int], str]
    program_restore: Callable[[str], None]
    restore_target: str
    signal_snapshot: Callable[[], dict[str, Any]]
    final_state: Callable[[], dict[str, Any]]
    indicator_owner: Any
    indicator_name: str | None = None
    paint_widgets: list[Any] = field(default_factory=list)
    extra_teardown: Callable[[], None] | None = None
    animated_user: bool = True
    indicator_name_for_target: Callable[[str], str | None] | None = None

    def _name_for(self, target: str | None) -> str | None:
        if target is not None and self.indicator_name_for_target is not None:
            return self.indicator_name_for_target(target)
        return self.indicator_name

    def current_indicator(self, target: str | None = None):
        return _indicator_of(self.indicator_owner, self._name_for(target))

    def current_driver(self, target: str | None = None):
        return _driver_of(self.indicator_owner, self._name_for(target))

    def current_plate(self, target: str | None = None):
        return _plate_of(self.indicator_owner, self._name_for(target))


def _show_host(app, widget, *, logic_only: bool, width: int, height: int) -> bool:
    widget.resize(width, height)
    widget.show()
    widget.raise_()
    try:
        widget.activateWindow()
    except Exception:
        pass
    app.processEvents()
    if logic_only:
        return window_is_exposed(widget)
    return wait_window_exposed(app, widget, timeout_s=4.0)


def _delta_counts(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    out = {}
    keys = set(before) | set(after)
    for key in keys:
        left = before.get(key, 0)
        right = after.get(key, 0)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            out[key] = right - left
        else:
            out[key] = {"before": left, "after": right}
    return out


def build_n1_empty(app, policy: str, *, logic_only: bool) -> SceneHost:
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.toolbar import Toolbar

    tb = Toolbar()
    tb.set_motion_policy(_policy_obj(policy))
    exposed = _show_host(app, tb, logic_only=logic_only, width=1280, height=64)
    del exposed
    spy = QSignalSpy(tb.mode_changed)
    buttons = {
        "time": tb.btn_mode_time,
        "fft": tb.btn_mode_fft,
        "fft_time": tb.btn_mode_fft_time,
        "order": tb.btn_mode_order,
        "frf": tb.btn_mode_frf,
    }
    cycle = ("fft", "time")

    def next_target(index: int, current: str | None) -> str:
        del current
        return cycle[index % 2]

    def user_activate(target: str, index: int) -> str:
        del index
        return _click_button(buttons[target])

    def program_restore(target: str) -> None:
        if tb.current_mode() == target:
            target = "fft" if target == "time" else "time"
        tb._set_mode(target)

    def signals() -> dict[str, Any]:
        return {"mode_changed": len(spy)}

    def state() -> dict[str, Any]:
        driver = _driver_of(tb)
        return {
            "mode": tb.current_mode(),
            "policy": policy,
            "driver_active": bool(driver is not None and driver.is_active()),
            "exposed": window_is_exposed(tb),
        }

    return SceneHost(
        scene_id="N1-empty",
        policy=policy,
        widget=tb,
        owner=tb,
        buttons=buttons,
        next_target=next_target,
        user_activate=user_activate,
        program_restore=program_restore,
        restore_target="time",
        signal_snapshot=signals,
        final_state=state,
        indicator_owner=tb,
        paint_widgets=[tb, getattr(tb, "_mode_segment", tb)],
    )


def build_n1_cached(app, policy: str, *, logic_only: bool, settings_dir: Path) -> SceneHost:
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.main_window import MainWindow

    del settings_dir
    window = MainWindow()
    ask = getattr(window, "_ask_use_local_time_range", None)
    if callable(ask):
        window._ask_use_local_time_range = lambda *_a, **_k: "full"
    window._prompt_unsaved_project = lambda: "discard"
    tb = window.toolbar
    tb.set_motion_policy(_policy_obj(policy))
    window.resize(1450, 850)
    window.show()
    window.raise_()
    window.activateWindow()
    if not logic_only:
        wait_window_exposed(app, window, timeout_s=4.0)
    else:
        app.processEvents()

    df, names, _summary = make_synthetic_frame(2, 10_000, 1000.0, dense=False)
    window._register_file_data(
        "probe_selection_slide_n1.mf4",
        df,
        ["Time", *names],
        {name: "Nm" for name in names},
        fs=1000.0,
    )
    fid = next(iter(window.files))
    window._on_source_load_finished([fid])
    window.navigator.set_checked_channels([(fid, names[0])])
    window.plot_time()
    app.processEvents()
    tb._set_mode("fft")
    app.processEvents()
    _motion.prime_fft_sources(window, fid, names)
    try:
        window.do_fft()
    except Exception:
        params = window.inspector.fft_ctx.compute_params()
        _t, sig, fs = window._get_sig()
        if sig is None:
            arrays, _names, _summary = make_synthetic_arrays(1, 1024, 1000.0)
            sig = arrays["方向盘扭矩"]
            fs = 1000.0
        window._fft_compute_arrays(sig, fs, params)
    pump_until(app, lambda: _motion.fft_cache_matches(window), 5.0)
    tb._set_mode("time")
    app.processEvents()

    spy = QSignalSpy(tb.mode_changed)
    buttons = {"time": tb.btn_mode_time, "fft": tb.btn_mode_fft}
    cycle = ("fft", "time")

    def next_target(index: int, current: str | None) -> str:
        del current
        return cycle[index % 2]

    def user_activate(target: str, index: int) -> str:
        del index
        return _click_button(buttons[target])

    def program_restore(target: str) -> None:
        if tb.current_mode() == target:
            target = "fft" if target == "time" else "time"
        tb._set_mode(target)

    def signals() -> dict[str, Any]:
        return {"mode_changed": len(spy)}

    def state() -> dict[str, Any]:
        driver = _driver_of(tb)
        return {
            "mode": tb.current_mode(),
            "stack_mode": window.chart_stack.current_mode(),
            "cache_matches": bool(_motion.fft_cache_matches(window)),
            "driver_active": bool(driver is not None and driver.is_active()),
            "exposed": window_is_exposed(window),
        }

    return SceneHost(
        scene_id="N1-cached",
        policy=policy,
        widget=window,
        owner=tb,
        buttons=buttons,
        next_target=next_target,
        user_activate=user_activate,
        program_restore=program_restore,
        restore_target="time",
        signal_snapshot=signals,
        final_state=state,
        indicator_owner=tb,
        paint_widgets=[tb, getattr(tb, "_mode_segment", tb)],
    )


def build_n2(app, policy: str, *, logic_only: bool) -> SceneHost:
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup

    group = MethodButtonGroup()
    group.set_motion_policy(_policy_obj(policy))
    _show_host(app, group, logic_only=logic_only, width=520, height=48)
    changed = QSignalSpy(group.methodChanged)
    activated = QSignalSpy(group.methodActivated)
    buttons = dict(group._buttons)
    cycle = ("time", "fft")

    def next_target(index: int, current: str | None) -> str:
        del current
        return cycle[index % 2]

    def user_activate(target: str, index: int) -> str:
        if index % 2 == 1:
            current = group.current_method()
            keys = tuple(group._buttons)
            current_i = keys.index(current) if current in keys else 0
            want_i = keys.index(target)
            key = Qt.Key_Right if want_i > current_i or (current_i == len(keys) - 1 and want_i == 0) else Qt.Key_Left
            buttons[current].setFocus(Qt.TabFocusReason)
            return _key_click(group, key)
        return _click_button(buttons[target])

    def program_restore(target: str) -> None:
        group.set_method(target)

    def signals() -> dict[str, Any]:
        return {
            "methodChanged": len(changed),
            "methodActivated": len(activated),
        }

    def state() -> dict[str, Any]:
        driver = _driver_of(group)
        return {
            "method": group.current_method(),
            "driver_active": bool(driver is not None and driver.is_active()),
            "exposed": window_is_exposed(group),
        }

    return SceneHost(
        scene_id="N2",
        policy=policy,
        widget=group,
        owner=group,
        buttons=buttons,
        next_target=next_target,
        user_activate=user_activate,
        program_restore=program_restore,
        restore_target="fft",
        signal_snapshot=signals,
        final_state=state,
        indicator_owner=group,
        paint_widgets=[group],
    )


def build_b1_phase(app, policy: str, *, logic_only: bool) -> SceneHost:
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.inspector_sections.contextual_frf import FrfContextual

    panel = FrfContextual()
    choice = panel.choice_phase_mode
    choice.set_motion_policy(_policy_obj(policy))
    _show_host(app, panel, logic_only=logic_only, width=320, height=900)
    choice_spy = QSignalSpy(choice.currentIndexChanged)
    display_spy = QSignalSpy(panel.display_params_changed)
    buttons = {
        "unwrapped": panel.btn_phase_unwrapped,
        "wrapped": panel.btn_phase_wrapped,
    }
    cycle = ("wrapped", "unwrapped")

    def next_target(index: int, current: str | None) -> str:
        del current
        return cycle[index % 2]

    def user_activate(target: str, index: int) -> str:
        del index
        return _click_button(buttons[target])

    def program_restore(target: str) -> None:
        choice.setCurrentIndex(1 if target == "wrapped" else 0)

    def signals() -> dict[str, Any]:
        return {
            "choice_currentIndexChanged": len(choice_spy),
            "display_params_changed": len(display_spy),
        }

    def state() -> dict[str, Any]:
        driver = choice._motion_driver
        return {
            "phase_index": int(choice.currentIndex()),
            "phase_data": panel.combo_phase_mode.currentData(),
            "driver_active": bool(driver is not None and driver.is_active()),
            "exposed": window_is_exposed(panel),
        }

    return SceneHost(
        scene_id="B1-phase",
        policy=policy,
        widget=panel,
        owner=choice,
        buttons=buttons,
        next_target=next_target,
        user_activate=user_activate,
        program_restore=program_restore,
        restore_target="unwrapped",
        signal_snapshot=signals,
        final_state=state,
        indicator_owner=choice,
        paint_widgets=[choice],
    )


def build_b1_preset(app, policy: str, *, logic_only: bool) -> SceneHost:
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.inspector_sections.contextual_frf import FrfContextual

    panel = FrfContextual()
    for name in (
        "choice_estimator",
        "choice_nfft_mode",
        "choice_magnitude_scale",
        "choice_frequency_scale",
        "choice_phase_mode",
    ):
        getattr(panel, name).set_motion_policy(_policy_obj(policy))
    _show_host(app, panel, logic_only=logic_only, width=320, height=900)
    choice = panel.choice_phase_mode
    compute_spy = QSignalSpy(panel.compute_params_changed)
    display_spy = QSignalSpy(panel.display_params_changed)
    phase_spy = QSignalSpy(choice.currentIndexChanged)
    buttons = {
        "wrapped": panel.btn_phase_wrapped,
        "preset": panel.preset_bar._load_btns[1],
    }

    def next_target(index: int, current: str | None) -> str:
        del current
        return "wrapped" if index % 2 == 0 else "preset"

    def user_activate(target: str, index: int) -> str:
        del index
        if target == "preset":
            return _click_button(buttons["preset"])
        return _click_button(buttons["wrapped"])

    def program_restore(target: str) -> None:
        del target
        panel.apply_builtin_preset("robust")

    def signals() -> dict[str, Any]:
        return {
            "compute_params_changed": len(compute_spy),
            "display_params_changed": len(display_spy),
            "phase_currentIndexChanged": len(phase_spy),
        }

    def state() -> dict[str, Any]:
        actives = {}
        for name in (
            "choice_estimator",
            "choice_nfft_mode",
            "choice_magnitude_scale",
            "choice_frequency_scale",
            "choice_phase_mode",
        ):
            driver = getattr(panel, name)._motion_driver
            actives[name] = bool(driver is not None and driver.is_active())
        return {
            "phase_index": int(choice.currentIndex()),
            "drivers_active": actives,
            "any_driver_active": any(actives.values()),
            "exposed": window_is_exposed(panel),
        }

    return SceneHost(
        scene_id="B1-preset",
        policy=policy,
        widget=panel,
        owner=choice,
        buttons=buttons,
        next_target=next_target,
        user_activate=user_activate,
        program_restore=program_restore,
        restore_target="preset",
        signal_snapshot=signals,
        final_state=state,
        indicator_owner=choice,
        paint_widgets=[choice],
        animated_user=True,
    )


def build_b5(app, policy: str, *, logic_only: bool) -> SceneHost:
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    form = DynamicParamForm()
    form.set_method("time")
    form.apply_params({"render_group_by": "source", "render_layout": "subplot"})
    choice = form._choice_render_layout
    choice.set_motion_policy(_policy_obj(policy))
    _show_host(app, form, logic_only=logic_only, width=420, height=720)
    params_spy = QSignalSpy(form.paramsChanged)
    grouping = form._grouping_cards
    buttons = {
        "none": grouping._buttons["none"],
        "source": grouping._buttons["source"],
        "overlay": choice.buttons()[0],
        "subplot": choice.buttons()[1],
    }
    cycle = ("none", "source")

    def next_target(index: int, current: str | None) -> str:
        del current
        return cycle[index % 2]

    def user_activate(target: str, index: int) -> str:
        del index
        return _click_button(buttons[target])

    def program_restore(target: str) -> None:
        form.apply_params({"render_group_by": target, "render_layout": "subplot"})

    def signals() -> dict[str, Any]:
        return {"paramsChanged": len(params_spy)}

    def state() -> dict[str, Any]:
        driver = choice._motion_driver
        return {
            "render_group_by": form.get_params().get("render_group_by"),
            "render_layout": form.get_params().get("render_layout"),
            "layout_enabled": bool(choice.isEnabled()),
            "driver_active": bool(driver is not None and driver.is_active()),
            "exposed": window_is_exposed(form),
        }

    return SceneHost(
        scene_id="B5",
        policy=policy,
        widget=form,
        owner=choice,
        buttons=buttons,
        next_target=next_target,
        user_activate=user_activate,
        program_restore=program_restore,
        restore_target="source",
        signal_snapshot=signals,
        final_state=state,
        indicator_owner=choice,
        paint_widgets=[choice, grouping],
        animated_user=False,
    )


def _plot_time_card(card) -> None:
    arrays, names, _summary = make_synthetic_arrays(2, 10_000, 1000.0, dense=False)
    t = arrays["Time"]
    rows = [
        (names[0], True, t, arrays[names[0]], "#1769e0", "Nm", "probe-a"),
        (names[1], True, t, arrays[names[1]], "#d9480f", "rpm", "probe-b"),
    ]
    card.canvas.plot_channels(rows, mode=card.plot_mode())


def build_c1(app, policy: str, *, logic_only: bool) -> SceneHost:
    from PyQt5.QtTest import QSignalSpy

    from mf4_analyzer.ui.chart_stack.cards import TimeChartCard
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    card = TimeChartCard(TimeDomainCanvasPG())
    _show_host(app, card, logic_only=logic_only, width=1200, height=420)
    _plot_time_card(card)
    card.set_motion_policy(_policy_obj(policy))
    app.processEvents()
    plot_spy = QSignalSpy(card.plot_mode_changed)
    cursor_spy = QSignalSpy(card.cursor_mode_changed)
    buttons = {
        "subplot": card.btn_subplot,
        "overlay": card.btn_overlay,
        "off": card._cursor_buttons["off"],
        "single": card._cursor_buttons["single"],
        "dual": card._cursor_buttons["dual"],
    }

    def next_target(index: int, current: str | None) -> str:
        del current
        if index % 2 == 0:
            return "overlay" if card.plot_mode() != "overlay" else "subplot"
        return "dual" if card.cursor_mode() != "dual" else "off"

    def user_activate(target: str, index: int) -> str:
        del index
        return _click_button(buttons[target])

    def program_restore(target: str) -> None:
        del target
        card.set_plot_mode("subplot")
        card.set_cursor_mode("off")

    def signals() -> dict[str, Any]:
        return {
            "plot_mode_changed": len(plot_spy),
            "cursor_mode_changed": len(cursor_spy),
        }

    def state() -> dict[str, Any]:
        plot_driver = _driver_of(card, "plot")
        cursor_driver = _driver_of(card, "cursor")
        return {
            "plot_mode": card.plot_mode(),
            "cursor_mode": card.cursor_mode(),
            "plot_driver_active": bool(plot_driver is not None and plot_driver.is_active()),
            "cursor_driver_active": bool(cursor_driver is not None and cursor_driver.is_active()),
            "exposed": window_is_exposed(card),
        }

    return SceneHost(
        scene_id="C1",
        policy=policy,
        widget=card,
        owner=card,
        buttons=buttons,
        next_target=next_target,
        user_activate=user_activate,
        program_restore=program_restore,
        restore_target="subplot",
        signal_snapshot=signals,
        final_state=state,
        indicator_owner=card,
        indicator_name="plot",
        indicator_name_for_target=lambda target: (
            "plot" if target in {"subplot", "overlay"} else "cursor"
        ),
        paint_widgets=[card.toolbar],
    )


def build_c2(app, policy: str, *, logic_only: bool) -> SceneHost:
    from PyQt5.QtTest import QSignalSpy
    from PyQt5.QtWidgets import QVBoxLayout, QWidget

    from mf4_analyzer.ui.chart_stack.cards import FrequencyCursorCard
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    holder = QWidget()
    layout = QVBoxLayout(holder)
    source = FrequencyCursorCard(PgLineCanvas(), annotations=True, chart_mode="fft")
    target = FrequencyCursorCard(PgLineCanvas(), annotations=True, chart_mode="fft")
    layout.addWidget(source)
    layout.addWidget(target)
    source.set_frequency_cursor_target_provider(lambda: target)
    source.set_motion_policy(_policy_obj(policy))
    target.set_motion_policy(_policy_obj(policy))
    _show_host(app, holder, logic_only=logic_only, width=1200, height=720)
    source_spy = QSignalSpy(source.cursor_mode_changed)
    target_spy = QSignalSpy(target.cursor_mode_changed)
    buttons = {
        "off": source._cursor_buttons["off"],
        "single": source._cursor_buttons["single"],
        "dual": source._cursor_buttons["dual"],
    }
    cycle = ("dual", "off")

    def next_target(index: int, current: str | None) -> str:
        del current
        return cycle[index % 2]

    def user_activate(target_key: str, index: int) -> str:
        del index
        return _click_button(buttons[target_key])

    def program_restore(target_key: str) -> None:
        del target_key
        target.set_cursor_mode("off")
        source.sync_frequency_cursor_control()

    def signals() -> dict[str, Any]:
        return {
            "source_cursor_mode_changed": len(source_spy),
            "target_cursor_mode_changed": len(target_spy),
        }

    def state() -> dict[str, Any]:
        source_driver = _driver_of(source, "cursor")
        target_driver = _driver_of(target, "cursor")
        return {
            "source_canvas": source.canvas.cursor_mode(),
            "target_canvas": target.canvas.cursor_mode(),
            "source_checked": next(
                (key for key, btn in source._cursor_buttons.items() if btn.isChecked()),
                None,
            ),
            "source_driver_active": bool(source_driver is not None and source_driver.is_active()),
            "target_driver_active": bool(target_driver is not None and target_driver.is_active()),
            "exposed": window_is_exposed(holder),
        }

    return SceneHost(
        scene_id="C2",
        policy=policy,
        widget=holder,
        owner=source,
        buttons=buttons,
        next_target=next_target,
        user_activate=user_activate,
        program_restore=program_restore,
        restore_target="off",
        signal_snapshot=signals,
        final_state=state,
        indicator_owner=source,
        indicator_name="cursor",
        paint_widgets=[source.toolbar, target.toolbar],
        animated_user=False,
    )


SCENE_BUILDERS: dict[str, Callable[..., SceneHost]] = {
    "N1-empty": build_n1_empty,
    "N1-cached": build_n1_cached,
    "N2": build_n2,
    "B1-phase": build_b1_phase,
    "B1-preset": build_b1_preset,
    "B5": build_b5,
    "C1": build_c1,
    "C2": build_c2,
}


# ---------------------------------------------------------------------------
# Scene execution
# ---------------------------------------------------------------------------

def _attach_paints(host: SceneHost, tap: PaintTap) -> None:
    tap.attach(host.widget, f"{host.scene_id}:widget")
    plate = host.current_plate()
    if plate is not None:
        tap.attach(plate, f"{host.scene_id}:plate")
    for widget in host.paint_widgets:
        tap.attach(widget, f"{host.scene_id}:paint")


def _should_count_animation(host: SceneHost, target: str, entry_kind: str) -> bool:
    if entry_kind == ENTRY_PROGRAM_RESTORE:
        return False
    if host.policy != "light":
        return False
    if host.scene_id == "B5":
        return False
    if host.scene_id == "B1-preset" and target == "preset":
        return False
    if host.scene_id == "C2":
        return False
    return bool(host.animated_user)


def run_one_action(
    app,
    host: SceneHost,
    *,
    target: str,
    phase: str,
    seq: int,
    entry_kind_hint: str | None,
    index: int,
    budget: Any,
    tap: PaintTap,
    logic_only: bool,
    offscreen: bool,
    exposed: bool,
    fingerprint: str | None,
    platform_plugin: str,
) -> dict[str, Any]:
    budget.start_action()
    before = host.signal_snapshot()
    driver = host.current_driver(target)
    animated = _should_count_animation(host, target, entry_kind_hint or ENTRY_BUTTON_CLICK)
    t0 = time.perf_counter()
    error = None
    timed_out = False
    entry_kind = entry_kind_hint or ENTRY_BUTTON_CLICK
    try:
        if entry_kind == ENTRY_PROGRAM_RESTORE:
            host.program_restore(target)
            entry_kind = ENTRY_PROGRAM_RESTORE
        else:
            entry_kind = host.user_activate(target, index)
        app.processEvents()
        t_callback = time.perf_counter()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        t_callback = time.perf_counter()
    content_ready = (t_callback - t0) * 1000.0
    anim_end_t = None
    if animated and error is None and not logic_only:
        anim_end_t = _wait_animation(
            app, host.current_driver(target), budget, logic_only=logic_only,
        )
    if budget.expired("action") or budget.expired("group"):
        timed_out = True
    feedback, intervals, work = _paint_metrics(tap, t0)
    has_paint = bool(work) and exposed and not logic_only and not offscreen
    after = host.signal_snapshot()
    animation_end = None if anim_end_t is None else (anim_end_t - t0) * 1000.0
    extra_reasons = {}
    if entry_kind == ENTRY_PROGRAM_RESTORE or not animated:
        extra_reasons["animation_end_ms"] = REASON_NOT_APPLICABLE
        extra_reasons["paint_intervals_ms"] = REASON_NOT_APPLICABLE
    record = make_raw_record(
        scene_id=host.scene_id,
        policy=host.policy,
        source_fingerprint=fingerprint,
        target=target,
        signal_counts=_delta_counts(before, after),
        final_state=host.final_state(),
        platform_plugin=platform_plugin,
        phase=phase,
        entry_kind=entry_kind,
        seq=seq,
        feedback_paint_ms=feedback,
        animation_end_ms=animation_end,
        content_ready_ms=content_ready,
        paint_intervals_ms=intervals or None,
        paint_work_ms=work or None,
        logic_only=logic_only,
        offscreen=offscreen,
        exposed=exposed,
        has_paint=has_paint,
        animated=animated,
        timed_out=timed_out,
        error=error,
        extra_reasons=extra_reasons,
    )
    record["input_callback_ms"] = None if logic_only or offscreen else content_ready
    if logic_only or offscreen:
        record["null_reasons"]["input_callback_ms"] = (
            REASON_LOGIC_ONLY if logic_only else REASON_OFFSCREEN
        )
        record["input_callback_ms"] = None
    else:
        record["null_reasons"]["input_callback_ms"] = None
    record["driver_was_present"] = driver is not None
    if timed_out:
        record["status"] = STATUS_UNVERIFIED
    return record


def run_scene_policy(
    app,
    scene_id: str,
    policy: str,
    *,
    logic_only: bool,
    offscreen: bool,
    warmup: int,
    samples: int,
    output_dir: Path,
    fingerprint: str | None,
    settings_dir: Path,
    capture_shots: bool,
) -> dict[str, Any]:
    budget = TimeoutBudget()
    budget.start_group()
    builder = SCENE_BUILDERS[scene_id]
    host = None
    tap = PaintTap()
    wraps = MethodWraps()
    records: list[dict[str, Any]] = []
    error = None
    timed_out = False
    geometry = None
    idle = None
    platform_plugin = ""
    exposed = False
    try:
        platform_plugin = str(app.platformName() if hasattr(app, "platformName") else "")
        if scene_id == "N1-cached":
            host = builder(app, policy, logic_only=logic_only, settings_dir=settings_dir)
        else:
            host = builder(app, policy, logic_only=logic_only)
        exposed = window_is_exposed(host.widget)
        _attach_paints(host, tap)
        seq = 0
        current = None
        first_target = host.next_target(0, current)
        seq += 1
        records.append(
            run_one_action(
                app, host, target=first_target, phase="first_access", seq=seq,
                entry_kind_hint=ENTRY_BUTTON_CLICK, index=0, budget=budget, tap=tap,
                logic_only=logic_only, offscreen=offscreen, exposed=exposed,
                fingerprint=fingerprint, platform_plugin=platform_plugin,
            )
        )
        current = first_target
        if capture_shots and not logic_only:
            focus_btn = host.buttons.get(first_target)
            if focus_btn is not None:
                try:
                    focus_btn.setFocus()
                    app.processEvents()
                except Exception:
                    pass
            geometry = capture_geometry_bundle(
                output_dir=output_dir,
                scene_id=scene_id,
                policy=policy,
                host=host.widget,
                buttons=host.buttons,
                plate=host.current_plate(),
                extra={"focus_target": first_target, "phase": "first_access"},
            )
            disabled_key = next(
                (key for key in host.buttons if key != first_target),
                first_target,
            )
            disabled_btn = host.buttons.get(disabled_key)
            if disabled_btn is not None and _widget_alive(disabled_btn):
                was_enabled = disabled_btn.isEnabled()
                disabled_btn.setEnabled(False)
                app.processEvents()
                disabled_path = output_dir / "screenshots" / f"{scene_id}-{policy}-disabled.png"
                if _save_png(host.widget, disabled_path):
                    geometry.setdefault("files", {})["disabled"] = str(disabled_path)
                disabled_btn.setEnabled(was_enabled)
                app.processEvents()
        for i in range(int(warmup)):
            if budget.expired("group"):
                timed_out = True
                break
            target = host.next_target(i + 1, current)
            seq += 1
            records.append(
                run_one_action(
                    app, host, target=target, phase="warmup", seq=seq,
                    entry_kind_hint=None, index=i + 1, budget=budget, tap=tap,
                    logic_only=logic_only, offscreen=offscreen, exposed=exposed,
                    fingerprint=fingerprint, platform_plugin=platform_plugin,
                )
            )
            current = target
            if records[-1]["timed_out"]:
                timed_out = True
                break
        for i in range(int(samples)):
            if budget.expired("group"):
                timed_out = True
                break
            target = host.next_target(warmup + 1 + i, current)
            seq += 1
            records.append(
                run_one_action(
                    app, host, target=target, phase="warm", seq=seq,
                    entry_kind_hint=None, index=warmup + 1 + i, budget=budget, tap=tap,
                    logic_only=logic_only, offscreen=offscreen, exposed=exposed,
                    fingerprint=fingerprint, platform_plugin=platform_plugin,
                )
            )
            current = target
            if records[-1]["timed_out"]:
                timed_out = True
                break
        if not timed_out:
            seq += 1
            records.append(
                run_one_action(
                    app, host, target=host.restore_target, phase="program_restore",
                    seq=seq, entry_kind_hint=ENTRY_PROGRAM_RESTORE, index=0,
                    budget=budget, tap=tap, logic_only=logic_only, offscreen=offscreen,
                    exposed=exposed, fingerprint=fingerprint,
                    platform_plugin=platform_plugin,
                )
            )
        idle = _observe_idle(app, host.current_driver() if host else None, logic_only=logic_only)
        if any(rec.get("error") for rec in records):
            error = next(rec["error"] for rec in records if rec.get("error"))
        if any(rec.get("timed_out") for rec in records):
            timed_out = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        records.append(
            make_raw_record(
                scene_id=scene_id,
                policy=policy,
                source_fingerprint=fingerprint,
                target="",
                signal_counts={},
                final_state={"traceback": traceback.format_exc()},
                platform_plugin=platform_plugin,
                phase="error",
                entry_kind=ENTRY_BUTTON_CLICK,
                seq=len(records) + 1,
                logic_only=logic_only,
                offscreen=offscreen,
                exposed=exposed,
                has_paint=False,
                animated=False,
                timed_out=False,
                error=error,
            )
        )
    finally:
        tap.restore()
        wraps.restore()
        extra = host.extra_teardown if host is not None else None
        if callable(extra):
            try:
                extra()
            except Exception:
                pass
        widget = host.widget if host is not None else None
        if widget is not None and _widget_alive(widget):
            try:
                widget.hide()
            except Exception:
                pass
        teardown_probe(app=app, window=widget)

    warm = [rec for rec in records if rec.get("phase") == "warm"]
    contract_ok = all(rec.get("error") is None for rec in records) and not timed_out
    if scene_id == "C2":
        for rec in records:
            if rec.get("phase") in {"first_access", "warmup", "warm"} and rec.get("entry_kind") != ENTRY_PROGRAM_RESTORE:
                if rec.get("signal_counts", {}).get("source_cursor_mode_changed", 0) not in (0,):
                    contract_ok = False
    statuses = scene_status_from_records(
        records,
        logic_only=logic_only,
        exposed=exposed,
        timed_out=timed_out,
        error=error,
        source_changed=False,
        contract_ok=contract_ok,
    )
    statistics = {
        field_name: summarize_timing(records, field_name) for field_name in TIMING_FIELDS
    }
    if logic_only or offscreen or not exposed:
        reason = (
            REASON_LOGIC_ONLY if logic_only
            else REASON_OFFSCREEN if offscreen
            else REASON_NOT_EXPOSED
        )
        statistics = {name: None for name in TIMING_FIELDS}
        statistics["null_reason"] = reason
    else:
        statistics["null_reason"] = None
        if all(statistics[name] is None for name in TIMING_FIELDS):
            statistics["null_reason"] = REASON_NO_ENDPOINT
    return {
        "id": scene_id,
        "p1_id": scene_p1_id(scene_id),
        "policy": policy,
        "config": {
            "warmup": warmup,
            "samples": samples,
            "idle_observe_s": IDLE_OBSERVE_S,
        },
        "records": records,
        "first_access": next((rec for rec in records if rec.get("phase") == "first_access"), None),
        "program_restore": next((rec for rec in records if rec.get("phase") == "program_restore"), None),
        "warm_count": len(warm),
        "statistics": statistics,
        "geometry": geometry,
        "idle": idle,
        "final_state": records[-1]["final_state"] if records else {},
        "errors_local": [] if error is None else [error],
        **statuses,
    }


def run_all_scenes(
    *,
    logic_only: bool,
    output_dir: Path,
    warmup: int,
    samples: int,
    scene_ids: list[str] | None = None,
    capture_shots: bool = True,
    record_screen: bool = False,
) -> dict[str, Any]:
    app = _qapp()
    require_platform(logic_only=logic_only, app=app)
    offscreen = is_offscreen_platform(app)
    output_dir.mkdir(parents=True, exist_ok=True)
    settings_dir = Path(tempfile.mkdtemp(prefix="probe-selection-slide-", dir=str(output_dir)))
    token = isolate_qsettings(settings_dir)
    isolated_path = prove_qsettings_isolated(token)
    snapshot_before = source_snapshot(SNAPSHOT_PATHS)
    errors: list[str] = []
    scenarios: list[dict[str, Any]] = []
    recording = None
    stylesheet_prev = app.styleSheet()
    try:
        if not logic_only:
            from mf4_analyzer.ui_kit.stylesheet import load_stylesheet

            load_stylesheet(app)
        selected = list(scene_ids or REPRESENTATIVE_SCENE_IDS)
        for scene_id in selected:
            if scene_id not in SCENE_BUILDERS:
                errors.append(f"unknown scene {scene_id}")
                continue
            for policy in POLICIES:
                scenarios.append(
                    run_scene_policy(
                        app, scene_id, policy,
                        logic_only=logic_only,
                        offscreen=offscreen,
                        warmup=warmup,
                        samples=samples,
                        output_dir=output_dir,
                        fingerprint=snapshot_before.get("fingerprint"),
                        settings_dir=settings_dir,
                        capture_shots=capture_shots and not logic_only,
                    )
                )
        if record_screen and not logic_only:
            recording = try_native_recording(output_dir, None)
            _write_json(output_dir / "recording.json", recording)
        elif not logic_only:
            recording = {
                "status": STATUS_UNVERIFIED,
                "reason": "native_recording_not_requested_or_unavailable",
                "path": None,
            }
            _write_json(output_dir / "recording.json", recording)
    except PlatformPolicyError:
        token.restore()
        raise
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    finally:
        try:
            app.setStyleSheet(stylesheet_prev)
        except Exception:
            pass
        token.restore()
        drain_deferred_deletes(app)

    snapshot_after = source_snapshot(SNAPSHOT_PATHS)
    source_changed = not snapshots_match(snapshot_before, snapshot_after)
    if source_changed:
        errors.append(REASON_SOURCE_CHANGED)
        for scenario in scenarios:
            scenario["status"] = STATUS_UNVERIFIED
            scenario["performance_status"] = STATUS_UNVERIFIED
            scenario["reason"] = REASON_SOURCE_CHANGED
    env = environment_record(
        app,
        logic_only=logic_only,
        extra={
            "command": "selection_slide",
            "qsettings": isolated_path,
            "recording": recording,
        },
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "environment": env,
        "source_snapshot_before": snapshot_before,
        "source_snapshot_after": snapshot_after,
        "representative_scene_ids": list(scene_ids or REPRESENTATIVE_SCENE_IDS),
        "p1_representative_ids": list(representative_p1_ids(scene_ids or REPRESENTATIVE_SCENE_IDS)),
        "p1_ids": list(P1_IDS),
        "scenarios": scenarios,
        "errors": errors,
        "recording": recording,
    }
    if logic_only:
        for scenario in report["scenarios"]:
            scenario["performance_status"] = STATUS_UNVERIFIED
            if scenario.get("status") == STATUS_PASS:
                scenario["status"] = STATUS_UNVERIFIED
            stats = scenario.get("statistics") or {}
            for name in TIMING_FIELDS:
                stats[name] = None
            stats["null_reason"] = REASON_LOGIC_ONLY
            scenario["statistics"] = stats
            for rec in scenario.get("records") or []:
                for name in TIMING_FIELDS:
                    rec[name] = None
                    rec.setdefault("null_reasons", {})[name] = REASON_LOGIC_ONLY
    _write_json(output_dir / "selection-slide.json", report)
    raw_path = output_dir / "records.json"
    _write_json(raw_path, {"records": [rec for sc in scenarios for rec in sc.get("records") or []]})
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for JSON/PNG/recording artifacts",
    )
    parser.add_argument("--logic-only", action="store_true")
    parser.add_argument("--warmup", type=int, default=WARMUP_COUNT)
    parser.add_argument("--samples", type=int, default=WARM_SAMPLE_COUNT)
    parser.add_argument("--scene", action="append", default=[])
    parser.add_argument("--record-screen", action="store_true")
    parser.add_argument("--skip-screenshots", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    try:
        report = run_all_scenes(
            logic_only=bool(args.logic_only),
            output_dir=output_dir,
            warmup=int(args.warmup),
            samples=int(args.samples),
            scene_ids=list(args.scene) or None,
            capture_shots=not args.skip_screenshots,
            record_screen=bool(args.record_screen),
        )
    except PlatformPolicyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    except ProbeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    errors = report.get("errors") or []
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
