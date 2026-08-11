#!/usr/bin/env python3
"""Standalone Python port of ZFLS ``wwt_import.m`` (WinWert .wwt).

Faithful translation of the official MATLAB importer (Lars Bartschat /
ZFLS GmbH, 2008–2009). Not wired into TraceLab — keep next to the ``.m``
for offline checks and tooling.

Usage:
    python tools/matlab_ports/wwt_import.py path/to/file.wwt
    python -c "from tools.matlab_ports.wwt_import import wwt_import; ..."
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

LENGTH_WWT_ID = 15
LENGTH_COMMENT = 256
LENGTH_KANALNAME = 40
LENGTH_KANALEINHEIT = 17
LENGTH_DATEINAME = 40
LENGTH_TYP = 5
LENGTH_FORMEL = 500


def _deblank(text: str) -> str:
    # MATLAB deblank trims trailing blanks; also drop NULs that appear when
    # the on-disk channel count is actually u16 (high byte becomes a leading
    # 0x00 on the first typ field — the .m script absorbs it via Zeit padding).
    return text.replace("\x00", "").rstrip().strip()


def _read_chars(fh, n: int) -> str:
    raw = fh.read(n)
    if len(raw) < n:
        raise EOFError(f"unexpected EOF reading {n} chars at offset {fh.tell()}")
    return raw.decode("latin-1", "replace")


def wwt_import(filename, *, debug: bool = False):
    """Mirror ``[HEADER, CHANNEL_INFO, CHANNEL, CHANNEL_COUNT] = wwt_import(f)``.

    Returns
    -------
    header : dict
        WWT_ID, COMMENT1, COMMENT2
    channel_info : list[dict]
        Per-channel metadata (Typ, Anzahl, Scale, Offset, ...)
    channel : list[np.ndarray]
        Per-channel samples (Zeit is synthesized; Pars is the formula chars)
    channel_count : int
    """
    path = Path(filename)
    with path.open("rb") as fh:
        header = {
            "WWT_ID": _deblank(_read_chars(fh, LENGTH_WWT_ID)),
            "COMMENT1": _deblank(_read_chars(fh, LENGTH_COMMENT)),
            "COMMENT2": _deblank(_read_chars(fh, LENGTH_COMMENT)),
        }
        if debug:
            print(header["WWT_ID"])
            print(header["COMMENT1"])
            print(header["COMMENT2"])

        channel_count = int(np.frombuffer(fh.read(1), dtype="<i1")[0])
        channel = [None] * channel_count
        channel_info = [None] * channel_count
        time = 0  # first Zeit needs an extra fread; later Zeit channels do not

        for kanal in range(channel_count):
            channel_offset = fh.tell()
            typ = _deblank(_read_chars(fh, LENGTH_TYP))

            if "Zeit" in typ and time < 1:
                fh.read(1)
                time += 1

            anzahl = int(np.frombuffer(fh.read(4), dtype="<i4")[0])
            teiler = None
            if "InBT" in typ or "FloT" in typ or "I10T" in typ:
                teiler = int(np.frombuffer(fh.read(4), dtype="<i4")[0])

            xkanalnr = int(np.frombuffer(fh.read(2), dtype="<i2")[0])
            minbereich = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
            maxbereich = float(np.frombuffer(fh.read(8), dtype="<f8")[0])

            if "Zeit" in typ and time < 2:
                kanalname = _deblank(_read_chars(fh, 4))
                fh.read(LENGTH_KANALNAME - 4)
                kanaleinheit = _deblank(_read_chars(fh, 1))
                fh.read(LENGTH_KANALEINHEIT - 1)
            else:
                kanalname = _deblank(_read_chars(fh, LENGTH_KANALNAME))
                kanaleinheit = _deblank(_read_chars(fh, LENGTH_KANALEINHEIT))

            dateiname = _deblank(_read_chars(fh, LENGTH_DATEINAME))

            daten = None
            formel = None
            if typ == "Pars":
                formel = _read_chars(fh, LENGTH_FORMEL)
                daten = np.array(list(formel), dtype="U1")

            offset = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
            scale = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
            frate = float(np.frombuffer(fh.read(8), dtype="<f8")[0])
            start = float(np.frombuffer(fh.read(8), dtype="<f8")[0])

            if debug:
                print("~" * 55)
                print(f"Kanal {kanal + 1}")
                print(f"ChannelOffset {channel_offset}")
                print(f"Typ {typ}")
                print(f"anzahl {anzahl}")
                if teiler is not None:
                    print(f"teiler {teiler}")
                print(f"xkanalnr {xkanalnr}")
                print(f"minbereich {minbereich}")
                print(f"maxbereich {maxbereich}")
                print(f"kanalname {kanalname}")
                print(f"kanaleinheit {kanaleinheit}")
                print(f"dateiname {dateiname}")
                print(f"offset {offset}")
                print(f"scale {scale}")
                print(f"frate {frate}")
                print(f"start {start}")
                if typ == "Pars" and formel is not None:
                    print("*********")
                    print(_deblank(formel))
                    print("*********")

            data_offset = fh.tell()
            info = {
                "Typ": typ,
                "Anzahl": anzahl,
                "XKanalNr": xkanalnr,
                "MinBereich": minbereich,
                "MaxBereich": maxbereich,
                "KanalName": kanalname,
                "KanalEinheit": kanaleinheit,
                "Dateiname": dateiname,
                "Offset": offset,
                "Scale": scale,
                "FRate": frate,
                "Start": start,
                "DataOffset": data_offset,
                "ChannelOffset": channel_offset,
            }
            if teiler is not None:
                info["Teiler"] = teiler
            channel_info[kanal] = info

            if "Zeit" in typ:
                if start == 0:
                    daten = np.arange(0, frate * (anzahl - 1) + frate * 0.5, frate)
                    daten = daten[:anzahl]
                else:
                    daten = np.arange(start, start + frate * anzahl, frate)[:anzahl]
            elif "int1" in typ:
                raw = np.frombuffer(fh.read(anzahl * 2), dtype="<i2")
                daten = raw.astype(np.float64) * scale + offset
            elif "Long" in typ:
                raw = np.frombuffer(fh.read(anzahl * 4), dtype="<i4")
                daten = raw.astype(np.float64) * scale + offset
            elif "Floa" in typ:
                raw = np.frombuffer(fh.read(anzahl * 4), dtype="<f4")
                daten = raw.astype(np.float64) * scale + offset
            elif "Real" in typ:
                raw = np.frombuffer(fh.read(anzahl * 8), dtype="<f8")
                daten = raw.astype(np.float64) * scale + offset
            elif "IntB" in typ:
                raw = np.frombuffer(fh.read(anzahl * 2), dtype="<u2")
                daten = raw.astype(np.float64) * scale + offset
            elif "InBT" in typ or "FloT" in typ or "I10T" in typ:
                werte = int(math.ceil(anzahl / teiler))
                if "FloT" in typ:
                    temp = np.frombuffer(fh.read(werte * 4), dtype="<f4")
                else:
                    temp = np.frombuffer(fh.read(werte * 2), dtype="<i2")
                daten = np.empty(anzahl, dtype=np.float64)
                k = 0
                for value in temp:
                    for _ in range(teiler):
                        if k >= anzahl:
                            break
                        daten[k] = value
                        k += 1
                    if k >= anzahl:
                        break
                daten = daten * scale + offset
            elif typ != "Pars":
                daten = np.array([])

            channel[kanal] = np.asarray(daten)

    return header, channel_info, channel, channel_count


def _summarize(path: Path) -> None:
    header, infos, channels, count = wwt_import(path)
    print(f"file: {path}")
    print(f"WWT_ID: {header['WWT_ID']!r}")
    print(f"COMMENT1: {header['COMMENT1'][:60]!r}")
    print(f"channel_count: {count}")
    for i, (info, data) in enumerate(zip(infos, channels), start=1):
        n = 0 if data is None else len(data)
        preview = ""
        if data is not None and n and np.issubdtype(data.dtype, np.number):
            preview = f"  first={float(data[0]):.6g} last={float(data[-1]):.6g}"
        print(
            f"  [{i:02d}] typ={info['Typ']!r:6s} name={info['KanalName']!r:30s}"
            f" n={info['Anzahl']:<8d} unit={info['KanalEinheit']!r}"
            f" scale={info['Scale']:g} offset={info['Offset']:g}"
            f" frate={info['FRate']:g} start={info['Start']:g}"
            f" loaded={n}{preview}"
        )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filename", type=Path, help=".wwt file")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    if args.debug:
        wwt_import(args.filename, debug=True)
    else:
        _summarize(args.filename)
    return 0


if __name__ == "__main__":
    sys.exit(main())
