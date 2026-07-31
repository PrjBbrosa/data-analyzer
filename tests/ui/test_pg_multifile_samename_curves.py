"""Regression guard: multi-file same-named channels must NOT vanish.

Root bug (S1 fix, lesson
``pyqt-ui/2026-06-24-channel-identity-vs-display-label-composite-key-dict``):

The pyqtgraph time-domain canvas keyed its per-channel storage dicts
(``channel_data`` / ``_channel_lines`` / ``_channel_data_id`` /
``_channel_is_monotonic`` / ``_last_range_key`` / ``_line_wall_state``) on the
channel's *display* name ``[short_name] ch``. ``FileData`` head-truncated the
filename to build ``short_name`` (``stem[:18]``), so two files whose names are
identical for the first >=18 characters but differ AFTER produced the SAME
display prefix. The second-bound channel then OVERWROTE the first's storage
slot; checking-all then unchecking one made a surviving curve VANISH because
its slot had been clobbered.

These tests assert on the *rendered scene*, not dict contents (CLAUDE.md
"验真机渲染"): two same-display-name channels from two different files must be
TWO DISTINCT live ``PlotDataItem`` objects (distinct ``id()`` AND distinct
amplitudes), and the survivor must stay live + visible across a
check-all -> uncheck-one sequence AND a subsequent viewport refresh (the
renderer envelope path where the per-name cache used to cross-contaminate).

The bug is multi-file-specific: single-file / distinct-name layouts never
collided. Each test builds the EXACT row shape ``window.py`` passes
(``(name, visible, t, sig, color, unit, fid)``) with a DISTINCT ``fid`` per
file and ``name = fd.get_prefixed_channel(ch)``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key


# -- fixtures / builders --------------------------------------------------


def _pg_canvas(qapp):
    """Construct + show a real TimeDomainCanvasPG (no MagicMock)."""
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _make_file(
    stem: str,
    *,
    amp: float,
    idx: int,
    offset: float = 0.0,
) -> FileData:
    """Build a minimal single-channel FileData with a known amplitude.

    The channel is named ``sig`` in every file so the prefixed display name
    collides whenever two stems share the same ``short_name`` truncation.
    ``amp`` differs per file so the rendered curves can be told apart by their
    sample values (not just by ``id()``).
    """
    n = 2_000
    t = np.linspace(0.0, 1.0, n, dtype=np.float64)
    sig = offset + amp * np.sin(2 * np.pi * 5 * t)
    df = pd.DataFrame({"time": t, "sig": sig})
    return FileData(f"{stem}.csv", df, ["time", "sig"], {"sig": "u"}, idx=idx)


def _row_for(fd: FileData, ch: str, fid: str, *, visible: bool):
    """Build the window.py row shape ``(name, visible, t, sig, color, unit, fid)``.

    ``name`` is the prefixed display name (what collides); ``fid`` is the
    DISTINCT per-file identity that the composite-key storage must use.
    """
    sig = fd.data[ch].to_numpy(copy=False).astype(float, copy=False)
    color = fd.get_color_palette()[0]
    return (
        fd.get_prefixed_channel(ch),
        visible,
        fd.time_array,
        sig,
        color,
        fd.channel_units.get(ch, ""),
        fid,
    )


def _live_pdis_for_display_name(canvas, display_name):
    """Every live PlotDataItem in the scene whose stored display label matches.

    Reads the canvas's ``_channel_lines`` by COMPOSITE iteration (so BOTH
    colliding entries are seen) and confirms each PlotDataItem is actually a
    child of a live ViewBox in the scene — i.e. it was really added, not just
    recorded in a dict.
    """
    import pyqtgraph as pg

    found = []
    for ck, name, (axis_handle, line_handle) in canvas._channel_lines.composite_items():
        if name != display_name:
            continue
        pdi = getattr(line_handle, "plot_data_item", None)
        if pdi is None:
            continue
        vb = getattr(axis_handle, "view_box", None)
        # Confirm scene membership: the PlotDataItem's scene must be the
        # canvas GraphicsView's scene (a dict entry whose item was never added
        # — the orphan symptom — fails this).
        in_scene = pdi.scene() is not None
        found.append(
            {
                "ck": ck,
                "pdi": pdi,
                "vb": vb,
                "in_scene": in_scene,
                "visible": bool(pdi.isVisible()),
            }
        )
    return found


# -- collision premise (middle-ellipsis era) ------------------------------
#
# After Task 2 the label uses a MIDDLE ellipsis, so two files differing only in
# the TAIL no longer collide. To keep exercising the storage-identity bug, the
# fixtures use two stems that share the same HEAD and the same TAIL but differ
# in the MIDDLE (the elided region) — these still collapse to one display label
# while carrying distinct file identities. The bug is about the DISPLAY-LABEL
# collision (whatever its cause); the test pins that invariant directly via
# ``get_prefixed_channel`` equality rather than a truncation-mechanism detail.

# Same head ("engine_r"), same tail ("_final_v1"), different middle.
_COLLIDE_STEM_A = "engine_run_AAAA_2026_alpha_final_v1"
_COLLIDE_STEM_B = "engine_run_BBBB_2026_alpha_final_v1"


def test_long_filenames_still_collide_on_display_label_premise():
    """Premise: two distinct files can still collapse to the SAME prefixed
    display label (now via a shared head+tail with a differing elided middle).

    If FileData's label format ever changes such that these stop colliding, the
    disappearance regression below would silently stop exercising the bug — so
    pin the premise explicitly.
    """
    fd_a = _make_file(_COLLIDE_STEM_A, amp=1000.0, idx=0)
    fd_b = _make_file(_COLLIDE_STEM_B, amp=7.0, idx=1)
    # Middle-ellipsis collapses the differing middle → same display label.
    assert "…" in fd_a.short_name, "fixture stem must be over-budget (elided)"
    assert fd_a.get_prefixed_channel("sig") == fd_b.get_prefixed_channel("sig")


class TestSameNameYFitUsesCompositeIdentity:
    """A newly-restored axis must fit from its exact file's samples."""

    @staticmethod
    def _plot_two(canvas, file_a, file_b, *, mode):
        display_a = file_a.get_prefixed_channel("sig")
        display_b = file_b.get_prefixed_channel("sig")
        canvas.plot_channels(
            [
                _row_for(file_a, "sig", "fid-A", visible=True),
                _row_for(file_b, "sig", "fid-B", visible=True),
            ],
            mode=mode,
        )
        QCoreApplication.processEvents()
        key_a = _view_state_channel_key("fid-A", display_a)
        key_b = _view_state_channel_key("fid-B", display_b)
        return display_a, display_b, key_a, key_b

    @pytest.mark.parametrize("mode", ["subplot", "overlay"])
    def test_restore_only_file_b_does_not_fit_file_a_from_same_label(
        self,
        qapp,
        mode,
    ):
        file_a = _make_file(_COLLIDE_STEM_A, amp=1.0, idx=0)
        file_b = _make_file(
            _COLLIDE_STEM_B,
            amp=50.0,
            idx=1,
            offset=150.0,
        )
        canvas = _pg_canvas(qapp)
        display_a, display_b, key_a, key_b = self._plot_two(
            canvas,
            file_a,
            file_b,
            mode=mode,
        )
        assert display_a == display_b, "fixture must exercise a display collision"

        lines = canvas._channel_view_state_lines
        lines[key_a][0].set_ylim(-1.0, 1.0)
        lines[key_b][0].set_ylim(100.0, 200.0)
        QCoreApplication.processEvents()
        before = canvas.get_visible_ylims()

        canvas.restore_visible_ylims({key_b: before[key_b]})
        QCoreApplication.processEvents()
        after = canvas.get_visible_ylims()

        assert before[key_a] == pytest.approx((-1.0, 1.0))
        assert before[key_b] == pytest.approx((100.0, 200.0))
        assert after[key_b] == pytest.approx((100.0, 200.0))
        # File A's raw range is [-1, 1]. Its fitted frame may add padding or
        # nice ticks, but it must never land in file B's [100, 200] regime.
        assert -5.0 < after[key_a][0] < -0.9
        assert 0.9 < after[key_a][1] < 5.0
        assert not (90.0 < after[key_a][0] < after[key_a][1] < 210.0)

    def test_ambiguous_display_label_fallback_fails_closed(self, qapp):
        file_a = _make_file(_COLLIDE_STEM_A, amp=1.0, idx=0)
        file_b = _make_file(
            _COLLIDE_STEM_B,
            amp=50.0,
            idx=1,
            offset=150.0,
        )
        canvas = _pg_canvas(qapp)
        display_a, display_b, key_a, _key_b = self._plot_two(
            canvas,
            file_a,
            file_b,
            mode="subplot",
        )
        assert display_a == display_b
        handle_a = canvas._channel_view_state_lines[key_a][0]
        handle_a.set_ylim(-7.0, 7.0)

        changed = canvas._fit_channel_y_to_visible_x(
            display_a,
            handle_a,
            8,
            frame_to_nice=False,
        )

        assert changed is False
        assert handle_a.get_ylim() == pytest.approx((-7.0, 7.0))

    def test_distinct_file_labels_still_fit_the_unrestored_channel(self, qapp):
        file_a = _make_file("distinct_alpha", amp=1.0, idx=0)
        file_b = _make_file(
            "distinct_beta",
            amp=50.0,
            idx=1,
            offset=150.0,
        )
        canvas = _pg_canvas(qapp)
        display_a, display_b, key_a, key_b = self._plot_two(
            canvas,
            file_a,
            file_b,
            mode="subplot",
        )
        assert display_a != display_b
        lines = canvas._channel_view_state_lines
        lines[key_a][0].set_ylim(-20.0, 20.0)
        lines[key_b][0].set_ylim(100.0, 200.0)

        canvas.restore_visible_ylims({key_b: (100.0, 200.0)})
        QCoreApplication.processEvents()

        fitted = canvas.get_visible_ylims()[key_a]
        assert -5.0 < fitted[0] < -0.9
        assert 0.9 < fitted[1] < 5.0

    def test_single_file_layout_still_fits_the_unrestored_channel(self, qapp):
        t = np.linspace(0.0, 1.0, 2_000, dtype=np.float64)
        low = np.sin(2 * np.pi * 5 * t)
        high = 150.0 + 50.0 * np.sin(2 * np.pi * 5 * t)
        low_name = "[single] low"
        high_name = "[single] high"
        rows = [
            (low_name, True, t, low, "#1769e0", "u", "fid-only"),
            (high_name, True, t, high, "#ef4444", "u", "fid-only"),
        ]
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        low_key = _view_state_channel_key("fid-only", low_name)
        high_key = _view_state_channel_key("fid-only", high_name)
        lines = canvas._channel_view_state_lines
        lines[low_key][0].set_ylim(-20.0, 20.0)
        lines[high_key][0].set_ylim(100.0, 200.0)

        canvas.restore_visible_ylims({high_key: (100.0, 200.0)})
        QCoreApplication.processEvents()

        fitted = canvas.get_visible_ylims()[low_key]
        assert -5.0 < fitted[0] < -0.9
        assert 0.9 < fitted[1] < 5.0


# -- Task 1: real-render disappearance regression -------------------------


class TestMultiFileSameNameCurvesSurvive:
    """Two files, same channel name, names that collide on ``short_name``.

    Drives the real ``plot_channels`` path and asserts on the rendered
    PlotDataItem SET + visibility, then simulates the uncheck + a viewport
    refresh and re-asserts the survivor persists.
    """

    STEM_A = _COLLIDE_STEM_A
    STEM_B = _COLLIDE_STEM_B

    def _two_files(self):
        fd_a = _make_file(self.STEM_A, amp=1000.0, idx=0)
        fd_b = _make_file(self.STEM_B, amp=7.0, idx=1)
        return fd_a, fd_b

    @pytest.mark.parametrize("mode", ["overlay", "subplot"])
    def test_both_samename_curves_present_after_check_all(self, qapp, mode):
        fd_a, fd_b = self._two_files()
        display_name = fd_a.get_prefixed_channel("sig")  # collides with fd_b's

        rows = [
            _row_for(fd_a, "sig", "fid-A", visible=True),
            _row_for(fd_b, "sig", "fid-B", visible=True),
        ]
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(rows, mode=mode)
        QCoreApplication.processEvents()

        found = _live_pdis_for_display_name(canvas, display_name)
        # ROOT assertion: BOTH same-display-name curves are present as separate
        # live PlotDataItems — pre-fix the second clobbered the first (== 1).
        assert len(found) == 2, (
            f"[{mode}] expected 2 live PlotDataItems for the colliding display "
            f"name, got {len(found)} (the orphan/clobber symptom)"
        )
        # Distinct objects (no slot sharing), both in the scene, both visible.
        ids = {id(f["pdi"]) for f in found}
        assert len(ids) == 2, f"[{mode}] the two curves must be DISTINCT objects"
        assert all(f["in_scene"] for f in found), (
            f"[{mode}] a recorded curve was never added to a live ViewBox"
        )
        assert all(f["visible"] for f in found), (
            f"[{mode}] both curves must be visible after check-all"
        )
        # Distinct composite keys (the per-(fid,name) identity).
        assert len({f["ck"] for f in found}) == 2
        # Distinct amplitudes prove they are the two DIFFERENT files' data, not
        # the same curve recorded twice.
        amps = sorted(
            float(np.nanmax(np.abs(f["pdi"].getData()[1])))
            for f in found
            if f["pdi"].getData()[1] is not None and len(f["pdi"].getData()[1])
        )
        assert len(amps) == 2 and amps[0] != pytest.approx(amps[1]), (
            f"[{mode}] curves must carry the two files' distinct amplitudes, "
            f"got {amps}"
        )

    @pytest.mark.parametrize("mode", ["overlay", "subplot"])
    def test_survivor_persists_after_uncheck_one(self, qapp, mode):
        fd_a, fd_b = self._two_files()
        display_name = fd_b.get_prefixed_channel("sig")

        # 1) Check all.
        rows_all = [
            _row_for(fd_a, "sig", "fid-A", visible=True),
            _row_for(fd_b, "sig", "fid-B", visible=True),
        ]
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(rows_all, mode=mode)
        QCoreApplication.processEvents()
        assert len(_live_pdis_for_display_name(canvas, display_name)) == 2

        # 2) Uncheck file A's channel: window.py rebuilds plot_channels with
        #    A's row removed. File B's same-named curve MUST survive — this is
        #    the curve that previously VANISHED (its slot had been clobbered by
        #    A during check-all, so removing A removed the only live slot).
        rows_b_only = [_row_for(fd_b, "sig", "fid-B", visible=True)]
        canvas.plot_channels(rows_b_only, mode=mode)
        QCoreApplication.processEvents()

        found = _live_pdis_for_display_name(canvas, display_name)
        assert len(found) == 1, (
            f"[{mode}] file B's curve vanished on uncheck-one (got {len(found)})"
        )
        survivor = found[0]
        assert survivor["in_scene"], f"[{mode}] survivor not in scene"
        assert survivor["visible"], f"[{mode}] survivor not visible"
        # It must be FILE B's data (amp 7.0), not A's (amp 1000.0).
        amp = float(np.nanmax(np.abs(survivor["pdi"].getData()[1])))
        assert amp == pytest.approx(7.0, rel=0.05), (
            f"[{mode}] survivor carries the wrong file's data (amp {amp:.3f}); "
            f"expected file B's ~7.0"
        )

    @pytest.mark.parametrize("mode", ["overlay", "subplot"])
    def test_survivor_persists_after_viewport_refresh(self, qapp, mode):
        """After uncheck-one, a viewport range change drives the renderer
        envelope path (``_refresh_visible_data``), keyed per-composite. The
        survivor must NOT be suppressed by a stale per-name cache entry left by
        the clobbered curve (the cross-contamination the composite key fixes).
        """
        fd_a, fd_b = self._two_files()
        display_name = fd_b.get_prefixed_channel("sig")

        rows_all = [
            _row_for(fd_a, "sig", "fid-A", visible=True),
            _row_for(fd_b, "sig", "fid-B", visible=True),
        ]
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(rows_all, mode=mode)
        QCoreApplication.processEvents()

        # Uncheck A.
        canvas.plot_channels(
            [_row_for(fd_b, "sig", "fid-B", visible=True)], mode=mode
        )
        QCoreApplication.processEvents()

        # Viewport refresh: zoom X to a sub-window, then flush the debounced
        # envelope refresh synchronously so the renderer hot path runs now.
        canvas.restore_visible_xlim((0.2, 0.6))
        QCoreApplication.processEvents()
        canvas._refresh_visible_data()
        QCoreApplication.processEvents()

        found = _live_pdis_for_display_name(canvas, display_name)
        assert len(found) == 1, (
            f"[{mode}] survivor lost after viewport refresh (got {len(found)})"
        )
        survivor = found[0]
        assert survivor["in_scene"] and survivor["visible"], (
            f"[{mode}] survivor not live+visible after viewport refresh"
        )
        # The envelope refresh must have produced real points in the new window,
        # not an empty/orphaned curve.
        xd, yd = survivor["pdi"].getData()
        assert xd is not None and len(xd) >= 2, (
            f"[{mode}] survivor has no envelope data after viewport refresh"
        )
        amp = float(np.nanmax(np.abs(yd)))
        assert amp == pytest.approx(7.0, rel=0.10), (
            f"[{mode}] post-refresh survivor carries wrong file's data "
            f"(amp {amp:.3f})"
        )

    def test_get_statistics_keeps_both_samename_entries(self, qapp):
        """The stats contract must report BOTH files' same-named channels (the
        consumer reads ``display_label`` for the header). Pre-fix, one entry
        was lost because the stats dict was keyed on the colliding name.
        """
        fd_a, fd_b = self._two_files()
        display_name = fd_a.get_prefixed_channel("sig")
        rows = [
            _row_for(fd_a, "sig", "fid-A", visible=True),
            _row_for(fd_b, "sig", "fid-B", visible=True),
        ]
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        stats = canvas.get_statistics()
        # composite_items keeps both; the display-name surface yields both too.
        labels = [s.get("display_label") for s in stats.values()]
        assert labels.count(display_name) == 2, (
            f"stats dropped a same-named channel: labels={labels}"
        )
        # Bare-name read still works (contract-method returns the subclass).
        assert display_name in stats
        # The two entries carry the two files' distinct max amplitudes.
        maxes = sorted(s["max"] for s in stats.values())
        assert maxes[0] == pytest.approx(7.0, rel=0.05)
        assert maxes[1] == pytest.approx(1000.0, rel=0.05)


class TestMultiFileSameNameColorSync:
    """A color edit on one file's curve must NOT recolor the OTHER file's
    same-display-name curve (same multi-file collision class as the storage
    bug, on the cosmetic color path). The sync must resolve the composite
    (data_id, name) identity of the EXACT recolored curve, not the last-bound
    same-named entry.
    """

    STEM_A = _COLLIDE_STEM_A
    STEM_B = _COLLIDE_STEM_B

    def _two_files(self):
        return (
            _make_file(self.STEM_A, amp=1000.0, idx=0),
            _make_file(self.STEM_B, amp=7.0, idx=1),
        )

    def _composite_entry(self, canvas, fid, display_name):
        """Read channel_data's stored entry for the exact (fid, name) curve."""
        from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key

        ck = _view_state_channel_key(fid, display_name)
        return canvas.channel_data.get(ck)

    def test_color_edit_lands_on_clicked_file_only(self, qapp):
        fd_a, fd_b = self._two_files()
        display_name = fd_a.get_prefixed_channel("sig")  # collides with B
        rows = [
            _row_for(fd_a, "sig", "fid-A", visible=True),
            _row_for(fd_b, "sig", "fid-B", visible=True),
        ]
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        # Locate the axis handle + line handle for FILE A's exact curve via the
        # composite key, then drive the REAL color-sync entry point.
        from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key

        ck_a = _view_state_channel_key("fid-A", display_name)
        ck_b = _view_state_channel_key("fid-B", display_name)
        handle_a, line_a = canvas._channel_lines.get(ck_a)
        # Sanity: the two colliding curves are distinct stored slots.
        _, line_b = canvas._channel_lines.get(ck_b)
        assert line_a.plot_data_item is not line_b.plot_data_item

        new_color = "#123456"
        old_b = self._composite_entry(canvas, "fid-B", display_name)
        # Real path: ChartOptionsDialog -> handle.sync_line_axis_color(line, c).
        handle_a.sync_line_axis_color(line_a, new_color)
        QCoreApplication.processEvents()

        entry_a = self._composite_entry(canvas, "fid-A", display_name)
        entry_b = self._composite_entry(canvas, "fid-B", display_name)
        # File A's color element updated...
        assert entry_a[2] == new_color, (
            f"clicked file A's color did not update (got {entry_a[2]!r})"
        )
        # ...and file B's entry is UNTOUCHED (color + data pass through verbatim).
        assert entry_b[2] == old_b[2], (
            f"color edit leaked onto file B (B color now {entry_b[2]!r}, "
            f"was {old_b[2]!r})"
        )
        # Numeric data is never mutated by a color sync (t/sig identical).
        assert np.array_equal(entry_a[0], fd_a.time_array)
        assert float(np.nanmax(np.abs(entry_a[1]))) == pytest.approx(1000.0, rel=0.05)
        assert float(np.nanmax(np.abs(entry_b[1]))) == pytest.approx(7.0, rel=0.05)
