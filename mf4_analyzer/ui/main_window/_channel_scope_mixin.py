"""Focused TimeDomain View file-attachment behavior."""
from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox


AUTO_ATTACH_SETTINGS_KEY = "channel_selection/auto_attach_current_view"


class ChannelScopeMixin:
    """Own attachment mutations while the navigator remains a projection."""

    def _channel_scope_settings(self):
        from ..inspector_sections._helpers import _preset_settings

        return _preset_settings()

    def _init_channel_scope(self):
        self._restoring_project = False
        settings = self._channel_scope_settings()
        raw = settings.value(AUTO_ATTACH_SETTINGS_KEY, True)
        if isinstance(raw, bool):
            enabled = raw
        else:
            enabled = str(raw).strip().lower() not in {"0", "false", "no", "off"}
        self.navigator.set_auto_attach_enabled(enabled)

    def _on_auto_attach_changed(self, enabled):
        settings = self._channel_scope_settings()
        settings.setValue(AUTO_ATTACH_SETTINGS_KEY, bool(enabled))
        settings.sync()

    def _focused_time_view_state(self):
        idx = getattr(self, "_focused_view_idx", None)
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return None
        return idx, self.view_manager.get(idx)

    def _attach_files_to_focused_view(self, fids):
        resolved = self._focused_time_view_state()
        if resolved is None:
            return ()
        idx, state = resolved
        added = []
        seen = set(state.attached_file_ids)
        for value in fids or ():
            fid = str(value)
            if fid not in self.files or fid in seen:
                continue
            seen.add(fid)
            added.append(fid)
        if not added:
            return ()
        state.attached_file_ids.extend(added)
        self._project_view_controls(idx)
        return tuple(added)

    def _on_source_load_finished(self, new_fids):
        if (
            not new_fids
            or getattr(self, "_restoring_project", False)
            or not self.navigator.auto_attach_enabled()
        ):
            return ()
        return self._attach_files_to_focused_view(new_fids)

    def _detach_files_from_focused_view(self, fids, label=""):
        resolved = self._focused_time_view_state()
        if resolved is None:
            return False
        idx, state = resolved
        self._capture_focused_view()
        attached = set(state.attached_file_ids)
        removing = tuple(
            fid
            for fid in dict.fromkeys(str(value) for value in (fids or ()))
            if fid in attached
        )
        if not removing:
            return False

        removed = set(removing)
        checked_count = sum(1 for fid, _channel in state.checked if fid in removed)
        if checked_count and not self._confirm_detach_files(label, checked_count):
            return False

        self._filter_time_view_state_for_removed_fids(state, removed)
        self._project_view_controls(idx)
        if checked_count and self.chart_stack.current_mode() == "time":
            canvas = self._canvas_for_view_index(idx) or self.canvas_time
            self._replot_canvas_for_view(idx, canvas)
        shown_label = label or f"{len(removing)} 个文件"
        self.toast(f"已从当前 View 移除 {shown_label}", "info")
        return True

    def _confirm_detach_files(self, label, checked_count):
        box = QMessageBox(self)
        box.setWindowTitle("从当前 View 移除")
        box.setIcon(QMessageBox.Question)
        shown_label = label or "所选文件"
        box.setText(
            f"从当前 View 移除“{shown_label}”后，将取消 {checked_count} 个通道。"
            "是否继续？"
        )
        remove = box.addButton("从当前 View 移除", QMessageBox.AcceptRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        return box.clickedButton() is remove

    def _remove_file_from_all_time_views(self, fid):
        removed = {str(fid)}
        for state in self.view_manager.views:
            self._filter_time_view_state_for_removed_fids(state, removed)

    @staticmethod
    def _filter_time_view_state_for_removed_fids(state, removed):
        removed = {str(fid) for fid in removed}
        state.attached_file_ids = [
            fid for fid in state.attached_file_ids if str(fid) not in removed
        ]
        state.checked = [key for key in state.checked if str(key[0]) not in removed]
        state.hidden_channels = [
            key for key in state.hidden_channels if str(key[0]) not in removed
        ]
        state.colors = {
            key: color
            for key, color in state.colors.items()
            if str(key[0]) not in removed
        }
        if state.overlay_primary and str(state.overlay_primary[0]) in removed:
            state.overlay_primary = None
        axis_opts = dict(state.axis_opts or {})
        x_axis = dict(axis_opts.get("x_axis") or {})
        if x_axis.get("fid") is not None and str(x_axis["fid"]) in removed:
            x_axis.update({"mode": "time", "fid": None, "channel": None})
            axis_opts["x_axis"] = x_axis
            state.axis_opts = axis_opts
