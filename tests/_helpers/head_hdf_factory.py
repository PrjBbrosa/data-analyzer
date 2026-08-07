# tests/_helpers/head_hdf_factory.py
from __future__ import annotations
from pathlib import Path
import numpy as np


def write_head_hdf(path, *, channels, n_scans, delta=3.861e-06,
                   start_of_data=4096, version=4, byte_order="Intel",
                   kind="Time data", scan_mode="synchronised multiple"):
    """Write a minimal HEAD acoustics datafile-format v4 file for tests."""
    L = []
    a = L.append
    a(";"); a("; HEAD acoustics datafile format"); a(";")
    a(f"version:                           {version}")
    a("release:                           6")
    a(f"byte order:                        {byte_order}")
    a(f"kind:                              {kind}")
    a(";#code page:                       936")
    a(f"start of data:                     {start_of_data}")
    a("nbr of abscissa:                   1")
    a(f"nbr of channel:                    {len(channels)}")
    toks = [(f"{c['factor']}*{i}" if c['factor'] != 1 else f"{i}")
            for i, c in enumerate(channels, 1)]
    a("ch order:                          " + ", ".join(toks))
    a("data org:                          a1b1 a2b2")
    a(f"scan mode:                         {scan_mode}")
    a("abscissa definition:               1")
    a("name str:                          Time")
    a("physical quantity:                 time")
    a("physical unit:                     s")
    a("absc sort:                         calc")
    a("first value:                       0")
    a(f"delta value:                       {delta!r}")
    a(f"nbr of scans:                      {n_scans}")
    a("distribution func:                 linear")
    for i, c in enumerate(channels, 1):
        a(f"channel definition:                {i}")
        a(f"name str:                          {c['name']}")
        if c.get("ext_name"):
            a(f";#ext name str:                    {c['ext_name']}")
        a(f";#moniker:                         {c.get('moniker', '')}")
        a(f"physical channel nbr:              {i - 1}")
        a(f"physical quantity:                 {c['quantity']}")
        a(f"physical unit:                     {c['unit']}")
        a(f"calibration:                       {c['calibration']!r}")
        a(f";#dB reference:                    {c.get('db_reference', '')}")
        a(f"implementation type:               {c.get('impl_type', 'FLOAT32')}")
        a(f";#equalization:                    {c.get('equalization', 'id')}")
    header = ("\r\n".join(L) + "\r\n").encode("cp936")
    if len(header) > start_of_data:
        raise ValueError("header exceeds start_of_data")
    header = header.ljust(start_of_data, b" ")

    blocks = []
    for c in channels:
        f = c["factor"]
        s = c.get("samples")
        s = (np.full(n_scans * f, np.nan) if s is None
             else np.asarray(s, dtype=float))
        if s.size != n_scans * f:
            raise ValueError(f"{c['name']}: {s.size} != {n_scans*f}")
        blocks.append(s.reshape(n_scans, f))
    body = np.concatenate(blocks, axis=1).astype("<f4").tobytes()
    Path(path).write_bytes(header + body)
    return Path(path)
