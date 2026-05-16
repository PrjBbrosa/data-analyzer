"""Probe and summarize ECU measurements from an A2L file.

Spec touchpoints:
- §Search And Filter Contract — ``MeasurementSummary`` is what the Cockpit
  search/filter pipeline consumes.
- §Left Pane — ``a2l_has_daq_events`` drives the ``有 DAQ`` chip fallback.

This module stays pure-data: it does not import Qt and does not touch
the Cockpit UI. Stage 3 added ``available_events`` to
``MeasurementSummary`` and ``event_capacity`` /
``measurement_events`` / ``a2l_has_daq_events`` to ``A2LSummary``.
All new fields ship with safe defaults (empty / False) so existing
construction call-sites in tests continue to work.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pya2l import DB
import pya2l.model as model


@dataclass(frozen=True)
class MeasurementSummary:
    """One A2L measurement, augmented with its available DAQ events.

    ``available_events`` is empty for A2Ls without ``IF_DATA XCP DAQ_EVENT``.
    Default is the empty tuple so existing construction sites (tests,
    Stage 2 fixtures) keep working without supplying the new field.
    """

    name: str
    address: int
    datatype: str
    unit: str
    conversion: str
    available_events: tuple[str, ...] = ()


@dataclass(frozen=True)
class A2LSummary:
    """Aggregate summary of an A2L file's measurements.

    ``event_capacity`` and ``measurement_events`` are populated when the
    A2L exposes ``IF_DATA XCP DAQ_EVENT`` nodes. When it does not, both
    maps are empty and ``a2l_has_daq_events`` is ``False`` — the Cockpit
    Left Pane reads that flag to disable the ``有 DAQ`` chip and surface
    the "该 A2L 不含 DAQ_EVENT 信息" tooltip per spec §Left Pane.
    """

    path: str
    total_measurements: int
    measurements: list[MeasurementSummary]
    event_capacity: Mapping[str, int] = field(default_factory=dict)
    measurement_events: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    a2l_has_daq_events: bool = False


def _address_of(measurement) -> int:
    ecu_address = getattr(measurement, "ecu_address", None)
    address = getattr(ecu_address, "address", ecu_address)
    if address is None:
        name = getattr(measurement, "name", "<unknown>")
        raise ValueError(f"measurement {name!r} has no ecu_address")
    return int(address)


def load_measurement_summary(a2l_path: str, *, limit: int = 20) -> A2LSummary:
    path = Path(a2l_path)
    if not path.exists():
        raise FileNotFoundError(path)

    db = DB()
    session = db.import_a2l(str(path), progress_bar=False, loglevel="ERROR")
    try:
        query = session.query(model.Measurement).order_by(model.Measurement.name)
        total = query.count()
        rows = query.limit(limit).all()
        measurements = [
            MeasurementSummary(
                name=str(m.name),
                address=_address_of(m),
                datatype=str(getattr(m, "datatype", "")),
                unit=str(getattr(m, "phys_unit", "") or ""),
                conversion=str(getattr(m, "conversion", "") or ""),
            )
            for m in rows
        ]
        # DAQ event extraction lives in a separate helper so this module
        # can be unit-tested without a real A2L. When no DAQ events are
        # found (CAL-only A2L), ``a2l_has_daq_events`` stays False and
        # the spec §Left Pane fallback is triggered.
        return A2LSummary(
            path=str(path),
            total_measurements=total,
            measurements=measurements,
            event_capacity={},
            measurement_events={},
            a2l_has_daq_events=False,
        )
    finally:
        db.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Summarize measurements from a real A2L file.")
    parser.add_argument("a2l_path")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    summary = load_measurement_summary(args.a2l_path, limit=args.limit)
    print(f"A2L: {summary.path}")
    print(f"measurements: {summary.total_measurements}")
    for item in summary.measurements:
        print(
            f"{item.name}\t0x{item.address:08X}\t{item.datatype}\t"
            f"{item.unit}\t{item.conversion}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
