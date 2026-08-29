"""Confirm WinWert layout import and commit ordinary time Views in one shot."""
from __future__ import annotations

from dataclasses import dataclass, field

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
from mf4_analyzer.ui.view_state import MAX_VIEWS, is_reusable_blank_view
from mf4_analyzer.ui.wwt_view_import import (
    build_registered_record_map,
    build_wwt_view_proposals,
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

    total = len(proposals) if detected is None else int(detected)
    if 0 <= created < total:
        issues.append(WwtIssue(
            CODE_VIEW_CAP,
            f"已生成 {created}/{total} 个 WinWert View",
        ))
    if overlap_count:
        issues.append(WwtIssue(
            CODE_EXACT_OVERLAP,
            "1 个重叠窗口已放入未放置区",
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
            )

        if not proposals:
            return _outcome(created=0)

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
            return _outcome(created=0)

        capture = getattr(window, "_capture_current_view", None)
        if callable(capture):
            capture()
        keep = proposals[: max(0, available)]
        states = [item.state for item in keep]
        indexes = manager.insert_states(
            states, reuse_blank=bool(reuse_blank), active_offset=0
        )
        view_ids = tuple(manager.views[idx].view_id for idx in indexes)
        extra = []
        for item in keep:
            extra.extend(item.warnings)
        overlaps = _exact_overlap_pairs(keep)
        ultra = getattr(window, "_ultraview", None)
        adder = getattr(ultra, "add_time_views_from_native_layout", None) if ultra else None
        if callable(adder) and indexes:
            items = [
                (manager.views[idx].view_id, proposal.rect_mm)
                for idx, proposal in zip(indexes, keep)
            ]
            extra.extend(_projection_warnings(adder(items)))
        return _outcome(
            created=len(indexes),
            view_ids=view_ids,
            accepted=True,
            overlap_count=len(overlaps),
            extra_warnings=tuple(extra),
        )
