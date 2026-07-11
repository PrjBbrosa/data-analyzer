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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import pickle
import subprocess
import sys
import tempfile

from can_logger.p0.ifdata_xcp import parse_ifdata_xcp, parse_measurement_events


DB = None
model = None
DEFAULT_A2L_PARSE_TIMEOUT_S = 30


class _MeasurementShim:
    name = "name"


class _ModelShim:
    Measurement = _MeasurementShim


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
    address_extension: int = 0
    scale_a: float = 1.0
    scale_b: float = 0.0
    conversion_supported: bool = True


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


def _fill_ifdata_events(
    raw_text: str,
    measurements: Sequence[MeasurementSummary],
) -> tuple[
    list[MeasurementSummary],
    dict[str, int],
    dict[str, tuple[str, ...]],
    bool,
]:
    """Fill DAQ event fields from raw ``IF_DATA XCP`` text."""

    ifdata_blocks = parse_ifdata_xcp(raw_text)
    event_capacity: dict[str, int] = {}
    for block in ifdata_blocks:
        for event in block.available_events:
            event_capacity.setdefault(event.name, event.max_odt_entries)

    measurement_events = dict(parse_measurement_events(raw_text))

    # AUTOSAR-style A2Ls (e.g. CANape 14 ECU output) enumerate DAQ
    # events only at the IF_DATA XCP top level — no per-MEASUREMENT
    # DAQ_EVENT/FIXED_EVENT_LIST bindings. ``parse_measurement_events``
    # is empty for those, which previously left
    # ``MeasurementSummary.available_events`` blank and disabled the
    # cockpit event picker for every signal. When the A2L has global
    # events but no per-measurement refs, fall back to the global list
    # so operators can still pick an event manually.
    global_events_fallback: tuple[str, ...] = ()
    if event_capacity and not measurement_events:
        global_events_fallback = tuple(event_capacity.keys())

    updated = [
        replace(
            m,
            available_events=measurement_events.get(m.name, global_events_fallback),
        )
        for m in measurements
    ]
    return updated, event_capacity, measurement_events, bool(event_capacity)


def _dispose_db(db) -> None:
    for method_name in ("close", "dispose"):
        method = getattr(db, method_name, None)
        if callable(method):
            method()
            return


def _format_exit_code(returncode: int) -> str:
    unsigned = returncode & 0xFFFFFFFF
    if returncode < 0 or unsigned > 0x7FFFFFFF:
        return f"{returncode} (0x{unsigned:08X})"
    return str(returncode)


def _compact_process_output(stdout: bytes, stderr: bytes) -> str:
    raw = stderr or stdout or b""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return "no output"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Take the LAST line — for a Python traceback the first line is
    # `Traceback (most recent call last):`, the actual exception text
    # is the last line. Using lines[0] hides the root cause.
    detail = lines[-1] if lines else "no output"
    # Long tracebacks (> 800 chars) get dumped verbatim to a temp log so
    # the operator can pull the full stack out of %TEMP% / /tmp.
    suffix = ""
    if len(text) > 800:
        try:
            fd, path = tempfile.mkstemp(prefix="a2l_probe_", suffix=".log")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            suffix = f"  (full log: {path})"
        except OSError:
            pass
    # Truncate the detail body first, then append the log-path suffix —
    # otherwise the 300-char cap would slice the suffix off (which is
    # the operator's pointer to the full traceback).
    body_cap = max(60, 300 - len(suffix))
    if len(detail) > body_cap:
        detail = detail[: body_cap - 3] + "..."
    return detail + suffix


def _load_measurement_summary_inprocess(
    a2l_path: str, *, limit: int | None = None
) -> A2LSummary:
    """Summarize an A2L file's measurements.

    ``limit=None`` (default) returns every measurement — that is what
    the Cockpit Left Pane needs (real ECU A2Ls hold 300+ measurements;
    truncating silently was the cause of "I picked an A2L and only see
    20 rows"). CLI probes that just want a sanity check pass an explicit
    small ``limit`` to keep the run cheap.
    """

    path = Path(a2l_path)
    if not path.exists():
        raise FileNotFoundError(path)

    global DB, model
    if DB is None:
        from pya2l import DB as loaded_db
        import pya2l.model as loaded_model

        DB = loaded_db
        model = loaded_model
    elif model is None:
        # Tests monkeypatch DB with a fake whose query() ignores the model
        # argument. Keep that path independent from the optional pya2l wheel.
        model = _ModelShim

    db_cls, a2l_model = DB, model
    db = db_cls()
    session = db.import_a2l(
        str(path),
        progress_bar=False,
        loglevel="ERROR",
        remove_existing=True,
    )
    try:
        query = session.query(a2l_model.Measurement).order_by(
            a2l_model.Measurement.name
        )
        total = query.count()
        rows = query.all() if limit is None else query.limit(limit).all()
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
    finally:
        _dispose_db(db)

    try:
        raw_text = path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        raw_text = ""
    measurements, event_capacity, measurement_events, has_daq = _fill_ifdata_events(
        raw_text,
        measurements,
    )

    return A2LSummary(
        path=str(path),
        total_measurements=total,
        measurements=measurements,
        event_capacity=event_capacity,
        measurement_events=measurement_events,
        a2l_has_daq_events=has_daq,
    )


def load_measurement_summary(
    a2l_path: str, *, limit: int | None = None
) -> A2LSummary:
    """Summarize an A2L file's measurements in a crash-isolated subprocess.

    ``limit=None`` (default) returns every measurement; callers that only want
    a cheap probe pass an explicit small ``limit``.
    """

    path = Path(a2l_path)
    if not path.exists():
        raise FileNotFoundError(path)

    cmd = [
        sys.executable,
        "-m",
        "can_logger.p0._a2l_subprocess",
        str(path),
    ]
    if limit is not None:
        cmd.extend(["--limit", str(limit)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=DEFAULT_A2L_PARSE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"A2L parse subprocess timed out after {exc.timeout:g}s: {path}"
        ) from exc

    if result.returncode != 0:
        detail = _compact_process_output(result.stdout, result.stderr)
        raise RuntimeError(
            "A2L parse subprocess failed "
            f"(exit={_format_exit_code(result.returncode)}): {detail}"
        )

    try:
        summary = pickle.loads(result.stdout)
    except Exception as exc:  # noqa: BLE001
        detail = _compact_process_output(result.stdout, result.stderr)
        raise RuntimeError(
            f"A2L parse subprocess returned invalid data: {detail}"
        ) from exc
    if not isinstance(summary, A2LSummary):
        raise RuntimeError(
            "A2L parse subprocess returned unexpected result type: "
            f"{type(summary).__name__}"
        )
    return summary


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


if __name__ == "__main__":  # pragma: no cover - module entry
    # Re-dispatch through the canonical module name: running via
    # ``-m can_logger.p0.a2l_probe`` loads this file as ``__main__``,
    # while pickle resolves ``A2LSummary`` from
    # ``can_logger.p0.a2l_probe``. Without this, isinstance rejects a
    # valid subprocess result.
    from can_logger.p0.a2l_probe import main as _canonical_main

    raise SystemExit(_canonical_main())
