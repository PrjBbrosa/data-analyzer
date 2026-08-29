"""Confirm WinWert layout import and commit ordinary time Views in one shot."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.io.loader import format_skipped_channels_notice
from mf4_analyzer.io.wwt_document import (
    CODE_EXACT_OVERLAP,
    CODE_SKIPPED_CHANNEL,
    CODE_UNKNOWN_RECORD,
    CODE_UNSUPPORTED_FORMULA,
    CODE_VIEW_CAP,
    WwtIssue,
    format_wwt_issue,
    parse_wwt_issue,
)
from mf4_analyzer.ui.view_state import default_view_tab_color, is_reusable_blank_view
from mf4_analyzer.ui.wwt_view_import import (
    build_registered_record_map,
    build_wwt_view_proposals,
    visible_y_windows,
)
from mf4_analyzer.ui_kit.message_box_buttons import fit_message_box_buttons_to_text

ACCEPT_TEXT = "按 WinWert 排版并绘图"
REJECT_TEXT = "仅加载数据"

# Placement is explained by the confirm dialog; UltraView already maps
# membership/placed/collision caps to Chinese copy. Do not yellow-toast
# those codes again. Axis-planning notes are not degraded-import facts.
_SILENT_CODES = frozenset({
    CODE_EXACT_OVERLAP,
    "hidden_axis",
    "auto_range",
    "quantized_collision",
    "duplicate_ref",
    "invalid_rect",
    "membership_limit",
    "placed_limit",
    "grid_full",
    "grid_collision",
    "board_limit",
})


def _projection_warnings(result) -> tuple[str, ...]:
    """Extract native-layout warnings from ``add_time_views_from_native_layout``."""
    warnings = getattr(result, "warnings", None)
    if warnings is not None:
        return tuple(str(item) for item in warnings if item)
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], tuple)
        and isinstance(result[1], (tuple, list))
    ):
        return tuple(str(item) for item in result[1] if item)
    return ()


@dataclass(frozen=True)
class WwtImportOutcome:
    detected: int
    created: int
    view_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    issues: tuple[WwtIssue, ...] = field(default_factory=tuple)
    summary: str = ""
    accepted: bool = False
    placed_count: int = 0
    unplaced_count: int = 0
    board_id: str = ""
    unprojected_count: int = 0
    generated_ids: tuple[str, ...] = ()


def _wwt_stem_for_fids(window, fids) -> str:
    """Filename stem of the physical ``.wwt`` that produced ``fids``."""
    files = getattr(window, "files", {}) or {}
    for fid in fids or ():
        fd = files.get(fid)
        if fd is None:
            continue
        path = getattr(fd, "filepath", None)
        if path is None:
            path = getattr(fd, "filename", None)
        if path:
            stem = Path(path).stem
            if stem:
                return stem
    return "WinWert"


def _layout_index(item) -> int:
    if hasattr(item, "window_index"):
        return int(item.window_index)
    return int(item.index)


def _exact_overlap_pairs(items) -> list[tuple[int, int]]:
    pairs = []
    seen = []
    for item in items:
        rect = item.rect_mm
        idx = _layout_index(item)
        for previous in seen:
            prev = previous.rect_mm
            if (
                abs(rect.x - prev.x) <= 1e-6
                and abs(rect.y - prev.y) <= 1e-6
                and abs(rect.width - prev.width) <= 1e-6
                and abs(rect.height - prev.height) <= 1e-6
            ):
                pairs.append((idx, _layout_index(previous)))
                break
        seen.append(item)
    return pairs


def _classify_unkept_windows(document, proposals) -> str:
    """Short reason label when kept proposals are fewer than file-real windows."""
    codes: list[str] = []
    kept = {getattr(item, "window_index", None) for item in proposals or ()}
    if any(window.index not in kept for window in visible_y_windows(document)):
        codes.append("dropped_window")
    for proposal in proposals or ():
        for text in getattr(proposal, "warnings", ()) or ():
            code = parse_wwt_issue(text).code
            if code in {"dropped_curve", "unknown_record", "dropped_window"}:
                codes.append(code)
    unique = list(dict.fromkeys(codes))
    labels = []
    if "unknown_record" in unique or "dropped_curve" in unique:
        labels.append("曲线无法解析")
    if "dropped_window" in unique:
        labels.append("窗口未生成")
    return "、".join(labels) if labels else "可见曲线无法绑定"


def layout_dialog_text(document, proposals, *, available: int) -> tuple[str, str]:
    file_windows = visible_y_windows(document)
    detected = len(file_windows)
    kept = len(proposals or ())
    formulas = sum(
        1
        for record in document.records
        if record.tag == "Pars" and record.values is not None
    )
    create = min(kept, available)
    if create <= 1:
        layout_line = (
            f"可按原排版生成 {create} 个时域 View，仅生成时域 View。"
        )
    else:
        layout_line = (
            f"可按原排版生成 {create} 个时域 View，并同步到独立 Board。"
        )
    body = (
        f"检测到 {detected} 个 WinWert 数据窗口和 {formulas} 个可用计算通道。\n"
        f"{layout_line}"
    )
    if kept < detected:
        dropped = detected - kept
        reason = _classify_unkept_windows(document, proposals)
        body += f"\n其中 {dropped} 个窗口未生成 View（{reason}）。"
    overlaps = _exact_overlap_pairs(file_windows)
    if overlaps and create >= 2:
        parts = [
            f"第 {later + 1} 个窗口与第 {earlier + 1} 个位置重叠"
            for later, earlier in overlaps
        ]
        body += "\n" + "，".join(parts) + "，将放入 UltraView 未放置区。"
    informative = ""
    if create < detected:
        informative = f"检测到 {detected} 个，可创建 {create} 个"
    return body, informative


def _issue_key(issue: WwtIssue) -> tuple[str, str]:
    return (issue.code, issue.detail)


def _unique_issues(issues: list[WwtIssue]) -> tuple[WwtIssue, ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[WwtIssue] = []
    for issue in issues:
        key = _issue_key(issue)
        if key in seen or not issue.code:
            continue
        seen.add(key)
        unique.append(issue)
    return tuple(unique)


def _skipped_name(entry) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name") or "")
    return str(entry or "")


def collect_wwt_import_issues(
    document,
    registered,
    proposals,
    *,
    created: int = 0,
    detected: int | None = None,
    overlap_count: int = 0,
) -> tuple[WwtIssue, ...]:
    """Grade document + proposal + placement into stable-code issues."""
    issues: list[WwtIssue] = []
    skip_seen: set[str] = set()
    formula_from_skip = False
    for group in getattr(document, "groups", ()) or ():
        metadata = (group or {}).get("source_metadata") or {}
        for entry in metadata.get("skipped_channels") or []:
            name = _skipped_name(entry)
            if not name or name in skip_seen:
                continue
            skip_seen.add(name)
            if " (公式:" in name:
                formula_from_skip = True
                issues.append(WwtIssue(CODE_UNSUPPORTED_FORMULA, name))
            else:
                issues.append(WwtIssue(CODE_UNKNOWN_RECORD, name))
        break

    for text in getattr(document, "diagnostics", ()) or ():
        issue = parse_wwt_issue(text)
        if issue.code == CODE_UNSUPPORTED_FORMULA and formula_from_skip:
            continue
        issues.append(issue)

    for text in getattr(registered, "warnings", ()) or ():
        issues.append(parse_wwt_issue(text))
    for proposal in proposals or ():
        for text in getattr(proposal, "warnings", ()) or ():
            issues.append(parse_wwt_issue(text))

    records = getattr(document, "records", ()) or ()
    n_records = len(records)
    kept_indexes = {
        getattr(proposal, "window_index", None) for proposal in proposals or ()
    }
    for window in visible_y_windows(document):
        y_rows = window.curves[1:] if window.curves else ()
        visible_rows = [row for row in y_rows if getattr(row, "visible", False)]
        if window.index not in kept_indexes:
            issues.append(WwtIssue(
                "dropped_window",
                f"window {window.index + 1}",
            ))
        for row in visible_rows:
            record_index = getattr(row, "record_index", -1)
            if record_index < 0 or record_index >= n_records:
                issues.append(WwtIssue(
                    "dropped_curve",
                    f"window {window.index + 1} record {record_index}",
                ))

    total = len(proposals) if detected is None else int(detected)
    if 0 <= created < total:
        issues.append(WwtIssue(
            CODE_VIEW_CAP,
            f"已生成 {created}/{total} 个 WinWert View",
        ))
    if overlap_count:
        issues.append(WwtIssue(
            CODE_EXACT_OVERLAP,
            f"{overlap_count} 个重叠窗口已放入未放置区",
        ))
    return _unique_issues(issues)


def _is_channel_skip_notice(issue: WwtIssue) -> bool:
    """True for retained-not-imported names that still use the 未导入 template."""
    detail = issue.detail or ""
    if issue.code == CODE_SKIPPED_CHANNEL:
        return True
    if issue.code == CODE_UNSUPPORTED_FORMULA and " (公式:" in detail:
        return True
    if issue.code != CODE_UNKNOWN_RECORD:
        return False
    return bool(detail) and "显示块" not in detail and "window " not in detail.lower()


def format_wwt_import_summary(
    issues,
    *,
    accepted: bool = False,
) -> str:
    """One user-facing degraded-import summary. Empty → no yellow toast."""
    toastable: list[WwtIssue] = []
    for issue in issues or ():
        if issue.code in _SILENT_CODES:
            continue
        if issue.code == CODE_VIEW_CAP and not accepted:
            continue
        toastable.append(issue)
    if not toastable:
        return ""

    skip_names: list[str] = []
    others: list[str] = []
    for issue in toastable:
        detail = issue.detail or issue.code
        if _is_channel_skip_notice(issue):
            skip_names.append(detail)
        else:
            others.append(detail if detail else format_wwt_issue(issue.code))
    parts: list[str] = []
    skip_notice = format_skipped_channels_notice(skip_names)
    if skip_notice:
        parts.append(skip_notice)
    parts.extend(others)
    return "；".join(dict.fromkeys(part for part in parts if part))


def format_wwt_placement_summary(outcome) -> str:
    """Accepted-import completion line. Empty when nothing was created."""
    if not getattr(outcome, "accepted", False):
        return ""
    created = int(getattr(outcome, "created", 0) or 0)
    if created <= 0:
        return ""
    placed = int(getattr(outcome, "placed_count", 0) or 0)
    unplaced = int(getattr(outcome, "unplaced_count", 0) or 0)
    unprojected = int(getattr(outcome, "unprojected_count", 0) or 0)
    if created < 2 or (placed == 0 and unplaced == 0 and unprojected == 0):
        return f"已生成 {created} 个 WinWert View"
    text = (
        f"已生成 {created} 个 WinWert View："
        f"{placed} 个已放置，{unplaced} 个在未放置区"
    )
    if unprojected:
        text += f"，{unprojected} 个未投影"
    return text


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
            channel_metadata = getattr(fd, "channel_metadata", {}) or {}
            groups.append({
                "channel_metadata": channel_metadata,
                "channel_display_names": {
                    channel: fd.get_prefixed_channel(channel)
                    for channel in channel_metadata
                },
                "source_metadata": getattr(fd, "source_metadata", {}) or {},
            })
        registered = build_registered_record_map(groups, fids)
        proposals = build_wwt_view_proposals(document, registered)

        def _outcome(
            *,
            created: int,
            view_ids: tuple[str, ...] = (),
            accepted: bool = False,
            overlap_count: int = 0,
            extra_warnings: tuple[str, ...] = (),
            placed_count: int = 0,
            unplaced_count: int = 0,
            board_id: str = "",
            unprojected_count: int = 0,
            generated_ids: tuple[str, ...] = (),
        ) -> WwtImportOutcome:
            issues = list(collect_wwt_import_issues(
                document,
                registered,
                proposals,
                created=created,
                detected=len(proposals),
                overlap_count=overlap_count,
            ))
            for text in extra_warnings or ():
                issues.append(parse_wwt_issue(text))
            issues = _unique_issues(issues)
            summary = format_wwt_import_summary(issues, accepted=accepted)
            warning_texts = [
                issue.detail or format_wwt_issue(issue.code)
                for issue in issues
                if issue.code not in _SILENT_CODES
            ]
            warnings = tuple(dict.fromkeys(text for text in warning_texts if text))
            return WwtImportOutcome(
                detected=len(proposals),
                created=created,
                view_ids=view_ids,
                warnings=warnings,
                issues=issues,
                summary=summary,
                accepted=accepted,
                placed_count=placed_count,
                unplaced_count=unplaced_count,
                board_id=board_id,
                unprojected_count=unprojected_count,
                generated_ids=generated_ids,
            )

        if not proposals:
            return _outcome(created=0)

        manager = window.view_manager
        if reuse_blank is None:
            reuse_blank = bool(
                manager.views and is_reusable_blank_view(manager.views[0])
            )
        reusable = 1 if reuse_blank and manager.views else 0
        available = manager.max_views - len(manager.views) + reusable
        body, informative = layout_dialog_text(
            document, proposals, available=max(0, available)
        )
        if not self._ask_layout(body, informative):
            return _outcome(created=0)

        capture = getattr(window, "_capture_current_view", None)
        if callable(capture):
            capture()
        keep = proposals[: max(0, available)]
        color_base = 0 if reusable else len(manager.views)
        for offset, item in enumerate(keep):
            item.state.tab_color = default_view_tab_color(color_base + offset)
        indexes = manager.insert_states(
            [item.state for item in keep],
            reuse_blank=bool(reuse_blank),
            active_offset=0,
        )
        for idx in indexes:
            manager.views[idx].tab_color = default_view_tab_color(idx)
        view_ids = tuple(manager.views[idx].view_id for idx in indexes)
        extra = []
        for item in keep:
            extra.extend(item.warnings)
        overlaps = _exact_overlap_pairs(keep)
        created = len(indexes)
        placed_count = 0
        unplaced_count = 0
        unprojected_count = 0
        board_id = ""
        generated_ids: tuple[str, ...] = ()
        if created >= 2:
            ultra = getattr(window, "_ultraview", None)
            adder = (
                getattr(ultra, "add_time_views_from_native_layout", None)
                if ultra else None
            )
            if callable(adder):
                items = [
                    (manager.views[idx].view_id, proposal.rect_mm)
                    for idx, proposal in zip(indexes, keep)
                ]
                result = adder(
                    items,
                    board_name=_wwt_stem_for_fids(window, fids),
                    dedicated_board=True,
                    reuse_empty_board=True,
                )
                extra.extend(_projection_warnings(result))
                placed_ids = getattr(result, "placed_view_ids", None)
                if placed_ids is None:
                    placed_ids = result[0] if isinstance(result, tuple) and result else ()
                unplaced_ids = tuple(getattr(result, "unplaced_ids", ()) or ())
                generated_ids = tuple(getattr(result, "generated_ids", None) or ())
                if not generated_ids:
                    generated_ids = tuple(placed_ids or ()) + unplaced_ids
                board_id = str(getattr(result, "board_id", "") or "")
                placed_count = len(tuple(placed_ids or ()))
                unplaced_count = len(unplaced_ids)
                unprojected_count = max(
                    0, len(generated_ids) - placed_count - unplaced_count
                )
        return _outcome(
            created=created,
            view_ids=view_ids,
            accepted=True,
            overlap_count=len(overlaps),
            extra_warnings=tuple(extra),
            placed_count=placed_count,
            unplaced_count=unplaced_count,
            board_id=board_id,
            unprojected_count=unprojected_count,
            generated_ids=generated_ids,
        )
