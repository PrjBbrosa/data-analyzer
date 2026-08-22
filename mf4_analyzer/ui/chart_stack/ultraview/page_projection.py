"""Pure UltraView card/chrome projection. No Page, Board writes, or timers.

Page gathers library/preview/selection facts, calls these helpers, and still
applies the resulting ``CardViewModel`` mapping to grid / free-grid / tray.
"""
from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mf4_analyzer.ui.ultraview_state import (
    COMPARE_FILTER_ALL,
    UltraViewRef,
    card_matches_compare_filter,
    derive_preview_status,
)

from .card_widgets import CardViewModel, preview_image

__all__ = [
    "LibraryChromeFacts",
    "axis_kind_from_record",
    "axis_records_from_models",
    "card_models_for_slots",
    "card_view_model",
    "chrome_value",
    "color_for",
    "replacement_armed_for",
    "source_for",
    "status_for",
    "title_for",
    "tray_chrome_maps",
    "x_unit_and_range_from_record",
]


@dataclass(frozen=True)
class LibraryChromeFacts:
    """Library chrome for one View. Plain data, not a QWidget row."""

    section: str
    view_id: str
    name: str = ""
    tab_color: str = ""
    source_summary: str = ""


def chrome_value(live: bool, lib_val: str, rec_val: str, default: str = "") -> str:
    """Live Views prefer library chrome; orphans prefer the preview record."""
    lib = str(lib_val or "")
    rec = str(rec_val or "")
    fallback = str(default or "")
    if live:
        return lib or rec or fallback
    return rec or lib or fallback


def _record_text(record: Any, attr: str) -> str:
    if record is None:
        return ""
    return str(getattr(record, attr, "") or "")


def title_for(
    ref: UltraViewRef,
    live: bool,
    chrome: LibraryChromeFacts | None,
    record: Any,
) -> str:
    lib_val = "" if chrome is None else chrome.name
    return chrome_value(live, lib_val, _record_text(record, "title"), ref.view_id)


def color_for(
    ref: UltraViewRef,
    live: bool,
    chrome: LibraryChromeFacts | None,
    record: Any,
) -> str:
    lib_val = "" if chrome is None else chrome.tab_color
    return chrome_value(live, lib_val, _record_text(record, "tab_color"))


def source_for(
    ref: UltraViewRef,
    live: bool,
    chrome: LibraryChromeFacts | None,
    record: Any,
) -> str:
    lib_val = "" if chrome is None else chrome.source_summary
    return chrome_value(live, lib_val, _record_text(record, "source_summary"))


def status_for(explicit_status: str | None, exists: bool, record: Any) -> str:
    """Prefer an explicit Page status; otherwise derive from exists + image."""
    if explicit_status is not None:
        return explicit_status
    image_valid = preview_image(record) is not None
    captured = getattr(record, "captured_digest", None) if record is not None else None
    return derive_preview_status(exists, image_valid, captured, None)


def axis_kind_from_record(record: Any) -> str | None:
    if record is None:
        return None
    kind = getattr(record, "axis_kind", None)
    return str(kind) if kind else None


def x_unit_and_range_from_record(record: Any) -> tuple[str, tuple[float, float] | None]:
    x_unit = str(getattr(record, "x_unit", "") or "") if record is not None else ""
    raw_range = getattr(record, "x_range", None) if record is not None else None
    x_range: tuple[float, float] | None = None
    if isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
        try:
            x_range = (float(raw_range[0]), float(raw_range[1]))
        except (TypeError, ValueError):
            x_range = None
    return x_unit, x_range


def replacement_armed_for(
    ref: UltraViewRef,
    slot_id: str,
    replacement_ref: UltraViewRef | None,
    replacement_slot: str | None,
) -> bool:
    return replacement_ref == ref or replacement_slot == slot_id


def card_view_model(
    *,
    slot_id: str,
    ref: UltraViewRef,
    live: bool,
    chrome: LibraryChromeFacts | None,
    record: Any,
    explicit_status: str | None,
    selected: bool,
    compare_filter: str,
    replacement_armed: bool,
    show_title: bool,
    show_source: bool,
    show_card_actions: bool,
) -> CardViewModel:
    axis_kind = axis_kind_from_record(record)
    x_unit, x_range = x_unit_and_range_from_record(record)
    return CardViewModel(
        slot_id=slot_id,
        section=ref.section,
        view_id=ref.view_id,
        title=title_for(ref, live, chrome, record),
        tab_color=color_for(ref, live, chrome, record),
        status=status_for(explicit_status, live, record),
        source_summary=source_for(ref, live, chrome, record),
        axis_kind=axis_kind,
        x_unit=x_unit,
        x_range=x_range,
        image=preview_image(record),
        selected=selected,
        dimmed=not card_matches_compare_filter(axis_kind, compare_filter),
        replacement_armed=replacement_armed,
        show_title=show_title,
        show_source=show_source,
        show_card_actions=show_card_actions,
    )


def card_models_for_slots(
    slot_refs: Mapping[str, UltraViewRef | None],
    *,
    chrome_by_key: Mapping[tuple[str, str], LibraryChromeFacts] | None = None,
    records: Mapping[UltraViewRef, Any] | None = None,
    statuses: Mapping[UltraViewRef, str] | None = None,
    exists: Mapping[UltraViewRef, bool] | None = None,
    selected: Collection[UltraViewRef] | None = None,
    compare_filter: str = COMPARE_FILTER_ALL,
    replacement_ref: UltraViewRef | None = None,
    replacement_slot: str | None = None,
    show_title: bool = True,
    show_source: bool = True,
    show_card_actions: bool = False,
) -> dict[str, CardViewModel | None]:
    """Build a template slot map. Empty slots stay ``None``."""
    chrome_by_key = chrome_by_key or {}
    records = records or {}
    statuses = statuses or {}
    exists = exists or {}
    selected_refs = selected or ()
    models: dict[str, CardViewModel | None] = {}
    for slot_id, ref in slot_refs.items():
        if ref is None:
            models[slot_id] = None
            continue
        models[slot_id] = card_view_model(
            slot_id=slot_id,
            ref=ref,
            live=exists.get(ref, True),
            chrome=chrome_by_key.get((ref.section, ref.view_id)),
            record=records.get(ref),
            explicit_status=statuses[ref] if ref in statuses else None,
            selected=ref in selected_refs,
            compare_filter=compare_filter,
            replacement_armed=replacement_armed_for(
                ref, slot_id, replacement_ref, replacement_slot
            ),
            show_title=show_title,
            show_source=show_source,
            show_card_actions=show_card_actions,
        )
    return models


def axis_records_from_models(
    models: Iterable[CardViewModel | None],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for model in models:
        if model is None or not model.axis_kind:
            continue
        records.append(
            {
                "axis_kind": model.axis_kind,
                "x_unit": model.x_unit,
                "x_range": model.x_range,
            }
        )
    return records


def tray_chrome_maps(
    refs: Sequence[UltraViewRef],
    *,
    chrome_by_key: Mapping[tuple[str, str], LibraryChromeFacts] | None = None,
    records: Mapping[UltraViewRef, Any] | None = None,
    statuses: Mapping[UltraViewRef, str] | None = None,
    exists: Mapping[UltraViewRef, bool] | None = None,
) -> tuple[
    dict[tuple[str, str], str],
    dict[tuple[str, str], str],
    dict[tuple[str, str], str],
]:
    """Titles / colors / statuses for unplaced tray rows, keyed by (section, view_id)."""
    chrome_by_key = chrome_by_key or {}
    records = records or {}
    statuses = statuses or {}
    exists = exists or {}
    titles: dict[tuple[str, str], str] = {}
    colors: dict[tuple[str, str], str] = {}
    status_map: dict[tuple[str, str], str] = {}
    for ref in refs:
        key = (ref.section, ref.view_id)
        live = exists.get(ref, True)
        chrome = chrome_by_key.get(key)
        record = records.get(ref)
        explicit = statuses[ref] if ref in statuses else None
        titles[key] = title_for(ref, live, chrome, record)
        colors[key] = color_for(ref, live, chrome, record)
        status_map[key] = status_for(explicit, live, record)
    return titles, colors, status_map
