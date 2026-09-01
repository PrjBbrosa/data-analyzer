"""Confirm WinWert layout import and commit ordinary time Views in one shot."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from PyQt5.QtWidgets import QCheckBox, QMessageBox

from mf4_analyzer.io.wwt_document import (
    CODE_MISSING_FORMULA_REF,
    CODE_UNKNOWN_RECORD,
    CODE_UNSUPPORTED_FORMULA,
    CODE_VIEW_CAP,
    WwtIssue,
    format_wwt_import_summary as format_wwt_import_summary_io,
    format_wwt_issue_for_user,
    parse_wwt_issue,
)
from mf4_analyzer.ui.view_state import default_view_tab_color, is_reusable_blank_view
from mf4_analyzer.ui.wwt_view_import import (
    build_registered_record_map,
    build_wwt_view_proposals,
    visible_y_windows,
)
from mf4_analyzer.ui_kit.message_box_buttons import fit_message_box_buttons_to_text

ACCEPT_TEXT = "创建时域 View 并绘图"
REJECT_TEXT = "仅加载数据"
APPLY_TO_REMAINING_TEXT = "对本次剩余 WWT 使用此选择"


class WwtBatchChoice(Enum):
    ASK = "ask"
    APPLY_LAYOUT = "apply_layout"
    LOAD_DATA_ONLY = "load_data_only"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class WwtLayoutPromptResult:
    accepted: bool
    apply_to_remaining: bool = False


_MISSING = object()


def coerce_layout_prompt(value) -> WwtLayoutPromptResult:
    """Accept the typed prompt, a raw bool, or a duck-typed decision.

    Monkeypatched tests may return ``bool`` (``apply_to_remaining=False``)
    or an object with ``.accepted`` / ``.apply_to_remaining``. Missing
    attributes are a TypeError, not a silent False.
    """
    if isinstance(value, WwtLayoutPromptResult):
        return value
    if isinstance(value, bool):
        return WwtLayoutPromptResult(accepted=value, apply_to_remaining=False)
    accepted = getattr(value, "accepted", _MISSING)
    remaining = getattr(value, "apply_to_remaining", _MISSING)
    if accepted is _MISSING or remaining is _MISSING:
        raise TypeError(
            "WWT layout prompt must be bool or have accepted and "
            f"apply_to_remaining, got {type(value).__name__}"
        )
    return WwtLayoutPromptResult(
        accepted=bool(accepted),
        apply_to_remaining=bool(remaining),
    )

# Axis-planning notes are not degraded-import facts and should not produce a
# warning toast after the ordinary TimeDomain Views are created.
_SILENT_CODES = frozenset({
    "hidden_axis",
    "auto_range",
})


@dataclass(frozen=True)
class WwtImportOutcome:
    detected: int
    created: int
    view_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    issues: tuple[WwtIssue, ...] = field(default_factory=tuple)
    summary: str = ""
    accepted: bool = False


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
    layout_line = f"可按 WinWert 窗口创建 {create} 个时域 View 并绘图。"
    body = (
        f"检测到 {detected} 个 WinWert 数据窗口和 {formulas} 个可用计算通道。\n"
        f"{layout_line}"
    )
    if kept < detected:
        dropped = detected - kept
        reason = _classify_unkept_windows(document, proposals)
        body += f"\n其中 {dropped} 个窗口未生成 View（{reason}）。"
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


_CONCRETE_FORMULA_CODES = frozenset({
    CODE_MISSING_FORMULA_REF,
    "formula_axis_mismatch",
    "formula_shape_mismatch",
    "formula_no_finite_values",
    "formula_nonfinite_values",
    "formula_cycle",
})
_FORMULA_SKIP_MARK = " (公式:"


def _skip_channel_name(detail: str) -> str:
    text = str(detail or "").strip()
    if _FORMULA_SKIP_MARK in text:
        return text.split(_FORMULA_SKIP_MARK, 1)[0].strip()
    return text


def _record_name_for_issue(document, issue: WwtIssue) -> str:
    records = getattr(document, "records", None) or ()
    detail = issue.detail or ""
    marker = "record "
    lowered = detail.lower()
    start = lowered.find(marker)
    if start < 0:
        return ""
    token = detail[start + len(marker):].split(":", 1)[0].strip().split()[0]
    try:
        index = int(token)
    except ValueError:
        return ""
    if 0 <= index < len(records):
        return str(getattr(records[index], "name", "") or "")
    return ""


def collect_wwt_import_issues(
    document,
    registered,
    proposals,
    *,
    created: int = 0,
    detected: int | None = None,
) -> tuple[WwtIssue, ...]:
    """Grade document + ordinary View proposal into stable-code issues."""
    issues: list[WwtIssue] = []
    skip_seen: set[str] = set()
    formula_skips: list[tuple[str, str]] = []
    other_skips: list[str] = []
    for group in getattr(document, "groups", ()) or ():
        metadata = (group or {}).get("source_metadata") or {}
        for entry in metadata.get("skipped_channels") or []:
            name = _skipped_name(entry)
            if not name or name in skip_seen:
                continue
            skip_seen.add(name)
            if _FORMULA_SKIP_MARK in name:
                formula_skips.append((_skip_channel_name(name), name))
            else:
                other_skips.append(name)
        break

    concrete_names: set[str] = set()
    for text in getattr(document, "diagnostics", ()) or ():
        issue = parse_wwt_issue(text)
        if issue.code == CODE_UNSUPPORTED_FORMULA:
            continue
        issues.append(issue)
        if issue.code in _CONCRETE_FORMULA_CODES:
            name = _record_name_for_issue(document, issue)
            if name:
                concrete_names.add(name)

    covered_formula = set(concrete_names)
    for channel, raw in formula_skips:
        if channel in covered_formula:
            continue
        issues.append(WwtIssue(CODE_UNSUPPORTED_FORMULA, raw))
        covered_formula.add(channel)
    for text in getattr(document, "diagnostics", ()) or ():
        issue = parse_wwt_issue(text)
        if issue.code != CODE_UNSUPPORTED_FORMULA:
            continue
        name = _record_name_for_issue(document, issue)
        if name and name in covered_formula:
            continue
        issues.append(issue)
        if name:
            covered_formula.add(name)
    for name in other_skips:
        if name in covered_formula:
            continue
        issues.append(WwtIssue(CODE_UNKNOWN_RECORD, name))

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
    return _unique_issues(issues)


def format_wwt_import_summary(
    issues,
    *,
    accepted: bool = False,
    document=None,
) -> str:
    """User-facing degraded-import summary. Delegates to the io formatter."""
    return format_wwt_import_summary_io(
        issues, document=document, accepted=accepted,
    )


class WwtImportCoordinator:
    def __init__(self, window):
        self._window = window
        self._batch_active = False
        self._batch_choice = WwtBatchChoice.ASK

    def begin_open_batch(self) -> None:
        self._batch_active = True
        self._batch_choice = WwtBatchChoice.ASK

    def end_open_batch(self) -> None:
        self._batch_active = False
        self._batch_choice = WwtBatchChoice.ASK

    def _ask_layout(self, body: str, informative: str) -> WwtLayoutPromptResult:
        box = QMessageBox(self._window)
        box.setWindowTitle("WinWert 排版")
        box.setIcon(QMessageBox.Question)
        box.setText(body)
        if informative:
            box.setInformativeText(informative)
        accept = box.addButton(ACCEPT_TEXT, QMessageBox.AcceptRole)
        box.addButton(REJECT_TEXT, QMessageBox.RejectRole)
        box.setDefaultButton(accept)
        checkbox = QCheckBox(APPLY_TO_REMAINING_TEXT)
        checkbox.setChecked(False)
        box.setCheckBox(checkbox)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        return WwtLayoutPromptResult(
            accepted=box.clickedButton() is accept,
            apply_to_remaining=bool(checkbox.isChecked()),
        )

    def _resolve_layout_prompt(
        self, body: str, informative: str
    ) -> WwtLayoutPromptResult:
        if self._batch_active:
            if self._batch_choice is WwtBatchChoice.APPLY_LAYOUT:
                return WwtLayoutPromptResult(accepted=True, apply_to_remaining=False)
            if self._batch_choice is WwtBatchChoice.LOAD_DATA_ONLY:
                return WwtLayoutPromptResult(accepted=False, apply_to_remaining=False)
        return coerce_layout_prompt(self._ask_layout(body, informative))

    def _remember_prompt_if_requested(self, prompt: WwtLayoutPromptResult) -> None:
        if not self._batch_active or not prompt.apply_to_remaining:
            return
        self._batch_choice = (
            WwtBatchChoice.APPLY_LAYOUT
            if prompt.accepted
            else WwtBatchChoice.LOAD_DATA_ONLY
        )

    def offer_layout(
        self, document, fids: list[str], *, reuse_blank: bool | None = None
    ) -> WwtImportOutcome | None:
        window = self._window
        if getattr(window, "_restoring_project", False):
            return None
        if not fids:
            # NOT_APPLICABLE: do not consume or overwrite a remembered choice.
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
            extra_warnings: tuple[str, ...] = (),
        ) -> WwtImportOutcome:
            issues = list(collect_wwt_import_issues(
                document,
                registered,
                proposals,
                created=created,
                detected=len(proposals),
            ))
            for text in extra_warnings or ():
                issues.append(parse_wwt_issue(text))
            issues = _unique_issues(issues)
            summary = format_wwt_import_summary(
                issues, document=document, accepted=accepted,
            )
            warning_texts = []
            if summary:
                warning_texts.append(summary)
            else:
                for issue in issues:
                    if issue.code in _SILENT_CODES:
                        continue
                    text = format_wwt_issue_for_user(issue, document=document)
                    if text:
                        warning_texts.append(text)
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
            # NOT_APPLICABLE: no askable layout; keep the current batch choice.
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
        prompt = self._resolve_layout_prompt(body, informative)
        self._remember_prompt_if_requested(prompt)
        if not prompt.accepted:
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
        created = len(indexes)
        return _outcome(
            created=created,
            view_ids=view_ids,
            accepted=True,
            extra_warnings=tuple(extra),
        )
