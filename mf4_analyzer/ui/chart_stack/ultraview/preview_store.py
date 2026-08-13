"""Process-local UltraView preview pixels.

``PreviewStore`` owns DPR-normalized ``QImage`` buffers for Board cards. Status
is never stored; callers derive it with
``ultraview_state.derive_preview_status``. The store does not keep a second
``QPixmap`` copy — the page creates pixmaps on demand on the GUI thread.
"""
from __future__ import annotations

import math
import time
from collections.abc import Iterable
from dataclasses import dataclass

from PyQt5.QtCore import QObject, Qt, QThread
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication

from ...image_utils import pixmap_as_device_pixel_image
from ...ultraview_state import PreviewMeta, UltraViewRef

MAX_PREVIEW_RAW_EDGE = 1600
MAX_PREVIEW_PIXELS = 16_000_000
PREVIEW_RECORD_OVERHEAD_BYTES = 256
_MIN_VALID_EDGE = 8
_BYTES_PER_PIXEL = 4


@dataclass
class PreviewRecord:
    """One captured preview. ``status`` is derived, never stored."""

    ref: UltraViewRef
    image: QImage | None
    captured_digest: str | None
    captured_at: float | None
    axis_kind: str | None
    x_unit: str | None
    x_range: tuple[float, float] | None
    y_unit: str | None
    title: str
    source_summary: str
    tab_color: str
    last_access: int


@dataclass(frozen=True)
class PreviewStoreStats:
    records: int
    images: int
    raw_pixels: int
    estimated_bytes: int
    evictions: int
    rejections: int


def _copy_x_range(
    value: tuple[float, float] | None,
) -> tuple[float, float] | None:
    if value is None:
        return None
    return (float(value[0]), float(value[1]))


def _scale_image(image: QImage, width: int, height: int) -> QImage:
    width = max(1, int(width))
    height = max(1, int(height))
    if width == image.width() and height == image.height():
        return image
    return image.scaled(
        width,
        height,
        Qt.IgnoreAspectRatio,
        Qt.SmoothTransformation,
    )


class PreviewStore(QObject):
    """GUI-thread owner of process-local UltraView preview images."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._records: dict[UltraViewRef, PreviewRecord] = {}
        self._pinned: set[UltraViewRef] = set()
        self._clock = 0
        self._evictions = 0
        self._rejections = 0

    @staticmethod
    def image_valid(image) -> bool:
        if image is None:
            return False
        if image.isNull():
            return False
        return image.width() >= _MIN_VALID_EDGE and image.height() >= _MIN_VALID_EDGE

    def publish(
        self,
        ref: UltraViewRef,
        image: QImage | QPixmap | None,
        *,
        digest: str | None,
        meta: PreviewMeta,
        captured_at: float | None = None,
    ) -> bool:
        """Insert or replace the record for *ref*. Invalid images are rejected.

        A rejected publish does not overwrite the last valid image. Returns
        True only when a normalized image was stored (budget eviction may
        later drop the pixels and leave metadata).
        """
        self._require_gui_thread()
        normalized = pixmap_as_device_pixel_image(image)
        if not self.image_valid(normalized):
            self._rejections += 1
            return False
        stored = self._downscale_to_max_edge(normalized)
        if not self.image_valid(stored):
            self._rejections += 1
            return False
        ts = captured_at
        if ts is None:
            ts = meta.captured_at
        if ts is None:
            ts = time.time()
        record = PreviewRecord(
            ref=ref,
            image=stored,
            captured_digest=digest,
            captured_at=float(ts),
            axis_kind=meta.axis_kind,
            x_unit=meta.x_unit,
            x_range=_copy_x_range(meta.x_range),
            y_unit=meta.y_unit,
            title=meta.title,
            source_summary=meta.source_summary,
            tab_color=meta.tab_color,
            last_access=self._next_access(),
        )
        self._records[ref] = record
        self._enforce_budget()
        return True

    def get(self, ref: UltraViewRef) -> PreviewRecord | None:
        return self._records.get(ref)

    def touch(self, ref: UltraViewRef) -> None:
        record = self._records.get(ref)
        if record is None:
            return
        record.last_access = self._next_access()

    def drop(self, ref: UltraViewRef) -> None:
        self._require_gui_thread()
        record = self._records.pop(ref, None)
        if record is not None:
            record.image = None

    def clear(self) -> None:
        self._require_gui_thread()
        for record in self._records.values():
            record.image = None
        self._records.clear()
        self._pinned.clear()
        self._clock = 0
        self._evictions = 0
        self._rejections = 0

    def set_pinned_refs(self, refs: Iterable[UltraViewRef]) -> None:
        self._require_gui_thread()
        self._pinned.clear()
        self._pinned.update(refs)
        self._enforce_budget()

    def stats(self) -> PreviewStoreStats:
        raw_pixels = self._raw_pixel_count()
        records = len(self._records)
        images = sum(
            1
            for record in self._records.values()
            if record.image is not None and not record.image.isNull()
        )
        return PreviewStoreStats(
            records=records,
            images=images,
            raw_pixels=raw_pixels,
            estimated_bytes=(
                raw_pixels * _BYTES_PER_PIXEL
                + records * PREVIEW_RECORD_OVERHEAD_BYTES
            ),
            evictions=self._evictions,
            rejections=self._rejections,
        )

    def _next_access(self) -> int:
        self._clock += 1
        return self._clock

    def _require_gui_thread(self) -> None:
        app = QApplication.instance()
        if app is None or QThread.currentThread() is not app.thread():
            raise RuntimeError(
                "PreviewStore pixel operations must run on the GUI thread"
            )

    def _downscale_to_max_edge(self, image: QImage) -> QImage:
        width = image.width()
        height = image.height()
        longest = max(width, height)
        if longest <= MAX_PREVIEW_RAW_EDGE:
            return image
        scale = MAX_PREVIEW_RAW_EDGE / float(longest)
        return _scale_image(
            image,
            max(1, int(round(width * scale))),
            max(1, int(round(height * scale))),
        )

    def _raw_pixel_count(self) -> int:
        total = 0
        for record in self._records.values():
            image = record.image
            if image is None or image.isNull():
                continue
            total += image.width() * image.height()
        return total

    def _enforce_budget(self) -> None:
        unpinned = [
            record
            for record in self._records.values()
            if record.ref not in self._pinned
            and record.image is not None
            and not record.image.isNull()
        ]
        unpinned.sort(key=lambda record: record.last_access)
        while self._raw_pixel_count() > MAX_PREVIEW_PIXELS and unpinned:
            victim = unpinned.pop(0)
            victim.image = None
            self._evictions += 1
        if self._raw_pixel_count() > MAX_PREVIEW_PIXELS:
            self._shrink_pinned_to_budget()

    def _shrink_pinned_to_budget(self) -> None:
        for _ in range(24):
            pixels = self._raw_pixel_count()
            if pixels <= MAX_PREVIEW_PIXELS:
                return
            pinned_images = [
                record
                for record in self._records.values()
                if record.ref in self._pinned
                and record.image is not None
                and not record.image.isNull()
            ]
            if not pinned_images:
                return
            scale = math.sqrt(MAX_PREVIEW_PIXELS / float(pixels))
            if scale >= 1.0:
                scale = 0.95
            for record in pinned_images:
                image = record.image
                new_w = max(1, int(image.width() * scale))
                new_h = max(1, int(image.height() * scale))
                if new_w == image.width() and new_h == image.height():
                    if image.width() >= image.height() and image.width() > 1:
                        new_w -= 1
                    elif image.height() > 1:
                        new_h -= 1
                record.image = _scale_image(image, new_w, new_h)
        while self._raw_pixel_count() > MAX_PREVIEW_PIXELS:
            pinned_images = [
                record
                for record in self._records.values()
                if record.ref in self._pinned
                and record.image is not None
                and not record.image.isNull()
                and (record.image.width() > 1 or record.image.height() > 1)
            ]
            if not pinned_images:
                return
            largest = max(
                pinned_images,
                key=lambda record: record.image.width() * record.image.height(),
            )
            image = largest.image
            largest.image = _scale_image(
                image,
                max(1, image.width() * 9 // 10),
                max(1, image.height() * 9 // 10),
            )
