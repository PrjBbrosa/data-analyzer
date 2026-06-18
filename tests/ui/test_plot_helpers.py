"""Characterization tests for pure helpers in mf4_analyzer.ui.plot_helpers.

These are CHARACTERIZATION tests: they pin the CURRENT behavior of each
helper exactly as-is. If a helper's output seems unexpected, we still
assert the actual observed value -- do not "fix" it here.

No Qt is needed for any of these helpers (matplotlib Figure is used for
_set_series_ylabel but is a standard dep, not PyQt).
"""

import math

import numpy as np
import pytest

from mf4_analyzer.ui.plot_helpers import (
    _compact_axis_label,
    _format_dual_html,
    _format_single_cursor_channel_html,
    _interp_cursor_value,
    _middle_ellipsis,
    _set_series_ylabel,
    _split_prefixed_label,
)


# ---------------------------------------------------------------------------
# 1. _split_prefixed_label
# ---------------------------------------------------------------------------

class TestSplitPrefixedLabel:
    def test_standard_prefix(self):
        prefix, rest = _split_prefixed_label('[myfile] RPM')
        assert prefix == '[myfile]'
        assert rest == 'RPM'

    def test_prefix_with_leading_space_in_rest(self):
        # rest is lstripped
        prefix, rest = _split_prefixed_label('[file]   channel')
        assert prefix == '[file]'
        assert rest == 'channel'

    def test_no_opening_bracket_returns_none_prefix(self):
        prefix, rest = _split_prefixed_label('plain channel name')
        assert prefix is None
        assert rest == 'plain channel name'

    def test_bracket_but_no_rest_returns_none_prefix(self):
        # '[file]' with nothing after the bracket -> rest is empty -> no match
        prefix, rest = _split_prefixed_label('[file]')
        assert prefix is None
        assert rest == '[file]'

    def test_bracket_but_only_spaces_after_returns_none_prefix(self):
        prefix, rest = _split_prefixed_label('[file]   ')
        assert prefix is None
        assert rest == '[file]   '

    def test_no_closing_bracket_returns_none_prefix(self):
        prefix, rest = _split_prefixed_label('[unclosed channel')
        assert prefix is None
        assert rest == '[unclosed channel'

    def test_empty_string(self):
        prefix, rest = _split_prefixed_label('')
        assert prefix is None
        assert rest == ''

    def test_bracket_at_non_start_returns_none(self):
        prefix, rest = _split_prefixed_label('text [file] channel')
        assert prefix is None
        assert rest == 'text [file] channel'


# ---------------------------------------------------------------------------
# 2. _compact_axis_label
# ---------------------------------------------------------------------------

class TestCompactAxisLabel:
    def test_short_name_passthrough(self):
        # 22 chars exactly fits
        name = 'A' * 22
        assert _compact_axis_label(name) == name

    def test_under_max_chars_passthrough(self):
        assert _compact_axis_label('RPM') == 'RPM'

    def test_prefixed_label_splits_on_newline(self):
        # '[f] channel' where total length > 22 -> prefix\nrest
        long_ch = '[file] very_long_channel_name'
        result = _compact_axis_label(long_ch)
        assert result == '[file]\nvery_long_channel_name'

    def test_plain_long_name_gets_ellipsis(self):
        name = 'A' * 30
        result = _compact_axis_label(name)
        # max_chars=22 -> first 19 chars + '...'
        assert result == 'A' * 19 + '...'
        assert len(result) == 22

    def test_custom_max_chars(self):
        name = 'B' * 40
        result = _compact_axis_label(name, max_chars=10)
        assert result.endswith('...')
        assert len(result) == 10

    def test_unit_is_ignored_in_output(self):
        # unit param is accepted but NOT included in returned label text
        result = _compact_axis_label('RPM', unit='r/min')
        assert result == 'RPM'
        assert 'r/min' not in result


# ---------------------------------------------------------------------------
# 3. _middle_ellipsis
# ---------------------------------------------------------------------------

class TestMiddleEllipsis:
    def test_short_text_passthrough(self):
        assert _middle_ellipsis('hello') == 'hello'

    def test_exactly_max_chars_passthrough(self):
        text = 'x' * 56
        assert _middle_ellipsis(text) == text

    def test_one_over_max_chars_triggers_ellipsis(self):
        text = 'x' * 57
        result = _middle_ellipsis(text)
        assert '...' in result
        assert len(result) == 56

    def test_middle_ellipsis_structure_default(self):
        # 60 chars: keep=53, left=26, right=27
        text = 'A' * 30 + 'B' * 30
        result = _middle_ellipsis(text)
        assert len(result) == 56
        # begins with first 26 As
        assert result.startswith('A' * 26)
        # ends with last 27 Bs
        assert result.endswith('B' * 27)
        assert '...' in result

    def test_tiny_max_chars_uses_head_path(self):
        # max_chars <= 8: text[:max(1, max_chars-3)] + '...'
        text = 'ABCDEFGHIJ'
        result = _middle_ellipsis(text, max_chars=6)
        # max(1, 6-3)=3 -> 'ABC...'
        assert result == 'ABC...'

    def test_max_chars_1_boundary(self):
        # max_chars=1 <= 8: text[:max(1,1-3)] = text[:max(1,-2)] = text[:1]
        result = _middle_ellipsis('HELLO', max_chars=1)
        assert result == 'H...'

    def test_custom_max_chars_normal(self):
        text = 'A' * 20 + 'B' * 20
        result = _middle_ellipsis(text, max_chars=15)
        # keep=12, left=max(1,6)=6, right=max(1,6)=6
        assert len(result) == 15
        assert '...' in result

    def test_non_string_input_is_converted(self):
        result = _middle_ellipsis(12345)
        assert result == '12345'


# ---------------------------------------------------------------------------
# 4. _set_series_ylabel
# ---------------------------------------------------------------------------

class TestSetSeriesYlabel:
    """Uses a real matplotlib Axes (matplotlib is a declared dependency)."""

    def _make_ax(self):
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib.figure import Figure
        fig = Figure()
        ax = fig.add_subplot(111)
        return ax

    def test_sets_ylabel_text(self):
        ax = self._make_ax()
        _set_series_ylabel(ax, 'Speed', '#ff0000')
        assert ax.get_ylabel() == 'Speed'

    def test_sets_ylabel_color(self):
        ax = self._make_ax()
        _set_series_ylabel(ax, 'Torque', '#00ff00')
        import matplotlib.colors as mcolors
        actual_color = ax.yaxis.label.get_color()
        # Compare as RGBA tuples to avoid string format differences
        assert mcolors.to_rgba(actual_color) == pytest.approx(
            mcolors.to_rgba('#00ff00'), abs=1e-6
        )

    def test_no_unit_chip_added_when_unit_empty(self):
        ax = self._make_ax()
        texts_before = len(ax.texts)
        _set_series_ylabel(ax, 'RPM', '#123456', unit='')
        # No extra text artist should be added for empty unit
        assert len(ax.texts) == texts_before

    def test_unit_chip_added_when_unit_given(self):
        ax = self._make_ax()
        _set_series_ylabel(ax, 'RPM', '#123456', unit='r/min')
        # One text artist should appear for the unit chip
        assert len(ax.texts) >= 1
        texts = [t.get_text() for t in ax.texts]
        assert 'r/min' in texts

    def test_right_side_unit_chip_anchor(self):
        ax = self._make_ax()
        _set_series_ylabel(ax, 'V', '#aabbcc', unit='mV', side='right')
        # The unit text artist should have ha='right'
        unit_text = [t for t in ax.texts if t.get_text() == 'mV']
        assert unit_text, "Expected a unit text artist for 'mV'"
        assert unit_text[0].get_ha() == 'right'

    def test_left_side_unit_chip_anchor(self):
        ax = self._make_ax()
        _set_series_ylabel(ax, 'V', '#aabbcc', unit='mV', side='left')
        unit_text = [t for t in ax.texts if t.get_text() == 'mV']
        assert unit_text, "Expected a unit text artist for 'mV'"
        assert unit_text[0].get_ha() == 'left'


# ---------------------------------------------------------------------------
# 5. _format_single_cursor_channel_html
# ---------------------------------------------------------------------------

class TestFormatSingleCursorChannelHtml:
    def test_plain_channel_name_contains_name_value_unit(self):
        html = _format_single_cursor_channel_html('RPM', 1234.5, ' r/min', '#ff0000')
        assert 'RPM' in html
        assert 'r/min' in html
        assert '#ff0000' in html

    def test_value_formatted_with_4g(self):
        # 1234.5 formatted as .4g -> '1234' (Python banker's rounding, rounds to even)
        html = _format_single_cursor_channel_html('Ch', 1234.5, '', '#000000')
        assert '1234' in html

    def test_plain_channel_color_applied(self):
        html = _format_single_cursor_channel_html('Torque', 50.0, ' Nm', '#abcdef')
        assert '#abcdef' in html

    def test_prefixed_channel_splits_prefix_and_name(self):
        html = _format_single_cursor_channel_html('[data.mf4] Speed', 99.9, ' km/h', '#0000ff')
        # prefix in grey, rest in color
        assert '[data.mf4]' in html
        assert '#64748b' in html   # prefix color
        assert '#0000ff' in html   # channel color
        assert 'Speed' in html
        assert 'km/h' in html

    def test_html_special_chars_in_unit_escaped(self):
        html = _format_single_cursor_channel_html('Ch', 1.0, '<>amp', '#000000')
        assert '<>amp' not in html   # raw angle brackets should be escaped
        assert '&lt;' in html or '&gt;' in html

    def test_html_special_chars_in_name_escaped(self):
        html = _format_single_cursor_channel_html('<bad>', 1.0, '', '#000000')
        assert '<bad>' not in html
        assert '&lt;bad&gt;' in html

    def test_small_value_4g_format(self):
        # 0.001234 -> 4g -> '0.001234'
        html = _format_single_cursor_channel_html('Ch', 0.001234, '', '#000000')
        assert '0.001234' in html

    def test_zero_value(self):
        html = _format_single_cursor_channel_html('Ch', 0.0, '', '#000000')
        assert '0' in html


# ---------------------------------------------------------------------------
# 6. _format_dual_html
# ---------------------------------------------------------------------------

class TestFormatDualHtml:
    def test_returns_html_table(self):
        rows = [('Speed', 10.0, 90.0, 50.0, 80.0, ' km/h', '#ff0000')]
        html = _format_dual_html(rows)
        assert html.startswith('<table')
        assert html.endswith('</table>')

    def test_single_row_contains_channel_name_and_stats(self):
        rows = [('Torque', 5.5, 100.0, 52.5, 94.5, ' Nm', '#00ff00')]
        html = _format_dual_html(rows)
        assert 'Torque' in html
        assert 'Nm' in html
        assert '#00ff00' in html
        # min, max, avg, delta labels
        assert 'Min' in html
        assert 'Max' in html
        assert 'Avg' in html

    def test_delta_symbol_present(self):
        rows = [('Ch', 0.0, 10.0, 5.0, 10.0, '', '#000000')]
        html = _format_dual_html(rows)
        assert '△' in html   # △ character

    def test_two_rows_both_channel_names_present(self):
        rows = [
            ('Speed', 10.0, 90.0, 50.0, 80.0, ' km/h', '#ff0000'),
            ('Torque', 5.0, 100.0, 52.5, 95.0, ' Nm', '#0000ff'),
        ]
        html = _format_dual_html(rows)
        assert 'Speed' in html
        assert 'Torque' in html
        assert '#ff0000' in html
        assert '#0000ff' in html

    def test_prefixed_channel_splits_prefix_gray(self):
        rows = [('[run1.mf4] RPM', 0.0, 6000.0, 3000.0, 6000.0, ' r/min', '#ff8800')]
        html = _format_dual_html(rows)
        assert '[run1.mf4]' in html
        assert 'RPM' in html
        assert '#64748b' in html   # prefix color
        assert '#ff8800' in html   # channel color

    def test_row_without_color_uses_default(self):
        # 6-element row (no color) -> default color #111827
        rows = [('Ch', 1.0, 2.0, 1.5, 1.0, ' V')]
        html = _format_dual_html(rows)
        assert '#111827' in html

    def test_second_row_has_top_padding(self):
        rows = [
            ('A', 0.0, 1.0, 0.5, 1.0, '', '#000000'),
            ('B', 2.0, 3.0, 2.5, 1.0, '', '#000000'),
        ]
        html = _format_dual_html(rows)
        # Second channel row should have 8px top padding
        assert 'padding-top:8px' in html

    def test_first_row_has_zero_top_padding(self):
        rows = [('A', 0.0, 1.0, 0.5, 1.0, '', '#000000')]
        html = _format_dual_html(rows)
        assert 'padding-top:0' in html

    def test_empty_rows_returns_empty_table(self):
        html = _format_dual_html([])
        assert '<table' in html
        assert '</table>' in html
        # No channel content
        assert 'Min' not in html

    def test_values_formatted_with_4g(self):
        # 1234.5 -> 4g -> '1234' (banker's rounding); 9999.9 -> '1e+04'
        rows = [('Ch', 1234.5, 9999.9, 5617.2, 8765.4, '', '#000000')]
        html = _format_dual_html(rows)
        assert '1234' in html   # min formatted with .4g (banker's rounding to even)
        assert '1e+04' in html   # max formatted with .4g


# ---------------------------------------------------------------------------
# 7. _interp_cursor_value  (NUMERIC — most thorough coverage)
# ---------------------------------------------------------------------------

class TestInterpCursorValue:
    """Linear interpolation helper. np.interp behaviour:
    - clamps at boundary for out-of-range x
    - exact-sample hit returns sample value
    - empty / all-NaN arrays return np.nan
    All numeric assertions use pytest.approx.
    """

    # --- basic interpolation ---

    def test_exact_sample_hit(self):
        t = [0.0, 1.0, 2.0]
        sig = [10.0, 20.0, 30.0]
        result = _interp_cursor_value(t, sig, 1.0)
        assert result == pytest.approx(20.0)

    def test_midpoint_interpolation(self):
        t = [0.0, 1.0]
        sig = [0.0, 10.0]
        result = _interp_cursor_value(t, sig, 0.5)
        assert result == pytest.approx(5.0)

    def test_quarter_point_interpolation(self):
        t = [0.0, 4.0]
        sig = [0.0, 40.0]
        result = _interp_cursor_value(t, sig, 1.0)
        assert result == pytest.approx(10.0)

    def test_three_point_interpolation_middle_segment(self):
        t = [0.0, 1.0, 2.0]
        sig = [0.0, 10.0, 30.0]
        # Between index 1 and 2: at x=1.5, linear interp = 10 + (30-10)*0.5 = 20
        result = _interp_cursor_value(t, sig, 1.5)
        assert result == pytest.approx(20.0)

    # --- out-of-range (clamping) ---

    def test_out_of_range_left_clamps_to_first(self):
        t = [0.0, 1.0, 2.0]
        sig = [10.0, 20.0, 30.0]
        # np.interp clamps to left boundary value
        result = _interp_cursor_value(t, sig, -1.0)
        assert result == pytest.approx(10.0)

    def test_out_of_range_right_clamps_to_last(self):
        t = [0.0, 1.0, 2.0]
        sig = [10.0, 20.0, 30.0]
        result = _interp_cursor_value(t, sig, 5.0)
        assert result == pytest.approx(30.0)

    def test_exactly_at_left_boundary(self):
        t = [0.0, 1.0, 2.0]
        sig = [10.0, 20.0, 30.0]
        result = _interp_cursor_value(t, sig, 0.0)
        assert result == pytest.approx(10.0)

    def test_exactly_at_right_boundary(self):
        t = [0.0, 1.0, 2.0]
        sig = [10.0, 20.0, 30.0]
        result = _interp_cursor_value(t, sig, 2.0)
        assert result == pytest.approx(30.0)

    # --- degenerate / edge cases ---

    def test_empty_t_returns_nan(self):
        result = _interp_cursor_value([], [], 1.0)
        assert math.isnan(result)

    def test_empty_sig_returns_nan(self):
        result = _interp_cursor_value([1.0], [], 1.0)
        assert math.isnan(result)

    def test_all_nan_t_returns_nan(self):
        result = _interp_cursor_value([np.nan, np.nan], [1.0, 2.0], 1.0)
        assert math.isnan(result)

    def test_all_nan_sig_returns_nan(self):
        result = _interp_cursor_value([0.0, 1.0], [np.nan, np.nan], 0.5)
        assert math.isnan(result)

    def test_all_nan_both_returns_nan(self):
        result = _interp_cursor_value([np.nan], [np.nan], 0.0)
        assert math.isnan(result)

    def test_single_point_returns_that_value_regardless_of_x(self):
        # np.interp with a single-element xp clamps to that value everywhere
        result = _interp_cursor_value([1.0], [42.0], 999.0)
        assert result == pytest.approx(42.0)

    def test_single_point_exact_hit(self):
        result = _interp_cursor_value([1.0], [42.0], 1.0)
        assert result == pytest.approx(42.0)

    # --- NaN filtering ---

    def test_nan_in_sig_filtered_out(self):
        # valid points: t=[0,2], sig=[0,20]; x=1 -> 10.0
        t = [0.0, 1.0, 2.0]
        sig = [0.0, np.nan, 20.0]
        result = _interp_cursor_value(t, sig, 1.0)
        assert result == pytest.approx(10.0)

    def test_nan_in_t_filtered_out(self):
        # valid points: t=[0,2], sig=[0,20]; x=1 -> 10.0
        t = [0.0, np.nan, 2.0]
        sig = [0.0, 99.0, 20.0]
        result = _interp_cursor_value(t, sig, 1.0)
        assert result == pytest.approx(10.0)

    def test_inf_in_t_filtered_out(self):
        # np.isfinite rejects inf
        t = [0.0, np.inf, 2.0]
        sig = [0.0, 99.0, 20.0]
        result = _interp_cursor_value(t, sig, 1.0)
        assert result == pytest.approx(10.0)

    # --- unsorted time ---

    def test_unsorted_t_gets_sorted(self):
        # reversed: t=[2,1,0], sig=[30,20,10] -> after sort same as [0,1,2],[10,20,30]
        t = [2.0, 1.0, 0.0]
        sig = [30.0, 20.0, 10.0]
        result = _interp_cursor_value(t, sig, 0.5)
        assert result == pytest.approx(15.0)

    def test_partially_unsorted_t(self):
        t = [0.0, 2.0, 1.0]
        sig = [0.0, 20.0, 10.0]
        # After sort: t=[0,1,2], sig=[0,10,20]; x=1.5 -> 15.0
        result = _interp_cursor_value(t, sig, 1.5)
        assert result == pytest.approx(15.0)

    # --- return type ---

    def test_return_is_python_float(self):
        result = _interp_cursor_value([0.0, 1.0], [0.0, 1.0], 0.5)
        assert isinstance(result, float)

    def test_nan_return_is_python_float(self):
        result = _interp_cursor_value([], [], 0.0)
        assert isinstance(result, float)

    # --- numpy array inputs ---

    def test_numpy_array_inputs(self):
        t = np.array([0.0, 1.0, 2.0])
        sig = np.array([0.0, 5.0, 10.0])
        result = _interp_cursor_value(t, sig, 1.0)
        assert result == pytest.approx(5.0)

    # --- negative values and non-unit spacing ---

    def test_negative_signal_values(self):
        t = [0.0, 1.0]
        sig = [-10.0, -20.0]
        result = _interp_cursor_value(t, sig, 0.5)
        assert result == pytest.approx(-15.0)

    def test_non_unit_time_spacing(self):
        t = [0.0, 10.0]
        sig = [100.0, 200.0]
        result = _interp_cursor_value(t, sig, 3.0)
        # linear: 100 + (200-100)*3/10 = 130
        assert result == pytest.approx(130.0)
