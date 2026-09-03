"""Immutable desktop-command metadata. No MainWindow, no live QUndoStack.

Menus, toolbar tooltips, hints, and QuickRef must project from this module
instead of hard-coding a second shortcut table. Bindings come from Qt
``QKeySequence.keyBindings`` (de-duplicated by PortableText) with an
explicit SaveAs fallback when the platform table is empty.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum

from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QAction


class CommandId(Enum):
    OPEN_PROJECT = "open_project"
    SAVE_PROJECT = "save_project"
    SAVE_PROJECT_AS = "save_project_as"
    QUIT = "quit"
    UNDO = "undo"
    REDO = "redo"
    FIND = "find"
    QUICK_REFERENCE = "quick_reference"
    NEXT_VIEW = "next_view"
    PREVIOUS_VIEW = "previous_view"
    VIEW_BACK = "view_back"
    VIEW_FORWARD = "view_forward"
    RESET_VIEW = "reset_view"
    RENAME = "rename"


class CommandScope(Enum):
    """Where the command is allowed to fire. Metadata only — not a widget."""

    WINDOW = "window"
    EDIT_OWNER = "edit_owner"
    CHART = "chart"
    VIEW = "view"


@dataclass(frozen=True)
class CommandMeta:
    command_id: CommandId
    label: str
    standard_key: object | None
    fallback: str | None
    scope: CommandScope
    help_text: str


_COMMANDS: dict[CommandId, CommandMeta] = {}


def _register(meta: CommandMeta) -> None:
    _COMMANDS[meta.command_id] = meta


_register(CommandMeta(
    CommandId.OPEN_PROJECT,
    "打开…",
    QKeySequence.Open,
    None,
    CommandScope.WINDOW,
    "打开数据文件或项目（.tlproj）",
))
_register(CommandMeta(
    CommandId.SAVE_PROJECT,
    "保存",
    QKeySequence.Save,
    None,
    CommandScope.WINDOW,
    "保存到当前 .tlproj 项目（未保存过则提示选择路径）",
))
_register(CommandMeta(
    CommandId.SAVE_PROJECT_AS,
    "另存为",
    QKeySequence.SaveAs,
    "Ctrl+Shift+S",
    CommandScope.WINDOW,
    "将当前会话另存为新的 .tlproj 项目",
))
_register(CommandMeta(
    CommandId.QUIT,
    "退出",
    QKeySequence.Quit,
    None,
    CommandScope.WINDOW,
    "退出应用（有未保存更改时先确认）",
))
_register(CommandMeta(
    CommandId.UNDO,
    "撤销",
    QKeySequence.Undo,
    None,
    CommandScope.EDIT_OWNER,
    "撤销当前编辑区域的上一步",
))
_register(CommandMeta(
    CommandId.REDO,
    "重做",
    QKeySequence.Redo,
    None,
    CommandScope.EDIT_OWNER,
    "重做当前编辑区域的下一步",
))
_register(CommandMeta(
    CommandId.FIND,
    "查找",
    QKeySequence.Find,
    None,
    CommandScope.WINDOW,
    "聚焦当前可搜索界面；否则打开操作速查搜索",
))
_register(CommandMeta(
    CommandId.QUICK_REFERENCE,
    "操作速查",
    None,
    "?",
    CommandScope.WINDOW,
    "打开或关闭操作速查",
))
_register(CommandMeta(
    CommandId.NEXT_VIEW,
    "下一个 View",
    None,
    None,
    CommandScope.VIEW,
    "切换到当前分区的下一个 View",
))
_register(CommandMeta(
    CommandId.PREVIOUS_VIEW,
    "上一个 View",
    None,
    None,
    CommandScope.VIEW,
    "切换到当前分区的上一个 View",
))
_register(CommandMeta(
    CommandId.VIEW_BACK,
    "视角后退",
    None,
    "Alt+Left",
    CommandScope.CHART,
    "当前图表视角后退",
))
_register(CommandMeta(
    CommandId.VIEW_FORWARD,
    "视角前进",
    None,
    "Alt+Right",
    CommandScope.CHART,
    "当前图表视角前进",
))
_register(CommandMeta(
    CommandId.RESET_VIEW,
    "复位视角",
    None,
    "Ctrl+R",
    CommandScope.CHART,
    "复位当前图表视角",
))
_register(CommandMeta(
    CommandId.RENAME,
    "重命名",
    None,
    "F2",
    CommandScope.VIEW,
    "重命名当前可编辑的 View、配置或行",
))


def metadata_for(command_id: CommandId) -> CommandMeta:
    return _COMMANDS[command_id]


def object_name_for(command_id: CommandId) -> str:
    return "action" + "".join(
        part.capitalize() for part in command_id.value.split("_")
    )


def _unique_key_bindings(
    standard_key, *, fallback_to_standard: bool = False
) -> list[QKeySequence]:
    """Return de-duplicated standard bindings, optionally with Qt fallback.

    Markup and UltraView retain the historical fallback when their platform
    table is empty. Command metadata deliberately opts out, except where its
    explicit ``fallback`` says otherwise.
    """
    seen: list[QKeySequence] = []
    texts: set[str] = set()
    for seq in QKeySequence.keyBindings(standard_key):
        if seq.isEmpty():
            continue
        portable = seq.toString(QKeySequence.PortableText)
        if not portable or portable in texts:
            continue
        texts.add(portable)
        seen.append(QKeySequence(seq))
    if not seen and fallback_to_standard:
        fallback = QKeySequence(standard_key)
        if not fallback.isEmpty():
            seen.append(fallback)
    return seen


def _fallback_for(meta: CommandMeta) -> str | None:
    """Return the platform-specific fallback declared by command semantics."""
    if meta.command_id == CommandId.NEXT_VIEW:
        # Qt maps Meta to the physical Control key on macOS. ``Ctrl+Tab``
        # instead means Command+Tab and is claimed by the app switcher.
        return "Meta+Tab" if sys.platform == "darwin" else "Ctrl+Tab"
    if meta.command_id == CommandId.PREVIOUS_VIEW:
        return "Meta+Shift+Tab" if sys.platform == "darwin" else "Ctrl+Shift+Tab"
    return meta.fallback


def bindings_for(command_id: CommandId) -> list[QKeySequence]:
    """Return de-duplicated platform bindings for ``command_id``.

    SaveAs: when ``keyBindings(SaveAs)`` is empty, register exactly one
    ``Ctrl+Shift+S`` fallback. Other commands with a fallback use it only
    when the standard table is missing or empty.
    """
    meta = metadata_for(command_id)
    seqs: list[QKeySequence] = []
    if meta.standard_key is not None:
        seqs = _unique_key_bindings(meta.standard_key)
    fallback_text = _fallback_for(meta)
    if not seqs and fallback_text:
        fallback = QKeySequence(fallback_text)
        if not fallback.isEmpty():
            seqs = [fallback]
    return seqs


def native_text_for(command_id: CommandId) -> str:
    """First binding as ``QKeySequence.NativeText``, or empty if unbound."""
    seqs = bindings_for(command_id)
    if not seqs:
        return ""
    return seqs[0].toString(QKeySequence.NativeText)


def tooltip_for(command_id: CommandId) -> str:
    """Help text plus NativeText; never a hard-coded Ctrl/Cmd token."""
    meta = metadata_for(command_id)
    native = native_text_for(command_id)
    if native:
        return f"{meta.help_text} ({native})"
    return meta.help_text


def iter_command_actions(parent=None):
    """Yield one ephemeral ``QAction`` per command. Do not cache these."""
    for command_id in CommandId:
        meta = metadata_for(command_id)
        action = QAction(meta.label, parent)
        action.setObjectName(object_name_for(command_id))
        seqs = bindings_for(command_id)
        if seqs:
            action.setShortcuts(seqs)
        action.setToolTip(tooltip_for(command_id))
        action.setStatusTip(meta.help_text)
        yield command_id, action
