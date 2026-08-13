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

# Lower numeric values are retained before higher values when the shared image
# budget is pressured.  The values deliberately describe display demand, not
# Board identity: a ref shown on 20 Boards is still one request/image owner.
RESIDENCY_TIER_FOCUS = 0
RESIDENCY_TIER_ACTIVE_VISIBLE = 1
RESIDENCY_TIER_ACTIVE_PLACED = 2
RESIDENCY_TIER_INACTIVE_PLACED = 3
RESIDENCY_TIER_TRAY = 4
_RESIDENCY_TIERS = frozenset(
    {
        RESIDENCY_TIER_FOCUS,
        RESIDENCY_TIER_ACTIVE_VISIBLE,
        RESIDENCY_TIER_ACTIVE_PLACED,
        RESIDENCY_TIER_INACTIVE_PLACED,
        RESIDENCY_TIER_TRAY,
    }
)


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
class ResidencyRequest:
    """One immutable display demand for a unique preview ref.

    ``target_size`` is the logical maximum pixel size currently useful to the
    requester.  It is intentionally advisory: the global budget can still
    downscale a record further.  Board/slot identifiers must never be added to
    this object because they would turn one shared ref into several owners.
    """

    ref: UltraViewRef
    tier: int = RESIDENCY_TIER_ACTIVE_PLACED
    target_size: tuple[int, int] | None = None


@dataclass(frozen=True)
class PreviewStoreStats:
    records: int
    images: int
    raw_pixels: int
    estimated_bytes: int
    evictions: int
    rejections: int
    residency_refs: int = 0


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
        self._residency: dict[UltraViewRef, ResidencyRequest] = {}
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
        self._residency.clear()
        self._clock = 0
        self._evictions = 0
        self._rejections = 0

    def set_pinned_refs(self, refs: Iterable[UltraViewRef]) -> None:
        """Compatibility pin API for the P0 coordinator.

        New P1 callers should supply named :class:`ResidencyRequest` values
        through :meth:`set_residency_requests`.  A legacy pin is equivalent to
        an active placed card, not a Board-owned pixel copy.
        """
        self._require_gui_thread()
        self.set_residency_requests(
            ResidencyRequest(ref=ref) for ref in refs
        )

    def set_residency_requests(
        self, requests: Iterable[ResidencyRequest]
    ) -> None:
        """Atomically replace shared preview residency demand.

        Duplicate ref requests are coalesced deterministically: the highest
        priority tier wins and same-tier requests retain the larger useful
        target.  Thus repeated membership across Boards never multiplies image
        buffers or budget weight.
        """
        self._require_gui_thread()
        merged: dict[UltraViewRef, ResidencyRequest] = {}
        for request in requests:
            if not isinstance(request, ResidencyRequest):
                raise TypeError("residency requests must be ResidencyRequest")
            normalized = self._normalize_residency_request(request)
            current = merged.get(normalized.ref)
            if current is None:
                merged[normalized.ref] = normalized
                continue
            merged[normalized.ref] = self._merge_residency_request(
                current, normalized
            )
        self._residency = merged
        self._enforce_budget()

    def residency_request(self, ref: UltraViewRef) -> ResidencyRequest | None:
        """Return the coalesced request for ``ref``; this does not mutate LRU."""
        return self._residency.get(ref)

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
            residency_refs=len(self._residency),
        )

    def _next_access(self) -> int:
        self._clock += 1
        return self._clock

    @staticmethod
    def _normalize_residency_request(request: ResidencyRequest) -> ResidencyRequest:
        if request.tier not in _RESIDENCY_TIERS:
            raise ValueError(f"unknown preview residency tier: {request.tier!r}")
        target_size = request.target_size
        if target_size is None:
            return request
        if (
            not isinstance(target_size, tuple)
            or len(target_size) != 2
            or isinstance(target_size[0], bool)
            or isinstance(target_size[1], bool)
        ):
            raise ValueError("residency target_size must be a two-item integer tuple")
        width, height = target_size
        if not isinstance(width, int) or not isinstance(height, int):
            raise ValueError("residency target_size must be a two-item integer tuple")
        if width < _MIN_VALID_EDGE or height < _MIN_VALID_EDGE:
            raise ValueError("residency target_size is below the valid image minimum")
        return ResidencyRequest(
            ref=request.ref,
            tier=request.tier,
            target_size=(
                min(width, MAX_PREVIEW_RAW_EDGE),
                min(height, MAX_PREVIEW_RAW_EDGE),
            ),
        )

    @staticmethod
    def _merge_residency_request(
        left: ResidencyRequest, right: ResidencyRequest
    ) -> ResidencyRequest:
        if right.tier < left.tier:
            return right
        if left.tier < right.tier:
            return left
        if left.target_size is None or right.target_size is None:
            return ResidencyRequest(left.ref, left.tier, None)
        left_pixels = left.target_size[0] * left.target_size[1]
        right_pixels = right.target_size[0] * right.target_size[1]
        return right if right_pixels > left_pixels else left

    def _residency_sort_key(self, record: PreviewRecord) -> tuple[int, int]:
        request = self._residency.get(record.ref)
        # No active request is less valuable than inactive/tray membership.
        tier = request.tier if request is not None else RESIDENCY_TIER_TRAY + 1
        # Oldest within a tier is evicted first.
        return (-tier, record.last_access)

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
        # Active placed/focus refs are allowed to shrink but not disappear.  A
        # no-request, tray or inactive record is evictable before that point.
        candidates = [
            record
            for record in self._records.values()
            if (
                self._residency.get(record.ref) is None
                or self._residency[record.ref].tier
                >= RESIDENCY_TIER_INACTIVE_PLACED
            )
            and record.image is not None
            and not record.image.isNull()
        ]
        # Evict unrequested first, then tray/inactive; oldest within a tier.
        candidates.sort(key=self._residency_sort_key)
        while self._raw_pixel_count() > MAX_PREVIEW_PIXELS and candidates:
            victim = candidates.pop(0)
            victim.image = None
            self._evictions += 1
        # This only occurs when every image is protected by residency.  Keep
        # each active preview legal by reducing shared images proportionally.
        if self._raw_pixel_count() > MAX_PREVIEW_PIXELS:
            self._shrink_resident_to_budget()

    def _shrink_resident_to_budget(self) -> None:
        for _ in range(24):
            pixels = self._raw_pixel_count()
            if pixels <= MAX_PREVIEW_PIXELS:
                return
            resident_images = [
                record
                for record in self._records.values()
                if record.ref in self._residency
                and record.image is not None
                and not record.image.isNull()
            ]
            if not resident_images:
                return
            scale = math.sqrt(MAX_PREVIEW_PIXELS / float(pixels))
            if scale >= 1.0:
                scale = 0.95
            for record in resident_images:
                image = record.image
                new_w = max(_MIN_VALID_EDGE, int(image.width() * scale))
                new_h = max(_MIN_VALID_EDGE, int(image.height() * scale))
                if new_w == image.width() and new_h == image.height():
                    if (
                        image.width() >= image.height()
                        and image.width() > _MIN_VALID_EDGE
                    ):
                        new_w -= 1
                    elif image.height() > _MIN_VALID_EDGE:
                        new_h -= 1
                record.image = _scale_image(image, new_w, new_h)
        while self._raw_pixel_count() > MAX_PREVIEW_PIXELS:
            resident_images = [
                record
                for record in self._records.values()
                if record.ref in self._residency
                and record.image is not None
                and not record.image.isNull()
                and (
                    record.image.width() > _MIN_VALID_EDGE
                    or record.image.height() > _MIN_VALID_EDGE
                )
            ]
            if not resident_images:
                return
            largest = max(
                resident_images,
                key=lambda record: record.image.width() * record.image.height(),
            )
            image = largest.image
            largest.image = _scale_image(
                image,
                max(_MIN_VALID_EDGE, image.width() * 9 // 10),
                max(_MIN_VALID_EDGE, image.height() * 9 // 10),
            )
