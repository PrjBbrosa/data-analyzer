import numpy as np
import pytest

from mf4_analyzer.signal.display_ranges import (
    line_amplitude_limits,
    prepare_line_range,
    visible_line_values,
)


def _legacy_plot_slice(freq, xlim):
    freq_arr = np.asarray(freq, dtype=float)
    lo, hi = sorted(xlim)
    inside = np.flatnonzero(np.isfinite(freq_arr) & (freq_arr >= lo) & (freq_arr <= hi))
    crossing = np.flatnonzero(
        np.isfinite(freq_arr[:-1]) & np.isfinite(freq_arr[1:])
        & (np.minimum(freq_arr[:-1], freq_arr[1:]) <= hi)
        & (np.maximum(freq_arr[:-1], freq_arr[1:]) >= lo))
    if not inside.size and not crossing.size:
        return 0, -1
    first = min(int(inside[0]) if inside.size else len(freq_arr),
                int(crossing[0]) if crossing.size else len(freq_arr))
    last = max(int(inside[-1]) if inside.size else -1,
               int(crossing[-1]) + 1 if crossing.size else -1)
    return first, last


def _assert_query_matches_visible(x, y, xlim, valid_mask=None, *, force_general_path=False):
    prepared = prepare_line_range(x, y, valid_mask=valid_mask)
    expected = visible_line_values(x, y, xlim, valid_mask=valid_mask)
    query = prepared.query(xlim, force_general_path=force_general_path)
    if expected.size == 0:
        assert query.y_min is None and query.y_max is None
        assert line_amplitude_limits(expected, amplitude_mode='amplitude') is None
        return query
    assert query.y_min == pytest.approx(float(np.min(expected)))
    assert query.y_max == pytest.approx(float(np.max(expected)))
    got_limits = line_amplitude_limits(
        np.array([query.y_min, query.y_max], dtype=float),
        amplitude_mode='amplitude',
    )
    assert got_limits == line_amplitude_limits(expected, amplitude_mode='amplitude')
    return query


SCENES = [
    (np.array([0.0, 10.0]), np.array([0.0, 100.0]), (2.0, 4.0), None),
    (np.array([0.0, 5.0, 10.0]), np.array([0.0, np.nan, 100.0]), (2.0, 4.0), None),
    (np.array([0.0, 10.0]), np.array([0.0, 100.0]), (2.0, 4.0), [True, False]),
    (np.array([0.0, 1.0, 2.0, 3.0, 4.0]), np.array([0.0, 10.0, -100.0, 10.0, 0.0]), (0.5, 3.5), None),
    (np.array([0.0, 10.0, 1.0]), np.array([0.0, 100.0, 50.0]), (2.0, 4.0), None),
    (np.array([0.0, 5.0, 5.0, 5.0, 10.0]), np.array([0.0, 1.0, 2.0, 3.0, 10.0]), (5.0, 5.0), None),
    (np.array([0.0, 5.0, 5.0, 5.0, 10.0]), np.array([0.0, 1.0, 2.0, 3.0, 10.0]), (4.0, 6.0), None),
    (np.linspace(0.0, 100.0, 201), np.sin(np.linspace(0.0, 100.0, 201)), (10.0, 20.0), None),
    (np.linspace(0.0, 100.0, 201), np.sin(np.linspace(0.0, 100.0, 201)), (-10.0, 200.0), None),
    (np.array([5.0]), np.array([10.0]), (0.0, 10.0), None),
    (np.array([5.0]), np.array([10.0]), (0.0, 4.0), None),
    (np.empty(0), np.empty(0), (0.0, 1.0), None),
    (np.array([0.0, np.nan, 10.0]), np.array([0.0, 50.0, 100.0]), (0.0, 10.0), None),
    (np.array([0.0, np.nan, 10.0]), np.array([0.0, 50.0, 100.0]), (2.0, 4.0), None),
    (np.array([10.0, 0.0]), np.array([100.0, 0.0]), (2.0, 4.0), None),
]


@pytest.mark.parametrize('x,y,xlim,mask', SCENES)
@pytest.mark.parametrize('force_general_path', [False, True])
def test_query_extrema_match_visible_line_values(x, y, xlim, mask, force_general_path):
    _assert_query_matches_visible(
        x, y, xlim, mask, force_general_path=force_general_path,
    )


@pytest.mark.parametrize('x,y,mask', [([0], [0, 1], None), ([[0]], [[1]], None), ([0], [1], [True, False])])
def test_shape_errors_match_visible_line_values(x, y, mask):
    with pytest.raises(ValueError) as visible_err:
        visible_line_values(x, y, (0, 1), valid_mask=mask)
    with pytest.raises(ValueError) as prepared_err:
        prepare_line_range(x, y, valid_mask=mask)
    assert str(prepared_err.value) == str(visible_err.value)


def test_xlim_errors_match_visible_line_values():
    prepared = prepare_line_range([0.0, 1.0], [0.0, 1.0])
    for xlim in [(1.0, 0.0), (np.nan, 1.0), (0.0,), ((0.0, 1.0), (2.0, 3.0))]:
        with pytest.raises(ValueError, match='xlim') as visible_err:
            visible_line_values([0.0, 1.0], [0.0, 1.0], xlim)
        with pytest.raises(ValueError, match='xlim') as query_err:
            prepared.query(xlim)
        assert str(query_err.value) == str(visible_err.value)


@pytest.mark.parametrize('dtype', [np.float32, np.float64])
def test_dtype_matches_visible_helper(dtype):
    x = np.array([0.0, 10.0, 20.0], dtype=dtype)
    y = np.array([0.0, 50.0, 100.0], dtype=dtype)
    _assert_query_matches_visible(x, y, (2.0, 14.0))
    _assert_query_matches_visible(x, y, (0.0, 20.0))


def test_monotonic_fast_path_matches_forced_general():
    x = np.linspace(0.0, 100.0, 401)
    y = np.cos(x / 7.0)
    prepared = prepare_line_range(x, y)
    assert prepared.ordered
    for xlim in [(0.0, 100.0), (-5.0, 200.0), (10.0, 20.0), (2.5, 8.5), (50.0, 50.0)]:
        fast = prepared.query(xlim)
        general = prepared.query(xlim, force_general_path=True)
        assert fast.used_ordered_path
        assert not general.used_ordered_path
        if fast.y_min is None:
            assert general.y_min is None and general.y_max is None
        else:
            assert fast.y_min == pytest.approx(general.y_min)
            assert fast.y_max == pytest.approx(general.y_max)
        assert [cy for _b, cy in fast.crossings] == pytest.approx(
            [cy for _b, cy in general.crossings]
        )
        assert [b for b, _cy in fast.crossings] == pytest.approx(
            [b for b, _cy in general.crossings]
        )


def test_nan_x_break_does_not_interpolate():
    x = np.array([0.0, 5.0, 10.0])
    y = np.array([0.0, np.nan, 100.0])
    query = prepare_line_range(x, y).query((2.0, 4.0))
    assert query.y_min is None
    assert query.crossings == ()
    assert visible_line_values(x, y, (2.0, 4.0)).size == 0


def test_invalid_mask_gap_does_not_interpolate():
    x = np.array([0.0, 10.0])
    y = np.array([0.0, 100.0])
    query = prepare_line_range(x, y, valid_mask=[True, False]).query((2.0, 4.0))
    assert query.y_min is None
    assert query.crossings == ()
    assert visible_line_values(x, y, (2.0, 4.0), valid_mask=[True, False]).size == 0


def test_repeated_x_does_not_cross_plateau():
    x = np.array([0.0, 5.0, 5.0, 5.0, 10.0])
    y = np.array([0.0, 1.0, 2.0, 3.0, 10.0])
    query = prepare_line_range(x, y).query((5.0, 5.0))
    assert query.y_min == pytest.approx(1.0)
    assert query.y_max == pytest.approx(3.0)
    assert query.crossings == ()


def test_non_monotonic_matches_visible_and_does_not_sort():
    x = np.array([0.0, 10.0, 1.0])
    y = np.array([0.0, 100.0, 50.0])
    prepared = prepare_line_range(x, y)
    assert not prepared.ordered
    assert list(prepared.x) == [0.0, 10.0, 1.0]
    query = _assert_query_matches_visible(x, y, (2.0, 4.0))
    expected_cross = [
        20.0,
        40.0,
        100.0 + (50.0 - 100.0) * (2.0 - 10.0) / (1.0 - 10.0),
        100.0 + (50.0 - 100.0) * (4.0 - 10.0) / (1.0 - 10.0),
    ]
    assert sorted(cy for _b, cy in query.crossings) == pytest.approx(sorted(expected_cross))
    sorted_x = np.sort(x)
    sorted_y = y[np.argsort(x)]
    sorted_visible = visible_line_values(sorted_x, sorted_y, (2.0, 4.0))
    actual_visible = visible_line_values(x, y, (2.0, 4.0))
    assert sorted(actual_visible) != pytest.approx(sorted(sorted_visible))


def test_deep_valley_inside_window_is_in_extrema():
    x = np.arange(5.0)
    y = np.array([0.0, 10.0, -100.0, 10.0, 0.0])
    query = prepare_line_range(x, y).query((0.5, 3.5))
    assert query.y_min == pytest.approx(-100.0)
    assert query.y_max == pytest.approx(10.0)
    assert query.y_min == pytest.approx(float(np.min(visible_line_values(x, y, (0.5, 3.5)))))


def test_crossing_interpolation_is_hand_calculated():
    x = np.array([0.0, 10.0])
    y = np.array([0.0, 100.0])
    query = prepare_line_range(x, y).query((2.0, 4.0))
    assert [pair[0] for pair in query.crossings] == pytest.approx([2.0, 4.0])
    assert [pair[1] for pair in query.crossings] == pytest.approx([20.0, 40.0])
    assert query.y_min == pytest.approx(20.0)
    assert query.y_max == pytest.approx(40.0)
    assert sorted(visible_line_values(x, y, (2.0, 4.0))) == pytest.approx([20.0, 40.0])


def test_full_coverage_reuses_full_valid_bounds(monkeypatch):
    x = np.linspace(0.0, 100.0, 1001)
    y = np.sin(x)
    prepared = prepare_line_range(x, y)
    isfinite_shapes = []
    orig = np.isfinite

    def wrapped(a, *args, **kwargs):
        arr = np.asarray(a)
        if arr.shape == x.shape:
            isfinite_shapes.append(arr.shape)
        return orig(a, *args, **kwargs)

    monkeypatch.setattr(np, 'isfinite', wrapped)
    query = prepared.query((-1.0, 200.0))
    assert query.fully_covered
    assert query.used_cached_full_bounds
    assert query.y_min == prepared.full_y_min
    assert query.y_max == prepared.full_y_max
    assert query.y_min == pytest.approx(float(np.min(y)))
    assert isfinite_shapes == []
    again = prepared.query((-5.0, 500.0))
    assert again.used_cached_full_bounds
    assert again.y_min == prepared.full_y_min


def test_index_stable_pan_reuses_interior_y_until_boundary_moves():
    x = np.arange(6.0)
    y = np.array([np.nan, 1.0, 2.0, 3.0, 4.0, 5.0])
    prepared = prepare_line_range(x, y)
    first = prepared.query((0.2, 4.0))
    second = prepared.query((0.4, 4.0))
    assert first.crossings == ()
    assert second.crossings == ()
    assert first.index_key == second.index_key
    assert second.reused_interior_y
    assert first.y_min == pytest.approx(1.0)
    assert first.y_max == pytest.approx(4.0)
    assert second.y_min == first.y_min
    assert second.y_max == first.y_max

    crossing = prepare_line_range(np.array([0.0, 10.0]), np.array([0.0, 100.0]))
    left = crossing.query((2.0, 4.0))
    moved = crossing.query((3.0, 5.0))
    assert left.index_key[0:2] == moved.index_key[0:2]
    assert left.index_key[2] is True
    assert moved.reused_interior_y
    assert left.y_min == pytest.approx(20.0)
    assert left.y_max == pytest.approx(40.0)
    assert moved.y_min == pytest.approx(30.0)
    assert moved.y_max == pytest.approx(50.0)


def test_query_does_not_copy_source_arrays():
    x = np.arange(250.0)
    y = x * 0.5
    prepared = prepare_line_range(x, y)
    x_id = id(prepared.x)
    y_id = id(prepared.y)
    valid_id = id(prepared.valid)
    prepared.query((10.0, 40.0))
    prepared.query((80.0, 90.0))
    assert id(prepared.x) == x_id
    assert id(prepared.y) == y_id
    assert id(prepared.valid) == valid_id


@pytest.mark.parametrize('x,xlim', [
    (np.linspace(0.0, 100.0, 201), (10.0, 20.0)),
    (np.linspace(0.0, 100.0, 201), (2.5, 8.5)),
    (np.array([0.0, np.nan, 10.0, 20.0]), (0.0, 20.0)),
    (np.array([0.0, np.nan, 10.0, 20.0]), (2.0, 4.0)),
    (np.array([0.0, 10.0, 1.0, 11.0]), (2.0, 4.0)),
    (np.arange(12.0), (0.5, 10.5)),
    (np.array([0.0, 10.0]), (2.0, 4.0)),
    (np.empty(0), (0.0, 1.0)),
])
def test_plot_source_slice_matches_legacy_inside_and_overlap(x, xlim):
    y = np.arange(x.size, dtype=float)
    prepared = prepare_line_range(x, y)
    assert prepared.plot_source_slice(xlim) == _legacy_plot_slice(x, xlim)


def test_incompatible_xy_are_not_silently_truncated():
    with pytest.raises(ValueError, match='equal shapes'):
        prepare_line_range(np.arange(4.0), np.arange(3.0))
