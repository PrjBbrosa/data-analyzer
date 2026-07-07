"""CSV layout sniffing for non-first-row headers.

Some measurement tools export CSVs with banner or metadata lines before
the channel-name row. This module detects the real header row, optional
units row, separator, encoding, and decimal style from a small text
prefix. It intentionally stays pure stdlib: callers can fall back to the
legacy pandas path when the sniff is inconclusive or trivial.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin1")
_SEPARATORS = (",", ";", "\t")
_NUMERIC_DOT = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_NUMERIC_COMMA = re.compile(r"^[+-]?\d+,\d*$")
_BRACKETED_UNIT = re.compile(r"^\[[^\[\]]{1,12}\]$")
_WORD_UNIT = re.compile(r"^[A-Za-z_][A-Za-z0-9_/%*^.\-]{0,7}$")


@dataclass(frozen=True)
class CsvLayout:
    header_row: int
    units_row: int | None
    data_row: int
    sep: str
    encoding: str
    decimal: str
    known_format: str | None

    @property
    def is_trivial(self) -> bool:
        return (
            self.header_row == 0
            and self.units_row is None
            and self.decimal == "."
            and self.encoding != "utf-8-sig"
        )


_KNOWN_FORMAT_RULES = (
    ("winwert", lambda lower: bool(lower) and "winwert" in lower[0], 1),
)


def _read_sniff_lines(path: Path, max_lines: int) -> tuple[list[str], str] | None:
    raw = path.read_bytes()[:65536]
    if not raw.strip():
        return None
    for enc in _ENCODINGS:
        if enc == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
            continue
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        lines = text.splitlines()[:max_lines]
        if lines:
            return lines, enc
    return None


def _split(line: str, sep: str) -> list[str]:
    try:
        return next(csv.reader(io.StringIO(line), delimiter=sep))
    except (csv.Error, StopIteration):
        return []


def _pick_separator(lines: list[str]) -> str | None:
    best: tuple[int, int, int, int, str] | None = None
    for order, sep in enumerate(_SEPARATORS):
        counts = [len(_split(line, sep)) for line in lines if line.strip()]
        multi = [count for count in counts if count > 1]
        if not multi:
            continue
        modal, score = Counter(multi).most_common(1)[0]
        if score < 2:
            continue
        headerish = sum(
            1
            for line in lines
            if len(_split(line, sep)) == modal
            and any(not _cell_numeric(cell) and cell.strip() for cell in _split(line, sep))
        )
        candidate = (score, headerish, modal, -order, sep)
        if best is None or candidate > best:
            best = candidate
    return best[-1] if best is not None else None


def _cell_numeric(cell: str) -> bool:
    cell = cell.strip()
    return bool(_NUMERIC_DOT.match(cell) or _NUMERIC_COMMA.match(cell))


def _mostly_numeric(cells: list[str]) -> bool:
    filled = [cell for cell in cells if cell.strip()]
    if len(filled) < 2:
        return False
    numeric = sum(1 for cell in filled if _cell_numeric(cell))
    return numeric / len(filled) >= 0.6


def _looks_like_units(cells: list[str]) -> bool:
    filled = [cell.strip() for cell in cells if cell.strip()]
    if not filled:
        return False
    unitish = sum(
        1
        for cell in filled
        if _BRACKETED_UNIT.match(cell) or _WORD_UNIT.match(cell)
    )
    return unitish / len(filled) >= 0.5


def _detect_decimal(rows: list[list[str]], data_row: int) -> str:
    cells = [
        cell.strip()
        for row in rows[data_row : data_row + 3]
        for cell in row
        if cell.strip()
    ]
    comma = sum(1 for cell in cells if _NUMERIC_COMMA.match(cell))
    dot = sum(1 for cell in cells if _NUMERIC_DOT.match(cell))
    return "," if comma > dot else "."


def _resolve_below(rows: list[list[str]], header_row: int) -> tuple[int, int | None]:
    units_row: int | None = None
    for i in range(header_row + 1, len(rows)):
        if _mostly_numeric(rows[i]):
            return i, units_row
        if units_row is None and _looks_like_units(rows[i]):
            units_row = i
    return header_row + 1, units_row


def sniff_csv_layout(path, *, max_lines: int = 10) -> CsvLayout | None:
    """Detect the real CSV layout from the first ``max_lines`` lines."""
    try:
        read = _read_sniff_lines(Path(path), max_lines)
    except OSError:
        return None
    if read is None:
        return None

    lines, encoding = read
    if len(lines) < 2:
        return None

    sep = _pick_separator(lines)
    if sep is None:
        return None

    rows = [_split(line, sep) for line in lines]
    lower = [line.lower() for line in lines]

    for name, predicate, header_row in _KNOWN_FORMAT_RULES:
        if predicate(lower) and header_row < len(rows):
            data_row, units_row = _resolve_below(rows, header_row)
            return CsvLayout(
                header_row=header_row,
                units_row=units_row,
                data_row=data_row,
                sep=sep,
                encoding=encoding,
                decimal=_detect_decimal(rows, data_row),
                known_format=name,
            )

    data_row = next((i for i, row in enumerate(rows) if _mostly_numeric(row)), None)
    if data_row is None or data_row == 0:
        if data_row == 0 and encoding == "utf-8-sig":
            return CsvLayout(0, None, 1, sep, encoding, ".", None)
        return None

    n_cols = len(rows[data_row])
    candidates = [
        i
        for i in range(data_row)
        if len(rows[i]) > 1
        and not _mostly_numeric(rows[i])
        and abs(len(rows[i]) - n_cols) <= 1
    ]
    if not candidates:
        return None

    header_row = candidates[-1]
    units_row = None
    if len(candidates) >= 2 and _looks_like_units(rows[candidates[-1]]):
        header_row = candidates[-2]
        units_row = candidates[-1]

    return CsvLayout(
        header_row=header_row,
        units_row=units_row,
        data_row=data_row,
        sep=sep,
        encoding=encoding,
        decimal=_detect_decimal(rows, data_row),
        known_format=None,
    )
