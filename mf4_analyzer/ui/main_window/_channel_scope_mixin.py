"""Focused TimeDomain View file-attachment behavior."""
from __future__ import annotations

from PyQt5.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from ..channel_config import (
    ChannelSelectionConfigStore,
    ConfigNameConflict,
    normalize_channel_names,
    resolve_channel_config,
)
from ..plot_risk import PlotRiskLevel


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
        self.channel_config_store = ChannelSelectionConfigStore(settings)
        self._reload_channel_config_bar()

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
        self._refresh_channel_config_context()
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
        self._refresh_channel_config_context()
        if checked_count and self.chart_stack.current_mode() == "time":
            canvas = self._canvas_for_view_index(idx) or self.canvas_time
            self._replot_canvas_for_view(idx, canvas)
        shown_label = label or f"{len(removing)} 个文件"
        self.toast(f"已从当前 View 移除 {shown_label}", "info")
        return True

    def _reload_channel_config_bar(self, selected_id=None):
        bar = self.navigator.channel_list.config_bar
        if selected_id is None:
            selected_id = bar.selected_config_id()
        bar.set_configs(self.channel_config_store.list(), selected_id=selected_id)
        self._refresh_channel_config_context()

    def _on_channel_config_selection_changed(self, _config_id):
        self._refresh_channel_config_context()

    def _refresh_channel_config_context(self):
        store = getattr(self, "channel_config_store", None)
        navigator = getattr(self, "navigator", None)
        if store is None or navigator is None:
            return
        bar = navigator.channel_list.config_bar
        resolved = self._focused_time_view_state()
        attached = [] if resolved is None else resolved[1].attached_file_ids
        existing_attached = [fid for fid in attached if fid in self.files]
        current_checked = {
            (str(fid), str(channel))
            for fid, channel, _color in navigator.get_checked_channels()
        }
        bar.set_context(
            has_checked=bool(current_checked),
            has_attached=bool(existing_attached),
        )
        config = store.get(bar.selected_config_id())
        if config is None:
            bar.set_dirty(False)
            return
        resolution = resolve_channel_config(config, existing_attached, self.files)
        bar.set_dirty(current_checked != set(resolution.matched))

    def _save_current_channel_config(self):
        checked = list(self.navigator.get_checked_channels())
        frozen_names = normalize_channel_names(row[1] for row in checked)
        if not frozen_names:
            return False
        bar = self.navigator.channel_list.config_bar
        pending = self.channel_config_store.get(bar.selected_config_id())
        default_name = pending.name if pending is not None else ""
        name, accepted = self._prompt_channel_config_name(
            default_name, len(frozen_names)
        )
        if not accepted:
            return False
        try:
            config = self.channel_config_store.create(name, frozen_names)
            action = "已保存"
        except ConfigNameConflict as conflict:
            existing = conflict.existing
            if not self._confirm_channel_config_overwrite(
                existing, len(frozen_names)
            ):
                return False
            config = self.channel_config_store.overwrite(
                existing.config_id, frozen_names
            )
            action = "已更新"
        except ValueError as exc:
            self.toast(str(exc), "warning")
            return False
        self._reload_channel_config_bar(config.config_id)
        self.toast(
            f"{action}配置“{config.name}” · {len(config.channel_names)} 个通道",
            "success",
        )
        return True

    def _prompt_channel_config_name(self, default_name, channel_count):
        return QInputDialog.getText(
            self,
            "保存通道配置",
            f"当前勾选 {channel_count} 个通道\n配置名称：",
            QLineEdit.Normal,
            default_name,
        )

    def _confirm_channel_config_overwrite(self, existing, new_count):
        box = QMessageBox(self)
        box.setWindowTitle("覆盖通道配置")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"配置“{existing.name}”已存在")
        box.setInformativeText(
            f"原 {len(existing.channel_names)} 个通道 → 新 {new_count} 个通道\n"
            "覆盖后无法从应用内撤销"
        )
        overwrite = box.addButton("覆盖配置", QMessageBox.AcceptRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        return box.clickedButton() is overwrite

    def _manage_channel_config(self, config_id=None):
        config = self.channel_config_store.get(config_id)
        if config is None:
            config = self._choose_channel_config_for_manage()
        if config is None:
            return False
        action = self._prompt_channel_config_manage_action(config)
        if action == "rename":
            name, accepted = self._prompt_channel_config_rename(config.name)
            if not accepted:
                return False
            try:
                renamed = self.channel_config_store.rename(config.config_id, name)
            except (ConfigNameConflict, ValueError) as exc:
                self.toast(str(exc), "warning")
                return False
            self._reload_channel_config_bar(renamed.config_id)
            self.toast(f"已重命名为“{renamed.name}”", "success")
            return True
        if action == "delete":
            if not self._confirm_channel_config_delete(config):
                return False
            self.channel_config_store.delete(config.config_id)
            self._reload_channel_config_bar()
            self.toast(f"已删除配置“{config.name}”", "info")
            return True
        return False

    def _choose_channel_config_for_manage(self):
        configs = self.channel_config_store.list()
        if not configs:
            self.toast("尚未保存通道配置", "info")
            return None
        labels = [config.name for config in configs]
        name, accepted = QInputDialog.getItem(
            self, "管理通道配置", "选择配置：", labels, 0, False
        )
        if not accepted:
            return None
        return next((config for config in configs if config.name == name), None)

    def _prompt_channel_config_manage_action(self, config):
        box = QMessageBox(self)
        box.setWindowTitle("管理通道配置")
        box.setText(f"配置“{config.name}” · {len(config.channel_names)} 个通道")
        rename = box.addButton("重命名", QMessageBox.ActionRole)
        delete = box.addButton("删除", QMessageBox.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        if box.clickedButton() is rename:
            return "rename"
        if box.clickedButton() is delete:
            return "delete"
        return "cancel"

    def _prompt_channel_config_rename(self, current_name):
        return QInputDialog.getText(
            self,
            "重命名通道配置",
            "配置名称：",
            QLineEdit.Normal,
            current_name,
        )

    def _confirm_channel_config_delete(self, config):
        box = QMessageBox(self)
        box.setWindowTitle("删除通道配置")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"删除配置“{config.name}”？")
        box.setInformativeText("删除后无法从应用内撤销")
        delete = box.addButton("删除配置", QMessageBox.DestructiveRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        return box.clickedButton() is delete

    def _apply_selected_channel_config(self, config_id):
        config = self.channel_config_store.get(config_id)
        resolved_view = self._focused_time_view_state()
        if config is None or resolved_view is None:
            self._reload_channel_config_bar()
            return False
        idx, state = resolved_view
        self._capture_focused_view()
        resolution = resolve_channel_config(
            config, state.attached_file_ids, self.files
        )
        if not resolution.matched:
            self.toast(
                f"配置“{config.name}”在当前 View 的已加入文件中没有匹配通道",
                "warning",
            )
            return False

        canvas = self._canvas_for_view_index(idx) or self.canvas_time
        mode = self.chart_stack.plot_mode_for_canvas(canvas)
        colors = self.navigator.get_channel_colors()
        rows = [
            (fid, channel, colors.get((fid, channel), "#1f77b4"))
            for fid, channel in resolution.matched
        ]
        risk = self._estimate_current_time_overlay_risk(mode, rows)
        if (
            risk.level is PlotRiskLevel.DANGER
            and not self._confirm_overlay_risk(risk)
        ):
            return False

        next_checked = list(resolution.matched)
        next_set = set(next_checked)
        state.checked = next_checked
        state.hidden_channels = [
            key for key in state.hidden_channels if key in next_set
        ]
        state.colors = {
            key: value for key, value in state.colors.items() if key in next_set
        }
        if state.overlay_primary not in next_set:
            state.overlay_primary = None
        self._project_view_controls(idx)
        self.navigator.channels_changed.emit()
        self.navigator.channel_list.config_bar.set_dirty(False)

        message = (
            f"已应用“{config.name}”：{resolution.target_file_count} 个文件，"
            f"匹配 {len(resolution.matched)} 个通道"
        )
        if resolution.missing_names:
            message += f"，缺失 {len(resolution.missing_names)} 个名称"
        self.toast(message, "success")
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
