"""Bounded temporary storage for prepared batch time-domain curves."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Sequence

import numpy as np

from .batch_render_models import BatchSeries


_MAX_GROUP_MEMBERS = 32
_MAX_SUBPLOT_PANELS = 8
_MAX_GROUP_PAYLOAD_BYTES = 128 * 1024 * 1024
_MAX_SPOOL_BYTES = 2 * 1024 * 1024 * 1024


def validate_group_shape(*, member_count: int, panel_count: int) -> None:
    """Reject a complete group shape before its first payload write."""

    if int(member_count) > _MAX_GROUP_MEMBERS:
        raise ValueError(f"group members exceed limit {_MAX_GROUP_MEMBERS}")
    if int(panel_count) > _MAX_SUBPLOT_PANELS:
        raise ValueError(f"subplot panels exceed limit {_MAX_SUBPLOT_PANELS}")


@dataclass(frozen=True)
class SpooledSeriesRef:
    x_path: Path
    y_path: Path
    label: str
    unit: str
    x_unit: str
    linestyle: str
    panel: int
    family_key: str
    series_key: str
    variant: str
    nbytes: int


class BatchSeriesSpool:
    """Own a private directory containing bounded ``.npy`` curve payloads."""

    def __init__(self, *, directory: str | Path | None = None) -> None:
        parent = None if directory is None else str(Path(directory))
        self._directory = Path(tempfile.mkdtemp(
            prefix="mf4-batch-series-",
            dir=parent,
        ))
        self._group_members: dict[str, set[str]] = {}
        self._group_panels: dict[str, set[int]] = {}
        self._group_bytes: dict[str, int] = {}
        self._spool_bytes = 0
        self._next_file_id = 0
        self._loaded_arrays: list[np.memmap] = []
        self._series_mappings: dict[int, tuple[np.memmap, np.memmap]] = {}
        self._closed = False

    def __enter__(self) -> "BatchSeriesSpool":
        self._require_open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def append(
        self,
        group_id: str,
        task_id: str,
        series: Sequence[BatchSeries],
    ) -> tuple[SpooledSeriesRef, ...]:
        self._require_open()
        group_key = str(group_id)
        task_key = str(task_id)
        prepared = tuple(series)
        if not all(isinstance(item, BatchSeries) for item in prepared):
            raise TypeError("series must contain BatchSeries values")

        current_members = self._group_members.get(group_key, set())
        member_count = len(current_members | {task_key})
        current_panels = self._group_panels.get(group_key, set())
        panels = current_panels | {
            item.panel
            for item in prepared
            if item.x.size > 0 and item.y.size > 0
        }
        validate_group_shape(
            member_count=member_count,
            panel_count=len(panels),
        )

        payload_bytes = sum(
            int(item.x.nbytes) + int(item.y.nbytes) for item in prepared
        )
        group_bytes = self._group_bytes.get(group_key, 0)
        if group_bytes + payload_bytes > _MAX_GROUP_PAYLOAD_BYTES:
            raise ValueError(
                "group payload exceeds limit "
                f"{_MAX_GROUP_PAYLOAD_BYTES} bytes"
            )
        if self._spool_bytes + payload_bytes > _MAX_SPOOL_BYTES:
            raise ValueError(
                f"run spool exceeds limit {_MAX_SPOOL_BYTES} bytes"
            )

        refs = []
        created_paths: list[Path] = []
        try:
            for item in prepared:
                file_id = self._next_file_id
                self._next_file_id += 1
                x_path = self._directory / f"series-{file_id:08d}-x.npy"
                y_path = self._directory / f"series-{file_id:08d}-y.npy"
                created_paths.extend((x_path, y_path))
                np.save(x_path, item.x, allow_pickle=False)
                np.save(y_path, item.y, allow_pickle=False)
                refs.append(SpooledSeriesRef(
                    x_path=x_path,
                    y_path=y_path,
                    label=item.label,
                    unit=item.unit,
                    x_unit=item.x_unit,
                    linestyle=item.linestyle,
                    panel=item.panel,
                    family_key=item.family_key,
                    series_key=item.series_key,
                    variant=item.variant,
                    nbytes=int(item.x.nbytes) + int(item.y.nbytes),
                ))
        except Exception:
            for path in created_paths:
                path.unlink(missing_ok=True)
            raise

        self._group_members.setdefault(group_key, set()).add(task_key)
        self._group_panels[group_key] = panels
        self._group_bytes[group_key] = group_bytes + payload_bytes
        self._spool_bytes += payload_bytes
        return tuple(refs)

    def load(
        self,
        refs: Sequence[SpooledSeriesRef],
    ) -> tuple[BatchSeries, ...]:
        self._require_open()
        loaded = []
        opened: list[np.memmap] = []
        try:
            for ref in refs:
                x = np.load(ref.x_path, mmap_mode="r", allow_pickle=False)
                opened.append(x)
                y = np.load(ref.y_path, mmap_mode="r", allow_pickle=False)
                opened.append(y)
                loaded.append(BatchSeries(
                    x=x,
                    y=y,
                    label=ref.label,
                    unit=ref.unit,
                    x_unit=ref.x_unit,
                    linestyle=ref.linestyle,
                    panel=ref.panel,
                    family_key=ref.family_key,
                    series_key=ref.series_key,
                    variant=ref.variant,
                ))
        except Exception:
            self._close_arrays(opened)
            raise
        self._loaded_arrays.extend(opened)
        for index, item in enumerate(loaded):
            offset = index * 2
            self._series_mappings[id(item)] = (
                opened[offset], opened[offset + 1],
            )
        return tuple(loaded)

    def release_loaded(self, series: Sequence[BatchSeries]) -> None:
        """Release mappings owned by one completed or failed render group."""

        released = [
            array
            for item in series
            for array in self._series_mappings.pop(id(item), ())
        ]
        target_ids = {id(array) for array in released}
        self._close_arrays(released)
        self._loaded_arrays = [
            array for array in self._loaded_arrays
            if id(array) not in target_ids
        ]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_arrays(self._loaded_arrays)
        self._loaded_arrays.clear()
        self._series_mappings.clear()
        shutil.rmtree(self._directory)

    @staticmethod
    def _close_arrays(arrays: Sequence[np.ndarray]) -> None:
        for array in reversed(tuple(arrays)):
            mapping = getattr(array, "_mmap", None)
            if mapping is not None and not mapping.closed:
                mapping.close()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("batch series spool is closed")


__all__ = ["BatchSeriesSpool", "SpooledSeriesRef", "validate_group_shape"]
