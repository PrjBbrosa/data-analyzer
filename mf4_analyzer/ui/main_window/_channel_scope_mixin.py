"""Focused TimeDomain View file-attachment behavior."""
from __future__ import annotations

import json

from PyQt5.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from ...ui_kit.message_box_buttons import fit_message_box_buttons_to_text
from ..channel_config import (
    ChannelSelectionConfigStore,
    ConfigNameConflict,
    build_channel_config_preview,
    normalize_channel_names,
    resolve_channel_config,
)
from ..plot_risk import PlotRiskLevel
from ..time_xaxis import CustomXAxisSpec, EXACT_SOURCE
from ..widgets.channel_config_manager import ChannelConfigManagerDialog
from .file_scope_follow import (
    ATTACH_ON_LOAD_KEY,
    FollowPrefs,
    load_follow_prefs,
    save_follow_prefs,
)


# Compat alias — historical name used by docs / older patches.
AUTO_ATTACH_SETTINGS_KEY = ATTACH_ON_LOAD_KEY


class ChannelScopeMixin:
    """Own attachment mutations while the navigator remains a projection."""

    def _channel_scope_settings(self):
        from ..inspector_sections._helpers import _preset_settings

        return _preset_settings()

    def _init_channel_scope(self):
        # `_restoring_project` is ProjectIOMixin's guard; this mixin only reads
        # it (see `_on_source_load_finished`). Its default now lives with its
        # owner as a class attribute, so exactly one file writes it.
        prefs = load_follow_prefs(self._channel_scope_settings())
        self.navigator.set_follow_prefs(prefs)
        self.channel_config_store = ChannelSelectionConfigStore(
            self._channel_scope_settings()
        )
        self._reload_channel_config_bar()

    def _on_follow_prefs_changed(self, prefs):
        if not isinstance(prefs, FollowPrefs):
            prefs = FollowPrefs(
                attach_on_load=bool(getattr(prefs, "attach_on_load", True)),
                inherit_on_new_view=bool(
                    getattr(prefs, "inherit_on_new_view", False)
                ),
                fill_on_mode_entry=bool(
                    getattr(prefs, "fill_on_mode_entry", False)
                ),
            )
        save_follow_prefs(self._channel_scope_settings(), prefs)

    def _on_auto_attach_changed(self, enabled):
        """Item-1 shim: merge into full prefs and persist."""
        current = self.navigator.follow_prefs()
        self._on_follow_prefs_changed(
            FollowPrefs(
                attach_on_load=bool(enabled),
                inherit_on_new_view=current.inherit_on_new_view,
                fill_on_mode_entry=current.fill_on_mode_entry,
            )
        )

    def _focused_time_view_state(self):
        idx = getattr(self, "_focused_view_idx", None)
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return None
        return idx, self.view_manager.get(idx)

    def _attach_files_to_focused_view(self, fids):
        """Time-specific compatibility seam: attach into the focused Time View."""
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

    def _active_analysis_view_state(self, section=None):
        mode = section or self.chart_stack.current_mode()
        if mode not in self.analysis_managers:
            return None
        mgr = self.analysis_managers[mode]
        if not mgr.views:
            return None
        return mode, mgr, mgr.get(mgr.active)

    def _attach_files_to_active_analysis_view(self, section, fids):
        resolved = self._active_analysis_view_state(section)
        if resolved is None:
            return ()
        section, _mgr, state = resolved
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
        if self.chart_stack.current_mode() == section:
            self._project_analysis_attachments(section, state)
        self._refresh_analysis_candidates(section)
        return tuple(added)

    def _attach_files_to_active_context(self, fids):
        mode = self.chart_stack.current_mode()
        if mode == "time":
            return self._attach_files_to_focused_view(fids)
        if mode in self.analysis_managers:
            return self._attach_files_to_active_analysis_view(mode, fids)
        return ()

    def _toast_analysis_files_attached(self, section, state, added):
        """Shared success toast for analysis-side attach (drop / load / follow)."""
        label = self._analysis_section_label(section)
        self.toast(
            f"已加入 {label} · {state.name} · {len(added)} 个文件",
            "success",
        )

    def _attach_files_from_drop(self, fids):
        mode = self.chart_stack.current_mode()
        if mode == "time":
            resolved = self._focused_time_view_state()
            if resolved is None:
                self.toast("当前没有可接收文件的 TimeDomain View", "warning")
                return ()
            idx, state = resolved
            added = self._attach_files_to_focused_view(fids)
            if not added:
                self.toast(f"文件已在当前 View 中 · {state.name}", "info")
                return ()
            role = (
                "副栏"
                if idx == getattr(self, "_secondary_view_idx", None)
                else "主栏"
            )
            self.toast(
                f"已加入{role} · {state.name} · {len(added)} 个文件",
                "success",
            )
            return added

        resolved = self._active_analysis_view_state(mode)
        if resolved is None:
            self.toast("当前没有可接收文件的分析 View", "warning")
            return ()
        section, _mgr, state = resolved
        added = self._attach_files_to_active_analysis_view(section, fids)
        label = self._analysis_section_label(section)
        if not added:
            self.toast(
                f"文件已在 {label} · {state.name} 中",
                "info",
            )
            return ()
        self._toast_analysis_files_attached(section, state, added)
        return added

    def _on_source_load_finished(self, new_fids, *, notify=True):
        if (
            not new_fids
            or getattr(self, "_restoring_project", False)
            or not self.navigator.auto_attach_enabled()
        ):
            return ()
        # Stage 1.1 item 1: attach into the active focus context (time or
        # analysis), not always the time View. See
        # docs/analyzer/specs/2026-08-11-file-scope-follow-link-menu-spec.md.
        added = self._attach_files_to_active_context(new_fids)
        mode = self.chart_stack.current_mode()
        if added and notify and mode in self.analysis_managers:
            resolved = self._active_analysis_view_state(mode)
            if resolved is not None:
                section, _mgr, state = resolved
                self._toast_analysis_files_attached(section, state, added)
        return added

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

    def _confirm_analysis_detach(self, section, state, label, impact):
        from PyQt5.QtWidgets import QMessageBox

        if not impact.cleared_roles:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("从当前分析 View 移除")
        box.setIcon(QMessageBox.Question)
        section_label = self._analysis_section_label(section)
        shown_label = label or "所选文件"
        box.setText(
            f"从 {section_label} · {state.name} 移除“{shown_label}”后，"
            f"将清除 {len(impact.cleared_roles)} 个来源角色。是否继续？"
        )
        remove = box.addButton("从当前 View 移除", QMessageBox.AcceptRole)
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        return box.clickedButton() is remove

    def _detach_files_from_active_analysis_view(self, section, fids, label=""):
        from .analysis_source_scope import detach_analysis_files

        resolved = self._active_analysis_view_state(section)
        if resolved is None:
            return False
        section, _mgr, state = resolved
        if self.chart_stack.current_mode() == section:
            self._capture_active_analysis_view(section)
        attached = set(state.attached_file_ids)
        removing = tuple(
            fid
            for fid in dict.fromkeys(str(value) for value in (fids or ()))
            if fid in attached
        )
        if not removing:
            return False

        # Probe impact on a copy first so Cancel leaves state untouched.
        from copy import deepcopy
        from ..analysis_view_state import AnalysisViewState

        probe = AnalysisViewState.from_dict(deepcopy(state.to_dict()))
        impact = detach_analysis_files(probe, removing)
        if impact.cleared_roles and not self._confirm_analysis_detach(
            section, state, label, impact
        ):
            return False

        detach_analysis_files(state, removing)
        if self.chart_stack.current_mode() == section:
            self._project_analysis_attachments(section, state)
            self._apply_analysis_sources(section, state)
            # Keep the visible canvas aligned with Pane state. Empty sources
            # clear the chart via the shared cache-render path; sibling Views
            # and shared per-fid caches stay untouched.
            self._render_analysis_view_from_cache(section, state)
        self._refresh_analysis_candidates(section)
        # Local detach must NOT call _invalidate_all_analysis_caches_for_fid.
        shown_label = label or f"{len(removing)} 个文件"
        section_label = self._analysis_section_label(section)
        self.toast(
            f"已从 {section_label} · {state.name} 移除 {shown_label}",
            "info",
        )
        return True

    def _detach_files_from_active_context(self, fids, label=""):
        mode = self.chart_stack.current_mode()
        if mode == "time":
            return self._detach_files_from_focused_view(fids, label=label)
        if mode in self.analysis_managers:
            return self._detach_files_from_active_analysis_view(
                mode, fids, label=label
            )
        return False

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
        unit_hints = self._current_checked_channel_hints()
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
            config = self.channel_config_store.create(
                name, frozen_names, channel_unit_hints=unit_hints
            )
            action = "已保存"
        except ConfigNameConflict as conflict:
            existing = conflict.existing
            if not self._confirm_channel_config_overwrite(
                existing, len(frozen_names)
            ):
                return False
            config = self.channel_config_store.overwrite(
                existing.config_id, frozen_names, channel_unit_hints=unit_hints
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
        fit_message_box_buttons_to_text(box)
        box.exec_()
        return box.clickedButton() is overwrite

    def _manage_channel_config(self, config_id=None):
        resolved = self._focused_time_view_state()
        attached = () if resolved is None else resolved[1].attached_file_ids
        preview = build_channel_config_preview(attached, self.files)
        checked_hints = self._current_checked_channel_hints()
        dialog = ChannelConfigManagerDialog(
            self.channel_config_store.list(),
            selected_id=config_id,
            preview=preview,
            checked_channel_hints=checked_hints,
            id_factory=self.channel_config_store.new_draft_id,
            parent=self,
        )
        dialog.save_requested.connect(
            lambda drafts: self._save_channel_config_drafts(dialog, drafts)
        )
        dialog.exec_()

    def _current_checked_channel_hints(self):
        """Freeze the manager's New-config input without changing View state."""
        hints = {}
        for fid, channel, _color in self.navigator.get_checked_channels():
            name = str(channel)
            if name in hints:
                continue
            fd = self.files.get(str(fid))
            hints[name] = str(
                (getattr(fd, "channel_units", None) or {}).get(name, "")
                if fd is not None
                else ""
            )
        return hints

    def _save_channel_config_drafts(self, dialog, drafts):
        """Commit one complete manager snapshot; management never applies a View."""
        try:
            persisted = self.channel_config_store.commit_snapshot(drafts)
        except (ConfigNameConflict, ValueError, OSError) as exc:
            dialog._set_feedback(f"保存失败：{exc}", "warning")
            self.toast(f"通道配置未保存：{exc}", "warning")
            return False
        selected = dialog.active_config_id
        self._reload_channel_config_bar(selected)
        dialog.mark_saved(persisted, active_id=selected)
        self.toast(f"已保存 {len(persisted)} 个通道配置", "success")
        return True

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
        fit_message_box_buttons_to_text(box)
        box.exec_()
        return box.clickedButton() is remove

    def _time_view_ids_using_fids(self, fids):
        """View ids whose attachments or curve bindings still name these fids."""
        removed = {str(fid) for fid in fids or ()}
        if not removed:
            return ()
        found = []
        seen = set()
        for state in self.view_manager.views:
            view_id = str(getattr(state, "view_id", "") or "")
            if not view_id or view_id in seen:
                continue
            attached = {str(fid) for fid in (state.attached_file_ids or ())}
            if attached & removed:
                seen.add(view_id)
                found.append(view_id)
                continue
            for binding in getattr(state, "curve_bindings", None) or ():
                x_fid = str(getattr(getattr(binding, "x_ref", None), "fid", "") or "")
                y_fid = str(getattr(getattr(binding, "y_ref", None), "fid", "") or "")
                if x_fid in removed or y_fid in removed:
                    seen.add(view_id)
                    found.append(view_id)
                    break
        return tuple(found)

    def _remove_file_from_all_time_views(self, fid):
        removed = {str(fid)}
        for state in self.view_manager.views:
            self._filter_time_view_state_for_removed_fids(state, removed)

    def _remove_channels_from_all_time_views(self, fid, channels):
        """Drop deleted channel references from every persisted TimeDomain View."""
        removed = {(str(fid), str(channel)) for channel in channels or ()}
        if not removed:
            return
        for state in self.view_manager.views:
            self._filter_time_view_state_for_removed_channels(state, removed)

    def _remove_file_from_all_analysis_views(self, fid):
        from .analysis_source_scope import detach_analysis_files

        removed = (str(fid),)
        for manager in self.analysis_managers.values():
            for state in manager.views:
                detach_analysis_files(state, removed)

    def _remove_channels_from_all_analysis_views(self, fid, channels):
        removed = {
            (str(fid), str(channel)) for channel in channels or ()
        }
        if not removed:
            return
        for manager in self.analysis_managers.values():
            for state in manager.views:
                for pane in state.panes:
                    pane.sources = [
                        key for key in pane.sources
                        if (str(key[0]), str(key[1])) not in removed
                    ]
                    if pane.rpm_source and (
                        str(pane.rpm_source[0]), str(pane.rpm_source[1])
                    ) in removed:
                        pane.rpm_source = None
                    if (
                        pane.input_source and (
                            str(pane.input_source[0]), str(pane.input_source[1])
                        ) in removed
                    ) or (
                        pane.output_source and (
                            str(pane.output_source[0]), str(pane.output_source[1])
                        ) in removed
                    ):
                        pane.input_source = None
                        pane.output_source = None

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

        def _ylim_fid(key):
            # ylims are keyed by ``_view_state_channel_key`` JSON strings, not
            # ChannelKey tuples — decode before comparing against removed fids.
            try:
                decoded = json.loads(key)
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
            if isinstance(decoded, (list, tuple)) and len(decoded) == 2:
                return None if decoded[0] is None else str(decoded[0])
            return None

        state.ylims = {
            key: ylim
            for key, ylim in (state.ylims or {}).items()
            if (fid := _ylim_fid(key)) is not None and fid not in removed
        }
        if state.overlay_primary and str(state.overlay_primary[0]) in removed:
            state.overlay_primary = None
        axis_opts = dict(state.axis_opts or {})
        x_axis = dict(axis_opts.get("x_axis") or {})
        spec = CustomXAxisSpec.from_axis_opts(x_axis)
        if (
            spec.resolver == EXACT_SOURCE
            and spec.source_fid is not None
            and str(spec.source_fid) in removed
        ):
            axis_opts["x_axis"] = CustomXAxisSpec(label=spec.label).to_axis_opts()
        from ..time_curve_bindings import filter_curve_bindings, prune_hidden_curve_binding_ids
        state.curve_bindings = filter_curve_bindings(
            getattr(state, "curve_bindings", None) or [],
            removed_fids=removed,
        )
        state.hidden_curve_binding_ids = prune_hidden_curve_binding_ids(
            getattr(state, "hidden_curve_binding_ids", None),
            state.curve_bindings,
        )
        signature = axis_opts.get("frf_source_signature")
        if isinstance(signature, dict):
            endpoints = (signature.get("input"), signature.get("output"))
            if any(
                isinstance(source, (list, tuple))
                and len(source) == 2
                and str(source[0]) in removed
                for source in endpoints
            ):
                axis_opts.pop("frf_source_signature", None)
        state.axis_opts = axis_opts

    @staticmethod
    def _filter_time_view_state_for_removed_channels(state, removed):
        removed = {(str(fid), str(channel)) for fid, channel in removed}
        state.checked = [
            key for key in state.checked
            if (str(key[0]), str(key[1])) not in removed
        ]
        state.hidden_channels = [
            key for key in state.hidden_channels
            if (str(key[0]), str(key[1])) not in removed
        ]
        state.colors = {
            key: color
            for key, color in state.colors.items()
            if (str(key[0]), str(key[1])) not in removed
        }
        if state.overlay_primary and (
            str(state.overlay_primary[0]), str(state.overlay_primary[1])
        ) in removed:
            state.overlay_primary = None
        axis_opts = dict(state.axis_opts or {})
        x_axis = dict(axis_opts.get("x_axis") or {})
        spec = CustomXAxisSpec.from_axis_opts(x_axis)
        if (
            spec.resolver == EXACT_SOURCE
            and (str(spec.source_fid), str(spec.channel)) in removed
        ):
            axis_opts["x_axis"] = CustomXAxisSpec(label=spec.label).to_axis_opts()
        from ..time_curve_bindings import filter_curve_bindings, prune_hidden_curve_binding_ids
        state.curve_bindings = filter_curve_bindings(
            getattr(state, "curve_bindings", None) or [],
            removed_channels=removed,
        )
        state.hidden_curve_binding_ids = prune_hidden_curve_binding_ids(
            getattr(state, "hidden_curve_binding_ids", None),
            state.curve_bindings,
        )
        signature = axis_opts.get("frf_source_signature")
        if isinstance(signature, dict):
            endpoints = (signature.get("input"), signature.get("output"))
            if any(
                isinstance(source, (list, tuple))
                and len(source) == 2
                and (str(source[0]), str(source[1])) in removed
                for source in endpoints
            ):
                axis_opts.pop("frf_source_signature", None)
        state.axis_opts = axis_opts
