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

from dataclasses import dataclass, field

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
