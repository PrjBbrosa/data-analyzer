"""The heatmap's 1D slice strip, driven only through PgHeatmapCanvas's own API.

Written against the interface as it exists before the slice logic is gathered
into its own object, so the two-step extraction (gather in-class, then move to
slice_panel.py) has to keep every one of these true without editing the file.

Complements tests/ui/test_slice_amp_floor_guard.py, which covers the amplitude
bounds maths itself; nothing here re-derives that.
"""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas


ROWS, COLS = 5, 8
X_EXTENT = (0.0, 7.0)
Y_EXTENT = (0.0, 4.0)


def _matrix():
    """Row r, col c -> r * 10 + c, so a slice is identifiable by its values."""
    return np.add.outer(np.arange(ROWS) * 10.0, np.arange(COLS) * 1.0)


@pytest.fixture
def sliced(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(720, 520)
    c.plot_or_update_heatmap(
        matrix=_matrix(), x_extent=X_EXTENT, y_extent=Y_EXTENT,
        x_label='Time (s)', y_label='Frequency (Hz)',
        amplitude_mode='amplitude', z_auto=True,
    )
    c.show()
    qapp.processEvents()
    c._seed_slice()
    yield c
    c.deleteLater()


def _curve_xy(canvas):
    x, y = canvas._slice_curve.getData()
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


# --- construction -----------------------------------------------------------

def test_no_slice_row_without_with_slice(qapp):
    c = PgHeatmapCanvas(with_slice=False)

    assert c._slice_plot is None
    assert c._slice_curve is None
    assert c._slice_marker is None
    assert c._slice_panel is None
    assert c._slice_toggle is None
    c.deleteLater()


def test_with_slice_builds_plot_curve_marker_and_panel(sliced):
    assert sliced._slice_plot is not None
    assert sliced._slice_curve is not None
    assert sliced._slice_marker is not None
    assert sliced._slice_panel is not None
    assert sliced._slice_toggle is not None
    assert sliced._slice_hint is not None


# --- seeding ----------------------------------------------------------------

def test_seed_lands_at_the_matrix_centre_on_a_first_render(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(720, 520)
    c.plot_or_update_heatmap(
        matrix=_matrix(), x_extent=X_EXTENT, y_extent=Y_EXTENT,
        amplitude_mode='amplitude', z_auto=True,
    )

    c._seed_slice()

    assert c._slice_x_idx == COLS // 2
    assert c._slice_y_idx == ROWS // 2
    c.deleteLater()


def test_reseed_maps_the_previous_position_back_by_coordinate(sliced):
    """A re-render must not snap the cursor to the middle -- it maps the last
    coordinate value to the nearest index of the new grid."""
    sliced.select_time_index(6)
    kept_x_val = sliced._slice_x_val

    sliced.plot_or_update_heatmap(
        matrix=_matrix(), x_extent=X_EXTENT, y_extent=Y_EXTENT,
        amplitude_mode='amplitude', z_auto=True,
    )
    sliced._seed_slice()

    assert sliced._slice_x_idx == 6
    assert sliced._slice_x_val == pytest.approx(kept_x_val)


def test_seed_is_a_noop_before_any_render(qapp):
    c = PgHeatmapCanvas(with_slice=True)

    c._seed_slice()  # must not raise

    assert c._matrix_disp is None
    c.deleteLater()


# --- direction switching ----------------------------------------------------

def test_x_direction_plots_a_column_against_the_y_axis(sliced):
    sliced.select_time_index(3)

    x, y = _curve_xy(sliced)
    assert sliced._slice_dir == 'x'
    # Column 3 of the matrix is [3, 13, 23, 33, 43].
    assert y.tolist() == [3.0, 13.0, 23.0, 33.0, 43.0]
    assert len(x) == ROWS


def test_y_direction_plots_a_row_against_the_x_axis(sliced):
    sliced._slice_y_idx = 2
    sliced.set_slice_direction('y')

    x, y = _curve_xy(sliced)
    assert sliced._slice_dir == 'y'
    # Row 2 of the matrix is [20..27].
    assert y.tolist() == [20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0]
    assert len(x) == COLS


def test_direction_flips_the_marker_angle(sliced):
    sliced.set_slice_direction('x')
    assert sliced._slice_marker.angle == 90

    sliced.set_slice_direction('y')
    assert sliced._slice_marker.angle == 0


def test_direction_switches_the_bottom_axis_label(sliced):
    sliced.set_slice_direction('x')
    x_label = sliced._slice_plot.getAxis('bottom').labelText

    sliced.set_slice_direction('y')

    assert x_label != sliced._slice_plot.getAxis('bottom').labelText


def test_unknown_direction_falls_back_to_x(sliced):
    sliced.set_slice_direction('y')

    sliced.set_slice_direction('sideways')

    assert sliced._slice_dir == 'x'


def test_direction_syncs_the_toggle_without_re_emitting(sliced):
    emitted = []
    sliced._slice_toggle.direction_changed.connect(emitted.append)

    sliced.set_slice_direction('y')

    assert sliced._slice_toggle.direction() == 'y'
    assert emitted == []


def test_toggle_click_drives_the_canvas_direction(sliced):
    sliced.set_slice_direction('x')

    sliced._slice_toggle.set_direction('y', emit=True)

    assert sliced._slice_dir == 'y'


# --- index clamping ---------------------------------------------------------

@pytest.mark.parametrize('given,expected', [
    (-5, 0), (0, 0), (3, 3), (COLS - 1, COLS - 1), (COLS + 40, COLS - 1),
])
def test_select_time_index_clamps_into_the_column_range(
        sliced, given, expected):
    sliced.select_time_index(given)

    assert sliced._slice_x_idx == expected


def test_out_of_range_row_index_is_clamped_on_render(sliced):
    sliced._slice_y_idx = ROWS + 99
    sliced.set_slice_direction('y')

    assert sliced._slice_y_idx == ROWS - 1


def test_select_time_index_forces_the_x_direction(sliced):
    sliced.set_slice_direction('y')

    sliced.select_time_index(2)

    assert sliced._slice_dir == 'x'
    assert sliced._slice_toggle.direction() == 'x'


# --- click-to-place ---------------------------------------------------------

def test_click_inside_the_map_places_an_x_slice_and_announces_it(sliced):
    picked = []
    sliced.slice_picked.connect(lambda: picked.append(True))
    sliced.set_slice_direction('x')

    sliced._select_slice_at(3.0, 2.0)

    assert picked == [True]
    assert sliced._slice_x_idx == sliced._time_index_for(3.0)


def test_click_inside_the_map_places_a_y_slice(sliced):
    picked = []
    sliced.slice_picked.connect(lambda: picked.append(True))
    sliced.set_slice_direction('y')

    sliced._select_slice_at(3.0, 2.0)

    assert picked == [True]
    assert sliced._slice_y_idx == sliced._freq_index_for(2.0)


@pytest.mark.parametrize('direction,point', [
    ('x', (X_EXTENT[1] + 5.0, 2.0)),
    ('y', (3.0, Y_EXTENT[1] + 5.0)),
])
def test_click_outside_the_extents_hints_instead_of_moving(
        sliced, direction, point):
    hints = []
    sliced.slice_hint_requested.connect(hints.append)
    sliced.set_slice_direction(direction)
    before = (sliced._slice_x_idx, sliced._slice_y_idx)

    sliced._select_slice_at(*point)

    assert hints == ["点击位置超出谱图范围"]
    assert (sliced._slice_x_idx, sliced._slice_y_idx) == before


def test_click_before_any_result_hints_to_compute_first(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    hints = []
    c.slice_hint_requested.connect(hints.append)

    c._select_slice_at(1.0, 1.0)

    assert hints == ["先点计算生成谱图"]
    c.deleteLater()


# --- marker drag ------------------------------------------------------------

def test_marker_drag_snaps_to_the_nearest_column(sliced):
    sliced.select_time_index(1)
    xc, _yc = sliced._slice_coords()
    target = float(xc[5])

    sliced._slice_marker.setValue(target + 0.1)

    assert sliced._slice_x_idx == 5
    assert sliced._slice_x_val == pytest.approx(target)


def test_marker_drag_snaps_to_the_nearest_row_in_y_mode(sliced):
    sliced._slice_y_idx = 0
    sliced.set_slice_direction('y')
    _xc, yc = sliced._slice_coords()
    target = float(yc[3])

    sliced._slice_marker.setValue(target - 0.1)

    assert sliced._slice_y_idx == 3


def test_programmatic_marker_moves_do_not_re_enter_the_drag_handler(sliced):
    """_apply_slice sets the marker itself; the updating guard is what keeps
    that from recursing back through the drag slot."""
    sliced.set_slice_direction('x')

    sliced.select_time_index(4)  # moves the marker from inside _apply_slice

    assert sliced._slice_marker_updating is False
    assert sliced._slice_x_idx == 4


def test_marker_drag_drops_antialiasing_then_schedules_its_return(sliced):
    sliced.select_time_index(1)
    xc, _yc = sliced._slice_coords()
    assert sliced._slice_aa_on is True

    sliced._slice_marker.setValue(float(xc[4]))

    assert sliced._slice_aa_on is False
    assert sliced._slice_aa_idle_timer.isActive()


# --- readout ----------------------------------------------------------------

def test_hint_reports_the_fixed_coordinate_of_an_x_slice(sliced):

    sliced.select_time_index(2)

    text = sliced._slice_hint.text()
    assert 'Time' in text
    assert 's' in text


def test_hint_reports_the_fixed_coordinate_of_a_y_slice(sliced):
    sliced._slice_y_idx = 1

    sliced.set_slice_direction('y')

    assert 'Freq' in sliced._slice_hint.text()


def test_button_labels_are_settable_for_the_order_map(sliced):
    sliced.set_slice_button_labels('时间', '阶次')

    assert sliced._slice_toggle._btn_x.text() == '时间'
    assert sliced._slice_toggle._btn_y.text() == '阶次'
    assert sliced._slice_x_btn_label == '时间'
    assert sliced._slice_y_btn_label == '阶次'


# --- visibility / collapse --------------------------------------------------

def test_collapsing_the_split_hides_the_info_panel(sliced, qapp):
    sliced._set_bottom_collapsed(True)
    qapp.processEvents()

    assert sliced._slice_panel.isVisible() is False

    sliced._set_bottom_collapsed(False)
    qapp.processEvents()
    assert sliced._slice_panel.isVisible() is True


def test_full_reset_clears_the_curve_and_hides_the_marker(sliced):
    sliced.select_time_index(2)

    sliced.full_reset()

    assert sliced._slice_curve.getData() == (None, None)
    assert sliced._slice_marker.isVisible() is False
