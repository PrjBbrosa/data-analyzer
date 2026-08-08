"""Cross-section analysis helpers as an explicit collaborator (spec D-E1).

``AnalysisMixin`` is not really a mixin: FFT / Order / FFT-vs-Time call into it
through ``self.`` dozens of times, so it is a *service layer* that happens to be
wired by method-resolution order.  The cost is that its logic -- time-range
masking, section routing, dB-reference resolution -- can only be reached by
constructing an entire ``MainWindow``.

``AnalysisContext`` takes the part of that service which is a pure function of
a few named collaborators and gives it a real object with real constructor
arguments.  ``AnalysisMixin`` keeps every method name and delegates in one
line, so the MRO is untouched and the three calling mixins change not at all.

Modelled on ``fft_time_coordinator.FftTimeCoordinator``, the directory's
existing example of the shape we want.

What deliberately stays on the mixin
------------------------------------
``_analysis_cache_key`` and ``_capture_active_analysis_view`` are *orchestrators*
over algorithms owned by the section mixins (``_fft_analysis_cache_key``,
``_order_effective_params_for_source``, ``_capture_analysis_sources``, ...).
Moving them would mean injecting a dozen window-bound callables, which is the
"inject the whole window" non-solution the design explicitly rules out.  They
also depend on ordinary ``self.`` dispatch so that narrow test stubs can
override one step -- ``tests/ui/test_task4_cache_invalidation.py`` builds a
``FFTTimeMixin + AnalysisMixin`` subclass and overrides
``_pane_time_range_for``.  Both stay put, and the reasoning is recorded in
``docs/analyzer/verify/main-window-state-inventory.md``.
"""

from __future__ import annotations

import numpy as np

from ... import db_reference


class AnalysisContext:
    """Section-aware analysis helpers over an explicit set of collaborators.

    Parameters
    ----------
    inspector:
        Supplies the per-section parameter contexts (``fft_ctx`` /
        ``fft_time_ctx`` / ``order_ctx``).
    chart_stack:
        Supplies the per-section pages (``page_fft`` / ``page_fft_time`` /
        ``page_order``).
    analysis_managers:
        Section -> view manager, for the active view's pane time ranges.
    db_reference_store:
        The single shared dB-reference settings store.
    files_provider:
        Zero-argument callable returning the current ``fid -> FileData``
        mapping.  A callable rather than the mapping itself because the
        window's ``files`` attribute is *rebound* (project close/open, and
        several tests do ``win.files = {}``), so a captured reference would go
        stale.
    """

    def __init__(
        self,
        *,
        inspector,
        chart_stack,
        analysis_managers,
        db_reference_store,
        files_provider,
    ):
        self._inspector = inspector
        self._chart_stack = chart_stack
        self._analysis_managers = analysis_managers
        self._db_reference_store = db_reference_store
        self._files_provider = files_provider

    # -- section routing ----------------------------------------------------

    def section_ctx(self, section):
        """The inspector parameter context driving ``section``."""
        return {
            'fft': self._inspector.fft_ctx,
            'fft_time': self._inspector.fft_time_ctx,
            'frf': self._inspector.frf_ctx,
            'order': self._inspector.order_ctx,
        }[section]

    def page(self, section):
        """The chart-stack page rendering ``section``."""
        return {
            'fft': self._chart_stack.page_fft,
            'fft_time': self._chart_stack.page_fft_time,
            'frf': self._chart_stack.page_frf,
            'order': self._chart_stack.page_order,
        }[section]

    # -- time ranges --------------------------------------------------------

    @staticmethod
    def section_uses_time_range(section):
        return section in {"fft", "fft_time", "frf", "order"}

    @staticmethod
    def normalize_time_range(value):
        """Coerce a stored/edited span to ``(lo, hi)`` or ``None``.

        Empty, inverted, non-finite and unparseable spans all collapse to
        ``None`` so every caller gets one "no range" representation.
        """
        if not value:
            return None
        try:
            lo = float(value[0])
            hi = float(value[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        return (lo, hi)

    def mask_time_range(self, t, *arrays, time_range=None):
        """Clip ``t`` and each companion array to ``time_range``, inclusive.

        An unusable range (or absent time base) passes everything through
        untouched, so callers can apply this unconditionally.
        """
        rng = self.normalize_time_range(time_range)
        if rng is None or t is None:
            return (t, *arrays)
        lo, hi = rng
        mask = (t >= lo) & (t <= hi)
        masked = [arr[mask] for arr in arrays]
        return (t[mask], *masked)

    def pane_time_range_for(self, section, pane_idx=None):
        """The active view's time range for one pane of ``section``.

        ``pane_idx=None`` means the focused pane.
        """
        if not self.section_uses_time_range(section):
            return None
        mgr = self._analysis_managers[section]
        state = mgr.get(mgr.active)
        if pane_idx is None:
            pane_idx = self.page(section).focused_index()
        if not (0 <= int(pane_idx) < len(state.panes)):
            return None
        return self.normalize_time_range(state.panes[int(pane_idx)].time_range)

    # -- dB reference -------------------------------------------------------

    def channel_reference_facts(self, fid, ch):
        """Build :class:`~mf4_analyzer.db_reference.ChannelReferenceFacts` for
        one ``(fid, ch)``, reading ONLY ``FileData`` metadata -- never a sample
        array (docs/lessons-learned/signal-processing/2026-06-22-head-
        calibration-is-metadata-not-sample-gain.md).  Missing/unknown
        ``(fid, ch)`` and malformed metadata both degrade to empty/unvalidated
        facts rather than raising -- the resolver (spec §7 R3) is responsible
        for treating an invalid ``metadata_reference`` as absent and falling
        through to the catalog.
        """
        files = self._files_provider()
        fd = files.get(fid) if fid is not None else None
        if fd is None or ch is None:
            return db_reference.ChannelReferenceFacts(quantity="", unit="")
        ch_meta = (getattr(fd, "channel_metadata", None) or {}).get(ch) or {}
        unit = (
            ch_meta.get("unit")
            or (getattr(fd, "channel_units", None) or {}).get(ch, "")
            or ""
        )
        # Reverse toolchain identifier-safe unit encoding (U_ prefix, Y for /)
        # at the facts boundary so both catalog matching and the displayed unit
        # get the clean form -- e.g. U_Nm -> Nm, U_degYsec -> deg/sec, and a
        # same-encoded vibration unit mYs2 -> m/s2 re-hits the ISO catalog
        # instead of silently falling to generic. normalize_unit is untouched.
        unit = db_reference.canonicalize_source_unit(unit)
        quantity = ch_meta.get("quantity") or ""
        metadata_reference = ch_meta.get("db_reference")
        is_audio_source_fn = getattr(fd, "is_audio_source", None)
        try:
            is_audio = bool(is_audio_source_fn()) if callable(is_audio_source_fn) else False
        except Exception:
            is_audio = False
        return db_reference.ChannelReferenceFacts(
            quantity=str(quantity),
            unit=str(unit),
            metadata_reference=metadata_reference,
            is_audio_source=is_audio,
        )

    def resolve_db_reference_for_source(self, section, source):
        """Resolve ``section``'s dB reference for ONE specific ``(fid, ch)``
        source, honoring the section's CURRENT View mode (spec §15 C1 /
        plan Task 6 Step 6.2) -- unlike ``_resolve_and_apply_db_reference``
        (which only ever targets the section's single "focused" source and
        writes the result back onto the compound control), this is a PURE
        resolution with no widget side effect, so FFT's checked-channel
        overlay can call it once per (fid, ch) ENTRY -- including sources
        other than the section's focused one -- to convert/label each curve
        with its own reference rather than one global control value (Task 5's
        deferred "Auto-resolve-on-selection-change is NOT yet wired" note).

        Manual mode reuses the single View-level value for every source
        (still resolved through :func:`db_reference.resolve_db_reference` so
        an invalid manual value falls through to the same catalog chain);
        Auto mode resolves fresh per source against the live catalog
        snapshot. Both branches read the SAME snapshot/control so this and
        ``_resolve_and_apply_db_reference`` can never silently drift apart on
        the resolution rule itself.
        """
        control = self.section_ctx(section).db_reference_control
        mode = control.mode()
        facts = (
            self.channel_reference_facts(*source) if source
            else db_reference.ChannelReferenceFacts(quantity="", unit="")
        )
        snapshot = self._db_reference_store.snapshot()
        manual_value = control.editor.value() if mode == 'manual' else None
        return db_reference.resolve_db_reference(
            mode=mode,
            manual_value=manual_value,
            facts=facts,
            user_catalog=snapshot.user_catalog,
            system_catalog=snapshot.system_catalog,
            prefer_channel_metadata=snapshot.prefer_channel_metadata,
        )
