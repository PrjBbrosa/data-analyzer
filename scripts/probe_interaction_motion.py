#!/usr/bin/env python3
"""TraceLab native interaction-motion probe (Spec §6, Plan T5).

Measures real View / section switches. Script → UI only; product code must
not import this module. Does not change historical metrics in
``probe_view_switch_quality.py`` and does not import that script's settle
waits.

Usage:
    TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_interaction_motion.py \\
        samples --output-dir .state/native-interaction-motion/cocoa-samples
    TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/probe_interaction_motion.py \\
        switches --output-dir .state/native-interaction-motion/cocoa-switches

Offscreen may only run ``--logic-only`` (event / JSON contracts). Performance
fields stay null. Requesting a Cocoa performance report on an offscreen
platform is an explicit failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = 1
ACTION_TIMEOUT_S = 30.0
GROUP_TIMEOUT_S = 180.0
INIT_TIMEOUT_S = 30.0
WARMUP_COUNT = 5
WARM_SAMPLE_COUNT = 40
COLD_PROCESS_COUNT = 5
FIXTURE_SEED = 20260905
HEARTBEAT_INTERVAL_MS = 16

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_UNVERIFIED = "UNVERIFIED"
STATUS_NOT_IN_SCOPE = "NOT_IN_SCOPE"

ENTRY_TAB_CLICK = "tab_click"
ENTRY_TOOLBAR_BUTTON = "toolbar_button"
ENTRY_DIRECT_CALL = "direct_call"

REASON_LOGIC_ONLY = "logic_only"
REASON_OFFSCREEN = "offscreen"
REASON_NOT_EXPOSED = "not_exposed"
REASON_NO_PAINT = "no_paint"
REASON_NO_ENDPOINT = "no_endpoint"
REASON_NOT_APPLICABLE = "not_applicable"
REASON_TIMEOUT = "timeout"
REASON_SOURCE_CHANGED = "source_changed"
REASON_EXCEPTION = "exception"

TIMING_FIELDS = (
    "input_callback_ms",
    "feedback_paint_ms",
    "content_ready_ms",
    "stable_paint_ms",
    "paint_work_ms",
    "paint_interval_ms",
    "event_loop_lag_ms",
)

SNAPSHOT_PATHS = (
    "mf4_analyzer/ui/main_window/window.py",
    "mf4_analyzer/ui/main_window/_view_mixin.py",
    "mf4_analyzer/ui/main_window/_fft_mixin.py",
    "mf4_analyzer/ui/toolbar.py",
    "mf4_analyzer/ui/view_tabbar.py",
)

CHANNEL_NAMES = (
    "方向盘扭矩",
    "电机转速",
    "电机扭矩",
    "Rack Force",
    "Rack Travel",
    "电机相电流U",
    "电机相电流V",
    "转向角",
)

SCENARIO_M01_SMALL = "M01-small"
SCENARIO_M01_DENSE = "M01-dense"
SCENARIO_M02_EMPTY = "M02-empty"
SCENARIO_M02_CACHED = "M02-cached"
ALL_SWITCH_SCENARIOS = (
    SCENARIO_M01_SMALL,
    SCENARIO_M01_DENSE,
    SCENARIO_M02_EMPTY,
    SCENARIO_M02_CACHED,
)
SAMPLE_IDS = ("S01", "S02", "S03", "S04", "S05", "S06", "S07")
ABBA_MODES = ("current", "light")


class ProbeError(Exception):
    """User-visible probe failure that should stop the current command."""


class PlatformPolicyError(ProbeError):
    """Offscreen environment asked to emit a Cocoa performance report."""


class IsolationError(ProbeError):
    """QSettings or recent-project isolation could not be proven."""


# ---------------------------------------------------------------------------
# Environment / platform
# ---------------------------------------------------------------------------

def platform_plugin_name(app=None) -> str:
    env = os.environ.get("QT_QPA_PLATFORM", "")
    if app is not None:
        name = getattr(app, "platformName", None)
        if callable(name):
            try:
                return str(name() or env or "")
            except Exception:
                return env
    return env


def is_offscreen_platform(app=None) -> bool:
    return platform_plugin_name(app).lower() == "offscreen"


def require_platform(*, logic_only: bool, app=None) -> dict[str, Any]:
    """Fail before any Cocoa performance report is attempted on offscreen."""
    plugin = platform_plugin_name(app)
    offscreen = plugin.lower() == "offscreen"
    if offscreen and not logic_only:
        raise PlatformPolicyError(
            "QT_QPA_PLATFORM=offscreen cannot produce a Cocoa performance "
            "report; pass --logic-only for event/serialization contracts."
        )
    return {
        "platform_plugin": plugin,
        "offscreen": offscreen,
        "logic_only": bool(logic_only),
        "allowed": True,
    }


def _qapp():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv[:1] or ["probe"])


def window_is_exposed(widget) -> bool:
    if widget is None:
        return False
    handle = getattr(widget, "windowHandle", lambda: None)()
    try:
        return bool(handle is not None and handle.isExposed())
    except Exception:
        return False


def wait_window_exposed(app, widget, *, timeout_s: float = 4.0) -> bool:
    deadline = time.perf_counter() + timeout_s
    handle = None
    while time.perf_counter() < deadline:
        app.processEvents()
        handle = widget.windowHandle() if handle is None else handle
        if window_is_exposed(widget):
            app.processEvents()
            return True
        time.sleep(0.01)
    return False


def environment_record(app=None, *, logic_only: bool, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "platform_plugin": platform_plugin_name(app),
        "logic_only": bool(logic_only),
        "presentation_timestamp_available": False,
        "refresh_hz": None,
        "dpr": None,
        "qt": None,
        "pyqt": None,
        "pyqtgraph": None,
        "loadavg": None,
    }
    try:
        info["loadavg"] = list(os.getloadavg())
    except OSError:
        info["loadavg"] = None
    if app is not None:
        try:
            from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR

            info["qt"] = QT_VERSION_STR
            info["pyqt"] = PYQT_VERSION_STR
        except Exception:
            pass
        try:
            screen = app.primaryScreen()
            if screen is not None:
                info["dpr"] = float(screen.devicePixelRatio())
                rate = float(screen.refreshRate())
                info["refresh_hz"] = rate if rate > 0 else None
        except Exception:
            pass
    try:
        import pyqtgraph

        info["pyqtgraph"] = getattr(pyqtgraph, "__version__", None)
    except Exception:
        pass
    if extra:
        info.update(dict(extra))
    return info


# ---------------------------------------------------------------------------
# QSettings isolation (IniFormat + NativeFormat two-arg constructor)
# ---------------------------------------------------------------------------

@dataclass
class SettingsIsolation:
    tmp_dir: Path
    ini_path: Path
    originals: dict[str, Any] = field(default_factory=dict)

    def restore(self) -> None:
        from PyQt5.QtCore import QSettings

        for key, value in self.originals.items():
            if key == "QSettings.__init__":
                QSettings.__init__ = value
            elif key.startswith("attr:"):
                obj, name = value[0], value[1]
                setattr(obj, name, value[2])
            elif key == "default_format":
                QSettings.setDefaultFormat(value)


def isolate_qsettings(tmp_dir: Path | str) -> SettingsIsolation:
    """Divert every persistent store the probe can construct.

    ``QSettings(org, app)`` hard-binds NativeFormat and ignores
    ``setDefaultFormat`` / ``setPath``. That constructor is wrapped, and
    NativeFormat paths are redirected as well.
    """
    from PyQt5.QtCore import QSettings

    tmp = Path(tmp_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    ini = tmp / "qsettings.ini"
    token = SettingsIsolation(tmp_dir=tmp, ini_path=ini)
    token.originals["QSettings.__init__"] = QSettings.__init__
    token.originals["default_format"] = QSettings.defaultFormat()

    def temp_settings(*_args, **_kwargs):
        return QSettings(str(ini), QSettings.IniFormat)

    modules: list[tuple[str, str]] = [
        ("mf4_analyzer.ui.inspector_sections", "_preset_settings"),
        ("mf4_analyzer.ui.inspector_sections._helpers", "_preset_settings"),
        ("mf4_analyzer.ui.inspector_sections.collapsible", "_preset_settings"),
        ("mf4_analyzer.ui.inspector_sections.presets", "_preset_settings"),
        ("mf4_analyzer.ui.inspector_sections.persistent_top", "_preset_settings"),
        ("mf4_analyzer.ui.batch_settings", "_default_settings"),
        ("mf4_analyzer.ui.recent_files", "_default_settings"),
    ]
    for mod_name, attr in modules:
        try:
            module = __import__(mod_name, fromlist=[attr])
        except Exception:
            continue
        if hasattr(module, attr):
            token.originals[f"attr:{mod_name}.{attr}"] = (module, attr, getattr(module, attr))
            setattr(module, attr, temp_settings)

    orig_init = QSettings.__init__

    def _patched_init(self, *args, **kwargs):
        if _is_native_org_app_ctor(args):
            orig_init(self, str(ini), QSettings.IniFormat)
            return
        orig_init(self, *args, **kwargs)

    QSettings.__init__ = _patched_init
    QSettings.setDefaultFormat(QSettings.IniFormat)
    for fmt in (QSettings.IniFormat, QSettings.NativeFormat):
        QSettings.setPath(fmt, QSettings.UserScope, str(tmp))
        QSettings.setPath(fmt, QSettings.SystemScope, str(tmp))
    return token


def _is_native_org_app_ctor(args: tuple[Any, ...]) -> bool:
    from PyQt5.QtCore import QSettings

    if not args:
        return False
    first = args[0]
    if first == QSettings.NativeFormat:
        return True
    if len(args) >= 2 and isinstance(first, str) and isinstance(args[1], str):
        if first.endswith((".ini", ".plist", ".conf")):
            return False
        if os.sep in first or first.startswith("/") or first.startswith("~"):
            return False
        return True
    return False


def prove_qsettings_isolated(token: SettingsIsolation) -> str:
    from PyQt5.QtCore import QSettings

    store = QSettings("MF4Analyzer", "DataAnalyzer")
    path = str(store.fileName())
    expected = str(token.ini_path)
    native_home = str(Path.home() / "Library" / "Preferences")
    if native_home in path and "MF4Analyzer" in path:
        raise IsolationError(
            f"NativeFormat two-arg QSettings still resolved to {path}"
        )
    if expected not in path and str(token.tmp_dir) not in path:
        raise IsolationError(
            f"isolated QSettings fileName={path!r} is outside {token.tmp_dir}"
        )
    store.setValue("probe/isolation_marker", "ok")
    store.sync()
    return path


# ---------------------------------------------------------------------------
# Source snapshot
# ---------------------------------------------------------------------------

def source_snapshot(paths: Iterable[str] = SNAPSHOT_PATHS) -> dict[str, Any]:
    files = {}
    digest = hashlib.sha256()
    for rel in paths:
        path = REPO_ROOT / rel
        if not path.is_file():
            files[rel] = None
            digest.update(f"missing:{rel}\n".encode())
            continue
        payload = path.read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        files[rel] = {"sha256": sha, "bytes": len(payload)}
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(sha.encode())
        digest.update(b"\n")
    return {
        "fingerprint": digest.hexdigest(),
        "files": files,
        "head": _git_head(),
    }


def _git_head() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return None


def snapshots_match(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return before.get("fingerprint") == after.get("fingerprint")


# ---------------------------------------------------------------------------
# Synthetic fixtures (Spec §6.1)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FixtureSpec:
    n_ch: int
    n_points: int
    fs: float
    dense: bool
    names: tuple[str, ...]
    summary: dict[str, Any]


def make_synthetic_arrays(
    n_ch: int,
    n_points: int,
    fs: float,
    *,
    dense: bool = False,
) -> tuple[Any, tuple[str, ...], dict[str, Any]]:
    import numpy as np

    n_ch = int(n_ch)
    n_points = int(n_points)
    fs = float(fs)
    t = np.arange(n_points, dtype=np.float64) / fs
    names = CHANNEL_NAMES[:n_ch]
    rng = np.random.default_rng(FIXTURE_SEED) if dense else None
    channels: dict[str, Any] = {"Time": t}
    summaries = []
    for i, name in enumerate(names):
        y = np.sin(2.0 * np.pi * (11.0 + 7.0 * i) * t)
        y = y + 0.15 * np.sin(2.0 * np.pi * (47.0 + 3.0 * i) * t)
        if dense:
            y = y + 0.02 * rng.standard_normal(n_points)
        y = np.asarray(y, dtype=np.float64)
        channels[name] = y
        summaries.append(_array_summary(name, y))
    summary = {
        "n_ch": n_ch,
        "n_points": n_points,
        "fs": fs,
        "dense": dense,
        "seed": FIXTURE_SEED if dense else None,
        "dtype": "float64",
        "time": _array_summary("Time", t),
        "channels": summaries,
        "unit": "Nm",
        "unit_kind": "synthetic",
    }
    return channels, names, summary


def make_synthetic_frame(
    n_ch: int,
    n_points: int,
    fs: float,
    *,
    dense: bool = False,
):
    import pandas as pd

    channels, names, summary = make_synthetic_arrays(
        n_ch, n_points, fs, dense=dense
    )
    return pd.DataFrame(channels), names, summary


def fixture_for_scenario(scenario_id: str) -> FixtureSpec:
    if scenario_id == SCENARIO_M01_DENSE:
        n_ch, n_points, fs, dense = 8, 1_000_000, 20_000.0, True
    else:
        n_ch, n_points, fs, dense = 2, 10_000, 1_000.0, False
    _channels, names, summary = make_synthetic_arrays(
        n_ch, n_points, fs, dense=dense
    )
    return FixtureSpec(n_ch, n_points, fs, dense, names, summary)


def _array_summary(name: str, values) -> dict[str, Any]:
    import numpy as np

    arr = np.asarray(values)
    digest = hashlib.sha256()
    digest.update(arr[:8].tobytes())
    digest.update(arr[-8:].tobytes())
    return {
        "name": name,
        "dtype": str(arr.dtype),
        "shape": list(arr.shape),
        "min": float(arr.min()) if arr.size else None,
        "max": float(arr.max()) if arr.size else None,
        "mean": float(arr.mean()) if arr.size else None,
        "ends_sha256": digest.hexdigest()[:16],
    }


# ---------------------------------------------------------------------------
# Measurement core
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    seq: int
    entry_kind: str
    target_identity: str
    t_input: float
    t_callback_return: float | None = None
    identity_ready: bool = False
    xlim_ready: bool = False
    ylim_ready: bool = False
    settle_ready: bool = False
    cache_ready: bool = False
    require_geometry: bool = True
    require_cache: bool = False
    content_ready_t: float | None = None
    compute_submits: int = 0
    error: str | None = None
    timed_out: bool = False

    @property
    def input_callback_ms(self) -> float | None:
        if self.t_callback_return is None:
            return None
        return (self.t_callback_return - self.t_input) * 1000.0

    @property
    def content_ready_ms(self) -> float | None:
        if self.content_ready_t is None:
            return None
        return (self.content_ready_t - self.t_input) * 1000.0


@dataclass
class PaintRecord:
    seq: int
    action_seq: int | None
    target_identity: str | None
    t_start: float
    t_end: float
    after_content_ready: bool = False
    animation_active: bool = False

    @property
    def work_ms(self) -> float:
        return (self.t_end - self.t_start) * 1000.0


class ActionSession:
    """Bind paints to actions by event sequence + target identity."""

    def __init__(self) -> None:
        self.actions: list[ActionRecord] = []
        self.direct_call_actions: list[ActionRecord] = []
        self.paints: list[PaintRecord] = []
        self.lags_ms: list[float] = []
        self._seq = 0
        self._paint_seq = 0
        self.animation_active = False
        self.compute_submits = 0

    def begin(
        self,
        entry_kind: str,
        target_identity: str,
        *,
        require_geometry: bool = True,
        require_cache: bool = False,
        t_input: float | None = None,
    ) -> ActionRecord:
        self._seq += 1
        action = ActionRecord(
            seq=self._seq,
            entry_kind=entry_kind,
            target_identity=target_identity,
            t_input=time.perf_counter() if t_input is None else t_input,
            require_geometry=require_geometry,
            require_cache=require_cache,
        )
        if entry_kind == ENTRY_DIRECT_CALL:
            self.direct_call_actions.append(action)
        else:
            self.actions.append(action)
        return action

    def finish_callback(self, action: ActionRecord, t: float | None = None) -> None:
        action.t_callback_return = time.perf_counter() if t is None else t

    def note_identity(self, action: ActionRecord, identity: str, t: float | None = None) -> None:
        if identity == action.target_identity:
            action.identity_ready = True
            self._maybe_content_ready(action, t)

    def note_xlim(self, action: ActionRecord, t: float | None = None) -> None:
        action.xlim_ready = True
        self._maybe_content_ready(action, t)

    def note_ylim(self, action: ActionRecord, t: float | None = None) -> None:
        action.ylim_ready = True
        self._maybe_content_ready(action, t)

    def note_settle(self, action: ActionRecord, t: float | None = None) -> None:
        action.settle_ready = True
        self._maybe_content_ready(action, t)

    def note_cache(self, action: ActionRecord, matched: bool, t: float | None = None) -> None:
        action.cache_ready = bool(matched)
        self._maybe_content_ready(action, t)

    def note_compute_submit(self, action: ActionRecord | None = None) -> None:
        self.compute_submits += 1
        if action is not None:
            action.compute_submits += 1

    def note_error(self, action: ActionRecord | None, exc: BaseException) -> None:
        text = f"{type(exc).__name__}: {exc}"
        if action is not None:
            action.error = text

    def note_timeout(self, action: ActionRecord | None) -> None:
        if action is not None:
            action.timed_out = True

    def discard(self, action: ActionRecord) -> None:
        self.paints = [paint for paint in self.paints if paint.action_seq != action.seq]
        if action in self.actions:
            self.actions.remove(action)
        if action in self.direct_call_actions:
            self.direct_call_actions.remove(action)

    def note_paint(
        self,
        target_identity: str | None,
        t_start: float,
        t_end: float,
        *,
        animation_active: bool | None = None,
    ) -> PaintRecord:
        owner = self._owner_for_paint(target_identity, t_start)
        after_ready = bool(
            owner is not None
            and owner.content_ready_t is not None
            and t_end >= owner.content_ready_t
        )
        self._paint_seq += 1
        rec = PaintRecord(
            seq=self._paint_seq,
            action_seq=None if owner is None else owner.seq,
            target_identity=target_identity,
            t_start=t_start,
            t_end=t_end,
            after_content_ready=after_ready,
            animation_active=self.animation_active if animation_active is None else animation_active,
        )
        self.paints.append(rec)
        return rec

    def note_lag(self, planned_t: float, actual_t: float) -> float:
        lag = (actual_t - planned_t) * 1000.0
        self.lags_ms.append(lag)
        return lag

    def _maybe_content_ready(self, action: ActionRecord, t: float | None) -> None:
        if action.content_ready_t is not None:
            return
        if not action.identity_ready:
            return
        if action.require_geometry and not (
            action.xlim_ready and action.ylim_ready and action.settle_ready
        ):
            return
        if action.require_cache and not action.cache_ready:
            return
        action.content_ready_t = time.perf_counter() if t is None else t

    def _owner_for_paint(self, target_identity: str | None, t_start: float) -> ActionRecord | None:
        candidates = [
            action
            for action in (*self.actions, *self.direct_call_actions)
            if action.t_input <= t_start
            and (target_identity is None or action.target_identity == target_identity)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda action: (action.t_input, action.seq))

    def paints_for(self, action: ActionRecord) -> list[PaintRecord]:
        return [paint for paint in self.paints if paint.action_seq == action.seq]


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    if hasattr(statistics, "quantiles"):
        # statistics.quantiles is n-tile; use nearest-rank on the sorted list.
        idx = min(len(ordered) - 1, max(0, int(round((q / 100.0) * (len(ordered) - 1)))))
        return float(ordered[idx])
    return float(ordered[-1])


def summarize_series(values: list[float] | None) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "raw": [float(v) for v in values],
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": float(max(values)),
        "n": len(values),
    }


def derive_action_contract(session: ActionSession, action: ActionRecord) -> dict[str, Any]:
    paints = session.paints_for(action)
    feedback = next((p for p in paints if p.target_identity == action.target_identity), None)
    stable = next((p for p in paints if p.after_content_ready), None)
    work = [p.work_ms for p in paints]
    intervals: list[float] = []
    if session.animation_active:
        anim = [p for p in paints if p.animation_active]
        for prev, cur in zip(anim, anim[1:]):
            intervals.append((cur.t_start - prev.t_end) * 1000.0)
    return {
        "seq": action.seq,
        "entry_kind": action.entry_kind,
        "target_identity": action.target_identity,
        "input_callback_ms": action.input_callback_ms,
        "feedback_paint_ms": None
        if feedback is None
        else (feedback.t_end - action.t_input) * 1000.0,
        "content_ready_ms": action.content_ready_ms,
        "stable_paint_ms": None
        if stable is None
        else (stable.t_end - action.t_input) * 1000.0,
        "paint_work_ms": work,
        "paint_interval_ms": intervals if session.animation_active else None,
        "identity_ready": action.identity_ready,
        "xlim_ready": action.xlim_ready,
        "ylim_ready": action.ylim_ready,
        "settle_ready": action.settle_ready,
        "cache_ready": action.cache_ready,
        "compute_submits": action.compute_submits,
        "error": action.error,
        "timed_out": action.timed_out,
        "paint_seqs": [p.seq for p in paints],
    }


def null_performance_fields(reason: str) -> dict[str, Any]:
    out = {name: None for name in TIMING_FIELDS}
    out["null_reason"] = reason
    if reason == REASON_NOT_APPLICABLE:
        out["paint_interval_reason"] = REASON_NOT_APPLICABLE
    return out


def publish_statistics(
    session: ActionSession,
    actions: list[ActionRecord],
    *,
    logic_only: bool,
    exposed: bool,
    has_real_paint: bool,
) -> dict[str, Any]:
    if logic_only:
        stats = null_performance_fields(REASON_LOGIC_ONLY)
        stats["paint_interval_reason"] = REASON_NOT_APPLICABLE
        return stats
    if not exposed:
        stats = null_performance_fields(REASON_NOT_EXPOSED)
        stats["paint_interval_reason"] = REASON_NOT_APPLICABLE
        return stats
    contracts = [derive_action_contract(session, action) for action in actions]
    if not has_real_paint:
        stats = {
            "input_callback_ms": summarize_series(
                [c["input_callback_ms"] for c in contracts if c["input_callback_ms"] is not None]
            ),
            "feedback_paint_ms": None,
            "content_ready_ms": summarize_series(
                [c["content_ready_ms"] for c in contracts if c["content_ready_ms"] is not None]
            ),
            "stable_paint_ms": None,
            "paint_work_ms": None,
            "paint_interval_ms": None,
            "event_loop_lag_ms": summarize_series(session.lags_ms),
            "null_reason": REASON_NO_PAINT,
            "paint_interval_reason": REASON_NOT_APPLICABLE,
        }
        return stats
    interval_values: list[float] = []
    if session.animation_active:
        for contract in contracts:
            interval_values.extend(contract["paint_interval_ms"] or [])
    stats = {
        "input_callback_ms": summarize_series(
            [c["input_callback_ms"] for c in contracts if c["input_callback_ms"] is not None]
        ),
        "feedback_paint_ms": summarize_series(
            [c["feedback_paint_ms"] for c in contracts if c["feedback_paint_ms"] is not None]
        ),
        "content_ready_ms": summarize_series(
            [c["content_ready_ms"] for c in contracts if c["content_ready_ms"] is not None]
        ),
        "stable_paint_ms": summarize_series(
            [c["stable_paint_ms"] for c in contracts if c["stable_paint_ms"] is not None]
        ),
        "paint_work_ms": summarize_series(
            [ms for c in contracts for ms in c["paint_work_ms"]]
        ),
        "paint_interval_ms": None
        if not session.animation_active
        else summarize_series(interval_values),
        "event_loop_lag_ms": summarize_series(session.lags_ms),
        "null_reason": None,
        "paint_interval_reason": None
        if session.animation_active
        else REASON_NOT_APPLICABLE,
    }
    for name in ("feedback_paint_ms", "content_ready_ms", "stable_paint_ms", "input_callback_ms"):
        if stats[name] is None:
            stats["null_reason"] = stats["null_reason"] or REASON_NO_ENDPOINT
    return stats


def scenario_status(
    *,
    logic_only: bool,
    exposed: bool,
    error: str | None,
    timed_out: bool,
    source_changed: bool,
    contract_ok: bool,
) -> dict[str, str]:
    if error or timed_out or source_changed:
        status = STATUS_UNVERIFIED
        reason = (
            REASON_EXCEPTION if error
            else REASON_TIMEOUT if timed_out
            else REASON_SOURCE_CHANGED
        )
        return {
            "status": status,
            "contract_status": STATUS_FAIL if error and not contract_ok else STATUS_UNVERIFIED,
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


def performance_status_is_pass(payload: Mapping[str, Any]) -> bool:
    if payload.get("performance_status") == STATUS_PASS:
        return True
    for scenario in payload.get("scenarios") or []:
        if scenario.get("performance_status") == STATUS_PASS:
            return True
        if (
            scenario.get("status") == STATUS_PASS
            and scenario.get("statistics", {}).get("null_reason") is None
            and any(scenario.get("statistics", {}).get(name) for name in TIMING_FIELDS)
        ):
            return True
    return False


def empty_report(*, logic_only: bool, error: str | None = None) -> dict[str, Any]:
    before = source_snapshot()
    return {
        "schema_version": SCHEMA_VERSION,
        "environment": environment_record(logic_only=logic_only),
        "source_snapshot_before": before,
        "source_snapshot_after": before,
        "scenarios": [],
        "errors": [] if error is None else [error],
    }


def build_report(
    *,
    environment: Mapping[str, Any],
    snapshot_before: Mapping[str, Any],
    snapshot_after: Mapping[str, Any],
    scenarios: list[Mapping[str, Any]],
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "environment": dict(environment),
        "source_snapshot_before": dict(snapshot_before),
        "source_snapshot_after": dict(snapshot_after),
        "scenarios": [dict(item) for item in scenarios],
        "errors": list(errors or []),
    }


# ---------------------------------------------------------------------------
# Heartbeat / timeout / teardown
# ---------------------------------------------------------------------------

class Heartbeat:
    def __init__(self, session: ActionSession, interval_ms: int = HEARTBEAT_INTERVAL_MS) -> None:
        self.session = session
        self.interval_ms = int(interval_ms)
        self._timer = None
        self._planned = None

    def start(self, parent=None) -> None:
        from PyQt5.QtCore import QTimer

        self._timer = QTimer(parent)
        self._timer.setInterval(self.interval_ms)
        self._timer.timeout.connect(self._on_tick)
        self._planned = time.perf_counter() + self.interval_ms / 1000.0
        self._timer.start()

    def _on_tick(self) -> None:
        now = time.perf_counter()
        planned = self._planned if self._planned is not None else now
        self.session.note_lag(planned, now)
        self._planned = now + self.interval_ms / 1000.0

    def stop(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is None:
            return
        try:
            timer.stop()
            timer.deleteLater()
        except Exception:
            pass


class TimeoutBudget:
    def __init__(
        self,
        *,
        action_s: float = ACTION_TIMEOUT_S,
        group_s: float = GROUP_TIMEOUT_S,
        init_s: float = INIT_TIMEOUT_S,
    ) -> None:
        self.action_s = action_s
        self.group_s = group_s
        self.init_s = init_s
        self.group_deadline = None
        self.action_deadline = None
        self.init_deadline = None

    def start_group(self) -> None:
        self.group_deadline = time.perf_counter() + self.group_s

    def start_action(self) -> None:
        self.action_deadline = time.perf_counter() + self.action_s

    def start_init(self) -> None:
        self.init_deadline = time.perf_counter() + self.init_s

    def expired(self, kind: str = "action") -> bool:
        now = time.perf_counter()
        if kind == "group" and self.group_deadline is not None:
            return now > self.group_deadline
        if kind == "init" and self.init_deadline is not None:
            return now > self.init_deadline
        if self.action_deadline is not None and now > self.action_deadline:
            return True
        if self.group_deadline is not None and now > self.group_deadline:
            return True
        return False


class MethodWraps:
    def __init__(self) -> None:
        self._restores: list[tuple[str, Any]] = []

    def wrap(self, obj: Any, name: str, wrapper: Callable[..., Any]) -> None:
        original = getattr(obj, name)
        setattr(obj, name, wrapper)
        self._restores.append(("attr", (obj, name, original)))

    def around(self, obj: Any, name: str, hook: Callable[..., Any]) -> None:
        original = getattr(obj, name)

        def wrapped(*args, **kwargs):
            return hook(original, *args, **kwargs)

        self.wrap(obj, name, wrapped)

    def reconnect_signal(self, signal, original_slot, wrapped_slot) -> None:
        try:
            signal.disconnect(original_slot)
        except TypeError:
            pass
        signal.connect(wrapped_slot)
        self._restores.append(("signal", (signal, wrapped_slot, original_slot)))

    def restore(self) -> None:
        while self._restores:
            kind, payload = self._restores.pop()
            try:
                if kind == "attr":
                    obj, name, original = payload
                    setattr(obj, name, original)
                else:
                    signal, wrapped_slot, original_slot = payload
                    try:
                        signal.disconnect(wrapped_slot)
                    except TypeError:
                        pass
                    signal.connect(original_slot)
            except Exception:
                pass


def _widget_alive(widget) -> bool:
    if widget is None:
        return False
    try:
        import sip

        return not sip.isdeleted(widget)
    except Exception:
        return True


def drain_deferred_deletes(app) -> None:
    from PyQt5.QtCore import QEvent
    from PyQt5.QtWidgets import QApplication

    if app is None:
        return
    app.processEvents()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def teardown_probe(
    *,
    app,
    window=None,
    filters=None,
    heartbeat=None,
    wraps=None,
    destroy_window: bool = True,
) -> None:
    if heartbeat is not None:
        heartbeat.stop()
    if wraps is not None:
        wraps.restore()
    for obj, filt in list(filters or []):
        try:
            if _widget_alive(obj):
                obj.removeEventFilter(filt)
        except Exception:
            pass
    if destroy_window and window is not None and _widget_alive(window):
        try:
            window.close()
        except Exception:
            pass
        try:
            window.deleteLater()
        except Exception:
            pass
    drain_deferred_deletes(app)


# ---------------------------------------------------------------------------
# Input helpers — wrap existing owners; do not edit MainWindow
# ---------------------------------------------------------------------------

def tab_click_point(tabbar, index: int):
    from PyQt5.QtCore import QPoint

    from mf4_analyzer.ui.view_tabbar import tab_close_hit_rect

    rect = tabbar.tabRect(index)
    if not rect.isValid():
        return None
    point = rect.center()
    close = tab_close_hit_rect(tabbar, index)
    if close.isValid() and close.contains(point):
        point = QPoint(rect.left() + (rect.width() * 3) // 4, rect.center().y())
        if close.contains(point):
            point = QPoint(rect.right() - 6, rect.center().y())
    if not rect.contains(point):
        return None
    return point


def click_view_tab(window, index: int) -> bool:
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    bar = getattr(window, "view_tabbar", None)
    tabs = bar.tabBar() if bar is not None else None
    if tabs is None:
        return False
    point = tab_click_point(tabs, index)
    if point is None:
        return False
    QTest.mouseClick(tabs, Qt.LeftButton, Qt.NoModifier, point)
    return True


def toolbar_mode_button(window, mode: str):
    toolbar = getattr(window, "toolbar", None)
    if toolbar is None:
        return None
    mapping = {
        "time": getattr(toolbar, "btn_mode_time", None),
        "fft": getattr(toolbar, "btn_mode_fft", None),
    }
    return mapping.get(mode)


def click_toolbar_mode(window, mode: str) -> bool:
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    button = toolbar_mode_button(window, mode)
    if button is None:
        return False
    QTest.mouseClick(button, Qt.LeftButton)
    toolbar = getattr(window, "toolbar", None)
    if toolbar is not None and toolbar.current_mode() != mode:
        button.click()
    return True


def click_fft_compute(window) -> bool:
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    ctx = getattr(getattr(window, "inspector", None), "fft_ctx", None)
    button = getattr(ctx, "btn_fft", None)
    if button is None:
        return False
    QTest.mouseClick(button, Qt.LeftButton)
    button.click()
    return True


def wrap_paint_method(widget, session: ActionSession, identity: str, wraps: MethodWraps) -> None:
    original = widget.paintEvent

    def painted(event):
        t0 = time.perf_counter()
        try:
            return original(event)
        finally:
            current = getattr(session, "_current_action", None)
            paint_identity = current.target_identity if current is not None else identity
            session.note_paint(paint_identity, t0, time.perf_counter())

    wraps.wrap(widget, "paintEvent", painted)


def curve_identity(canvas) -> list[str]:
    out = []
    lines = getattr(canvas, "_channel_lines", None)
    if lines is None:
        return out
    items = getattr(lines, "composite_items", None)
    if not callable(items):
        return out
    for ck, name, _pair in items():
        out.append(str(getattr(ck, "key", ck) if hasattr(ck, "key") else (ck, name)))
    return out


def visible_xy(canvas) -> dict[str, Any]:
    xlim = None
    ylims = None
    getter_x = getattr(canvas, "get_visible_xlim", None)
    getter_y = getattr(canvas, "get_visible_ylims", None)
    try:
        if callable(getter_x):
            xlim = list(getter_x())
    except Exception:
        xlim = None
    try:
        if callable(getter_y):
            ylims = getter_y()
            if ylims is not None:
                ylims = [list(item) for item in ylims]
    except Exception:
        ylims = None
    return {"xlim": xlim, "ylims": ylims, "curve_identity": curve_identity(canvas)}


def prime_fft_sources(window, fid: str, names: tuple[str, ...]) -> None:
    """Attach checked time channels to the active FFT view via existing APIs."""
    channels = [(fid, names[0])]
    navigator = getattr(window, "navigator", None)
    if navigator is not None:
        navigator.set_checked_channels(channels)
    mgr = getattr(window, "analysis_managers", {}).get("fft")
    if mgr is None:
        return
    state = mgr.get(mgr.active)
    state.attached_file_ids = [fid]
    if state.panes:
        state.panes[0].sources = list(channels)


def fft_cache_matches(window) -> bool:
    mgr = getattr(window, "analysis_managers", {}).get("fft")
    cache = getattr(window, "analysis_caches", {}).get("fft")
    if mgr is None or cache is None:
        return False
    try:
        state = mgr.get(mgr.active)
    except Exception:
        return False
    helper = getattr(window, "_fft_any_source_cached", None)
    if callable(helper):
        try:
            return bool(helper(state))
        except Exception:
            return False
    return False


# ---------------------------------------------------------------------------
# MainWindow switch session
# ---------------------------------------------------------------------------

def register_fixture(window, fixture_id: str) -> tuple[str, tuple[str, ...], dict[str, Any]]:
    spec = fixture_for_scenario(fixture_id if fixture_id == SCENARIO_M01_DENSE else SCENARIO_M01_SMALL)
    if fixture_id == SCENARIO_M02_EMPTY:
        return "", (), {"empty": True}
    df, names, summary = make_synthetic_frame(
        spec.n_ch, spec.n_points, spec.fs, dense=spec.dense
    )
    window._register_file_data(
        f"probe_motion_{fixture_id}.mf4",
        df,
        ["Time", *names],
        {name: "Nm" for name in names},
        fs=spec.fs,
    )
    fid = next(iter(window.files))
    window._on_source_load_finished([fid])
    return fid, names, summary


def prepare_two_time_views(
    app,
    window,
    fid: str,
    names: tuple[str, ...],
    *,
    plot_mode_a: str = "subplot",
    plot_mode_b: str = "subplot",
    hidden_in_a: bool = False,
) -> None:
    window.chart_stack.set_plot_mode(plot_mode_a)
    window.navigator.set_checked_channels([(fid, names[i]) for i in range(min(2, len(names)))])
    if hidden_in_a and len(names) > 1:
        window.navigator.set_hidden_channels([(fid, names[1])])
    else:
        window.navigator.set_hidden_channels([])
    window.plot_time()
    app.processEvents()
    window._capture_current_view()
    window._on_view_new()
    app.processEvents()
    if len(window.view_manager.views) > 1 and window.view_manager.active != 1:
        window.view_manager.set_active(1)
        app.processEvents()
    window.chart_stack.set_plot_mode(plot_mode_b)
    window.navigator.set_hidden_channels([])
    picks = [(fid, names[i]) for i in range(min(2, len(names)))]
    if len(names) >= 4:
        picks = [(fid, names[i]) for i in (2, 3)]
    window.navigator.set_checked_channels(picks)
    window.plot_time()
    app.processEvents()
    window._capture_current_view()


def pump_until(app, predicate: Callable[[], bool], timeout_s: float) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if predicate():
            return True
        app.processEvents()
    return False


def attach_switch_observers(window, session: ActionSession, wraps: MethodWraps) -> None:
    current: dict[str, ActionRecord | None] = {"action": None}

    def bind(action: ActionRecord) -> None:
        current["action"] = action
        session._current_action = action

    session._bind_current = bind  # type: ignore[attr-defined]
    session._current_action = None
    session.mode_changed_calls = []

    def on_switch(original, idx, *args, **kwargs):
        action = current["action"]
        try:
            result = original(idx, *args, **kwargs)
            if action is not None:
                views = getattr(window.view_manager, "views", [])
                if 0 <= idx < len(views):
                    session.note_identity(action, f"view:{views[idx].view_id}")
                session.finish_callback(action)
            return result
        except Exception as exc:
            session.note_error(action, exc)
            raise

    def on_mode(original, mode, *args, **kwargs):
        action = current["action"]
        session.mode_changed_calls.append(mode)
        try:
            result = original(mode, *args, **kwargs)
            if action is not None:
                session.note_identity(action, f"mode:{mode}")
                if action.entry_kind in {ENTRY_TOOLBAR_BUTTON, ENTRY_DIRECT_CALL}:
                    session.finish_callback(action)
            return result
        except Exception as exc:
            session.note_error(action, exc)
            raise

    def mark(flag: str):
        def hook(original, *args, **kwargs):
            result = original(*args, **kwargs)
            action = current["action"]
            if action is not None:
                getattr(session, flag)(action)
            return result
        return hook

    original_switch = window._switch_view

    def wrapped_switch(idx, *args, **kwargs):
        return on_switch(original_switch, idx, *args, **kwargs)

    window._switch_view = wrapped_switch
    wraps._restores.append(("attr", (window, "_switch_view", original_switch)))
    tabbar = getattr(window, "view_tabbar", None)
    if tabbar is not None:
        wraps.reconnect_signal(tabbar.switch_requested, original_switch, wrapped_switch)

    original_on_mode = window._on_mode_changed

    def wrapped_on_mode(mode, *args, **kwargs):
        return on_mode(original_on_mode, mode, *args, **kwargs)

    window._on_mode_changed = wrapped_on_mode
    wraps._restores.append(("attr", (window, "_on_mode_changed", original_on_mode)))
    toolbar = getattr(window, "toolbar", None)
    if toolbar is not None:
        wraps.reconnect_signal(toolbar.mode_changed, original_on_mode, wrapped_on_mode)
        wraps.around(toolbar, "_set_mode", lambda original, mode, *a, **k: original(mode, *a, **k))
    canvas = getattr(window, "canvas_time", None)
    if canvas is not None:
        wraps.around(canvas, "restore_visible_xlim", mark("note_xlim"))
        wraps.around(canvas, "restore_visible_ylims", mark("note_ylim"))
        wraps.around(canvas, "settle_view_restore", mark("note_settle"))
        glw = getattr(canvas, "_glw", None)
        if glw is not None:
            wrap_paint_method(glw, session, "canvas:time", wraps)
    bar = getattr(window, "view_tabbar", None)
    if bar is not None:
        wrap_paint_method(bar, session, "chrome:view_tabbar", wraps)
        tabs = bar.tabBar()
        wrap_paint_method(tabs, session, "chrome:view_tabbar", wraps)
    fft_page = getattr(getattr(window, "chart_stack", None), "page_fft", None)
    if fft_page is not None and hasattr(fft_page, "pane_canvas"):
        try:
            fft_canvas = fft_page.pane_canvas(0)
        except Exception:
            fft_canvas = None
        if fft_canvas is not None:
            wrap_paint_method(fft_canvas, session, "canvas:fft", wraps)
    compute = getattr(window, "_fft_compute_arrays", None)
    if callable(compute):
        def on_compute(original, *args, **kwargs):
            session.note_compute_submit(current["action"])
            return original(*args, **kwargs)

        wraps.around(window, "_fft_compute_arrays", on_compute)
    if callable(getattr(window, "_offer_analysis_time_range_before_compute", None)):
        wraps.around(
            window,
            "_offer_analysis_time_range_before_compute",
            lambda _original, *_a, **_k: True,
        )
    if callable(getattr(window, "_check_uniform_or_prompt", None)):
        wraps.around(
            window,
            "_check_uniform_or_prompt",
            lambda _original, *_a, **_k: True,
        )
    original_do = getattr(window, "do_fft", None)
    if callable(original_do):
        wraps.around(window, "do_fft", lambda original, *a, **k: original(*a, **k))
        inspector = getattr(window, "inspector", None)
        signal = getattr(inspector, "fft_requested", None)
        if signal is not None:
            wraps.reconnect_signal(signal, original_do, window.do_fft)
    enter = getattr(window, "_enter_fft_mode", None)
    if callable(enter):
        def on_enter(original, *args, **kwargs):
            result = original(*args, **kwargs)
            action = current["action"]
            if action is not None and action.target_identity.startswith("mode:"):
                session.note_identity(action, action.target_identity)
                if action.require_cache:
                    session.note_cache(action, fft_cache_matches(window))
                else:
                    session.note_cache(action, True)
                    action.xlim_ready = True
                    action.ylim_ready = True
                    action.settle_ready = True
                    session._maybe_content_ready(action, None)
            return result

        wraps.around(window, "_enter_fft_mode", on_enter)


def run_one_view_switch(
    app,
    window,
    session: ActionSession,
    *,
    target_index: int,
    budget: TimeoutBudget,
    entry_kind: str = ENTRY_TAB_CLICK,
) -> ActionRecord:
    view = window.view_manager.get(target_index)
    identity = f"view:{view.view_id}"
    budget.start_action()
    action = session.begin(
        entry_kind,
        identity,
        require_geometry=True,
        require_cache=False,
    )
    session._bind_current(action)
    try:
        if entry_kind == ENTRY_DIRECT_CALL:
            window._switch_view(target_index)
        else:
            if not click_view_tab(window, target_index):
                raise ProbeError(f"tab click failed for index {target_index}")
        pump_until(app, lambda: action.content_ready_t is not None, min(2.0, ACTION_TIMEOUT_S))
        if budget.expired("action"):
            session.note_timeout(action)
    except Exception as exc:
        session.note_error(action, exc)
        if action.t_callback_return is None:
            session.finish_callback(action)
    return action


def run_one_mode_switch(
    app,
    window,
    session: ActionSession,
    *,
    mode: str,
    budget: TimeoutBudget,
    entry_kind: str,
    require_cache: bool,
) -> ActionRecord:
    identity = f"mode:{mode}"
    budget.start_action()
    action = session.begin(
        entry_kind,
        identity,
        require_geometry=False,
        require_cache=require_cache,
    )
    session._bind_current(action)
    try:
        if entry_kind == ENTRY_DIRECT_CALL:
            window._on_mode_changed(mode)
        else:
            if not click_toolbar_mode(window, mode):
                raise ProbeError(f"toolbar mode click failed for {mode}")
        pump_until(
            app,
            lambda: action.identity_ready and (not require_cache or action.cache_ready or action.content_ready_t is not None),
            min(2.0, ACTION_TIMEOUT_S),
        )
        if mode == "time":
            action.xlim_ready = True
            action.ylim_ready = True
            action.settle_ready = True
            if window.chart_stack.current_mode() == "time":
                session.note_identity(action, identity)
            session._maybe_content_ready(action, None)
        if budget.expired("action"):
            session.note_timeout(action)
    except Exception as exc:
        session.note_error(action, exc)
        if action.t_callback_return is None:
            session.finish_callback(action)
    return action


def _scenario_payload(
    scenario_id: str,
    session: ActionSession,
    *,
    config: Mapping[str, Any],
    entry_kind: str,
    phase: str,
    logic_only: bool,
    exposed: bool,
    source_changed: bool,
    init_ms: float | None,
    final_state: Mapping[str, Any],
    group_timeout: bool = False,
) -> dict[str, Any]:
    actions = list(session.actions)
    error = next((action.error for action in actions if action.error), None)
    timed_out = group_timeout or any(action.timed_out for action in actions)
    contracts = [derive_action_contract(session, action) for action in actions]
    contract_ok = all(
        action.error is None and not action.timed_out for action in actions
    ) and (not actions or any(item["identity_ready"] for item in contracts) or logic_only)
    has_real_paint = any(session.paints) and exposed and not logic_only
    statuses = scenario_status(
        logic_only=logic_only,
        exposed=exposed,
        error=error,
        timed_out=timed_out,
        source_changed=source_changed,
        contract_ok=contract_ok and not source_changed,
    )
    return {
        "id": scenario_id,
        "config": dict(config),
        "entry_kind": entry_kind,
        "phase": phase,
        "events": contracts,
        "direct_call_events": [
            derive_action_contract(session, action) for action in session.direct_call_actions
        ],
        "paints": [
            {
                "seq": paint.seq,
                "action_seq": paint.action_seq,
                "target_identity": paint.target_identity,
                "work_ms": paint.work_ms,
                "after_content_ready": paint.after_content_ready,
            }
            for paint in session.paints
        ],
        "statistics": publish_statistics(
            session,
            actions,
            logic_only=logic_only,
            exposed=exposed,
            has_real_paint=has_real_paint,
        ),
        "final_state": dict(final_state),
        "init_ms": None if logic_only else init_ms,
        "compute_submits": session.compute_submits,
        **statuses,
    }


def run_switch_scenario(
    app,
    window,
    scenario_id: str,
    *,
    logic_only: bool,
    exposed: bool,
    warmup: int,
    samples: int,
    include_direct_call: bool = True,
) -> dict[str, Any]:
    session = ActionSession()
    wraps = MethodWraps()
    heartbeat = Heartbeat(session)
    budget = TimeoutBudget()
    snapshot_mid = source_snapshot()
    config: dict[str, Any] = {"scenario": scenario_id}
    init_ms = None
    error = None
    try:
        heartbeat.start(window)
        attach_switch_observers(window, session, wraps)
        budget.start_group()
        if scenario_id in {SCENARIO_M01_SMALL, SCENARIO_M01_DENSE}:
            budget.start_init()
            t0 = time.perf_counter()
            fid, names, summary = register_fixture(window, scenario_id)
            modes = [("subplot", "subplot")]
            if scenario_id == SCENARIO_M01_DENSE:
                modes.append(("subplot", "overlay"))
            prepare_two_time_views(app, window, fid, names, plot_mode_a=modes[0][0], plot_mode_b=modes[0][1])
            init_ms = (time.perf_counter() - t0) * 1000.0
            config.update({"fixture": summary, "layouts": modes})
            if budget.expired("init"):
                session.note_timeout(None)
            targets = [1, 0]
            for _ in range(warmup):
                for idx in targets:
                    warmed = run_one_view_switch(
                        app, window, session, target_index=idx, budget=budget
                    )
                    session.discard(warmed)
            for i in range(samples):
                if budget.expired("group"):
                    session.note_timeout(session.actions[-1] if session.actions else None)
                    break
                run_one_view_switch(app, window, session, target_index=targets[i % 2], budget=budget)
            if include_direct_call:
                run_one_view_switch(
                    app, window, session, target_index=targets[0],
                    budget=budget, entry_kind=ENTRY_DIRECT_CALL,
                )
            canvas = window.canvas_time
            final_state = {
                "active_view": window.view_manager.active,
                "view_ids": [v.view_id for v in window.view_manager.views],
                **visible_xy(canvas),
                "hidden_channels": list(window.navigator.get_hidden_channels() or []),
                "plot_mode": window.chart_stack.plot_mode(),
            }
            entry_kind = ENTRY_TAB_CLICK
        elif scenario_id == SCENARIO_M02_EMPTY:
            config["empty"] = True
            for _ in range(warmup):
                session.discard(run_one_mode_switch(
                    app, window, session, mode="fft", budget=budget,
                    entry_kind=ENTRY_TOOLBAR_BUTTON, require_cache=False,
                ))
                session.discard(run_one_mode_switch(
                    app, window, session, mode="time", budget=budget,
                    entry_kind=ENTRY_TOOLBAR_BUTTON, require_cache=False,
                ))
            for i in range(samples):
                if budget.expired("group"):
                    break
                mode = "fft" if i % 2 == 0 else "time"
                run_one_mode_switch(
                    app, window, session, mode=mode, budget=budget,
                    entry_kind=ENTRY_TOOLBAR_BUTTON, require_cache=False,
                )
            if include_direct_call:
                run_one_mode_switch(
                    app, window, session, mode="fft", budget=budget,
                    entry_kind=ENTRY_DIRECT_CALL, require_cache=False,
                )
            final_state = {
                "mode": window.chart_stack.current_mode(),
                "files": len(getattr(window, "files", {})),
            }
            entry_kind = ENTRY_TOOLBAR_BUTTON
        else:
            budget.start_init()
            t0 = time.perf_counter()
            fid, names, summary = register_fixture(window, SCENARIO_M01_SMALL)
            window.navigator.set_checked_channels([(fid, names[0])])
            window.plot_time()
            app.processEvents()
            prime_fft_sources(window, fid, names)
            click_toolbar_mode(window, "fft")
            pump_until(app, lambda: window.chart_stack.current_mode() == "fft", 2.0)
            session.compute_submits = 0
            click_fft_compute(window)
            pump_until(app, lambda: fft_cache_matches(window), min(INIT_TIMEOUT_S, 10.0))
            init_ms = (time.perf_counter() - t0) * 1000.0
            config.update({"fixture": summary, "cached": True})
            if budget.expired("init"):
                session.note_timeout(None)
            session.compute_submits = 0
            click_toolbar_mode(window, "time")
            pump_until(app, lambda: window.chart_stack.current_mode() == "time", 2.0)
            for _ in range(warmup):
                for mode in ("fft", "time"):
                    session.discard(run_one_mode_switch(
                        app, window, session, mode=mode, budget=budget,
                        entry_kind=ENTRY_TOOLBAR_BUTTON, require_cache=True,
                    ))
            sampling_submits_at_start = session.compute_submits
            for i in range(samples):
                if budget.expired("group"):
                    break
                mode = "fft" if i % 2 == 0 else "time"
                run_one_mode_switch(
                    app, window, session, mode=mode, budget=budget,
                    entry_kind=ENTRY_TOOLBAR_BUTTON, require_cache=True,
                )
            config["sampling_compute_submits"] = session.compute_submits - sampling_submits_at_start
            if include_direct_call:
                run_one_mode_switch(
                    app, window, session, mode="fft", budget=budget,
                    entry_kind=ENTRY_DIRECT_CALL, require_cache=True,
                )
            final_state = {
                "mode": window.chart_stack.current_mode(),
                "cache_matches": fft_cache_matches(window),
                "sampling_compute_submits": config["sampling_compute_submits"],
            }
            entry_kind = ENTRY_TOOLBAR_BUTTON
        group_timeout = budget.expired("group")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        final_state = {"error": error, "traceback": traceback.format_exc()}
        entry_kind = ENTRY_TAB_CLICK if scenario_id.startswith("M01") else ENTRY_TOOLBAR_BUTTON
        group_timeout = False
        session.note_error(None, exc)
    finally:
        teardown_probe(app=app, window=None, heartbeat=heartbeat, wraps=wraps)

    source_changed = not snapshots_match(snapshot_mid, source_snapshot())
    payload = _scenario_payload(
        scenario_id,
        session,
        config=config,
        entry_kind=entry_kind,
        phase="warm",
        logic_only=logic_only,
        exposed=exposed,
        source_changed=source_changed,
        init_ms=init_ms,
        final_state=final_state,
        group_timeout=group_timeout,
    )
    if error:
        payload["errors_local"] = [error]
        payload["status"] = STATUS_UNVERIFIED
        payload["performance_status"] = STATUS_UNVERIFIED
        payload["reason"] = REASON_EXCEPTION
    return payload


def create_isolated_mainwindow(settings_dir: Path):
    token = isolate_qsettings(settings_dir)
    prove_qsettings_isolated(token)
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    ask = getattr(window, "_ask_use_local_time_range", None)
    if callable(ask):
        window._ask_use_local_time_range = lambda *_a, **_k: "full"
    return window, token


# ---------------------------------------------------------------------------
# Samples (ABBA, independent instances; performance ≠ recording)
# ---------------------------------------------------------------------------

def abba_sequence(modes: tuple[str, str] = ABBA_MODES) -> tuple[str, ...]:
    a, b = modes
    return (a, b, b, a)


def try_import_motion_demo():
    try:
        from mf4_analyzer.ui import motion_demo
    except ImportError:
        return None
    return motion_demo


def run_sample_abba(
    *,
    logic_only: bool,
    host_factory: Callable[[str], Any] | None = None,
    teardown_host: Callable[[Any], None] | None = None,
) -> list[dict[str, Any]]:
    scenarios = []
    demo = None if host_factory is not None else try_import_motion_demo()
    if host_factory is None and demo is None:
        for mode in abba_sequence():
            session = ActionSession()
            statuses = scenario_status(
                logic_only=logic_only,
                exposed=False,
                error=None,
                timed_out=False,
                source_changed=False,
                contract_ok=True,
            )
            scenarios.append({
                "id": "samples",
                "config": {"mode": mode, "sample_ids": list(SAMPLE_IDS)},
                "entry_kind": "sample_host",
                "phase": "abba",
                "events": [],
                "direct_call_events": [],
                "paints": [],
                "statistics": null_performance_fields(
                    REASON_LOGIC_ONLY if logic_only else "motion_demo_unavailable"
                ),
                "final_state": {"host": "unavailable"},
                **statuses,
                "status": STATUS_UNVERIFIED,
                "performance_status": STATUS_UNVERIFIED,
                "reason": "motion_demo_unavailable",
            })
        return scenarios

    factory = host_factory or (lambda mode: _construct_demo_host(demo, mode))
    closer = teardown_host or _default_teardown_host
    seen_ids = []
    for mode in abba_sequence():
        try:
            host = factory(mode)
        except Exception as exc:
            scenarios.append({
                "id": "samples",
                "config": {"mode": mode},
                "entry_kind": "sample_host",
                "phase": "abba",
                "events": [],
                "direct_call_events": [],
                "paints": [],
                "statistics": null_performance_fields(
                    REASON_LOGIC_ONLY if logic_only else "host_construct_failed"
                ),
                "final_state": {"error": str(exc)},
                "status": STATUS_UNVERIFIED,
                "contract_status": STATUS_UNVERIFIED,
                "performance_status": STATUS_UNVERIFIED,
                "reason": "host_construct_failed",
            })
            continue
        seen_ids.append(id(host))
        session = ActionSession()
        try:
            for sample_id in SAMPLE_IDS:
                action = session.begin("sample_action", f"sample:{sample_id}", require_geometry=False)
                session.note_identity(action, f"sample:{sample_id}")
                action.xlim_ready = action.ylim_ready = action.settle_ready = True
                session._maybe_content_ready(action, None)
                session.finish_callback(action)
                runner = getattr(host, "run_sample", None)
                if callable(runner):
                    runner(sample_id)
        except Exception as exc:
            session.note_error(session.actions[-1] if session.actions else None, exc)
        finally:
            closer(host)
        statuses = scenario_status(
            logic_only=logic_only,
            exposed=False if logic_only else True,
            error=next((a.error for a in session.actions if a.error), None),
            timed_out=False,
            source_changed=False,
            contract_ok=all(a.error is None for a in session.actions),
        )
        scenarios.append({
            "id": "samples",
            "config": {"mode": mode, "host_id": seen_ids[-1]},
            "entry_kind": "sample_host",
            "phase": "abba",
            "events": [derive_action_contract(session, action) for action in session.actions],
            "direct_call_events": [],
            "paints": [],
            "statistics": publish_statistics(
                session, session.actions,
                logic_only=logic_only, exposed=not logic_only, has_real_paint=False,
            ),
            "final_state": {"mode": mode},
            **statuses,
        })
    if len(set(seen_ids)) != len(seen_ids):
        scenarios[-1]["status"] = STATUS_UNVERIFIED
        scenarios[-1]["errors_local"] = ["abba_reused_instance"]
    return scenarios


def _construct_demo_host(demo, mode: str):
    for name in ("create_demo_window", "build_demo", "make_host"):
        factory = getattr(demo, name, None)
        if callable(factory):
            return factory(mode)
    cls = getattr(demo, "MotionDemoWindow", None)
    if cls is None:
        raise ProbeError("motion_demo has no constructible host factory")
    host = cls()
    policies = {
        "current": getattr(demo, "POLICY_OFF", None),
        "light": getattr(demo, "POLICY_LIGHT", None),
        "reduced": getattr(demo, "POLICY_REDUCED", None),
    }
    setter = getattr(host, "set_motion_policy", None)
    policy = policies.get(mode)
    if callable(setter) and policy is not None:
        setter(policy)
    return host


def _default_teardown_host(host) -> None:
    close = getattr(host, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    delete = getattr(host, "deleteLater", None)
    if callable(delete):
        try:
            delete()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_output(args, default_name: str) -> Path:
    if getattr(args, "output", None):
        return Path(args.output)
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / default_name


def _settings_scratch(prefix: str, output_dir: str | None = None) -> Path:
    root = Path(output_dir or os.environ.get("TMPDIR") or tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def cmd_samples(args) -> dict[str, Any]:
    logic_only = bool(args.logic_only)
    app = _qapp()
    require_platform(logic_only=logic_only, app=app)
    settings_dir = _settings_scratch("probe-motion-samples-", args.output_dir)
    token = isolate_qsettings(settings_dir)
    prove_qsettings_isolated(token)
    snapshot_before = source_snapshot()
    errors: list[str] = []
    try:
        scenarios = run_sample_abba(logic_only=logic_only)
        if args.record_screen:
            # Recording is a separate pass and never mixed into paint/callback stats.
            rec_path = _resolve_output(args, "samples-recording.json")
            _write_json(rec_path, {
                "schema_version": SCHEMA_VERSION,
                "kind": "screen_recording",
                "status": STATUS_UNVERIFIED,
                "reason": "recording_separated_not_collected_in_t5_logic",
            })
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        scenarios = []
    snapshot_after = source_snapshot()
    if not snapshots_match(snapshot_before, snapshot_after):
        errors.append(REASON_SOURCE_CHANGED)
        for scenario in scenarios:
            scenario["status"] = STATUS_UNVERIFIED
            scenario["performance_status"] = STATUS_UNVERIFIED
    env = environment_record(app, logic_only=logic_only, extra={"command": "samples"})
    report = build_report(
        environment=env,
        snapshot_before=snapshot_before,
        snapshot_after=snapshot_after,
        scenarios=scenarios,
        errors=errors,
    )
    if logic_only and performance_status_is_pass(report):
        report["errors"].append("logic_only_emitted_performance_pass")
        report.setdefault("performance_status", STATUS_UNVERIFIED)
        for scenario in report["scenarios"]:
            scenario["performance_status"] = STATUS_UNVERIFIED
            if scenario.get("status") == STATUS_PASS:
                scenario["status"] = STATUS_UNVERIFIED
    _write_json(_resolve_output(args, "samples.json"), report)
    token.restore()
    return report


def cmd_switches(args) -> dict[str, Any]:
    logic_only = bool(args.logic_only)
    app = _qapp()
    require_platform(logic_only=logic_only, app=app)
    settings_dir = _settings_scratch("probe-motion-switches-", args.output_dir)
    snapshot_before = source_snapshot()
    errors: list[str] = []
    scenarios: list[dict[str, Any]] = []
    window = None
    token = None
    try:
        window, token = create_isolated_mainwindow(settings_dir)
        window.resize(1450, 850)
        window.show()
        window.raise_()
        window.activateWindow()
        exposed = wait_window_exposed(app, window) if not logic_only else window_is_exposed(window)
        env = environment_record(
            app, logic_only=logic_only,
            extra={"command": "switches", "exposed": exposed},
        )
        selected = list(args.scenario or ALL_SWITCH_SCENARIOS)
        if logic_only:
            selected = [item for item in selected if item != SCENARIO_M01_DENSE] or [SCENARIO_M02_EMPTY]
        warmup = int(args.warmup)
        samples = int(args.samples)
        if getattr(args, "cold_one", False):
            selected = selected[:1]
            warmup = 0
            samples = 1
        for scenario_id in selected:
            scenarios.append(
                run_switch_scenario(
                    app, window, scenario_id,
                    logic_only=logic_only,
                    exposed=exposed,
                    warmup=warmup,
                    samples=samples,
                )
            )
        if args.record_screen:
            rec_path = _resolve_output(args, "switches-recording.json")
            _write_json(rec_path, {
                "schema_version": SCHEMA_VERSION,
                "kind": "screen_recording",
                "status": STATUS_UNVERIFIED,
                "reason": "recording_separated_not_collected_in_t5_logic",
            })
        if (
            not logic_only
            and not getattr(args, "skip_cold", False)
            and not getattr(args, "cold_one", False)
        ):
            scenarios.extend(_run_cold_processes(args, selected))
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        env = environment_record(app, logic_only=logic_only, extra={"command": "switches"})
    finally:
        teardown_probe(app=app, window=window)
        if token is not None:
            token.restore()
    snapshot_after = source_snapshot()
    if not snapshots_match(snapshot_before, snapshot_after):
        errors.append(REASON_SOURCE_CHANGED)
        for scenario in scenarios:
            scenario["status"] = STATUS_UNVERIFIED
            scenario["performance_status"] = STATUS_UNVERIFIED
    report = build_report(
        environment=env,
        snapshot_before=snapshot_before,
        snapshot_after=snapshot_after,
        scenarios=scenarios,
        errors=errors,
    )
    if logic_only and performance_status_is_pass(report):
        report["errors"].append("logic_only_emitted_performance_pass")
        for scenario in report["scenarios"]:
            scenario["performance_status"] = STATUS_UNVERIFIED
            if scenario.get("status") == STATUS_PASS:
                scenario["status"] = STATUS_UNVERIFIED
    _write_json(_resolve_output(args, "switches.json"), report)
    return report


def _run_cold_processes(args, scenario_ids: list[str]) -> list[dict[str, Any]]:
    results = []
    out_dir = Path(args.output_dir) / "cold"
    out_dir.mkdir(parents=True, exist_ok=True)
    for scenario_id in scenario_ids:
        raws = []
        for idx in range(COLD_PROCESS_COUNT):
            dest = out_dir / f"{scenario_id}-cold-{idx}.json"
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "switches",
                "--output", str(dest),
                "--output-dir", str(out_dir),
                "--scenario", scenario_id,
                "--cold-one",
                "--warmup", "0",
                "--samples", "1",
                "--skip-cold",
            ]
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(REPO_ROOT),
                    timeout=ACTION_TIMEOUT_S + INIT_TIMEOUT_S + 15,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if dest.is_file():
                    raws.append(json.loads(dest.read_text(encoding="utf-8")))
                elif completed.returncode != 0:
                    raws.append({
                        "status": STATUS_UNVERIFIED,
                        "error": completed.stderr[-400:],
                    })
            except Exception as exc:
                raws.append({"status": STATUS_UNVERIFIED, "error": str(exc)})
        values = []
        for raw in raws:
            for scenario in raw.get("scenarios") or []:
                events = scenario.get("events") or []
                if events and events[0].get("input_callback_ms") is not None:
                    values.append(events[0]["input_callback_ms"])
        results.append({
            "id": f"{scenario_id}-cold",
            "config": {"processes": COLD_PROCESS_COUNT, "scenario": scenario_id},
            "entry_kind": "cold_process",
            "phase": "cold",
            "events": raws,
            "direct_call_events": [],
            "paints": [],
            "statistics": {
                **null_performance_fields(REASON_NO_ENDPOINT if len(values) < 5 else None or REASON_NO_ENDPOINT),
                "cold_raw_input_callback_ms": values,
                "cold_range": [min(values), max(values)] if values else None,
            },
            "final_state": {"n_raw": len(raws)},
            "status": STATUS_UNVERIFIED,
            "contract_status": STATUS_UNVERIFIED,
            "performance_status": STATUS_UNVERIFIED,
            "reason": "cold_n5_not_p95",
        })
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("samples", "switches"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--output-dir", default=".state/native-interaction-motion")
        cmd.add_argument("--output", default=None)
        cmd.add_argument("--logic-only", action="store_true")
        cmd.add_argument("--record-screen", action="store_true")
        cmd.add_argument("--warmup", type=int, default=WARMUP_COUNT)
        cmd.add_argument("--samples", type=int, default=WARM_SAMPLE_COUNT)
        cmd.add_argument("--scenario", action="append", default=[])
        cmd.add_argument("--skip-cold", action="store_true")
        cmd.add_argument("--cold-one", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "samples":
            report = cmd_samples(args)
        else:
            report = cmd_switches(args)
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
