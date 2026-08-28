"""Confirm WinWert layout import and commit ordinary time Views in one shot."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.ui.view_state import MAX_VIEWS, is_reusable_blank_view
from mf4_analyzer.ui.wwt_view_import import (
    build_registered_record_map,
    build_wwt_view_proposals,
)
from mf4_analyzer.ui_kit.message_box_buttons import fit_message_box_buttons_to_text

ACCEPT_TEXT = "按 WinWert 排版并绘图"
REJECT_TEXT = "仅加载数据"


@dataclass(frozen=True)
class WwtImportOutcome:
    detected: int
    created: int
    view_ids: tuple[str, ...]
    warnings: tuple[str, ...]


def _exact_overlap_pairs(proposals) -> list[tuple[int, int]]:
    pairs = []
    seen = []
    for proposal in proposals:
        rect = proposal.rect_mm
        for previous in seen:
            if (
                abs(rect.x - previous.rect_mm.x) <= 1e-6
                and abs(rect.y - previous.rect_mm.y) <= 1e-6
                and abs(rect.width - previous.rect_mm.width) <= 1e-6
                and abs(rect.height - previous.rect_mm.height) <= 1e-6
            ):
                pairs.append((proposal.window_index, previous.window_index))
                break
        seen.append(proposal)
    return pairs


def layout_dialog_text(document, proposals, *, available: int) -> tuple[str, str]:
    detected = len(proposals)
    formulas = sum(
        1
        for record in document.records
        if record.tag == "Pars" and record.values is not None
    )
    create = min(detected, available)
    body = (
        f"检测到 {detected} 个 WinWert 数据窗口和 {formulas} 个可用计算通道。\n"
        f"可按原排版生成 {create} 个时域 View，并同步加入 UltraView。"
    )
    overlaps = _exact_overlap_pairs(proposals)
    if overlaps:
        later, earlier = overlaps[0]
        body += (
            f"\n第 {later + 1} 个窗口与第 {earlier + 1} 个位置重叠，"
            "将放入 UltraView 未放置区。"
        )
    informative = ""
    if create < detected:
        informative = f"检测到 {detected} 个，可创建 {create} 个"
    return body, informative


class WwtImportCoordinator:
    def __init__(self, window):
        self._window = window

    def _ask_layout(self, body: str, informative: str) -> bool:
        box = QMessageBox(self._window)
        box.setWindowTitle("WinWert 排版")
        box.setIcon(QMessageBox.Question)
        box.setText(body)
        if informative:
            box.setInformativeText(informative)
        accept = box.addButton(ACCEPT_TEXT, QMessageBox.AcceptRole)
        box.addButton(REJECT_TEXT, QMessageBox.RejectRole)
        box.setDefaultButton(accept)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        return box.clickedButton() is accept

    def offer_layout(
        self, document, fids: list[str], *, reuse_blank: bool | None = None
    ) -> WwtImportOutcome | None:
        window = self._window
        if getattr(window, "_restoring_project", False):
            return None
        if not fids:
            return WwtImportOutcome(0, 0, (), ())
        groups = []
        files = getattr(window, "files", {}) or {}
        for fid in fids:
            fd = files.get(fid)
            if fd is None:
                continue
            groups.append({
                "channel_metadata": getattr(fd, "channel_metadata", {}) or {},
                "source_metadata": getattr(fd, "source_metadata", {}) or {},
            })
        for fid in fids:
            fd = files.get(fid)
            if fd is None:
                continue
            metadata = dict(getattr(fd, "source_metadata", None) or {})
            metadata["wwt_record_store"] = document.records
            fd.source_metadata = metadata
        registered = build_registered_record_map(groups, fids)
        proposals = build_wwt_view_proposals(document, registered)
        if not proposals:
            return WwtImportOutcome(0, 0, (), tuple(registered.warnings))

        manager = window.view_manager
        if reuse_blank is None:
            reuse_blank = bool(
                manager.views and is_reusable_blank_view(manager.views[0])
            )
        reusable = 1 if reuse_blank and manager.views else 0
        available = MAX_VIEWS - len(manager.views) + reusable
        body, informative = layout_dialog_text(
            document, proposals, available=max(0, available)
        )
        if not self._ask_layout(body, informative):
            return WwtImportOutcome(len(proposals), 0, (), ())

        capture = getattr(window, "_capture_current_view", None)
        if callable(capture):
            capture()
        keep = proposals[: max(0, available)]
        states = [item.state for item in keep]
        indexes = manager.insert_states(
            states, reuse_blank=bool(reuse_blank), active_offset=0
        )
        view_ids = tuple(manager.views[idx].view_id for idx in indexes)
        warnings = []
        for item in keep:
            warnings.extend(item.warnings)
        if len(keep) < len(proposals):
            warnings.append(
                f"已生成 {len(keep)}/{len(proposals)} 个 WinWert View"
            )
        overlaps = _exact_overlap_pairs(keep)
        if overlaps:
            warnings.append("1 个重叠窗口已放入未放置区")
        toast = getattr(window, "toast", None)
        if callable(toast) and (len(keep) < len(proposals) or overlaps):
            if len(keep) < len(proposals):
                toast(f"已生成 {len(keep)}/{len(proposals)} 个 WinWert View", "warn")
            elif overlaps:
                toast("1 个重叠窗口已放入未放置区", "warn")
        ultra = getattr(window, "_ultraview", None)
        adder = getattr(ultra, "add_time_views_from_native_layout", None) if ultra else None
        if callable(adder) and indexes:
            items = [
                (manager.views[idx].view_id, proposal.rect_mm)
                for idx, proposal in zip(indexes, keep)
            ]
            adder(items)
        return WwtImportOutcome(
            detected=len(proposals),
            created=len(indexes),
            view_ids=view_ids,
            warnings=tuple(dict.fromkeys(warnings)),
        )
