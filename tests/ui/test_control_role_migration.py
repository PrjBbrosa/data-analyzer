"""P0 role-migration contracts for product control call sites.

The shared QSS deliberately gives ``icon`` controls compact geometry.  These
tests keep textual controls out of that role and exercise their real,
production-styled layout at the narrow rail width where an icon-only rule used
to collapse text below its font height.
"""
from __future__ import annotations

from pathlib import Path
import re

from PyQt5.QtWidgets import (
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_ROLE_CALL = re.compile(
    r'''setProperty\(\s*["']role["']\s*,\s*["'](?:tool|accent|destructive|create)["']\s*\)'''
)

# The variable names make this an action-level audit rather than a fragile
# repository-wide count.  Dedicated role namespaces intentionally stay out of
# this table (for example ``frf-segment`` and ``chart-choice``).
_EXPECTED_CALL_SITE_ROLES = {
    "mf4_analyzer/ui/file_navigator.py": (
        ("self._btn_close", "icon"),
        ("self.btn_auto_attach", "icon"),
        ("self._btn_kebab", "icon"),
    ),
    "mf4_analyzer/ui/widgets/stats.py": (("self._btn_expand", "icon"),),
    "mf4_analyzer/ui/inspector_sections/contextual_fft.py": (
        ("self.btn_rebuild", "icon"),
    ),
    "mf4_analyzer/ui/inspector_sections/contextual_fft_time.py": (
        ("self.btn_rebuild", "icon"),
    ),
    "mf4_analyzer/ui/inspector_sections/contextual_order.py": (
        ("self.btn_rebuild", "icon"),
    ),
    "mf4_analyzer/ui/widgets/channel_tree.py": (
        ("self.btn_all", "quiet"),
        ("self.btn_none", "quiet"),
        ("self.btn_selected_only", "quiet"),
        ("self.btn_edit", "quiet"),
    ),
    "mf4_analyzer/ui/drawers/rebuild_time_popover.py": (
        ("self.btn_cancel", "quiet"),
    ),
    "mf4_analyzer/ui/drawers/batch/frf_pair_editor.py": (
        ("self._add_button", "quiet"),
        ("remove", "quiet"),
    ),
    "mf4_analyzer/ui/widgets/channel_config_manager.py": (
        ("self.btn_batch", "quiet"),
        ("self.btn_delete_configs", "danger"),
        ("self.btn_delete_config", "danger"),
        ("self.btn_remove_channels", "danger"),
        ("discard", "danger"),
    ),
    "mf4_analyzer/ui/dialogs/channel_editor.py": (
        ("btn", "secondary"),
        ("btn2", "secondary"),
        ("self.btn_export", "secondary"),
    ),
    "mf4_analyzer/ui/drawers/batch/sheet.py": (
        ("self._btn_preview", "secondary"),
        ("self._btn_abort", "danger"),
    ),
    "mf4_analyzer/ui/drawers/batch/preview_dialog.py": (
        ("self._btn_regenerate", "secondary"),
        ("self._btn_cancel", "danger"),
    ),
    "mf4_analyzer/acquisition_ui/review_modal.py": (
        ("self._btn_discard", "danger"),
    ),
}


def test_product_role_call_sites_use_the_approved_semantic_roles():
    for relative_path, expected_calls in _EXPECTED_CALL_SITE_ROLES.items():
        source = (_REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for variable, role in expected_calls:
            expression = re.compile(
                rf'{re.escape(variable)}\.setProperty\(\s*"role"\s*,\s*"{role}"\s*\)'
            )
            assert expression.search(source), (
                f"{relative_path}: {variable} must use role={role!r}"
            )


def test_product_role_call_sites_no_longer_depend_on_legacy_aliases():
    offenders = []
    for source_path in (_REPO_ROOT / "mf4_analyzer").rglob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        if _LEGACY_ROLE_CALL.search(source):
            offenders.append(str(source_path.relative_to(_REPO_ROOT)))
    assert not offenders, "legacy role call sites remain: " + ", ".join(offenders)


def _assert_text_button_fits(button) -> None:
    """Assert against the styled content rect, not just the outer button box."""
    option = QStyleOptionButton()
    option.initFrom(button)
    option.text = button.text()
    option.icon = button.icon()
    contents = button.style().subElementRect(
        QStyle.SE_PushButtonContents, option, button,
    )
    text_rect = button.fontMetrics().boundingRect(button.text())

    assert button.height() >= text_rect.height() + 6
    assert contents.height() >= text_rect.height()
    assert contents.width() >= text_rect.width()


def test_quiet_text_actions_keep_full_height_and_text_with_production_qss(
    qapp, qtbot,
):
    """Textual rail actions must never inherit the compact icon geometry."""
    from mf4_analyzer.ui.drawers.batch.frf_pair_editor import FrfPairEditor
    from mf4_analyzer.ui.drawers.rebuild_time_popover import RebuildTimePopover
    from mf4_analyzer.ui_kit import load_stylesheet
    from mf4_analyzer.ui.widgets.channel_tree import MultiFileChannelWidget

    previous_stylesheet = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        channel_host = QWidget()
        channel_layout = QVBoxLayout(channel_host)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel = MultiFileChannelWidget(channel_host)
        channel_layout.addWidget(channel)
        channel_host.resize(288, 360)
        qtbot.addWidget(channel_host)
        channel_host.show()
        qtbot.wait(20)

        text_actions = (
            channel.btn_all,
            channel.btn_none,
            channel.btn_selected_only,
            channel.btn_edit,
        )
        assert all(action.property("role") == "quiet" for action in text_actions)
        assert all(action.isVisibleTo(channel_host) for action in text_actions)
        for action in text_actions:
            _assert_text_button_fits(action)

        popover = RebuildTimePopover(
            parent=channel_host, target_filename="x.mf4", current_fs=1000.0,
        )
        qtbot.addWidget(popover)
        popover.show()
        qtbot.wait(20)
        assert popover.btn_cancel.property("role") == "quiet"
        _assert_text_button_fits(popover.btn_cancel)

        pair_editor = FrfPairEditor()
        qtbot.addWidget(pair_editor)
        pair_editor.resize(288, 180)
        pair_editor.show()
        qtbot.wait(20)
        pair_actions = (pair_editor._add_button, pair_editor._groups[0].remove_button)
        assert all(action.property("role") == "quiet" for action in pair_actions)
        for action in pair_actions:
            _assert_text_button_fits(action)
    finally:
        qapp.setStyleSheet(previous_stylesheet)


def test_ambiguous_file_and_config_actions_match_their_rendered_content(
    qapp, qtbot,
):
    """The two classification exceptions are proved from actual widget geometry."""
    from mf4_analyzer.ui.channel_config import ChannelSelectionConfig
    from mf4_analyzer.ui.file_navigator import FileNavigator
    from mf4_analyzer.ui.widgets.channel_config_manager import (
        ChannelConfigManagerDialog,
    )
    from mf4_analyzer.ui_kit import load_stylesheet

    previous_stylesheet = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        navigator = FileNavigator()
        qtbot.addWidget(navigator)
        # The navigator's splitter needs a normal workspace height; forcing
        # its whole page below its layout minimum would compress any header
        # child and would not describe the actual 24px icon contract.
        navigator.resize(288, 800)
        navigator.show()
        qtbot.wait(20)

        auto_attach = navigator.btn_auto_attach
        assert auto_attach.property("role") == "icon"
        assert auto_attach.text() == ""
        assert not auto_attach.icon().isNull()
        assert auto_attach.size().width() == auto_attach.size().height() == 24
        assert auto_attach.width() >= auto_attach.sizeHint().width()
        assert auto_attach.toolTip() and auto_attach.accessibleName()

        config = ChannelSelectionConfig.create(
            "config-1", "转向基础", ("SteerTorque",), now="2026-08-09T00:00:00+00:00",
        )
        manager = ChannelConfigManagerDialog([config], selected_id="config-1")
        qtbot.addWidget(manager)
        manager.show()
        qtbot.wait(20)

        batch = manager.btn_batch
        assert batch.property("role") == "quiet"
        assert batch.text() == "批量管理配置"
        _assert_text_button_fits(batch)
    finally:
        qapp.setStyleSheet(previous_stylesheet)
