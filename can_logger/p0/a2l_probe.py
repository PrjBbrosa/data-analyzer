from dataclasses import dataclass
from pathlib import Path

from pya2l import DB
import pya2l.model as model


@dataclass(frozen=True)
class MeasurementSummary:
    name: str
    address: int
    datatype: str
    unit: str
    conversion: str


@dataclass(frozen=True)
class A2LSummary:
    path: str
    total_measurements: int
    measurements: list[MeasurementSummary]


def _address_of(measurement) -> int:
    ecu_address = getattr(measurement, "ecu_address", None)
    address = getattr(ecu_address, "address", ecu_address)
    if address is None:
        return 0
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
        return A2LSummary(
            path=str(path),
            total_measurements=total,
            measurements=measurements,
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
