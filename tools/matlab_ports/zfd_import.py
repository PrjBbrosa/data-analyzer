#!/usr/bin/env python3
"""Standalone Python port of ZFLS ``zfd_import.m`` (.ZFD).

Faithful translation of the official MATLAB importer (Lars Bartschat, 2008).
Not wired into TraceLab — for offline checks against the ``.m`` reference.

Usage:
    python tools/matlab_ports/zfd_import.py path/to/file.zfd
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def _to_next_lf(fh) -> str:
    """Read bytes until LF (10), including the LF — same as MATLAB helper."""
    chars = []
    while True:
        byte = fh.read(1)
        if not byte:
            break
        chars.append(byte.decode("latin-1", "replace"))
        if byte == b"\n":
            break
    return "".join(chars)


def _deblank(text: str) -> str:
    return text.rstrip("\x00\r\n ").strip()


def zfd_import(filename, *, debug: bool = False):
    """Mirror ``[HEADER, CHANNEL_INFO, CHANNEL] = zfd_import(f)``.

    Returns
    -------
    header : list[str]
        11 header lines plus optional text-annotation contents
    channel_info : list[dict]
    channel : list[np.ndarray]
        Note: type 2/3 raw integer samples are stored as read; scale/offset
        are only recorded in channel_info (same as the MATLAB script).
    """
    path = Path(filename)
    with path.open("rb") as fh:
        header = []
        for _ in range(11):
            header.append(_to_next_lf(fh).rstrip("\n"))

        text_count = int(np.frombuffer(fh.read(2), dtype="<i2")[0])
        for _ in range(text_count):
            fh.read(2)  # ausr_h
            fh.read(2)  # ausr_v
            fh.read(2)  # farbe
            fh.read(4)  # posx float32
            fh.read(4)  # posy
            fh.read(4)  # xxx
            inhalt = _deblank(_to_next_lf(fh))
            header.append(inhalt)

        channels = int(np.frombuffer(fh.read(1), dtype="<i1")[0])
        channel = []
        channel_info = []

        for _ in range(channels):
            typ = int(np.frombuffer(fh.read(2), dtype="<i2")[0])
            if typ == 0:
                fh.read(1)
                anzahl_werte = int(np.frombuffer(fh.read(4), dtype="<i4")[0])
                kanalname = _deblank(_to_next_lf(fh))
                kanaleinheit = _deblank(_to_next_lf(fh))
                start = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
                abstand = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
                if debug:
                    print("Kanal 0 gefunden!")
                    print(f"Anzahl Werte={anzahl_werte}")
                    print(f"Kanalname = {kanalname}")
                    print(f"Kanaleinheit = {kanaleinheit}")
                    print(f"Startwert = {start}")
                    print(f"Abstand = {abstand}")
                if start == 0:
                    kanal0 = np.arange(0, abstand * (anzahl_werte - 1) + abstand * 0.5, abstand)
                    kanal0 = kanal0[:anzahl_werte]
                else:
                    kanal0 = np.arange(start, start + abstand * anzahl_werte, abstand)
                    kanal0 = kanal0[:anzahl_werte]
                channel.append(kanal0)
                channel_info.append({
                    "Typ": typ,
                    "AnzahlWerte": anzahl_werte,
                    "KanalName": kanalname,
                    "KanalEinheit": kanaleinheit,
                    "StartWert": start,
                    "Abstand": abstand,
                })
                continue

            anzahl_werte = int(np.frombuffer(fh.read(4), dtype="<i4")[0])
            kanalname = _deblank(_to_next_lf(fh))
            kanaleinheit = _deblank(_to_next_lf(fh))
            xkanalnr = int(np.frombuffer(fh.read(1), dtype="<i1")[0])
            fh.read(1)

            skalierung = None
            offset = None
            min_v = None
            max_v = None
            if typ == 2:
                skalierung = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
                offset = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
            else:
                min_v = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
                max_v = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
            if typ == 3:
                skalierung = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
                offset = float(np.frombuffer(fh.read(8), dtype="<f8")[0])

            if debug:
                print(f"Kanal Typ {typ} gefunden!")
                print(f"Anzahl Werte={anzahl_werte}")
                print(f"Kanalname = {kanalname}")
                print(f"Kanaleinheit = {kanaleinheit}")
                print(f"XKanal Nr. = {xkanalnr}")
                if skalierung is not None:
                    print(f"Skalierung = {skalierung}")
                if offset is not None:
                    print(f"Offset = {offset}")
                if min_v is not None:
                    print(f"min= {min_v}")
                if max_v is not None:
                    print(f"max= {max_v}")

            if typ == 1:
                werte = np.frombuffer(fh.read(anzahl_werte * 4), dtype="<f4").astype(np.float64)
            elif typ == 2:
                werte = np.frombuffer(fh.read(anzahl_werte * 2), dtype="<i2")
            elif typ == 3:
                werte = np.frombuffer(fh.read(anzahl_werte * 4), dtype="<i4")
            elif typ == 4:
                werte = np.frombuffer(fh.read(anzahl_werte * 4), dtype="<f4").astype(np.float64)
            else:
                werte = np.array([])

            info = {
                "Typ": typ,
                "AnzahlWerte": anzahl_werte,
                "KanalName": kanalname,
                "KanalEinheit": kanaleinheit,
                "XKanalNr": xkanalnr,
                "Min": min_v,
                "Max": max_v,
            }
            if skalierung is not None:
                info["Skalierung"] = skalierung
            if offset is not None:
                info["Offset"] = offset
            channel_info.append(info)
            channel.append(np.asarray(werte))

    return header, channel_info, channel


def _summarize(path: Path) -> None:
    header, infos, channels = zfd_import(path)
    print(f"file: {path}")
    print(f"header[0:3]: {[h[:60] for h in header[:3]]}")
    print(f"channels: {len(channels)}")
    for i, (info, data) in enumerate(zip(infos, channels), start=1):
        n = len(data)
        preview = ""
        if n and np.issubdtype(np.asarray(data).dtype, np.number):
            preview = f"  first={float(data[0]):.6g} last={float(data[-1]):.6g}"
        print(
            f"  [{i:02d}] typ={info['Typ']} name={info['KanalName']!r:24s}"
            f" n={info.get('AnzahlWerte', n):<8d}"
            f" unit={info['KanalEinheit']!r}{preview}"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filename", type=Path, help=".zfd file")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    if args.debug:
        zfd_import(args.filename, debug=True)
    else:
        _summarize(args.filename)
    return 0


if __name__ == "__main__":
    sys.exit(main())
