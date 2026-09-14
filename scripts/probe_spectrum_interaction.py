#!/usr/bin/env python3
"""Spectrum / time-domain pan interaction probe (plan T0).

Two modes that MUST NOT be mixed:

* ``perf`` (default): GUI-event cadence timing. No cProfile and no hot-path
  clocks. Counting wrappers are allowed; they only increment integers.
* ``profile``: cProfile attribution only. Dumps go to a separate directory
  and must never be folded into perf p50/p95.

Comparable Cocoa numbers require a native window. Do not set
``QT_QPA_PLATFORM=offscreen`` for that baseline. If the window cannot be
exposed, the process re-execs offscreen and records comparable_cocoa=false.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import os
import pstats
import platform
import resource
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("TMPDIR", "/tmp")
os.environ.setdefault("MPLCONFIGDIR", "/tmp")

FINGERPRINT_FILES = (
    "mf4_analyzer/ui/pg_canvas/line_canvas.py",
    "mf4_analyzer/signal/display_ranges.py",
    "mf4_analyzer/ui/pg_canvas/canvas.py",
    "mf4_analyzer/ui/pg_canvas/heatmap_canvas.py",
)
# T0 fingerprint-before did not include this file (it did not exist yet).
FINGERPRINT_EXTRA_FILES = (
    "mf4_analyzer/ui/pg_canvas/spectrum_display.py",
)
SOURCE_N = 594_001
N_CURVES = 2
XLIM = (-11000.0, 21000.0)
NARROW_XLIM = (0.0, 200.0)
Y_MANUAL = (-120.0, 80.0)
WIDGET_SIZE = (1200, 800)
COLORS = ("#2563eb", "#00aa77")
DATA_X_MAX_HZ = 12000.0
PAINT_FLOOR_MS = 0.5
SETTLE_MS = 250.0
FRAME_16_7_MS = 16.7
FRAME_8_3_MS = 8.3
PEAK_HZ = 80.0
VALLEY_HZ = 50.0
NAN_HZ = 100.0
PEAK_AMP = 80.0
VALLEY_AMP = -300.0
SCHEMA_VERSION = 2
COUNTING_DEFINITIONS = {
    "setData_count": (
        "PlotDataItem.setData calls on tracked spectrum amp curves "
        "(FFT) or visible time-domain channel curves during the timed "
        "event window."
    ),
    "full_array_scan_count": (
        "Calls into visible_line_values and/or PgLineCanvas._spectrum_plot_arrays "
        "whose first array argument has size == source_n (594001). After T1 the "
        "auto-Y path uses PreparedLineRange.query instead of visible_line_values; "
        "after T3 a coverage HIT skips _spectrum_plot_arrays entirely. Length "
        "check only, not a proof that every element was read."
    ),
    "peak_trace_count": "build_peak_trace calls during the timed event window.",
    "y_fit_count": (
        "_fit_active_spectrum_y calls during the timed event window. "
        "_auto_amplitude_y_range is reported separately because plot/setup "
        "and Y-fit both use it."
    ),
    "y_fit_in_callback": (
        "_fit_active_spectrum_y calls while the probe is inside sendEvent / "
        "ViewBox.mouseDragEvent (the mouse/range callback stack)."
    ),
    "y_fit_in_timer": (
        "_fit_active_spectrum_y calls while PgLineCanvas._spectrum_refresh_timer "
        "is delivering timeout (16 ms single-shot)."
    ),
    "cache_hit_count": (
        "plan_spectrum_display results with reuse=True during the timed window. "
        "Integer-only; no hot-path clock."
    ),
    "cache_rebuild_count": (
        "plan_spectrum_display results with reuse=False during the timed window."
    ),
    "prepared_query_count": "PreparedLineRange.query calls during the timed window.",
    "prepared_query_full_bounds": (
        "PreparedLineRange.query results that reused cached full-valid Y bounds."
    ),
    "prepared_query_in_callback": (
        "PreparedLineRange.query calls while inside the mouse/range callback stack."
    ),
}


def _arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="TraceLab spectrum pan probe (perf vs profile, never mixed).",
    )
    parser.add_argument("--mode", choices=("perf", "profile"), default="perf")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Smoke: 1 round x 20 events, 60 Hz, GUI events only.",
    )
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="Force offscreen. Marks comparable_cocoa=false.",
    )
    parser.add_argument(
        "--offscreen-fallback",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--input-mode",
        choices=("gui", "direct_viewbox", "both"),
        default="both",
        help="gui = QMouse/QWheel via the event loop; direct_viewbox is localization only.",
    )
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--events", type=int, default=120)
    parser.add_argument("--width", type=int, default=WIDGET_SIZE[0])
    parser.add_argument("--height", type=int, default=WIDGET_SIZE[1])
    parser.add_argument(
        "--mainwindow",
        action="store_true",
        help="Also run a QSettings-isolated MainWindow product-path probe.",
    )
    parser.add_argument(
        "--skip-extra",
        action="store_true",
        help="Skip T4 extra scenarios (narrow/overscan/correctness/contrast).",
    )
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help=(
            "Only T0 comparable rows (fft auto/manual + time-domain). "
            "Implies --skip-extra. MainWindow still requires --mainwindow."
        ),
    )
    parser.add_argument(
        "--fingerprint-out",
        type=Path,
        help="Optional extra fingerprint JSON path.",
    )
    args = parser.parse_args(argv)
    if args.compare_only:
        args.skip_extra = True
    return args


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _git_status() -> list[str]:
    try:
        text = subprocess.check_output(
            ["git", "status", "--short"], cwd=REPO_ROOT, text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in text.splitlines() if line.strip()]


def _fingerprint_entry(rel: str) -> dict | None:
    path = REPO_ROOT / rel
    if not path.is_file():
        return None
    stat = path.stat()
    return {
        "sha256": _sha256(path),
        "nbytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def build_fingerprint() -> dict:
    files = {}
    for rel in FINGERPRINT_FILES:
        entry = _fingerprint_entry(rel)
        if entry is not None:
            files[rel] = entry
    extra = {}
    for rel in FINGERPRINT_EXTRA_FILES:
        entry = _fingerprint_entry(rel)
        if entry is not None:
            extra[rel] = entry
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "head": _git_head(),
        "dirty_scope": _git_status(),
        "relevant_files": files,
        "extra_files": extra,
    }


def rss_bytes() -> int | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError:
        return None
    value = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return value
    return value * 1024


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    try:
        import numpy as np
        if isinstance(value, (np.floating, np.integer)):
            return float(value) if isinstance(value, np.floating) else int(value)
    except Exception:
        pass
    raise TypeError(f"unserializable {type(value)!r}")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _stats(values, *, extra_thresholds=()):
    import numpy as np

    data = [float(v) for v in values]
    n = len(data)
    result = {
        "n": n,
        "p50_ms": float(np.percentile(data, 50)) if n else None,
        "p95_ms": float(np.percentile(data, 95)) if n else None,
        "mean_ms": float(np.mean(data)) if n else None,
        "max_ms": float(max(data)) if n else None,
        "min_ms": float(min(data)) if n else None,
    }
    for name, limit in extra_thresholds:
        count = sum(1 for v in data if v > limit)
        result[name] = count
        result[name + "_frac"] = (count / n) if n else None
    return result


def isolate_qsettings(tmp_dir: Path) -> Path:
    """Divert org/app and bare QSettings away from MF4Analyzer/DataAnalyzer."""
    from PyQt5.QtCore import QSettings

    tmp_dir.mkdir(parents=True, exist_ok=True)
    ini = tmp_dir / "qsettings.ini"

    def temp_settings(*_args, **_kwargs):
        return QSettings(str(ini), QSettings.IniFormat)

    modules = [
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
        QSettings.setPath(fmt, QSettings.UserScope, str(tmp_dir))
        QSettings.setPath(fmt, QSettings.SystemScope, str(tmp_dir))
    return ini


def _is_native_org_app_ctor(args: tuple) -> bool:
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


class Counters:
    """Integer-only hot-path instrumentation. Perf mode must not time these."""

    __slots__ = (
        "setData_count",
        "visible_line_values_calls",
        "visible_line_values_full",
        "spectrum_plot_arrays_calls",
        "spectrum_plot_arrays_full",
        "peak_trace_count",
        "y_fit_fit_active",
        "y_fit_auto_amplitude",
        "y_fit_in_callback",
        "y_fit_in_timer",
        "y_fit_other",
        "spectrum_refresh_count",
        "spectrum_refresh_from_timer",
        "timedomain_refresh_visible_data",
        "cache_hit_count",
        "cache_rebuild_count",
        "cache_reason_hit",
        "cache_reason_empty",
        "cache_reason_revision",
        "cache_reason_coverage",
        "cache_reason_density",
        "prepared_query_count",
        "prepared_query_full_bounds",
        "prepared_query_in_callback",
    )

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        for name in self.__slots__:
            setattr(self, name, 0)

    def snapshot(self) -> dict:
        full = self.visible_line_values_full + self.spectrum_plot_arrays_full
        return {
            "setData_count": self.setData_count,
            "full_array_scan_count": full,
            "full_array_scan_visible_line_values": self.visible_line_values_full,
            "full_array_scan_spectrum_plot_arrays": self.spectrum_plot_arrays_full,
            "visible_line_values_calls": self.visible_line_values_calls,
            "spectrum_plot_arrays_calls": self.spectrum_plot_arrays_calls,
            "peak_trace_count": self.peak_trace_count,
            "y_fit_count": self.y_fit_fit_active,
            "y_fit_auto_amplitude_y_range": self.y_fit_auto_amplitude,
            "y_fit_in_callback": self.y_fit_in_callback,
            "y_fit_in_timer": self.y_fit_in_timer,
            "y_fit_other": self.y_fit_other,
            "spectrum_refresh_count": self.spectrum_refresh_count,
            "spectrum_refresh_from_timer": self.spectrum_refresh_from_timer,
            "timedomain_refresh_visible_data": self.timedomain_refresh_visible_data,
            "cache_hit_count": self.cache_hit_count,
            "cache_rebuild_count": self.cache_rebuild_count,
            "cache_reason_hit": self.cache_reason_hit,
            "cache_reason_empty": self.cache_reason_empty,
            "cache_reason_revision": self.cache_reason_revision,
            "cache_reason_coverage": self.cache_reason_coverage,
            "cache_reason_density": self.cache_reason_density,
            "prepared_query_count": self.prepared_query_count,
            "prepared_query_full_bounds": self.prepared_query_full_bounds,
            "prepared_query_in_callback": self.prepared_query_in_callback,
            "count_window": "timed_events_only",
        }


class ProbeFlags:
    in_input_callback = False
    in_spectrum_timer = False
    source_n = SOURCE_N
    tracked_pdi_ids: set[int] = set()
    counters = Counters()


def _array_len(value) -> int:
    import numpy as np

    try:
        arr = np.asarray(value)
    except Exception:
        return -1
    if arr.ndim != 1:
        return -1
    return int(arr.size)


def _note_cache_plan(plan) -> None:
    reason = str(getattr(plan, "reason", "") or "")
    if bool(getattr(plan, "reuse", False)):
        ProbeFlags.counters.cache_hit_count += 1
        ProbeFlags.counters.cache_reason_hit += 1
        return
    ProbeFlags.counters.cache_rebuild_count += 1
    attr = {
        "empty": "cache_reason_empty",
        "revision": "cache_reason_revision",
        "coverage": "cache_reason_coverage",
        "density": "cache_reason_density",
        "hit": "cache_reason_hit",
    }.get(reason)
    if attr:
        setattr(ProbeFlags.counters, attr, getattr(ProbeFlags.counters, attr) + 1)


def install_counting_wrappers() -> None:
    """Count-only monkeypatches, installed only in this probe process."""
    import mf4_analyzer.signal.display_ranges as display_ranges
    import mf4_analyzer.signal.envelope as envelope
    import mf4_analyzer.ui.pg_canvas.canvas as canvas_mod
    import mf4_analyzer.ui.pg_canvas.line_canvas as line_mod
    import mf4_analyzer.ui.pg_canvas.spectrum_display as spec_mod
    from pyqtgraph.graphicsItems.PlotDataItem import PlotDataItem

    orig_visible = display_ranges.visible_line_values
    orig_peak = envelope.build_peak_trace
    orig_plot_arrays = line_mod.PgLineCanvas._spectrum_plot_arrays
    orig_fit = line_mod.PgLineCanvas._fit_active_spectrum_y
    orig_auto = line_mod.PgLineCanvas._auto_amplitude_y_range
    orig_refresh = line_mod.PgLineCanvas._run_spectrum_display_transaction
    orig_td_refresh = canvas_mod.TimeDomainCanvasPG._refresh_visible_data
    orig_set_data = PlotDataItem.setData
    orig_plan = spec_mod.plan_spectrum_display
    orig_query = display_ranges.PreparedLineRange.query

    def visible_line_values(x, y, xlim, *, valid_mask=None):
        ProbeFlags.counters.visible_line_values_calls += 1
        if _array_len(x) == ProbeFlags.source_n:
            ProbeFlags.counters.visible_line_values_full += 1
        return orig_visible(x, y, xlim, valid_mask=valid_mask)

    def build_peak_trace(*args, **kwargs):
        ProbeFlags.counters.peak_trace_count += 1
        return orig_peak(*args, **kwargs)

    def spectrum_plot_arrays(self, freq, amp, *, xlim=None, prepared=None):
        ProbeFlags.counters.spectrum_plot_arrays_calls += 1
        if _array_len(freq) == ProbeFlags.source_n:
            ProbeFlags.counters.spectrum_plot_arrays_full += 1
        return orig_plot_arrays(self, freq, amp, xlim=xlim, prepared=prepared)

    def fit_active(self):
        ProbeFlags.counters.y_fit_fit_active += 1
        if ProbeFlags.in_input_callback:
            ProbeFlags.counters.y_fit_in_callback += 1
        elif ProbeFlags.in_spectrum_timer:
            ProbeFlags.counters.y_fit_in_timer += 1
        else:
            ProbeFlags.counters.y_fit_other += 1
        return orig_fit(self)

    def auto_amp(self, entries, xlim):
        ProbeFlags.counters.y_fit_auto_amplitude += 1
        return orig_auto(self, entries, xlim)

    def refresh_spectrum(self, *args, **kwargs):
        ProbeFlags.counters.spectrum_refresh_count += 1
        if ProbeFlags.in_spectrum_timer:
            ProbeFlags.counters.spectrum_refresh_from_timer += 1
        return orig_refresh(self, *args, **kwargs)

    def td_refresh(self, *args, **kwargs):
        ProbeFlags.counters.timedomain_refresh_visible_data += 1
        return orig_td_refresh(self, *args, **kwargs)

    def set_data(self, *args, **kwargs):
        if id(self) in ProbeFlags.tracked_pdi_ids:
            ProbeFlags.counters.setData_count += 1
        return orig_set_data(self, *args, **kwargs)

    def plan_spectrum_display(request, cache):
        plan = orig_plan(request, cache)
        _note_cache_plan(plan)
        return plan

    def prepared_query(self, xlim, **kwargs):
        ProbeFlags.counters.prepared_query_count += 1
        if ProbeFlags.in_input_callback:
            ProbeFlags.counters.prepared_query_in_callback += 1
        result = orig_query(self, xlim, **kwargs)
        if getattr(result, "used_cached_full_bounds", False):
            ProbeFlags.counters.prepared_query_full_bounds += 1
        return result

    display_ranges.visible_line_values = visible_line_values
    envelope.build_peak_trace = build_peak_trace
    line_mod.visible_line_values = visible_line_values
    line_mod.build_peak_trace = build_peak_trace
    line_mod.PgLineCanvas._spectrum_plot_arrays = spectrum_plot_arrays
    line_mod.PgLineCanvas._fit_active_spectrum_y = fit_active
    line_mod.PgLineCanvas._auto_amplitude_y_range = auto_amp
    line_mod.PgLineCanvas._run_spectrum_display_transaction = refresh_spectrum
    canvas_mod.TimeDomainCanvasPG._refresh_visible_data = td_refresh
    PlotDataItem.setData = set_data
    spec_mod.plan_spectrum_display = plan_spectrum_display
    line_mod.plan_spectrum_display = plan_spectrum_display
    display_ranges.PreparedLineRange.query = prepared_query


def hook_spectrum_timer(canvas) -> None:
    """Mark 16 ms timeout deliveries without adding a hot-path clock."""
    timer = getattr(canvas, "_spectrum_refresh_timer", None)
    if timer is None:
        return
    try:
        timer.timeout.disconnect()
    except Exception:
        pass

    def _on_timeout():
        ProbeFlags.in_spectrum_timer = True
        try:
            handler = getattr(
                canvas, "_on_spectrum_refresh_timeout", canvas._refresh_spectrum_display,
            )
            handler()
        finally:
            ProbeFlags.in_spectrum_timer = False

    timer.timeout.connect(_on_timeout)


def make_synthetic_xy():
    import numpy as np

    x = np.linspace(0.0, DATA_X_MAX_HZ, SOURCE_N)
    y = 60 * np.exp(-x / 80) - x / 400 + 5 * np.sin(x / 150) + np.sin(x * 5)
    return x, y


def _nearest_index(x, hz: float) -> int:
    import numpy as np

    return int(np.argmin(np.abs(x - float(hz))))


def make_correctness_xy():
    """T0 formula plus a known peak, raw deep valley, and NaN frequency break."""
    import numpy as np

    x, y = make_synthetic_xy()
    x = np.array(x, copy=True)
    y = np.array(y, copy=True)
    peak_i = _nearest_index(x, PEAK_HZ)
    valley_i = _nearest_index(x, VALLEY_HZ)
    nan_i = _nearest_index(x, NAN_HZ)
    y[peak_i] = PEAK_AMP
    y[valley_i] = VALLEY_AMP
    x[nan_i] = np.nan
    y[nan_i] = np.nan
    return x, y, {
        "peak_i": peak_i,
        "valley_i": valley_i,
        "nan_i": nan_i,
        "peak_hz": float(PEAK_HZ),
        "valley_hz": float(VALLEY_HZ),
        "nan_hz": float(NAN_HZ),
        "peak_amp": float(PEAK_AMP),
        "valley_amp": float(VALLEY_AMP),
    }


def fft_entries(x, y):
    import numpy as np

    entries = []
    for i, color in enumerate(COLORS[:N_CURVES]):
        amp = y - i
        entries.append({
            "label": str(i),
            "color": color,
            "freq": x,
            "amp": amp,
            "amp_for_xlim": 10 ** ((amp) / 20),
            "time": np.array([0.0, 1.0]),
            "signal": np.array([0.0, 1.0]),
        })
    return entries


def time_rows(x, y):
    rows = []
    for i, color in enumerate(COLORS[:N_CURVES]):
        rows.append((
            str(i), True, x, y - i, color, "dB", f"synthetic-{i}",
        ))
    return rows


def _wrap_instance_setdata(item) -> None:
    """Instance wrap: class-level PlotDataItem.setData does not see every curve."""
    if item is None:
        return
    ProbeFlags.tracked_pdi_ids.add(id(item))
    orig = item.setData
    if getattr(orig, "_spectrum_probe_wrapped", False):
        return

    def counted(*args, **kwargs):
        ProbeFlags.counters.setData_count += 1
        return orig(*args, **kwargs)

    counted._spectrum_probe_wrapped = True
    item.setData = counted


def track_curves(kind: str, canvas) -> None:
    ProbeFlags.tracked_pdi_ids.clear()
    if kind.startswith("fft"):
        for curve in getattr(canvas, "_amp_curves", ()):
            _wrap_instance_setdata(curve)
        return
    lines = getattr(canvas, "_channel_lines", None)
    if lines is None:
        return
    for _key, _name, (_axis, line) in lines.composite_items():
        _wrap_instance_setdata(getattr(line, "plot_data_item", None))


def active_viewbox(kind: str, canvas):
    if kind.startswith("fft"):
        return canvas._plot_amp.vb
    handle = getattr(canvas, "_primary_xaxis_ax", None)
    if handle is not None and getattr(handle, "view_box", None) is not None:
        return handle.view_box
    axes = getattr(canvas, "axes_list", None) or []
    if axes:
        return axes[0].view_box
    raise RuntimeError("no view box")


def viewbox_geometry(canvas, vb) -> dict:
    from PyQt5.QtCore import QRectF

    widget = canvas.size()
    glw = canvas._glw.size()
    scene = vb.sceneBoundingRect()
    try:
        mapped = canvas._glw.mapFromScene(scene)
        if hasattr(mapped, "boundingRect"):
            pixel = mapped.boundingRect()
        else:
            pixel = QRectF(mapped)
    except Exception:
        pixel = QRectF()
    try:
        dpr = float(canvas._glw.devicePixelRatioF())
    except Exception:
        dpr = None
    return {
        "widget_px": [int(widget.width()), int(widget.height())],
        "glw_px": [int(glw.width()), int(glw.height())],
        "viewbox_scene": [float(scene.x()), float(scene.y()),
                          float(scene.width()), float(scene.height())],
        "viewbox_mapped_px": [float(pixel.x()), float(pixel.y()),
                              float(pixel.width()), float(pixel.height())],
        "dpr": dpr,
    }


def viewport_pos_for_viewbox(canvas, vb, dx=0.0, dy=0.0):
    from PyQt5.QtCore import QPointF

    rect = vb.sceneBoundingRect()
    if float(rect.width()) <= 1.0 or float(rect.height()) <= 1.0:
        (x0, x1), (y0, y1) = vb.viewRange()
        scene_pt = vb.mapViewToScene(QPointF((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    else:
        scene_pt = rect.center()
    scene_pt = scene_pt + QPointF(float(dx), float(dy))
    return QPointF(canvas._glw.mapFromScene(scene_pt))


def wait_exposed(app, widget, *, timeout_ms=4000.0) -> bool:
    handle = widget.windowHandle()
    deadline = time.perf_counter() + float(timeout_ms) / 1000.0
    while time.perf_counter() < deadline:
        app.processEvents()
        if handle is None:
            handle = widget.windowHandle()
        try:
            if handle is not None and handle.isExposed():
                app.processEvents()
                return True
        except Exception:
            return False
        time.sleep(0.01)
    return False


def settle(app, ms=SETTLE_MS) -> None:
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.004)


def timed_repaint(canvas) -> tuple[float, bool]:
    viewport = canvas._glw.viewport()
    elapsed_ms = None
    for _ in range(2):
        started = time.perf_counter()
        canvas._glw.scene().update()
        viewport.repaint()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms >= PAINT_FLOOR_MS:
            break
    return float(elapsed_ms), float(elapsed_ms) < PAINT_FLOOR_MS


def restore_view(kind: str, canvas, *, y_auto: bool, xlim=XLIM) -> None:
    import pyqtgraph as pg

    vb = active_viewbox(kind, canvas)
    try:
        vb.setMouseMode(pg.ViewBox.PanMode)
    except Exception:
        pass
    lo, hi = float(xlim[0]), float(xlim[1])
    vb.setXRange(lo, hi, padding=0)
    if kind.startswith("fft"):
        if y_auto:
            canvas._spectrum_y_auto = True
            canvas._fit_active_spectrum_y()
        else:
            canvas._spectrum_y_auto = False
            canvas._plot_amp.setYRange(Y_MANUAL[0], Y_MANUAL[1], padding=0)
        flush = getattr(canvas, "flush_pending_spectrum_display", None)
        if callable(flush):
            flush()
    else:
        vb.setYRange(Y_MANUAL[0], Y_MANUAL[1], padding=0)


def current_xlim(kind: str, canvas) -> list[float]:
    lo, hi = active_viewbox(kind, canvas).viewRange()[0]
    return [float(lo), float(hi)]


def build_pan_trajectory(n_events: int) -> list[dict]:
    """press + horizontal moves + release + ctrl-wheel in/out pairs."""
    if n_events < 4:
        raise ValueError("need at least 4 events")
    wheel = min(10, max(0, (n_events - 4) // 5 * 2))
    if wheel % 2:
        wheel -= 1
    remaining = n_events - 2 - wheel
    moves = max(1, remaining)
    events = [{"kind": "press", "dx": 0}]
    for i in range(1, moves + 1):
        events.append({"kind": "move", "dx": i})
    events.append({"kind": "release", "dx": moves})
    for i in range(wheel):
        events.append({"kind": "wheel_in" if i % 2 == 0 else "wheel_out", "dx": moves})
    if len(events) < n_events:
        last_dx = events[-1]["dx"]
        events.extend({"kind": "move", "dx": last_dx} for _ in range(n_events - len(events)))
    return events[:n_events]


def build_narrow_pan_trajectory(n_events: int) -> list[dict]:
    """1 px X pans that stay inside a 0..200 Hz overscan cover (~0..300 Hz)."""
    if n_events < 3:
        raise ValueError("need at least 3 events")
    moves = n_events - 2
    events = [{"kind": "press", "dx": 0}]
    for i in range(1, moves + 1):
        events.append({"kind": "move", "dx": i})
    events.append({"kind": "release", "dx": moves})
    return events[:n_events]


def build_overscan_trajectory(n_events: int) -> list[dict]:
    """Alternate a cached 0..200 Hz window with one past the 0.5 overscan pad."""
    inside = (0.0, 200.0)
    outside = (400.0, 600.0)
    events = []
    for i in range(n_events):
        events.append({
            "kind": "xlim_step",
            "dx": 0,
            "xlim": inside if (i % 2 == 0) else outside,
        })
    return events


def build_wheel_zoom_trajectory(n_events: int) -> list[dict]:
    events = [{"kind": "press", "dx": 0}, {"kind": "release", "dx": 0}]
    while len(events) < n_events:
        events.append({"kind": "wheel_in", "dx": 0})
    return events[:n_events]


class _FakeDrag:
    """Minimal pyqtgraph mouseDragEvent object for localization only."""

    def __init__(self, pos, last, start, finish, down):
        from pyqtgraph import Point

        self._pos = Point(pos)
        self._last = Point(last)
        self._start = bool(start)
        self._finish = bool(finish)
        self._down = Point(down)

    def button(self):
        from PyQt5.QtCore import Qt

        return Qt.LeftButton

    def isStart(self):
        return self._start

    def isFinish(self):
        return self._finish

    def pos(self):
        return self._pos

    def lastPos(self):
        return self._last

    def buttonDownPos(self, *_args):
        return self._down

    def accept(self):
        return None

    def ignore(self):
        return None

    def isAccepted(self):
        return True

    def modifiers(self):
        from PyQt5.QtCore import Qt

        return Qt.NoModifier

    def scenePos(self):
        return self._pos

    def screenPos(self):
        return self._pos

    def lastScreenPos(self):
        return self._last


def send_xlim_step(canvas, spec) -> None:
    xlim = spec.get("xlim")
    if not xlim:
        return
    canvas._plot_amp.setXRange(float(xlim[0]), float(xlim[1]), padding=0)
    idle = getattr(canvas, "_idle_activity", None)
    if idle is not None and hasattr(idle, "note_pulse"):
        idle.note_pulse()
    try:
        canvas._begin_view_interaction()
    except Exception:
        pass
    canvas._plot_amp.vb.sigRangeChangedManually.emit([True, False])
    on_range = getattr(canvas, "_on_interactive_range_changed", None)
    if callable(on_range):
        on_range(canvas._plot_amp)


def send_gui_event(app, canvas, vb, spec) -> None:
    from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent, QWheelEvent
    from PyQt5.QtWidgets import QApplication

    if spec.get("kind") == "xlim_step":
        send_xlim_step(canvas, spec)
        return
    pos = viewport_pos_for_viewbox(canvas, vb, dx=float(spec["dx"]), dy=0.0)
    global_pos = QPointF(canvas._glw.viewport().mapToGlobal(pos.toPoint()))
    kind = spec["kind"]
    viewport = canvas._glw.viewport()
    if kind == "press":
        event = QMouseEvent(
            QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        QApplication.sendEvent(viewport, event)
        return
    if kind == "move":
        event = QMouseEvent(
            QEvent.MouseMove, pos, Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        )
        QApplication.sendEvent(viewport, event)
        return
    if kind == "release":
        event = QMouseEvent(
            QEvent.MouseButtonRelease, pos, Qt.LeftButton, Qt.NoButton, Qt.NoModifier,
        )
        QApplication.sendEvent(viewport, event)
        return
    angle = 120 if kind == "wheel_in" else -120
    event = QWheelEvent(
        pos,
        global_pos,
        QPoint(0, 0),
        QPoint(0, angle),
        Qt.NoButton,
        Qt.ControlModifier,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(viewport, event)


def send_direct_event(canvas, vb, spec, origin) -> None:
    from pyqtgraph import Point

    if spec.get("kind") == "xlim_step":
        send_xlim_step(canvas, spec)
        return
    x0, y0 = origin
    dx = float(spec["dx"])
    pos = Point(x0 + dx, y0)
    last = Point(x0 + max(0.0, dx - 1.0), y0)
    down = Point(x0, y0)
    kind = spec["kind"]
    if kind.startswith("wheel"):
        return
    drag = _FakeDrag(
        pos, last,
        start=(kind == "press"),
        finish=(kind == "release"),
        down=down,
    )
    vb.mouseDragEvent(drag)


def drive_scheduled(app, n_events, interval_s, fire):
    from PyQt5.QtCore import QEventLoop, QTimer, Qt

    samples = []
    error = {"text": None}
    loop = QEventLoop()
    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.setSingleShot(True)
    state = {"i": 0, "t0": 0.0}

    def tick():
        try:
            i = state["i"]
            scheduled = state["t0"] + i * interval_s
            actual = time.perf_counter()
            samples.append(fire(i, scheduled, actual))
            state["i"] = i + 1
            if state["i"] >= n_events:
                timer.stop()
                loop.quit()
                return
            delay_s = state["t0"] + state["i"] * interval_s - time.perf_counter()
            timer.start(max(0, int(round(delay_s * 1000.0))))
        except Exception:
            error["text"] = traceback.format_exc()
            timer.stop()
            loop.quit()

    timer.timeout.connect(tick)
    state["t0"] = time.perf_counter()
    timer.start(0)
    loop.exec_()
    if error["text"]:
        raise RuntimeError(error["text"])
    return samples, state["t0"]


def fire_one(app, *, kind, canvas, vb, spec, input_mode, origin, scheduled, actual, index):
    callback_started = time.perf_counter()
    ProbeFlags.in_input_callback = True
    try:
        if input_mode == "gui_event":
            send_gui_event(app, canvas, vb, spec)
        else:
            send_direct_event(canvas, vb, spec, origin)
    finally:
        ProbeFlags.in_input_callback = False
    callback_ms = (time.perf_counter() - callback_started) * 1000.0
    paint_ms, suspect = timed_repaint(canvas)
    return {
        "i": int(index),
        "kind": spec["kind"],
        "scheduled_s": float(scheduled),
        "actual_s": float(actual),
        "lag_ms": float((actual - scheduled) * 1000.0),
        "callback_ms": float(callback_ms),
        "paint_ms": float(paint_ms),
        "callback_plus_paint_ms": float(callback_ms + paint_ms),
        "suspect_paint": bool(suspect),
        "input_mode": input_mode,
    }


def plot_canvas(app, kind, canvas, x, y, *, y_auto: bool, xlim=XLIM) -> dict:
    ProbeFlags.counters.reset()
    rss_before = rss_bytes()
    started = time.perf_counter()
    if kind.startswith("fft"):
        canvas.plot_spectra(
            fft_entries(x, y),
            xlim=xlim,
            amp_label="Amplitude (dB)",
            title="probe",
            y_auto=y_auto,
            y_min=Y_MANUAL[0],
            y_max=Y_MANUAL[1],
        )
    else:
        canvas.plot_channels(
            time_rows(x, y),
            mode="overlay",
            render_context_key=("spectrum-probe", "time"),
        )
    app.processEvents()
    restore_view(kind, canvas, y_auto=y_auto, xlim=xlim)
    app.processEvents()
    paint_ms, suspect = timed_repaint(canvas)
    first_ms = (time.perf_counter() - started) * 1000.0
    track_curves(kind, canvas)
    return {
        "first_paint_ms": float(first_ms),
        "forced_repaint_ms": float(paint_ms),
        "suspect_first_paint": bool(suspect),
        "setup_counts_excluded": ProbeFlags.counters.snapshot(),
        "rss_before": rss_before,
        "rss_after": rss_bytes(),
        "xlim": [float(xlim[0]), float(xlim[1])],
    }


def run_event_batch(app, *, kind, canvas, input_mode, hz, n_events, trajectory):
    import pyqtgraph as pg

    vb = active_viewbox(kind, canvas)
    try:
        vb.setMouseMode(pg.ViewBox.PanMode)
    except Exception:
        pass
    rect = vb.rect()
    origin = (float(rect.center().x()) - 40.0, float(rect.center().y()))
    interval_s = 1.0 / float(hz)
    xlim_before = current_xlim(kind, canvas)

    def fire(i, scheduled, actual):
        return fire_one(
            app, kind=kind, canvas=canvas, vb=vb, spec=trajectory[i],
            input_mode=input_mode, origin=origin,
            scheduled=scheduled, actual=actual, index=i,
        )

    samples, t0 = drive_scheduled(app, n_events, interval_s, fire)
    settle_started = time.perf_counter()
    settle(app, SETTLE_MS)
    settle_ms = (time.perf_counter() - settle_started) * 1000.0
    xlim_after = current_xlim(kind, canvas)
    if xlim_before == xlim_after:
        print(
            f"    WARN xlim unchanged {kind} {input_mode} "
            f"{xlim_before} geom={vb.sceneBoundingRect()}",
            flush=True,
        )
    return {
        "samples": samples,
        "settle_ms": float(settle_ms),
        "xlim_before": xlim_before,
        "xlim_after": xlim_after,
        "xlim_changed": xlim_before != xlim_after,
        "t0": t0,
        "interval_s": interval_s,
    }


def summarize_samples(samples, settle_ms_list) -> dict:
    callback = [s["callback_ms"] for s in samples]
    paint = [s["paint_ms"] for s in samples]
    both = [s["callback_plus_paint_ms"] for s in samples]
    lag = [s["lag_ms"] for s in samples]
    thresholds = (
        ("over_16_7_ms", FRAME_16_7_MS),
        ("over_8_3_ms", FRAME_8_3_MS),
    )
    return {
        "n": len(samples),
        "callback": _stats(callback, extra_thresholds=thresholds),
        "paint": _stats(paint, extra_thresholds=thresholds),
        "callback_plus_paint": _stats(both, extra_thresholds=thresholds),
        "event_lag": _stats(lag),
        "settle": _stats(settle_ms_list),
        "suspect_paint_count": sum(1 for s in samples if s["suspect_paint"]),
        "excluded": ["warmup", "first_paint", "final_settle"],
    }


def create_canvas(kind: str, width: int, height: int):
    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    canvas = PgLineCanvas() if kind.startswith("fft") else TimeDomainCanvasPG()
    canvas.resize(width, height)
    canvas.setWindowTitle(f"spectrum-probe {kind}")
    if kind.startswith("fft"):
        hook_spectrum_timer(canvas)
    return canvas


def environment_info(app, canvas) -> dict:
    import numpy as np
    import pyqtgraph
    from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    info = {
        "platform_plugin": app.platformName(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "qt": QT_VERSION_STR,
        "pyqt": PYQT_VERSION_STR,
        "pyqtgraph": pyqtgraph.__version__,
        "numpy": np.__version__,
        "qt_qpa_platform_env": os.environ.get("QT_QPA_PLATFORM"),
    }
    try:
        info["loadavg"] = os.getloadavg()
    except OSError:
        info["loadavg"] = None
    if canvas is not None:
        try:
            info["dpr"] = float(canvas._glw.devicePixelRatioF())
        except Exception:
            info["dpr"] = None
    return info


def maybe_reexec_offscreen(args, exposed: bool) -> None:
    if exposed:
        return
    if args.offscreen or args.offscreen_fallback:
        return
    if os.environ.get("SPECTRUM_PROBE_OFFSCREEN_FALLBACK") == "1":
        return
    print("native window was not exposed; re-execing offscreen fallback", flush=True)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["SPECTRUM_PROBE_OFFSCREEN_FALLBACK"] = "1"
    os.execve(sys.executable, [sys.executable, *sys.argv, "--offscreen-fallback"], env)


def prepare_qt(args):
    if args.offscreen or args.offscreen_fallback:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    settings_dir = Path(tempfile.mkdtemp(prefix="spectrum-pan-qsettings-", dir="/tmp"))
    isolate_qsettings(settings_dir)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("TraceLabProbe")
    app.setApplicationName("SpectrumPanProbe")
    try:
        app.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    except Exception:
        pass
    return app, settings_dir


def scenario_order():
    return (
        ("fft_auto_y", "fft", True),
        ("fft_manual_y", "fft", False),
        ("time_domain", "time", False),
    )


def input_modes_for(args) -> list[str]:
    if args.quick:
        return ["gui_event"]
    if args.mode == "profile" and args.input_mode == "both":
        return ["gui_event"]
    if args.input_mode == "gui":
        return ["gui_event"]
    if args.input_mode == "direct_viewbox":
        return ["direct_viewbox"]
    return ["gui_event", "direct_viewbox"]


def rates_for(args, input_mode: str) -> list[int]:
    if args.quick:
        return [60]
    if args.mode == "profile":
        return [60]
    if input_mode == "direct_viewbox":
        return [60]
    return [60, 120]


def extra_scenario_specs(args):
    if args.quick or args.mode == "profile" or args.skip_extra:
        return ()
    return (
        {
            "name": "fft_narrow_incache",
            "kind": "fft",
            "y_auto": True,
            "xlim": NARROW_XLIM,
            "input_mode": "gui_event",
            "trajectory": "narrow",
            "data": "correctness",
        },
        {
            "name": "fft_overscan_cross",
            "kind": "fft",
            "y_auto": True,
            "xlim": NARROW_XLIM,
            "input_mode": "xlim_step",
            "trajectory": "overscan",
            "data": "correctness",
        },
        {
            "name": "fft_wheel_zoom",
            "kind": "fft",
            "y_auto": True,
            "xlim": NARROW_XLIM,
            "input_mode": "gui_event",
            "trajectory": "wheel_zoom",
            "data": "correctness",
        },
    )


def trajectory_for(spec, n_events: int):
    kind = spec.get("trajectory", "wide")
    if kind == "narrow":
        return build_narrow_pan_trajectory(n_events)
    if kind == "overscan":
        return build_overscan_trajectory(n_events)
    if kind == "wheel_zoom":
        return build_wheel_zoom_trajectory(n_events)
    return build_pan_trajectory(n_events)


def aa_timer_interval(canvas):
    timer = getattr(canvas, "_aa_idle_timer", None)
    if timer is None:
        return None
    try:
        return int(timer.interval())
    except Exception:
        return None


def curve_xy(canvas):
    import numpy as np

    if not getattr(canvas, "_amp_curves", None):
        return None, None
    data = canvas._amp_curves[0].getData()
    if data is None or data[0] is None:
        return np.array([]), np.array([])
    return np.asarray(data[0], dtype=float), np.asarray(data[1], dtype=float)


def peak_present(y, amp=PEAK_AMP, atol=1e-6) -> bool:
    import numpy as np

    if y is None or getattr(y, "size", 0) == 0:
        return False
    finite = y[np.isfinite(y)]
    if finite.size == 0:
        return False
    return bool(np.any(np.abs(finite - float(amp)) <= atol) or np.max(finite) >= float(amp) - 1.0)


def save_screenshot(widget, path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    pix = widget.grab()
    ok = bool(pix.save(str(path), "PNG"))
    return {
        "path": str(path),
        "ok": ok,
        "width": int(pix.width()),
        "height": int(pix.height()),
    }


def group_scenario_rows(rows, *, name, kind, y_auto, input_mode, hz, n_events,
                        warmup_events, geometry, first_paint, exposed):
    samples = [s for row in rows for s in row["batch"]["samples"]]
    settles = [row["batch"]["settle_ms"] for row in rows]
    xlim_changed = [row["batch"]["xlim_changed"] for row in rows]
    return {
        "name": name,
        "kind": kind,
        "y_auto": y_auto,
        "input_mode": input_mode,
        "target_hz": hz,
        "rounds": len(rows),
        "events_per_round": n_events,
        "warmup_events": warmup_events,
        "plot_geometry": geometry,
        "first_paint": first_paint,
        "exposed": exposed,
        "xlim_changed_per_round": xlim_changed,
        "timed_events": {
            **summarize_samples(samples, settles),
            "raw_samples": samples,
        },
        "counts": {
            key: sum(row["counts"][key] for row in rows)
            for key in rows[0]["counts"]
            if key != "count_window"
        } | {"count_window": "timed_events_only_summed_over_rounds"},
        "per_round_counts": [row["counts"] for row in rows],
        "per_round_xlim": [
            {
                "before": row["batch"]["xlim_before"],
                "after": row["batch"]["xlim_after"],
            }
            for row in rows
        ],
        "profile_dumps": [row["profile_dump"] for row in rows],
        "peak_present_after_round": [
            row.get("peak_present") for row in rows
        ],
    }


def read_correctness(canvas, entry, meta, *, xlim):
    import numpy as np
    from mf4_analyzer.signal.display_ranges import line_amplitude_limits

    flush = getattr(canvas, "flush_pending_spectrum_display", None)
    if callable(flush):
        flush()
    raw_freq = entry["freq"]
    raw_amp = entry["amp"]
    xr, yr = canvas._plot_amp.vb.viewRange()
    trace_x, trace_y = curve_xy(canvas)
    nan_in_polyline = bool(
        trace_x.size and np.isnan(trace_x).any() and np.isnan(trace_y).any()
    )
    prepared = canvas._lookup_prepared_for_entry(entry)
    query = prepared.query(xlim) if prepared is not None else None
    expected_y = line_amplitude_limits(
        np.array([query.y_min, query.y_max], dtype=float) if query is not None else raw_amp,
        amplitude_mode="amplitude_db",
    )
    return {
        "raw_freq_id": id(raw_freq),
        "raw_amp_id": id(raw_amp),
        "raw_n": int(np.asarray(raw_freq).size),
        "raw_peak_amp": float(raw_amp[meta["peak_i"]]),
        "raw_valley_amp": float(raw_amp[meta["valley_i"]]),
        "raw_nan_x": bool(np.isnan(raw_freq[meta["nan_i"]])),
        "xlim": [float(xr[0]), float(xr[1])],
        "ylim": [float(yr[0]), float(yr[1])],
        "ylim_covers_valley": bool(yr[0] <= VALLEY_AMP <= yr[1]),
        "ylim_covers_peak": bool(yr[0] <= PEAK_AMP <= yr[1]),
        "query_y_min": None if query is None else query.y_min,
        "query_y_max": None if query is None else query.y_max,
        "query_fully_covered": None if query is None else bool(query.fully_covered),
        "expected_padded_ylim": None if expected_y is None else [float(expected_y[0]), float(expected_y[1])],
        "trace_n": int(trace_x.size),
        "peak_in_trace": peak_present(trace_y),
        "nan_break_in_polyline": nan_in_polyline,
        "aa_idle_timer_ms": aa_timer_interval(canvas),
        "raw_identity_unchanged": True,
    }


def run_correctness_snapshot(app, canvas, x, y, meta, *, output_dir: Path):
    entries = fft_entries(x, y)
    entry = entries[0]
    freq_id, amp_id = id(entry["freq"]), id(entry["amp"])
    plot = plot_canvas(app, "fft", canvas, x, y, y_auto=True, xlim=NARROW_XLIM)
    settle(app, SETTLE_MS)
    before = read_correctness(canvas, entry, meta, xlim=NARROW_XLIM)
    canvas._plot_amp.setXRange(20.0, 180.0, padding=0)
    idle = getattr(canvas, "_idle_activity", None)
    if idle is not None and hasattr(idle, "note_pulse"):
        idle.note_pulse()
    canvas._plot_amp.vb.sigRangeChangedManually.emit([True, False])
    settle(app, SETTLE_MS)
    canvas.flush_pending_spectrum_display()
    after = read_correctness(canvas, entry, meta, xlim=tuple(canvas._plot_amp.vb.viewRange()[0]))
    after["raw_identity_unchanged"] = (
        id(entry["freq"]) == freq_id and id(entry["amp"]) == amp_id
        and after["raw_n"] == SOURCE_N
        and after["raw_peak_amp"] == PEAK_AMP
        and after["raw_valley_amp"] == VALLEY_AMP
        and after["raw_nan_x"] is True
    )
    shot = save_screenshot(canvas, output_dir / "correctness-nan-valley.png")
    restore_view("fft", canvas, y_auto=True, xlim=NARROW_XLIM)
    wide = plot_canvas(app, "fft", canvas, x, y, y_auto=True, xlim=XLIM)
    settle(app, 80)
    wide_shot = save_screenshot(canvas, output_dir / "wide-pan.png")
    restore_view("fft", canvas, y_auto=True, xlim=NARROW_XLIM)
    settle(app, 80)
    narrow_shot = save_screenshot(canvas, output_dir / "narrow-window.png")
    return {
        "first_paint": plot,
        "wide_replot_first_paint_ms": wide.get("first_paint_ms"),
        "before_pan": before,
        "after_pan_flush": after,
        "screenshots": [shot, wide_shot, narrow_shot],
        "aa_idle_timer_ms": aa_timer_interval(canvas),
        "pass": bool(
            after["raw_identity_unchanged"]
            and after["ylim_covers_valley"]
            and after["peak_in_trace"]
            and after["nan_break_in_polyline"]
            and after["aa_idle_timer_ms"] == 150
        ),
    }


def run_revision_invalidation(app, canvas, x, y):
    """New result / Linear↔dB must miss the old cache; Y still from raw."""
    plot_canvas(app, "fft", canvas, x, y, y_auto=True, xlim=NARROW_XLIM)
    settle(app, 80)
    restore_view("fft", canvas, y_auto=True, xlim=NARROW_XLIM)
    canvas.flush_pending_spectrum_display()
    ProbeFlags.counters.reset()
    canvas._plot_amp.setXRange(5.0, 195.0, padding=0)
    canvas._plot_amp.vb.sigRangeChangedManually.emit([True, False])
    canvas.flush_pending_spectrum_display()
    hit_counts = ProbeFlags.counters.snapshot()
    ProbeFlags.counters.reset()
    rss_before = rss_bytes()
    started = time.perf_counter()
    canvas.plot_spectra(
        fft_entries(x, y + 1.0),
        xlim=NARROW_XLIM,
        amp_label="Amplitude",
        title="probe-linear",
        y_auto=True,
        y_min=Y_MANUAL[0],
        y_max=Y_MANUAL[1],
    )
    app.processEvents()
    linear_ms = (time.perf_counter() - started) * 1000.0
    linear_counts = ProbeFlags.counters.snapshot()
    canvas.flush_pending_spectrum_display()
    return {
        "in_cache_pan_after_prepare": hit_counts,
        "linear_replot_ms": float(linear_ms),
        "linear_replot_counts": linear_counts,
        "rss_after_linear": rss_bytes(),
        "rss_before_linear": rss_before,
        "aa_idle_timer_ms": aa_timer_interval(canvas),
    }


def run_resize_and_foreign(app, canvas, *, width, height):
    ProbeFlags.counters.reset()
    started = time.perf_counter()
    canvas.resize(width + 400, height)
    app.processEvents()
    canvas.flush_pending_spectrum_display()
    resize_ms = (time.perf_counter() - started) * 1000.0
    resize_counts = ProbeFlags.counters.snapshot()
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication, QWidget

    foreign = QWidget()
    foreign.resize(80, 80)
    foreign.show()
    app.processEvents()
    ProbeFlags.counters.reset()
    event = QMouseEvent(
        QEvent.MouseButtonPress,
        foreign.rect().center(),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    QApplication.sendEvent(foreign, event)
    canvas.flush_pending_spectrum_display()
    foreign_counts = ProbeFlags.counters.snapshot()
    interval_after = aa_timer_interval(canvas)
    foreign.hide()
    foreign.close()
    foreign.deleteLater()
    canvas.resize(width, height)
    app.processEvents()
    canvas.flush_pending_spectrum_display()
    return {
        "resize_ms": float(resize_ms),
        "resize_counts": resize_counts,
        "foreign_press_counts": foreign_counts,
        "aa_idle_timer_ms": interval_after,
    }


def run_contrast(app, *, width, height, n_events, hz, output_dir: Path):
    """Heatmap slice / FRF measurement only. Never folded into FFT p50/p95."""
    import numpy as np
    import mf4_analyzer.ui.pg_canvas.heatmap_canvas as heat_mod
    import mf4_analyzer.ui.pg_canvas.slice_panel as slice_mod
    import mf4_analyzer.ui.pg_canvas.frf_canvas as frf_mod
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas
    from types import SimpleNamespace
    from pyqtgraph.graphicsItems.PlotDataItem import PlotDataItem

    contrast = {
        "heatmap_slice_on": {},
        "heatmap_slice_off": {},
        "frf": {},
        "note": (
            "Contrast timings are isolated from FFT perf stats. "
            "Do not treat them as sharing the FFT pan cause."
        ),
    }
    freqs = np.linspace(0.0, 2000.0, 513)
    times = np.linspace(0.0, 2.0, 128)
    amp = np.clip(
        np.outer(np.exp(-freqs / 400.0), 0.2 + 0.8 * np.sin(2 * np.pi * times)),
        1e-6, None,
    ).astype(np.float32)
    result = SpectrogramResult(
        times=times, frequencies=freqs, amplitude=amp,
        params=SpectrogramParams(fs=4000.0, nfft=1024),
        channel_name="contrast", unit="Pa",
    )

    orig_sync = heat_mod.PgHeatmapCanvas._sync_slice_to_heatmap_view
    orig_apply = slice_mod._SliceStrip._apply_slice
    orig_set = PlotDataItem.setData
    display_ranges = __import__(
        "mf4_analyzer.signal.display_ranges", fromlist=["visible_line_values"]
    )
    orig_visible = display_ranges.visible_line_values
    orig_slice_visible = slice_mod.visible_line_values
    orig_frf_render = frf_mod.PgFrfCanvas._render_result
    orig_frf_ticks = frf_mod.PgFrfCanvas._sync_frequency_ticks

    def wrap_timed(bucket, key, orig):
        def inner(*args, **kwargs):
            started = time.perf_counter()
            try:
                return orig(*args, **kwargs)
            finally:
                bucket[key + "_calls"] = bucket.get(key + "_calls", 0) + 1
                bucket[key + "_ms"] = bucket.get(key + "_ms", 0.0) + (
                    time.perf_counter() - started
                ) * 1000.0
        return inner

    def restore_heatmap_wrappers():
        heat_mod.PgHeatmapCanvas._sync_slice_to_heatmap_view = orig_sync
        slice_mod._SliceStrip._apply_slice = orig_apply
        PlotDataItem.setData = orig_set
        display_ranges.visible_line_values = orig_visible
        slice_mod.visible_line_values = orig_slice_visible

    def run_heatmap(with_slice: bool, bucket: dict):
        canvas = PgHeatmapCanvas(with_slice=with_slice)
        canvas.resize(width, height)
        canvas.show()
        app.processEvents()
        wait_exposed(app, canvas, timeout_ms=2000.0)
        timed_visible = wrap_timed(bucket, "visible_line_values", orig_visible)
        heat_mod.PgHeatmapCanvas._sync_slice_to_heatmap_view = wrap_timed(
            bucket, "sync_slice", orig_sync,
        )
        slice_mod._SliceStrip._apply_slice = wrap_timed(bucket, "apply_slice", orig_apply)

        def set_data(self, *args, **kwargs):
            bucket["setData_calls"] = bucket.get("setData_calls", 0) + 1
            started = time.perf_counter()
            try:
                return orig_set(self, *args, **kwargs)
            finally:
                bucket["setData_ms"] = bucket.get("setData_ms", 0.0) + (
                    time.perf_counter() - started
                ) * 1000.0

        PlotDataItem.setData = set_data
        display_ranges.visible_line_values = timed_visible
        slice_mod.visible_line_values = timed_visible
        try:
            started = time.perf_counter()
            canvas.plot_result(
                result, amplitude_mode="amplitude_db", cmap="turbo",
                z_auto=True, y_auto=True, x_auto=True,
            )
            app.processEvents()
            bucket["first_paint_ms"] = (time.perf_counter() - started) * 1000.0
            vb = canvas._plot.vb
            trajectory = build_pan_trajectory(n_events)

            def fire(i, scheduled, actual):
                return fire_one(
                    app, kind="heatmap", canvas=canvas, vb=vb, spec=trajectory[i],
                    input_mode="gui_event", origin=(0.0, 0.0),
                    scheduled=scheduled, actual=actual, index=i,
                )

            ProbeFlags.counters.reset()
            samples, _t0 = drive_scheduled(app, n_events, 1.0 / float(hz), fire)
            settle(app, SETTLE_MS)
            bucket["timed"] = summarize_samples(samples, [SETTLE_MS])
            bucket["fft_counters_unrelated"] = ProbeFlags.counters.snapshot()
            if with_slice:
                save_screenshot(canvas, output_dir / "contrast-heatmap-slice.png")
        finally:
            canvas.hide()
            canvas.close()
            canvas.deleteLater()
            restore_heatmap_wrappers()
            app.processEvents()

    try:
        run_heatmap(True, contrast["heatmap_slice_on"])
        run_heatmap(False, contrast["heatmap_slice_off"])
    except Exception:
        contrast["heatmap_error"] = traceback.format_exc()

    frf = None
    try:
        frf = PgFrfCanvas()
        frf.resize(width, height)
        frf.show()
        app.processEvents()
        wait_exposed(app, frf, timeout_ms=2000.0)
        bucket = contrast["frf"]
        frf_mod.PgFrfCanvas._render_result = wrap_timed(bucket, "render_result", orig_frf_render)
        frf_mod.PgFrfCanvas._sync_frequency_ticks = wrap_timed(
            bucket, "sync_frequency_ticks", orig_frf_ticks,
        )

        def frf_set(self, *args, **kwargs):
            bucket["setData_calls"] = bucket.get("setData_calls", 0) + 1
            started = time.perf_counter()
            try:
                return orig_set(self, *args, **kwargs)
            finally:
                bucket["setData_ms"] = bucket.get("setData_ms", 0.0) + (
                    time.perf_counter() - started
                ) * 1000.0

        PlotDataItem.setData = frf_set
        n = 8192
        frequencies = np.linspace(0.0, 2000.0, n)
        transfer = (1.0 / (1.0 + 1j * (frequencies - 120.0) / 40.0)).astype(np.complex128)
        coherence = np.clip(0.95 - frequencies / 8000.0, 0.2, 1.0)
        frf_result = SimpleNamespace(
            frequencies=frequencies, transfer=transfer, coherence=coherence,
            effective=SimpleNamespace(fs=4000.0, df=frequencies[1] - frequencies[0], segments=8),
            warnings=(),
        )
        started = time.perf_counter()
        frf.set_result(frf_result, {
            "magnitude_scale": "db",
            "frequency_scale": "log",
            "phase_mode": "unwrapped",
            "coherence_threshold": 0.5,
            "fade_low_coherence": True,
        }, {"input_unit": "N", "output_unit": "m/s"})
        app.processEvents()
        bucket["first_paint_ms"] = (time.perf_counter() - started) * 1000.0
        vb = frf._plot_magnitude.vb
        trajectory = build_pan_trajectory(n_events)

        def fire(i, scheduled, actual):
            return fire_one(
                app, kind="frf", canvas=frf, vb=vb, spec=trajectory[i],
                input_mode="gui_event", origin=(0.0, 0.0),
                scheduled=scheduled, actual=actual, index=i,
            )

        samples, _t0 = drive_scheduled(app, n_events, 1.0 / float(hz), fire)
        settle(app, SETTLE_MS)
        bucket["timed"] = summarize_samples(samples, [SETTLE_MS])
        bucket["three_curves"] = True
        bucket["log_frequency"] = True
        save_screenshot(frf, output_dir / "contrast-frf.png")
    except Exception:
        contrast["frf_error"] = traceback.format_exc()
    finally:
        if frf is not None:
            try:
                frf.hide()
                frf.close()
                frf.deleteLater()
            except Exception:
                pass
        frf_mod.PgFrfCanvas._render_result = orig_frf_render
        frf_mod.PgFrfCanvas._sync_frequency_ticks = orig_frf_ticks
        PlotDataItem.setData = orig_set
        restore_heatmap_wrappers()
        app.processEvents()
    contrast["note"] = (
        "Contrast timings are isolated from FFT perf stats. "
        "sync_slice includes apply_slice on the slice-on path; do not add them. "
        "Do not treat heatmap/FRF hotspots as sharing the FFT pan cause."
    )
    return contrast


def _destroy_mainwindow(app, win) -> None:
    from PyQt5.QtCore import QCoreApplication, QEvent

    holder = getattr(win, "_project_dirty", None)
    if holder is not None:
        holder.save_point = holder.revision
        holder.close_teardown_started = True
    try:
        win.hide()
        app.processEvents()
        win.close()
    except Exception:
        pass
    try:
        win.deleteLater()
    except Exception:
        pass
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def run_mainwindow_probe(app, x, y, *, width, height, n_events, hz, output_dir: Path):
    """Product-path FFT canvas with analysis_range_adapter. Isolated QSettings."""
    from mf4_analyzer.ui.main_window import MainWindow

    payload = {
        "constructed": False,
        "plotted": False,
        "limitation": None,
    }
    win = None
    try:
        win = MainWindow()
        win.resize(width, height)
        win.show()
        win.raise_()
        app.processEvents()
        exposed = wait_exposed(app, win, timeout_ms=4000.0)
        payload["constructed"] = True
        payload["exposed"] = bool(exposed)
        win.toolbar._set_mode("fft")
        app.processEvents()
        canvas = win.canvas_fft
        hook_spectrum_timer(canvas)
        entries = fft_entries(x, y)
        ctx = win.inspector.fft_ctx
        ctx.chk_y_auto.setChecked(True)
        ctx.chk_x_auto.setChecked(True)
        started = time.perf_counter()
        win._plot_fft_entries(entries, canvas)
        app.processEvents()
        payload["first_plot_ms"] = (time.perf_counter() - started) * 1000.0
        payload["plotted"] = bool(getattr(canvas, "has_result", lambda: bool(canvas._amp_curves))())
        track_curves("fft", canvas)
        restore_view("fft", canvas, y_auto=True, xlim=XLIM)
        settle(app, SETTLE_MS)
        adapter = getattr(canvas, "analysis_range_adapter", None)
        policy_before = adapter[0]() if adapter is not None else None
        ProbeFlags.counters.reset()
        trajectory = build_pan_trajectory(n_events)
        vb = active_viewbox("fft", canvas)

        def fire(i, scheduled, actual):
            return fire_one(
                app, kind="fft", canvas=canvas, vb=vb, spec=trajectory[i],
                input_mode="gui_event", origin=(0.0, 0.0),
                scheduled=scheduled, actual=actual, index=i,
            )

        samples, _t0 = drive_scheduled(app, n_events, 1.0 / float(hz), fire)
        canvas.flush_pending_spectrum_display()
        settle(app, SETTLE_MS)
        policy_after = adapter[0]() if adapter is not None else None
        page = win.chart_stack.page_fft
        status = page.viewport_status_label.text() if hasattr(page, "viewport_status_label") else ""
        origin_after = (policy_after or {}).get("viewport_origin", {})
        payload["timed"] = summarize_samples(samples, [SETTLE_MS])
        payload["counts"] = ProbeFlags.counters.snapshot()
        payload["viewport_status"] = status
        payload["viewport_origin_before"] = None if policy_before is None else dict(
            (policy_before.get("viewport_origin") or {}),
        )
        payload["viewport_origin_after"] = dict(origin_after)
        payload["auto_y_mislabeled_manual"] = origin_after.get("y") == "user"
        payload["aa_idle_timer_ms"] = aa_timer_interval(canvas)
        export_pix = canvas.grab_pixmap(scale=1.0)
        payload["export_grab"] = {
            "null": bool(export_pix.isNull()),
            "width": int(export_pix.width()),
            "height": int(export_pix.height()),
        }
        payload["screenshot"] = save_screenshot(win, output_dir / "mainwindow-fft.png")
        try:
            win._on_analysis_split("fft", True)
            app.processEvents()
            c1 = win.chart_stack.page_fft.pane_canvas(1)
            win._plot_fft_entries(entries, c1)
            app.processEvents()
            payload["dual_pane"] = {
                "pane1_has_curves": bool(getattr(c1, "_amp_curves", ())),
                "pane0_origin": dict(origin_after),
            }
        except Exception:
            payload["dual_pane_error"] = traceback.format_exc()
        payload["limitation"] = (
            "Synthetic in-memory FFT entries via _plot_fft_entries; no customer "
            "file load, no worker compute, no history-from-project."
        )
    except Exception:
        payload["error"] = traceback.format_exc()
        payload["limitation"] = (
            "MainWindow product-path probe failed; see error. Bare-canvas "
            "rows remain the comparable T0/T4 measurement."
        )
    finally:
        if win is not None:
            _destroy_mainwindow(app, win)
    return payload


def run_probe(args) -> dict:
    if args.mode == "profile" and args.quick is False:
        # Full 5x120 under cProfile is attribution, not a comparable baseline.
        pass

    fingerprint = build_fingerprint()
    if args.fingerprint_out:
        _write_json(args.fingerprint_out, fingerprint)

    rounds = 1 if args.quick else max(1, args.rounds)
    if args.mode == "profile" and not args.quick and args.rounds == 5:
        # Attribution dump, not the comparable 5x120 cadence study.
        rounds = 1
    n_events = 20 if args.quick else max(4, args.events)
    warmup_events = min(12, n_events)
    width, height = args.width, args.height

    app, settings_dir = prepare_qt(args)
    install_counting_wrappers()

    from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG  # noqa: F401
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas  # noqa: F401

    x, y = make_synthetic_xy()
    canvases = {}
    first_paints = {}
    exposed_flags = {}
    geometries = {}

    for name, kind, y_auto in scenario_order():
        canvas = create_canvas(kind, width, height)
        canvas.show()
        canvas.raise_()
        canvas.activateWindow()
        app.processEvents()
        exposed = wait_exposed(app, canvas)
        maybe_reexec_offscreen(args, exposed)
        exposed_flags[name] = bool(exposed)
        first_paints[name] = plot_canvas(app, kind, canvas, x, y, y_auto=y_auto)
        settle(app, SETTLE_MS)
        geometries[name] = viewbox_geometry(canvas, active_viewbox(kind, canvas))
        canvases[name] = canvas
        print(
            f"ready {name} exposed={exposed} first_paint_ms="
            f"{first_paints[name]['first_paint_ms']:.1f}",
            flush=True,
        )

    comparable_cocoa = (
        app.platformName() == "cocoa"
        and not args.offscreen
        and not args.offscreen_fallback
        and all(exposed_flags.values())
        and os.environ.get("QT_QPA_PLATFORM") not in {"offscreen", "minimal"}
    )
    env = environment_info(app, canvases["fft_auto_y"])
    trajectory_full = build_pan_trajectory(n_events)
    trajectory_warm = build_pan_trajectory(warmup_events)

    results = []
    profile_dir = args.output_dir if args.mode == "profile" else None

    for input_mode in input_modes_for(args):
        for hz in rates_for(args, input_mode):
            print(f"=== {input_mode} {hz} Hz rounds={rounds} events={n_events} ===", flush=True)
            for round_i in range(rounds):
                for name, kind, y_auto in scenario_order():
                    canvas = canvases[name]
                    canvas.show()
                    canvas.raise_()
                    restore_view(kind, canvas, y_auto=y_auto)
                    settle(app, 80)
                    if round_i == 0:
                        print(f"  warmup {name} {input_mode} {hz}Hz", flush=True)
                        ProbeFlags.counters.reset()
                        run_event_batch(
                            app, kind=kind, canvas=canvas, input_mode=input_mode,
                            hz=hz, n_events=warmup_events, trajectory=trajectory_warm,
                        )
                        restore_view(kind, canvas, y_auto=y_auto)
                        settle(app, SETTLE_MS)
                    print(f"  round {round_i + 1}/{rounds} {name} {input_mode} {hz}Hz", flush=True)
                    ProbeFlags.counters.reset()
                    profiler = None
                    if args.mode == "profile":
                        profiler = cProfile.Profile()
                        profiler.enable()
                    batch = run_event_batch(
                        app, kind=kind, canvas=canvas, input_mode=input_mode,
                        hz=hz, n_events=n_events, trajectory=trajectory_full,
                    )
                    counts = ProbeFlags.counters.snapshot()
                    if profiler is not None:
                        profiler.disable()
                        dump_name = f"{name}-{hz}hz-{input_mode}-r{round_i + 1}"
                        dump_path = Path(profile_dir) / f"{dump_name}.prof"
                        txt_path = Path(profile_dir) / f"{dump_name}.txt"
                        profiler.dump_stats(str(dump_path))
                        buf = io.StringIO()
                        pstats.Stats(profiler, stream=buf).sort_stats("cumtime").print_stats(40)
                        txt_path.write_text(buf.getvalue(), encoding="utf-8")
                    results.append({
                        "scenario": name,
                        "kind": kind,
                        "y_auto": y_auto,
                        "input_mode": input_mode,
                        "target_hz": hz,
                        "round": round_i + 1,
                        "counts": counts,
                        "batch": batch,
                        "profile_dump": (
                            str(dump_path) if args.mode == "profile" else None
                        ),
                    })
                    restore_view(kind, canvas, y_auto=y_auto)
                    settle(app, 40)

    grouped = []
    for input_mode in input_modes_for(args):
        for hz in rates_for(args, input_mode):
            for name, kind, y_auto in scenario_order():
                rows = [
                    row for row in results
                    if row["scenario"] == name
                    and row["input_mode"] == input_mode
                    and row["target_hz"] == hz
                ]
                samples = [s for row in rows for s in row["batch"]["samples"]]
                settles = [row["batch"]["settle_ms"] for row in rows]
                xlim_changed = [row["batch"]["xlim_changed"] for row in rows]
                grouped.append({
                    "name": name,
                    "kind": kind,
                    "y_auto": y_auto,
                    "input_mode": input_mode,
                    "target_hz": hz,
                    "rounds": len(rows),
                    "events_per_round": n_events,
                    "warmup_events": warmup_events,
                    "plot_geometry": geometries[name],
                    "first_paint": first_paints[name],
                    "exposed": exposed_flags[name],
                    "xlim_changed_per_round": xlim_changed,
                    "timed_events": {
                        **summarize_samples(samples, settles),
                        "raw_samples": samples,
                    },
                    "counts": {
                        key: sum(row["counts"][key] for row in rows)
                        for key in rows[0]["counts"]
                        if key != "count_window"
                    } | {"count_window": "timed_events_only_summed_over_rounds"},
                    "per_round_counts": [row["counts"] for row in rows],
                    "per_round_xlim": [
                        {
                            "before": row["batch"]["xlim_before"],
                            "after": row["batch"]["xlim_after"],
                        }
                        for row in rows
                    ],
                    "profile_dumps": [row["profile_dump"] for row in rows],
                })

    extra_payload = {
        "correctness": None,
        "invalidation": None,
        "resize_foreign": None,
        "contrast": None,
        "mainwindow": None,
        "screenshots": [],
        "rss_peak": rss_bytes(),
    }
    extra_canvas = None
    extra_x, extra_y, extra_meta = None, None, None
    extra_first = None
    extra_exposed = None
    extra_geom = None
    extra_results = []
    if args.mode == "perf" and not args.skip_extra:
        extra_x, extra_y, extra_meta = make_correctness_xy()
        extra_canvas = create_canvas("fft", width, height)
        extra_canvas.show()
        extra_canvas.raise_()
        app.processEvents()
        extra_exposed = wait_exposed(app, extra_canvas)
        extra_first = plot_canvas(
            app, "fft", extra_canvas, extra_x, extra_y,
            y_auto=True, xlim=NARROW_XLIM,
        )
        settle(app, SETTLE_MS)
        extra_geom = viewbox_geometry(extra_canvas, active_viewbox("fft", extra_canvas))
        print(
            f"ready extra fft exposed={extra_exposed} first_paint_ms="
            f"{extra_first['first_paint_ms']:.1f}",
            flush=True,
        )
        extra_rounds = 1 if args.quick else rounds
        extra_events = n_events
        extra_warmup = min(12, extra_events)
        for spec in extra_scenario_specs(args):
            traj_full = trajectory_for(spec, extra_events)
            traj_warm = trajectory_for(spec, extra_warmup)
            xlim = spec["xlim"]
            fire_mode = "gui_event" if spec["input_mode"] != "direct_viewbox" else "direct_viewbox"
            extra_rates = [60] if args.quick else [60, 120]
            for hz in extra_rates:
                print(
                    f"=== extra {spec['name']} {spec['input_mode']} {hz}Hz ===",
                    flush=True,
                )
                for round_i in range(extra_rounds):
                    extra_canvas.show()
                    extra_canvas.raise_()
                    restore_view("fft", extra_canvas, y_auto=True, xlim=xlim)
                    settle(app, 80)
                    if round_i == 0:
                        ProbeFlags.counters.reset()
                        run_event_batch(
                            app, kind="fft", canvas=extra_canvas,
                            input_mode=fire_mode, hz=hz,
                            n_events=extra_warmup, trajectory=traj_warm,
                        )
                        restore_view("fft", extra_canvas, y_auto=True, xlim=xlim)
                        settle(app, SETTLE_MS)
                    print(
                        f"  extra round {round_i + 1}/{extra_rounds} "
                        f"{spec['name']} {hz}Hz",
                        flush=True,
                    )
                    ProbeFlags.counters.reset()
                    batch = run_event_batch(
                        app, kind="fft", canvas=extra_canvas,
                        input_mode=fire_mode, hz=hz,
                        n_events=extra_events, trajectory=traj_full,
                    )
                    extra_canvas.flush_pending_spectrum_display()
                    _tx, ty = curve_xy(extra_canvas)
                    extra_results.append({
                        "scenario": spec["name"],
                        "kind": "fft",
                        "y_auto": True,
                        "input_mode": spec["input_mode"],
                        "target_hz": hz,
                        "round": round_i + 1,
                        "counts": ProbeFlags.counters.snapshot(),
                        "batch": batch,
                        "profile_dump": None,
                        "peak_present": peak_present(ty),
                    })
                    restore_view("fft", extra_canvas, y_auto=True, xlim=xlim)
                    settle(app, 40)
        for spec in extra_scenario_specs(args):
            extra_rates = [60] if args.quick else [60, 120]
            for hz in extra_rates:
                rows = [
                    row for row in extra_results
                    if row["scenario"] == spec["name"]
                    and row["input_mode"] == spec["input_mode"]
                    and row["target_hz"] == hz
                ]
                if not rows:
                    continue
                grouped.append(group_scenario_rows(
                    rows, name=spec["name"], kind="fft", y_auto=True,
                    input_mode=spec["input_mode"], hz=hz,
                    n_events=extra_events, warmup_events=extra_warmup,
                    geometry=extra_geom, first_paint=extra_first,
                    exposed=bool(extra_exposed),
                ))
        try:
            extra_payload["correctness"] = run_correctness_snapshot(
                app, extra_canvas, extra_x, extra_y, extra_meta,
                output_dir=args.output_dir,
            )
            extra_payload["screenshots"] = extra_payload["correctness"].get("screenshots", [])
        except Exception:
            extra_payload["correctness_error"] = traceback.format_exc()
        try:
            extra_payload["invalidation"] = run_revision_invalidation(
                app, extra_canvas, extra_x, extra_y,
            )
        except Exception:
            extra_payload["invalidation_error"] = traceback.format_exc()
        try:
            extra_payload["resize_foreign"] = run_resize_and_foreign(
                app, extra_canvas, width=width, height=height,
            )
        except Exception:
            extra_payload["resize_foreign_error"] = traceback.format_exc()
        extra_payload["rss_peak"] = rss_bytes()

    if extra_canvas is not None:
        extra_canvas.hide()
        extra_canvas.close()
        extra_canvas.deleteLater()

    for canvas in canvases.values():
        canvas.hide()
        canvas.close()
        canvas.deleteLater()
    from PyQt5.QtCore import QEvent, QCoreApplication
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()

    if args.mode == "perf" and not args.skip_extra and not args.quick:
        contrast_events = min(40, n_events)
        try:
            extra_payload["contrast"] = run_contrast(
                app, width=width, height=height,
                n_events=contrast_events, hz=60,
                output_dir=args.output_dir,
            )
        except Exception:
            extra_payload["contrast_error"] = traceback.format_exc()
        extra_payload["rss_peak"] = rss_bytes()

    if args.mainwindow and args.mode == "perf":
        mw_events = 20 if args.quick else min(60, n_events)
        try:
            extra_payload["mainwindow"] = run_mainwindow_probe(
                app, x, y, width=width, height=height,
                n_events=mw_events, hz=60,
                output_dir=args.output_dir,
            )
        except Exception:
            extra_payload["mainwindow"] = {
                "error": traceback.format_exc(),
                "limitation": "MainWindow probe raised before construction completed.",
            }
        extra_payload["rss_peak"] = rss_bytes()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "probe": "probe_spectrum_interaction",
        "mode": args.mode,
        "profiler_enabled": args.mode == "profile",
        "comparable": args.mode == "perf",
        "comparable_cocoa": bool(comparable_cocoa) and args.mode == "perf",
        "qt_platform": app.platformName(),
        "offscreen_fallback": bool(args.offscreen_fallback or os.environ.get(
            "SPECTRUM_PROBE_OFFSCREEN_FALLBACK",
        )),
        "qsettings_ini": str(settings_dir / "qsettings.ini"),
        "head": fingerprint["head"],
        "fingerprint": fingerprint,
        "environment": env,
        "rss_peak": extra_payload.get("rss_peak"),
        "data": {
            "n_samples": SOURCE_N,
            "n_curves": N_CURVES,
            "x_min": 0.0,
            "x_max": DATA_X_MAX_HZ,
            "xlim": list(XLIM),
            "narrow_xlim": list(NARROW_XLIM),
            "y_manual": list(Y_MANUAL),
            "formula": "y = 60*exp(-x/80)-x/400+5*sin(x/150)+sin(x*5); overlay y-i",
            "historical_probe": ".state/fft-drag-analysis/probe.py",
        },
        "event_trajectory": {
            "description": (
                "GUI: left-press, 1px X moves, release, then Ctrl+wheel in/out. "
                "direct_viewbox: FakeDrag press/move/release only; wheel specs are no-ops."
            ),
            "events": trajectory_full,
            "cadence_note": (
                "Events are scheduled on QTimer PreciseTimer against monotonic t0+"
                "i/hz. Late events fire immediately (delay 0) and record lag_ms. "
                "FPS is not inferred from tight-loop duration."
            ),
        },
        "counting_definitions": COUNTING_DEFINITIONS,
        "quick": bool(args.quick),
        "widget_requested_px": [width, height],
        "scenarios": grouped,
        "t4_extra": extra_payload,
        "warnings": _warnings(grouped, comparable_cocoa, args),
    }
    return payload


def _warnings(grouped, comparable_cocoa, args) -> list[str]:
    warnings = []
    if args.mode == "profile":
        warnings.append("profile timings are not comparable; use perf JSON for p50/p95")
    if not comparable_cocoa:
        warnings.append("comparable_cocoa is false; do not treat this as a Cocoa baseline")
    for row in grouped:
        if row["input_mode"] == "direct_viewbox":
            warnings.append(
                f"{row['name']} {row['target_hz']}Hz uses input_mode=direct_viewbox "
                "and must not be mixed with gui_event stats"
            )
        if row["input_mode"] in {"gui_event", "xlim_step"} and not any(row["xlim_changed_per_round"]):
            warnings.append(f"{row['name']} {row['target_hz']}Hz pan did not change xlim")
    return warnings


def main(argv=None) -> int:
    args = _arguments(argv)
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / f"{args.mode}.log"
    started = time.perf_counter()
    try:
        payload = run_probe(args)
    except SystemExit:
        raise
    except Exception:
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc(), file=sys.stderr)
        return 1
    payload["wall_s"] = time.perf_counter() - started
    out_json = args.output_dir / f"{args.mode}.json"
    _write_json(out_json, payload)
    slim = dict(payload)
    slim_scenarios = []
    for row in payload["scenarios"]:
        copy = dict(row)
        timed = dict(copy["timed_events"])
        timed.pop("raw_samples", None)
        copy["timed_events"] = timed
        slim_scenarios.append(copy)
    slim["scenarios"] = slim_scenarios
    _write_json(args.output_dir / f"{args.mode}-summary.json", slim)
    print(f"wrote {out_json}", flush=True)
    print(f"qt_platform={payload['qt_platform']} comparable_cocoa={payload['comparable_cocoa']}", flush=True)
    for row in payload["scenarios"]:
        both = row["timed_events"]["callback_plus_paint"]
        print(
            f"{row['name']:14s} {row['input_mode']:16s} {row['target_hz']:3d}Hz "
            f"p50={both['p50_ms']:.2f} p95={both['p95_ms']:.2f} "
            f"setData={row['counts']['setData_count']} "
            f"fullScan={row['counts']['full_array_scan_count']} "
            f"yFitCb={row['counts']['y_fit_in_callback']} "
            f"yFitTimer={row['counts']['y_fit_in_timer']} "
            f"cacheHit={row['counts'].get('cache_hit_count', 0)} "
            f"rebuild={row['counts'].get('cache_rebuild_count', 0)}",
            flush=True,
        )
    extra = payload.get("t4_extra") or {}
    correctness = extra.get("correctness") or {}
    if correctness:
        print(
            f"correctness pass={correctness.get('pass')} "
            f"valley={((correctness.get('after_pan_flush') or {}).get('ylim_covers_valley'))} "
            f"peak={((correctness.get('after_pan_flush') or {}).get('peak_in_trace'))} "
            f"nan={((correctness.get('after_pan_flush') or {}).get('nan_break_in_polyline'))}",
            flush=True,
        )
    mw = extra.get("mainwindow")
    if mw:
        print(
            f"mainwindow constructed={mw.get('constructed')} plotted={mw.get('plotted')} "
            f"mislabeled={mw.get('auto_y_mislabeled_manual')}",
            flush=True,
        )
    log_path.write_text(
        f"exit=0 wall_s={payload['wall_s']:.1f} json={out_json}\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
