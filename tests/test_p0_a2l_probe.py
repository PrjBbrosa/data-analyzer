import os

import pytest

from can_logger.p0.a2l_probe import load_measurement_summary


@pytest.mark.skipif(
    not os.environ.get("P0_A2L_PATH"),
    reason="set P0_A2L_PATH to a real ECU A2L file for this probe",
)
def test_p0_real_a2l_has_measurements():
    summary = load_measurement_summary(os.environ["P0_A2L_PATH"], limit=5)

    assert summary.total_measurements > 0
    assert summary.measurements
    first = summary.measurements[0]
    assert first.name
    assert first.datatype
    assert isinstance(first.address, int)


def test_address_of_raises_when_attribute_missing():
    from can_logger.p0.a2l_probe import _address_of

    class FakeMeasurement:
        name = "BadMeasurement"
        # no ecu_address attribute

    with pytest.raises(ValueError, match="BadMeasurement.*ecu_address"):
        _address_of(FakeMeasurement())
