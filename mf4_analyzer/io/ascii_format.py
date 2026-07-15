"""Evidence-based detection for tabular ASCII files."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin1")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_TIME_NAMES = {"time", "t", "zeit", "timestamp", "time_s", "time(s)", "t(s)"}


@dataclass(frozen=True)
class FixedWidthLayout:
    encoding: str
    header_row: int
    units_row: int | None
    data_row: int
    colspecs: tuple[tuple[int, int], ...]
    sample_interval: float | None
    confidence: str = "high"


def _decode_lines(path: Path, limit: int = 262_144) -> tuple[list[str], str] | None:
    raw = path.read_bytes()[:limit]
    if not raw.strip():
        return None
    for encoding in _ENCODINGS:
        if encoding == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
            continue
        try:
            return raw.decode(encoding).splitlines()[:300], encoding
        except UnicodeDecodeError:
            pass
    return None


def _numeric_spans(line: str):
    matches = list(_NUMBER.finditer(line))
    if len(matches) < 2 or _NUMBER.sub("", line).strip():
        return ()
    return tuple((m.start(), m.end()) for m in matches)


def _cells(line: str, colspecs):
    return [line[start:end].strip() for start, end in colspecs]


def _is_units(cells):
    filled = [cell for cell in cells if cell]
    if not filled:
        return False
    unitish = sum(
        bool(re.fullmatch(r"(?:\[[^\]]{1,16}\]|[A-Za-zÀ-ÿ°µ/%*^._-]{1,12})", cell))
        for cell in filled
    )
    return unitish / len(filled) >= 0.6


def _metadata_interval(lines, data_row, columns):
    # A complete structural signature is required; an isolated scalar is never fs.
    if not lines or lines[0].strip().casefold() != "winwertasciidaten" or data_row < 8:
        return None
    try:
        interval = float(lines[data_row - 7].strip())
        channel_count = int(lines[data_row - 5].strip())
        counts = _numeric_spans(lines[data_row - 4])
        zeros = _numeric_spans(lines[data_row - 3])
    except ValueError:
        return None
    if interval <= 0 or channel_count != columns or len(counts) != columns or len(zeros) != columns:
        return None
    return interval


def sniff_fixed_width_ascii(path) -> FixedWidthLayout | None:
    decoded = _decode_lines(Path(path))
    if decoded is None:
        return None
    lines, encoding = decoded
    for row in range(0, max(0, len(lines) - 7)):
        run = [_numeric_spans(line) for line in lines[row:row + 8]]
        if not run or not run[0] or any(len(item) != len(run[0]) for item in run):
            continue
        if any(len(lines[row + i]) != len(lines[row]) for i in range(8)):
            continue
        spans = run[0]
        bounds = [0] + [(spans[i][1] + spans[i + 1][0]) // 2 for i in range(len(spans) - 1)] + [len(lines[row])]
        colspecs = tuple(zip(bounds, bounds[1:]))
        units_row = row - 1 if row >= 1 and _is_units(_cells(lines[row - 1], colspecs)) else None
        header_row = row - 2 if units_row is not None else row - 1
        if header_row < 0:
            continue
        headers = _cells(lines[header_row], colspecs)
        if sum(bool(cell and not _NUMBER.fullmatch(cell)) for cell in headers) < len(colspecs) - 1:
            continue
        return FixedWidthLayout(
            encoding, header_row, units_row, row, colspecs,
            _metadata_interval(lines, row, len(colspecs)),
        )
    return None


def has_time_column(channels) -> bool:
    return any(str(channel).strip().casefold() in _TIME_NAMES for channel in channels)
