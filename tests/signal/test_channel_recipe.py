"""Owner tests for the shared channel-edit recipe evaluator."""
import math

import numpy as np
import pytest

from mf4_analyzer.signal.channel_recipe import (
    RecipeError,
    derive_from_dict,
    evaluate_derive,
    make_dual,
    make_expression,
    make_single,
    remove_from_dict,
)


def _table():
    time = np.array([0.0, 0.1, 0.2, 0.3])
    columns = {
        "speed": np.array([0.0, 1.0, 3.0, 6.0]),
        "torque": np.array([2.0, 2.0, 0.0, 4.0]),
    }

    def lookup(name):
        return columns[name]

    return time, lookup, columns


def test_single_recipes_match_independent_numpy():
    time, lookup, columns = _table()
    speed = columns["speed"]
    columns["signed"] = np.array([-2.0, 0.0, 1.5, -4.0])
    cases = {
        ("derivative", "speed"): (None, np.gradient(speed, time)),
        ("integral", "speed"): (
            None,
            np.concatenate((
                [0.0],
                np.cumsum(0.5 * (speed[1:] + speed[:-1]) * np.diff(time)),
            )),
        ),
        ("scale", "speed"): (2.5, speed * 2.5),
        ("offset", "speed"): (-1.0, speed - 1.0),
        ("moving_avg", "speed"): (3, np.convolve(speed, np.ones(3) / 3, mode="same")),
        ("abs", "signed"): (None, np.abs(columns["signed"])),
    }
    for (fn, src), (param, expected) in cases.items():
        entry = make_single(f"out_{fn}", "rpm", fn, src, param)
        got = evaluate_derive(entry, time, lookup)
        np.testing.assert_array_equal(got, expected)
        assert got.dtype == np.float64
        assert entry.to_dict()["fn"] == fn
        assert derive_from_dict(entry.to_dict()) == entry


def test_moving_avg_full_window_is_the_mean_and_nan_scale_is_preserved():
    time = np.array([0.0, 0.1, 0.2])
    columns = {"speed": np.array([1.0, 3.0, 5.0])}
    mean = evaluate_derive(
        make_single("wide", "", "moving_avg", "speed", 9), time, columns.__getitem__,
    )
    np.testing.assert_array_equal(mean, np.full(3, 3.0))
    columns["speed"] = np.array([1.0, np.nan, 5.0])
    scaled = evaluate_derive(
        make_single("scaled", "", "scale", "speed", 2.0), time, columns.__getitem__,
    )
    assert np.array_equal(scaled, columns["speed"] * 2.0, equal_nan=True)


def test_dual_recipes_match_independent_numpy_including_divide_by_zero():
    time, lookup, columns = _table()
    left, right = columns["speed"], columns["torque"]
    with np.errstate(divide="ignore", invalid="ignore"):
        divided = np.where(right != 0, left / right, 0.0)
    expected = {
        "add": left + right,
        "sub": left - right,
        "mul": left * right,
        "div": divided,
        "max": np.maximum(left, right),
        "min": np.minimum(left, right),
    }
    for fn, values in expected.items():
        entry = make_dual("out", "Nm", fn, "speed", "torque")
        np.testing.assert_array_equal(evaluate_derive(entry, time, lookup), values)


def test_expression_broadcast_and_all_invalid():
    time, lookup, _columns = _table()
    entry = make_expression("mag", "", "sqrt(A^2 + B^2) * 0.5", "speed", "torque")
    speed, torque = _table()[2]["speed"], _table()[2]["torque"]
    np.testing.assert_allclose(
        evaluate_derive(entry, time, lookup),
        np.sqrt(speed ** 2 + torque ** 2) * 0.5,
    )
    broken = make_expression("bad", "", "log(A)", "torque_zero", None)
    zero = {"torque_zero": np.zeros(4)}
    with pytest.raises(RecipeError) as exc:
        evaluate_derive(broken, time, zero.__getitem__)
    assert exc.value.code == "expression_all_invalid"


def test_rejects_length_mismatch_non_numeric_and_unknown_fields():
    time, lookup, columns = _table()
    columns["short"] = np.array([1.0, 2.0])
    entry = make_dual("out", "", "add", "speed", "short")
    with pytest.raises(RecipeError) as exc:
        evaluate_derive(entry, time, lookup)
    assert exc.value.code == "length_mismatch"

    columns["text"] = np.array(["a", "b", "c", "d"])
    with pytest.raises(RecipeError) as exc:
        evaluate_derive(make_single("out", "", "abs", "text", None), time, lookup)
    assert exc.value.code == "non_numeric"

    with pytest.raises(RecipeError) as exc:
        evaluate_derive(make_single("out", "", "derivative", "speed", None), None, lookup)
    assert exc.value.code == "time_unavailable"

    with pytest.raises(RecipeError):
        derive_from_dict({"op": "derive", "kind": "single", "name": "x", "unit": "", "fn": "scale", "src": "a"})
    with pytest.raises(RecipeError):
        derive_from_dict({
            "op": "derive", "kind": "dual", "name": "x", "unit": "",
            "fn": "add", "a": "a", "b": "b", "extra": 1,
        })
    with pytest.raises(RecipeError):
        remove_from_dict({"op": "remove", "names": "speed"})
    with pytest.raises(RecipeError):
        make_single("out", "", "moving_avg", "speed", 2)
    assert not math.isfinite(float("nan"))
