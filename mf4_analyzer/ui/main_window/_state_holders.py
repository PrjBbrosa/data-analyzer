"""Named owners for MainWindow state that used to be written from several files.

Each holder is a plain dataclass hung off ``MainWindow`` once.  The window keeps
property shims under the historical attribute names so reads (including the
``getattr(window, "_custom_xaxis_ch", None)`` style used by ``view_bridge`` and
by tests that build fake windows) keep working unchanged -- only the *writes*
move onto the holder.

Why that split: several tests bind real ``MainWindow`` methods onto
``SimpleNamespace`` fakes carrying bare attributes (see
``docs/analyzer/verify/main-window-state-inventory.md`` §4).  Rewriting reads
would break those fakes, and one of them drives ``_plot_time_on_canvas`` --
time-domain plotting, which spec D-E3 puts out of scope for this package.
"""

from __future__ import annotations

from dataclasses import astuple, dataclass, field, replace
from typing import Any

from ..time_xaxis import EXACT_SOURCE, CustomXAxisSpec

# Distinguishes "leave the label alone" from "set the label to None", which are
# different operations at the call sites (mirrors _sentinel._INSPECTOR_TIME_RANGE).
KEEP = object()


@dataclass
class CustomXAxisState:
    """The applied custom-X axis selection.

    ``spec`` is authoritative.  ``fid`` / ``ch`` are legacy *exact-source
    adapters* retained for callers that predate the spec, and they are strictly
    derived from it -- keeping that derivation inside this class is the point of
    the holder, since it used to be re-implemented at each of the four write
    sites across two files.
    """

    spec: CustomXAxisSpec = field(default_factory=CustomXAxisSpec)
    fid: str | None = None
    ch: str | None = None
    xlabel: str | None = None

    def clear(self) -> None:
        """Reset to the default time axis."""
        self.spec = CustomXAxisSpec()
        self.fid = None
        self.ch = None
        self.xlabel = None

    def adopt(self, spec: CustomXAxisSpec, *, xlabel=KEEP) -> None:
        """Apply ``spec`` and re-derive the legacy exact-source adapters.

        Only an ``exact_source`` spec carries a concrete ``(fid, channel)``
        pair; a ``per_source_name`` spec resolves per file at draw time, so its
        adapters must be cleared or a stale source would leak into the payload
        builder.

        ``xlabel`` defaults to :data:`KEEP` -- omit it to leave the label
        alone, pass ``None`` to clear it.
        """
        self.spec = spec
        exact = spec.resolver == EXACT_SOURCE
        self.fid = spec.source_fid if exact else None
        self.ch = spec.channel if exact else None
        if xlabel is not KEEP:
            self.xlabel = xlabel


@dataclass
class ViewFocusState:
    """Which time-domain Views are bound to the two panes, and which has focus.

    ``primary`` / ``secondary`` mirror ``view_manager.active`` /
    ``view_manager.split_with``; they are re-derived by :meth:`bind` whenever
    the manager changes.  ``focused`` is the one piece that is *not* derivable
    -- it records which of the two bound panes the user last selected -- and it
    is constrained to stay on a bound pane.
    """

    primary: int | None = None
    secondary: int | None = None
    focused: int | None = None

    def bind(self, *, active: int | None, partner: int | None) -> None:
        """Mirror the manager's active/split pair, keeping focus on a bound pane.

        Focus is preserved across a re-bind when it still points at one of the
        two panes; otherwise it falls back to the active View, so focus can
        never strand on a pane that is no longer displayed.
        """
        self.primary = active
        self.secondary = partner
        if partner is None or self.focused not in (active, partner):
            self.focused = active


@dataclass
class TimeRenderGate:
    """Re-entrancy gate for the time-domain render pipeline.

    ``depth`` > 0 means a time plot / View projection is running on the GUI
    thread.  That window is *not* atomic: ``_begin_compute_progress`` pumps the
    Qt event loop so the status-bar bar reaches the screen, and any 0 ms
    ``QTimer`` already posted (UltraView's ``navigate_to_view``) is delivered
    inside that pump.  A View switch that executes there re-enters
    ``_render_view_to_canvas`` on the same canvas: the outer render then
    finishes on top of the inner one, so the tab highlight, the navigator
    projection and the painted curves end up describing three different Views,
    and the next capture writes that mixture back into ViewState.

    The gate makes the pipeline serial instead: a switch intent that arrives
    while ``busy`` is parked in ``pending_view_id`` (by *view id*, so a
    concurrent delete/reorder cannot redirect it at a stale index) and replayed
    once the outermost render has unwound.  Only the LAST intent survives --
    rapid tab clicking means "take me to the one I stopped on".

    Owned by ``MainWindow`` (assigned once in ``window.py``); mixins mutate it
    through these methods so the state-ownership ratchet sees no new
    multi-file bare attribute.
    """

    depth: int = 0
    pending_view_id: str | None = None
    drain_scheduled: bool = False
    pending_section_view: object | None = None
    section_entry_scheduled: bool = False

    @property
    def busy(self) -> bool:
        return self.depth > 0

    def enter(self) -> None:
        self.depth += 1

    def leave(self) -> None:
        self.depth = max(0, self.depth - 1)

    def defer_switch(self, view_id) -> None:
        """Park a switch intent; a later intent supersedes an earlier one."""
        self.pending_view_id = None if view_id is None else str(view_id)

    def clear_pending_switch(self) -> None:
        self.pending_view_id = None

    def take_pending_switch(self) -> str | None:
        view_id = self.pending_view_id
        self.pending_view_id = None
        return view_id


@dataclass
class AnalysisPinBook:
    """Per-pane set of real analysis-cache keys currently bound to a View.

    Owned exclusively by ``MainWindow`` (assigned once in ``window.py``). Mixin
    helpers mutate through methods so the state-ownership ratchet sees no
    multi-file bare ``self._analysis_pins[...]`` writes.
    """

    _slots: dict = field(default_factory=dict)

    def pinned_keys(self, section: str) -> frozenset:
        pinned = set()
        for (sec, _view_id, _pane_idx), keys in self._slots.items():
            if sec == section:
                pinned.update(keys)
        return frozenset(pinned)

    def add(self, section, view_id, pane_idx, key) -> None:
        slot = (section, str(view_id), int(pane_idx))
        self._slots.setdefault(slot, set()).add(key)

    def replace(self, section, view_id, pane_idx, keys) -> None:
        slot = (section, str(view_id), int(pane_idx))
        key_set = set(keys)
        if key_set:
            self._slots[slot] = key_set
        else:
            self._slots.pop(slot, None)

    def drop_view(self, section, view_id) -> None:
        view_id = str(view_id)
        for slot in [
            key for key in self._slots
            if key[0] == section and key[1] == view_id
        ]:
            del self._slots[slot]

    def clear_section(self, section) -> None:
        for slot in [key for key in self._slots if key[0] == section]:
            del self._slots[slot]

    def __contains__(self, slot) -> bool:
        return slot in self._slots

    def __getitem__(self, slot):
        return self._slots[slot]


@dataclass
class ProjectFileRestoreResult:
    """Structured outcome of remapping ``.tlproj`` file refs onto freshly loaded fids."""

    fid_map: dict = field(default_factory=dict)
    missing_paths: list[str] = field(default_factory=list)
    missing_old_fids: list[str] = field(default_factory=list)
    timebase_notices: list[str] = field(default_factory=list)


@dataclass
class ProjectRestoreHealth:
    """Session-local health of the last project restore (Stage 1 degraded-save guard).

    Mutations stay on this holder so ``MainWindow`` does not grow another
    multi-file bare attribute write cluster.
    """

    missing_paths: list[str] = field(default_factory=list)
    missing_old_fids: list[str] = field(default_factory=list)
    dropped_time_refs: list[Any] = field(default_factory=list)
    # (section, view_id, pane_idx, role)
    dropped_analysis_refs: list[tuple] = field(default_factory=list)
    timebase_notices: list[str] = field(default_factory=list)
    degraded: bool = False

    def clear(self) -> None:
        self.missing_paths.clear()
        self.missing_old_fids.clear()
        self.dropped_time_refs.clear()
        self.dropped_analysis_refs.clear()
        self.timebase_notices.clear()
        self.degraded = False

    def adopt_restore(
        self,
        *,
        missing_paths,
        missing_old_fids,
        dropped_time_refs=(),
        dropped_analysis_refs=(),
        timebase_notices=(),
    ) -> None:
        """Replace health from one restore pass and set ``degraded`` accordingly.

        Time-base notices are reported, but they are not missing-file
        degradation: the project file is left unchanged and ranges are not
        rescaled.
        """
        self.missing_paths = list(missing_paths or ())
        self.missing_old_fids = list(missing_old_fids or ())
        self.dropped_time_refs = list(dropped_time_refs or ())
        self.dropped_analysis_refs = list(dropped_analysis_refs or ())
        self.timebase_notices = list(timebase_notices or ())
        self.degraded = bool(
            self.missing_paths
            or self.missing_old_fids
            or self.dropped_time_refs
            or self.dropped_analysis_refs
        )


def optional_float(value) -> float | None:
    """Finite float, or ``None`` when the value cannot be one.

    NaN and infinities are ``None`` so a signature compares equal to itself.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def optional_float_pair(value) -> tuple[float, float] | None:
    if value is None:
        return None
    try:
        lo, hi = value
    except (TypeError, ValueError):
        return None
    lo_f = optional_float(lo)
    hi_f = optional_float(hi)
    if lo_f is None or hi_f is None:
        return None
    return (lo_f, hi_f)


def composite_source_id(source) -> tuple[str, str] | None:
    """``(fid, channel)`` identity. Display names are not part of the key."""
    if not isinstance(source, (tuple, list)) or len(source) != 2:
        return None
    fid, channel = source
    if fid is None or channel is None:
        return None
    return (str(fid), str(channel))


def widget_raster_metrics(widget) -> tuple[int, int, float]:
    """``(width, height, device-pixel-ratio)`` when the widget exposes them."""
    width = _call_int(getattr(widget, "width", None))
    height = _call_int(getattr(widget, "height", None))
    dpr = 1.0
    dpr_fn = getattr(widget, "devicePixelRatioF", None)
    if callable(dpr_fn):
        number = optional_float(dpr_fn())
        if number is not None and number > 0.0:
            dpr = number
    return width, height, dpr


def _call_int(fn) -> int:
    if not callable(fn):
        return 0
    try:
        return int(fn())
    except (TypeError, ValueError):
        return 0


def heatmap_slice_snapshot(canvas) -> tuple[str | None, float | None, float | None]:
    direction = getattr(canvas, "_slice_dir", None)
    if direction is not None:
        direction = str(direction)
    return (
        direction,
        optional_float(getattr(canvas, "_slice_x_val", None)),
        optional_float(getattr(canvas, "_slice_y_val", None)),
    )


def canvas_previous_db_reference(canvas) -> float | None:
    if not hasattr(canvas, "_last_db_reference"):
        return None
    return optional_float(canvas._last_db_reference)


def heatmap_result_identity(result) -> tuple:
    """``(epoch, id)``. Epoch is stamped when a result is stored; id alone is not reused as a generation."""
    epoch = getattr(result, "_heatmap_reveal_epoch", None)
    if not isinstance(epoch, int):
        epoch = None
    return (epoch, id(result))


def heatmap_render_signature(inputs, result_identity: tuple) -> tuple:
    """Stable signature: every input field, then result identity/generation."""
    return (astuple(inputs), result_identity)


def heatmap_level_writeback_blocks_retain(inputs) -> bool:
    """True when a paint would rewrite the Inspector Z spins.

    Section entry applies the saved View params before this check. Skipping
    the plot in that window must not leave the spins on the saved values
    while the canvas shows a shifted or auto window.
    """
    if inputs.amplitude_mode != "amplitude_db":
        return False
    if inputs.z_auto:
        return True
    previous = inputs.previous_db_reference
    if previous is None:
        return False
    return previous != inputs.db_value


def finish_heatmap_render_inputs(inputs, canvas):
    """Snapshot the canvas fields a later entry will read back.

    Seeding the slice and stamping the dB reference happen during paint and
    are not reset when the View's params are applied on the next entry.
    """
    direction, slice_x, slice_y = heatmap_slice_snapshot(canvas)
    previous = inputs.previous_db_reference
    if hasattr(canvas, "_last_db_reference"):
        previous = canvas_previous_db_reference(canvas)
    return replace(
        inputs,
        slice_dir=direction,
        slice_x=slice_x,
        slice_y=slice_y,
        previous_db_reference=previous,
    )


@dataclass(frozen=True)
class OrderHeatmapRenderInputs:
    """Display inputs ``_paint_order_heatmap`` reads. No widgets or diagnostics."""

    signal_title: str
    order_resolution_text: str
    amplitude_mode: str
    weighting: str
    db_reference_mode: str
    db_value: float
    db_unit: str
    db_quantity: str
    db_source: str
    db_warning: str
    z_auto: bool
    z_floor: float
    z_ceiling: float
    x_auto: bool
    x_min: float
    x_max: float
    y_auto: bool
    y_min: float
    y_max: float
    cmap: str
    interp: str
    tick_x: int
    tick_y: int
    source_id: tuple[str, str] | None
    x_origin: str
    y_origin: str
    x_lim: tuple[float, float] | None
    y_lim: tuple[float, float] | None
    slice_dir: str | None
    slice_x: float | None
    slice_y: float | None
    seed_slice: bool
    canvas_width: int
    canvas_height: int
    canvas_dpr: float
    previous_db_reference: float | None
    x_extent: tuple[float, float]
    y_extent: tuple[float, float]

    def signature_tuple(self) -> tuple:
        return astuple(self)


@dataclass(frozen=True)
class FftTimeHeatmapRenderInputs:
    """Display inputs ``_paint_fft_time_heatmap`` reads. No widgets or diagnostics."""

    amplitude_mode: str
    weighting: str
    db_reference_mode: str
    db_value: float
    db_unit: str
    db_quantity: str
    db_source: str
    db_warning: str
    z_auto: bool
    z_floor: float
    z_ceiling: float
    x_auto: bool
    x_min: float
    x_max: float
    y_auto: bool
    y_min: float
    y_max: float
    freq_range: tuple[float, float] | None
    cmap: str
    interp: str
    tick_x: int
    tick_y: int
    source_id: tuple[str, str] | None
    x_origin: str
    y_origin: str
    x_lim: tuple[float, float] | None
    y_lim: tuple[float, float] | None
    slice_dir: str | None
    slice_x: float | None
    slice_y: float | None
    seed_slice: bool
    canvas_width: int
    canvas_height: int
    canvas_dpr: float
    previous_db_reference: float | None
    time_extent: tuple[float, float] | None
    frequency_extent: tuple[float, float] | None
    channel_name: str
    channel_unit: str

    def signature_tuple(self) -> tuple:
        return astuple(self)


@dataclass
class HeatmapRevealBook:
    """Last painted order / FFT-vs-Time signature for each live canvas.

    Constructed once. Signature slots start empty (``None`` when missing),
    which means "do not retain". Epochs start at 0 and only increase.
    """

    _epoch: int = 0
    _signatures: dict = field(default_factory=dict)

    def bump_result(self, result) -> tuple:
        """New generation for a stored result. Clears any previous epoch on it."""
        self._epoch += 1
        try:
            result._heatmap_reveal_epoch = self._epoch
        except (AttributeError, TypeError):
            pass
        return heatmap_result_identity(result)

    def result_identity(self, result) -> tuple:
        return heatmap_result_identity(result)

    def remember(self, section: str, canvas, signature: tuple) -> None:
        self._signatures[(str(section), id(canvas))] = signature

    def signature_for(self, section: str, canvas):
        return self._signatures.get((str(section), id(canvas)))

    def forget_canvas(self, canvas) -> None:
        canvas_id = id(canvas)
        for key in [key for key in self._signatures if key[1] == canvas_id]:
            del self._signatures[key]

    def forget_id(self, section: str, canvas_id: int) -> None:
        self._signatures.pop((str(section), int(canvas_id)), None)

    def forget_section(self, section: str) -> None:
        section = str(section)
        for key in [key for key in self._signatures if key[0] == section]:
            del self._signatures[key]

    def keeps(self, section: str, canvas, signature: tuple, identity: tuple) -> bool:
        if self.signature_for(section, canvas) != signature:
            return False
        if getattr(canvas, "_tracelab_heatmap_picture", None) != (str(section), identity):
            return False
        has = getattr(canvas, "has_result", None)
        if not callable(has):
            return False
        try:
            return bool(has())
        except RuntimeError:
            return False
