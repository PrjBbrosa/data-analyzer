"""UltraView MainWindow façade: wiring + delegates.

MainWindow keeps a single ``self._ultraview = UltraViewCoordinator(...)``.
This class owns one-shot Page/manager wiring, public method/property
delegates, and top-level shutdown/reset order (stop capture → reset
workspace → reset page). Capture, PreviewStore, and timers live on
``UltraViewCaptureCoordinator``; Board mutation lives on
``UltraViewWorkspaceController``. This façade does not own a second
store, timer, workspace, or runtime ledger.
"""
from __future__ import annotations

import logging
import weakref
from functools import partial
from typing import Any

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QFileDialog

from ..ultraview_capture_facts import hide_transient_overlays
from ..ultraview_state import (
    COMPARE_FILTER_ALL,
    SOURCE_SECTIONS,
    UltraViewBoardState,
    UltraViewWorkspaceState,
    UltraViewRef,
    GridAnchor,
    active_board,
    all_refs,
    default_workspace,
    derive_preview_status,
    membership_set,
    normalize_workspace_payload,
    parse_ref_payload,
    placed_ref_set,
    BoardPlacementSnapshot,
    BoardEditEntry,
    AuthorMutationResult,
    GridRect,
    workspace_to_payload,
)
from ..ultraview_edits import SelectionMutationPlan
from ..chart_stack.ultraview.author_tools import (
    SelectionDeleteIntent,
    SelectionNudgeIntent,
)
from ..chart_stack.ultraview.preview_store import PreviewStore
from ..chart_stack.ultraview.card_fit import CardFitFacts
from ..chart_stack.ultraview.widgets import LibraryRow
from ..chart_stack.ultraview.compositor import (
    ComposeError,
    compose_board,
    save_composed_png,
)
from .ultraview_capture_coordinator import (
    UltraViewCaptureCoordinator,
    _DIGEST_RETRY_LIMIT,
    _IDLE_CAPTURE_MS,
    _alive,
    read_markup_revision,
)
from .ultraview_workspace_controller import (
    UltraViewWorkspaceController,
    _BOARD_HISTORY_BYTE_BUDGET,
    _GridHistory,
    _GridHistoryEntry,
    _PendingAutoAspect,
    _PLACEMENT_HISTORY_CAP,
)

logger = logging.getLogger(__name__)

def notify_ultraview_plot(window, section: str, reason: str = "plot") -> None:
    """Queue a visible-section capture after an actual plot/set_result."""
    coordinator = getattr(window, "_ultraview", None)
    if coordinator is None or coordinator.is_shutdown:
        return
    coordinator.request_visible_section_capture(section, reason)

class UltraViewCoordinator(QObject):
    """Façade: wiring + delegates for workspace mutation and capture commands."""

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent if parent is not None else window)
        self._window_ref = weakref.ref(window)
        self._shutdown = False
        self._capture = UltraViewCaptureCoordinator(
            window=self._window_ref,
            is_inactive=self._inactive,
            page=self.page,
            push_preview=self._forward_push_preview,
            workspace=self._workspace_for_capture,
            sheet_visible=self._sheet_visible,
            parent=self,
        )
        self.last_source_mode = "time"
        self._workspace_controller = UltraViewWorkspaceController(
            default_workspace(),
            is_inactive=self._inactive,
            refresh_projection=self.refresh_page,
            toast=self._toast,
            page=self.page,
            preview_fit_image_size=self._preview_fit_image_size,
            on_active_board_changed=self._capture.prioritize_sidecar_queue,
        )
        self._page_hooks: list[tuple[Any, Any, Any]] = []
        self._stack_hooks: list[tuple[Any, Any, Any]] = []
        self._manager_hooks: list[tuple[Any, Any, Any]] = []
        self._sync_work_queue: list[UltraViewRef] = []
        self._sync_current_ref: UltraViewRef | None = None
        self._sync_nav_busy = False
        self._sync_nav_needs_raise = False
        self.attach()

    def _forward_push_preview(self, ref, *, usable: bool = True) -> None:
        return self._push_preview(ref, usable=usable)

    def _workspace_for_capture(self) -> UltraViewWorkspaceState:
        return self._workspace_controller.workspace

    @property
    def is_shutdown(self) -> bool:
        return bool(self._shutdown)

    @property
    def store(self) -> PreviewStore:
        return self._capture.store

    def note_source_mode(self, mode: str) -> None:
        if mode in SOURCE_SECTIONS:
            self.last_source_mode = mode

    # -- capture façade delegates -------------------------------------

    def bind_canvas(self, canvas, ref: UltraViewRef | None) -> None:
        return self._capture.bind_canvas(canvas, ref)

    def bound_ref_for(self, canvas) -> UltraViewRef | None:
        return self._capture.bound_ref_for(canvas)

    def offer_capture_bound_canvas(self, canvas, incoming_ref: UltraViewRef | None=None) -> None:
        return self._capture.offer_capture_bound_canvas(canvas, incoming_ref)

    def request_capture(self, ref, widget, reason: str) -> None:
        return self._capture.request_capture(ref, widget, reason)

    def request_visible_section_capture(self, section: str, reason: str='plot') -> None:
        return self._capture.request_visible_section_capture(section, reason)

    def notify_result_stored(self, section, view_id, pane_idx, key, result) -> None:
        return self._capture.notify_result_stored(section, view_id, pane_idx, key, result)

    def result_generation_for(self, section, view_id, pane_idx, key) -> int:
        return self._capture.result_generation_for(section, view_id, pane_idx, key)

    def presentation_payload_for(self, ref: UltraViewRef) -> dict | None:
        return self._capture.presentation_payload_for(ref)

    def current_digest_for(self, ref: UltraViewRef) -> str | None:
        return self._capture.current_digest_for(ref)

    def set_pinned_from_board(self, board) -> None:
        return self._capture.set_pinned_from_board(board)

    def project_source_mode(self) -> str:
        if self.last_source_mode in SOURCE_SECTIONS:
            return self.last_source_mode
        return "time"

    def to_project_payload(self) -> dict:
        return workspace_to_payload(self._workspace)

    def restore_project_state(self, payload, *, project_path=None) -> list[str]:
        """Replace Board from a persisted payload. Store stays empty."""
        if self._shutdown:
            return []
        self._clear_sync_work()
        self._capture.reset_capture_state()
        workspace, warnings = normalize_workspace_payload(payload)
        self._workspace = workspace
        self._clear_placement_runtime()
        self._reset_page_runtime()
        if project_path is not None and workspace.preview_sidecar is not None:
            warnings.extend(
                self._capture.load_preview_sidecar(
                    project_path,
                    workspace_to_payload(workspace),
                    workspace.preview_sidecar,
                )
            )
        self.refresh_page()
        for item in warnings:
            logger.warning("UltraView project restore: %s", item)
        return list(warnings)

    @property
    def board(self) -> UltraViewBoardState:
        return self._workspace_controller.board

    @property
    def workspace(self) -> UltraViewWorkspaceState:
        return self._workspace_controller.workspace

    def save_preview_sidecar(self, project_path) -> list[str]:
        return self._capture.save_preview_sidecar(project_path)

    def page(self):
        window = self._window
        if window is None:
            return None
        stack = getattr(window, "chart_stack", None)
        return getattr(stack, "page_ultraview", None)

    def attach(self) -> None:
        if self._inactive():
            return
        window = self._window
        if window is None:
            return
        # Page and stack hooks are independent: a late page() must still
        # connect even if the stack add-to-ultraview hook is already live.
        if not self._page_hooks:
            page = self.page()
            if page is not None:
                page.set_workspace(self._workspace)
                self._connect_page(page)
        if not self._stack_hooks:
            stack = getattr(window, "chart_stack", None)
            if stack is not None:
                signal = getattr(stack, "add_to_ultraview_requested", None)
                if signal is not None:
                    signal.connect(self.add_from_source_tab)
                    self._stack_hooks.append(
                        (stack, signal, self.add_from_source_tab)
                    )
        if not self._manager_hooks:
            self._connect_managers()
        self.refresh_page()

    def capture_leaving_source(self, section: str) -> None:
        return self._capture.capture_leaving_source(section)

    def add_time_views_from_native_layout(self, items) -> tuple[str, ...]:
        """Add stable time view ids to the active Board in one mutation."""
        from ...ultraview_core.model import UltraViewRef
        from ...ultraview_core.native_layout import (
            NativeLayoutRect,
            plan_native_layout,
        )

        if self._inactive():
            return ()
        planned = []
        for view_id, rect in items:
            planned.append((
                UltraViewRef("time", str(view_id)),
                NativeLayoutRect(
                    float(rect.x),
                    float(rect.y),
                    float(rect.width),
                    float(rect.height),
                ),
            ))
        plan = plan_native_layout(planned)
        return self._workspace_ctl.apply_native_layout_plan(plan)

    def add_from_source_tab(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        window = self._window
        stack = getattr(window, "chart_stack", None) if window is not None else None
        current_mode = getattr(stack, "current_mode", lambda: "")()
        if current_mode == section:
            if section == "time":
                widget = self._time_canvas_for_ref(ref)
                if widget is not None:
                    reason = (
                        "add-from-tab-split"
                        if widget is not getattr(stack, "canvas_time", None)
                        else "add-from-tab"
                    )
                    self.bind_canvas(widget, ref)
                    self.request_capture(ref, widget, reason)
            else:
                current = self._active_ref(section)
                if current == ref:
                    widget = self._visible_widget_for(section)
                    if widget is not None:
                        self.bind_canvas(widget, ref)
                        self.request_capture(ref, widget, "add-from-tab")
        page = self.page()
        anchor = (
            page.current_free_grid_insert_anchor() if page is not None else None
        )
        self._apply_add_ref(ref, preferred_anchor=anchor)

    def open_source(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        if self._navigate_to_view(section, view_id, raise_window=True):
            return
        page = self.page()
        if page is not None:
            page.arm_replacement(section, view_id)

    def sync_preview(self, section: str, view_id: str) -> None:
        """Recapture one Board card from the live source View. Never recomputes.

        Hidden sources navigate then grab. Multiple syncs in one turn are
        serialized so the last ``navigate_to_view`` cannot steal an earlier
        canvas before its grab runs. Sync navigation does not raise the
        Analyzer; the Board stays in front and is raised only after the
        queue drains.
        """
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        if ref == self._sync_current_ref or ref in self._sync_work_queue:
            return
        self._sync_work_queue.append(ref)
        self._pump_sync_work()

    def refresh_page(self) -> None:
        if self._inactive():
            return
        self._sync_entry_content_marker()
        page = self.page()
        if page is None:
            return
        board = active_board(self._workspace)
        with page.projection_batch():
            # Library chrome (name/color) must be current before set_board
            # projects cards. Preview-record no-op must not freeze tab color.
            self._refresh_library(page)
            page.set_workspace(self._workspace)
            self.set_pinned_from_board(board)
            for ref in membership_set(board):
                self._push_preview(ref)

    def presentation_revision_for(self, ref: UltraViewRef) -> int:
        return self._capture.presentation_revision_for(ref)

    def bump_presentation_revision(self, ref: UltraViewRef) -> int:
        return self._capture.bump_presentation_revision(ref)

    def copy_board_to_clipboard(self) -> bool:
        image = self._compose_or_toast(scale=1, action="复制整板图")
        if image is None:
            return False
        clipboard = QApplication.clipboard()
        if clipboard is None:
            self._export_failed("clipboard_failed", "无法访问剪贴板")
            return False
        clipboard.setImage(image)
        self._toast("已复制整板图", "success")
        return True

    def copy_card_to_clipboard(self, ref: UltraViewRef) -> bool:
        if self._inactive():
            return False
        record = self.store.get(ref)
        image = getattr(record, "image", None) if record is not None else None
        if not PreviewStore.image_valid(image):
            self._export_failed("missing_preview", "该卡片尚无可用预览")
            return False
        clipboard = QApplication.clipboard()
        if clipboard is None:
            self._export_failed("clipboard_failed", "无法访问剪贴板")
            return False
        clipboard.setImage(image)
        self.store.touch(ref)
        self._toast("已复制卡片图", "success")
        return True

    def choose_and_export_png(self, scale: int = 1) -> bool:
        if self._inactive():
            return False
        factor = 1 if int(scale) <= 1 else 2
        path, _filter = QFileDialog.getSaveFileName(
            self._feedback_host(),
            f"导出 PNG {factor}×",
            "",
            "PNG (*.png)",
        )
        if not path:
            return False
        if not str(path).lower().endswith(".png"):
            path = str(path) + ".png"
        return self.export_png_to_path(path, scale=factor)

    def export_png_to_path(self, path, *, scale: int = 1) -> bool:
        image = self._compose_or_toast(scale=scale, action="导出 PNG")
        if image is None:
            return False
        try:
            save_composed_png(image, path)
        except ComposeError as exc:
            self._export_failed(exc.code, exc.message)
            return False
        self._toast(f"已导出 PNG {1 if int(scale) <= 1 else 2}×", "success")
        return True

    def compose_board_image(self, scale: int = 1) -> QImage:
        return self._compose_board(scale)

    def shutdown(self) -> None:
        """Final MainWindow close path: stop capture, reset workspace, reset page.

        Idempotent. Project reset must call ``reset_project_state`` instead.
        Queued callbacks no-op after the flag is set, even if a timer still
        delivers.
        """
        if self._shutdown:
            return
        self._shutdown = True
        self._clear_sync_work()
        self._capture.shutdown_capture()
        self._workspace = default_workspace()
        self._clear_placement_runtime()
        self._reset_page_runtime()
        self._disconnect_page_hooks()
        self._disconnect_stack_hooks()
        self._disconnect_manager_hooks()

    def reset_project_state(self) -> None:
        """Clear Board/Store/runtime for a new or replaced project.

        Page and stack hooks stay connected so the same window remains
        interactive. Does not run during shutdown.
        """
        if self._shutdown:
            return
        self._clear_sync_work()
        self._capture.reset_capture_state()
        self._workspace = default_workspace()
        self._clear_placement_runtime()
        self._reset_page_runtime()
        self.refresh_page()

    def clear(self) -> None:
        """Compatibility shim. Product paths must call reset or shutdown."""
        self.reset_project_state()

    def schedule_idle_capture(self, ref, widget=None) -> None:
        return self._capture.schedule_idle_capture(ref, widget)

    def _active_card_visible(self, ref: UltraViewRef) -> bool:
        return self._capture._active_card_visible(ref)

    def _card_display_sizes(self) -> dict:
        return self._capture._card_display_sizes()

    def _preview_pixel_size(self, ref: UltraViewRef) -> tuple[int, int]:
        return self._capture._preview_pixel_size(ref)

    def _needs_focus_recapture(self, ref: UltraViewRef) -> bool:
        return self._capture._needs_focus_recapture(ref)

    def _on_camera_settled(self) -> None:
        return self._capture._on_camera_settled()

    def _on_focus_residency_timeout(self) -> None:
        return self._capture._on_focus_residency_timeout()

    def _recapture_focus_refs(self) -> None:
        return self._capture._recapture_focus_refs()

    def _queue_sidecar_images(self, images) -> None:
        return self._capture._queue_sidecar_images(images)

    def _prioritize_sidecar_queue(self) -> None:
        return self._capture.prioritize_sidecar_queue()

    def _on_sidecar_load_timeout(self) -> None:
        return self._capture._on_sidecar_load_timeout()

    def _capture_visible_time_refs(self, reason: str) -> None:
        return self._capture._capture_visible_time_refs(reason)

    def _time_canvas_for_ref(self, ref: UltraViewRef):
        return self._capture._time_canvas_for_ref(ref)

    def _ref_exists(self, ref: UltraViewRef) -> bool:
        return self._capture._ref_exists(ref)

    def _on_store_images_dropped(self, refs) -> None:
        return self._capture._on_store_images_dropped(refs)

    def _time_payload(self, window, ref: UltraViewRef) -> dict | None:
        return self._capture._time_payload(window, ref)

    def _analysis_payload(self, window, ref: UltraViewRef) -> dict | None:
        return self._capture._analysis_payload(window, ref)

    def _time_data_signatures(self, window, state) -> list:
        return self._capture._time_data_signatures(window, state)

    def _channel_signature(self, files, fid, channel):
        return self._capture._channel_signature(files, fid, channel)

    def _filter_payload(self, window) -> dict:
        return self._capture._filter_payload(window)

    def _pane_cache_keys(self, window, section, view_id, pane_idx) -> list:
        return self._capture._pane_cache_keys(window, section, view_id, pane_idx)

    def _cursor_payload(self, window, ref: UltraViewRef, state) -> dict:
        return self._capture._cursor_payload(window, ref, state)

    def _pill_fingerprint(self, window, widget):
        return self._capture._pill_fingerprint(window, widget)

    def _has_current_preview(self, ref, digest: str) -> bool:
        return self._capture._has_current_preview(ref, digest)

    def _try_publish_now(self, ref, widget, reason: str) -> bool:
        return self._capture._try_publish_now(ref, widget, reason)

    def _queue_grab(self, key, ref, widget, digest, reason) -> None:
        return self._capture._queue_grab(key, ref, widget, digest, reason)

    def _queue_heatmap_grab(self, key, ref, widget, digest, reason) -> None:
        return self._capture._queue_heatmap_grab(key, ref, widget, digest, reason)

    def _publish_grab(self, ref, widget, digest, reason) -> bool:
        return self._capture._publish_grab(ref, widget, digest, reason)

    def _grab_scale(self, widget, ref) -> float:
        return self._capture._grab_scale(widget, ref)

    def _grab_image(self, widget, ref=None) -> QImage | None:
        return self._capture._grab_image(widget, ref)

    def _widget_has_any_real_result(self, widget) -> bool:
        return self._capture._widget_has_any_real_result(widget)

    def _is_stable(self, widget, section: str, *, facts=None) -> bool:
        return self._capture._is_stable(widget, section, facts=facts)

    def _widget_visible_and_sized(self, widget) -> bool:
        return self._capture._widget_visible_and_sized(widget)

    def _hosts_heatmap(self, widget) -> bool:
        return self._capture._hosts_heatmap(widget)

    def _ensure_stability_hooks(self, widget) -> None:
        return self._capture._ensure_stability_hooks(widget)

    def _watch_canvas_destroyed(self, canvas) -> None:
        return self._capture._watch_canvas_destroyed(canvas)

    def _on_canvas_destroyed(self, ident: int, *_args) -> None:
        return self._capture._on_canvas_destroyed(ident, *_args)

    def _on_quality_status_changed(self, *_args) -> None:
        return self._capture._on_quality_status_changed(*_args)

    def _on_layout_geometry_changed(self, *_args) -> None:
        return self._capture._on_layout_geometry_changed(*_args)

    def _reconsider_pending(self, sender) -> None:
        return self._capture._reconsider_pending(sender)

    def _active_ref(self, section: str) -> UltraViewRef | None:
        return self._capture._active_ref(section)

    def _visible_widget_for(self, section: str):
        return self._capture._visible_widget_for(section)

    def _widget_for_ref(self, ref: UltraViewRef):
        return self._capture._widget_for_ref(ref)

    def _bound_widget_for(self, ref: UltraViewRef):
        return self._capture._bound_widget_for(ref)

    def _facts_from_widget(self, widget):
        return self._capture._facts_from_widget(widget)

    def _runtime_facts_for(self, ref: UltraViewRef):
        return self._capture._runtime_facts_for(ref)

    def _time_state(self, window, view_id: str):
        return self._capture._time_state(window, view_id)

    def _analysis_state(self, window, section: str, view_id: str | None):
        return self._capture._analysis_state(window, section, view_id)

    def _analysis_page(self, window, section: str):
        return self._capture._analysis_page(window, section)

    def _preview_meta(self, ref: UltraViewRef, digest: str) -> PreviewMeta:
        return self._capture._preview_meta(ref, digest)

    def _source_summary(self, window, fids) -> str:
        return self._capture._source_summary(window, fids)

    @staticmethod
    def _pair(value):
        return UltraViewCaptureCoordinator._pair(value)

    @staticmethod
    def _generation_slot(section, view_id, pane_idx, key):
        return UltraViewCaptureCoordinator._generation_slot(
            section, view_id, pane_idx, key
        )

    @staticmethod
    def _digest_key(key):
        return UltraViewCaptureCoordinator._digest_key(key)

    def _warn_capture(self, ref, widget, reason, detail) -> None:
        return self._capture._warn_capture(ref, widget, reason, detail)

    def _warn_digest(self, ref, exc) -> None:
        return self._capture._warn_digest(ref, exc)

    def _start_timer(self, key, callback) -> None:
        return self._capture._start_timer(key, callback)

    def _drop_queued_for_ref(self, ref, keep=None) -> None:
        return self._capture._drop_queued_for_ref(ref, keep)

    def _binding_for_idle_sender(self, sender):
        return self._capture._binding_for_idle_sender(sender)

    def _on_idle_presentation_signal(self, *_args) -> None:
        return self._capture._on_idle_presentation_signal(*_args)

    def _on_idle_source_signal(self, *_args) -> None:
        return self._capture._on_idle_source_signal(*_args)

    def _on_idle_capture_timeout(self) -> None:
        return self._capture._on_idle_capture_timeout()

    def _requeue_after_digest_change(self, ref, widget, reason: str) -> None:
        return self._capture._requeue_after_digest_change(ref, widget, reason)

    def _drop_all_timers(self) -> None:
        self._capture._drop_all_timers()
        self._clear_sync_work()

    def _disconnect_hooks(self) -> None:
        return self._capture._disconnect_hooks()

    def _inactive(self) -> bool:
        return self._shutdown or not _alive(self)

    @property
    def _window(self):
        return self._window_ref()

    @property
    def _workspace(self) -> UltraViewWorkspaceState:
        return self._workspace_controller.workspace

    @_workspace.setter
    def _workspace(self, value: UltraViewWorkspaceState) -> None:
        self._workspace_controller.replace_workspace(value)

    @property
    def _grid_histories(self):
        return self._workspace_controller.grid_histories

    @property
    def _pending_auto_aspect(self):
        return self._workspace_controller.pending_auto_aspect

    @property
    def _layout_revision(self):
        return self._workspace_controller.layout_revision

    def _connect_page(self, page) -> None:
        pairs = (
            (page.add_ref_requested, self._on_add_ref),
            (page.replace_slot_requested, self._on_replace_slot),
            (page.rebind_ref_requested, self._on_rebind_ref),
            (page.swap_slots_requested, self._on_swap_slots),
            (page.place_from_unplaced_requested, self._on_place_from_unplaced),
            (page.place_free_grid_from_unplaced_requested, self._on_place_free_grid_from_unplaced),
            (page.free_grid_insert_requested, self._on_free_grid_insert),
            (page.free_grid_replace_requested, self._on_free_grid_replace),
            (page.move_to_unplaced_requested, self._on_move_to_unplaced),
            (page.remove_ref_requested, self._on_remove_ref),
            (page.open_source_requested, self.open_source),
            (page.sync_requested, self.sync_preview),
            (page.focus_requested, self._on_focus),
            (page.layout_changed, self._on_layout),
            (page.ratio_nudge_requested, self._on_ratio_nudge),
            (page.presentation_toggled, self._on_presentation),
            (page.compare_filter_changed, self._on_compare_filter),
            (page.copy_board_requested, self.copy_board_to_clipboard),
            (page.copy_card_image_requested, self._on_copy_card),
            (page.export_png_requested, self.choose_and_export_png),
            (page.board_name_changed, self._on_board_name),
            (page.create_board_requested, self._on_create_board),
            (page.duplicate_board_requested, self._on_duplicate_board),
            (page.rename_board_requested, self._on_rename_board),
            (page.delete_board_requested, self._on_delete_board),
            (page.reorder_board_requested, self._on_reorder_board),
            (page.select_board_requested, self._on_select_board),
            (page.free_grid_toggled, self._on_free_grid_toggled),
            (page.free_grid_geometry_requested, self._on_free_grid_geometry),
            (page.free_grid_group_geometry_requested, self._on_free_grid_group_geometry),
            (page.free_grid_preset_requested, self._on_free_grid_preset),
            (page.free_grid_autofit_requested, self._on_free_grid_autofit),
            (page.organize_free_grid_requested, self._on_organize_free_grid),
            (page.auto_arrange_requested, self._on_auto_arrange_free_grid),
            (page.free_grid_undo_requested, self._on_free_grid_undo),
            (page.free_grid_redo_requested, self._on_free_grid_redo),
            (page.author_create_requested, self._on_author_create),
            (page.author_update_requested, self._on_author_update),
            (page.author_delete_requested, self._on_author_delete),
            (page.author_batch_requested, self._on_author_batch),
            (page.show_titles_toggled, self._on_show_titles),
            (page.show_sources_toggled, self._on_show_sources),
            (page.show_card_actions_toggled, self._on_show_card_actions),
            (page.feedback_requested, self._on_page_feedback),
            (page.camera_settled, self._on_camera_settled),
        )
        for signal, slot in pairs:
            signal.connect(slot)
            self._page_hooks.append((page, signal, slot))
        page.resolve_insert_span = self._insert_span_for_drag
        page.can_undo_auto_arrange = self._can_undo_auto_arrange

    def _connect_managers(self) -> None:
        if self._manager_hooks:
            return
        for _section, manager in self._iter_managers():
            signal = getattr(manager, "views_changed", None)
            if signal is None:
                continue
            signal.connect(self._on_manager_views_changed)
            self._manager_hooks.append(
                (manager, signal, self._on_manager_views_changed)
            )

    def _on_manager_views_changed(self, *_args) -> None:
        if self._inactive():
            return
        self.refresh_page()

    def _navigate_to_view(
        self, section: str, view_id: str, *, raise_window: bool = True
    ) -> bool:
        """Call ``MainWindow.navigate_to_view``; tolerate 2-arg test fakes."""
        window = self._window
        navigate = getattr(window, "navigate_to_view", None) if window is not None else None
        if not callable(navigate):
            return False
        try:
            return bool(navigate(section, view_id, raise_window=raise_window))
        except TypeError:
            return bool(navigate(section, view_id))

    def _pump_sync_work(self) -> None:
        if self._inactive() or self._sync_nav_busy:
            return
        if not self._sync_work_queue:
            if self._sync_nav_needs_raise:
                self._sync_nav_needs_raise = False
                self._raise_ultraview_sheet()
            return
        ref = self._sync_work_queue.pop(0)
        self._sync_nav_busy = True
        self._sync_current_ref = ref
        widget = self._sync_capture_widget(ref)
        if widget is not None:
            self._request_user_sync(ref, widget)
            self._finish_sync_item(ref)
            return
        if not self._ref_exists(ref):
            self._toast("找不到原 View，无法同步", "warning")
            self._finish_sync_item(ref, wait_capture=False)
            return
        if self._navigate_to_view(ref.section, ref.view_id, raise_window=False):
            self._sync_nav_needs_raise = True
            QTimer.singleShot(0, partial(self._sync_preview_after_navigate, ref))
            return
        self._toast("请先打开原 View 再同步", "warning")
        self._finish_sync_item(ref, wait_capture=False)

    def _sync_preview_after_navigate(self, ref) -> None:
        try:
            if self._inactive() or ref is None:
                return
            widget = self._sync_capture_widget(ref)
            if widget is None:
                widget = self._visible_widget_for(ref.section)
                if widget is not None and self._active_ref(ref.section) == ref:
                    self.bind_canvas(widget, ref)
                else:
                    widget = None
            if widget is None:
                self._toast("请先打开原 View 再同步", "warning")
                return
            self._request_user_sync(ref, widget)
        finally:
            self._finish_sync_item(ref)

    def _finish_sync_item(self, ref, *, wait_capture: bool = True) -> None:
        coord_ref = weakref.ref(self)

        def _advance():
            coord = coord_ref()
            if coord is None or coord._inactive():
                return
            if wait_capture and coord._capture.has_pending_capture(ref):
                QTimer.singleShot(0, _advance)
                return
            if coord._sync_current_ref == ref:
                coord._sync_current_ref = None
            coord._sync_nav_busy = False
            coord._pump_sync_work()

        QTimer.singleShot(0, _advance)

    def _clear_sync_work(self) -> None:
        self._sync_work_queue.clear()
        self._sync_current_ref = None
        self._sync_nav_busy = False
        self._sync_nav_needs_raise = False

    def _sync_capture_widget(self, ref):
        candidates = []
        bound = self._bound_widget_for(ref)
        if bound is not None:
            candidates.append(bound)
        if self._active_ref(ref.section) == ref:
            visible = self._visible_widget_for(ref.section)
            if visible is not None and visible not in candidates:
                candidates.append(visible)
        for widget in candidates:
            if widget is None or not _alive(widget):
                continue
            try:
                if widget.isVisible():
                    return widget
            except RuntimeError:
                continue
        return None

    def _request_user_sync(self, ref, widget) -> None:
        if widget is None or not _alive(widget):
            self._toast("找不到原 View，无法同步", "warning")
            return
        try:
            if not widget.isVisible():
                self._toast("请先打开原 View 再同步", "warning")
                return
        except RuntimeError:
            self._toast("找不到原 View，无法同步", "warning")
            return
        if not self._widget_has_any_real_result(widget):
            self._toast("原 View 尚无可用结果", "warning")
            return
        digest = self.current_digest_for(ref)
        if digest is None:
            self._toast("无法读取当前图面，稍后再试", "warning")
            return
        self.bind_canvas(widget, ref)
        if self._has_current_preview(ref, digest) and not self._needs_focus_recapture(ref):
            self._push_preview(ref)
            return
        self.request_capture(ref, widget, "user-sync")

    def _raise_ultraview_sheet(self) -> None:
        window = self._window
        sheet = getattr(window, "_ultraview_sheet", None) if window is not None else None
        if sheet is None or not _alive(sheet):
            return
        try:
            sheet.raise_()
            sheet.activateWindow()
        except RuntimeError:
            return

    def _sync_entry_content_marker(self) -> None:
        """Keep each source-rail entry honest about configured Board cards."""
        window = self._window
        chart_stack = getattr(window, "chart_stack", None) if window is not None else None
        sync = getattr(chart_stack, "set_ultraview_has_content", None)
        if callable(sync):
            sync(any(all_refs(board) for board in self._workspace.boards))

    def _refresh_library(self, page) -> None:
        rows = []
        for section, manager in self._iter_managers():
            for state in list(manager.views):
                ref = UltraViewRef(section, str(state.view_id))
                record = self.store.get(ref)
                exists = True
                digest = self.current_digest_for(ref)
                image_valid = record is not None and PreviewStore.image_valid(
                    getattr(record, "image", None)
                )
                captured = getattr(record, "captured_digest", None) if record else None
                rows.append(LibraryRow(
                    section=section,
                    view_id=str(state.view_id),
                    name=str(getattr(state, "name", "") or ""),
                    tab_color=str(getattr(state, "tab_color", "") or ""),
                    source_summary=self._checked_summary(state),
                    on_board=any(ref in membership_set(board) for board in self._workspace.boards),
                    status=derive_preview_status(
                        exists, image_valid, captured, digest
                    ),
                ))
        page.set_library_rows(rows)

    def _iter_managers(self):
        window = self._window
        if window is None:
            return
        time_manager = getattr(window, "view_manager", None)
        if time_manager is not None:
            yield "time", time_manager
        managers = getattr(window, "analysis_managers", None) or {}
        for section in SOURCE_SECTIONS:
            if section == "time":
                continue
            manager = managers.get(section)
            if manager is not None:
                yield section, manager

    def _checked_summary(self, state) -> str:
        checked = list(getattr(state, "checked", None) or [])
        names = []
        for item in checked[:3]:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                names.append(str(item[1]))
            else:
                names.append(str(item))
        extra = len(checked) - 3
        text = ", ".join(names)
        if extra > 0:
            text = f"{text} +{extra}"
        return text

    def _push_preview(self, ref: UltraViewRef, *, usable: bool = True) -> None:
        page = self.page()
        if page is None:
            return
        record = self.store.get(ref)
        exists = self._ref_exists(ref)
        digest = (
            self.current_digest_for(ref) if exists and usable else None
        )
        image_valid = record is not None and PreviewStore.image_valid(
            getattr(record, "image", None)
        )
        captured = getattr(record, "captured_digest", None) if record else None
        status = derive_preview_status(exists, image_valid, captured, digest)
        page.apply_preview_and_status(ref, record, status, exists)
        if image_valid and any(ref in placed_ref_set(board) for board in self._workspace.boards):
            self.store.touch(ref)
        self._refresh_open_focus(ref)
        if image_valid and usable:
            self._maybe_apply_pending_auto_aspect(ref)

    def _refresh_open_focus(self, ref: UltraViewRef) -> None:
        page = self.page()
        if page is None:
            return
        layer = page.focus_layer()
        if not layer.isVisible():
            return
        current = layer.current_ref()
        if current != (ref.section, ref.view_id):
            return
        page.show_focus(ref.section, ref.view_id)
        digest = self.current_digest_for(ref)
        page.set_focus_syncing(
            digest is None or not self._has_current_preview(ref, digest)
        )

    def _after_board_mutation(self) -> None:
        return self._workspace_controller._after_board_mutation()

    def _apply_add_ref(
        self, ref: UltraViewRef, *, preferred_anchor: GridAnchor | None = None
    ) -> None:
        return self._workspace_controller._apply_add_ref(ref, preferred_anchor=preferred_anchor)

    def _on_add_ref(self, section: str, view_id: str) -> None:
        return self._workspace_controller._on_add_ref(section, view_id)

    def _on_replace_slot(self, slot_id: str, section: str, view_id: str) -> None:
        return self._workspace_controller._on_replace_slot(slot_id, section, view_id)

    def _on_rebind_ref(
        self,
        old_section: str,
        old_view_id: str,
        new_section: str,
        new_view_id: str,
    ) -> None:
        return self._workspace_controller._on_rebind_ref(old_section, old_view_id, new_section, new_view_id)

    def _on_swap_slots(self, slot_a: str, slot_b: str) -> None:
        return self._workspace_controller._on_swap_slots(slot_a, slot_b)

    def _on_place_from_unplaced(self, slot_id: str, section: str, view_id: str) -> None:
        return self._workspace_controller._on_place_from_unplaced(slot_id, section, view_id)

    def _on_place_free_grid_from_unplaced(self, section: str, view_id: str) -> None:
        return self._workspace_controller._on_place_free_grid_from_unplaced(section, view_id)

    def _on_free_grid_insert(
        self, section: str, view_id: str, anchor: GridAnchor
    ) -> None:
        return self._workspace_controller._on_free_grid_insert(section, view_id, anchor)

    def _on_free_grid_replace(
        self,
        target_section: str,
        target_view_id: str,
        source_section: str,
        source_view_id: str,
    ) -> None:
        return self._workspace_controller._on_free_grid_replace(target_section, target_view_id, source_section, source_view_id)

    def _on_move_to_unplaced(self, section: str, view_id: str) -> None:
        return self._workspace_controller._on_move_to_unplaced(section, view_id)

    def _on_remove_ref(self, section: str, view_id: str) -> None:
        return self._workspace_controller._on_remove_ref(section, view_id)

    def _on_layout(self, layout_id: str) -> None:
        return self._workspace_controller._on_layout(layout_id)

    def _on_ratio_nudge(self, steps: int) -> None:
        return self._workspace_controller._on_ratio_nudge(steps)

    def _on_free_grid_toggled(self, enabled: bool) -> None:
        return self._workspace_controller._on_free_grid_toggled(enabled)

    def _on_free_grid_geometry(
        self,
        section: str,
        view_id: str,
        column: int,
        row: int,
        column_span: int,
        row_span: int,
        _reason: str,
    ) -> None:
        return self._workspace_controller._on_free_grid_geometry(section, view_id, column, row, column_span, row_span, _reason)

    def _on_free_grid_group_geometry(self, updates) -> None:
        return self._workspace_controller._on_free_grid_group_geometry(updates)

    def _on_free_grid_preset(self, section: str, view_id: str, preset: str) -> None:
        return self._workspace_controller._on_free_grid_preset(section, view_id, preset)

    def _on_free_grid_autofit(self, section: str, view_id: str) -> None:
        return self._workspace_controller._on_free_grid_autofit(section, view_id)

    def _card_fit_facts_for(
        self,
        board: UltraViewBoardState,
        item,
        image_size: tuple[int, int] | None,
    ) -> CardFitFacts:
        return self._workspace_controller._card_fit_facts_for(board, item, image_size)

    def _live_card_fit_chrome(
        self, ref: UltraViewRef
    ) -> tuple[int, int, int, int, int]:
        return self._workspace_controller._live_card_fit_chrome(ref)

    def _on_organize_free_grid(self) -> None:
        return self._workspace_controller._on_organize_free_grid()

    def _on_auto_arrange_free_grid(self) -> None:
        return self._workspace_controller._on_auto_arrange_free_grid()

    def _can_undo_auto_arrange(self) -> bool:
        return self._workspace_controller._can_undo_auto_arrange()

    def _grid_history(self, board: UltraViewBoardState) -> _GridHistory:
        return self._workspace_controller._grid_history(board)

    @staticmethod
    def _placement_snapshot(board: UltraViewBoardState) -> BoardPlacementSnapshot:
        return UltraViewWorkspaceController._placement_snapshot(board)

    def _record_grid_transition(
        self,
        board: UltraViewBoardState,
        before: BoardPlacementSnapshot,
        *,
        kind: str = "",
    ) -> bool:
        return self._workspace_controller._record_grid_transition(board, before, kind=kind)

    def _commit_author_mutation(
        self,
        board: UltraViewBoardState,
        mutation: AuthorMutationResult,
        *,
        label: str,
        placement_before: BoardPlacementSnapshot | None = None,
    ) -> bool:
        return self._workspace_controller._commit_author_mutation(board, mutation, label=label, placement_before=placement_before)

    def _record_board_edit(
        self, board: UltraViewBoardState, entry: BoardEditEntry
    ) -> bool:
        return self._workspace_controller._record_board_edit(board, entry)

    def _on_author_create(self, intent) -> None:
        return self._workspace_controller._on_author_create(intent)

    def _on_author_update(self, intent) -> None:
        return self._workspace_controller._on_author_update(intent)

    def _on_author_delete(self, intent) -> None:
        return self._workspace_controller._on_author_delete(intent)

    def _on_author_batch(self, intent) -> None:
        return self._workspace_controller._on_author_batch(intent)

    def _on_selection_delete(self, board, intent: SelectionDeleteIntent) -> None:
        return self._workspace_controller._on_selection_delete(board, intent)

    def _on_selection_nudge(self, board, intent: SelectionNudgeIntent) -> None:
        return self._workspace_controller._on_selection_nudge(board, intent)

    def _commit_selection_mutation(
        self, board, plan: SelectionMutationPlan
    ) -> None:
        return self._workspace_controller._commit_selection_mutation(board, plan)

    def _publish_author_mutation(
        self,
        board,
        mutation,
        *,
        label: str,
        placement_before=None,
    ) -> None:
        return self._workspace_controller._publish_author_mutation(board, mutation, label=label, placement_before=placement_before)

    @staticmethod
    def _history_entry_byte_cost(entry: _GridHistoryEntry | BoardEditEntry) -> int:
        return UltraViewWorkspaceController._history_entry_byte_cost(entry)

    def _push_history_undo(
        self, history: _GridHistory, entry: _GridHistoryEntry | BoardEditEntry
    ) -> None:
        return self._workspace_controller._push_history_undo(history, entry)

    def _push_history_redo(
        self, history: _GridHistory, entry: _GridHistoryEntry | BoardEditEntry
    ) -> None:
        return self._workspace_controller._push_history_redo(history, entry)

    def _clear_history_redo(self, history: _GridHistory) -> None:
        return self._workspace_controller._clear_history_redo(history)

    def _pop_history_undo(
        self, history: _GridHistory
    ) -> _GridHistoryEntry | BoardEditEntry:
        return self._workspace_controller._pop_history_undo(history)

    def _pop_history_redo(
        self, history: _GridHistory
    ) -> _GridHistoryEntry | BoardEditEntry:
        return self._workspace_controller._pop_history_redo(history)

    def _commit_grid_change(
        self,
        board: UltraViewBoardState,
        before: BoardPlacementSnapshot,
        warnings: list[str],
        *,
        lost_cards=(),
        kind: str = "",
    ) -> None:
        return self._workspace_controller._commit_grid_change(board, before, warnings, lost_cards=lost_cards, kind=kind)

    def _toast_grid_warnings(self, warnings: list[str]) -> None:
        return self._workspace_controller._toast_grid_warnings(warnings)

    def _toast_layout_warnings(self, warnings: list[str]) -> None:
        return self._workspace_controller._toast_layout_warnings(warnings)

    def _discard_stale_grid_history(self, history: _GridHistory) -> None:
        return self._workspace_controller._discard_stale_grid_history(history)

    @staticmethod
    def _apply_grid_snapshot(
        board: UltraViewBoardState,
        snapshot: BoardPlacementSnapshot,
    ) -> bool:
        return UltraViewWorkspaceController._apply_grid_snapshot(board, snapshot)

    def _on_free_grid_undo(self) -> None:
        return self._workspace_controller._on_free_grid_undo()

    def _on_free_grid_redo(self) -> None:
        return self._workspace_controller._on_free_grid_redo()

    def _preview_image_size(self, ref: UltraViewRef) -> tuple[int, int] | None:
        record = self.store.get(ref)
        image = getattr(record, "image", None) if record is not None else None
        if not PreviewStore.image_valid(image):
            return None
        return (int(image.width()), int(image.height()))

    def _preview_fit_device_pixel_ratio(self) -> float:
        """Return the logical-pixel scale of the card's current screen.

        ``PreviewStore`` deliberately keeps DPR-normalized raw pixels so its
        memory budget and sidecar stay portable. Free-grid geometry, however,
        is expressed in widget logical pixels. Using raw Retina dimensions in
        the aspect solver makes a capture look twice as large as its eventual
        card pixmap, which leaves an oversized shell around a new View.
        """
        for widget in (self.page(), self._window):
            if widget is None:
                continue
            try:
                ratio = float(widget.devicePixelRatioF())
            except RuntimeError:
                continue
            if ratio > 0.0:
                return max(1.0, ratio)
        return 1.0

    def _preview_fit_image_size(self, ref: UltraViewRef) -> tuple[int, int] | None:
        """Return the stored preview's size in the card solver's pixel space."""
        raw_size = self._preview_image_size(ref)
        if raw_size is None:
            return None
        dpr = self._preview_fit_device_pixel_ratio()
        return (
            max(1, int(round(raw_size[0] / dpr))),
            max(1, int(round(raw_size[1] / dpr))),
        )

    def _insert_span_for_ref(
        self, board: UltraViewBoardState, ref: UltraViewRef
    ) -> tuple[int, int] | None:
        return self._workspace_controller._insert_span_for_ref(board, ref)

    def _insert_span_for_drag(
        self, section: str, view_id: str
    ) -> tuple[int, int] | None:
        return self._workspace_controller._insert_span_for_drag(section, view_id)

    def _place_unplaced_on_free_grid(
        self,
        board: UltraViewBoardState,
        ref: UltraViewRef,
        *,
        preferred_anchor: GridAnchor | None,
    ) -> None:
        return self._workspace_controller._place_unplaced_on_free_grid(board, ref, preferred_anchor=preferred_anchor)

    def _fitted_insert_span(
        self, board: UltraViewBoardState, image_size: tuple[int, int]
    ) -> tuple[int, int]:
        return self._workspace_controller._fitted_insert_span(board, image_size)

    def _current_layout_revision(self, board_id: str) -> int:
        return self._workspace_controller._current_layout_revision(board_id)

    def _bump_layout_revision(self, board_id: str) -> None:
        return self._workspace_controller._bump_layout_revision(board_id)

    def _register_pending_auto_aspect(
        self,
        board: UltraViewBoardState,
        ref: UltraViewRef,
        inserted_rect: GridRect,
    ) -> None:
        return self._workspace_controller._register_pending_auto_aspect(board, ref, inserted_rect)

    def _cancel_pending_for_ref(self, board_id: str, ref: UltraViewRef) -> None:
        return self._workspace_controller._cancel_pending_for_ref(board_id, ref)

    def _cancel_pending_for_board(self, board_id: str) -> None:
        return self._workspace_controller._cancel_pending_for_board(board_id)

    def _clear_pending_merge_flags(self) -> None:
        return self._workspace_controller._clear_pending_merge_flags()

    def _clear_placement_runtime(self) -> None:
        return self._workspace_controller._clear_placement_runtime()

    def _drop_board_placement_runtime(self, board_id: str) -> None:
        return self._workspace_controller._drop_board_placement_runtime(board_id)

    def _maybe_apply_pending_auto_aspect(self, ref: UltraViewRef) -> None:
        return self._workspace_controller._maybe_apply_pending_auto_aspect(ref)

    def _apply_one_pending_auto_aspect(self, token: _PendingAutoAspect) -> None:
        return self._workspace_controller._apply_one_pending_auto_aspect(token)

    def _on_focus(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is None:
            return
        self.store.touch(ref)
        page = self.page()
        digest = self.current_digest_for(ref)
        stale = digest is None or not self._has_current_preview(ref, digest)
        self.set_pinned_from_board(active_board(self._workspace))
        if self._needs_focus_recapture(ref):
            stale = True
        if page is not None:
            page.set_focus_syncing(stale)
        if not stale:
            return
        widget = self._widget_for_ref(ref)
        if widget is None:
            candidate = self._visible_widget_for(ref.section)
            if candidate is not None and self._active_ref(ref.section) == ref:
                widget = candidate
        if widget is None:
            if page is not None:
                page.set_focus_syncing(False)
            return
        self.bind_canvas(widget, ref)
        self.request_capture(ref, widget, "focus-inspect")

    def _on_page_feedback(self, message: str) -> None:
        if self._inactive():
            return
        text = str(message or "").strip()
        if text:
            self._toast(text, "info")

    def _on_copy_card(self, section: str, view_id: str) -> None:
        ref = parse_ref_payload({"section": section, "view_id": view_id})
        if ref is not None:
            self.copy_card_to_clipboard(ref)

    def _on_board_name(self, name: str) -> None:
        return self._workspace_controller._on_board_name(name)

    def _on_create_board(self) -> None:
        return self._workspace_controller._on_create_board()

    def _on_duplicate_board(self, board_id: str) -> None:
        return self._workspace_controller._on_duplicate_board(board_id)

    def _on_rename_board(self, board_id: str, name: str) -> None:
        return self._workspace_controller._on_rename_board(board_id, name)

    def _on_delete_board(self, board_id: str) -> None:
        return self._workspace_controller._on_delete_board(board_id)

    def _on_reorder_board(self, board_id: str, index: int) -> None:
        return self._workspace_controller._on_reorder_board(board_id, index)

    def _on_select_board(self, board_id: str) -> None:
        return self._workspace_controller._on_select_board(board_id)

    def _compose_board(self, scale: int) -> QImage:
        records = {}
        statuses = {}
        board = active_board(self._workspace)
        for ref in all_refs(board):
            record = self.store.get(ref)
            records[ref] = record
            if record is not None and PreviewStore.image_valid(getattr(record, "image", None)):
                if ref in placed_ref_set(board):
                    self.store.touch(ref)
            exists = self._ref_exists(ref)
            digest = self.current_digest_for(ref) if exists else None
            image_valid = record is not None and PreviewStore.image_valid(
                getattr(record, "image", None)
            )
            captured = getattr(record, "captured_digest", None) if record else None
            statuses[ref] = derive_preview_status(exists, image_valid, captured, digest)
        return compose_board(board, records, statuses, scale=scale)

    def _compose_or_toast(self, *, scale: int, action: str) -> QImage | None:
        if self._inactive():
            return None
        try:
            return self._compose_board(scale)
        except ComposeError as exc:
            self._export_failed(exc.code, f"{action}失败：{exc.message}")
            return None

    def _export_failed(self, code: str, message: str) -> None:
        logger.warning("UltraView export %s: %s", code, message)
        self._toast(message, "warning")

    def _feedback_host(self):
        """Visible Board window when the page lives there; else Analyzer."""
        page = self.page()
        if page is not None:
            try:
                host = page.window()
            except RuntimeError:
                host = None
            if host is not None and _alive(host):
                try:
                    if host.isVisible() and host is not self._window:
                        return host
                except RuntimeError:
                    pass
        if self._sheet_visible():
            window = self._window
            sheet = getattr(window, "_ultraview_sheet", None) if window is not None else None
            if sheet is not None and _alive(sheet):
                return sheet
        return self._window

    def _toast(self, message: str, level: str) -> None:
        host = self._feedback_host()
        toast = getattr(host, "toast", None) if host is not None else None
        if callable(toast):
            toast(message, level)

    def _on_rebind_arm(self, section: str, view_id: str) -> None:
        if self._inactive():
            return
        page = self.page()
        if page is not None:
            page.arm_replacement(section, view_id)

    def _on_compare_filter(self, filter_id: str) -> None:
        if self._inactive():
            return
        page = self.page()
        wanted = str(filter_id or COMPARE_FILTER_ALL)
        if page is not None and page.compare_filter() != wanted:
            page.set_compare_filter(wanted)

    def _on_show_titles(self, checked: bool) -> None:
        return self._workspace_controller._on_show_titles(checked)

    def _on_show_sources(self, checked: bool) -> None:
        return self._workspace_controller._on_show_sources(checked)

    def _on_show_card_actions(self, checked: bool) -> None:
        return self._workspace_controller._on_show_card_actions(checked)

    def _on_shift_slot(self, section: str, view_id: str, delta: int) -> None:
        return self._workspace_controller._on_shift_slot(section, view_id, delta)

    def _on_set_primary(self, section: str, view_id: str) -> None:
        return self._workspace_controller._on_set_primary(section, view_id)

    def _on_presentation(self, active: bool) -> None:
        if self._inactive():
            return
        page = self.page()
        if page is not None:
            page.set_presentation_active(bool(active))

    def _index_for_view_id(self, section: str, view_id: str) -> int | None:
        window = self._window
        if window is None:
            return None
        if section == "time":
            manager = getattr(window, "view_manager", None)
        else:
            managers = getattr(window, "analysis_managers", None) or {}
            manager = managers.get(section)
        if manager is None:
            return None
        target = str(view_id)
        for idx, state in enumerate(manager.views):
            if str(getattr(state, "view_id", "")) == target:
                return idx
        return None

    def _reset_page_runtime(self) -> None:
        page = self.page()
        if page is None:
            return
        page.reset_sheet_session()
        page.clear_runtime_caches()

    def _disconnect_page_hooks(self) -> None:
        for obj, signal, slot in self._page_hooks:
            if not _alive(obj):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue
        self._page_hooks.clear()

    def _disconnect_stack_hooks(self) -> None:
        for obj, signal, slot in self._stack_hooks:
            if not _alive(obj):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue
        self._stack_hooks.clear()

    def _disconnect_manager_hooks(self) -> None:
        for obj, signal, slot in self._manager_hooks:
            if not _alive(obj):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                continue
        self._manager_hooks.clear()

    def _sheet_visible(self) -> bool:
        window = self._window
        if window is None:
            return False
        sheet = getattr(window, "_ultraview_sheet", None)
        if sheet is None or not _alive(sheet):
            return False
        try:
            return bool(sheet.isVisible())
        except RuntimeError:
            return False
