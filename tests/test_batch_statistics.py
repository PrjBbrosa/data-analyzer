from __future__ import annotations

import numpy as np


def _series(x, y, *, key="series", family="family", panel=0):
    from mf4_analyzer.batch_statistics import StatisticSeriesInput
    return StatisticSeriesInput(
        x=np.asarray(x, dtype=float), y=np.asarray(y, dtype=float),
        series_key=key, family_key=family, label=key, panel=panel,
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
    for y in ((0, 4, 8, 5, 1), (5, 7, 9, 8, 6), (-9, -7, -4, -6, -8)):
        plan = plan_chart_statistics(
            (_series([0, 1, 2, 1, 0], y),), _enabled(),
            x_source="channel", x_origin="absolute",
        )
        assert not plan.diagnostics
        rows = plan.rows
        assert [row.direction for row in rows] == ["X↑", "X↓"]
        assert [row.sample_count for row in rows] == [3, 3]
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
            _series([0, 1, 2, 1, 0], [0, 1, 2, 1, 0], key="a", family="a"),
            _series([0, 1, 2, 1, 0], [2, 3, 4, 3, 2], key="b", family="b"),
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
