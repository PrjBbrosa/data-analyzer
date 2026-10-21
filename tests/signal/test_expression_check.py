"""Full-data checks share the production expression evaluator."""
import numpy as np
import pytest

from mf4_analyzer.signal.expression import (
    ExpressionError, check_channel_expression, evaluate,
)


def test_check_reports_partial_invalid_and_preserves_values():
    t = np.array([2., 3., 4.])
    a = np.array([1., 2., 3.])
    b = np.array([1., 0., np.nan])
    result = check_channel_expression("A / B", t, {"A": a, "B": b})
    assert not result.ok and result.can_create
    assert result.invalid_count == 2
    assert result.first_invalid_index == 1
    assert result.first_invalid_time == 3.
    assert result.input_invalid_counts == {"B": 1}
    np.testing.assert_allclose(result.values, evaluate("A / B", {"A": a, "B": b}, size=3))


@pytest.mark.parametrize("expr,expected", [
    ("mean(A)", [2., 2., 2.]), ("cumsum(A)", [1., 3., 6.]),
    ("（a × 2）", [2., 4., 6.]), ("time + A", [3., 5., 7.]),
    ("42", [42., 42., 42.]),
])
def test_check_uses_whole_signal_and_normalization(expr, expected):
    result = check_channel_expression(expr, [2, 3, 4], {"A": [1, 2, 3]})
    assert result.ok and result.can_create
    np.testing.assert_allclose(result.values, expected)


def test_unused_channel_is_not_validated():
    result = check_channel_expression("A", [0., 1.], {"A": [2, 3], "B": ["bad"]})
    assert result.ok


def test_all_invalid_cannot_create():
    result = check_channel_expression("sqrt(-abs(A))", [0., 1.], {"A": [1, 2]})
    assert not result.ok and not result.can_create
    assert result.invalid_count == 2


@pytest.mark.parametrize("expr,t,channels,match", [
    ("A", [], {"A": []}, "为空"),
    ("A", [[0, 1]], {"A": [1, 2]}, "一维"),
    ("A", [0, np.nan], {"A": [1, 2]}, "时间"),
    ("A", [0, 1], {}, "通道A"),
    ("A", [0, 1], {"A": [1]}, "长度"),
    ("A", [0, 1], {"A": [[1, 2]]}, "一维"),
    ("A", [0, 1], {"A": ["a", "b"]}, "数值"),
    ("A", [0, 1], {"A": [1+2j, 2]}, "实数"),
    ("A + C", [0, 1], {"A": [1, 2]}, "未知变量"),
    ("clip(A)", [0, 1], {"A": [1, 2]}, "参数"),
    ("A[0]", [0, 1], {"A": [1, 2]}, "语法"),
])
def test_invalid_inputs_are_actionable(expr, t, channels, match):
    with pytest.raises(ExpressionError, match=match):
        check_channel_expression(expr, t, channels)


def test_single_sample_and_masked_missing_input():
    result = check_channel_expression("where(A > 0, A, 0)", [3.], {"A": [np.nan]})
    assert result.ok and result.input_invalid_counts == {"A": 1}
    assert result.values.tolist() == [0.]


def test_numpy_out_argument_is_not_an_expression_feature():
    a = np.array([1., 4.])
    b = np.array([8., 9.])
    with pytest.raises(ExpressionError, match="参数"):
        evaluate("sqrt(A, B)", {"A": a, "B": b})
    np.testing.assert_array_equal(b, [8, 9])


def test_numeric_domain_value_error_is_actionable():
    with pytest.raises(ExpressionError):
        check_channel_expression("2^-1", [0.], {})
