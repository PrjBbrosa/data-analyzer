# tests/signal/test_expression.py
import numpy as np
import pytest

from mf4_analyzer.signal.expression import (
    ExpressionError,
    evaluate,
    normalize,
    referenced_names,
)


@pytest.fixture
def vars3():
    return {
        "A": np.array([3.0, 4.0, 0.0]),
        "B": np.array([4.0, 3.0, 2.0]),
        "t": np.array([0.0, 0.1, 0.2]),
    }


def test_parentheses_coefficients_and_sqrt(vars3):
    r = evaluate("sqrt(A^2 + B^2) * 0.5", vars3)
    assert np.allclose(r, [2.5, 2.5, 1.0])


def test_caret_is_power_not_xor():
    assert normalize("A^2") == "A**2"
    assert np.allclose(evaluate("2^10", {"A": np.zeros(1)}), 1024.0)


def test_full_width_operators_are_accepted(vars3):
    r = evaluate("（A × 2 − B）÷ 2", vars3)
    assert np.allclose(r, [1.0, 2.5, -1.0])


def test_time_variable_available(vars3):
    assert np.allclose(evaluate("t * 10", vars3), [0.0, 1.0, 2.0])


def test_whole_signal_scalars_broadcast(vars3):
    assert np.allclose(evaluate("A - mean(A)", vars3), [3 - 7 / 3, 4 - 7 / 3, -7 / 3])
    assert np.allclose(evaluate("rms(B)", vars3, size=3),
                       np.full(3, np.sqrt((16 + 9 + 4) / 3)))


def test_min_max_single_arg_is_scalar_multi_arg_is_elementwise(vars3):
    assert np.allclose(evaluate("max(A)", vars3, size=3), np.full(3, 4.0))
    assert np.allclose(evaluate("max(A, B)", vars3), [4.0, 4.0, 2.0])
    assert np.allclose(evaluate("min(A, B, 1)", vars3), [1.0, 1.0, 0.0])


def test_where_with_comparison(vars3):
    assert np.allclose(evaluate("where(A > 3, A, -B)", vars3), [-4.0, 4.0, -2.0])


def test_scalar_result_broadcasts_to_size(vars3):
    assert np.allclose(evaluate("42", vars3, size=3), np.full(3, 42.0))


def test_non_finite_results_become_nan(vars3):
    r = evaluate("A / (A - 3)", vars3)     # first sample divides by zero
    assert np.isnan(r[0]) and np.isfinite(r[1])
    assert np.isnan(evaluate("sqrt(-1 + 0*A)", vars3)).all()


def test_length_mismatch_against_size_is_reported(vars3):
    with pytest.raises(ExpressionError, match="长度"):
        evaluate("A", vars3, size=99)


def test_referenced_names_excludes_functions_and_constants():
    assert referenced_names("sqrt(A^2 + B^2) + t") == {"A", "B", "t"}
    assert referenced_names("mean(A) * pi") == {"A"}


def test_case_insensitive_names_and_functions(vars3):
    assert np.allclose(evaluate("SQRT(a) + B", vars3), np.sqrt(vars3["A"]) + vars3["B"])


def test_unknown_variable_lists_available(vars3):
    with pytest.raises(ExpressionError, match="未知变量"):
        evaluate("rpm * 2", vars3)


def test_unknown_function_rejected(vars3):
    with pytest.raises(ExpressionError, match="不支持的函数"):
        evaluate("foo(A)", vars3)


def test_empty_expression_rejected(vars3):
    with pytest.raises(ExpressionError, match="为空"):
        evaluate("   ", vars3)


def test_syntax_error_is_wrapped(vars3):
    with pytest.raises(ExpressionError, match="语法错误"):
        evaluate("A +", vars3)


@pytest.mark.parametrize("expr", [
    "__import__('os').system('true')",
    "A.real",
    "A[0]",
    "(lambda: 1)()",
    "open('/etc/passwd')",
    "[x for x in A]",
    "A if B else t",
    "A and B",
])
def test_dangerous_or_unsupported_syntax_rejected(vars3, expr):
    with pytest.raises(ExpressionError):
        evaluate(expr, vars3)


def test_huge_exponent_rejected_before_evaluation(vars3):
    with pytest.raises(ExpressionError, match="指数"):
        evaluate("2 ** 99999999", vars3)


def test_result_must_be_one_dimensional(vars3):
    with pytest.raises(ExpressionError, match="一维"):
        evaluate("A", {"A": np.zeros((3, 3))})
