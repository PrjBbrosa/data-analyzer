import os
from types import SimpleNamespace

import pytest

from can_logger.p0 import a2l_probe as a2l_probe_module
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


def _fake_measurement(name: str = "VehicleSpeed") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        ecu_address=SimpleNamespace(address=0x1234),
        datatype="UWORD",
        phys_unit="km/h",
        conversion="SpeedConv",
    )


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def order_by(self, *_args):
        return self

    def count(self):
        return len(self._rows)

    def all(self):
        return self._rows

    def limit(self, limit):
        return _FakeQuery(self._rows[:limit])


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *_args):
        return _FakeQuery(self._rows)


def test_load_measurement_summary_import_removes_existing_sidecar(monkeypatch, tmp_path):
    a2l = tmp_path / "Bside.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")
    calls = []

    class FakeDB:
        def import_a2l(self, file_name, **kwargs):
            calls.append((file_name, kwargs))
            return _FakeSession([_fake_measurement()])

        def close(self):
            pass

    monkeypatch.setattr(a2l_probe_module, "DB", FakeDB)

    summary = a2l_probe_module.load_measurement_summary(str(a2l), limit=1)

    assert summary.total_measurements == 1
    assert calls == [
        (
            str(a2l),
            {
                "progress_bar": False,
                "loglevel": "ERROR",
                "remove_existing": True,
            },
        )
    ]


def test_load_measurement_summary_reimports_same_path_without_db_close(
    monkeypatch, tmp_path
):
    a2l = tmp_path / "Bside.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")
    calls = []

    class FakeDB:
        def import_a2l(self, file_name, **kwargs):
            calls.append((file_name, kwargs))
            return _FakeSession([_fake_measurement("RepeatedSignal")])

    monkeypatch.setattr(a2l_probe_module, "DB", FakeDB)

    first = a2l_probe_module.load_measurement_summary(str(a2l), limit=1)
    second = a2l_probe_module.load_measurement_summary(str(a2l), limit=1)

    assert [item.name for item in first.measurements] == ["RepeatedSignal"]
    assert [item.name for item in second.measurements] == ["RepeatedSignal"]
    assert [kwargs["remove_existing"] for _file_name, kwargs in calls] == [True, True]
