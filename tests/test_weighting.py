import numpy as np

from mf4_analyzer.signal.weighting import (
    a_weighting_gain_db,
    a_weighting_gain_linear,
)


def test_a_weighting_db_matches_reference_table():
    freqs = np.array(
        [10, 20, 50, 100, 200, 500, 1000, 2000, 2500, 5000, 10000, 20000],
        dtype=float,
    )
    expected_db = np.array(
        [-70.4, -50.5, -30.2, -19.1, -10.9, -3.2, 0.0, 1.2, 1.3, 0.5, -2.5, -9.3],
        dtype=float,
    )

    np.testing.assert_allclose(a_weighting_gain_db(freqs), expected_db, atol=0.2)


def test_a_weighting_linear_is_unity_at_1khz_and_zero_at_dc():
    assert np.isclose(float(a_weighting_gain_linear(1000.0)), 1.0, rtol=1e-12)
    assert float(a_weighting_gain_linear(0.0)) == 0.0
    assert float(a_weighting_gain_linear(-10.0)) == 0.0


def test_a_weighting_db_is_negative_infinity_at_dc():
    assert np.isneginf(float(a_weighting_gain_db(0.0)))
    assert np.isneginf(float(a_weighting_gain_db(-1.0)))


def test_a_weighting_preserves_vector_shape():
    freqs = np.array([[0.0, 20.0, 1000.0], [2000.0, 2500.0, 20000.0]])

    linear = a_weighting_gain_linear(freqs)
    db = a_weighting_gain_db(freqs)

    assert linear.shape == freqs.shape
    assert db.shape == freqs.shape


def test_a_weighting_monotonic_from_20hz_to_2500hz():
    freqs = np.array([20.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 2500.0])

    db = a_weighting_gain_db(freqs)

    assert np.all(np.diff(db) > 0.0)
