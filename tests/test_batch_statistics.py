from __future__ import annotations

import numpy as np


def _series(x, y, *, key="series", family="family", variant="", panel=0):
    from mf4_analyzer.batch_statistics import StatisticSeriesInput
    return StatisticSeriesInput(
        x=np.asarray(x, dtype=float), y=np.asarray(y, dtype=float),
        series_key=key, family_key=family, label=key, variant=variant, panel=panel,
    )


def _enabled(*, lo=None, hi=None):
    return {
        "enabled": True,
        "range_mode": "custom" if lo is not None else "full",
        "x_min": lo, "x_max": hi,
        "metrics": ["max", "min", "mean"],
    }


def test_monotonic_statistics_use_raw_ordered_samples_and_display_x():
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    plan = plan_chart_statistics(
        (_series([10, 11, 12], [3, 1, 5]),), _enabled(),
        x_source="time", x_origin="zero",
    )

    assert not plan.diagnostics
    row = plan.rows[0]
    assert row.branch_label == "全程"
    assert row.sample_count == 3
    assert (row.minimum, row.maximum, row.mean) == (1.0, 5.0, 3.0)
    assert (row.argmin_x, row.argmax_x) == (1.0, 2.0)


def test_single_hysteresis_splits_by_x_direction_regardless_of_y_sign():
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    expected = None
    for y in (
        (0, 4, 8, 10, 5, 1, 0),
        (5, 7, 9, 10, 8, 6, 5),
        (-9, -7, -4, -3, -6, -8, -9),
    ):
        plan = plan_chart_statistics(
            (_series([0, 1, 2, 3, 2, 1, 0], y),), _enabled(),
            x_source="channel", x_origin="absolute",
        )
        assert not plan.diagnostics
        rows = plan.rows
        assert [row.direction for row in rows] == ["X↑", "X↓"]
        assert [row.sample_count for row in rows] == [4, 4]
        current = [(row.branch_label, row.direction, row.sample_count) for row in rows]
        assert expected is None or current == expected
        expected = current


def test_plateau_and_single_edge_noise_do_not_create_multiple_reversal_error():
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    plan = plan_chart_statistics(
        (_series([0, 1, 2, 2, 3, 2.9, 4, 5], np.arange(8)),),
        _enabled(), x_source="channel", x_origin="absolute",
    )

    assert not plan.diagnostics
    assert [row.branch_label for row in plan.rows] == ["全程"]


def test_custom_interval_keeps_order_and_reports_empty_branch():
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    plan = plan_chart_statistics(
        (_series([0, 1, 2, 1, 0], [0, 1, 2, 3, 4]),),
        _enabled(lo=1.5, hi=2.0), x_source="channel", x_origin="absolute",
    )

    assert len(plan.rows) == 1
    assert plan.rows[0].sample_count == 1
    assert plan.rows[0].branch_label == "全程"


def test_multiple_families_or_multiple_reversals_replace_pane_statistics():
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    overlay = plan_chart_statistics(
        (
            _series([0, 1, 2, 3, 2, 1, 0], [0, 1, 2, 3, 2, 1, 0], key="a", family="a"),
            _series([0, 1, 2, 3, 2, 1, 0], [2, 3, 4, 5, 4, 3, 2], key="b", family="b"),
        ), _enabled(), x_source="channel", x_origin="absolute",
    )
    assert overlay.rows == ()
    assert [item.code for item in overlay.diagnostics] == [
        "chart_statistics.multiple_hysteresis_overlay",
    ]

    cycles = plan_chart_statistics(
        (_series([0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 2, 1, 0], np.arange(13)),), _enabled(),
        x_source="channel", x_origin="absolute",
    )
    assert cycles.rows == ()
    assert [item.code for item in cycles.diagnostics] == [
        "chart_statistics.multiple_x_reversals",
    ]


def _noisy_single_cycle():
    """One physical out-and-back path with deterministic quantisation chatter."""
    forward = np.linspace(-83.0, 83.0, 2001)
    backward = np.linspace(83.0, -83.0, 2001)[1:]
    x = np.concatenate((forward, backward))
    chatter = np.resize(
        np.asarray((0.20, 0.10, 0.0, -0.10, -0.20, -0.10, 0.0, 0.10)), x.size,
    )
    return x + chatter


def test_custom_x_quantisation_chatter_keeps_one_out_and_back_pair():
    """A local dx-sign flip must not turn one physical cycle into an ERROR."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    x = _noisy_single_cycle()
    expected = None
    for y in (np.arange(x.size), np.arange(x.size) + 5000, -np.arange(x.size)):
        plan = plan_chart_statistics(
            (_series(x, y),), _enabled(lo=-20.0, hi=20.0),
            x_source="channel", x_origin="absolute",
        )

        assert not plan.diagnostics
        current = [(row.direction, row.sample_count) for row in plan.rows]
        assert [row.direction for row in plan.rows] == ["X↑", "X↓"]
        assert all(row.sample_count > 400 for row in plan.rows)
        assert expected is None or current == expected
        expected = current


def test_full_range_merges_short_leading_residue_before_statistics():
    """A sub-threshold lead-in must not add a third full-range path."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    lead_in = np.linspace(-82.5, -83.0, 301)
    forward = np.linspace(-83.0, 83.0, 2001)[1:]
    backward = np.linspace(83.0, -83.0, 2001)[1:]
    x = np.concatenate((lead_in, forward, backward))
    plan = plan_chart_statistics(
        (_series(x, np.arange(x.size)),), _enabled(),
        x_source="channel", x_origin="absolute",
    )

    assert not plan.diagnostics
    assert [(row.direction, row.sample_count) for row in plan.rows] == [
        ("X↑", 2301), ("X↓", 2001),
    ]


def test_nonfinite_gap_never_joins_two_acquisition_segments():
    """A nonfinite sample is a hard acquisition boundary, not a display sample."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    for x_gap, y_gap in (
        (np.nan, 3.0), (np.inf, 3.0), (2.0, np.nan), (2.0, np.inf),
    ):
        plan = plan_chart_statistics(
            (_series([0, 1, 2, x_gap, 2, 1, 0], [0, 1, 2, y_gap, 4, 5, 6]),),
            _enabled(),
            x_source="channel", x_origin="absolute",
        )

        assert not plan.diagnostics
        assert [(row.direction, row.sample_count) for row in plan.rows] == [
            ("X↑", 3), ("X↓", 3),
        ]


def test_major_leg_detection_survives_wide_and_turning_point_ranges():
    """Only an under-supported range may fall back to one full-range row."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    x = _noisy_single_cycle()
    cases = (
        (None, None, ["X↑", "X↓"]),
        (-20.0, 20.0, ["X↑", "X↓"]),
        (-0.25, 0.25, [""]),
        (81.7, 82.7, ["X↑", "X↓"]),
    )
    for lo, hi, expected_directions in cases:
        forward_x, backward_x = x[:2001], x[2000:]
        forward_y, backward_y = np.arange(2001), np.arange(2000, 4001)
        if lo is None:
            forward_mask = np.ones(forward_x.size, dtype=bool)
            backward_mask = np.ones(backward_x.size, dtype=bool)
        else:
            forward_mask = (forward_x >= lo) & (forward_x <= hi)
            backward_mask = (backward_x >= lo) & (backward_x <= hi)
        plan = plan_chart_statistics(
            (_series(x, np.arange(x.size)),), _enabled(lo=lo, hi=hi),
            x_source="channel", x_origin="absolute",
        )

        assert not plan.diagnostics
        assert [row.direction for row in plan.rows] == expected_directions
        if len(expected_directions) == 2:
            for row, branch_x, branch_y in zip(
                plan.rows,
                (forward_x[forward_mask], backward_x[backward_mask]),
                (forward_y[forward_mask], backward_y[backward_mask]),
            ):
                assert row.sample_count == branch_x.size
                assert row.minimum == float(branch_y[0])
                assert row.maximum == float(branch_y[-1])
                assert row.argmin_x == float(branch_x[0])
                assert row.argmax_x == float(branch_x[-1])
        else:
            all_x = np.concatenate((forward_x[forward_mask], backward_x[backward_mask]))
            all_y = np.concatenate((forward_y[forward_mask], backward_y[backward_mask]))
            assert plan.rows[0].sample_count == all_x.size
            assert plan.rows[0].argmin_x == float(all_x[0])
            assert plan.rows[0].argmax_x == float(all_x[-1])
            assert plan.rows[0].minimum == float(all_y[0])
            assert plan.rows[0].maximum == float(all_y[-1])


def test_short_cycle_degrades_to_one_full_range_row():
    """Five samples cannot establish a physical out-and-back path."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    plan = plan_chart_statistics(
        (_series([0, 1, 2, 1, 0], np.arange(5)),), _enabled(),
        x_source="channel", x_origin="absolute",
    )

    assert not plan.diagnostics
    assert [(row.branch_label, row.sample_count) for row in plan.rows] == [("全程", 5)]


def test_filtered_variant_shares_its_family_with_the_original_path():
    """Two variants of one source cannot create a multi-family overlay error."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    x = _noisy_single_cycle()
    plan = plan_chart_statistics(
        (
            _series(x, np.arange(x.size), key="task:value", family="task", variant="original"),
            _series(x, -np.arange(x.size), key="task:filtered", family="task", variant="filtered"),
        ), _enabled(lo=-20.0, hi=20.0), x_source="channel", x_origin="absolute",
    )

    assert not plan.diagnostics
    assert [(row.variant, row.direction) for row in plan.rows] == [
        ("original", "X↑"), ("original", "X↓"),
        ("filtered", "X↑"), ("filtered", "X↓"),
    ]


def test_tiny_boundary_touch_from_another_leg_does_not_create_a_path():
    """A two-sample preheat visit is not a third physical range path."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    preheat = np.concatenate((
        np.linspace(-21.0, -20.005, 41),
        np.linspace(-20.005, -19.9975, 3)[1:],
        np.linspace(-19.9975, -83.0, 761)[1:],
    ))
    forward = np.linspace(-83.0, 83.0, 2001)[1:]
    backward = np.linspace(83.0, -83.0, 2001)[1:]
    x = np.concatenate((preheat, forward, backward))
    plan = plan_chart_statistics(
        (_series(x, np.arange(x.size)),), _enabled(lo=-20.0, hi=20.0),
        x_source="channel", x_origin="absolute",
    )

    assert not plan.diagnostics
    assert [row.direction for row in plan.rows] == ["X↑", "X↓"]


def test_three_significant_range_visits_still_replace_rows_with_a_diagnostic():
    """Actual repeated coverage of the selected range must not be hidden as noise."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    x = np.concatenate((
        np.linspace(-30.0, 30.0, 121),
        np.linspace(30.0, -30.0, 121)[1:],
        np.linspace(-30.0, 30.0, 121)[1:],
    ))
    plan = plan_chart_statistics(
        (_series(x, np.arange(x.size)),), _enabled(lo=21.0, hi=29.0),
        x_source="channel", x_origin="absolute",
    )

    assert plan.rows == ()
    assert [(item.code, item.message) for item in plan.diagnostics] == [(
        "chart_statistics.multiple_x_reversals",
        "当前统计区间识别到 3 条有效 X 路径，无法确定唯一升程/回程。",
    )]


def test_two_same_direction_range_visits_replace_rows_with_a_diagnostic():
    """Two valid X↑ visits cannot be presented as a matched out-and-back pair."""
    from mf4_analyzer.batch_statistics import plan_chart_statistics

    upward = np.linspace(-30.0, 30.0, 121)
    x = np.concatenate((upward, np.asarray((np.nan,)), upward))
    plan = plan_chart_statistics(
        (_series(x, np.arange(x.size)),), _enabled(lo=21.0, hi=29.0),
        x_source="channel", x_origin="absolute",
    )

    assert plan.rows == ()
    assert [(item.code, item.message) for item in plan.diagnostics] == [(
        "chart_statistics.multiple_x_reversals",
        "当前统计区间识别到 2 条有效 X 路径，无法确定唯一升程/回程。",
    )]
