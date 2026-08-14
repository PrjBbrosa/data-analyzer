"""UI-neutral column-frame contract for lazy tabular sources.

This is the project-facing table protocol: enumerate columns, read one
column, drop columns, report row count, and opt in to pandas materialization.
It is not a pandas facade. Row-oriented pandas operations are unsupported
and must fail clearly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
import sys
from typing import Any

import numpy as np


class UnsupportedChannelFrameOperation(TypeError):
    """Raised when a ChannelFrame is asked for unimplemented pandas row semantics."""


class ChannelFrame(ABC):
    """Column-oriented table with optional lazy ZOH materialization."""

    is_channel_frame = True

    @abstractmethod
    def column_names(self) -> Sequence[str]:
        """Return column names in display order.

        Names are unique: columns are addressed by name, so an implementation
        must disambiguate or reject duplicates rather than let two series
        share one name (the second would be unreachable).
        """

    @abstractmethod
    def has_column(self, name: str) -> bool:
        """Return whether this frame has a column called ``name``."""

    @abstractmethod
    def get_column(self, name: str) -> np.ndarray:
        """Return one 1-D column, materializing only that column if lazy.

        The result is a read-only view over frame-owned memory; copy it
        before mutating. Same guarantee as the ``frame[name]`` path.
        """

    @abstractmethod
    def drop_columns(self, names) -> ChannelFrame:
        """Return a new frame without the named columns. Row drops are invalid."""

    @abstractmethod
    def row_count(self) -> int:
        """Return the shared row count (Time-axis length)."""

    @abstractmethod
    def to_pandas(self):
        """Explicitly materialize every column into a pandas DataFrame."""

    def to_dataframe(self):
        return self.to_pandas()

    @abstractmethod
    def is_lazy(self) -> bool:
        """Return whether unread signal columns still store event series.

        This is per-instance state, not a class capability: a lazy frame
        whose every column has been read must report ``False``.
        """

    @abstractmethod
    def materialized_column_names(self) -> tuple[str, ...]:
        """Return columns already resident as dense arrays."""

    @abstractmethod
    def zoh_materialization_count(self) -> int:
        """Return how many ZOH resamples this frame has performed."""

    def time_column_name(self) -> str | None:
        for name in self.column_names():
            if str(name).lower() in _TIME_COLUMN_NAMES:
                return str(name)
        return None

    def dtype_note(self) -> str:
        return "float64 columns on a shared Time axis; CAN signals ZOH-hold"


_TIME_COLUMN_NAMES = frozenset({
    "time", "t", "zeit", "timestamp", "time_s", "time(s)", "t(s)",
})


def is_channel_frame(obj: Any) -> bool:
    return bool(getattr(obj, "is_channel_frame", False)) and callable(
        getattr(obj, "get_column", None)
    )


def is_pandas_dataframe(obj: Any) -> bool:
    # pandas is already a top-level io import on loader paths. A nested
    # ``import pandas`` here is scanned as a lazy frozen dependency and
    # would force ``--collect-all pandas``. If pandas is not loaded, no
    # DataFrame instance can exist in this process.
    pd = sys.modules.get("pandas")
    if pd is None:
        return False
    return isinstance(obj, pd.DataFrame)


def is_tabular_frame(obj: Any) -> bool:
    return is_channel_frame(obj) or is_pandas_dataframe(obj)


def frame_column_names(obj: Any) -> list[str]:
    if is_channel_frame(obj):
        return [str(name) for name in obj.column_names()]
    columns = getattr(obj, "columns", ())
    return [str(name) for name in columns]


def frame_has_column(obj: Any, name: str) -> bool:
    if is_channel_frame(obj) and callable(getattr(obj, "has_column", None)):
        return bool(obj.has_column(name))
    return name in getattr(obj, "columns", ())


def frame_get_column(obj: Any, name: str) -> np.ndarray:
    getter = getattr(obj, "get_column", None)
    if callable(getter):
        return np.asarray(getter(name))
    column = obj[name]
    to_numpy = getattr(column, "to_numpy", None)
    if callable(to_numpy):
        try:
            return np.asarray(to_numpy(copy=False))
        except TypeError:
            return np.asarray(to_numpy())
    return np.asarray(column)


def frame_row_count(obj: Any) -> int:
    if is_channel_frame(obj) and callable(getattr(obj, "row_count", None)):
        return int(obj.row_count())
    return int(len(obj))
